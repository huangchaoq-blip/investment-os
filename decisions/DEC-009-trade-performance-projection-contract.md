# DEC-009 Trade Performance Projection Contract

Status: Accepted

## Purpose

Define the deterministic V1 aggregate statistics that may consume only a
`TradeProjectionResult`. Performance Projection is a pure projection; it does
not read market data, Facts, Strategy, Replay state, or Execution state.

## Canonical Input And Population

The canonical input is one single-symbol `TradeProjectionResult` from WO-047.
Only `closed_trades` participate in aggregate statistics. `open_trade` is not
realized performance, is not a win or loss, and is reported only through
`has_open_trade` and a limitation. Replay end must never create a synthetic exit.

## Current Evidence Assessment

The current `TradeRecord` freezes entry/exit prices, initial and final quantity,
cost-per-share evidence, adjustment event IDs, holding calendar days, and
lifecycle sequence evidence. It does **not** freeze canonical per-trade
`gross_realized_pnl`, `gross_return_pct`, or `realized_r_multiple`.

For an unadjusted lifecycle, some values appear arithmetically derivable. That
is not sufficient for this contract: after `POSITION_ADJUSTED` or
`SPLIT_APPLIED`, DEC-005 does not freeze a cost-basis/economic-value rule.
Performance Projection must not infer one from prices, quantities, or split
ratios. Therefore the following metrics are unsupported in V1:

- gross PnL and gross return aggregates;
- win/loss/breakeven classification and rates;
- profit factor;
- expectancy PnL or R multiple;
- largest win/loss PnL or return;
- realized R multiple.

WO-048 may not calculate these values until a future accepted contract adds
canonical economic fields to `TradeRecord` with adjustment-safe semantics.

## V1 Included Metrics

The following closed-trade and lifecycle metrics are supported from existing
Trade Projection evidence:

- `total_closed_trades`;
- `has_open_trade`;
- `average_holding_calendar_days`;
- `median_holding_calendar_days`;
- `minimum_holding_calendar_days`;
- `maximum_holding_calendar_days`.

For an even number of holdings, median is the arithmetic mean of the two middle
values after sorting ascending. Internal calculations use `Decimal` converted
from the canonical integer holding-day values. Rounding is a presentation-layer
responsibility; no locale formatting is part of Projection.

## Empty Sample Semantics

With no closed trades, status is `EMPTY`, or `EMPTY_WITH_OPEN_TRADE` when an
open trade exists. Counts are zero. Holding-period aggregates are `None` rather
than zero. An open trade is never included in the denominator.

## Metadata And Determinism

The result copies `execution_run_id`, `symbol`, `strategy_version`,
`dataset_version`, `execution_configuration_version`, and `source_event_count`
from `TradeProjectionResult`. Closed trades must already be ordered by their
canonical `first_sequence_number`; non-canonical ordering is rejected, never
silently sorted. Identical inputs produce identical outputs without time,
randomness, object identity, locale, or unstable mapping order.

## Adjustment Boundary

Performance Projection does not read Corporate Action data, recompute split
ratios, use adjusted prices, or reinterpret position adjustments. A blocked
corporate-action lifecycle remains evidence only and may be surfaced as a
limitation. It does not create PnL.

## Explicitly Unsupported V1 Metrics

V1 also excludes CAGR, annualized return, drawdown, equity curves, daily return
series, Sharpe/Sortino/Calmar, portfolio volatility, exposure-adjusted return,
unrealized PnL, mark-to-market return, capital utilization, and benchmark alpha
or beta. There is no frozen capital, cash, sizing, valuation, or benchmark
contract.

## Error Boundary

A future Performance Projection must use a stable `PerformanceProjectionError`
for mixed metadata, invalid trade ordering, inconsistent counts, non-finite
inputs, or missing required economic evidence. It must not add a complex
exception framework.

## Out Of Scope

This decision introduces no Portfolio, Cash, Broker, Fees, Slippage, Dividends,
Taxes, Currency Conversion, multi-symbol aggregation, benchmark comparison,
parameter sweep, or report formatting.

## Decision

V1 Performance Projection is limited to closed-trade counts and holding-period
statistics until adjustment-safe canonical economic fields are accepted. This
decision does not modify Trade Projection, Position Projection, Replay,
Execution, or Strategy.
