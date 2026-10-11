"""Contract-safe non-economic Research Performance derived only from Ledger V1."""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path

from .ledger import RESEARCH_LEDGER_SCHEMA_VERSION, ResearchLedgerV1


RESEARCH_PERFORMANCE_VERSION = "research-performance-v1"

AVAILABLE_METRICS = (
    "closed_trade_count",
    "average_holding_calendar_days",
    "exit_reason_distribution",
)

BLOCKED_METRICS = (
    "return_pct",
    "realized_pnl",
    "adjusted_return",
    "raw_return",
    "win_rate",
    "average_win",
    "average_loss",
    "profit_factor",
    "expectancy",
    "cumulative_return",
    "max_drawdown",
    "cagr",
    "benchmark",
    "exposure",
    "quantity_based_metrics",
)


class ResearchPerformanceError(ValueError):
    """Raised when Research Ledger evidence cannot satisfy Performance V1."""


@dataclass(frozen=True)
class ResearchMetadata:
    strategy_version: str | None
    dataset_version: str | None
    ledger_schema_version: str
    replay_timestamp: str | None
    research_version: str


@dataclass(frozen=True)
class ExitReasonCount:
    exit_reason: str
    count: int


@dataclass(frozen=True)
class MetricEvidence:
    name: str
    status: str
    value: object = None
    reason: str | None = None


@dataclass(frozen=True)
class ResearchPerformanceV1:
    schema_version: str
    metadata: ResearchMetadata
    metrics: tuple[MetricEvidence, ...]


def project_research_performance(ledger: ResearchLedgerV1) -> ResearchPerformanceV1:
    """Derive only DEC-009-safe evidence from Research Ledger V1."""
    records = _validated_records(ledger)
    strategy_version, dataset_version = _metadata(records)
    holding_days = tuple(record.holding_calendar_days for record in records)
    average = (
        None
        if not holding_days
        else sum((Decimal(value) for value in holding_days), Decimal(0))
        / Decimal(len(holding_days))
    )
    exit_counts = tuple(
        ExitReasonCount(reason, count)
        for reason, count in sorted(
            Counter(record.exit_reason for record in records).items()
        )
    )
    metrics = (
        MetricEvidence("closed_trade_count", "AVAILABLE", len(records)),
        MetricEvidence("average_holding_calendar_days", "AVAILABLE", average),
        MetricEvidence("exit_reason_distribution", "AVAILABLE", exit_counts),
    ) + tuple(
        MetricEvidence(name, "BLOCKED", reason="DEC-009")
        for name in BLOCKED_METRICS
    )
    return ResearchPerformanceV1(
        schema_version=RESEARCH_PERFORMANCE_VERSION,
        metadata=ResearchMetadata(
            strategy_version=strategy_version,
            dataset_version=dataset_version,
            ledger_schema_version=ledger.schema_version,
            replay_timestamp=None,
            research_version=RESEARCH_PERFORMANCE_VERSION,
        ),
        metrics=metrics,
    )


def export_research_performance_json(
    performance: ResearchPerformanceV1, path
) -> Path:
    """Create one deterministic UTF-8 JSON export and refuse replacement."""
    _validate_performance(performance)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(
            f"Research Performance export already exists: {destination}."
        )
    payload = {
        "schema_version": performance.schema_version,
        "metadata": {
            "strategy_version": performance.metadata.strategy_version,
            "dataset_version": performance.metadata.dataset_version,
            "ledger_schema_version": performance.metadata.ledger_schema_version,
            "replay_timestamp": performance.metadata.replay_timestamp,
            "research_version": performance.metadata.research_version,
        },
        "metrics": {
            metric.name: _metric_payload(metric) for metric in performance.metrics
        },
    }
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
        stream.write("\n")
    return destination


def _validated_records(ledger):
    if not isinstance(ledger, ResearchLedgerV1):
        raise ResearchPerformanceError(
            "performance input must be a ResearchLedgerV1."
        )
    if ledger.schema_version != RESEARCH_LEDGER_SCHEMA_VERSION:
        raise ResearchPerformanceError("Unsupported Research Ledger schema version.")
    if not isinstance(ledger.records, tuple):
        raise ResearchPerformanceError("Research Ledger records must be a tuple.")

    seen_trade_ids = set()
    previous_sequence = None
    for record in ledger.records:
        for field in (
            "trade_id",
            "strategy_version",
            "dataset_version",
            "exit_reason",
            "first_sequence_number",
            "holding_calendar_days",
        ):
            if not hasattr(record, field):
                raise ResearchPerformanceError(
                    f"Research Ledger record is missing {field}."
                )
        if not isinstance(record.trade_id, str) or not record.trade_id:
            raise ResearchPerformanceError("trade_id must be a non-empty string.")
        if record.trade_id in seen_trade_ids:
            raise ResearchPerformanceError("trade_id values must be unique.")
        if (
            not isinstance(record.first_sequence_number, int)
            or isinstance(record.first_sequence_number, bool)
            or (
                previous_sequence is not None
                and record.first_sequence_number <= previous_sequence
            )
        ):
            raise ResearchPerformanceError(
                "Research Ledger records must retain canonical order."
            )
        if (
            not isinstance(record.holding_calendar_days, int)
            or isinstance(record.holding_calendar_days, bool)
            or record.holding_calendar_days < 0
        ):
            raise ResearchPerformanceError(
                "holding_calendar_days must be a non-negative integer."
            )
        if not isinstance(record.exit_reason, str) or not record.exit_reason:
            raise ResearchPerformanceError("exit_reason must be a non-empty string.")
        seen_trade_ids.add(record.trade_id)
        previous_sequence = record.first_sequence_number
    return ledger.records


def _metadata(records):
    if not records:
        return None, None
    strategy_version = records[0].strategy_version
    dataset_version = records[0].dataset_version
    if not isinstance(strategy_version, str) or not strategy_version:
        raise ResearchPerformanceError("strategy_version must be a non-empty string.")
    if not isinstance(dataset_version, str) or not dataset_version:
        raise ResearchPerformanceError("dataset_version must be a non-empty string.")
    for record in records[1:]:
        if record.strategy_version != strategy_version:
            raise ResearchPerformanceError("Ledger contains mixed strategy versions.")
        if record.dataset_version != dataset_version:
            raise ResearchPerformanceError("Ledger contains mixed dataset versions.")
    return strategy_version, dataset_version


def _validate_performance(performance):
    if not isinstance(performance, ResearchPerformanceV1):
        raise ResearchPerformanceError(
            "performance must be a ResearchPerformanceV1."
        )
    if performance.schema_version != RESEARCH_PERFORMANCE_VERSION:
        raise ResearchPerformanceError(
            "Unsupported Research Performance schema version."
        )
    names = tuple(metric.name for metric in performance.metrics)
    if names != AVAILABLE_METRICS + BLOCKED_METRICS:
        raise ResearchPerformanceError("Research Performance metric schema changed.")
    for metric in performance.metrics[: len(AVAILABLE_METRICS)]:
        if metric.status != "AVAILABLE" or metric.reason is not None:
            raise ResearchPerformanceError("Available metric evidence is invalid.")
    for metric in performance.metrics[len(AVAILABLE_METRICS) :]:
        if (
            metric.status != "BLOCKED"
            or metric.reason != "DEC-009"
            or metric.value is not None
        ):
            raise ResearchPerformanceError("Blocked metric evidence is invalid.")


def _metric_payload(metric):
    if metric.status == "BLOCKED":
        return {"status": metric.status, "reason": metric.reason}
    value = metric.value
    if isinstance(value, Decimal):
        value = _decimal_string(value)
    elif metric.name == "exit_reason_distribution":
        value = [
            {"exit_reason": item.exit_reason, "count": item.count}
            for item in value
        ]
    return {"status": metric.status, "value": value}


def _decimal_string(value):
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered
