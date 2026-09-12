"""Canonicalize same-revision semantic observations, never names into identities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .model import SourceRange, Symbol, SymbolKind
from .semantic import SemanticProviderError


@dataclass(frozen=True, slots=True)
class SymbolObservation:
    symbol: Symbol
    site: SourceRange | None = None  # actual selection, never a fabricated declaration site
    parent_kind: SymbolKind | None = None
    provenance: str | None = None  # opaque backend audit JSON; never used to select a winner


class SymbolMergeConflict(SemanticProviderError):
    def __init__(self, field: str, observations: tuple[SymbolObservation, ...]) -> None:
        self.field = field
        self.observations = observations
        super().__init__(f"Conflicting symbol {observations[0].symbol.identity.value}: {field}")


@dataclass(frozen=True, slots=True)
class CanonicalSymbolGroup:
    """Canonical scalar view plus lossless, sorted original semantic evidence."""

    symbol: Symbol
    observations: tuple[SymbolObservation, ...]


def canonicalize_symbol_groups(observations: Iterable[SymbolObservation]) -> tuple[CanonicalSymbolGroup, ...]:
    """Merge a complete collection from one repository/revision; fail atomically.

    Missing optional evidence may be supplemented. Namespace ranges allow reopen
    sites; other conflicting non-null ranges fail. Local member presentation
    differences require a unique declaration-site
    class/struct hierarchy observation. Collection order has no authority.
    """
    groups: dict[str, list[SymbolObservation]] = {}
    for observation in observations:
        groups.setdefault(observation.symbol.identity.value, []).append(observation)
    result = []
    for identity in sorted(groups):
        facts = tuple(sorted(set(groups[identity]), key=repr))

        def unique(field: str, *, missing: bool = False):
            values = {getattr(f.symbol, field) for f in facts}
            if missing:
                values.discard(None)
            if len(values) > 1:
                raise SymbolMergeConflict(field, facts)
            return next(iter(values)) if values else None

        kind = unique("kind")
        qualified_name = unique("qualified_name")
        def namespace_range(field: str) -> SourceRange | None:
            ranges = {getattr(f.symbol, field) for f in facts} - {None}
            # A namespace may legally have multiple declarations/definitions.
            # This is a stable representative, not a claim of a unique site.
            return min(ranges, key=lambda r: (r.file.path.as_posix(), r.start.line,
                                              r.start.column, r.end.line, r.end.column)) if ranges else None

        declaration = namespace_range("declaration") if kind is SymbolKind.NAMESPACE else unique("declaration", missing=True)
        definition = namespace_range("definition") if kind is SymbolKind.NAMESPACE else unique("definition", missing=True)
        namespace = unique("namespace_identity", missing=True)
        parents = {f.symbol.parent_identity for f in facts} - {None}
        displays = {f.symbol.display_name for f in facts}
        if len(displays) == 1 and len(parents) <= 1:
            display_name = next(iter(displays))
            parent = next(iter(parents)) if parents else None
            result.append(CanonicalSymbolGroup(Symbol(facts[0].symbol.identity, kind, display_name, qualified_name,
                                                     declaration, definition, parent, namespace), facts))
            continue
        # Preserve the existing document-local out-of-class presentation rule;
        # absent endpoint metadata is not declaration-site hierarchy evidence.
        if len(displays) == 1:
            raise SymbolMergeConflict("parent_identity", facts)
        hierarchy = {(f.symbol.display_name, f.symbol.parent_identity) for f in facts}
        if len(hierarchy) > 1:
            declarations = tuple(f for f in facts if declaration is not None and f.site is not None
                                 and f.symbol.parent_identity is not None and f.parent_kind is not None
                                 and f.site.file == declaration.file
                                 and max((f.site.start.line, f.site.start.column),
                                         (declaration.start.line, declaration.start.column))
                                 < min((f.site.end.line, f.site.end.column),
                                       (declaration.end.line, declaration.end.column)))
            proven = {(f.symbol.display_name, f.symbol.parent_identity) for f in declarations}
            if (kind not in (SymbolKind.METHOD, SymbolKind.FIELD) or not declarations or len(proven) != 1
                    or any(f.parent_kind not in (SymbolKind.CLASS, SymbolKind.STRUCT)
                           or f.symbol.parent_identity is None for f in declarations)):
                raise SymbolMergeConflict("declaration_site_containment", facts)
            display_name, parent = next(iter(proven))
            for fact in facts:
                if (fact.symbol.display_name == display_name
                        and fact.symbol.parent_identity in (None, parent)):
                    continue
                if (fact.site is not None and fact.parent_kind is SymbolKind.NAMESPACE
                        and fact.symbol.parent_identity is not None
                        and fact.symbol.parent_identity == namespace
                        and fact.symbol.display_name != display_name):
                    continue  # proven out-of-class local namespace presentation
                raise SymbolMergeConflict("related_symbol_metadata", facts)
        else:
            display_name, parent = next(iter(hierarchy))
        result.append(CanonicalSymbolGroup(Symbol(facts[0].symbol.identity, kind, display_name, qualified_name,
                                                 declaration, definition, parent, namespace), facts))
    return tuple(result)


def canonicalize_symbols(observations: Iterable[SymbolObservation]) -> tuple[Symbol, ...]:
    """Scalar compatibility view; use groups to retain every original site."""
    return tuple(group.symbol for group in canonicalize_symbol_groups(observations))
