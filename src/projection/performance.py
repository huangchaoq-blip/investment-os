"""DEC-009 holding-period statistics from canonical Trade Projection evidence."""

from dataclasses import dataclass
from decimal import Decimal
from math import isfinite

from .trade import TradeProjectionResult


class PerformanceProjectionError(ValueError):
    """Stable failure for invalid Trade Projection evidence."""


BASE_LIMITATIONS = (
    "NO_ADJUSTMENT_SAFE_REALIZED_PNL", "NO_RETURN_METRICS",
    "NO_WIN_LOSS_CLASSIFICATION", "NO_PROFIT_FACTOR", "NO_EXPECTANCY",
    "NO_R_MULTIPLE_METRICS", "NO_PORTFOLIO_EQUITY_METRICS",
)


@dataclass(frozen=True)
class PerformanceProjectionResult:
    execution_run_id: str | None; symbol: str | None; strategy_version: str | None
    dataset_version: str | None; execution_configuration_version: str | None
    source_event_count: int; total_closed_trades: int; has_open_trade: bool
    average_holding_calendar_days: Decimal | None; median_holding_calendar_days: Decimal | None
    minimum_holding_calendar_days: int | None; maximum_holding_calendar_days: int | None
    status: str; warnings: tuple[str, ...]; limitations: tuple[str, ...]


def project_performance(trade_projection: TradeProjectionResult) -> PerformanceProjectionResult:
    """Return deterministic, non-economic aggregate trade lifecycle statistics."""
    if not isinstance(trade_projection, TradeProjectionResult):
        _fail("INVALID_TRADE_COUNT")
    trades = trade_projection.closed_trades
    _validate(trade_projection, trades)
    has_open = trade_projection.open_trade is not None
    limitations = list(BASE_LIMITATIONS)
    if has_open: limitations.append("OPEN_TRADE_EXCLUDED_FROM_AGGREGATES")
    blocked = "CORPORATE_ACTION_BLOCKED" in trade_projection.limitations
    warnings = ("CORPORATE_ACTION_BLOCKED",) if blocked else ()
    if not trades:
        status = "EMPTY_WITH_OPEN_TRADE" if has_open else "EMPTY"
        return PerformanceProjectionResult(*_metadata(trade_projection), 0, has_open, None, None, None, None, status, warnings, tuple(limitations))
    days = [trade.holding_calendar_days for trade in trades]
    ordered = sorted(days)
    count = len(days); middle = count // 2
    median = Decimal(ordered[middle]) if count % 2 else (Decimal(ordered[middle - 1]) + Decimal(ordered[middle])) / Decimal(2)
    average = sum((Decimal(value) for value in days), Decimal(0)) / Decimal(count)
    status = "COMPLETE_WITH_OPEN_TRADE" if has_open else "COMPLETE"
    return PerformanceProjectionResult(*_metadata(trade_projection), count, has_open, average, median, min(days), max(days), status, warnings, tuple(limitations))


def _metadata(result):
    return (result.execution_run_id, result.symbol, result.strategy_version, result.dataset_version, result.execution_configuration_version, result.source_event_count)


def _validate(result, trades):
    if not isinstance(result.source_event_count, int) or isinstance(result.source_event_count, bool) or result.source_event_count < 0: _fail("NON_FINITE_NUMERIC_INPUT")
    previous_last = None
    for trade in trades:
        for field, expected in (("execution_run_id", result.execution_run_id), ("symbol", result.symbol), ("strategy_version", result.strategy_version), ("dataset_version", result.dataset_version), ("execution_configuration_version", result.execution_configuration_version)):
            if getattr(trade, field) != expected: _fail("MIXED_RUN_METADATA" if field == "execution_run_id" else ("MIXED_SYMBOL" if field == "symbol" else "MIXED_VERSION_METADATA"))
        days = trade.holding_calendar_days
        if isinstance(days, bool) or not isinstance(days, int) or days < 0: _fail("INVALID_HOLDING_CALENDAR_DAYS")
        if not isinstance(trade.first_sequence_number, int) or not isinstance(trade.last_sequence_number, int) or trade.first_sequence_number > trade.last_sequence_number: _fail("INVALID_TRADE_ORDER")
        if previous_last is not None and trade.first_sequence_number <= previous_last: _fail("INVALID_TRADE_ORDER")
        previous_last = trade.last_sequence_number


def _fail(code):
    raise PerformanceProjectionError(code)
