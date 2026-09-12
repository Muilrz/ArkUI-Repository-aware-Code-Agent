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

`SymbolObservation(symbol)` also accepts public endpoint results without local
document hierarchy evidence: `site` and `parent_kind` are then None. Never invent
a document selection from the resolved declaration. Collect related symbols into
the same lossless group before persistence; whole-object equality is not a merge.

Multi-file consumers collect all observations for their fixed semantic scope before
calling `canonicalize_symbols`. All observations must belong to one repository,
revision and backend configuration; the caller owns this scope/lifetime invariant.
This API does not combine revisions, discover files, query clangd, refresh indexes or
resolve missing identities. Existing provider handles are not used as merge winners.

For clangd, use `symbol_observations_in_files` for the fixed scope. At most four
documents are open simultaneously, including related endpoint documents. Large
scopes use two finite passes: open/query documentSymbol over every requested file
to establish AST readiness, then reopen/query/collect symbols over the same scope.
Small scopes retain the all-document readiness barrier without a redundant pass.
No location observations are collected before the complete preparation pass.
Eviction sends didClose; subsequent document/reference/call queries reopen the
actual endpoint URI. One process and its dynamic index survive both passes:
[LLVM ClangdServer](https://github.com/llvm/llvm-project/blob/llvmorg-22.1.6/clang-tools-extra/clangd/ClangdServer.cpp)
updates FileIndex on parsed ASTs; removeDocument removes drafts and TU scheduling,
not that index. This bounds live documents, not total index/observation memory.
The preparation avoids combining early header-only state with later facts from
definition translation units. Files are scheduled in stable path order;
no record wins by that order, and all observations remain subject to strict merge.
It does not poll/retry, expand scope or guarantee a full background repository
index. Incompatible ranges that remain after this preparation still fail.
Single-file observations remain valid local queries; independently collected
observations from changing backend visibility are not a fixed-scope batch.

## Canonicalization

Reopened namespace extension: only `SymbolKind.NAMESPACE` permits multiple
declaration/definition locations for the same opaque identity. Kind, qualified
name, display name and non-null parent/namespace identities still must agree.
`canonicalize_symbol_groups` returns a `CanonicalSymbolGroup` per identity with
all original `SymbolObservation` records (deduplicated and deterministically
sorted), preserving resolved declarations/definitions and actual local sites.
The scalar Symbol chooses the lexicographically first path/coordinate for each
range role; it is a representative, never a unique namespace declaration claim.
`canonicalize_symbols` remains the compatibility scalar view. Lossless consumers
must retain groups; production refresh persists them as generation-local
`semantic-observations.json` audit provenance. The P1 scalar index/read API is
unchanged and does not enumerate all namespace reopen sites. This audit file is
not a new query artifact or a replacement for P3-B's read contract.

1. Group by opaque SymbolIdentity only; sort output by identity. Same names with
   different identities, including overloads, remain separate.
2. Kind and qualified name must agree. Non-null declaration, definition and
   namespace identity facts must respectively agree exactly. Missing evidence may
   be supplemented; except for the namespace extension above, non-null range differences are real conflicts, even when
   source text or names look similar.
3. Optional declaration/definition, parent and namespace fields use known-value
   enrichment: None is absence of evidence, not a conflicting value. Compatible
   partial observations yield the union of known information. Two different known
   containment values with the same display name are conflicts. Kind and names
   remain mandatory; enrichment never reconciles contradictory names or ranges.
   If display names differ, the pre-existing document-local presentation rule below
   applies only with actual declaration hierarchy evidence; related endpoint
   metadata must agree with the resulting canonical name and known containment.
   Only METHOD/FIELD observations may resolve that local hierarchy difference.
4. Declaration-site evidence means an observation of that same identity whose
   actual selection range overlaps the resolved declaration range in the same
   file. Merely being collected from the declaration file is insufficient.
5. All complete declaration-site hierarchy observations must agree on display name and parent; their
   immediate hierarchy parent must be a class/struct with a non-null identity.
   This unique tuple is canonical. Out-of-class definition namespace nesting
   cannot override this declaration-site containment.
   A different known parent is admissible only as that proven local namespace
   presentation (parent kind NAMESPACE and identity equal to the known namespace),
   never as a competing class/struct or a related endpoint's contradictory parent.
6. Missing/ambiguous declaration-site containment, differing declaration parents,
   non-member hierarchy disagreement and incompatible facts raise
   `SymbolMergeConflict`. Its `field` and all original conflicting observations
   remain available; no partial canonical tuple is returned.

There is no first/last-observed preference, extension preference, qualified-name
parent parsing, smallest-parent heuristic or symbol-specific exception. Duplicate
observations are idempotent; reversing the complete observation order yields the
same Symbol tuple or the same conflict evidence. The merge returns original proven
declaration/definition ranges, never synthesized enclosing body ranges.
All original partial observations remain in `CanonicalSymbolGroup.observations`,
including absent metadata, even after the canonical Symbol has been enriched.

## Clangd identity binding and provenance

The clangd adapter uses one opaque identity namespace for backend SymbolIDs:
`symbol:SHA256("clangd-id\\0" + uppercase-SymbolID)`. `symbolInfo.id` and the
clangd call-hierarchy item's `data` identify the same backend entity. When only
USR is supplied, the adapter derives the same 8-byte SymbolID from SHA-1(USR),
as specified by [LLVM SymbolID](https://github.com/llvm/llvm-project/blob/llvmorg-22.1.6/clang-tools-extra/clangd/index/SymbolID.cpp).
An id/USR disagreement fails. No kind/name suffix is added to split a conflicting
backend identity. This replaces the former USR-first hash; the refresh configuration
version changes, and existing generations are never migrated in place.

`symbolInfo` is a candidate list, not a first-result winner. A call item's own
SymbolID must match before a candidate supplies identity, qualified name or source
ranges. A macro expansion selection can resolve to an enclosing class or macro;
those unrelated candidates are retained as audit evidence but never attached to
the called method. If none match, the call item's own ID/detail/location remain
the evidence; its location is a declaration anchor, not a fabricated definition.
Document observations select an unambiguous name-compatible candidate; ambiguity
or incompatible candidates without independent identity fail explicitly.
The known clangd display-name pair `(anonymous
namespace)` / `(anonymous)` is normalized only for namespace-kind observations.
Missing backend identity retains the existing source-anchor fallback, never an inherited
parent/caller/callee handle identity. Fallback does not promise equivalence across
different source sites when the backend supplies no shared identity evidence.
`prepareCallHierarchy` likewise must identify the requested backend identity,
rather than silently querying the first prepared entity. Genuine contradictions
within one ID remain subject to unchanged canonical conflict checks.

`SymbolObservation.provenance` is opaque adapter-owned audit JSON, not a query
schema or merge authority. `ClangdSemanticProvider.symbol_observations()` returns
all converted records including related endpoints. It retains endpoint item,
symbolInfo query location, all raw candidates, and the identity key actually used.
Refresh persists this evidence before final canonicalization so merge failures
remain diagnosable. Consumers do not parse clangd's schema to construct symbols.

The real Button failure was a macro-backed `UpdateTextColor` item from
`callHierarchy/outgoingCalls`: data `6F4910AA4E2EA311`, kind 6, detail
`OHOS::Ace::NG::TextLayoutProperty::UpdateTextColor`, selection at zero-based
`text_layout_property.h:146:4`. `symbolInfo` at that selection returned first the
class (`id=55BD34204665C459`, `usr=c:@N@OHOS@N@Ace@N@NG@S@TextLayoutProperty`), then
`ACE_DEFINE_PROPERTY_ITEM_WITH_GROUP`. The former `_call_hierarchy_symbol` →
`_symbol_info` → `_identity_key` path used that first class USR, producing the same
`symbol:c9614f6c711f66f62f77bb95e3e4feece31a0d7864838db50e8fad75b76e933f` as the
document class. It also incorrectly borrowed the class's name/ranges. This was
candidate misassociation at a macro site, not a hash collision or partial metadata.

## Owned process lifecycle

`ClangdSemanticProvider.set_progress_observer(callback)` is an optional public
telemetry boundary. Callback arguments are `(phase, current, total, file)` with
semantic_prepare/semantic_collect and completed-file counts over the same fixed
scope. Empty documentSymbol results still complete a file. The observer never
selects files or semantic facts; ordinary observer exceptions are isolated, while
KeyboardInterrupt propagates to the owner. No private adapter introspection is
needed for production refresh progress. Closing defers console SIGINT until the
bounded resource cleanup ends; repeated interrupts cannot strand owned clangd.

Protocol writes as well as reads have a timeout. Closing the provider does not
send an unbounded batch of didClose notifications; process exit releases its
documents. Graceful shutdown/exit has a two-second total grace period, followed
by bounded terminate/kill and worker join. Pipes are closed after the workers
stop. Close is idempotent and operates only on the process created by this provider.
Cleanup diagnostics remain available; cleanup exceptions annotate an existing
semantic/build exception rather than replacing it. If no original exception
exists, an unrecoverable cleanup failure propagates and prevents publication.

A single stdout reader continuously consumes protocol frames, discarding log/
diagnostic notifications rather than accumulating them while the caller writes.
stderr is continuously drained into an 8192-byte tail. Operational errors include
method/request id/URI, last successful operation, successful write/request/didOpen
counts, observed process exit code, stderr tail, semantic stage and prepared/
collected/current-open counts. A live process has exit_code=None, not a fabricated
exit reason. Exit observation has a bounded grace period. Reader workers are joined
during owned-process teardown. No document source text is included in diagnostics.

## C2 preparation consumer

The explicitly authorized C2 preparation consumes this public P1 boundary. It
records `p1-declaration-site-canonical-v1` in configuration provenance and retains
the fixed declaration/definition source closure over **all original observations**.
Normalization does not expand semantic scope or derive inventory from C2 output.
Unresolved real conflicts prevent publication. This change does not alter frozen
C2 expected or P2/C1 expected; it supplies canonical existing semantic evidence.
