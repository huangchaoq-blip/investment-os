"""Pure reconstruction of one-symbol trade lifecycles from ExecutionEvents."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from math import isfinite
from collections.abc import Mapping, Sequence


class TradeProjectionError(ValueError):
    """Stable failure for an Event stream that cannot form canonical Trades."""


@dataclass(frozen=True)
class TradeRecord:
    trade_id: str; position_id: str; execution_run_id: str; symbol: str
    strategy_version: str; dataset_version: str; execution_configuration_version: str
    entry_intent_id: str | None; entry_date: str; entry_price: float; initial_quantity: float
    initial_cost_per_share: float; initial_stop: float; target_price: float; entry_reason_code: str
    exit_intent_id: str | None; exit_date: str; exit_price: float; exit_reason: str
    final_quantity: float; final_cost_per_share: float; final_position_version: int
    position_adjustment_count: int; applied_adjustment_event_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]; first_sequence_number: int; last_sequence_number: int
    holding_calendar_days: int


@dataclass(frozen=True)
class OpenTradeRecord:
    trade_id: str; position_id: str; execution_run_id: str; symbol: str
    strategy_version: str; dataset_version: str; execution_configuration_version: str
    entry_intent_id: str | None; entry_date: str; entry_price: float; current_quantity: float
    current_cost_per_share: float; current_stop: float; target_price: float; current_position_version: int
    position_adjustment_count: int; applied_adjustment_event_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]; first_sequence_number: int; last_sequence_number: int


@dataclass(frozen=True)
class TradeProjectionResult:
    execution_run_id: str | None; strategy_version: str | None; dataset_version: str | None
    execution_configuration_version: str | None; symbol: str | None
    closed_trades: tuple[TradeRecord, ...]; open_trade: OpenTradeRecord | None
    source_event_count: int; last_sequence_number: int | None; status: str
    warnings: tuple[str, ...]; limitations: tuple[str, ...]


def project_trades(events: Sequence[Mapping]) -> TradeProjectionResult:
    """Project immutable Events only; no market, Strategy, or Execution access."""
    if not events:
        return TradeProjectionResult(None, None, None, None, None, (), None, 0, None, "EMPTY", (), ())
    metadata = _validate_stream(events)
    current = None; closed = []; blocked = False
    for event in events:
        kind = event["event_type"]
        if kind == "CORPORATE_ACTION_BLOCKED":
            blocked = True; continue
        if kind == "ENTRY_FILLED":
            if current is not None: _fail("OVERLAPPING_POSITIONS")
            current = _open(event, metadata)
        elif kind in {"POSITION_ADJUSTED", "SPLIT_APPLIED"}:
            if current is None: _fail("UNSUPPORTED_EVENT_TRANSITION")
            _adjust(current, event)
        elif kind == "POSITION_CLOSED":
            if current is None: _fail("DUPLICATE_POSITION_CLOSE")
            closed.append(_close(current, event)); current = None
        elif kind in {"INTENT_RECEIVED", "ENTRY_REJECTED", "END_OF_DATA_REACHED", "STOP_TRIGGERED", "TARGET_TRIGGERED", "TREND_EXIT_TRIGGERED"}:
            if current is not None and event.get("position_id") not in {None, current["position_id"]}:
                _fail("POSITION_ID_MISMATCH")
            if current is not None and kind in {"STOP_TRIGGERED", "TARGET_TRIGGERED", "TREND_EXIT_TRIGGERED"}:
                current["ids"].append(event["event_id"]); current["last"] = event["sequence_number"]
        elif kind in {"POSITION_OPENED", "EXIT_FILLED", "ENTRY_PENDING", "ENTRY_EXPIRED", "DATA_GAP_OBSERVED"}:
            _fail("UNSUPPORTED_EVENT_TRANSITION")
        else:
            _fail("UNSUPPORTED_EVENT_TRANSITION")
    open_trade = _open_record(current) if current is not None else None
    status = "BLOCKED_WITH_OPEN_TRADE" if blocked and open_trade else ("COMPLETE_WITH_OPEN_TRADE" if open_trade else "COMPLETE")
    return TradeProjectionResult(*metadata, tuple(closed), open_trade, len(events), events[-1]["sequence_number"], status, (), ("CORPORATE_ACTION_BLOCKED" if blocked else "",) if blocked else ())


def _validate_stream(events):
    ids = set(); first = events[0]["sequence_number"]; metadata = None
    for offset, event in enumerate(events):
        required = ("event_id", "sequence_number", "event_type", "symbol", "payload", "execution_run_id", "strategy_version", "dataset_version", "execution_config_version")
        if not isinstance(event, Mapping) or any(field not in event for field in required): _fail("INCOMPLETE_EVENT_EVIDENCE")
        if event["sequence_number"] != first + offset: _fail("NON_CONTIGUOUS_SEQUENCE")
        if event["event_id"] in ids: _fail("DUPLICATE_EVENT_ID")
        ids.add(event["event_id"])
        value = (event["execution_run_id"], event["strategy_version"], event["dataset_version"], event["execution_config_version"], event["symbol"])
        if not all(isinstance(item, str) and item for item in value): _fail("MIXED_VERSION_METADATA")
        if metadata is not None and value != metadata:
            _fail("MIXED_EXECUTION_RUN" if value[0] != metadata[0] else "MIXED_VERSION_METADATA")
        metadata = value
    return metadata


def _open(event, metadata):
    p = event["payload"]; needed = ("position_id", "position_version", "quantity", "entry_date", "entry_price", "cost_per_share", "initial_stop", "target_price")
    if any(field not in p for field in needed) or event.get("position_id") != p.get("position_id"): _fail("INCOMPLETE_ENTRY_EVIDENCE")
    if p["position_version"] != 1: _fail("POSITION_VERSION_MISMATCH")
    for field in ("quantity", "entry_price", "cost_per_share", "initial_stop", "target_price"):
        if not _positive(p[field]): _fail("INCOMPLETE_ENTRY_EVIDENCE")
    return {"position_id": p["position_id"], "metadata": metadata, "entry_intent_id": event.get("intent_id"), "entry_date": p["entry_date"], "entry_price": float(p["entry_price"]), "initial_quantity": float(p["quantity"]), "initial_cost": float(p["cost_per_share"]), "initial_stop": float(p["initial_stop"]), "target": float(p["target_price"]), "quantity": float(p["quantity"]), "cost": float(p["cost_per_share"]), "stop": float(p["initial_stop"]), "version": 1, "entry_reason": event.get("reason_code"), "ids": [event["event_id"]], "first": event["sequence_number"], "last": event["sequence_number"], "adjustments": []}


def _adjust(current, event):
    p = event["payload"]; needed = ("position_id", "position_version", "quantity", "cost_per_share", "initial_stop", "target_price")
    if any(field not in p for field in needed) or p["position_id"] != current["position_id"] or event.get("position_id") != current["position_id"]: _fail("POSITION_ID_MISMATCH")
    if p["position_version"] != current["version"] + 1: _fail("POSITION_VERSION_MISMATCH")
    for field in ("quantity", "cost_per_share", "initial_stop", "target_price"):
        if not _positive(p[field]): _fail("INCOMPLETE_EVENT_EVIDENCE")
    current.update(quantity=float(p["quantity"]), cost=float(p["cost_per_share"]), stop=float(p["initial_stop"]), target=float(p["target_price"]), version=p["position_version"], last=event["sequence_number"]); current["ids"].append(event["event_id"]); current["adjustments"].append(event["event_id"])


def _close(current, event):
    p = event["payload"]; needed = ("position_id", "position_version", "exit_date", "exit_price", "exit_reason")
    if any(field not in p for field in needed): _fail("INCOMPLETE_EXIT_EVIDENCE")
    if p["position_id"] != current["position_id"] or event.get("position_id") != current["position_id"]: _fail("POSITION_ID_MISMATCH")
    if p["position_version"] != current["version"] + 1: _fail("POSITION_VERSION_MISMATCH")
    if not _positive(p["exit_price"]): _fail("INCOMPLETE_EXIT_EVIDENCE")
    current["ids"].append(event["event_id"]); current["last"] = event["sequence_number"]
    return TradeRecord(_trade_id(current), current["position_id"], *_record_metadata(current), current["entry_intent_id"], current["entry_date"], current["entry_price"], current["initial_quantity"], current["initial_cost"], current["initial_stop"], current["target"], current["entry_reason"], event.get("intent_id"), p["exit_date"], float(p["exit_price"]), p["exit_reason"], current["quantity"], current["cost"], p["position_version"], len(current["adjustments"]), tuple(current["adjustments"]), tuple(current["ids"]), current["first"], current["last"], (date.fromisoformat(p["exit_date"]) - date.fromisoformat(current["entry_date"])).days)


def _open_record(current):
    return OpenTradeRecord(_trade_id(current), current["position_id"], *_record_metadata(current), current["entry_intent_id"], current["entry_date"], current["entry_price"], current["quantity"], current["cost"], current["stop"], current["target"], current["version"], len(current["adjustments"]), tuple(current["adjustments"]), tuple(current["ids"]), current["first"], current["last"])


def _record_metadata(current):
    run, strategy, dataset, config, symbol = current["metadata"]
    return run, symbol, strategy, dataset, config


def _trade_id(current):
    payload = json.dumps({"run": current["metadata"][0], "position": current["position_id"], "symbol": current["metadata"][4], "entry": current["entry_date"], "strategy": current["metadata"][1], "dataset": current["metadata"][2], "config": current["metadata"][3]}, sort_keys=True, separators=(",", ":"))
    return "trade-v1-" + sha256(payload.encode()).hexdigest()


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value)) and value > 0


def _fail(code):
    raise TradeProjectionError(code)
