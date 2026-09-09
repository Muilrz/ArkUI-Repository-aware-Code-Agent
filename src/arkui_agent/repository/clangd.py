"""Minimal clangd-backed implementation of the semantic provider contract."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from types import TracebackType
from typing import NoReturn, Self
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
from arkui_agent.repository.symbol_merge import SymbolObservation


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
        self._write(message)
        deadline = time.monotonic() + self._request_timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._raise_timeout(method)
            response = self._read_with_timeout(method, remaining)
            if "method" in response:
                if "id" in response:
                    self._answer_server_request(response)
                continue
            if response.get("id") != request_id:
                continue
            error = response.get("error")
            if isinstance(error, dict):
                code = error.get("code", -32603)
                message_text = error.get("message", "unknown error")
                raise _RequestError(method, int(code), str(message_text))
            return response.get("result")

    def notify(self, method: str, params: object | None = None) -> None:
        message: dict[str, object] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._write(message)

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
        self._write(response)

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
            raise ClangdProtocolError("Failed to write to clangd.") from exc

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
        result: Queue[dict[str, object] | Exception] = Queue(maxsize=1)

        def read_one_message() -> None:
            try:
                result.put(self._read())
            except Exception as exc:
                result.put(exc)

        reader = Thread(target=read_one_message, daemon=True)
        reader.start()
        try:
            response = result.get(timeout=remaining)
        except Empty as exc:
            self._raise_timeout(method, exc)
        if isinstance(response, Exception):
            raise response
        return response

    def _raise_timeout(
        self, method: str, cause: Exception | None = None
    ) -> NoReturn:
        self._abort_process()
        error = ClangdProtocolError(
            f"clangd request {method!r} timed out after "
            f"{self._request_timeout:g} seconds."
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
        self._position_encoding = "utf-16"
        self._supports_call_hierarchy = False

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
                stderr=subprocess.DEVNULL,
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
        except BaseException:
            self._terminate_process()
            self._close_process_streams()
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
        """Collect a fixed scope after every requested document has been parsed.

        Do not mix early header-only location queries with later observations
        made after opening the definition translation unit. This is a bounded
        preparation barrier, not polling, retries or selection of winning facts.
        """
        self._require_open()
        uris = tuple(self._open_document(file) for file in sorted(set(files), key=lambda f: f.path.as_posix()))
        documents = []
        for uri in uris:
            result = self._request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
            if result is None:
                continue
            if not isinstance(result, list):
                raise ClangdProtocolError("clangd returned invalid document symbols.")
            documents.append((uri, result))
        # documentSymbol responses establish AST readiness for the entire scope
        # before any declaration/definition location query is collected.
        symbols: list[SymbolObservation] = []
        for uri, result in documents:
            self._collect_document_symbols(result, uri, symbols, None, None, "")
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
        return self._symbols_from_call_hierarchy(items)

    def callees(self, identity: SymbolIdentity) -> tuple[Symbol, ...]:
        handle = self._find_handle(identity)
        if handle is None:
            return ()
        items = self._call_hierarchy_items(handle, "callHierarchy/outgoingCalls", "to")
        return self._symbols_from_call_hierarchy(items)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        transport = self._transport
        process = self._process
        if transport is None or process is None:
            return

        try:
            for uri in sorted(self._opened_documents):
                transport.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
            transport.request("shutdown")
            transport.notify("exit")
            process.wait(timeout=5)
        except (SemanticProviderError, subprocess.TimeoutExpired):
            self._terminate_process()
        finally:
            self._terminate_process()
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
        self.close()

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
            symbol_info = self._symbol_info(uri, position)
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
            output.append(SymbolObservation(symbol, site, parent_kind))
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

    def _symbol_info(self, uri: str, position: dict[str, int]) -> dict[str, object] | None:
        try:
            result = self._request(
                "textDocument/symbolInfo",
                {"textDocument": {"uri": uri}, "position": position},
            )
        except _RequestError as exc:
            if exc.code == -32601:
                return None
            raise
        if not isinstance(result, list) or not result or not isinstance(result[0], dict):
            return None
        return result[0]

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
            calls = self._request(method, {"item": prepared[0]})
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
        self, items: tuple[dict[str, object], ...]
    ) -> tuple[Symbol, ...]:
        symbols: dict[SymbolIdentity, Symbol] = {}
        for item in items:
            symbol = self._call_hierarchy_symbol(item)
            if symbol is not None:
                symbols[symbol.identity] = symbol
        return tuple(sorted(symbols.values(), key=_symbol_sort_key))

    def _call_hierarchy_symbol(self, item: dict[str, object]) -> Symbol | None:
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
        info = self._symbol_info(uri, position)
        qualified_name = _qualified_name(info, "", name)
        identity = _opaque_symbol_identity(
            _identity_key(info, kind, qualified_name, uri, position)
        )
        declaration = self._symbol_info_range(
            info, "declarationRange"
        ) or self._location_query("textDocument/declaration", uri, position)
        definition = self._symbol_info_range(
            info, "definitionRange"
        ) or self._location_query("textDocument/definition", uri, position)
        if declaration is None and definition is None:
            definition = fallback_range
        symbol = Symbol(
            identity=identity,
            kind=kind,
            display_name=name,
            qualified_name=qualified_name,
            declaration=declaration,
            definition=definition,
        )
        self._handles.setdefault(identity, _SymbolHandle(symbol, uri, position))
        return symbol

    def _find_handle(self, identity: SymbolIdentity) -> _SymbolHandle | None:
        self._require_open()
        return self._handles.get(identity)

    def _request(self, method: str, params: object | None = None) -> object:
        self._require_open()
        if self._transport is None:
            raise ClangdProtocolError("clangd transport is unavailable.")
        return self._transport.request(method, params)

    def _notify(self, method: str, params: object | None = None) -> None:
        self._require_open()
        if self._transport is None:
            raise ClangdProtocolError("clangd transport is unavailable.")
        self._transport.notify(method, params)

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
        usr = symbol_info.get("usr")
        if isinstance(usr, str) and usr:
            return f"usr\0{usr}"
        clangd_id = symbol_info.get("id")
        if isinstance(clangd_id, str) and clangd_id:
            return f"clangd-id\0{clangd_id}"
    return (
        f"source-anchor\0{kind.value}\0{qualified_name}\0{uri}\0"
        f"{position['line']}\0{position['character']}"
    )


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
