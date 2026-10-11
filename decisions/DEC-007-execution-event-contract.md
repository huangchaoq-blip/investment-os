# DEC-007 ExecutionEvent Contract

## Status

Accepted

## 1. Purpose

ExecutionEvent is immutable Evidence produced only by the Execution Engine.

ExecutionEvent 是仅由 Execution Engine 产生的不可变 Evidence。

## 2. Ownership

The sole creator of an ExecutionEvent is the Execution Engine.

No other module may create an Event.

## 3. Consumers

The following Consumers may consume Events or their projections:

- Trade Ledger
- Position Projection
- Performance
- Benchmark
- Research

The Execution Engine does not depend on these Consumers.

## 4. Lifecycle

```text
Created
    ↓
Persisted
    ↓
Consumed
```

An Event is immutable for its entire lifecycle. It must not be updated, deleted, or replaced.

## 5. Invariants

- Immutable
- Ordered
- Deterministic
- Versioned
- Replayable
- Auditable

## 6. Canonical Event Contract

RFC-002 defines the following minimum Event evidence:

- `event_id`
- `schema_version`
- `sequence_number`
- `event_type`
- `event_date`
- `symbol`
- `intent_id`
- `position_id`
- `strategy_version`
- `dataset_version`
- `execution_config_version`
- `execution_run_id`
- `payload`
- `reason_code`
- deterministic run metadata

`symbol` carries the security identifier referred to as `code` in RFC-002. This Contract does not create a second synonymous `code` field.

Canonical Event metadata has explicit sources. `strategy_version` comes from
`ExecutionContext.strategy_version`; `dataset_version` comes from
`ExecutionContext.dataset_version`; and `execution_config_version` comes from
`ExecutionContext.execution_configuration_version`. `execution_run_id` comes
from the separate Execution metadata governed by ADR-003, not from a second
runtime Context. This applies even when Intent is absent.

The Checkpoint owns the persisted Event cursor. Execution metadata supplies the
next sequence value derived from that cursor. Execution assigns that value to
the first Event it produces, uses consecutive numbers for later Events in the
same call, and must not renumber an Event after creation. When
`cache_manifest_id` applies, deterministic run metadata preserves it separately
from `dataset_version`; neither identifier may replace the other.

`position_id` is determined by the Execution Engine when it produces `ENTRY_FILLED`. It binds at least `intent_id`, `symbol`, `entry_date`, `strategy_version`, and `dataset_version`. Identical inputs produce the same identifier; random UUIDs and system current time are prohibited. The identifier uses the format `position-v1-<stable-hash>`. `ENTRY_FILLED` and every subsequent Position-mutating Event must carry the same `position_id`.

## 7. Position Event Evidence

The canonical `ENTRY_FILLED` payload contains at least:

- `position_id`
- `position_version`
- `quantity`
- `entry_date`
- `entry_price`
- `cost_per_share`
- `initial_stop`
- `target_price`

The top-level `event.position_id` must equal `payload.position_id`. `position_version = 1` when `ENTRY_FILLED` creates a Position. `quantity` comes from `execution_configuration_snapshot.entry_quantity`. `cost_per_share` equals the V1 actual `entry_price`; it excludes fees, slippage, and cash dividends and must not be interpreted as a tax cost basis. `initial_stop` and `target_price` use the Execution Day raw price scale. Projection must not recalculate any of these fields.

The canonical `POSITION_CLOSED` payload contains at least:

- `position_id`
- `position_version`
- `exit_date`
- `exit_price`
- `exit_reason`

Its top-level `event.position_id` must match `payload.position_id`.

Every Event that mutates a Position Snapshot must advance `position_version` by exactly one. V1 Position-mutating Events include `ENTRY_FILLED`, `SPLIT_APPLIED`, `POSITION_ADJUSTED`, and `POSITION_CLOSED`; Events that do not change a Position must not advance it. Projection consumes Event versions and fails explicitly on missing or non-continuous versions.

When implemented, `SPLIT_APPLIED` and `POSITION_ADJUSTED` must explicitly record adjusted `quantity`, `cost_per_share`, `initial_stop`, `target_price`, and the new `position_version`. Projection must not derive these values from raw market data.

## 8. Event Categories

Only the categories and Events defined by RFC-002 are frozen:

| Category | Events |
| --- | --- |
| Intent | `INTENT_RECEIVED`, `INTENT_REJECTED` |
| Entry | `ENTRY_PENDING`, `ENTRY_FILLED`, `ENTRY_REJECTED`, `ENTRY_EXPIRED` |
| Position | `POSITION_OPENED`, `POSITION_ADJUSTED`, `POSITION_CLOSED` |
| Exit | `STOP_TRIGGERED`, `TARGET_TRIGGERED`, `TREND_EXIT_TRIGGERED`, `EXIT_FILLED` |
| Corporate Action | `SPLIT_APPLIED`, `CORPORATE_ACTION_BLOCKED` |
| Data | `DATA_GAP_OBSERVED`, `END_OF_DATA_REACHED` |

## 9. Non-goals

ExecutionEvent is not:

- Trade
- Position
- Portfolio
- Report
- Performance Snapshot

These are Event projections.

## 10. Open Questions

Open Questions: None for V1 Event Contract.

## 11. Decision

Status: Accepted.

This document does not authorize an Execution Engine implementation.
