"""Minimal clangd-backed implementation of the semantic provider contract."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from types import TracebackType
from typing import Callable, NoReturn, Self
from urllib.parse import urlparse
from urllib.request import url2pathname

from arkui_agent.repository.model import (
    RepositoryFile,
    SourceLocation,
    SourceRange,
    Symbol,
    SymbolIdentity,
    SymbolKind,
)
from arkui_agent.repository.semantic import (
    SemanticProviderClosedError,
    SemanticProviderError,
)
from arkui_agent.repository.workspace import RepositoryWorkspace
from arkui_agent.repository.symbol_merge import SymbolObservation, canonicalize_symbols
from arkui_agent.repository.interrupts import defer_keyboard_interrupt


class ClangdUnavailableError(SemanticProviderError):
    """Raised when the configured clangd executable cannot be started."""


class ClangdProtocolError(SemanticProviderError):
    """Raised when clangd communication or a clangd request fails."""


class _RequestError(ClangdProtocolError):
    def __init__(self, method: str, code: int, message: str) -> None:
        super().__init__(f"clangd request {method!r} failed ({code}): {message}")
        self.code = code


class _JsonRpcTransport:
    """Synchronous JSON-RPC framing used only by the clangd adapter."""

    def __init__(
        self, process: subprocess.Popen[bytes], request_timeout: float
    ) -> None:
        if process.stdin is None or process.stdout is None:
            raise ClangdProtocolError("clangd was started without protocol pipes.")
        self._process = process
        self._stdin = process.stdin
        self._stdout = process.stdout
        self._next_request_id = 1
        self._request_timeout = request_timeout
        self.last_successful_operation = "none"
        self.last_completed_request = "none"
        self.operation = "none"
        self.write_count = 0
        self.request_count = 0
        self.open_count = 0
        self.stderr_tail = b""
        self._responses: Queue[dict[str, object] | Exception] = Queue()
        self._reader = Thread(target=self._drain_stdout, daemon=True)
        self._stderr_reader = Thread(target=self._drain_stderr, daemon=True)
        self._reader.start()
        self._stderr_reader.start()

    def _drain_stdout(self) -> None:
        try:
            while True:
                message = self._read()
                # Diagnostics/log notifications must not back up the output pipe
                # while the synchronous caller sends a document notification.
                if "id" in message:
                    self._responses.put(message)
        except (SemanticProviderError, OSError, ValueError) as error:
            self._responses.put(error)

    def _drain_stderr(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        try:
            while chunk := os.read(stream.fileno(), 4096):
                self.stderr_tail = (self.stderr_tail + chunk)[-8192:]
        except (OSError, ValueError):
            return  # Stream closure during bounded teardown.

    def diagnostic(self) -> str:
        # EOF can precede Windows process-signalling by a few milliseconds.
        try:
            self._process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            pass
        return (f"operation={self.operation}; last_success={self.last_successful_operation}; "
                f"last_completed_request={self.last_completed_request}; "
                f"exit_code={self._process.poll()!r}; requests_completed={self.request_count}; "
                f"requests_started={self._next_request_id - 1}; "
                f"writes_completed={self.write_count}; didOpen_completed={self.open_count}; "
                f"stderr_tail={self.stderr_tail.decode('utf-8', errors='replace')!r}")

    def request(self, method: str, params: object | None = None) -> object:
        request_id = self._next_request_id
        self._next_request_id += 1
        message: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        deadline = time.monotonic() + self._request_timeout
        self._write_with_timeout(message, self._request_timeout)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._raise_timeout(method)
            response = self._read_with_timeout(method, remaining)
            if "method" in response:
                if "id" in response:
                    requested_operation = self.operation
                    try:
                        self._answer_server_request(response)
                    finally:
                        self.operation = requested_operation
                continue
            if response.get("id") != request_id:
                continue
            error = response.get("error")
            if isinstance(error, dict):
                code = error.get("code", -32603)
                message_text = error.get("message", "unknown error")
                raise _RequestError(method, int(code), str(message_text) + "; " + self.diagnostic())
            self.request_count += 1
            self.last_successful_operation = self.operation + " response"
            self.last_completed_request = self.operation
            return response.get("result")

    def notify(self, method: str, params: object | None = None) -> None:
        message: dict[str, object] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._write_with_timeout(message, self._request_timeout)

    def _answer_server_request(self, request: dict[str, object]) -> None:
        method = request.get("method")
        if method == "workspace/configuration":
            params = request.get("params")
            items = params.get("items", []) if isinstance(params, dict) else []
            result: object = [None for _ in items] if isinstance(items, list) else []
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        elif method in {
            "client/registerCapability",
            "window/workDoneProgress/create",
        }:
            response = {"jsonrpc": "2.0", "id": request["id"], "result": None}
        else:
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": -32601, "message": "Method not supported"},
            }
        self._write_with_timeout(response, self._request_timeout)

    def _write_with_timeout(self, message: dict[str, object], timeout: float) -> None:
        params = message.get("params")
        document = params.get("textDocument", params.get("item", {})) if isinstance(params, dict) else {}
        uri = document.get("uri", "") if isinstance(document, dict) else ""
        self.operation = f"{message.get('method', 'server-response')} id={message.get('id')} file={uri}"
        result: Queue[Exception | None] = Queue(maxsize=1)

        def write_frame() -> None:
            try:
                self._write(message)
                result.put(None)
            except (SemanticProviderError, OSError, ValueError) as error:
                result.put(error)

        writer = Thread(target=write_frame, daemon=True)
        writer.start()
        try:
            error = result.get(timeout=timeout)
        except Empty as cause:
            try:
                self._raise_timeout(str(message.get("method", "response write")), cause)
            finally:
                writer.join(timeout=1)
        writer.join(timeout=1)
        if error is not None:
            self._stderr_reader.join(timeout=0.1)
            raise ClangdProtocolError(f"{error}; {self.diagnostic()}") from error
        self.write_count += 1
        self.open_count += message.get("method") == "textDocument/didOpen"
        self.last_successful_operation = self.operation + " write"

    def _write(self, message: dict[str, object]) -> None:
        if self._process.poll() is not None:
            raise ClangdProtocolError(
                f"clangd exited unexpectedly with code {self._process.returncode}."
            )
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        frame = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload
        try:
            self._stdin.write(frame)
            self._stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ClangdProtocolError(f"Failed to write to clangd: {exc!r}") from exc

    def _read(self) -> dict[str, object]:
        headers: dict[bytes, bytes] = {}
        try:
            while True:
                line = self._stdout.readline()
                if not line:
                    self._raise_eof()
                if line in {b"\r\n", b"\n"}:
                    break
                name, separator, value = line.partition(b":")
                if not separator:
                    raise ClangdProtocolError("Malformed clangd response header.")
                headers[name.strip().lower()] = value.strip()

            raw_length = headers.get(b"content-length")
            if raw_length is None:
                raise ClangdProtocolError("clangd response has no Content-Length.")
            length = int(raw_length)
            payload = self._stdout.read(length)
        except (OSError, ValueError) as exc:
            raise ClangdProtocolError("Failed to read a clangd response.") from exc
        if len(payload) != length:
            self._raise_eof()
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClangdProtocolError("clangd returned invalid JSON.") from exc
        if not isinstance(decoded, dict):
            raise ClangdProtocolError("clangd returned a non-object JSON-RPC message.")
        return decoded

    def _read_with_timeout(
        self, method: str, remaining: float
    ) -> dict[str, object]:
        try:
            response = self._responses.get(timeout=remaining)
        except Empty as exc:
            self._raise_timeout(method, exc)
        if isinstance(response, Exception):
            self._stderr_reader.join(timeout=0.1)
            raise ClangdProtocolError(f"{response}; {self.diagnostic()}") from response
        return response

    def _raise_timeout(
        self, method: str, cause: Exception | None = None
    ) -> NoReturn:
        self._abort_process()
        error = ClangdProtocolError(
            f"clangd request {method!r} timed out after "
            f"{self._request_timeout:g} seconds; {self.diagnostic()}"
        )
        if cause is None:
            raise error
        raise error from cause

    def _abort_process(self) -> None:
        if self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=1)

    def _raise_eof(self) -> NoReturn:
        raise ClangdProtocolError(
            f"clangd closed its output unexpectedly (exit code "
            f"{self._process.poll()!r})."
        )


@dataclass(frozen=True, slots=True)
class _SymbolHandle:
    symbol: Symbol
    uri: str
    position: dict[str, int]


_LSP_SYMBOL_KINDS: dict[int, SymbolKind] = {
    3: SymbolKind.NAMESPACE,
    5: SymbolKind.CLASS,
    6: SymbolKind.METHOD,
    8: SymbolKind.FIELD,
    9: SymbolKind.METHOD,
    10: SymbolKind.ENUM,
    12: SymbolKind.FUNCTION,
    22: SymbolKind.FIELD,
    23: SymbolKind.STRUCT,
}


class ClangdSemanticProvider:
    """A synchronous, read-only semantic provider backed by one clangd process."""

    MAX_OPEN_DOCUMENTS = 4

    def set_progress_observer(self, observer: Callable[[str, int, int, str | None], None]) -> None:
        """Optional public telemetry hook; never changes semantic query behavior."""
        self._progress_observer = observer
        self.progress_diagnostic: str | None = None

    def _report_progress(self, phase: str, current: int, total: int, file: str | None = None) -> None:
        observer = getattr(self, "_progress_observer", None)
        if observer is not None:
            try:
                observer(phase, current, total, file)
            except Exception as error:
                self.progress_diagnostic = "Semantic progress observer failed: " + str(error)[:300]

    def __init__(
        self,
        workspace: RepositoryWorkspace,
        *,
        executable: str | os.PathLike[str] = "clangd",
        compilation_database_directory: str | os.PathLike[str] | None = None,
        fallback_flags: tuple[str, ...] = (),
        request_timeout: float = 10.0,
    ) -> None:
        self._workspace = workspace
        self._process: subprocess.Popen[bytes] | None = None
        self._transport: _JsonRpcTransport | None = None
        self._closed = False
        self._opened_documents: set[str] = set()
        self._handles: dict[SymbolIdentity, _SymbolHandle] = {}
        self._observations: list[SymbolObservation] = []
        self.cleanup_diagnostics: tuple[str, ...] = ()
        self._position_encoding = "utf-16"
        self._supports_call_hierarchy = False
        self._semantic_stage = "initialize"
        self._prepared_files = 0
        self._collected_files = 0

        compilation_directory = _validate_compilation_database_directory(
            compilation_database_directory
        )
        validated_request_timeout = _validate_request_timeout(request_timeout)
        executable_path = shutil.which(os.fspath(executable))
        if executable_path is None:
            raise ClangdUnavailableError(
                f"clangd executable was not found: {os.fspath(executable)!r}"
            )
        command = [executable_path, "--log=error"]
        if compilation_directory is not None:
            command.append(f"--compile-commands-dir={compilation_directory}")

        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise ClangdUnavailableError(
                f"Unable to start clangd executable: {executable_path}"
            ) from exc

        self._transport = _JsonRpcTransport(
            self._process, validated_request_timeout
        )
        try:
            result = self._transport.request(
                "initialize",
                self._initialize_params(tuple(fallback_flags)),
            )
            capabilities = (
                result.get("capabilities", {}) if isinstance(result, dict) else {}
            )
            if isinstance(capabilities, dict):
                encoding = capabilities.get("positionEncoding")
                if encoding in {"utf-8", "utf-16", "utf-32"}:
                    self._position_encoding = str(encoding)
                self._supports_call_hierarchy = bool(
                    capabilities.get("callHierarchyProvider")
                )
            self._transport.notify("initialized", {})
        except BaseException as original:
            try:
                with defer_keyboard_interrupt(reraise=False):
                    self._terminate_process()
                    self._close_process_streams()
            except (OSError, subprocess.TimeoutExpired) as cleanup:
                original.add_note("clangd initialization cleanup failed: " + str(cleanup))
            self._closed = True
            raise

    @property
    def supports_call_hierarchy(self) -> bool:
        """Whether this clangd instance advertised call-hierarchy support."""

        return self._supports_call_hierarchy

    @property
    def is_closed(self) -> bool:
        return self._closed

    def symbols_in_file(self, file: RepositoryFile) -> tuple[Symbol, ...]:
        return tuple(f.symbol for f in self.symbol_observations_in_file(file))

    def symbol_observations_in_file(self, file: RepositoryFile) -> tuple[SymbolObservation, ...]:
        """Return local hierarchy facts with their actual semantic selection sites.

        Multi-file consumers can canonicalize the complete collection through
        canonicalize_symbols; no first-observed handle is used to select facts.
        """
        return self.symbol_observations_in_files((file,))

    def symbol_observations_in_files(self, files: tuple[RepositoryFile, ...]) -> tuple[SymbolObservation, ...]:
        """Prepare the entire fixed scope, then collect with bounded open ASTs.

        clangd retains its dynamic file index after didClose. The first pass
        establishes AST readiness across the scope; the second reopens documents
        as needed without discarding cross-file index knowledge or observations.
        """
        self._require_open()
        ordered = tuple(sorted(set(files), key=lambda f: f.path.as_posix()))
        self._semantic_stage = "prepare-scope"
        self._prepared_files = 0
        self._collected_files = 0
        if len(ordered) > self.MAX_OPEN_DOCUMENTS:
            self._report_progress("semantic_prepare", 0, len(ordered))
            for file in ordered:
                uri = self._open_document(file)
                result = self._request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
                if result is not None and not isinstance(result, list):
                    raise ClangdProtocolError(f"Invalid document symbols during scope preparation: {file.path}")
                self._prepared_files += 1
                self._report_progress("semantic_prepare", self._prepared_files, len(ordered), file.path.as_posix())
            self._semantic_stage = "collect-symbols"
            self._report_progress("semantic_collect", 0, len(ordered))
            symbols: list[SymbolObservation] = []
            for file in ordered:
                uri = self._open_document(file)
                result = self._request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
                if result is not None:
                    if not isinstance(result, list):
                        raise ClangdProtocolError("clangd returned invalid document symbols.")
                    self._collect_document_symbols(result, uri, symbols, None, None, "")
                self._collected_files += 1
                self._report_progress("semantic_collect", self._collected_files, len(ordered), file.path.as_posix())
            self._semantic_stage = "relations"
            return tuple(sorted(symbols, key=lambda f: _symbol_sort_key(f.symbol)))
        self._report_progress("semantic_prepare", 0, len(ordered))
        uris = tuple(self._open_document(file) for file in ordered)
        documents = []
        for uri in uris:
            result = self._request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
            self._prepared_files += 1
            self._report_progress("semantic_prepare", self._prepared_files, len(ordered),
                                  ordered[self._prepared_files - 1].path.as_posix())
            if result is None:
                result = []
            if not isinstance(result, list):
                raise ClangdProtocolError("clangd returned invalid document symbols.")
            documents.append((uri, result))
        # documentSymbol responses establish AST readiness for the entire scope
        # before any declaration/definition location query is collected.
        symbols: list[SymbolObservation] = []
        self._semantic_stage = "collect-symbols"
        self._report_progress("semantic_collect", 0, len(ordered))
        for uri, result in documents:
            self._collect_document_symbols(result, uri, symbols, None, None, "")
            self._collected_files += 1
            self._report_progress("semantic_collect", self._collected_files, len(ordered),
                                  ordered[self._collected_files - 1].path.as_posix())
        self._semantic_stage = "relations"
        return tuple(sorted(symbols, key=lambda f: _symbol_sort_key(f.symbol)))

    def declaration(self, identity: SymbolIdentity) -> SourceRange | None:
        handle = self._find_handle(identity)
        return None if handle is None else handle.symbol.declaration

    def definition(self, identity: SymbolIdentity) -> SourceRange | None:
        handle = self._find_handle(identity)
        return None if handle is None else handle.symbol.definition

    def references(self, identity: SymbolIdentity) -> tuple[SourceRange, ...]:
        handle = self._find_handle(identity)
        if handle is None:
            return ()
        result = self._request(
            "textDocument/references",
            {
                "textDocument": {"uri": handle.uri},
                "position": handle.position,
                "context": {"includeDeclaration": False},
            },
        )
        return self._convert_locations(result, "references")

    def callers(self, identity: SymbolIdentity) -> tuple[Symbol, ...]:
        handle = self._find_handle(identity)
        if handle is None:
            return ()
        items = self._call_hierarchy_items(handle, "callHierarchy/incomingCalls", "from")
        return self._symbols_from_call_hierarchy(items, "callHierarchy/incomingCalls")

    def callees(self, identity: SymbolIdentity) -> tuple[Symbol, ...]:
        handle = self._find_handle(identity)
        if handle is None:
            return ()
        items = self._call_hierarchy_items(handle, "callHierarchy/outgoingCalls", "to")
        return self._symbols_from_call_hierarchy(items, "callHierarchy/outgoingCalls")

    def close(self) -> None:
        with defer_keyboard_interrupt():
            self._close_owned()

    def _close_owned(self) -> None:
        if self._closed:
            return
        self._closed = True
        transport = self._transport
        process = self._process
        if transport is None or process is None:
            return

        errors: list[str] = []

        def shutdown() -> None:
            try:
                # Process exit closes all documents. A didClose flood can fill
                # both pipes while clangd publishes diagnostics during teardown.
                if process.poll() is None:
                    transport.request("shutdown")
                    transport.notify("exit")
                    process.wait(timeout=1)
            except (SemanticProviderError, OSError, ValueError, subprocess.TimeoutExpired) as error:
                errors.append(str(error))

        worker = Thread(target=shutdown, daemon=True)
        worker.start()
        worker.join(timeout=2)
        if worker.is_alive():
            errors.append("clangd graceful shutdown exceeded 2 seconds; terminating owned process")
        try:
            self._terminate_process()
        finally:
            worker.join(timeout=2)
            self.cleanup_diagnostics = tuple(errors)
        if worker.is_alive():
            raise ClangdProtocolError("clangd shutdown worker did not stop after process termination")
        self._close_process_streams()

    def __enter__(self) -> Self:
        self._require_open()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.close()
        except (SemanticProviderError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
            if exception is None:
                raise
            exception.add_note("clangd cleanup failed: " + str(error))
        if exception is not None:
            for diagnostic in self.cleanup_diagnostics:
                exception.add_note("clangd cleanup: " + diagnostic)

    def symbol_observations(self) -> tuple[SymbolObservation, ...]:
        """Lossless audit of converted document and related endpoint records."""
        return tuple(sorted(set(self._observations), key=repr))

    def _initialize_params(self, fallback_flags: tuple[str, ...]) -> dict[str, object]:
        root_uri = self._workspace.root.as_uri()
        params: dict[str, object] = {
            "processId": os.getpid(),
            "rootUri": root_uri,
            "workspaceFolders": [
                {"uri": root_uri, "name": self._workspace.root.name}
            ],
            "capabilities": {
                "general": {"positionEncodings": ["utf-8", "utf-16"]},
                "textDocument": {
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                    "callHierarchy": {},
                },
            },
        }
        if fallback_flags:
            params["initializationOptions"] = {"fallbackFlags": list(fallback_flags)}
        return params

    def _open_document(self, file: RepositoryFile) -> str:
        path = self._workspace.resolve(file.path.as_posix())
        if not path.is_file():
            raise SemanticProviderError(
                f"Repository file does not exist or is not a file: {file.path}"
            )
        uri = path.as_uri()
        if uri in self._opened_documents:
            return uri
        if len(self._opened_documents) >= self.MAX_OPEN_DOCUMENTS:
            evicted = min(self._opened_documents)
            self._notify("textDocument/didClose", {"textDocument": {"uri": evicted}})
            self._opened_documents.remove(evicted)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SemanticProviderError(
                f"Unable to read repository file as UTF-8: {file.path}"
            ) from exc
        self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": _language_id(path),
                    "version": 1,
                    "text": text,
                }
            },
        )
        self._opened_documents.add(uri)
        return uri

    def _collect_document_symbols(
        self,
        items: list[object],
        uri: str,
        output: list[SymbolObservation],
        parent_identity: SymbolIdentity | None,
        namespace_identity: SymbolIdentity | None,
        container_name: str,
        parent_kind: SymbolKind | None = None,
    ) -> None:
        for item in items:
            if not isinstance(item, dict):
                raise ClangdProtocolError("clangd returned an invalid document symbol.")
            kind = _LSP_SYMBOL_KINDS.get(item.get("kind"))
            name = item.get("name")
            selection = item.get("selectionRange")
            source_range = item.get("range")
            if kind is None or not isinstance(name, str):
                continue
            if not isinstance(selection, dict) or not isinstance(source_range, dict):
                raise ClangdProtocolError("clangd document symbol has no valid range.")
            position = _lsp_position(selection.get("start"))
            symbol_info = self._symbol_info(uri, position, expected_name=name, expected_kind=kind)
            evidence = self._last_identity_query
            qualified_name = _qualified_name(symbol_info, container_name, name)
            identity_key = _identity_key(
                symbol_info, kind, qualified_name, uri, position
            )
            identity = _opaque_symbol_identity(identity_key)
            fallback_range = _lsp_range_to_source_range(
                self._workspace, uri, source_range, self._position_encoding
            )
            if fallback_range is None:
                continue
            declaration = self._symbol_info_range(
                symbol_info, "declarationRange"
            ) or self._location_query(
                "textDocument/declaration", uri, position
            )
            definition = self._symbol_info_range(
                symbol_info, "definitionRange"
            ) or self._location_query("textDocument/definition", uri, position)
            if declaration is None and definition is None:
                declaration = fallback_range
            symbol = Symbol(
                identity=identity,
                kind=kind,
                display_name=name,
                qualified_name=qualified_name,
                declaration=declaration,
                definition=definition,
                parent_identity=parent_identity,
                namespace_identity=(
                    identity if kind is SymbolKind.NAMESPACE else namespace_identity
                ),
            )
            site = _lsp_range_to_source_range(self._workspace, uri, selection, self._position_encoding)
            if site is None:
                raise ClangdProtocolError("Document symbol selection is outside the repository.")
            observation = SymbolObservation(symbol, site, parent_kind, json.dumps({
                "endpoint": "textDocument/documentSymbol", "item": item,
                "symbol_info": evidence, "identity_key": identity_key,
            }, sort_keys=True))
            output.append(observation)
            self._observations.append(observation)
            self._handles.setdefault(identity, _SymbolHandle(symbol, uri, position))

            children = item.get("children", [])
            if isinstance(children, list):
                self._collect_document_symbols(
                    children,
                    uri,
                    output,
                    identity,
                    identity if kind is SymbolKind.NAMESPACE else namespace_identity,
                    qualified_name,
                    kind,
                )

    def _symbol_info(self, uri: str, position: dict[str, int], *,
                     expected_name: str, expected_id: str | None = None,
                     expected_kind: SymbolKind | None = None) -> dict[str, object] | None:
        try:
            result = self._request(
                "textDocument/symbolInfo",
                {"textDocument": {"uri": uri}, "position": position},
            )
        except _RequestError as exc:
            if exc.code == -32601:
                result = None
            else:
                raise
        self._last_identity_query = {"endpoint": "textDocument/symbolInfo", "uri": uri,
                                     "position": position, "payload": result,
                                     "expected_name": expected_name, "expected_id": expected_id}
        try:
            return _select_symbol_info(result, expected_name, expected_id, expected_kind)
        except ClangdProtocolError as error:
            raise ClangdProtocolError(str(error) + "; identity provenance=" +
                                     json.dumps(self._last_identity_query, sort_keys=True)) from error

    def _symbol_info_range(
        self, symbol_info: dict[str, object] | None, field: str
    ) -> SourceRange | None:
        return _symbol_info_location_to_range(
            self._workspace,
            symbol_info,
            field,
            self._position_encoding,
        )

    def _location_query(
        self, method: str, uri: str, position: dict[str, int]
    ) -> SourceRange | None:
        result = self._request(
            method, {"textDocument": {"uri": uri}, "position": position}
        )
        locations = self._convert_locations(result, method)
        return locations[0] if locations else None

    def _convert_locations(self, result: object, operation: str) -> tuple[SourceRange, ...]:
        if result is None:
            return ()
        raw_locations = result if isinstance(result, list) else [result]
        converted: set[SourceRange] = set()
        for location in raw_locations:
            if not isinstance(location, dict):
                raise ClangdProtocolError(f"clangd returned invalid {operation} data.")
            uri = location.get("uri", location.get("targetUri"))
            range_data = location.get("range", location.get("targetRange"))
            if not isinstance(uri, str) or not isinstance(range_data, dict):
                raise ClangdProtocolError(f"clangd returned invalid {operation} location.")
            source_range = _lsp_range_to_source_range(
                self._workspace, uri, range_data, self._position_encoding
            )
            if source_range is not None:
                converted.add(source_range)
        return tuple(sorted(converted, key=_range_sort_key))

    def _call_hierarchy_items(
        self, handle: _SymbolHandle, method: str, result_key: str
    ) -> tuple[dict[str, object], ...]:
        if not self._supports_call_hierarchy:
            return ()
        try:
            prepared = self._request(
                "textDocument/prepareCallHierarchy",
                {
                    "textDocument": {"uri": handle.uri},
                    "position": handle.position,
                },
            )
            if (
                not isinstance(prepared, list)
                or not prepared
                or not isinstance(prepared[0], dict)
            ):
                return ()
            matching = [item for item in prepared if isinstance(item, dict)
                        and _clangd_id(item.get("data")) is not None
                        and _opaque_symbol_identity("clangd-id\0" + _clangd_id(item.get("data")))
                        == handle.symbol.identity]
            if len(matching) != 1:
                raise ClangdProtocolError("prepareCallHierarchy did not uniquely identify the requested symbol")
            calls = self._request(method, {"item": matching[0]})
        except _RequestError as exc:
            if exc.code == -32601:
                self._supports_call_hierarchy = False
                return ()
            raise
        if calls is None:
            return ()
        if not isinstance(calls, list):
            raise ClangdProtocolError("clangd returned invalid call hierarchy data.")
        items: list[dict[str, object]] = []
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get(result_key), dict):
                raise ClangdProtocolError("clangd returned an invalid call hierarchy item.")
            items.append(call[result_key])
        return tuple(items)

    def _symbols_from_call_hierarchy(
        self, items: tuple[dict[str, object], ...], endpoint: str = "callHierarchy"
    ) -> tuple[Symbol, ...]:
        observations = []
        for item in items:
            symbol = self._call_hierarchy_symbol(item, endpoint)
            if symbol is not None:
                observations.append(SymbolObservation(symbol))
        return tuple(sorted(canonicalize_symbols(observations), key=_symbol_sort_key))

    def _call_hierarchy_symbol(self, item: dict[str, object], endpoint: str = "callHierarchy") -> Symbol | None:
        uri = item.get("uri")
        name = item.get("name")
        kind = _LSP_SYMBOL_KINDS.get(item.get("kind"))
        selection = item.get("selectionRange")
        item_range = item.get("range")
        if (
            not isinstance(uri, str)
            or not isinstance(name, str)
            or kind is None
            or not isinstance(selection, dict)
            or not isinstance(item_range, dict)
        ):
            raise ClangdProtocolError("clangd returned an invalid call hierarchy symbol.")
        repository_file = _repository_file_from_uri(self._workspace, uri)
        if repository_file is None:
            return None
        uri = self._open_document(repository_file)
        fallback_range = _lsp_range_to_source_range(
            self._workspace, uri, item_range, self._position_encoding
        )
        if fallback_range is None:
            return None
        position = _lsp_position(selection.get("start"))
        backend_id = _clangd_id(item.get("data"))
        info = self._symbol_info(uri, position, expected_name=name, expected_id=backend_id, expected_kind=kind)
        detail = item.get("detail")
        qualified_name = _qualified_name(info, "", name) if info else (
            detail if isinstance(detail, str) and detail else name
        )
        identity_key = _identity_key({"id": backend_id} if backend_id else info,
                                     kind, qualified_name, uri, position)
        identity = _opaque_symbol_identity(identity_key)
        # A macro expansion selection may resolve to its enclosing class/macro.
        # Only matching identity evidence can contribute location/name facts.
        declaration = self._symbol_info_range(info, "declarationRange")
        definition = self._symbol_info_range(info, "definitionRange")
        if info is not None:
            declaration = declaration or self._location_query("textDocument/declaration", uri, position)
            definition = definition or self._location_query("textDocument/definition", uri, position)
        if declaration is None and definition is None:
            declaration = fallback_range  # call item guarantees a symbol location, not a definition
        symbol = Symbol(
            identity=identity,
            kind=kind,
            display_name=name,
            qualified_name=qualified_name,
            declaration=declaration,
            definition=definition,
        )
        self._observations.append(SymbolObservation(symbol, provenance=json.dumps({
            "endpoint": endpoint, "item": item, "symbol_info": self._last_identity_query,
            "identity_key": identity_key,
        }, sort_keys=True)))
        self._handles.setdefault(identity, _SymbolHandle(symbol, uri, position))
        return symbol

    def _find_handle(self, identity: SymbolIdentity) -> _SymbolHandle | None:
        self._require_open()
        return self._handles.get(identity)

    def _request(self, method: str, params: object | None = None) -> object:
        self._require_open()
        if self._transport is None:
            raise ClangdProtocolError("clangd transport is unavailable.")
        document = params.get("textDocument", params.get("item", {})) if isinstance(params, dict) else {}
        uri = document.get("uri") if isinstance(document, dict) else None
        if isinstance(uri, str) and uri not in self._opened_documents:
            file = _repository_file_from_uri(self._workspace, uri)
            if file is not None:
                self._open_document(file)
        try:
            return self._transport.request(method, params)
        except ClangdProtocolError as error:
            # Preserve _RequestError type: callers negotiate unsupported methods.
            if isinstance(error, _RequestError):
                error.args = (f"{self._progress()}; {error}; request_file={uri}",)
                raise
            raise ClangdProtocolError(f"{self._progress()}; {error}") from error

    def _notify(self, method: str, params: object | None = None) -> None:
        self._require_open()
        if self._transport is None:
            raise ClangdProtocolError("clangd transport is unavailable.")
        try:
            self._transport.notify(method, params)
        except ClangdProtocolError as error:
            raise ClangdProtocolError(f"{self._progress()}; {error}") from error

    def _progress(self) -> str:
        return (f"stage={self._semantic_stage}; prepared_files={self._prepared_files}; "
                f"collected_files={self._collected_files}; open_documents={len(self._opened_documents)}; "
                f"open_limit={self.MAX_OPEN_DOCUMENTS}")

    def _require_open(self) -> None:
        if self._closed:
            raise SemanticProviderClosedError("Semantic provider is closed.")

    def _terminate_process(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _close_process_streams(self) -> None:
        process = self._process
        if process is None:
            return
        if self._transport is not None:
            self._transport._reader.join(timeout=1)
            self._transport._stderr_reader.join(timeout=1)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass


def _validate_compilation_database_directory(
    directory: str | os.PathLike[str] | None,
) -> Path | None:
    if directory is None:
        return None
    path = Path(directory).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SemanticProviderError(
            f"Compilation database directory does not exist: {directory!s}"
        ) from exc
    if not resolved.is_dir():
        raise SemanticProviderError(
            f"Compilation database path is not a directory: {directory!s}"
        )
    return resolved


def _validate_request_timeout(request_timeout: float) -> float:
    try:
        timeout = float(request_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("clangd request timeout must be a number.") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("clangd request timeout must be finite and greater than zero.")
    return timeout


def _language_id(path: Path) -> str:
    return "c" if path.suffix.lower() == ".c" else "cpp"


def _lsp_position(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ClangdProtocolError("clangd returned an invalid source position.")
    line = value.get("line")
    character = value.get("character")
    if (
        not isinstance(line, int)
        or not isinstance(character, int)
        or line < 0
        or character < 0
    ):
        raise ClangdProtocolError("clangd returned an invalid source position.")
    return {"line": line, "character": character}


def _lsp_range_to_source_range(
    workspace: RepositoryWorkspace,
    uri: str,
    value: dict[str, object],
    position_encoding: str = "utf-16",
) -> SourceRange | None:
    """Convert one LSP range into the repository model at the adapter boundary."""

    repository_file = _repository_file_from_uri(workspace, uri)
    if repository_file is None:
        return None
    file_path = workspace.resolve(repository_file.path.as_posix())
    start = _lsp_position(value.get("start"))
    end = _lsp_position(value.get("end"))
    lines = _read_source_lines(file_path)
    return SourceRange(
        start=SourceLocation(
            repository_file,
            start["line"] + 1,
            _model_column(lines, start, position_encoding),
        ),
        end=SourceLocation(
            repository_file,
            end["line"] + 1,
            _model_column(lines, end, position_encoding),
        ),
    )


def _symbol_info_location_to_range(
    workspace: RepositoryWorkspace,
    symbol_info: dict[str, object] | None,
    field: str,
    position_encoding: str,
) -> SourceRange | None:
    if symbol_info is None:
        return None
    location = symbol_info.get(field)
    if not isinstance(location, dict):
        return None
    uri = location.get("uri")
    range_data = location.get("range")
    if not isinstance(uri, str) or not isinstance(range_data, dict):
        raise ClangdProtocolError(
            f"clangd symbolInfo returned invalid {field} data."
        )
    return _lsp_range_to_source_range(
        workspace, uri, range_data, position_encoding
    )


def _repository_file_from_uri(
    workspace: RepositoryWorkspace, uri: str
) -> RepositoryFile | None:
    file_path = _file_uri_to_path(uri)
    try:
        relative_path = file_path.resolve(strict=False).relative_to(workspace.root)
    except (OSError, RuntimeError, ValueError):
        return None
    return RepositoryFile.from_path(relative_path.as_posix())


def _file_uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ClangdProtocolError(f"clangd returned an unsupported URI: {uri!r}")
    path = url2pathname(parsed.path)
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    return Path(path)


def _read_source_lines(path: Path) -> tuple[str, ...]:
    try:
        return tuple(path.read_text(encoding="utf-8").splitlines(keepends=True))
    except (OSError, UnicodeError) as exc:
        raise ClangdProtocolError(
            f"Unable to read source file for position conversion: {path}"
        ) from exc


def _model_column(
    lines: tuple[str, ...], position: dict[str, int], position_encoding: str
) -> int:
    line_number = position["line"]
    offset = position["character"]
    if line_number >= len(lines):
        return offset + 1
    line = lines[line_number].rstrip("\r\n")
    if position_encoding == "utf-8":
        prefix = line.encode("utf-8")[:offset]
        return len(prefix.decode("utf-8", errors="ignore")) + 1
    if position_encoding == "utf-16":
        units = 0
        characters = 0
        for character in line:
            width = len(character.encode("utf-16-le")) // 2
            if units + width > offset:
                break
            units += width
            characters += 1
        return characters + 1
    return min(offset, len(line)) + 1


def _qualified_name(
    symbol_info: dict[str, object] | None, container_name: str, name: str
) -> str:
    if symbol_info is not None:
        info_name = symbol_info.get("name")
        info_container = symbol_info.get("containerName")
        if isinstance(info_name, str) and info_name:
            name = info_name
        if isinstance(info_container, str) and info_container:
            return f"{info_container.rstrip(':')}::{name}"
    return f"{container_name}::{name}" if container_name else name


def _identity_key(
    symbol_info: dict[str, object] | None,
    kind: SymbolKind,
    qualified_name: str,
    uri: str,
    position: dict[str, int],
) -> str:
    if symbol_info is not None:
        clangd_id = _symbol_info_id(symbol_info)
        if clangd_id:
            return f"clangd-id\0{clangd_id}"
    return (
        f"source-anchor\0{kind.value}\0{qualified_name}\0{uri}\0"
        f"{position['line']}\0{position['character']}"
    )


def _clangd_id(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or re.fullmatch(r"[0-9A-Fa-f]{16}", value) is None:
        raise ClangdProtocolError("Unsupported clangd SymbolID payload")
    return value.upper()


def _symbol_info_id(info: dict[str, object]) -> str | None:
    backend_id = _clangd_id(info.get("id"))
    usr = info.get("usr")
    derived = hashlib.sha1(usr.encode("utf-8")).hexdigest()[:16].upper() if isinstance(usr, str) and usr else None
    if backend_id and derived and backend_id != derived:
        raise ClangdProtocolError("clangd symbolInfo id contradicts its USR")
    return backend_id or derived


def _select_symbol_info(result: object, name: str, backend_id: str | None,
                        kind: SymbolKind | None = None) -> dict[str, object] | None:
    if result is None or result == []:
        return None
    if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
        raise ClangdProtocolError("Invalid clangd symbolInfo payload")
    matches = []
    for item in result:
        item_name = item.get("name")
        name_matches = isinstance(item_name, str) and (name == item_name or name.endswith("::" + item_name))
        if kind is SymbolKind.NAMESPACE and name == "(anonymous namespace)" and item_name == "(anonymous)":
            name_matches = True  # clangd's document-vs-symbolInfo display spelling
        if backend_id is not None:
            if _symbol_info_id(item) != backend_id:
                continue
            if not name_matches:
                raise ClangdProtocolError("Matching clangd SymbolID has contradictory symbol name")
        elif not name_matches:
            continue
        if item not in matches:
            matches.append(item)
    if len(matches) > 1:
        raise ClangdProtocolError("Ambiguous clangd symbolInfo identity evidence")
    if not matches and backend_id is None:
        raise ClangdProtocolError("symbolInfo resolves another symbol; no independent endpoint identity")
    return matches[0] if matches else None


def _opaque_symbol_identity(key: str) -> SymbolIdentity:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return SymbolIdentity(f"symbol:{digest}")


def _range_sort_key(source_range: SourceRange) -> tuple[object, ...]:
    return (
        source_range.file.path.as_posix(),
        source_range.start.line,
        source_range.start.column,
        source_range.end.line,
        source_range.end.column,
    )


def _symbol_sort_key(symbol: Symbol) -> tuple[object, ...]:
    source_range = symbol.declaration or symbol.definition
    assert source_range is not None
    return (*_range_sort_key(source_range), symbol.qualified_name, symbol.identity.value)
