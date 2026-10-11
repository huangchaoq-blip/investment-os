from collections.abc import Mapping
from datetime import date
from hashlib import sha256
import json
from math import isfinite
from types import MappingProxyType

from .entry import process_entry
from .exit import process_exit
from .exceptions import InvalidExecutionContextError, InvalidExecutionIntentError


INTENT_REQUIRED_FIELDS = (
    "intent_id",
    "requested_action",
    "symbol",
    "signal_date",
    "facts_date",
    "strategy_version",
    "dataset_version",
    "intent_reason_code",
)
CONTEXT_REQUIRED_FIELDS = (
    "execution_date",
    "market_data_snapshot",
    "corporate_action_snapshot",
    "current_position_projection",
    "execution_configuration_version",
    "execution_configuration_snapshot",
    "next_event_sequence_number",
    "execution_run_id",
    "strategy_version",
    "dataset_version",
)
MARKET_DATA_FIELDS = ("open", "high", "low", "close")
EVENT_SCHEMA_VERSION = "execution-event-v1"
ENGINE_VERSION = "execution-tick-runtime-v1"
NO_INTENT_MARKER = "<no-intent>"
NO_POSITION_MARKER = "<no-position>"


class ExecutionEngine:
    """Runs one deterministic ARCH-005 Execution Tick from explicit Context."""

    def execute(self, context, intent=None):
        self._validate_context(context)
        intent = self._intent_mapping(intent)
        if intent is not None:
            self._validate_intent(intent)
            self._validate_intent_context_versions(intent, context)

        event_factory, events = self._event_factory(context, intent)
        corporate_action_reason = self._corporate_action_block_reason(
            context["corporate_action_snapshot"]
        )
        if corporate_action_reason is not None:
            event_factory(
                event_type="CORPORATE_ACTION_BLOCKED",
                reason_code=corporate_action_reason,
                payload={"corporate_action_status": corporate_action_reason},
                symbol=self._event_symbol(context, intent),
            )
            return events

        position = context["current_position_projection"]
        position_is_open = position is not None and position.get("position_status") == "OPEN"
        if position_is_open:
            if intent is not None and intent["requested_action"] == "ENTER_LONG":
                raise InvalidExecutionIntentError(
                    "ENTER_LONG is invalid while current_position_projection is OPEN."
                )
            trend_exit = intent is not None and intent["requested_action"] == "EXIT_POSITION"
            process_exit(
                context=context,
                event_factory=event_factory,
                trend_exit=trend_exit,
            )
            return events

        if intent is None:
            return events
        if intent["requested_action"] == "EXIT_POSITION":
            raise InvalidExecutionIntentError(
                "EXIT_POSITION requires an OPEN current_position_projection."
            )

        event_factory(
            event_type="INTENT_RECEIVED",
            reason_code="INTENT_RECEIVED",
            payload={
                "requested_action": intent["requested_action"],
                "signal_date": intent["signal_date"],
                "facts_date": intent["facts_date"],
            },
        )
        process_entry(
            intent,
            context,
            event_factory,
            self._entry_position_id,
        )
        return events

    def _event_factory(self, context, intent):
        events = []
        outer_context = context
        outer_intent = intent

        def create(
            event_type,
            reason_code,
            payload,
            position_id=None,
            symbol=None,
            intent=None,
            context=None,
        ):
            execution_context = outer_context
            sequence_number = execution_context["next_event_sequence_number"] + len(events)
            event_symbol = symbol or self._event_symbol(execution_context, outer_intent)
            event_position_id = (
                self._position_id(execution_context["current_position_projection"])
                if position_id is None
                else position_id
            )
            event = self._event(
                context=execution_context,
                intent=outer_intent,
                event_type=event_type,
                reason_code=reason_code,
                payload=payload,
                sequence_number=sequence_number,
                symbol=event_symbol,
                position_id=event_position_id,
            )
            events.append(event)
            return event

        return create, events

    def _event(
        self,
        context,
        intent,
        event_type,
        reason_code,
        payload,
        sequence_number,
        symbol,
        position_id,
    ):
        intent_id = NO_INTENT_MARKER if intent is None else intent["intent_id"]
        event_payload = MappingProxyType(dict(payload))
        event = {
            "event_id": self._event_id(
                context=context,
                intent_id=intent_id,
                event_type=event_type,
                reason_code=reason_code,
                payload=event_payload,
                sequence_number=sequence_number,
                symbol=symbol,
                position_id=position_id,
            ),
            "schema_version": EVENT_SCHEMA_VERSION,
            "sequence_number": sequence_number,
            "event_type": event_type,
            "event_date": context["execution_date"],
            "symbol": symbol,
            "intent_id": None if intent is None else intent["intent_id"],
            "position_id": position_id,
            "strategy_version": context["strategy_version"],
            "dataset_version": context["dataset_version"],
            "execution_config_version": context["execution_configuration_version"],
            "execution_run_id": context["execution_run_id"],
            "payload": event_payload,
            "reason_code": reason_code,
            "deterministic_run_metadata": MappingProxyType(
                {
                    "engine_version": ENGINE_VERSION,
                    "execution_run_id": context["execution_run_id"],
                }
            ),
        }
        return MappingProxyType(event)

    def _validate_intent(self, intent):
        self._validate_mapping(intent, INTENT_REQUIRED_FIELDS, InvalidExecutionIntentError, "Intent")
        self._validate_required_values(intent, INTENT_REQUIRED_FIELDS, InvalidExecutionIntentError, "Intent")
        self._validate_date(intent["signal_date"], InvalidExecutionIntentError, "signal_date")
        self._validate_date(intent["facts_date"], InvalidExecutionIntentError, "facts_date")
        expected_reason_codes = {
            "ENTER_LONG": "PULLBACK_ENTRY",
            "EXIT_POSITION": "TREND_EXIT",
        }
        expected_reason_code = expected_reason_codes.get(intent["requested_action"])
        if expected_reason_code is None:
            raise InvalidExecutionIntentError(
                "requested_action must be ENTER_LONG or EXIT_POSITION."
            )
        if intent["intent_reason_code"] != expected_reason_code:
            raise InvalidExecutionIntentError(
                f"{intent['requested_action']} requires intent_reason_code "
                f"{expected_reason_code}."
            )
        if intent["requested_action"] == "ENTER_LONG":
            if "signal_stop" not in intent:
                raise InvalidExecutionIntentError("ENTER_LONG requires signal_stop.")
            self._validate_finite_positive(
                intent["signal_stop"], InvalidExecutionIntentError, "signal_stop"
            )

    def _validate_context(self, context):
        self._validate_mapping(
            context, CONTEXT_REQUIRED_FIELDS, InvalidExecutionContextError, "Context"
        )
        self._validate_required_values(
            context,
            (
                "execution_date",
                "execution_configuration_version",
                "execution_run_id",
                "strategy_version",
                "dataset_version",
                "execution_configuration_snapshot",
            ),
            InvalidExecutionContextError,
            "Context",
        )
        self._validate_date(
            context["execution_date"], InvalidExecutionContextError, "execution_date"
        )
        self._validate_positive_integer(
            context["next_event_sequence_number"],
            InvalidExecutionContextError,
            "next_event_sequence_number",
        )
        market_data = context["market_data_snapshot"]
        if market_data is not None:
            self._validate_mapping(
                market_data,
                MARKET_DATA_FIELDS,
                InvalidExecutionContextError,
                "Context market_data_snapshot",
            )
            for field in MARKET_DATA_FIELDS:
                self._validate_finite_positive(
                    market_data[field],
                    InvalidExecutionContextError,
                    f"market_data_snapshot.{field}",
                )
            if market_data["low"] > market_data["high"]:
                raise InvalidExecutionContextError(
                    "market_data_snapshot.low must not exceed market_data_snapshot.high."
                )
        if not isinstance(context["corporate_action_snapshot"], (tuple, list)):
            raise InvalidExecutionContextError(
                "Context corporate_action_snapshot must be a sequence."
            )
        position = context["current_position_projection"]
        if position is not None and not isinstance(position, Mapping):
            raise InvalidExecutionContextError(
                "Context current_position_projection must be a mapping or None."
            )
        configuration = context["execution_configuration_snapshot"]
        if not isinstance(configuration, Mapping):
            raise InvalidExecutionContextError(
                "Context execution_configuration_snapshot must be a mapping."
            )
        for field in ("max_initial_risk_pct", "target_r_multiple", "entry_quantity"):
            self._validate_finite_positive(
                configuration.get(field),
                InvalidExecutionContextError,
                f"execution_configuration_snapshot.{field}",
            )

    def _validate_intent_context_versions(self, intent, context):
        if intent["strategy_version"] != context["strategy_version"]:
            raise InvalidExecutionIntentError(
                "Intent strategy_version must match Context strategy_version."
            )
        if intent["dataset_version"] != context["dataset_version"]:
            raise InvalidExecutionIntentError(
                "Intent dataset_version must match Context dataset_version."
            )
        position = context["current_position_projection"]
        if position is not None and intent["symbol"] != position.get("symbol"):
            raise InvalidExecutionIntentError(
                "Intent symbol must match current_position_projection.symbol."
            )

    def _corporate_action_block_reason(self, actions):
        if not actions:
            return None
        for action in actions:
            if not isinstance(action, Mapping):
                return "UNSUPPORTED_CORPORATE_ACTION"
            status = str(action.get("normalization_status", "")).upper()
            if "AMBIGUOUS" in status:
                return "AMBIGUOUS_SPLIT"
            if status != "READY":
                return "UNKNOWN_CORPORATE_ACTION"
        return "UNSUPPORTED_CORPORATE_ACTION"

    def _entry_position_id(self, intent, context):
        payload = json.dumps(
            {
                "intent_id": intent["intent_id"],
                "symbol": intent["symbol"],
                "entry_date": context["execution_date"],
                "strategy_version": context["strategy_version"],
                "dataset_version": context["dataset_version"],
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return "position-v1-" + sha256(payload.encode("utf-8")).hexdigest()

    def _event_id(
        self,
        context,
        intent_id,
        event_type,
        reason_code,
        payload,
        sequence_number,
        symbol,
        position_id,
    ):
        fingerprint = {
            "execution_run_id": context["execution_run_id"],
            "sequence_number": sequence_number,
            "event_type": event_type,
            "event_date": context["execution_date"],
            "symbol": symbol,
            "intent_id": intent_id,
            "position_id": NO_POSITION_MARKER if position_id is None else position_id,
            "strategy_version": context["strategy_version"],
            "dataset_version": context["dataset_version"],
            "execution_config_version": context["execution_configuration_version"],
            "payload": payload,
            "reason_code": reason_code,
        }
        encoded = json.dumps(
            _canonicalize(fingerprint),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return "evt-v1-" + sha256(encoded.encode("utf-8")).hexdigest()

    def _event_symbol(self, context, intent):
        if intent is not None:
            return intent["symbol"]
        position = context["current_position_projection"]
        if position is not None:
            return position.get("symbol")
        actions = context["corporate_action_snapshot"]
        if actions and isinstance(actions[0], Mapping) and actions[0].get("code"):
            return str(actions[0]["code"])
        raise InvalidExecutionContextError(
            "Context requires an Intent, Position, or corporate action code to identify Event symbol."
        )

    def _intent_mapping(self, intent):
        if intent is None or isinstance(intent, Mapping):
            return intent
        to_dict = getattr(intent, "to_dict", None)
        if callable(to_dict):
            return MappingProxyType(to_dict())
        raise InvalidExecutionIntentError("Intent must be a mapping or provide to_dict().")

    def _validate_mapping(self, value, fields, error_type, name):
        if not isinstance(value, Mapping):
            raise error_type(f"{name} must be a mapping that follows its frozen Contract.")
        missing = [field for field in fields if field not in value]
        if missing:
            raise error_type(f"{name} is missing required fields: {', '.join(missing)}.")

    def _validate_required_values(self, value, fields, error_type, name):
        empty = [field for field in fields if value[field] is None or value[field] == ""]
        if empty:
            raise error_type(f"{name} has empty required fields: {', '.join(empty)}.")

    def _validate_date(self, value, error_type, field):
        if not isinstance(value, str):
            raise error_type(f"{field} must use YYYY-MM-DD.")
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise error_type(f"{field} must use YYYY-MM-DD.") from error

    def _validate_finite_positive(self, value, error_type, field):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise error_type(f"{field} must be a finite positive number.")
        if not isfinite(float(value)) or value <= 0:
            raise error_type(f"{field} must be a finite positive number.")

    def _validate_positive_integer(self, value, error_type, field):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise error_type(f"{field} must be a positive integer.")

    def _position_id(self, position):
        return None if position is None else position.get("position_id")


def _canonicalize(value):
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonicalize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Frozen Contract input contains non-deterministic value: {type(value).__name__}")
