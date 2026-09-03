"""Adapter from current P1 repository APIs to the baseline runner contract."""

from __future__ import annotations

from arkui_agent.evaluation.model import (
    BenchmarkQuery,
    IdentityQueryInput,
    RetrievalKind,
    SymbolQueryMatch,
    SymbolSearchInput,
    TextQueryMode,
    TextSearchInput,
)
from arkui_agent.evaluation.runner import (
    FailureCategory,
    RetrievalExecutionError,
    RetrievalOutput,
    RetrievedRelation,
    RetrievedSymbol,
    RetrievedTest,
)
from arkui_agent.repository import (
    RepositoryTextSearch,
    RepositoryTextSearchError,
    RepositoryWorkspace,
    SourceRange,
    Symbol,
    SymbolIdentity,
    SymbolIndex,
    SymbolIndexError,
    TextSearchMode,
    TextSearchQuery,
    TextSearchQueryError,
    TextSearchToolUnavailableError,
)
from arkui_agent.retrieval import (
    DefinitionDeclarationRetrievalError,
    DefinitionDeclarationRetriever,
    DirectCallRelation,
    ReferenceCallRetriever,
)


class P1RetrievalExecutor:
    """Execute all P1-I required query kinds without exposing backend details."""

    def __init__(
        self, workspace: RepositoryWorkspace, symbol_index: SymbolIndex
    ) -> None:
        self._workspace = workspace
        self._index = symbol_index
        self._definitions = DefinitionDeclarationRetriever(symbol_index)
        self._relations = ReferenceCallRetriever(symbol_index)

    def execute(self, query: BenchmarkQuery) -> RetrievalOutput:
        try:
            if isinstance(query, TextSearchInput):
                return self._text_search(query)
            if isinstance(query, SymbolSearchInput):
                return self._search_symbol(query)
            return self._identity_query(query)
        except RetrievalExecutionError:
            raise
        except TextSearchToolUnavailableError as exc:
            raise RetrievalExecutionError(
                FailureCategory.BACKEND_UNAVAILABLE, str(exc)
            ) from exc
        except RepositoryTextSearchError as exc:
            raise RetrievalExecutionError(
                FailureCategory.BACKEND_FAILURE, str(exc)
            ) from exc
        except TextSearchQueryError as exc:
            raise RetrievalExecutionError(
                FailureCategory.QUERY_REJECTED, str(exc)
            ) from exc
        except SymbolIndexError as exc:
            raise RetrievalExecutionError(
                FailureCategory.INDEX_FAILURE, str(exc)
            ) from exc
        except DefinitionDeclarationRetrievalError as exc:
            raise RetrievalExecutionError(
                FailureCategory.QUERY_REJECTED, str(exc)
            ) from exc

    def _text_search(self, query: TextSearchInput) -> RetrievalOutput:
        search = RepositoryTextSearch(self._workspace)
        matches = search.search(
            TextSearchQuery(
                query.text,
                mode=(
                    TextSearchMode.EXACT
                    if query.mode is TextQueryMode.EXACT
                    else TextSearchMode.REGEX
                ),
                case_sensitive=query.case_sensitive,
                path_scope=query.path_scope,
                file_globs=query.file_globs,
                limit=query.limit,
            )
        )
        return RetrievalOutput(
            files=tuple(match.file.path.as_posix() for match in matches)
        )

    def _search_symbol(self, query: SymbolSearchInput) -> RetrievalOutput:
        candidates = (
            self._definitions.candidates_by_name(query.name)
            if query.match is SymbolQueryMatch.DISPLAY_NAME
            else self._definitions.candidates_by_qualified_name(query.name)
        )
        symbols = candidates.symbols
        if query.limit is not None:
            symbols = symbols[: query.limit]
        return RetrievalOutput(
            files=tuple(
                source_range.file.path.as_posix()
                for symbol in symbols
                if (source_range := symbol.definition or symbol.declaration) is not None
            ),
            symbols=tuple(_retrieved_symbol(symbol) for symbol in symbols),
        )

    def _identity_query(self, query: IdentityQueryInput) -> RetrievalOutput:
        symbol = self._exact_symbol(query)
        identity = symbol.identity
        if query.kind is RetrievalKind.FIND_DECLARATION:
            return _source_fact_output(symbol, self._definitions.declaration(identity))
        if query.kind is RetrievalKind.FIND_DEFINITION:
            return _source_fact_output(symbol, self._definitions.definition(identity))
        if query.kind is RetrievalKind.FIND_REFERENCES:
            references = self._relations.references(identity)
            return RetrievalOutput(
                files=tuple(
                    item.source_range.file.path.as_posix() for item in references
                ),
                symbols=tuple(_retrieved_symbol(symbol) for _ in references),
            )
        if query.kind is RetrievalKind.FIND_CALLERS:
            return _relation_output(self._relations.callers(identity))
        if query.kind is RetrievalKind.FIND_CALLEES:
            return _relation_output(self._relations.callees(identity))
        if query.kind is RetrievalKind.FIND_TESTS:
            tests = self._index.test_cases_for_symbol(identity)
            return RetrievalOutput(
                files=tuple(test.source_range.file.path.as_posix() for test in tests),
                tests=tuple(
                    RetrievedTest(
                        test.identity.value,
                        test.display_name,
                        test.source_range.file.path.as_posix(),
                    )
                    for test in tests
                ),
            )
        raise RetrievalExecutionError(
            FailureCategory.QUERY_REJECTED,
            f"Unsupported identity query kind: {query.kind.value}",
        )

    def _exact_symbol(self, query: IdentityQueryInput) -> Symbol:
        symbol = self._index.get(SymbolIdentity(query.symbol.identity))
        if symbol is None:
            raise RetrievalExecutionError(
                FailureCategory.QUERY_REJECTED,
                f"Symbol identity is not indexed: {query.symbol.identity!r}.",
            )
        if symbol.qualified_name != query.symbol.qualified_name:
            raise RetrievalExecutionError(
                FailureCategory.QUERY_REJECTED,
                "Identity query qualified name does not agree with the indexed "
                f"identity: expected {query.symbol.qualified_name!r}, indexed "
                f"{symbol.qualified_name!r}.",
            )
        return symbol


def _source_fact_output(
    symbol: Symbol, source_range: SourceRange | None
) -> RetrievalOutput:
    if source_range is None:
        return RetrievalOutput()
    file = source_range.file.path.as_posix()
    return RetrievalOutput(files=(file,), symbols=(_retrieved_symbol(symbol),))


def _relation_output(relations: tuple[DirectCallRelation, ...]) -> RetrievalOutput:
    return RetrievalOutput(
        files=tuple(
            relation.source_range.file.path.as_posix()
            for relation in relations
            if relation.source_range is not None
        ),
        symbols=tuple(
            _retrieved_symbol(endpoint)
            for relation in relations
            for endpoint in (relation.caller, relation.callee)
            if endpoint is not None
        ),
        relations=tuple(
            RetrievedRelation(
                caller=_relation_endpoint(relation.caller_identity, relation.caller),
                callee=_relation_endpoint(relation.callee_identity, relation.callee),
            )
            for relation in relations
        ),
    )


def _retrieved_symbol(symbol: Symbol) -> RetrievedSymbol:
    return RetrievedSymbol(symbol.identity.value, symbol.qualified_name)


def _relation_endpoint(
    identity: SymbolIdentity, symbol: Symbol | None
) -> RetrievedSymbol:
    return RetrievedSymbol(
        identity.value,
        None if symbol is None else symbol.qualified_name,
    )
