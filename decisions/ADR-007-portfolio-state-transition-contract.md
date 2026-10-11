# ADR-007: Portfolio State Transition Contract

## Status

Accepted

## Date

2026-07-17

## Context

ADR-004 defines Portfolio as the aggregate that represents current investment
state. ADR-005 makes Portfolio Engine the sole owner of Portfolio state
transitions. ADR-006 defines the result returned by Portfolio Engine.

The Portfolio Engine skeleton can route canonical ExecutionEvents, but the
accepted architecture does not yet define enough semantics to implement the
first BUY transition. Five gaps block that implementation:

1. which canonical ExecutionEvent authorizes a BUY transition;
2. how the event quantity may be used without introducing position sizing;
3. how Cash changes for a BUY;
4. how an ENTRY_FILLED payload maps to the frozen Position representation; and
5. which minimum Transaction Evidence must accompany the transition.

This decision closes only those gaps. It does not define a complete accounting
framework.

## Decision Scope

This contract applies only to a normalized simulation lifecycle with at most
one current Position: an `ENTRY_FILLED` BUY that creates a Position and a
subsequent full `POSITION_CLOSED` that removes it. A later entry is permitted
only after the preceding Position has closed.

It does not authorize real-money accounting, broker execution, Japanese board
lot sizing, capital allocation, or any inference of an order quantity.

## Decision 1: Canonical Trigger

Portfolio Engine shall perform the first BUY transition only from a canonical
DEC-007 `ENTRY_FILLED` ExecutionEvent.

No new `BUY` ExecutionEvent type is introduced. `BUY` is the Portfolio
Transaction type derived from the completed execution fact.

For this transition, the input event shall satisfy all existing DEC-007
structural and metadata requirements. In addition:

- the event and payload `position_id` values shall match;
- `position_version` shall be `1`;
- `quantity`, `entry_price`, and `cost_per_share` shall be finite and positive;
- `cost_per_share` shall equal `entry_price`, as required by DEC-007 V1; and
- the event shall belong to the supplied ExecutionContext and Portfolio.

Decision 6 defines the bounded supporting sequence required to close the
Position. Other event types and multi-Position behavior remain outside this
ADR.

## Decision 2: Quantity Semantics

Portfolio Engine shall copy `ENTRY_FILLED.payload.quantity` into the new
Position and Transaction Evidence.

The quantity is an already completed, normalized execution quantity. Portfolio
Engine shall not calculate, resize, round, or infer it from Cash, account value,
market conventions, or instrument lot size.

This preserves DEC-008: V1 quantity remains a normalized research unit and
shall not be represented as a real Japanese board lot, a broker quantity, or a
capital-allocation decision.

## Decision 3: Cash Transition

For the first BUY transition:

```text
gross_amount = quantity * cost_per_share
cash_after = cash_before - gross_amount
```

The transition is permitted only when `cash_before >= gross_amount`.

Cash may become zero but shall never become negative. Insufficient Cash causes
an explicit deterministic failure. No PortfolioEngineResult or Transaction
Evidence is produced on failure.

This formula includes no commission, tax, fee, slippage, foreign exchange,
settlement, borrowing, margin, or rounding rule. All values use the numeric
semantics already carried by the accepted Portfolio and ExecutionEvent
contracts.

## Decision 4: Position Creation

The first BUY shall create exactly one Position with this mapping:

| Position field | Source |
| --- | --- |
| `symbol` | `ExecutionEvent.symbol` |
| `quantity` | `ENTRY_FILLED.payload.quantity` |
| `average_cost` | `ENTRY_FILLED.payload.cost_per_share` |

`position_id`, `initial_stop`, and `target_price` remain Execution evidence and
shall not be added to the frozen Portfolio Position persistence schema by this
ADR.

The Portfolio shall contain no current Position when an entry is applied. An
existing Position, whether for the same or a different symbol, causes an
explicit deterministic failure. A later entry after a completed full close is
permitted. Add-on purchases, Position merging, and simultaneous multi-Position
sequencing require separate contracts.

## Decision 5: Minimum Transaction Evidence

A successful first BUY shall produce one immutable Portfolio Transaction with
the following V1 evidence:

| Field | Meaning |
| --- | --- |
| `schema_version` | `portfolio-transaction-v1` |
| `transaction_id` | Deterministic Transaction identity |
| `transaction_type` | `BUY` |
| `portfolio_id` | Portfolio receiving the Position |
| `source_event_id` | Canonical `ENTRY_FILLED.event_id` |
| `execution_run_id` | Execution run carried by the source event |
| `position_id` | Position identity carried by the source event |
| `symbol` | Executed instrument |
| `transaction_date` | `ENTRY_FILLED.event_date` |
| `quantity` | Executed normalized quantity |
| `price` | `ENTRY_FILLED.payload.entry_price` |
| `gross_amount` | `quantity * cost_per_share` |
| `cash_delta` | `-gross_amount` |
| `cash_balance_after` | Resulting Portfolio Cash amount |

`transaction_id` shall be derived deterministically from the canonical
Transaction fields other than `transaction_id`. It shall not depend on current
time, random input, filenames, directory layout, or mutable global state.

Transaction Evidence is part of PortfolioEngineResult. It is not owned by the
Portfolio aggregate and this ADR does not define a separate Transaction store,
ledger, file format, or reporting interface.

## Decision 6: Full Position Close

Portfolio Engine shall process a full Position close only from one of the
ordered canonical sequences:

```text
INTENT_RECEIVED -> ENTRY_FILLED -> TARGET_TRIGGERED -> POSITION_CLOSED
INTENT_RECEIVED -> ENTRY_FILLED -> STOP_TRIGGERED -> POSITION_CLOSED
INTENT_RECEIVED -> ENTRY_FILLED -> TREND_EXIT_TRIGGERED -> POSITION_CLOSED
```

`ENTRY_REJECTED` may consume a pending intent without changing Portfolio Cash,
Positions, or Transactions. A close requires the current Position created by
the accepted `ENTRY_FILLED`, the matching `position_id` and Symbol, an accepted
`TARGET_TRIGGERED`, `STOP_TRIGGERED`, or `TREND_EXIT_TRIGGERED` for that
Position and current version, and the next `POSITION_CLOSED.position_version`.
Portfolio Engine does not
derive either trigger or an exit price; Execution supplies the canonical
DEC-003/DEC-007 event pair and Portfolio applies the same close transition for
either accepted trigger.

`POSITION_CLOSED` represents a full close of the active Position. Its quantity
is the current Position quantity established by the accepted entry evidence.
The V1 DEC-007 close payload does not require a quantity field. If a close
payload supplies `quantity`, it MUST equal that current quantity; partial exits
are rejected.

The close requires finite positive `exit_price`, matching `exit_date`, and an
`exit_reason` equal to the accepted trigger reason. It does not infer a stop,
target, trend, corporate-action, or other exit cause. `STOP_TRIGGERED`,
`TARGET_TRIGGERED`, and `TREND_EXIT_TRIGGERED` therefore differ only in their
immutable trigger evidence and matching exit reason; they share quantity
reduction, Cash credit, Position removal, and Close Transaction construction.

### Close Cash Transition

For a successful full close:

```text
gross_amount = current_position_quantity * exit_price
cash_after = cash_before + gross_amount
```

No commission, tax, fee, slippage, foreign exchange, settlement, margin,
borrowing, rounding, or dividend rule applies. The formula uses the same finite
numeric quantity, price, and Cash model as Decision 3. It is a cash state
transition only and does not create a realized-PnL, return, or performance
metric.

### Close Transaction Evidence

A successful full close produces one immutable `CLOSE` Portfolio Transaction
in the same ordered PortfolioEngineResult as the entry Transaction. It has the
existing V1 Transaction fields with this mapping:

| Field | Source or value |
| --- | --- |
| `transaction_type` | `CLOSE` |
| `source_event_id` | `POSITION_CLOSED.event_id` |
| `position_id` | active Position identity |
| `symbol` | active Position Symbol |
| `transaction_date` | `POSITION_CLOSED.event_date` |
| `quantity` | current Position quantity |
| `price` | `POSITION_CLOSED.payload.exit_price` |
| `gross_amount` | `quantity * exit_price` |
| `cash_delta` | `+gross_amount` |
| `cash_balance_after` | resulting Cash |
| `close_reason` | `POSITION_CLOSED.payload.exit_reason` |

The Close Transaction identity MUST use the same deterministic derivation as
BUY and bind the close-specific fields, including `close_reason`. `BUY` has no
close reason. No `SELL` Transaction type is introduced.

### Close Atomicity

The Engine performs close validation, Cash credit, Position removal, and Close
Transaction construction as one immutable transition. On any failure it MUST
return no successful result, leave the input Portfolio unchanged, and produce
no partial Cash, Position, Transaction, or applied-event state.

## Preconditions and Failure Atomicity

Before applying the transition, Portfolio Engine shall verify:

- ExecutionContext, Portfolio, and event identity bindings;
- canonical `ENTRY_FILLED` structure and metadata;
- an empty input Position collection;
- finite positive quantity and price values;
- sufficient Cash; and
- the resulting Portfolio through the existing Portfolio Validation capability.

Any failed precondition causes an explicit deterministic failure.

The transition is atomic. On failure:

- the input Portfolio remains unchanged;
- no partial Position or Cash update is observable;
- no Transaction Evidence is produced; and
- no successful PortfolioEngineResult is returned.

## Successful Result

A successful transition returns the ADR-006 PortfolioEngineResult containing:

- a new Portfolio with reduced Cash and one new Position;
- exactly one BUY Transaction Evidence item;
- the existing Portfolio Validation outcome; and
- a deterministic fingerprint of the resulting Portfolio state.

The input Portfolio and source ExecutionEvent remain immutable.

## Ownership Boundaries

Execution remains responsible for producing the completed `ENTRY_FILLED` fact.

Portfolio Engine remains responsible for the Cash and Position transition and
for producing Transaction Evidence.

Portfolio remains a passive representation of current investment state.

Execution Workflow remains responsible only for orchestration and Checkpoint
persistence. It shall not reproduce this transition logic.

## Contract Compatibility

This decision:

- reuses DEC-007 without changing ExecutionEvent;
- preserves DEC-008 normalized quantity and non-sizing boundaries;
- preserves ADR-004 Portfolio ownership and persistence fields;
- preserves ADR-005 Portfolio Engine ownership;
- satisfies the ADR-006 PortfolioEngineResult components; and
- does not change Execution Workflow or Checkpoint contracts.

## Out of Scope

This ADR does not define:

- add-on BUY or Position merge behavior;
- multiple open Positions;
- partial exits, add-on BUY, Position merge, or multiple current Positions;
- deposits or withdrawals;
- commission, tax, fee, or slippage;
- currency conversion or multi-currency accounting;
- real share, board lot, or capital-allocation semantics;
- dividends, splits, or other corporate actions;
- realized or unrealized profit and loss;
- market valuation or Portfolio Statistics calculation;
- settlement, margin, borrowing, or short selling;
- transaction persistence, reporting, or reconciliation;
- stop, trend, or other exit-trigger behavior; or
- broker, order, or live-execution integration.

These concerns require separate accepted contracts before implementation.

## Consequences

### Benefits

- The first Portfolio BUY becomes deterministic and auditable.
- Quantity is consumed without introducing hidden position sizing.
- Cash and Position state remain internally consistent.
- Failed transitions are fail-closed and atomic.
- Transaction Evidence links Portfolio state changes to immutable execution
  evidence.

### Trade-offs

- Only an empty-Portfolio first BUY is supported.
- The normalized quantity model is unsuitable for real-money accounting.
- Existing Positions and mixed event batches remain unsupported.
- Further BUY and SELL behavior requires additional contracts.

## Implementation Gate

BUY Handler implementation may begin only after this ADR is reviewed and
accepted. Until then, the Portfolio Engine placeholder behavior remains the
correct implementation.
