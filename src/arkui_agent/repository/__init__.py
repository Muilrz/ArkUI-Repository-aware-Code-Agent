"""Repository workspace package."""

from arkui_agent.repository.clangd import (
    ClangdProtocolError,
    ClangdSemanticProvider,
    ClangdUnavailableError,
)
from arkui_agent.repository.index import (
    SYMBOL_INDEX_FILENAME,
    SymbolIndex,
    SymbolIndexClosedError,
    SymbolIndexError,
    SymbolSemanticFacts,
)
from arkui_agent.repository.model import (
    RepositoryFile,
    SourceLocation,
    SourceRange,
    Symbol,
    SymbolIdentity,
    SymbolKind,
)
from arkui_agent.repository.scanner import (
    DEFAULT_EXCLUDED_DIRECTORIES,
    RepositoryFileType,
    RepositoryScanner,
    classify_repository_path,
)
from arkui_agent.repository.semantic import (
    SemanticProvider,
    SemanticProviderClosedError,
    SemanticProviderError,
)
from arkui_agent.repository.workspace import (
    ARKUI_REPO_ROOT,
    RepositoryConfigurationError,
    RepositoryPathError,
    RepositoryRootError,
    RepositoryWorkspace,
    RepositoryWorkspaceError,
)

__all__ = [
    "ARKUI_REPO_ROOT",
    "ClangdProtocolError",
    "ClangdSemanticProvider",
    "ClangdUnavailableError",
    "DEFAULT_EXCLUDED_DIRECTORIES",
    "RepositoryConfigurationError",
    "RepositoryFile",
    "RepositoryFileType",
    "RepositoryPathError",
    "RepositoryRootError",
    "RepositoryScanner",
    "RepositoryWorkspace",
    "RepositoryWorkspaceError",
    "SemanticProvider",
    "SemanticProviderClosedError",
    "SemanticProviderError",
    "SYMBOL_INDEX_FILENAME",
    "SourceLocation",
    "SourceRange",
    "Symbol",
    "SymbolIdentity",
    "SymbolIndex",
    "SymbolIndexClosedError",
    "SymbolIndexError",
    "SymbolKind",
    "SymbolSemanticFacts",
    "classify_repository_path",
]
