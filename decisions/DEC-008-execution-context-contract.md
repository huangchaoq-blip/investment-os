# DEC-008 ExecutionContext Contract

## Status

Accepted

Aligned with `ADR-003 Execution Workflow Architecture Review`.

## 1. Purpose

ExecutionContext is the single immutable runtime Context shared by Execution
Workflow, Replay, Execution Engine, and Portfolio Engine for one deterministic
execution state.

ExecutionContext 是 Execution Workflow、Replay、Execution Engine 与 Portfolio
Engine 在一个确定性执行状态中共同使用的唯一不可变运行时 Context。

The architecture has no second workflow-level, Replay-level, or
Portfolio-level runtime Context. Execution metadata is represented separately
and does not create another Context.

## 2. Ownership

ExecutionContext is restored or created as part of the Checkpoint-controlled
Execution Workflow. Workflow coordinates the Context lifecycle. Replay,
Execution Engine, and Portfolio Engine operate on that same immutable Context
according to their responsibilities.

No component may create a parallel Context, copy Context fields into hidden
mutable state, or use an implicit current Context. A state transition produces
a new immutable ExecutionContext candidate that becomes current only through a
successfully persisted Checkpoint.

## 3. Consumers

The allowed Consumers of the one ExecutionContext are:

- Execution Workflow;
- Replay;
- Execution Engine; and
- Portfolio Engine.

Each Consumer reads only the fields required by its accepted responsibility.
Sharing one Context does not transfer business-rule ownership between modules.
Execution still owns execution decisions; Replay still coordinates evaluation;
Portfolio still applies accepted Portfolio rules; Workflow only orchestrates.

## 4. Lifecycle and Checkpoint Boundary

```text
Created or Restored from Checkpoint
                ↓
Used by Workflow, Replay, Execution, and Portfolio
                ↓
Persisted as part of the next complete Checkpoint
                ↓
Superseded by the next immutable ExecutionContext
```

ExecutionContext is immutable. It must not be updated in place, reused as a
different execution state, or reconstructed independently from other
Checkpoint members.

Checkpoint is the single persistence and recovery unit. It conceptually
contains:

- ExecutionContext;
- PortfolioState;
- Timeline position;
- Event cursor; and
- Manifest references.

Recovery restores the last complete Checkpoint. It must not restore Context,
PortfolioState, Timeline, Event cursor, or Manifest references independently.
Timeline advances only after the next Checkpoint is durably persisted.

## 5. Invariants

- Single Context
- Immutable
- Read-only to Consumers
- Point-in-time
- Versioned
- Deterministic
- Checkpoint-controlled
- Independent of physical filenames and directory layout

Long-lived domain identities are explicit. Calendar dates may be domain values
but must not substitute for Run, Portfolio, Universe, Checkpoint, Replay, or
Manifest identity.

## 6. Canonical Context Contract

ExecutionContext contains the runtime information required to coordinate the
accepted workflow and execute one resolved trading-session state:

- `execution_date`
- `market_data_snapshot`
- `corporate_action_snapshot`
- `current_position_projection`
- `execution_configuration_version`
- `execution_configuration_snapshot`
- `strategy_version`
- `dataset_version`
- `cache_manifest_id`
- `timeline_position`
- `runtime_mode`
- `universe_id`
- `universe`
- `replay_version`
- `portfolio_id`
- `calendar_identity`
- `execution_workflow_version`

The exact serialized representation remains an implementation decision. Field
meaning and identity must not depend on file paths, directory names, or current
time.

### 6.1 Dual Manifest Strategy

`dataset_version` and `cache_manifest_id` are separate fields with separate
governance meanings:

- `dataset_version` identifies Canonical Research data.
- `cache_manifest_id` identifies noncanonical Local Historical Cache state.

They must never be merged, substituted, inferred from one another, or placed
under one ambiguous field. A cache manifest does not become a Canonical Dataset
version by appearing in ExecutionContext. Yahoo remains PROVISIONAL, and cache
content remains ineligible for formal Research conclusions under DEC-013.

Mode-specific presence and validation must be explicit in the eventual API and
serialization Contract. An implementation must not fabricate an identity when
one data layer is not applicable.

### 6.2 Workflow and Timeline Fields

`runtime_mode` identifies the accepted workflow mode. `timeline_position`
identifies the current position in an ordered trading-session Timeline governed
by `calendar_identity`. `universe_id` is the stable identity of the universe;
`universe` is its ordered symbol content. `replay_version`, `portfolio_id`, and
`execution_workflow_version` are stable domain identities or versions, not
filenames or dates.

The Workflow uses these fields only to load state, resolve the session, execute
Replay, execute Portfolio Engine, persist the Checkpoint, and advance the
Timeline. It must not import data, synchronize a Provider, generate reports,
interact with a Broker, perform risk management, or send notifications.

### 6.3 Market and Position Snapshot

`market_data_snapshot` contains the resolved market date and raw OHLC required
for the current execution state. `corporate_action_snapshot` contains the
qualified corporate-action evidence available to Execution.

`current_position_projection` is the immutable point-in-time Position Snapshot
supplied to Execution. Its canonical V1 fields are:

- `position_id`
- `symbol`
- `position_status`
- `quantity`
- `entry_date`
- `entry_price`
- `cost_per_share`
- `initial_stop`
- `target_price`
- `position_version`

Exit Processing requires `position_status = OPEN`; any other state must fail or
be rejected explicitly, without inference. `initial_stop` and `target_price`
must use the current Execution Day raw price scale and must not be recalculated
from Strategy Facts. If a split occurs, they must be adjusted under DEC-005
before price-event comparison.

`quantity` and `cost_per_share` are adjusted under DEC-005 when a split occurs;
the split itself does not create PnL. `entry_price` is the actual per-share fill
price and must not use Provider `adjusted_close`. `position_version` identifies
the deterministic Position Snapshot version.

The Position Snapshot does not include unrealized PnL, performance metrics,
Portfolio cash, account balance, Broker orders, news, Provider handles, or
database handles.

Every canonical Position Snapshot field must be reconstructable from the
ordered ExecutionEvent stream. Projection must not depend on a Provider,
Dataset query, historical Context copy, implicit memory state, random value, or
current time.

### 6.4 Corporate Actions

When a split is effective before a tick's market-price checks, Execution applies
the DEC-005 adjustment before comparing raw OHLC with `initial_stop` or
`target_price`. Corporate-action evidence that cannot be safely interpreted
must produce `CORPORATE_ACTION_BLOCKED`; Execution must not silently continue.

### 6.5 Execution Configuration

`execution_configuration_snapshot` is immutable, point-in-time, and corresponds
to `execution_configuration_version`. V1 retains the explicit values frozen by
DEC-003 and later amendments:

- `max_initial_risk_pct = 0.05`
- `target_r_multiple = 2.0`
- `entry_quantity = 1`

`entry_quantity` is a finite positive normalized research unit used only for
Position and PnL reconstruction. It is not a Japanese market lot size,
Portfolio sizing decision, or Broker order quantity. Execution must not infer
quantity from account funds or market rules. Real trading units and capital
allocation remain future Portfolio and Security Master concerns.

Execution must not use a version alone to read external configuration. A
version and snapshot mismatch fails explicitly. No Consumer may access the
network or unversioned configuration through Context.

### 6.6 Intent Consistency

`strategy_version` and `dataset_version` are stable Context bindings. When an
Intent is present, its `strategy_version` and `dataset_version` must exactly
match Context. Execution must fail or reject explicitly on mismatch and must
not rewrite either input.

The one Context does not move Strategy Rule evaluation into Execution or
Portfolio. Context carries deterministic inputs; module ownership remains
unchanged.

Execution processes every valid resolved-session state with an optional
Intent. With an OPEN Position, it evaluates frozen market-triggered Stop and
Target exits even when Intent is absent. An Intent remains required only for
`ENTER_LONG` and Strategy-confirmed `EXIT_POSITION / TREND_EXIT`; Context with
neither an OPEN Position nor an Intent is a normal no-op.

## 7. Execution Metadata

Execution metadata accompanies the workflow but is not another runtime
Context. It includes operational and evidence-envelope values such as:

- Run ID;
- Trace ID when used;
- operational timestamps;
- Event cursor and next sequence evidence; and
- persistence diagnostics.

Run ID and other long-lived metadata identities must be deterministic when they
participate in system behavior. Random values, system time, filenames, and
directory paths must not determine execution results.

Run ID binds at least `dataset_version`, `cache_manifest_id`,
`strategy_version`, `execution_configuration_version`, Replay range, and
initial Checkpoint identity. Mode-specific non-applicability must be explicit;
an implementation must not fabricate either Manifest identity.

The Event cursor is persisted inside Checkpoint and supplied to Execution as
metadata for deterministic sequence allocation. Execution does not own or
advance the persisted cursor. Event metadata sourcing is governed by DEC-007.

## 8. Amendment and Alignment

ADR-003 replaces the former single-tick, Execution-only Context scope with one
runtime Context shared by Workflow, Replay, Execution Engine, and Portfolio
Engine. It also adds the explicit `cache_manifest_id` alongside
`dataset_version`, moves Run/Trace/timestamp metadata outside Context, and makes
Checkpoint the persistence and recovery unit.

Earlier accepted amendments remain in force:

- `execution_configuration_snapshot` closes the DEC-003 Entry Processing
  configuration gap without copying policy values into Intent.
- `current_position_projection` closes the DEC-003 Exit Processing state gap
  without creating a Position Repository inside Context.
- `entry_quantity` keeps V1 normalized quantity in explicit versioned
  configuration rather than Projection inference.
- `strategy_version` and `dataset_version` preserve complete Event metadata
  when Intent is absent without adding those values to PositionSnapshot.

This alignment does not change Entry, Exit, Stop, Target, Trend Exit, Position,
or corporate-action business rules. It changes architecture documentation and
future Contract ownership only.

## 9. Non-goals

ExecutionContext is not:

- a Provider;
- a Replay Engine;
- a Portfolio;
- a Strategy;
- a database;
- a Market Repository;
- an Execution Metadata envelope; or
- a Checkpoint.

Checkpoint contains ExecutionContext; Context does not replace Checkpoint.

## 10. Open Questions

The storage format, API shape, Timeline implementation, Portfolio implementation,
and mode-specific dual-manifest validation rules remain outside this Contract
alignment.

## 11. Decision

Status: Accepted.
