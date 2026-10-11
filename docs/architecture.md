# Architecture

Investment OS is the project. SSPL is one research application, not the core.

| Boundary | Selected source | Responsibility |
| --- | --- | --- |
| Core domain | `execution/context.py`, `strategy/intent.py` | Versioned Context, immutable intent and explicit runtime metadata |
| Provider abstraction | `data_platform/provider.py`, `models.py` | Provider-neutral requests/results; no credential in a request |
| Evidence qualification | `qualification_engine.py`, `qualification_schemas.py` | Required/conditional/future capabilities; scoped evidence, not provider-wide trust |
| Dataset governance | `data/manifest.py`, `data_platform/publisher.py`, `registration.py` | Data class, content identity, validation and immutable publication |
| Replay | `replay/orchestrator.py` | Chronological scheduling; consumes a named dataset, does not own the strategy |
| Execution | `execution/engine.py`, `entry.py`, `exit.py` | Next-open entry, bounded rejection/exit rules and deterministic events |
| Projection | `projection/` | Reconstruct position/trade state only from events |
| Portfolio | `portfolio/aggregate.py`, `engine.py`, `persistence.py` | Capital state, invariants, accepted transitions and serialization |
| Research evidence | `research/ledger.py`, `performance.py` | Stable trade ledger and explicitly limited non-economic metrics |

The original code includes an older strategy candidate for provenance, not a
recommended strategy. Original Replay defaults depend on published historical
data and point-in-time Facts; public examples instead inject synthetic loaders
and predetermined intents. Injection is an existing interface, not a new Replay
implementation.

The four trimmed initializers (`data`, `database`, `data_platform`, `research`)
avoid pulling private workflow modules into this deliberately selected subset.
Their provenance is PUBLIC_ADAPTATION. Other selected algorithm source bytes are
unchanged. Four governance documents have navigation-only adaptations recorded
in the source index; omitted private references point to an explicit notice.
Imports retained for compatibility do not mean all legacy workflows are endorsed.

## Contract vs Implementation

Original DEC/ADR/RFC documents in this repository are historical design evidence.
They do not override the observed module status or authorize trading. References
to omitted historical files are not claims that those files can be reproduced.
The public package is not a merger of every version of the original system.

## Bounded Safety

Replay and provider qualification fail on explicit invalid inputs, mismatched
versions and unavailable required evidence. This is not a claim that all possible
bad inputs are prevented or that every historical provider fact is qualified.
Some Portfolio event routes are explicitly unimplemented. Corporate actions do
not become safe merely because an adjusted price exists. Real provider terms,
calendar evidence, provenance and immutable publication would be prerequisites
for a separately authorized real-data execution.
