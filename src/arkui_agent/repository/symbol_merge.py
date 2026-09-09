"""Canonicalize same-revision semantic observations, never names into identities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .model import SourceRange, Symbol, SymbolKind
from .semantic import SemanticProviderError


@dataclass(frozen=True, slots=True)
class SymbolObservation:
    symbol: Symbol
    site: SourceRange  # actual documentSymbol selection, not its resolved declaration
    parent_kind: SymbolKind | None


class SymbolMergeConflict(SemanticProviderError):
    def __init__(self, field: str, observations: tuple[SymbolObservation, ...]) -> None:
        self.field = field
        self.observations = observations
        super().__init__(f"Conflicting symbol {observations[0].symbol.identity.value}: {field}")


def canonicalize_symbols(observations: Iterable[SymbolObservation]) -> tuple[Symbol, ...]:
    """Merge a complete collection from one repository/revision; fail atomically.

    Missing range evidence may be supplemented, conflicting non-null ranges may
    not. Member containment/display differences require a unique declaration-site
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
        declaration = unique("declaration", missing=True)
        definition = unique("definition", missing=True)
        namespace = unique("namespace_identity", missing=True)
        hierarchy = {(f.symbol.display_name, f.symbol.parent_identity) for f in facts}
        if len(hierarchy) > 1:
            declarations = tuple(f for f in facts if declaration is not None
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
        else:
            display_name, parent = next(iter(hierarchy))
        result.append(Symbol(facts[0].symbol.identity, kind, display_name, qualified_name,
                             declaration, definition, parent, namespace))
    return tuple(result)
