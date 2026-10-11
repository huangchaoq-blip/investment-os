from math import isfinite
from types import MappingProxyType

from .exceptions import InvalidExecutionContextError, InvalidExecutionIntentError


def process_entry(intent, context, event_factory, position_id_factory):
    """Apply only DEC-003 entry acceptance, rejection, and end-of-data rules."""

    market_data = context["market_data_snapshot"]
    if market_data is None:
        return [
            event_factory(
                intent=intent,
                context=context,
                event_type="END_OF_DATA_REACHED",
                reason_code="UNFILLED_END_OF_DATA",
                payload={"requested_action": intent["requested_action"]},
            )
        ]

    entry_price = _finite_positive(
        market_data.get("open"),
        InvalidExecutionContextError,
        "market_data_snapshot.open",
    )
    signal_stop = _finite_positive(
        intent["signal_stop"],
        InvalidExecutionIntentError,
        "signal_stop",
    )
    configuration = context["execution_configuration_snapshot"]
    max_initial_risk_pct = _finite_positive(
        configuration.get("max_initial_risk_pct"),
        InvalidExecutionContextError,
        "execution_configuration_snapshot.max_initial_risk_pct",
    )
    target_r_multiple = _finite_positive(
        configuration.get("target_r_multiple"),
        InvalidExecutionContextError,
        "execution_configuration_snapshot.target_r_multiple",
    )
    entry_quantity = _finite_positive(
        configuration.get("entry_quantity"),
        InvalidExecutionContextError,
        "execution_configuration_snapshot.entry_quantity",
    )
    shared_available_cash = configuration.get("shared_available_cash")
    if shared_available_cash is not None:
        shared_available_cash = _finite_nonnegative(
            shared_available_cash,
            InvalidExecutionContextError,
            "execution_configuration_snapshot.shared_available_cash",
        )

    if entry_price <= signal_stop:
        return [
            event_factory(
                intent=intent,
                context=context,
                event_type="ENTRY_REJECTED",
                reason_code="ENTRY_GAP_BELOW_STOP",
                payload={
                    "entry_price": entry_price,
                    "signal_stop": signal_stop,
                },
            )
        ]

    actual_risk = entry_price - signal_stop
    actual_risk_pct = actual_risk / entry_price
    if actual_risk_pct > max_initial_risk_pct:
        return [
            event_factory(
                intent=intent,
                context=context,
                event_type="ENTRY_REJECTED",
                reason_code="ENTRY_RISK_EXCEEDED",
                payload={
                    "entry_price": entry_price,
                    "signal_stop": signal_stop,
                    "actual_risk": actual_risk,
                    "actual_risk_pct": actual_risk_pct,
                },
            )
        ]

    required_cash = entry_price * entry_quantity
    if shared_available_cash is not None and required_cash > shared_available_cash:
        return [
            event_factory(
                intent=intent,
                context=context,
                event_type="ENTRY_REJECTED",
                reason_code="ENTRY_INSUFFICIENT_CASH",
                payload={
                    "entry_price": entry_price,
                    "quantity": entry_quantity,
                    "required_cash": required_cash,
                    "available_cash": shared_available_cash,
                },
            )
        ]

    target_price = entry_price + target_r_multiple * actual_risk
    position_id = position_id_factory(intent, context)
    return [
        event_factory(
            intent=intent,
            context=context,
            event_type="ENTRY_FILLED",
            reason_code="ENTRY_FILLED",
            payload={
                "position_id": position_id,
                "position_version": 1,
                "quantity": entry_quantity,
                "entry_date": context["execution_date"],
                "entry_price": entry_price,
                "cost_per_share": entry_price,
                "initial_stop": signal_stop,
                "actual_risk": actual_risk,
                "actual_risk_pct": actual_risk_pct,
                "target_price": target_price,
            },
            position_id=position_id,
        )
    ]


def _finite_positive(value, error_type, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error_type(f"{field_name} must be a finite positive number.")
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise error_type(f"{field_name} must be a finite positive number.")
    return value


def _finite_nonnegative(value, error_type, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error_type(f"{field_name} must be a finite non-negative number.")
    value = float(value)
    if not isfinite(value) or value < 0:
        raise error_type(f"{field_name} must be a finite non-negative number.")
    return value
