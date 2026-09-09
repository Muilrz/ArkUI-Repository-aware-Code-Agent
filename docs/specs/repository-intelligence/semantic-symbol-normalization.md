# Semantic symbol normalization — v1

P1 public boundary: `SymbolObservation`, `canonicalize_symbols`, `SymbolMergeConflict`.
This normalization is independent of C2, retrieval, persistence and LLMs.

## Observations and scope

`ClangdSemanticProvider.symbols_in_file` retains its existing per-document Symbol
results. A document's nesting is local presentation evidence, not automatically
canonical cross-file semantic containment. `symbol_observations_in_file` additionally
preserves the actual documentSymbol selection range and the immediate hierarchy
parent's kind alongside each Symbol. These are backend evidence, not inferred from
qualified names or file extensions. Coordinates remain P1 one-based, end-exclusive.

Multi-file consumers collect all observations for their fixed semantic scope before
calling `canonicalize_symbols`. All observations must belong to one repository,
revision and backend configuration; the caller owns this scope/lifetime invariant.
This API does not combine revisions, discover files, query clangd, refresh indexes or
resolve missing identities. Existing provider handles are not used as merge winners.

For clangd, use `symbol_observations_in_files` for the fixed scope. It opens every
requested document and obtains all documentSymbol responses before collecting
any declaration/definition location queries. This finite AST-readiness barrier
avoids combining an early header-only semantic state with later facts from an
opened definition translation unit. Files are scheduled in stable path order;
no record wins by that order, and all observations remain subject to strict merge.
It does not poll/retry, expand scope or guarantee a full background repository
index. Incompatible ranges that remain after this preparation still fail.
Single-file observations remain valid local queries; independently collected
observations from changing backend visibility are not a fixed-scope batch.

## Canonicalization

1. Group by opaque SymbolIdentity only; sort output by identity. Same names with
   different identities, including overloads, remain separate.
2. Kind and qualified name must agree. Non-null declaration, definition and
   namespace identity facts must respectively agree exactly. Missing evidence may
   be supplemented, but non-null range differences are real conflicts, even when
   source text or names look similar.
3. If display name and parent identity already agree, preserve them. Otherwise,
   only METHOD/FIELD observations may resolve the local hierarchy difference.
4. Declaration-site evidence means an observation of that same identity whose
   actual selection range overlaps the resolved declaration range in the same
   file. Merely being collected from the declaration file is insufficient.
5. All declaration-site observations must agree on display name and parent; their
   immediate hierarchy parent must be a class/struct with a non-null identity.
   This unique tuple is canonical. Out-of-class definition namespace nesting
   cannot override this declaration-site containment.
6. Missing/ambiguous declaration-site containment, differing declaration parents,
   non-member hierarchy disagreement and incompatible facts raise
   `SymbolMergeConflict`. Its `field` and all original conflicting observations
   remain available; no partial canonical tuple is returned.

There is no first/last-observed preference, extension preference, qualified-name
parent parsing, smallest-parent heuristic or symbol-specific exception. Duplicate
observations are idempotent; reversing the complete observation order yields the
same Symbol tuple or the same conflict evidence. The merge returns original proven
declaration/definition ranges, never synthesized enclosing body ranges.

## C2 preparation consumer

The explicitly authorized C2 preparation consumes this public P1 boundary. It
records `p1-declaration-site-canonical-v1` in configuration provenance and retains
the fixed declaration/definition source closure over **all original observations**.
Normalization does not expand semantic scope or derive inventory from C2 output.
Unresolved real conflicts prevent publication. This change does not alter frozen
C2 expected or P2/C1 expected; it supplies canonical existing semantic evidence.
