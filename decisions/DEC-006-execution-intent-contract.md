# DEC-006 ExecutionIntent Contract

## Status

Accepted

## 1. Purpose

ExecutionIntent represents an immutable request produced by Strategy after evaluation and consumed by Execution before execution processing.

ExecutionIntent 表示一个不可变请求：由 Strategy 在评估后产生，并由 Execution 在执行处理前消费。

## 2. Ownership

The sole owner of ExecutionIntent creation is Strategy.

Execution must not create an Intent. Replay must not modify an Intent. Research must not modify an Intent. Benchmark must not modify an Intent.

## 3. Lifecycle

```text
Created
    ↓
Consumed
    ↓
Archived
```

The Intent lifecycle ends at `Consumed`.

`Accepted` and `Rejected` are ExecutionEvents. They are not Intent lifecycle states.

## 4. Invariants

- Immutable.
- Does not guarantee execution.
- Produced only by Strategy.
- Consumed only by Execution.
- Independent of Broker.
- Independent of Portfolio.
- Independent of Performance.
- Independent of Benchmark.
- Independent of Research.

## 5. Minimum Required Information

This Decision freezes only the minimum Contract information:

- `intent_id`
- `requested_action`
- `symbol`
- `signal_date`
- `facts_date`
- `strategy_version`
- `dataset_version`
- `signal_stop`
- `intent_reason_code`

`symbol` is the canonical ExecutionIntent Contract field name. Current Japanese stock codes map to this field. The Contract does not create a second synonymous `code` field.

`signal_stop` is the ProvisionalStop calculated by Strategy/Facts on `signal_date`, using the signal price scale. It must be a finite positive number. Execution must not recalculate it. Under DEC-005, Entry Execution converts it to the execution-day raw price scale when required. It does not guarantee a final fill.

`signal_stop` is required for an `ENTER_LONG` Intent. It is not an input to an `EXIT_POSITION` Intent; Exit Processing instead consumes the current Position Snapshot from ExecutionContext.

`intent_reason_code` is the stable business reason code supplied by Strategy for `requested_action`. Execution must not use it to recalculate a Strategy Rule; it uses the code only to select a frozen execution path and to preserve the corresponding Event `reason_code`. In V1, `ENTER_LONG` may use `PULLBACK_ENTRY`; `EXIT_POSITION` must use `TREND_EXIT`. The field does not carry MA, ATR, Close, or other Strategy Evidence, and does not include Broker, Portfolio, or Performance information.

RFC-002 identifies additional candidate evidence for a future complete Intent Contract. This Decision does not add, define, or freeze those fields.

## 5.1 V1 Intent Production

Strategy produces an `ENTER_LONG` Intent if and only if all of the following are true:

- no OPEN Position exists;
- `PullbackFacts.status = READY`;
- `PullbackStrategyResult.decision = BUY_CANDIDATE`.

The Intent uses `requested_action = ENTER_LONG` and `intent_reason_code = PULLBACK_ENTRY`.

Strategy produces an `EXIT_POSITION` Intent if and only if all of the following are true:

- an OPEN Position exists;
- `PullbackFacts.status = READY`;
- `close_above_ma75 = False`.

The Intent uses `requested_action = EXIT_POSITION` and `intent_reason_code = TREND_EXIT`. Execution must not recalculate the MA75 condition.

Strategy produces no Intent for `WAIT`, `UNKNOWN`, non-READY Facts, a new `BUY_CANDIDATE` while an OPEN Position exists, or a Trend Exit condition while no Position is open.

`intent_id` must be deterministic. At minimum it binds `requested_action`, `intent_reason_code`, `symbol`, `signal_date`, `facts_date`, `strategy_version`, and `dataset_version`. The implementation may choose the hash algorithm, but identical inputs must produce the same identifier. Random UUIDs, system time, file modification time, and unversioned configuration are prohibited.

## Amendment

`signal_stop` is added to eliminate the DEC-003 Entry Processing Contract gap. This amendment does not add `risk_limit`, `target_policy`, or `reference_price`.

`intent_reason_code` is added to eliminate the DEC-003 `TREND_EXIT_NEXT_OPEN` Contract gap. It records the Strategy-confirmed exit reason without moving Strategy Rule evaluation into Execution.

V1 Intent Production is added to eliminate the Strategy-to-Intent Contract gap before historical Replay. It does not add a Strategy Rule or change any Strategy parameter.

## 6. Non-goals

ExecutionIntent is not:

- Trade
- Order
- Position
- Portfolio
- Recommendation

## 7. Open Questions

Open Questions: None for V1 contract.

## 8. Decision

Status: Accepted.

This document does not authorize an Execution Engine implementation.
