from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from collections.abc import Mapping
from typing import Optional


INTENT_ID_VERSION = "execution-intent-v1"
ENTRY_ACTION = "ENTER_LONG"
EXIT_ACTION = "EXIT_POSITION"
PULLBACK_ENTRY = "PULLBACK_ENTRY"
TREND_EXIT = "TREND_EXIT"


@dataclass(frozen=True)
class ExecutionIntent:
    """Immutable DEC-006 Strategy-to-Execution request."""

    intent_id: str
    requested_action: str
    intent_reason_code: str
    symbol: str
    signal_date: str
    facts_date: str
    strategy_version: str
    dataset_version: str
    signal_stop: Optional[float] = None

    def to_dict(self):
        return asdict(self)


def produce_execution_intent(facts, strategy_result, current_position_projection):
    """Produce one deterministic DEC-006 Intent or None without executing it."""

    if facts is None or strategy_result is None or facts.status != "READY":
        return None

    _validate_identity(facts, strategy_result)
    position_is_open = _position_status(current_position_projection) == "OPEN"

    if position_is_open and facts.signal_close < facts.ma75:
        return _intent(
            requested_action=EXIT_ACTION,
            intent_reason_code=TREND_EXIT,
            facts=facts,
            strategy_result=strategy_result,
        )

    if not position_is_open and strategy_result.decision == "BUY_CANDIDATE":
        signal_stop = _finite_positive(facts.provisional_stop, "facts.provisional_stop")
        return _intent(
            requested_action=ENTRY_ACTION,
            intent_reason_code=PULLBACK_ENTRY,
            facts=facts,
            strategy_result=strategy_result,
            signal_stop=signal_stop,
        )

    return None


def _intent(requested_action, intent_reason_code, facts, strategy_result, signal_stop=None):
    values = {
        "requested_action": requested_action,
        "intent_reason_code": intent_reason_code,
        "symbol": str(facts.code),
        "signal_date": str(facts.facts_date),
        "facts_date": str(facts.facts_date),
        "strategy_version": str(strategy_result.strategy_version),
        "dataset_version": str(facts.dataset_version),
    }
    return ExecutionIntent(
        intent_id=_intent_id(values),
        signal_stop=signal_stop,
        **values,
    )


def _intent_id(values):
    serialized = json.dumps(
        {"version": INTENT_ID_VERSION, **values},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{INTENT_ID_VERSION}-" + sha256(serialized.encode("utf-8")).hexdigest()


def _validate_identity(facts, strategy_result):
    required_facts = ("code", "facts_date", "dataset_version")
    missing = [field for field in required_facts if not getattr(facts, field, None)]
    if missing:
        raise ValueError("Facts missing required Intent fields: " + ", ".join(missing))
    if not getattr(strategy_result, "strategy_version", None):
        raise ValueError("Strategy result missing required Intent field: strategy_version")
    for field in ("code", "facts_date", "dataset_version"):
        result_value = getattr(strategy_result, field, None)
        if result_value is not None and str(result_value) != str(getattr(facts, field)):
            raise ValueError(f"Facts and Strategy result disagree on {field}.")


def _position_status(position):
    if position is None:
        return None
    if isinstance(position, Mapping):
        return position.get("position_status")
    return getattr(position, "position_status", None)


def _finite_positive(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite positive number.")
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be a finite positive number.")
    return value
