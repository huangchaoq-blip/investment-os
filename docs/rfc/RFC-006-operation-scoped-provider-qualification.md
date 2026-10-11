# RFC-006: Operation-Scoped Provider Qualification

Status: Accepted

Accepted: 2026-07-17

Capability: Data Platform - Provider Qualification

Priority: P0

Architecture impact: None - implements the accepted DEC-010 amendment

Breaking change: Internal qualification decision and evidence schemas are
versioned; existing historical reports remain readable but are not silently
reinterpreted

## Objective

Implement the provider-independent qualification model accepted by DEC-010.

The implementation separates:

1. Provider Capability Evidence;
2. versioned Operation Qualification Profiles; and
3. deterministic Qualification Decisions.

The evaluator must determine whether accepted provider evidence satisfies one
declared operation profile and scope. It must not call a Provider, access the
network, publish a Dataset, decide Dataset Readiness, or contain provider-specific
logic.

## Governing Contracts

This RFC implements and does not reinterpret:

- [DEC-004 Historical Market Data Contract](../omitted-archive-references.md);
- [DEC-005 Adjusted Price Processing Contract](../omitted-archive-references.md);
- [DEC-010 Canonical Provider and Provider-Fallback Policy](../omitted-archive-references.md);
- [DEC-011 Dataset Publication and Versioning Contract](../../decisions/DEC-011-dataset-publication-and-versioning-contract.md);
- [DEC-012 Daily Readiness Contract](../omitted-archive-references.md); and
- [RFC-004 Investment OS Data Platform](../omitted-archive-references.md).

DEC-010 remains the sole authority for provider qualification requirements,
profiles, statuses, fallback policy, and profile evolution. This RFC defines how
the accepted model is represented, evaluated, serialized, and verified.

## Problem

The current qualification implementation performs provider acquisition and
qualification aggregation in one service. It also encodes target applicability
through fixed internal check lists. That implementation cannot represent the
DEC-010 amendment completely because it does not provide:

- a complete capability evidence catalogue independent of one diagnostic run;
- immutable versioned profile data;
- explicit `Required`, `Conditional`, and `Future` requirement semantics;
- deterministic conditional applicability evidence;
- Consumer and Purpose traceability in the executable Contract;
- profile-scoped decisions and decision identity; or
- profile and decision provenance for publication consumers.

Provider acquisition evidence remains necessary, but evidence collection and
operation permission are different responsibilities.

## Scope

Implement:

- immutable Provider Capability Evidence records;
- an immutable Provider Capability Evidence Catalogue;
- immutable Operation Qualification Profiles;
- the two V1 profiles accepted by DEC-010;
- immutable Qualification Scope and conditional-applicability evidence;
- one provider-independent Qualification Evaluator;
- immutable per-requirement results;
- immutable Qualification Decisions;
- deterministic canonical serialization and fingerprints;
- safe compatibility reading for existing qualification reports; and
- offline tests for all profile and decision rules.

The RFC may refactor the current qualification service so that provider
diagnostics produce evidence and the provider-independent evaluator produces the
decision. It must preserve historical report readability and fail-closed
behavior.

## Non-Goals

This RFC does not:

- implement or modify Yahoo, J-Quants, or another Provider adapter;
- define API endpoints, field mappings, SDK use, authentication lifecycle,
  pagination mechanics, retries, or cache behavior;
- collect live evidence;
- qualify or promote a Provider;
- modify the profiles accepted by DEC-010;
- modify DEC-012 Readiness semantics or gate priority;
- publish or mutate a Dataset;
- modify the Local Historical Cache;
- introduce provider fallback;
- implement Strategy, Facts, Replay, Execution, Portfolio, or Reporting; or
- authorize real-money operation.

## Architectural Boundary

The required flow is:

```text
Provider Adapter / Diagnostic / Review
                |
                v
Provider Capability Evidence Catalogue
                +
Operation Qualification Profile
                +
Qualification Scope and Applicability Evidence
                |
                v
Provider-independent Qualification Evaluator
                |
                v
Qualification Decision
```

Provider-specific components may create evidence records. They must not decide
which requirements participate in an operation profile.

The evaluator receives evidence only. It must have no Provider interface, SDK,
HTTP client, credential, filesystem discovery, current-time call, or implicit
global registry dependency.

## Qualification Evaluator Permanent Non-Responsibilities

The Qualification Evaluator never owns or performs:

- Provider API access;
- HTTP or another transport;
- Provider SDK integration;
- authentication or credential lifecycle;
- retry, backoff, pagination, or rate-limit handling;
- Local Historical Cache access;
- Dataset loading, creation, mutation, or validation;
- Dataset publication or Publisher orchestration;
- Readiness evaluation;
- CLI or UI behavior;
- logging, metrics emission, tracing, or audit persistence; or
- status-registry mutation.

Those responsibilities may produce inputs for, or consume outputs from, the
evaluator through separate boundaries. They must not be injected into the
evaluator as collaborators, callbacks, services, or hidden globals.

## Purity and Determinism

The Qualification Evaluator is a pure function of exactly four explicit inputs:

- Capability Catalogue;
- Qualification Profile;
- Scope; and
- Applicability Evidence.

For equivalent normalized values of those four inputs, the evaluator must
return a completely equivalent Qualification Decision, including byte-identical
canonical serialization, requirement ordering, blocking reasons, decision ID,
and fingerprint.

The evaluator must not:

- mutate an input or an object reachable from an input;
- read current time, randomness, environment variables, process state,
  filesystem state, network state, or mutable global state;
- maintain state between calls;
- persist, cache, memoize with observable state, log, trace, or emit metrics;
- choose a Provider or fallback; or
- make output depend on invocation order or concurrent execution.

Its only observable outcomes are the returned immutable Qualification Decision
or the explicit qualification Contract error defined by this RFC.

## Canonical Schema Versions

V1 introduces these schema identities:

```text
provider-capability-evidence-v1
provider-capability-catalogue-v1
operation-qualification-profile-v1
provider-qualification-decision-v1
```

Schema identity is stored in serialized content and never inferred from a file
name or directory.

Versioning rules are:

- Evidence, Catalogue, Profile, and Decision content is immutable after
  creation.
- Schema version participates in canonical serialization and fingerprinting.
- A change to required fields, field semantics, normalization, canonical
  ordering, or fingerprint inputs requires a new schema version.
- Catalogue schema evolution does not rewrite or relabel an Evidence record.
- Any profile requirement, classification, acceptance policy, applicability
  policy, Consumer, Purpose, or requested-status change requires a new profile
  version under DEC-010.
- A Decision permanently records the exact Evidence, Catalogue, Profile, and
  Decision schema versions it evaluated.
- A future Decision schema must not change the meaning or identity of a prior
  Decision.
- Readers may retain explicit support for older versions. Unsupported future
  versions fail through the Contract-error boundary and are never interpreted
  as the latest version.
- Migration creates a new object with explicit provenance. It never mutates an
  existing Evidence record, Catalogue, Profile, or Decision in place.

## Provider Capability Evidence

### Evidence record

One immutable evidence record represents the assessed state of one capability
for one provider/adapter and evidence scope.

Required fields:

| Field | Contract |
| --- | --- |
| `schema_version` | `provider-capability-evidence-v1` |
| `capability_id` | Stable capability identity defined by this RFC |
| `provider_id` | Normalized non-empty provider identity |
| `adapter_version` | Non-empty adapter or evidence-boundary version |
| `support_status` | `SUPPORTED`, `PARTIAL`, `UNSUPPORTED`, or `UNKNOWN` |
| `evidence_assessment` | DEC-004 evidence assessment: `QUALIFIED`, `PARTIAL`, `UNSUITABLE`, or `UNKNOWN` |
| `coverage` | Explicit market, asset, universe, date, and permitted-use scope |
| `limitations` | Immutable ordered-safe collection of disclosed limitations |
| `evidence_references` | Immutable non-secret evidence identities |
| `assessed_at` | Timezone-aware assessment timestamp supplied by the upstream evidence producer |
| `supersedes` | Optional prior evidence identity |
| `evidence_id` | Deterministic identity for canonical record content |

Credentials, tokens, cookies, raw authorization material, unrestricted provider
responses, and exception representations are prohibited.

### Coverage

Evidence coverage contains:

- market;
- asset type;
- symbols or an explicit universe identity;
- inclusive start and end date where date coverage applies;
- permitted-use scope;
- provider contract or entitlement identity when applicable; and
- declared limitation boundaries.

Coverage containment is deterministic:

- market and asset type must match exactly;
- symbol coverage must contain every symbol required by the decision scope;
- date coverage must contain the decision interval when the capability is
  date-dependent;
- permitted use must include the requested operation; and
- provider and adapter identities must match exactly.

Absence of coverage evidence never implies full coverage.

### Evidence catalogue

The immutable catalogue contains:

- catalogue schema version;
- provider ID;
- adapter version;
- catalogue evidence version;
- evidence records keyed by unique `capability_id`;
- catalogue creation metadata; and
- catalogue fingerprint.

Duplicate active records for the same capability are invalid. Superseded records
may remain in historical storage but only one explicitly selected record may be
active in one decision catalogue.

Missing catalogue entries are evaluated as unknown evidence. The evaluator must
not synthesize successful capability records.

## Stable Capability Identities

V1 uses these provider-independent identities:

```text
PROVIDER_IDENTITY_AUTHENTICATION
SYMBOL_UNIVERSE_COVERAGE
DATE_RANGE_MINIMUM_HISTORY
CANONICAL_OHLCV_COMPLETENESS
TRADING_DATE_CALENDAR_COMPATIBILITY
RAW_ADJUSTED_PRICE_SEMANTICS
SPLIT_REVERSE_SPLIT_EVIDENCE
REVISION_CORRECTION_BEHAVIOR
REPRODUCIBILITY
PROVENANCE
PERMITTED_USE
FAILURE_BEHAVIOR
PAGINATION_RATE_LIMIT_COMPLETENESS
INCREMENTAL_ACQUISITION_OVERLAP
OPERATIONAL_AVAILABILITY_PUBLICATION_LAG
SYMBOL_CHANGE_HANDLING
DELISTING_HANDLING
UNSUPPORTED_LIFECYCLE_DETECTION
CASH_DIVIDEND_EVIDENCE
MERGER_ECONOMIC_TERMS_EVIDENCE
SPINOFF_ALLOCATION_EVIDENCE
DIVIDEND_ENTITLEMENT_PAYMENT_EVIDENCE
```

Provider adapters must map evidence to these identities outside the evaluator.
The evaluator must not branch on provider ID.

## Operation Qualification Profile

### Profile contract

An immutable profile contains:

| Field | Contract |
| --- | --- |
| `schema_version` | `operation-qualification-profile-v1` |
| `profile_id` | Stable operation profile identity |
| `profile_version` | Explicit immutable profile version |
| `requested_operational_status` | Existing DEC-010 target status |
| `operation_scope` | Declared operation and permitted-use scope |
| `market` | Profile market |
| `asset_type` | Profile asset type |
| `requirements` | Immutable unique capability requirements |
| `profile_fingerprint` | Deterministic fingerprint of canonical profile content |

One requirement contains:

- `capability_id`;
- classification: `Required`, `Conditional`, or `Future`;
- Consumer;
- Purpose;
- evidence acceptance policy identity;
- applicability policy identity for `Conditional`; and
- planned capability or future Consumer for `Future`.

Validation rules:

- every capability appears at most once per profile;
- `Required` has Consumer, Purpose, and acceptance policy;
- `Conditional` additionally has an applicability policy;
- `Future` has a planned capability or future Consumer and no active
  applicability policy;
- unknown classification values fail explicitly;
- a profile cannot request real-money permission; and
- profile content is not mutable through configuration.

### Accepted V1 profile projections

The following is the executable projection of DEC-010. The DEC remains
authoritative if a transcription conflict is discovered.

The canonical identities and requested statuses are:

| Profile identity | `profile_version` | Requested operational status |
| --- | ---: | --- |
| `DAILY_PAPER_DECISION_V1` | `1` | `QUALIFIED_FOR_DAILY_PAPER_OPERATION` |
| `RESEARCH_REPLAY_V1` | `1` | `QUALIFIED_FOR_RESEARCH` |

`profile_id` stores the complete canonical identity shown above. The explicit
version field must agree with that identity and must not be inferred from a file
name.

| Capability ID | `DAILY_PAPER_DECISION_V1` | `RESEARCH_REPLAY_V1` |
| --- | --- | --- |
| `PROVIDER_IDENTITY_AUTHENTICATION` | Required | Required |
| `SYMBOL_UNIVERSE_COVERAGE` | Required | Required |
| `DATE_RANGE_MINIMUM_HISTORY` | Required | Required |
| `CANONICAL_OHLCV_COMPLETENESS` | Required | Required |
| `TRADING_DATE_CALENDAR_COMPATIBILITY` | Required | Required |
| `RAW_ADJUSTED_PRICE_SEMANTICS` | Required | Required |
| `SPLIT_REVERSE_SPLIT_EVIDENCE` | Required | Required |
| `REVISION_CORRECTION_BEHAVIOR` | Required | Required |
| `REPRODUCIBILITY` | Required | Required |
| `PROVENANCE` | Required | Required |
| `PERMITTED_USE` | Required | Required |
| `FAILURE_BEHAVIOR` | Required | Required |
| `PAGINATION_RATE_LIMIT_COMPLETENESS` | Required | Required |
| `INCREMENTAL_ACQUISITION_OVERLAP` | Required | Future |
| `OPERATIONAL_AVAILABILITY_PUBLICATION_LAG` | Required | Future |
| `SYMBOL_CHANGE_HANDLING` | Conditional | Conditional |
| `DELISTING_HANDLING` | Conditional | Conditional |
| `UNSUPPORTED_LIFECYCLE_DETECTION` | Conditional | Conditional |
| `CASH_DIVIDEND_EVIDENCE` | Future | Future |
| `MERGER_ECONOMIC_TERMS_EVIDENCE` | Future | Future |
| `SPINOFF_ALLOCATION_EVIDENCE` | Future | Future |
| `DIVIDEND_ENTITLEMENT_PAYMENT_EVIDENCE` | Future | Future |

The implementation must encode Consumer, Purpose, applicability policy, future
Consumer, and acceptance policy from DEC-010 in the profile data. It must not
encode only this classification table.

### Executable Consumer traceability

The accepted V1 profiles must encode the following Consumer and Purpose values
as profile data. This table is an implementation projection of DEC-010, not a
second source of architecture authority.

| Capability ID | Consumer(s) | Purpose |
| --- | --- | --- |
| `PROVIDER_IDENTITY_AUTHENTICATION` | Canonical daily update; canonical Research ingestion | Bind acquisition to the explicitly selected provider and authenticated entitlement without hidden source substitution. |
| `SYMBOL_UNIVERSE_COVERAGE` | Readiness; Facts; Replay | Prove complete declared-universe coverage and prohibit partial-universe decisions or research. |
| `DATE_RANGE_MINIMUM_HISTORY` | Facts; Replay | Supply the required feature lookback and declared research interval. |
| `CANONICAL_OHLCV_COMPLETENESS` | Facts; Strategy; Execution; Replay | Supply structurally valid complete daily observations without inferred or partial bars. |
| `TRADING_DATE_CALENDAR_COMPATIBILITY` | Readiness; Replay | Interpret exchange sessions deterministically and reject invalid, duplicate, missing, or future records for the declared scope. |
| `RAW_ADJUSTED_PRICE_SEMANTICS` | Facts; Execution; Replay | Prevent mixing raw execution prices, signal-analysis prices, and provider-adjusted evidence. |
| `SPLIT_REVERSE_SPLIT_EVIDENCE` | Point-in-Time Facts; Execution; Replay | Preserve split-continuous signals and prevent split discontinuities from becoming false trading events. |
| `REVISION_CORRECTION_BEHAVIOR` | Canonical daily update; canonical Research ingestion | Detect corrections and prevent accepted evidence from changing silently. |
| `REPRODUCIBILITY` | Publication verification; Replay evidence | Establish comparable evidence for equivalent requests and normalization contracts. |
| `PROVENANCE` | Dataset Publisher; Replay; audit consumers | Bind evidence to provider, adapter, request, normalization, and retrieval provenance without secrets. |
| `PERMITTED_USE` | Canonical daily update; canonical Research ingestion | Confirm the declared personal daily-paper or research use is permitted. |
| `FAILURE_BEHAVIOR` | Canonical daily update; canonical Research ingestion | Preserve explicit fail-closed evidence for transport, provider, malformed, incomplete, unsupported, and partial failures. |
| `PAGINATION_RATE_LIMIT_COMPLETENESS` | Canonical daily update; canonical Research ingestion | Prove transport boundaries cannot silently truncate the universe or interval. |
| `INCREMENTAL_ACQUISITION_OVERLAP` | Canonical daily update | Acquire completed sessions and corrections without mutating a published Dataset. |
| `OPERATIONAL_AVAILABILITY_PUBLICATION_LAG` | Canonical daily update; Readiness configuration producer | Establish repeated operational support and the declared provider-publication-lag evidence. |
| `SYMBOL_CHANGE_HANDLING` | Readiness; Replay | Preserve identity and continuity when the applicability policy establishes that a symbol change affects scope. |
| `DELISTING_HANDLING` | Readiness; Replay | Distinguish an ended listing from missing or stale data when delisting affects scope. |
| `UNSUPPORTED_LIFECYCLE_DETECTION` | Readiness; Replay | Block rather than invent semantics when an unsupported lifecycle event affects scope. |

Every `Future` profile entry must encode the following planned Consumer:

| Capability ID and profile | Future capability or Consumer |
| --- | --- |
| `INCREMENTAL_ACQUISITION_OVERLAP` in `RESEARCH_REPLAY_V1` | Future incremental Research Dataset refresh |
| `OPERATIONAL_AVAILABILITY_PUBLICATION_LAG` in `RESEARCH_REPLAY_V1` | Future operational Research ingestion service |
| `CASH_DIVIDEND_EVIDENCE` in both V1 profiles | Dividend-aware Portfolio/Daily reporting and total-return Research Performance |
| `MERGER_ECONOMIC_TERMS_EVIDENCE` in both V1 profiles | Portfolio lifecycle processing and adjustment-safe Research accounting |
| `SPINOFF_ALLOCATION_EVIDENCE` in both V1 profiles | Portfolio lifecycle processing and adjustment-safe Research accounting |
| `DIVIDEND_ENTITLEMENT_PAYMENT_EVIDENCE` in both V1 profiles | Portfolio cash ledger and total-return Research Performance |

Profile construction fails explicitly when required traceability content is
missing or differs from the accepted profile projection.

## Qualification Scope

One immutable decision scope contains:

- provider ID;
- adapter version;
- profile ID and version;
- market and asset type;
- required symbols or universe identity and resolved symbols;
- inclusive evidence date range;
- permitted-use identity;
- applicable provider contract or entitlement identity when required by the
  evidence policy.

Equivalent normalized scope inputs must compare equal. Symbol ordering and
duplicate symbols must not change the decision. Business dates declared in the
Scope are domain data; evaluator invocation time is not an input and must not be
read or recorded by the evaluator.

## Conditional Applicability Evidence

Conditional applicability is represented independently from capability support.
For each conditional requirement, the caller supplies an immutable result:

```text
APPLIES
DOES_NOT_APPLY
UNKNOWN
```

The result includes:

- capability ID;
- applicability policy identity;
- scope identity;
- evidence references;
- safe reason; and
- deterministic fingerprint.

Rules:

- `APPLIES` activates the requirement and applies the same fail-closed evidence
  rules as `Required`;
- `DOES_NOT_APPLY` produces an explicit non-blocking requirement result;
- `UNKNOWN`, missing evidence, policy mismatch, or scope mismatch blocks the
  decision; and
- absence of a provider event is not automatically evidence that a condition
  does not apply.

The evaluator does not detect corporate actions or inspect market data. That
evidence is produced upstream.

V1 freezes these applicability policy identities:

| Capability ID | Applicability policy | `APPLIES` | `DOES_NOT_APPLY` |
| --- | --- | --- | --- |
| `SYMBOL_CHANGE_HANDLING` | `SYMBOL_CHANGE_AFFECTS_SCOPE_V1` | Accepted evidence identifies a symbol change affecting a required symbol or the decision interval. | Accepted identity/lifecycle evidence covers the complete scope and establishes that no symbol change affects it. |
| `DELISTING_HANDLING` | `DELISTING_AFFECTS_SCOPE_V1` | Accepted evidence identifies a delisting or delisting lifecycle affecting a required symbol or interval. | Accepted listing-status evidence covers the complete scope and establishes that no delisting affects it. |
| `UNSUPPORTED_LIFECYCLE_DETECTION` | `UNSUPPORTED_LIFECYCLE_AFFECTS_SCOPE_V1` | Accepted evidence or an unresolved lifecycle anomaly identifies a merger, spin-off, special distribution, or other unsupported event that may affect required evidence. | Accepted lifecycle evidence and validation cover the complete scope and establish that no unsupported lifecycle event affects it. |

If the evidence satisfies neither positive condition, the result is `UNKNOWN`.
The evaluator must not convert missing events, an empty provider response, or
absence of a known action record into `DOES_NOT_APPLY`.

## Evidence Acceptance

V1 defines one strict scope-aware acceptance policy for activated requirements:

```text
STRICT_SCOPE_QUALIFIED_V1
```

An activated requirement is satisfied only when:

1. exactly one active evidence record exists for its capability;
2. provider and adapter identities match the decision scope;
3. evidence coverage contains the complete decision scope;
4. permitted-use evidence covers the requested operation where applicable;
5. support is `SUPPORTED`;
6. DEC-004 evidence assessment is `QUALIFIED` for that scope;
7. no recorded limitation invalidates the requirement acceptance criteria; and
8. every referenced evidence identity is structurally valid.

`PARTIAL`, `UNSUPPORTED`, `UNKNOWN`, `UNSUITABLE`, missing, expired where an
expiry rule applies, or scope-incompatible evidence blocks an activated
requirement. V1 does not contain a generic exception that converts `PARTIAL`
evidence into success.

A later DEC amendment may define a more specific acceptance policy for a
versioned profile. Implementation code must not do so independently.

## Public Evaluation API

Provide one public, provider-independent service entry point equivalent to:

```text
evaluate(
    catalogue,
    profile,
    scope,
    applicability_evidence,
) -> QualificationDecision
```

The exact module layout is implementation-defined. The public semantic contract
is not.

The service must be:

- pure with respect to its inputs;
- deterministic;
- side-effect free;
- offline;
- independent of Provider interfaces; and
- unable to mutate provider operational status.

It must not log, trace, emit metrics, persist, cache, or modify any input. A
caller may present or persist the returned Decision outside this boundary.

Malformed Contract input fails explicitly through one stable qualification
contract error boundary. Evidence insufficiency is a normal blocked Decision,
not an exception.

## Requirement Decision Results

Every profile requirement produces exactly one immutable result in stable
capability-ID order.

Permitted result statuses are:

```text
SATISFIED
BLOCKED
NOT_APPLICABLE
NOT_ACTIVATED
```

Mapping:

- satisfied `Required` or applicable `Conditional` -> `SATISFIED`;
- insufficient activated evidence -> `BLOCKED`;
- `Conditional` with accepted `DOES_NOT_APPLY` evidence -> `NOT_APPLICABLE`;
- `Future` -> `NOT_ACTIVATED`.

Each result includes capability ID, classification, applicability outcome,
acceptance-policy identity, evidence IDs, safe summary, blockers, and warnings.

`Future` results must remain visible. They must not be omitted merely because
they do not affect the current decision.

## Qualification Decision Contract

The immutable decision contains at least:

- decision schema version;
- deterministic decision ID;
- provider ID and adapter version;
- profile ID, profile version, and profile fingerprint;
- exact Evidence, Catalogue, Profile, and Decision schema versions;
- requested operational status;
- decision scope;
- catalogue fingerprint;
- ordered requirement results;
- overall outcome: `QUALIFIED` or `BLOCKED`;
- blocking reasons and warnings;
- evaluated evidence identities;
- decision fingerprint.

The outcome is `QUALIFIED` only when every `Required` and every applicable
`Conditional` requirement is `SATISFIED`. `Future` and accepted non-applicable
conditional requirements do not block.

A successful decision is evidence that the requested operational status is
supported for the recorded profile and scope. It does not mutate a Provider
registry, broaden the decision scope, approve real-money use, publish a Dataset,
or make a Dataset `READY`.

## Deterministic Serialization and Identity

Canonical serialization uses UTF-8 JSON with:

- sorted object keys;
- stable capability-ID ordering;
- normalized symbol ordering;
- Unicode strings normalized to NFC;
- ISO-8601 dates and timestamps normalized to UTC with a `Z` suffix;
- compact separators `,` and `:` with no insignificant whitespace or trailing
  newline;
- no NaN, Infinity, environment paths, durations, random IDs, or secret values;
  and
- the fingerprint algorithm label `sha256` and lowercase hexadecimal digests.

Canonical JSON is encoded directly as UTF-8 and does not escape non-ASCII
characters solely to construct an identity. Maps are ordered lexicographically;
collections whose Contract semantics are unordered are normalized to their
declared stable ordering before serialization.

Identity construction excludes the identity field being constructed:

- Evidence hash payload excludes `evidence_id`;
- Catalogue hash payload excludes `catalogue_fingerprint`;
- Profile hash payload excludes `profile_fingerprint`;
- Applicability Evidence hash payload excludes its `fingerprint`; and
- Decision hash payload excludes `decision_id` and `decision_fingerprint`.

The resulting public values are:

```text
evidence_id = provider-capability-evidence-v1:<sha256 hex digest>
catalogue_fingerprint = sha256:<sha256 hex digest>
profile_fingerprint = sha256:<sha256 hex digest>
applicability_fingerprint = sha256:<sha256 hex digest>
decision_fingerprint = sha256:<sha256 hex digest>
decision_id = provider-qualification-decision-v1:<same decision hex digest>
```

The Decision digest is computed once from its canonical hash payload and reused
for both `decision_fingerprint` and `decision_id` with their respective prefixes.

Decision identity is derived only from:

- Decision schema version;
- Catalogue fingerprint;
- Profile fingerprint;
- canonical normalized Scope;
- conditional Applicability Evidence fingerprints in capability-ID order; and
- the resulting ordered requirement results.

Evidence assessment timestamps already contained in the immutable Catalogue are
part of Catalogue data. Evaluator invocation time, current time, report creation
time, runtime metadata, and an independently generated timestamp are not
Decision fields or identity inputs.

Repeated evaluation of equivalent normalized inputs produces identical
serialized content, decision ID, and fingerprint.

Report output path, process ID, runtime duration, log text, and filesystem
ordering must not affect identity.

## Evaluation Algorithm

The evaluator performs these steps in order:

1. Validate catalogue, profile, scope, and applicability evidence structure.
2. Verify provider, adapter, profile, market, asset, and scope identities.
3. Iterate all profile requirements in stable capability-ID order.
4. Emit `NOT_ACTIVATED` for `Future` requirements.
5. Resolve every `Conditional` requirement from explicit applicability
   evidence; block missing, mismatched, or `UNKNOWN` applicability.
6. Evaluate evidence for every `Required` and applicable `Conditional`
   requirement using its acceptance policy.
7. Emit one result for every requirement.
8. Collect blocking reasons in stable capability-ID and reason order.
9. Produce `QUALIFIED` only when no activated requirement is blocked.
10. Serialize and fingerprint the complete decision deterministically.

The evaluator must evaluate all requirements and report all blockers. It must
not stop after the first evidence failure.

## Failure Semantics

The implementation distinguishes:

### Contract failure

Examples:

- duplicate capability identities;
- unknown classification;
- malformed profile;
- unsupported schema version;
- inconsistent provider identity inside one catalogue; or
- missing required structural fields.

These fail explicitly without producing a misleading Qualification Decision.

### Qualification block

Examples:

- missing activated evidence;
- unknown or partial support;
- insufficient scope coverage;
- failed permitted-use review;
- unknown conditional applicability; or
- an applicability/evidence policy mismatch.

These produce a complete `BLOCKED` decision with all safe blocking reasons.

Neither category may fall back to another Provider or silently ignore a
requirement.

## Existing Report Compatibility

Existing provider qualification reports, including the current v6 report
schema and older supported reports, remain immutable historical evidence.

A compatibility reader may extract evidence candidates from an older report,
but it must:

- preserve the original report and schema identity;
- record the source report evidence ID;
- never infer missing profile, scope, capability, or applicability evidence;
- mark unavailable fields as unknown;
- validate extracted evidence under the V1 catalogue Contract; and
- require a new Qualification Decision against an explicit V1 profile.

An old report's prior overall result is not automatically a V1 decision.

## Publication and Readiness Integration Boundary

A future implementation slice may persist successful decision provenance with a
published Dataset as required by DEC-010. At minimum it must preserve:

- profile ID and version;
- decision ID and fingerprint;
- provider and adapter identity;
- evaluated scope; and
- requested operational status.

DEC-011 remains responsible for publication. DEC-012 Readiness remains
responsible for publication, integrity, freshness, coverage, validation, and
corporate-action gates. Readiness must not reconstruct or rerun provider
qualification from raw evidence.

This RFC does not change a Readiness state, priority, or exit code.

## Security and Privacy

Evidence and decisions must be safe for local audit and machine-readable output.
They must never contain:

- API keys, tokens, passwords, cookies, or authorization headers;
- email addresses or account identifiers from private configuration;
- unrestricted raw provider payloads;
- stack traces or exception representations; or
- private configuration paths when a stable evidence identity is sufficient.

Safe redaction must occur before evidence enters the catalogue. The evaluator is
not a secret-scrubbing fallback for unsafe upstream evidence.

## Acceptance Criteria

Implementation is complete when:

- the three DEC-010 layers have separate immutable representations;
- the evaluator has no Provider or network dependency;
- both V1 profiles exactly project the accepted DEC-010 requirements;
- every requirement carries the required traceability fields;
- all catalogue capabilities remain visible in decisions;
- every activated requirement is evaluated fail-closed;
- unknown conditional applicability blocks;
- `Future` requirements do not block and remain visible;
- qualification is scoped by provider, adapter, profile, market, asset,
  universe, date, and permitted use;
- equivalent input produces byte-stable decisions and fingerprints;
- the evaluator neither reads nor records invocation time;
- the evaluator does not mutate inputs, persist, cache, log, trace, or emit
  metrics;
- all evidence failures are reported, not only the first;
- malformed Contracts fail explicitly;
- older reports remain readable without silent V1 qualification;
- no Provider status is upgraded automatically;
- no fallback, publication, Dataset mutation, or Readiness semantic change is
  introduced; and
- existing provider, publisher, readiness, CLI, ingestion, manifest, and Replay
  regressions remain green.

## Verification

All automated verification is offline.

### Evidence and catalogue tests

- immutable evidence records;
- deterministic evidence IDs and catalogue fingerprints;
- stable serialization independent of input ordering;
- complete coverage and insufficient-coverage behavior;
- duplicate capability rejection;
- provider/adapter identity mismatch rejection;
- unsupported schema rejection;
- unknown capability evidence remains visible;
- supersession selection is explicit; and
- secrets and unsafe values are rejected or absent before evaluation.

### Profile tests

- exact `DAILY_PAPER_DECISION_V1` projection;
- exact `RESEARCH_REPLAY_V1` projection;
- unique requirement identities;
- Required Consumer/Purpose enforcement;
- Conditional applicability-policy enforcement;
- Future Consumer enforcement;
- profile immutability and deterministic fingerprint;
- unknown classification rejection; and
- real-money profile rejection.

### Decision tests

- all Required evidence satisfied -> `QUALIFIED`;
- one and multiple Required blockers -> complete stable `BLOCKED` decision;
- missing required evidence -> `BLOCKED`;
- `PARTIAL`, `UNSUPPORTED`, `UNKNOWN`, and `UNSUITABLE` activated evidence ->
  `BLOCKED`;
- conditional `APPLIES` with qualified evidence -> `SATISFIED`;
- conditional `APPLIES` with insufficient evidence -> `BLOCKED`;
- conditional `DOES_NOT_APPLY` -> `NOT_APPLICABLE`;
- conditional `UNKNOWN`, missing, or mismatched -> `BLOCKED`;
- Future evidence missing or unknown -> `NOT_ACTIVATED` without blocking;
- a complete catalogue with unrelated unknown Future capabilities can still
  qualify the current profile;
- scope mismatch blocks without widening evidence;
- symbol and evidence input order do not affect output;
- repeated equivalent evaluation is byte-identical;
- changed profile, evidence, scope, or applicability evidence changes decision
  identity deterministically;
- different invocation times with identical four inputs do not change output;
- no current time, network, Provider, filesystem, or mutable-global access;
- no logging, tracing, metrics, persistence, cache, CLI, or UI dependency;
- no automatic Provider status mutation; and
- no provider-ID-specific branch behavior.

### Compatibility and regression tests

- supported historical qualification reports remain readable;
- historical overall results are not treated as V1 decisions;
- current diagnostic evidence can be represented without Provider-specific
  evaluator logic;
- publisher behavior remains fail-closed until scoped decision provenance is
  integrated;
- Readiness gates and priority remain unchanged;
- Yahoo remains `PROVISIONAL`;
- J-Quants receives no status automatically; and
- all Data Platform and Replay regressions remain offline and green.

## Implementation Slices

The implementation should proceed in independently verifiable slices:

1. **Schemas and canonical serialization** - evidence, catalogue, profile,
   scope, applicability, result, and decision models.
2. **Frozen V1 profile registry** - data-only projections of DEC-010.
3. **Provider-independent evaluator** - deterministic requirement evaluation.
4. **Historical report compatibility** - safe evidence extraction with unknown
   preservation.
5. **Existing qualification refactor** - diagnostics produce evidence;
   evaluator produces decisions.
6. **Publication provenance integration** - separate RFC or implementation WO
   if the publisher Contract surface requires migration.
7. **Readiness evidence integration** - separate RFC or implementation WO,
   without changing DEC-012 semantics.

Each slice must retain offline tests and must not introduce a provider adapter.

## Known Migration Impact

The current qualification implementation uses fixed `_RESEARCH_CHECKS` and
`_PAPER_CHECKS` collections and calls provider acquisition methods inside the
qualification service. It therefore does not yet satisfy this RFC.

Migration must preserve existing diagnostic evidence and report readers. During
migration, the system remains fail-closed: absence of a successful scoped V1
decision cannot be replaced by a legacy overall result or a bare provider
status.

No existing Provider is promoted by implementing this RFC.

## Final Architecture Review Record

The final architecture review completed on 2026-07-17 with no unresolved major
issue.

The review confirmed:

- the evaluator boundary is Provider-independent and excludes transport,
  authentication, cache, Dataset, Publisher, Readiness, CLI, UI, and logging;
- the evaluator is a pure function of exactly Catalogue, Profile, Scope, and
  Applicability Evidence;
- equivalent normalized inputs produce byte-identical Decisions;
- Decision identity excludes invocation time, randomness, runtime metadata, and
  external state;
- all four canonical object families have explicit immutable version semantics;
- Required and Conditional requirements carry Consumer and Purpose;
- Future requirements carry a planned capability or Future Consumer;
- Contract failures and evidence insufficiency have distinct deterministic
  outcomes; and
- implementation can proceed without changing this RFC or any accepted DEC.

RFC-006 is therefore Accepted and ready for implementation. Acceptance does not
qualify a Provider, alter a Readiness gate, or authorize Dataset publication.

## Definition of Done

The RFC is implemented only when the Provider Capability Evidence Catalogue,
both accepted V1 Profiles, and the provider-independent Qualification Evaluator
are complete, deterministic, serialized, and verified offline; the migration
preserves historical evidence; and no Dataset, Readiness gate, Provider status,
or fallback rule has changed implicitly.
