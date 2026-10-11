"""Stable Research Ledger V1 exports from immutable Trade Projection evidence."""

import csv
from dataclasses import dataclass
import json
from pathlib import Path

from projection import TradeProjectionResult, TradeRecord


RESEARCH_LEDGER_SCHEMA_VERSION = "trade-ledger-v1"

# V1 is explicit so future TradeRecord additions cannot silently change this contract.
RESEARCH_LEDGER_COLUMNS = (
    "trade_id",
    "position_id",
    "execution_run_id",
    "symbol",
    "strategy_version",
    "dataset_version",
    "execution_configuration_version",
    "entry_intent_id",
    "entry_date",
    "entry_price",
    "initial_quantity",
    "initial_cost_per_share",
    "initial_stop",
    "target_price",
    "entry_reason_code",
    "exit_intent_id",
    "exit_date",
    "exit_price",
    "exit_reason",
    "final_quantity",
    "final_cost_per_share",
    "final_position_version",
    "position_adjustment_count",
    "applied_adjustment_event_ids",
    "source_event_ids",
    "first_sequence_number",
    "last_sequence_number",
    "holding_calendar_days",
)

_SEQUENCE_COLUMNS = {
    "applied_adjustment_event_ids",
    "source_event_ids",
}


class ResearchLedgerContractError(ValueError):
    """Raised when Projection evidence cannot satisfy Research Ledger V1."""


@dataclass(frozen=True)
class ResearchLedgerV1:
    """Immutable closed-trade Projection selected for Research consumption."""

    schema_version: str
    records: tuple[TradeRecord, ...]


def build_research_ledger(projection: TradeProjectionResult) -> ResearchLedgerV1:
    """Select closed Trade Projection records without adding trade semantics."""
    if not isinstance(projection, TradeProjectionResult):
        raise ResearchLedgerContractError(
            "projection must be a TradeProjectionResult."
        )

    records = tuple(projection.closed_trades)
    seen_trade_ids = set()
    previous_sequence = None
    for record in records:
        _validate_record(record)
        if record.trade_id in seen_trade_ids:
            raise ResearchLedgerContractError("trade_id values must be unique.")
        if (
            previous_sequence is not None
            and record.first_sequence_number <= previous_sequence
        ):
            raise ResearchLedgerContractError(
                "Trade records must retain canonical event order."
            )
        _validate_projection_metadata(projection, record)
        seen_trade_ids.add(record.trade_id)
        previous_sequence = record.first_sequence_number

    return ResearchLedgerV1(RESEARCH_LEDGER_SCHEMA_VERSION, records)


def export_research_ledger_json(ledger: ResearchLedgerV1, path) -> Path:
    """Create one immutable UTF-8 JSON export and refuse replacement."""
    ledger = _validated_ledger(ledger)
    destination = _new_destination(path)
    payload = {
        "schema_version": ledger.schema_version,
        "columns": list(RESEARCH_LEDGER_COLUMNS),
        "records": [_json_row(record) for record in ledger.records],
    }
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
        stream.write("\n")
    return destination


def export_research_ledger_csv(ledger: ResearchLedgerV1, path) -> Path:
    """Create one immutable UTF-8 CSV export and refuse replacement."""
    ledger = _validated_ledger(ledger)
    destination = _new_destination(path)
    columns = ("schema_version",) + RESEARCH_LEDGER_COLUMNS
    with destination.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for record in ledger.records:
            writer.writerow(_csv_row(ledger.schema_version, record))
    return destination


def _validate_projection_metadata(projection, record):
    pairs = (
        ("execution_run_id", projection.execution_run_id, record.execution_run_id),
        ("strategy_version", projection.strategy_version, record.strategy_version),
        ("dataset_version", projection.dataset_version, record.dataset_version),
        (
            "execution_configuration_version",
            projection.execution_configuration_version,
            record.execution_configuration_version,
        ),
        ("symbol", projection.symbol, record.symbol),
    )
    mismatches = [name for name, expected, actual in pairs if expected != actual]
    if mismatches:
        raise ResearchLedgerContractError(
            "Trade record metadata differs from its Projection: "
            + ", ".join(mismatches)
            + "."
        )


def _validated_ledger(ledger):
    if not isinstance(ledger, ResearchLedgerV1):
        raise ResearchLedgerContractError("ledger must be a ResearchLedgerV1.")
    if ledger.schema_version != RESEARCH_LEDGER_SCHEMA_VERSION:
        raise ResearchLedgerContractError(
            "Unsupported Research Ledger schema version."
        )
    if not isinstance(ledger.records, tuple) or not all(
        isinstance(record, TradeRecord) for record in ledger.records
    ):
        raise ResearchLedgerContractError(
            "Research Ledger records must be an immutable TradeRecord tuple."
        )
    seen_trade_ids = set()
    previous_sequence = None
    for record in ledger.records:
        _validate_record(record)
        if record.trade_id in seen_trade_ids:
            raise ResearchLedgerContractError("trade_id values must be unique.")
        if (
            previous_sequence is not None
            and record.first_sequence_number <= previous_sequence
        ):
            raise ResearchLedgerContractError(
                "Trade records must retain canonical event order."
            )
        seen_trade_ids.add(record.trade_id)
        previous_sequence = record.first_sequence_number
    return ledger


def _validate_record(record):
    if not isinstance(record, TradeRecord):
        raise ResearchLedgerContractError(
            "closed_trades must contain TradeRecord values."
        )
    nullable = {"entry_intent_id", "exit_intent_id"}
    for column in RESEARCH_LEDGER_COLUMNS:
        value = getattr(record, column)
        if column in _SEQUENCE_COLUMNS:
            if not isinstance(value, tuple):
                raise ResearchLedgerContractError(
                    f"{column} must be an immutable tuple."
                )
        elif column not in nullable and value is None:
            raise ResearchLedgerContractError(f"{column} must not be null.")


def _new_destination(path):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(
            f"Research Ledger export already exists: {destination}."
        )
    return destination


def _json_row(record):
    return {
        column: (
            list(getattr(record, column))
            if column in _SEQUENCE_COLUMNS
            else getattr(record, column)
        )
        for column in RESEARCH_LEDGER_COLUMNS
    }


def _csv_row(schema_version, record):
    row = {"schema_version": schema_version}
    for column in RESEARCH_LEDGER_COLUMNS:
        value = getattr(record, column)
        if column in _SEQUENCE_COLUMNS:
            value = json.dumps(list(value), ensure_ascii=True, separators=(",", ":"))
        elif value is None:
            value = ""
        row[column] = value
    return row
