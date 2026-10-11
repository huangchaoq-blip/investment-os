# DEC-003 Replay Execution Model v0.1

Status

Accepted

Date

2026-07-10

---

# Status

Name: Replay Execution Model v0.1

Status: Accepted

This model applies to Pullback Candidate historical Replay and later unified strategy comparisons.

It is not a live trading system, does not connect to a broker, and does not automatically approve any Baseline.

All Replay results must be reproducible.

---

# ATR14 Definition

ATR14 uses Wilder Average True Range.

TrueRange is:

max(High - Low, abs(High - PreviousClose), abs(Low - PreviousClose))

The initial ATR is the simple average of the first 14 TrueRange values.

For later trading days:

ATR_today = (ATR_previous * 13 + TR_today) / 14

If data is insufficient to calculate ATR14, the result is UNKNOWN and no BUY_CANDIDATE is produced.

---

# Signal Timing

For trading day D, signals use all information known after D closes.

Signals must not be executed at D's close.

The signal must store the actual FactsDate, rather than a user-requested non-trading date.

The earliest execution is the Open of the next valid market data record after D. That record is the Execution Day.

## Pending Intent Scheduling and Expiry

An Intent produced after the close of D executes only on the first valid market data record after D. That record is its unique Execution Tick; an Intent must not remain pending across multiple valid trading days. It is Consumed after a fill or rejection.

If no valid market data record exists after the signal date, Replay produces `END_OF_DATA_REACHED` with `reason_code = UNFILLED_END_OF_DATA`. V1 does not implement manual cancellation, partial fills, or multi-day-valid orders. `ENTRY_PENDING` means only that the Intent is waiting for this next valid record; it is not an order of arbitrary duration.

---

# Entry Execution

EntryPrice = Execution Day Open

SignalStop is the ProvisionalStop calculated by DEC-002 on the signal day.

Before opening a position, all of the following must pass:

- EntryPrice > SignalStop
- ActualRisk = EntryPrice - SignalStop
- ActualRiskPct = ActualRisk / EntryPrice
- ActualRiskPct > 0
- ActualRiskPct <= 0.05

If any condition fails, Entry Status is REJECTED_AT_EXECUTION and no position is opened.

InitialStop = SignalStop

The Stop must not be loosened or moved lower because of an Execution Day open-price change.

TargetPrice = EntryPrice + 2.0 * ActualRisk

After a position opens at the Execution Day Open, that day's High and Low may trigger Stop or Target.

---

# Entry Gap Rules

If Execution Day Open <= InitialStop:

- Do not buy.
- Mark ENTRY_GAP_BELOW_STOP.
- Do not simulate an entry followed by an immediate Stop.

If Execution Day Open causes ActualRiskPct > 0.05:

- Do not buy.
- Mark ENTRY_RISK_EXCEEDED.

If Execution Day Open is above SignalClose, use the Open as EntryPrice and recalculate ActualRiskPct and the 2R TargetPrice.

SignalClose must not replace the simulated execution price.

---

# Holding-Day Price Event Order

## Execution Tick Processing

For every valid Execution Tick, Execution first validates Context and processes or blocks qualified corporate actions. If Context contains an OPEN Position, Execution evaluates the following market price exits even when no Strategy Intent exists:

1. Stop Gap
2. Target Gap
3. Same-Day Stop and Target
4. Intraday Stop
5. Intraday Target

If a price exit occurs, Execution does not process a `TREND_EXIT` Intent in that Tick. Only when no price exit occurs may Execution process an `EXIT_POSITION / TREND_EXIT` Intent supplied by Strategy at the Execution Day Open. Only when no Position is OPEN may Execution process an `ENTER_LONG` Intent. Context with neither an OPEN Position nor an Intent is a normal no-op.

Stop and Target are Execution market-triggered processing, not Strategy Intents. Strategy still exclusively creates `ENTER_LONG` and `EXIT_POSITION / TREND_EXIT` Intents, and Execution must not recalculate `Close < MA75`.

For each holding day, evaluate price events in this order:

## A. Stop Gap

If Open <= InitialStop:

ExitPrice = Open

ExitReason = STOP_GAP

## B. Target Gap

If Open >= TargetPrice:

ExitPrice = Open

ExitReason = TARGET_GAP

## C. Same-Day Stop and Target

If Low <= InitialStop and High >= TargetPrice:

ExitPrice = InitialStop

ExitReason = STOP_TARGET_SAME_DAY_CONSERVATIVE

Daily OHLC cannot determine intraday order, so the conservative Stop outcome applies.

## D. Intraday Stop

If only Low <= InitialStop:

ExitPrice = InitialStop

ExitReason = STOP_INTRADAY

## E. Intraday Target

If only High >= TargetPrice:

ExitPrice = TargetPrice

ExitReason = TARGET_INTRADAY

Only when none of these price events occurs may Execution process the Strategy-confirmed Trend Exit Intent.

---

# Trend Exit

If the close of trading day D is below MA75:

ExitSignal = TREND_EXIT_SIGNAL

The actual exit is at the Open of the next valid market data record after D.

ExitReason = TREND_EXIT_NEXT_OPEN

On that Trend Exit Execution Day, first evaluate:

- Open <= InitialStop: exit with STOP_GAP.
- Open >= TargetPrice: exit with TARGET_GAP.
- Otherwise: exit at Open with TREND_EXIT_NEXT_OPEN.

The close that produced the Trend Exit signal must not be used as the exit price.

---

# Duplicate and Pending Orders

For the same stock:

- Ignore new BUY_CANDIDATE signals while a position is held.
- Do not add to a position.
- Do not reset InitialStop.
- Do not reset TargetPrice.
- Do not create a second Pending Entry.
- Ignore later Entry signals while a Pending Entry exists, until it fills or is rejected.

---

# Missing Data and Suspension

OHLCV must not be fabricated.

If no valid record exists after a signal date:

- Produce `END_OF_DATA_REACHED` with `reason_code = UNFILLED_END_OF_DATA`.

If holding-period dates are missing:

- Do not interpolate.
- Do not assume a Stop or Target event.
- Resume event evaluation at the next valid record.
- Record DataGapDays or equivalent Evidence.

Exchange calendars and long-suspension expiry rules belong to the Historical Data Contract. Missing data must not be assumed to be a normal market holiday.

---

# End of Replay

For a position still open at Replay end, the Baseline Report must record:

- Status = OPEN_AT_END
- LastClose
- UnrealizedReturn
- InitialStop
- TargetPrice
- HoldingDays

Do not fabricate a formal exit at the final close.

If a research report needs mark-to-market, report it separately from closed-trade results.

---

# Costs

The Execution Engine must support:

- Buy fee
- Sell fee
- Buy slippage
- Sell slippage
- Tax or other explicit cost

All costs must come from explicit configuration and be saved in Replay Metadata.

This decision does not invent current Matsui Securities fees.

Formal Benchmark reports must include:

- Gross Result: excluding fees and slippage.
- Costed Result: using frozen fee and slippage configuration.

Fee and slippage values will be frozen by a later Historical Data / Trading Cost Contract.

Gross Result alone must not be used to approve a Baseline.

---

# Corporate Actions

Until an adjusted-price and corporate-action data contract is complete:

- Replay results are Preliminary.
- Results must not support Production Baseline Approval.
- Splits, reverse splits, and dividends must not be silently ignored.

The Historical Data Contract will define adjusted-price and corporate-action rules.

---

# Required Replay Evidence

Each candidate and trade must retain:

- SignalDate
- FactsDate
- ExecutionDate
- Code
- SignalClose
- EntryPrice
- InitialStop
- ActualRisk
- ActualRiskPct
- TargetPrice
- ExitSignalDate
- ExitDate
- ExitPrice
- ExitReason
- GrossPnL
- Cost
- NetPnL
- HoldingBars
- DataGap indicator
- Strategy Version
- Rule Version
- Data Version
- Replay Configuration Version

---

# Out of Scope

This decision does not define:

- Single-trade investment amount
- Maximum position count
- Same-day multi-stock capital ordering
- Japanese stock trading units
- Current Matsui Securities fee values
- Specific slippage values
- Benchmark Index
- Business Health
- Financial data
- Broker synchronization
- Automated orders
