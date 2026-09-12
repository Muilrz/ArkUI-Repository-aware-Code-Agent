"""Compiler-derived translation-unit dependency impact contracts.

This module owns only F1 change/compile/dependency analysis.  It does not
invoke a semantic producer, mutate an index, project a graph, or publish a
knowledge snapshot.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Protocol

from .model import RepositoryFile
from .workspace import RepositoryWorkspace


_TU_EXTENSIONS = frozenset({".c", ".cc", ".cpp", ".cxx", ".m", ".mm"})
_HEADER_EXTENSIONS = frozenset({".h", ".hh", ".hpp", ".hxx", ".inc"})


class ChangeKind(str, Enum):
    MODIFY = "modify"
    ADD = "add"
    DELETE = "delete"
    RENAME = "rename"


class CoverageStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ImpactStatus(str, Enum):
    SAFE_INCREMENTAL = "safe_incremental"
    UNKNOWN = "unknown"
    FULL_REBUILD_REQUIRED = "full_rebuild_required"


class DiagnosticCode(str, Enum):
    MISSING_COMPILE_METADATA = "missing_compile_metadata"
    MALFORMED_METADATA = "malformed_metadata"
    MISSING_COMPILE_CONTEXT = "missing_compile_context"
    MISSING_DEPENDENCY_METADATA = "missing_dependency_metadata"
    UNKNOWN_HEADER_IMPACT = "unknown_header_impact"
    OUTSIDE_REPOSITORY_DEPENDENCY = "outside_repository_dependency"
    UNSUPPORTED_CHANGED_FILE = "unsupported_changed_file"


@dataclass(frozen=True, slots=True)
class ImpactDiagnostic:
    code: DiagnosticCode
    message: str
    path: str | None = None
    translation_unit: str | None = None
    requires_full_rebuild: bool = False


@dataclass(frozen=True, slots=True)
class RepositoryChange:
    old_path: RepositoryFile | None
    new_path: RepositoryFile | None
    kind: ChangeKind

    def __post_init__(self) -> None:
        valid = {
            ChangeKind.ADD: self.old_path is None and self.new_path is not None,
            ChangeKind.DELETE: self.old_path is not None and self.new_path is None,
            ChangeKind.MODIFY: self.old_path is not None and self.old_path == self.new_path,
            ChangeKind.RENAME: self.old_path is not None and self.new_path is not None
            and self.old_path != self.new_path,
        }
        if not valid[self.kind]:
            raise ValueError("Repository change kind disagrees with old/new paths.")

    @classmethod
    def from_paths(cls, old_path: str | None, new_path: str | None,
                   kind: ChangeKind) -> RepositoryChange:
        return cls(None if old_path is None else RepositoryFile.from_path(old_path),
                   None if new_path is None else RepositoryFile.from_path(new_path), kind)


def normalize_repository_changes(changes: Iterable[RepositoryChange]) -> tuple[RepositoryChange, ...]:
    """Validate, deduplicate, and canonically order a repository change set."""
    items = tuple(changes)
    if any(not isinstance(item, RepositoryChange) for item in items):
        raise TypeError("Repository changes must be RepositoryChange values.")
    unique = set(items)
    old_paths = [item.old_path for item in unique if item.old_path is not None]
    new_paths = [item.new_path for item in unique if item.new_path is not None]
    if len(old_paths) != len(set(old_paths)) or len(new_paths) != len(set(new_paths)):
        raise ValueError("Repository change set contains conflicting paths on one revision side.")
    return tuple(sorted(unique, key=lambda item: (
        "" if item.old_path is None else item.old_path.path.as_posix(),
        "" if item.new_path is None else item.new_path.path.as_posix(), item.kind.value,
    )))


@dataclass(frozen=True, slots=True)
class ConfigurationInput:
    path: RepositoryFile
    sha256: str

    def __post_init__(self) -> None:
        _require_sha256(self.sha256, "configuration input")


@dataclass(frozen=True, slots=True)
class CompileContextIdentity:
    value: str

    def __post_init__(self) -> None:
        if not self.value.startswith("compile-context:sha256:"):
            raise ValueError("Compile context identity must use the versioned sha256 scheme.")


@dataclass(frozen=True, slots=True)
class CompileContext:
    source: RepositoryFile
    working_directory: str
    arguments: tuple[str, ...]
    configuration_inputs: tuple[ConfigurationInput, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.working_directory:
            raise ValueError("Compile context working directory must not be empty.")
        if not self.arguments or not all(isinstance(value, str) and value for value in self.arguments):
            raise ValueError("Compile context arguments must be non-empty strings.")
        canonical = tuple(sorted(set(self.configuration_inputs),
                                 key=lambda item: item.path.path.as_posix()))
        if (canonical != self.configuration_inputs
                or len({item.path for item in self.configuration_inputs}) != len(self.configuration_inputs)):
            raise ValueError("Compile configuration inputs must be unique and canonically ordered.")
        if self.schema_version != 1:
            raise ValueError("Unsupported compile context schema version.")

    @property
    def identity(self) -> CompileContextIdentity:
        payload = {
            "schema_version": self.schema_version,
            "source": self.source.path.as_posix(),
            "working_directory": self.working_directory,
            "arguments": self.arguments,
            "configuration_inputs": tuple(
                (item.path.path.as_posix(), item.sha256) for item in self.configuration_inputs
            ),
        }
        return CompileContextIdentity("compile-context:sha256:" + _canonical_sha256(payload))


@dataclass(frozen=True, slots=True)
class TranslationUnitIdentity:
    value: str
    source: RepositoryFile
    compile_context: CompileContextIdentity

    def __post_init__(self) -> None:
        if not self.value.startswith("tu:sha256:"):
            raise ValueError("Translation unit identity must use the versioned sha256 scheme.")

    @classmethod
    def from_context(cls, context: CompileContext) -> TranslationUnitIdentity:
        value = _canonical_sha256({
            "schema_version": 1,
            "source": context.source.path.as_posix(),
            "compile_context": context.identity.value,
        })
        return cls("tu:sha256:" + value, context.source, context.identity)


@dataclass(frozen=True, slots=True)
class CompileContextInventory:
    contexts: tuple[CompileContext, ...]
    coverage: CoverageStatus
    diagnostics: tuple[ImpactDiagnostic, ...] = ()
    provider_identity: str = "unknown"

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.contexts, key=lambda item: (
            item.source.path.as_posix(), item.identity.value,
        )))
        if ordered != self.contexts or len({item.identity for item in self.contexts}) != len(self.contexts):
            raise ValueError("Compile contexts must have unique identities and canonical order.")

    @property
    def translation_units(self) -> tuple[TranslationUnitIdentity, ...]:
        return tuple(TranslationUnitIdentity.from_context(item) for item in self.contexts)


class CompileContextProvider(Protocol):
    def load(self, workspace: RepositoryWorkspace) -> CompileContextInventory: ...


class CompilationDatabaseProvider:
    """Read the standard JSON compilation database through a P1 adapter."""

    def __init__(self, path: str | os.PathLike[str] = "compile_commands.json", *,
                 configuration_files: Iterable[str] = ()) -> None:
        self.path = Path(path).expanduser()
        self.configuration_files = tuple(sorted(
            (RepositoryFile.from_path(item) for item in configuration_files),
            key=lambda item: item.path.as_posix(),
        ))

    def load(self, workspace: RepositoryWorkspace) -> CompileContextInventory:
        provider_identity = "compilation-database-json-v1:"
        try:
            database_path = (self.path.resolve() if self.path.is_absolute()
                             else workspace.resolve(self.path))
            raw = database_path.read_bytes()
            provider_identity += hashlib.sha256(raw).hexdigest()
            payload = json.loads(raw)
            if not isinstance(payload, list):
                raise ValueError("Compilation database root must be a JSON array.")
            configuration_inputs = tuple(ConfigurationInput(path, _hash_file(workspace.resolve(path.path.as_posix())))
                                         for path in self.configuration_files)
            contexts = [self._context(workspace, item, configuration_inputs) for item in payload]
            contexts.sort(key=lambda item: (item.source.path.as_posix(), item.identity.value))
            if len({item.identity for item in contexts}) != len(contexts):
                raise ValueError("Compilation database repeats an identical compile context.")
            return CompileContextInventory(tuple(contexts), CoverageStatus.COMPLETE, (), provider_identity)
        except FileNotFoundError as error:
            diagnostic = ImpactDiagnostic(
                DiagnosticCode.MISSING_COMPILE_METADATA,
                f"Compilation database or relevant configuration file is missing: {error}",
                str(self.path), requires_full_rebuild=True,
            )
            return CompileContextInventory((), CoverageStatus.UNKNOWN, (diagnostic,), provider_identity)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            diagnostic = ImpactDiagnostic(DiagnosticCode.MALFORMED_METADATA,
                                          f"Unable to load compilation database: {error}",
                                          str(self.path), requires_full_rebuild=True)
            return CompileContextInventory((), CoverageStatus.UNKNOWN, (diagnostic,), provider_identity)

    @staticmethod
    def _context(workspace: RepositoryWorkspace, item: object,
                 configuration_inputs: tuple[ConfigurationInput, ...]) -> CompileContext:
        if not isinstance(item, dict):
            raise ValueError("Compilation database entry must be an object.")
        directory = item.get("directory")
        file_value = item.get("file")
        if not isinstance(directory, str) or not directory or not isinstance(file_value, str) or not file_value:
            raise ValueError("Compilation database entry needs string directory and file fields.")
        if not Path(directory).is_absolute():
            raise ValueError("Compilation database directory must be absolute.")
        arguments = item.get("arguments")
        command = item.get("command")
        if isinstance(arguments, list) and all(isinstance(value, str) for value in arguments):
            parsed_arguments = tuple(arguments)
        elif isinstance(command, str):
            parsed_arguments = tuple(shlex.split(command, posix=os.name != "nt"))
        else:
            raise ValueError("Compilation database entry needs arguments or command.")
        working_directory = str(Path(directory).expanduser().resolve())
        source = _repository_file_from_metadata(workspace, file_value, Path(working_directory))
        if source.path.suffix.casefold() not in _TU_EXTENSIONS:
            raise ValueError(f"Compilation database entry is not a translation unit: {source.path}")
        if not workspace.resolve(source.path.as_posix()).is_file():
            raise ValueError(f"Compilation database source does not exist: {source.path}")
        return CompileContext(source, working_directory, parsed_arguments, configuration_inputs)


@dataclass(frozen=True, slots=True)
class DependencyRecord:
    translation_unit: TranslationUnitIdentity
    dependencies: tuple[RepositoryFile, ...]
    metadata_identity: str

    def __post_init__(self) -> None:
        ordered = tuple(sorted(set(self.dependencies), key=lambda item: item.path.as_posix()))
        if ordered != self.dependencies:
            raise ValueError("Dependencies must be unique and canonically ordered.")
        if self.translation_unit.source not in self.dependencies:
            raise ValueError("Dependency metadata must include the translation unit source.")
        if not self.metadata_identity:
            raise ValueError("Dependency metadata identity must not be empty.")


@dataclass(frozen=True, slots=True)
class DependencyMetadataSnapshot:
    records: tuple[DependencyRecord, ...]
    coverage: CoverageStatus
    diagnostics: tuple[ImpactDiagnostic, ...] = ()
    provider_identity: str = "unknown"

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.records, key=lambda item: item.translation_unit.value))
        if ordered != self.records or len({item.translation_unit for item in self.records}) != len(self.records):
            raise ValueError("Dependency records must be unique and canonically ordered.")


class DependencyMetadataProvider(Protocol):
    def load(self, workspace: RepositoryWorkspace,
             contexts: CompileContextInventory) -> DependencyMetadataSnapshot: ...


class MakeDepfileDependencyProvider:
    """Adapter for compiler-generated Make-style depfiles (for example ``-MD``)."""

    def __init__(self, metadata_root: str | os.PathLike[str],
                 depfiles: Mapping[str, str]) -> None:
        self.metadata_root = Path(metadata_root).expanduser().resolve()
        self.depfiles_by_tu = {key: Path(depfile) for key, depfile in depfiles.items()
                               if key.startswith("tu:sha256:")}
        self.depfiles_by_source = {RepositoryFile.from_path(key): Path(depfile)
                                   for key, depfile in depfiles.items()
                                   if not key.startswith("tu:sha256:")}

    def load(self, workspace: RepositoryWorkspace,
             contexts: CompileContextInventory) -> DependencyMetadataSnapshot:
        records: list[DependencyRecord] = []
        diagnostics: list[ImpactDiagnostic] = []
        source_counts: dict[RepositoryFile, int] = {}
        for context in contexts.contexts:
            source_counts[context.source] = source_counts.get(context.source, 0) + 1
        for context in contexts.contexts:
            source = context.source
            tu = TranslationUnitIdentity.from_context(context)
            depfile = self.depfiles_by_tu.get(tu.value)
            if depfile is None and source_counts[source] == 1:
                depfile = self.depfiles_by_source.get(source)
            if depfile is None:
                diagnostics.append(ImpactDiagnostic(
                    DiagnosticCode.MISSING_DEPENDENCY_METADATA,
                    "No unambiguous compiler depfile is registered for the exact translation unit.",
                    translation_unit=source.path.as_posix(), requires_full_rebuild=True,
                ))
                continue
            try:
                path = (self.metadata_root / depfile).resolve()
                path.relative_to(self.metadata_root)
                raw = path.read_text(encoding="utf-8")
                dependencies = {source}
                outside = 0
                for token in _parse_make_depfile(raw):
                    try:
                        dependencies.add(_repository_file_from_metadata(
                            workspace, token, Path(context.working_directory)
                        ))
                    except ValueError:
                        outside += 1  # System/toolchain headers do not participate in repository changes.
                if outside:
                    diagnostics.append(ImpactDiagnostic(
                        DiagnosticCode.OUTSIDE_REPOSITORY_DEPENDENCY,
                        f"Ignored {outside} dependency paths outside the repository.",
                        path=path.name, translation_unit=source.path.as_posix(),
                    ))
                identity = "make-depfile-v1:sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
                records.append(DependencyRecord(
                    tu,
                    tuple(sorted(dependencies, key=lambda item: item.path.as_posix())), identity,
                ))
            except (OSError, UnicodeError, ValueError) as error:
                diagnostics.append(ImpactDiagnostic(
                    DiagnosticCode.MALFORMED_METADATA, f"Unable to load compiler depfile: {error}",
                    path=str(depfile), translation_unit=source.path.as_posix(), requires_full_rebuild=True,
                ))
        coverage = CoverageStatus.COMPLETE
        if contexts.coverage is CoverageStatus.UNKNOWN or not contexts.contexts:
            coverage = CoverageStatus.UNKNOWN
        elif len(records) != len(contexts.contexts) or contexts.coverage is CoverageStatus.PARTIAL:
            coverage = CoverageStatus.PARTIAL
        return DependencyMetadataSnapshot(tuple(sorted(records, key=lambda item: item.translation_unit.value)),
                                          coverage, tuple(diagnostics), "make-depfile-v1")


class ReverseDependencyIndex:
    def __init__(self, metadata: DependencyMetadataSnapshot) -> None:
        reverse: dict[RepositoryFile, set[TranslationUnitIdentity]] = {}
        for record in metadata.records:
            for dependency in record.dependencies:
                reverse.setdefault(dependency, set()).add(record.translation_unit)
        self._reverse = {path: tuple(sorted(values, key=lambda item: item.value))
                         for path, values in reverse.items()}

    def translation_units_for(self, path: RepositoryFile) -> tuple[TranslationUnitIdentity, ...]:
        return self._reverse.get(path, ())


@dataclass(frozen=True, slots=True)
class SemanticFileState:
    path: RepositoryFile
    sha256: str

    def __post_init__(self) -> None:
        _require_sha256(self.sha256, "semantic file state")


@dataclass(frozen=True, slots=True)
class SemanticFingerprintInput:
    translation_unit: TranslationUnitIdentity
    source_and_dependencies: tuple[SemanticFileState, ...]
    dependency_metadata_identity: str
    semantic_producer_identity: str
    semantic_schema_identity: str
    fingerprint_schema_version: int = 1

    def __post_init__(self) -> None:
        ordered = tuple(sorted(set(self.source_and_dependencies), key=lambda item: item.path.path.as_posix()))
        if (ordered != self.source_and_dependencies
                or len({item.path for item in self.source_and_dependencies}) != len(self.source_and_dependencies)):
            raise ValueError("Semantic file states must be unique and canonically ordered.")
        if self.translation_unit.source not in {item.path for item in self.source_and_dependencies}:
            raise ValueError("Semantic fingerprint input must include the translation unit source state.")
        if not all((self.dependency_metadata_identity, self.semantic_producer_identity,
                    self.semantic_schema_identity)):
            raise ValueError("Semantic fingerprint identities must not be empty.")
        if self.fingerprint_schema_version != 1:
            raise ValueError("Unsupported semantic fingerprint schema version.")

    @property
    def sha256(self) -> str:
        return _canonical_sha256({
            "schema_version": self.fingerprint_schema_version,
            "translation_unit": self.translation_unit.value,
            "compile_context": self.translation_unit.compile_context.value,
            "files": tuple((item.path.path.as_posix(), item.sha256)
                           for item in self.source_and_dependencies),
            "dependency_metadata": self.dependency_metadata_identity,
            "semantic_producer": self.semantic_producer_identity,
            "semantic_schema": self.semantic_schema_identity,
        })


@dataclass(frozen=True, slots=True)
class DependencyImpact:
    changes: tuple[RepositoryChange, ...]
    affected_translation_units: tuple[TranslationUnitIdentity, ...]
    status: ImpactStatus
    dependency_coverage: CoverageStatus
    diagnostics: tuple[ImpactDiagnostic, ...]

    @property
    def requires_full_rebuild(self) -> bool:
        return self.status is not ImpactStatus.SAFE_INCREMENTAL


class DependencyImpactAnalyzer:
    """Compute a conservative affected-TU set from proven compiler metadata."""

    def analyze(self, changes: Iterable[RepositoryChange], *,
                previous_contexts: CompileContextInventory,
                current_contexts: CompileContextInventory,
                previous_dependencies: DependencyMetadataSnapshot,
                current_dependencies: DependencyMetadataSnapshot) -> DependencyImpact:
        normalized = normalize_repository_changes(changes)
        diagnostics = list(previous_contexts.diagnostics + current_contexts.diagnostics
                           + previous_dependencies.diagnostics + current_dependencies.diagnostics)
        affected: set[TranslationUnitIdentity] = set()
        previous_tus = _translation_units_by_source(previous_contexts)
        current_tus = _translation_units_by_source(current_contexts)
        previous_reverse = ReverseDependencyIndex(previous_dependencies)
        current_reverse = ReverseDependencyIndex(current_dependencies)

        effective_dependency_coverage = [previous_dependencies.coverage,
                                         current_dependencies.coverage]
        for label, contexts, metadata in (
            ("previous", previous_contexts, previous_dependencies),
            ("current", current_contexts, current_dependencies),
        ):
            expected = set(contexts.translation_units)
            actual = {item.translation_unit for item in metadata.records}
            if expected != actual:
                effective_dependency_coverage.append(CoverageStatus.PARTIAL)
                diagnostics.append(ImpactDiagnostic(
                    DiagnosticCode.MISSING_DEPENDENCY_METADATA,
                    f"{label} dependency metadata TU coverage mismatch: "
                    f"missing={len(expected - actual)}, unexpected={len(actual - expected)}.",
                    requires_full_rebuild=True,
                ))

        # Compile context additions/removals/changes are semantic invalidations even
        # when no source path appears in the repository diff.
        for source in sorted(set(previous_tus) | set(current_tus), key=lambda item: item.path.as_posix()):
            before, after = previous_tus.get(source, set()), current_tus.get(source, set())
            affected.update(before ^ after)

        relevant_configuration: dict[RepositoryFile, set[TranslationUnitIdentity]] = {}
        for inventory in (previous_contexts, current_contexts):
            for context in inventory.contexts:
                tu = TranslationUnitIdentity.from_context(context)
                for item in context.configuration_inputs:
                    relevant_configuration.setdefault(item.path, set()).add(tu)

        header_changed = False
        for change in normalized:
            paths = tuple(path for path in (change.old_path, change.new_path) if path is not None)
            extensions = {path.path.suffix.casefold() for path in paths}
            if extensions & _HEADER_EXTENSIONS:
                header_changed = True
                for path in paths:
                    affected.update(previous_reverse.translation_units_for(path))
                    affected.update(current_reverse.translation_units_for(path))
            if extensions & _TU_EXTENSIONS:
                for path in paths:
                    affected.update(previous_tus.get(path, ()))
                    affected.update(current_tus.get(path, ()))
                if not any(path in previous_tus or path in current_tus for path in paths):
                    diagnostics.append(ImpactDiagnostic(
                        DiagnosticCode.MISSING_COMPILE_CONTEXT,
                        "Changed source has no translation-unit compile context.",
                        path=paths[-1].path.as_posix(), requires_full_rebuild=True,
                    ))
            for path in paths:
                affected.update(relevant_configuration.get(path, ()))
            if (not extensions & (_TU_EXTENSIONS | _HEADER_EXTENSIONS)
                    and not any(path in relevant_configuration for path in paths)):
                diagnostics.append(ImpactDiagnostic(
                    DiagnosticCode.UNSUPPORTED_CHANGED_FILE,
                    "Changed file is not a TU/header or a declared relevant compile input.",
                    path=paths[-1].path.as_posix(),
                ))

        coverage = _combined_coverage(previous_contexts.coverage, current_contexts.coverage,
                                      *effective_dependency_coverage)
        if header_changed and coverage is not CoverageStatus.COMPLETE:
            diagnostics.append(ImpactDiagnostic(
                DiagnosticCode.UNKNOWN_HEADER_IMPACT,
                "Header impact is not provably complete because dependency metadata coverage is incomplete.",
                requires_full_rebuild=True,
            ))
        fallback = any(item.requires_full_rebuild for item in diagnostics)
        status = ImpactStatus.FULL_REBUILD_REQUIRED if fallback else (
            ImpactStatus.UNKNOWN if coverage is CoverageStatus.UNKNOWN else ImpactStatus.SAFE_INCREMENTAL
        )
        return DependencyImpact(normalized, tuple(sorted(affected, key=lambda item: item.value)),
                                status, coverage, tuple(sorted(set(diagnostics), key=_diagnostic_key)))


def _combined_coverage(*values: CoverageStatus) -> CoverageStatus:
    if CoverageStatus.UNKNOWN in values:
        return CoverageStatus.UNKNOWN
    if CoverageStatus.PARTIAL in values:
        return CoverageStatus.PARTIAL
    return CoverageStatus.COMPLETE


def _translation_units_by_source(inventory: CompileContextInventory) -> dict[
    RepositoryFile, set[TranslationUnitIdentity]
]:
    result: dict[RepositoryFile, set[TranslationUnitIdentity]] = {}
    for context in inventory.contexts:
        result.setdefault(context.source, set()).add(TranslationUnitIdentity.from_context(context))
    return result


def _diagnostic_key(item: ImpactDiagnostic) -> tuple[object, ...]:
    return (item.code.value, item.path or "", item.translation_unit or "",
            item.requires_full_rebuild, item.message)


def _repository_file_from_metadata(workspace: RepositoryWorkspace, value: str,
                                   directory: Path) -> RepositoryFile:
    candidate = Path(value)
    absolute = candidate if candidate.is_absolute() else directory / candidate
    resolved = absolute.resolve()
    try:
        relative = resolved.relative_to(workspace.root)
    except ValueError as error:
        raise ValueError(f"Metadata path is outside repository: {value}") from error
    return RepositoryFile.from_path(relative.as_posix())


def _parse_make_depfile(value: str) -> tuple[str, ...]:
    logical = re.sub(r"\\\r?\n", "", value)
    separator = re.search(r":\s", logical)
    if separator is None:
        raise ValueError("Depfile has no target/dependency separator.")
    dependencies = logical[separator.end():]
    words: list[str] = []
    current: list[str] = []
    escaped = False
    for character in dependencies:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character.isspace():
            if current:
                words.append("".join(current))
                current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    if current:
        words.append("".join(current))
    if not words:
        raise ValueError("Depfile has no dependencies.")
    return tuple(words)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: str, label: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} sha256 must be 64 lowercase hexadecimal characters.")
