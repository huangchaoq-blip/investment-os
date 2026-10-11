from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite


SUPPORTED_EVENT_TYPES = {
    "INTENT_RECEIVED",
    "ENTRY_PENDING",
    "ENTRY_FILLED",
    "ENTRY_REJECTED",
    "ENTRY_EXPIRED",
    "END_OF_DATA_REACHED",
    "STOP_TRIGGERED",
    "TARGET_TRIGGERED",
    "TREND_EXIT_TRIGGERED",
    "EXIT_FILLED",
    "POSITION_OPENED",
    "POSITION_ADJUSTED",
    "SPLIT_APPLIED",
    "POSITION_CLOSED",
    "CORPORATE_ACTION_BLOCKED",
    "DATA_GAP_OBSERVED",
}

ENTRY_FIELDS = (
    "position_id",
    "position_version",
    "quantity",
    "entry_date",
    "entry_price",
    "cost_per_share",
    "initial_stop",
    "target_price",
)
ADJUSTMENT_FIELDS = (
    "position_id",
    "position_version",
    "quantity",
    "cost_per_share",
    "initial_stop",
    "target_price",
)
CLOSE_FIELDS = (
    "position_id",
    "position_version",
    "exit_date",
    "exit_price",
    "exit_reason",
)


class PositionProjectionError(ValueError):
    """Raised when immutable ExecutionEvents cannot form a valid Position view."""


@dataclass(frozen=True)
class PositionSnapshot:
    position_id: str
    symbol: str
    position_status: str
    quantity: float
    entry_date: str
    entry_price: float
    cost_per_share: float
    initial_stop: float
    target_price: float
    position_version: int


def project_position(events: Sequence[Mapping]) -> PositionSnapshot | None:
    """Rebuild one DEC-008 Position Snapshot from ordered ExecutionEvents."""

    snapshot = None
    seen_event_ids = set()
    previous_sequence = 0
    run_metadata = None

    for event in events:
        run_metadata = _validate_event(
            event,
            seen_event_ids,
            previous_sequence,
            run_metadata,
        )
        sequence_number = event["sequence_number"]
        previous_sequence = sequence_number
        event_type = event["event_type"]

        if snapshot is not None and event["symbol"] != snapshot.symbol:
            raise PositionProjectionError(
                "ExecutionEvent symbol must match the current Position symbol."
            )

        if event_type == "ENTRY_FILLED":
            snapshot = _open_snapshot(event, snapshot)
        elif event_type in {"POSITION_ADJUSTED", "SPLIT_APPLIED"}:
            snapshot = _adjust_snapshot(event, snapshot)
        elif event_type == "POSITION_CLOSED":
            snapshot = _close_snapshot(event, snapshot)

    return snapshot


def _validate_event(event, seen_event_ids, previous_sequence, run_metadata):
    if not isinstance(event, Mapping):
        raise PositionProjectionError("ExecutionEvent must be a mapping.")
    for field in (
        "event_id",
        "sequence_number",
        "event_type",
        "symbol",
        "payload",
        "execution_run_id",
        "strategy_version",
        "dataset_version",
        "execution_config_version",
    ):
        if field not in event:
            raise PositionProjectionError(f"ExecutionEvent is missing required field: {field}.")
    event_id = event["event_id"]
    if not isinstance(event_id, str) or not event_id:
        raise PositionProjectionError("ExecutionEvent event_id must be a non-empty string.")
    if event_id in seen_event_ids:
        raise PositionProjectionError("ExecutionEvent event_id must not repeat.")
    seen_event_ids.add(event_id)
    sequence_number = event["sequence_number"]
    if isinstance(sequence_number, bool) or not isinstance(sequence_number, int):
        raise PositionProjectionError("ExecutionEvent sequence_number must be an integer.")
    if sequence_number != previous_sequence + 1:
        raise PositionProjectionError("ExecutionEvent sequence_number must be strictly consecutive.")
    if event["event_type"] not in SUPPORTED_EVENT_TYPES:
        raise PositionProjectionError(f"Unknown ExecutionEvent type: {event['event_type']}.")
    if not isinstance(event["symbol"], str) or not event["symbol"]:
        raise PositionProjectionError("ExecutionEvent symbol must be a non-empty string.")
    if not isinstance(event["payload"], Mapping):
        raise PositionProjectionError("ExecutionEvent payload must be a mapping.")
    metadata = tuple(
        _non_empty_string(event[field], f"ExecutionEvent {field}")
        for field in (
            "execution_run_id",
            "strategy_version",
            "dataset_version",
            "execution_config_version",
        )
    )
    if run_metadata is not None and metadata != run_metadata:
        raise PositionProjectionError(
            "ExecutionEvent stream must use one execution run and version metadata."
        )
    return metadata


def _open_snapshot(event, current):
    if current is not None and current.position_status == "OPEN":
        raise PositionProjectionError("ENTRY_FILLED cannot modify an existing Position.")
    payload = _canonical_payload(event, ENTRY_FIELDS)
    _matching_position_id(event, payload)
    if current is not None and current.position_id == payload["position_id"]:
        raise PositionProjectionError("ENTRY_FILLED cannot reopen a CLOSED Position.")
    if payload["position_version"] != 1:
        raise PositionProjectionError("ENTRY_FILLED position_version must equal 1.")
    _positive_integer(payload["position_version"], "ENTRY_FILLED position_version")
    return PositionSnapshot(
        position_id=payload["position_id"],
        symbol=event["symbol"],
        position_status="OPEN",
        quantity=_finite_positive(payload["quantity"], "ENTRY_FILLED quantity"),
        entry_date=_non_empty_string(payload["entry_date"], "ENTRY_FILLED entry_date"),
        entry_price=_finite_positive(payload["entry_price"], "ENTRY_FILLED entry_price"),
        cost_per_share=_finite_positive(
            payload["cost_per_share"], "ENTRY_FILLED cost_per_share"
        ),
        initial_stop=_finite_positive(
            payload["initial_stop"], "ENTRY_FILLED initial_stop"
        ),
        target_price=_finite_positive(
            payload["target_price"], "ENTRY_FILLED target_price"
        ),
        position_version=payload["position_version"],
    )


def _adjust_snapshot(event, current):
    _require_open_position(current, event["event_type"])
    payload = _canonical_payload(event, ADJUSTMENT_FIELDS)
    _matching_position_id(event, payload)
    _matching_snapshot_position(current, payload, event)
    next_version = _next_version(current, payload, event["event_type"])
    return PositionSnapshot(
        position_id=current.position_id,
        symbol=current.symbol,
        position_status="OPEN",
        quantity=_finite_positive(payload["quantity"], f"{event['event_type']} quantity"),
        entry_date=current.entry_date,
        entry_price=current.entry_price,
        cost_per_share=_finite_positive(
            payload["cost_per_share"], f"{event['event_type']} cost_per_share"
        ),
        initial_stop=_finite_positive(
            payload["initial_stop"], f"{event['event_type']} initial_stop"
        ),
        target_price=_finite_positive(
            payload["target_price"], f"{event['event_type']} target_price"
        ),
        position_version=next_version,
    )


def _close_snapshot(event, current):
    _require_open_position(current, "POSITION_CLOSED")
    payload = _canonical_payload(event, CLOSE_FIELDS)
    _matching_position_id(event, payload)
    _matching_snapshot_position(current, payload, event)
    next_version = _next_version(current, payload, "POSITION_CLOSED")
    _non_empty_string(payload["exit_date"], "POSITION_CLOSED exit_date")
    _finite_positive(payload["exit_price"], "POSITION_CLOSED exit_price")
    _non_empty_string(payload["exit_reason"], "POSITION_CLOSED exit_reason")
    return PositionSnapshot(
        **{
            **current.__dict__,
            "position_status": "CLOSED",
            "position_version": next_version,
        }
    )


def _canonical_payload(event, fields):
    payload = event["payload"]
    missing = [field for field in fields if field not in payload]
    if missing:
        raise PositionProjectionError(
            "ExecutionEvent payload is missing canonical fields: " + ", ".join(missing)
        )
    return payload


def _matching_position_id(event, payload):
    event_position_id = event.get("position_id")
    payload_position_id = _non_empty_string(payload["position_id"], "payload position_id")
    if event_position_id != payload_position_id:
        raise PositionProjectionError(
            "ExecutionEvent position_id must match payload position_id."
        )


def _matching_snapshot_position(current, payload, event):
    if current.position_id != payload["position_id"]:
        raise PositionProjectionError("ExecutionEvent position_id must match the OPEN Position.")
    if event["symbol"] != current.symbol:
        raise PositionProjectionError("ExecutionEvent symbol must match the OPEN Position.")


def _next_version(current, payload, event_type):
    version = _positive_integer(payload["position_version"], f"{event_type} position_version")
    if version != current.position_version + 1:
        raise PositionProjectionError(
            f"{event_type} position_version must increment by exactly one."
        )
    return version


def _require_open_position(current, event_type):
    if current is None:
        raise PositionProjectionError(f"{event_type} requires an OPEN Position.")
    if current.position_status != "OPEN":
        raise PositionProjectionError(f"{event_type} cannot modify a CLOSED Position.")


def _finite_positive(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PositionProjectionError(f"{field_name} must be a finite positive number.")
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise PositionProjectionError(f"{field_name} must be a finite positive number.")
    return value


def _positive_integer(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PositionProjectionError(f"{field_name} must be a positive integer.")
    return value


def _non_empty_string(value, field_name):
    if not isinstance(value, str) or not value:
        raise PositionProjectionError(f"{field_name} must be a non-empty string.")
    return value
