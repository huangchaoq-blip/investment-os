from collections.abc import Mapping
from math import isfinite

from .exceptions import InvalidExecutionContextError


POSITION_REQUIRED_FIELDS = (
    "position_id",
    "symbol",
    "position_status",
    "quantity",
    "entry_date",
    "entry_price",
    "cost_per_share",
    "initial_stop",
    "target_price",
    "position_version",
)


def process_exit(context, event_factory, trend_exit):
    """Apply DEC-003 market exits, then an optional Strategy-confirmed trend exit."""

    position = _open_position(context["current_position_projection"])
    market_data = context["market_data_snapshot"]
    if not isinstance(market_data, Mapping):
        raise InvalidExecutionContextError(
            "Exit Processing requires a market_data_snapshot mapping."
        )

    open_price = _finite_positive(market_data.get("open"), "market_data_snapshot.open")
    high_price = _finite_positive(market_data.get("high"), "market_data_snapshot.high")
    low_price = _finite_positive(market_data.get("low"), "market_data_snapshot.low")
    if low_price > high_price:
        raise InvalidExecutionContextError(
            "market_data_snapshot.low must not exceed market_data_snapshot.high."
        )

    initial_stop = _finite_positive(
        position["initial_stop"], "current_position_projection.initial_stop"
    )
    target_price = _finite_positive(
        position["target_price"], "current_position_projection.target_price"
    )
    position_version = _positive_integer(
        position["position_version"], "current_position_projection.position_version"
    )

    outcome = _price_exit_outcome(
        open_price, high_price, low_price, initial_stop, target_price
    )
    if outcome is None:
        if not trend_exit:
            return []
        outcome = ("TREND_EXIT_NEXT_OPEN", open_price, "TREND_EXIT_TRIGGERED")

    reason_code, exit_price, trigger_type = outcome
    event_factory(
        event_type=trigger_type,
        reason_code=reason_code,
        payload={
            "position_id": position["position_id"],
            "position_version": position_version,
            "trigger_reason": reason_code,
        },
        position_id=position["position_id"],
    )
    return [
        event_factory(
            event_type="POSITION_CLOSED",
            reason_code=reason_code,
            payload={
                "position_id": position["position_id"],
                "position_version": position_version + 1,
                "exit_reason": reason_code,
                "exit_price": exit_price,
                "exit_date": context["execution_date"],
            },
            position_id=position["position_id"],
        )
    ]


def _price_exit_outcome(open_price, high_price, low_price, initial_stop, target_price):
    if open_price <= initial_stop:
        return "STOP_GAP", open_price, "STOP_TRIGGERED"
    if open_price >= target_price:
        return "TARGET_GAP", open_price, "TARGET_TRIGGERED"
    if low_price <= initial_stop and high_price >= target_price:
        return "STOP_TARGET_SAME_DAY_CONSERVATIVE", initial_stop, "STOP_TRIGGERED"
    if low_price <= initial_stop:
        return "STOP_INTRADAY", initial_stop, "STOP_TRIGGERED"
    if high_price >= target_price:
        return "TARGET_INTRADAY", target_price, "TARGET_TRIGGERED"
    return None


def _open_position(position):
    if not isinstance(position, Mapping):
        raise InvalidExecutionContextError(
            "Exit Processing requires current_position_projection."
        )
    missing = [field for field in POSITION_REQUIRED_FIELDS if field not in position]
    if missing:
        raise InvalidExecutionContextError(
            "current_position_projection is missing required fields: "
            + ", ".join(missing)
            + "."
        )
    empty = [
        field
        for field in ("position_id", "symbol", "position_status", "entry_date")
        if position[field] is None or position[field] == ""
    ]
    if empty:
        raise InvalidExecutionContextError(
            "current_position_projection has empty required fields: "
            + ", ".join(empty)
            + "."
        )
    if position["position_status"] != "OPEN":
        raise InvalidExecutionContextError(
            "Exit Processing requires current_position_projection.position_status OPEN."
        )
    for field in (
        "quantity",
        "entry_price",
        "cost_per_share",
        "initial_stop",
        "target_price",
    ):
        _finite_positive(position[field], f"current_position_projection.{field}")
    _positive_integer(
        position["position_version"], "current_position_projection.position_version"
    )
    return position


def _finite_positive(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidExecutionContextError(f"{field_name} must be a finite positive number.")
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise InvalidExecutionContextError(f"{field_name} must be a finite positive number.")
    return value


def _positive_integer(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidExecutionContextError(f"{field_name} must be a positive integer.")
    return value
