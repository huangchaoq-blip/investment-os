# DEC-011: Dataset Publication and Versioning Contract

Status: ACCEPTED

Date: 2026-07-14

## Decision

Investment OS canonical datasets are published as complete immutable versions.
Every bootstrap or incremental update produces a complete new logical dataset
version, or reuses an existing identical published version. Published content
is never edited in place.

Publication is staged and atomic from the consumer perspective. A failed
update cannot replace, damage, or make unavailable the previous valid published
version. Only PUBLISHED versions may be consumed as Canonical Dataset evidence
by status, replay, daily, Facts, Strategy, Execution, or Projection.

DEC-013 defines a separate Local Historical Cache for noncanonical Investment
OS runtime use. That cache is outside this publication contract and cannot be
treated as a PUBLISHED Canonical Dataset or Research evidence.

This decision freezes the publication contract. It does not claim that the
staging store, latest index, lock protocol, or incremental updater is already
implemented.

## Context

RFC-004 defines the Data Platform boundary. DEC-010 selects Yahoo as a
PROVISIONAL implementation candidate and prohibits automatic fallback.
Existing canonical Replay already depends on immutable version identifiers,
including ds-v1-e5de63b1f28de1ad.

The current historical-ingestion implementation creates a complete dataset
directory in a temporary location and renames it into
data/raw/versioned/<dataset-version>. This is a useful prototype, but it does
not yet provide a formal published-index, incremental-update, lock, recovery,
or readiness contract.

DEC-004 remains authoritative for raw daily bars and historical data identity.
DEC-005 remains authoritative for price domains and corporate-action handling.

## 1. Immutable Publication

After publication:

- bars must not be edited in place;
- corporate actions must not be edited in place;
- normalization artifacts that affect interpretation must not be edited in
  place;
- manifest fields participating in content identity must not be edited;
- corrections require a new published dataset version;
- historical Replay continues to reference the original explicit version.

Operational metadata that does not participate in content identity may be
stored separately. It must not alter historical reproducibility, canonical
content, or the meaning of an existing version.

## 2. Update Produces a New Complete Version

Both full bootstrap synchronization and incremental synchronization produce a
complete, independently readable immutable dataset version.

Incremental means that acquisition may request only the new and overlap ranges.
It does not permit mutable published storage. An implementation may reuse
unchanged staged content internally, but the published logical contents must be
complete for every symbol and date covered by the version.

## 3. Dataset Lifecycle

The accepted lifecycle is:

    REQUESTED
      -> FETCHING
      -> NORMALIZING
      -> VALIDATING
      -> STAGED
      -> PUBLISHED

Failure states are:

    FETCH_FAILED
    NORMALIZATION_FAILED
    VALIDATION_FAILED
    PUBLICATION_FAILED
    BLOCKED

Only PUBLISHED datasets may be consumed as Canonical Dataset evidence by:

- status;
- replay;
- daily;
- Facts;
- Strategy;
- Execution;
- Projection.

A staged candidate is not a dataset version available to consumers.

The Local Historical Cache introduced by DEC-013 is not a staged candidate or
a PUBLISHED dataset. Its runtime lifecycle cannot modify, replace, or confer
status on this canonical publication lifecycle.

## 4. Staging Boundary and Store Layout

The recommended first-release local layout is:

    data/
      raw/
        versioned/
          <dataset-version>/
      staging/
        <update-id>/
      metadata/
        publication/
          latest.json
          versions.json
          locks/
            canonical-store.lock

data/raw/versioned remains the published-version root for compatibility with
existing Replay and ds-v1-e5de63b1f28de1ad. The new staging and publication
metadata locations are future implementation targets.

Requirements:

- staging is distinct from the published root;
- staging is never visible as a published version;
- consumers do not scan arbitrary staging paths;
- staged artifacts may be incomplete;
- validation runs against the staged candidate;
- failed staging does not alter the last valid publication;
- abandoned staging artifacts are safely cleanable after lock/lease review.

The exact directory names may evolve only through a compatible migration. The
published version path is never reused for a different content identity.

## 5. Atomic Publication

Publication must be atomic from the consumer perspective.

The required sequence is:

1. Finish acquisition.
2. Finish normalization.
3. Finish corporate-action processing required by the candidate.
4. Generate candidate manifest and validation artifacts.
5. Complete validation.
6. Calculate content identity and checksums.
7. Verify no published version has a conflicting identity.
8. Atomically move or rename the complete staged candidate into the published
   root.
9. Atomically update the latest publication index.
10. Record the publication outcome.

Consumers observe either the previous published state or the fully published
new state, never an intermediate state.

The first implementation must use a same-filesystem rename/move boundary where
atomic rename is relied upon. If this cannot be guaranteed, publication is
BLOCKED or uses an equivalent explicitly tested atomic mechanism.

## 6. Dataset Version Identity

The canonical format is:

    ds-v<dataset-schema-major>-<content-id>

The existing ds-v1-<16 lowercase hex> pattern remains compatible and valid.
The content ID is deterministic and content-addressed. The exact hash
algorithm, canonical serialization, truncation length, and collision handling
must be documented and tested before publication code is accepted.

The canonical content-identity bundle includes, where applicable:

- canonical bar content;
- canonical corporate-action evidence content;
- canonical action-normalization output and normalization version when it
  affects interpretation;
- normalized symbol universe;
- normalized date coverage;
- market and asset identity;
- dataset schema version;
- bar and action schema versions;
- adjustment/normalization contract versions;
- trading-calendar identity where it affects canonical content;
- provider identity where it changes data interpretation.

The bundle must be serialized deterministically. A change that requires new
identity inputs or incompatible canonicalization increments the dataset schema
major instead of reinterpreting a prior version.

Volatile operational values are excluded from content identity:

- retrieval timestamp;
- publication timestamp;
- staging path;
- runtime duration;
- log file path;
- retry count;
- process ID;
- operator display text.

This policy is compatible with the current v1 manifest checksum over canonical
bars and corporate actions. Existing v1 versions retain their historical
identity; a future publisher must not retroactively change their checksum or
name.

## 7. Duplicate-Content Behavior

When a fully validated candidate has the same canonical content identity as an
already published dataset:

- do not create a conflicting mutable copy;
- return REUSED_EXISTING;
- reference the existing immutable version;
- do not rewrite existing published contents;
- record that the update produced no new canonical content;
- update latest only if the deterministic publication-index policy says it
  should reference that identical version.

Identical content is an idempotent result, not a failed update.

## 8. Manifest Fields and Metadata Classes

The manifest contract extends the existing data manifest without redefining
DEC-004 raw-bar requirements.

### A. Content-identity fields

These fields are deterministic and participate in the identity bundle:

- dataset schema major;
- data class;
- provider identity where semantically relevant;
- market and asset type;
- normalized symbols and symbol count;
- normalized date coverage;
- bar/action schema versions;
- bar checksum;
- corporate-action checksum;
- canonical-action checksum when applicable;
- adjustment and normalization versions;
- trading-calendar identity when applicable.

### B. Immutable publication metadata

These are immutable after publication but do not change the content ID:

- update/request ID;
- update mode;
- previous dataset version;
- retrieval and publication timestamps;
- provider adapter version;
- provider qualification status at publication;
- requested and received symbols/ranges;
- validation result and report checksum/reference;
- safe provenance references;
- publication outcome.

### C. External operational and audit metadata

These remain outside immutable dataset content:

- staging paths;
- retry attempts and durations;
- lock diagnostics;
- log locations;
- operator-facing diagnostics;
- cleanup records.

Publication timestamps and runtime diagnostics must never give identical market
content a different content ID.

## 9. Latest Reference Policy

A separate mutable publication index locates the latest published version.

Latest means the most recently successfully published version on the one
canonical local publication line. It does not mean highest market coverage
date, daily-ready, or strategy-approved.

Requirements:

- latest is not a dataset;
- updating latest is atomic;
- latest references an existing PUBLISHED version;
- a failed update does not modify latest;
- latest contains its own update timestamp and publication provenance;
- Replay never uses latest when an explicit version is required;
- status may inspect latest offline;
- daily may select latest only after a separate readiness evaluation.

Readiness approval is not embedded permanently in immutable dataset identity.

## 10. Concurrency and Locking

Only one publisher for the canonical local store may proceed at a time.

The lock scope is the canonical local publication store, including staging
allocation, published-root rename, and latest-index update. A lock record must
contain at least update ID, process identity, host identity where available,
acquisition time, intended previous version, and lease/heartbeat information if
implemented.

A second update request returns BLOCKED_CONCURRENCY rather than publishing in
parallel. Read-only consumers continue reading the last PUBLISHED version while
an update is staged.

A lock is not deleted merely because it is old. Stale-lock recovery requires
an explicit audited recovery action that verifies the original publisher is no
longer active and that no partial publication is being promoted.

## 11. Validation Gate

A staged candidate cannot become PUBLISHED unless all publication-blocking
validation checks pass.

At minimum, publication is blocked for:

- invalid schema;
- checksum failure;
- duplicate symbol/date keys;
- invalid OHLC relationships;
- incomplete required watchlist coverage;
- missing required date range;
- unresolved blocking corporate action;
- corrupt manifest;
- provider response known to be incomplete;
- continuity violations classified as BLOCKER.

Warnings may be published only where the validation contract explicitly permits
them. The validation report is retained or referenced by immutable publication
metadata.

Validation never silently repairs an input record.

## 12. Corporate-Action Coupling

Bars and corporate actions that affect normalization publish as one coherent
dataset version.

The platform must not publish:

- new bars with old incompatible action data;
- adjusted signal data without normalization provenance;
- post-publication corporate-action edits.

A corporate-action correction produces a new dataset version. DEC-005 remains
authoritative for signal, execution, and accounting price domains.

## 13. Previous-Version Linkage

Every non-bootstrap published version records previous_dataset_version.

For the first bootstrap version, previous_dataset_version is null. The first
release supports one canonical local publication line and no arbitrary
branching. An intentional update from an older version is BLOCKED unless a
future decision explicitly introduces branching.

Replay may access every retained published version by its explicit identifier.

## 14. Retention Policy

Published versions are non-destructive by default.

During initial paper-operation development, retain all PUBLISHED versions.
Staging directories and failed temporary artifacts may be cleaned only after
the applicable failure and lock-recovery rules have been satisfied.

A dataset referenced by a Replay record, validation report, or paper-operation
record must not be silently deleted. latest is not a retention boundary.

Future archival or pruning requires explicit tooling and policy. The cost is
increased local storage, which is accepted in exchange for reproducibility and
auditability.

## 15. Corruption Behavior

If a published dataset fails checksum or structural verification:

- mark and report it as corrupted;
- do not mutate or silently repair it;
- do not use it for new daily decisions;
- cause Replay for that explicit version to fail closed;
- restore a verified copy or publish a new valid version for recovery;
- do not leave latest pointing to a known-corrupt version when a valid prior
  version is available.

Changing latest during corruption recovery is an explicit audited recovery
action. It is not a normal automatic side effect of a failed read.

## 16. Publication Result Contract

A publication operation returns a machine-implementable result containing:

- update/request ID;
- status;
- dataset version;
- previous dataset version;
- staging location or safe staging reference;
- published location;
- content checksum;
- manifest checksum;
- validation result/reference;
- whether new content was published;
- whether an existing identical version was reused;
- blocking/failure reasons;
- publication timestamp;
- provider provenance reference.

Accepted result statuses are:

    PUBLISHED_NEW
    REUSED_EXISTING
    BLOCKED_VALIDATION
    BLOCKED_CONCURRENCY
    FAILED_PUBLICATION
    FAILED_STORAGE

Provider acquisition and normalization failure states remain visible in the
operation record and map to a non-published result.

## 17. File and Path Safety

Publication code must:

- resolve all paths beneath the configured canonical store root;
- reject traversal components and unsafe externally supplied filenames;
- use temporary names that cannot be mistaken for published versions;
- require same-filesystem rename boundaries where atomic rename is used;
- apply restrictive local permissions appropriate to data and provenance;
- avoid publication through symlinks unless explicitly validated;
- perform disk-space checks before large staging writes where practical;
- fsync or apply documented equivalent durability steps before exposing the
  latest index for a local first release.

This contract does not require distributed-storage semantics.

## 18. Replay Compatibility

Existing canonical Replay remains able to load:

    ds-v1-e5de63b1f28de1ad

A future implementation preserves current dataset layout compatibility or
provides an explicit, tested compatibility adapter/migration path. It does not
mutate the existing dataset merely to fit a new publisher.

Replay always binds an explicit immutable dataset version and never resolves
latest implicitly.

## 19. Existing Dataset Migration Policy

Migration starts by verifying the existing manifest and checksums for
ds-v1-e5de63b1f28de1ad in its current
data/raw/versioned/<dataset-version> location.

If verified, it is registered as an existing PUBLISHED version without
regeneration, renaming, or content mutation. The migration record identifies
the import as a legacy-layout registration and records no predecessor.

Migration preserves exact Replay reproducibility. It does not make the dataset
daily-ready: freshness, provider qualification, watchlist readiness, and
corporate-action conditions remain independent gates.

## 20. Failure Behavior

| Failure | Required behavior |
| --- | --- |
| Disk full during staging | FAILED_STORAGE; clean only safe temporary artifacts; latest unchanged |
| Disk full during publication | FAILED_STORAGE or FAILED_PUBLICATION; no partial version visible; latest unchanged |
| Interrupted normalization or validation | Candidate remains non-published; recover after lease review |
| Interrupted rename/index update | Verify published root and index separately; perform audited recovery; never infer success |
| Checksum mismatch after write | VALIDATION_FAILED; do not publish or repair in place |
| Latest-index corruption | Report corruption; use explicit verified version for recovery; do not silently choose one |
| Stale lock | BLOCKED until explicit audited recovery |
| Duplicate update request | Acquire/reuse result deterministically; do not publish in parallel |
| Identical-content update | REUSED_EXISTING; no content rewrite |
| Manifest serialization failure | FAILED_PUBLICATION; latest unchanged |

No failure may expose a partial dataset as PUBLISHED.

## 21. Security Boundary

Dataset publication must not embed provider credentials, access tokens, private
configuration values, or raw sensitive HTTP headers. Provenance contains safe
provider identifiers and references only.

## 22. Consequences

### Benefits

- Reproducible Replay.
- Safe failure recovery.
- No partial publication.
- Deterministic identities.
- Auditable corrections.
- Stable daily consumption once readiness exists.

### Costs

- More local storage.
- Each correction creates a new version.
- Publication requires staging space.
- Update implementation is more complex than overwriting files.
- Retention management is deferred.

## 23. Rejected Alternatives

1. Updating published Parquet or CSV files in place.
2. Using a mutable database snapshot with no immutable version identity.
3. Assigning versions only from timestamps.
4. Including publication timestamps in content identity.
5. Letting daily read staging data.
6. Deleting prior versions whenever latest advances.
7. Silently repairing published datasets.
8. Letting Replay fetch or patch missing data.
9. Publishing bars before corporate-action processing finishes.

All are rejected because they weaken reproducibility, integrity, or
consumer-visible atomicity.

## Status

This decision is ACCEPTED.

The accepted contract freezes immutable version publication, atomic
consumer-visible publish, content-addressed identity, idempotent duplicate
handling, a separate latest index, one-writer locking, non-destructive
retention, and compatibility for ds-v1-e5de63b1f28de1ad.

It does not implement those mechanisms or mark the existing dataset
daily-ready.
