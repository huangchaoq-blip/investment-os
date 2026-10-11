"""Deterministic Portfolio Engine for bounded Replay state transitions."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
from types import MappingProxyType

from execution.context import ExecutionContext

from .aggregate import Cash, Portfolio, Position
from .persistence import portfolio_from_representation, serialize_portfolio
from .transaction import BUY_TRANSACTION, CLOSE_TRANSACTION, PortfolioTransaction
from .validation import PortfolioValidationResult, validate_portfolio


_EVENT_ROUTES = MappingProxyType(
    {
        "INTENT_RECEIVED": "_handle_intent_received",
        "INTENT_REJECTED": "_handle_not_implemented",
        "ENTRY_PENDING": "_handle_not_implemented",
        "ENTRY_FILLED": "_handle_entry_filled",
        "ENTRY_REJECTED": "_handle_entry_rejected",
        "ENTRY_EXPIRED": "_handle_not_implemented",
        "POSITION_OPENED": "_handle_not_implemented",
        "POSITION_ADJUSTED": "_handle_not_implemented",
        "POSITION_CLOSED": "_handle_position_closed",
        "STOP_TRIGGERED": "_handle_stop_triggered",
        "TARGET_TRIGGERED": "_handle_target_triggered",
        "TREND_EXIT_TRIGGERED": "_handle_trend_exit_triggered",
        "EXIT_FILLED": "_handle_not_implemented",
        "SPLIT_APPLIED": "_handle_not_implemented",
        "CORPORATE_ACTION_BLOCKED": "_handle_not_implemented",
        "DATA_GAP_OBSERVED": "_handle_not_implemented",
        "END_OF_DATA_REACHED": "_handle_not_implemented",
    }
)


@dataclass
class _LifecycleState:
    """Per-apply evidence state; it never becomes Portfolio aggregate state."""

    pending_intents: dict[str, str] = field(default_factory=dict)
    active_positions: dict[str, "_ActivePosition"] = field(default_factory=dict)
    seen_position_ids: set[str] = field(default_factory=set)


@dataclass
class _ActivePosition:
    symbol: str
    quantity: int | float
    position_version: int
    trigger_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PortfolioEngineResult:
    """Immutable session outcome required by ADR-006."""

    updated_portfolio: Portfolio
    transactions: tuple
    validation_outcome: PortfolioValidationResult
    state_fingerprint: str

    def __post_init__(self):
        if type(self.updated_portfolio) is not Portfolio:
            raise TypeError("updated_portfolio must be a Portfolio aggregate.")
        if not isinstance(self.transactions, tuple):
            raise TypeError("transactions must be an immutable tuple.")
        if any(type(item) is not PortfolioTransaction for item in self.transactions):
            raise TypeError(
                "transactions must contain immutable PortfolioTransaction values."
            )
        if type(self.validation_outcome) is not PortfolioValidationResult:
            raise TypeError(
                "validation_outcome must be a PortfolioValidationResult."
            )
        if (
            not isinstance(self.state_fingerprint, str)
            or not self.state_fingerprint
        ):
            raise ValueError("state_fingerprint must be a non-empty string.")


class PortfolioEngine:
    """Apply ordered ExecutionEvents to canonical Portfolio state."""

    def apply(self, context, portfolio_state, events):
        if type(context) is not ExecutionContext:
            raise TypeError("context must be an ExecutionContext.")

        portfolio = portfolio_from_representation(portfolio_state)
        if context.portfolio_id != portfolio.metadata.portfolio_id:
            raise ValueError("ExecutionContext and Portfolio identity mismatch.")

        event_batch = self._validate_event_batch(context, events)
        lifecycle = _LifecycleState()
        transactions = []
        for event in event_batch:
            handler = getattr(self, _EVENT_ROUTES[event["event_type"]])
            portfolio, produced = handler(context, portfolio, event, lifecycle)
            transactions.extend(produced)

        validation_outcome = validate_portfolio(portfolio)
        if not validation_outcome.valid:
            raise ValueError("Portfolio transition produced invalid Portfolio state.")
        canonical_state = serialize_portfolio(portfolio).encode("utf-8")
        return PortfolioEngineResult(
            updated_portfolio=portfolio,
            transactions=tuple(transactions),
            validation_outcome=validation_outcome,
            state_fingerprint=sha256(canonical_state).hexdigest(),
        )

    def _validate_event_batch(self, context, events):
        if not isinstance(events, tuple):
            raise TypeError("events must be an immutable ordered tuple.")

        previous_sequence = None
        previous_date = None
        event_ids = set()
        run_id = None
        for event in events:
            if type(event) is not MappingProxyType:
                raise TypeError(
                    "events must contain immutable ExecutionEvent mappings."
                )
            self._validate_immutable_value(event, "ExecutionEvent")

            event_type = event.get("event_type")
            if event_type not in _EVENT_ROUTES:
                raise ValueError("Unsupported ExecutionEvent type.")

            sequence = event.get("sequence_number")
            if (
                isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence < 1
            ):
                raise ValueError(
                    "ExecutionEvent sequence_number must be a positive integer."
                )
            if previous_sequence is not None and sequence != previous_sequence + 1:
                raise ValueError("ExecutionEvent batch must be continuous and ordered.")
            previous_sequence = sequence

            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                raise ValueError("ExecutionEvent event_id must be a non-empty string.")
            if event_id in event_ids:
                raise ValueError("ExecutionEvent batch must not repeat event_id values.")
            event_ids.add(event_id)

            event_date = event.get("event_date")
            if not isinstance(event_date, str):
                raise ValueError("ExecutionEvent event_date must use YYYY-MM-DD.")
            try:
                parsed_date = date.fromisoformat(event_date)
            except ValueError as error:
                raise ValueError(
                    "ExecutionEvent event_date must use YYYY-MM-DD."
                ) from error
            if context.execution_date is not None and parsed_date < date.fromisoformat(
                context.execution_date
            ):
                raise ValueError("ExecutionEvent predates the ExecutionContext.")
            if previous_date is not None and parsed_date < previous_date:
                raise ValueError("ExecutionEvent batch dates must be ordered.")
            previous_date = parsed_date

            expected_metadata = (
                ("schema_version", "execution-event-v1"),
                ("strategy_version", context.strategy_version),
                ("dataset_version", context.dataset_version),
                (
                    "execution_config_version",
                    context.execution_configuration_version,
                ),
            )
            if any(event.get(field) != expected for field, expected in expected_metadata):
                raise ValueError("ExecutionEvent metadata does not match ExecutionContext.")
            if event.get("symbol") not in context.universe:
                raise ValueError("ExecutionEvent symbol is outside ExecutionContext universe.")
            current_run_id = event.get("execution_run_id")
            if not isinstance(current_run_id, str) or not current_run_id:
                raise ValueError("ExecutionEvent execution_run_id must be a non-empty string.")
            if run_id is not None and current_run_id != run_id:
                raise ValueError("ExecutionEvent batch must use one execution_run_id.")
            run_id = current_run_id
            if "transaction_id" in event:
                raise ValueError("ExecutionEvent must not supply a Portfolio transaction_id.")

        return events

    def _validate_immutable_value(self, value, path):
        if isinstance(value, Mapping):
            if type(value) is not MappingProxyType:
                raise TypeError(f"{path} mappings must be immutable.")
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError(f"{path} field names must be strings.")
                self._validate_immutable_value(item, f"{path}.{key}")
            return
        if isinstance(value, tuple):
            for index, item in enumerate(value):
                self._validate_immutable_value(item, f"{path}[{index}]")
            return
        if value is None or isinstance(value, (str, int, float, bool)):
            return
        raise TypeError(f"{path} contains unsupported mutable evidence.")

    def _handle_intent_received(self, context, portfolio, event, lifecycle):
        del context
        intent_id = event.get("intent_id")
        payload = event["payload"]
        if (
            not isinstance(intent_id, str)
            or not intent_id
            or payload.get("requested_action") != "ENTER_LONG"
            or event.get("reason_code") != "INTENT_RECEIVED"
        ):
            raise ValueError("INTENT_RECEIVED evidence is invalid.")
        if intent_id in lifecycle.pending_intents:
            raise ValueError("INTENT_RECEIVED intent_id must not repeat.")
        lifecycle.pending_intents[intent_id] = event["symbol"]
        return portfolio, ()

    def _handle_entry_rejected(self, context, portfolio, event, lifecycle):
        del context
        intent_id = event.get("intent_id")
        if (
            not isinstance(intent_id, str)
            or lifecycle.pending_intents.get(intent_id) != event["symbol"]
        ):
            raise ValueError("ENTRY_REJECTED requires a matching pending Intent.")
        lifecycle.pending_intents.pop(intent_id)
        return portfolio, ()

    def _handle_entry_filled(self, context, portfolio, event, lifecycle):
        payload = event["payload"]
        self._validate_entry_filled(context, event, payload)
        intent_id = event.get("intent_id")
        if (
            not isinstance(intent_id, str)
            or lifecycle.pending_intents.get(intent_id) != event["symbol"]
        ):
            raise ValueError("ENTRY_FILLED requires a matching pending Intent.")
        if any(position.symbol == event["symbol"] for position in portfolio.positions):
            raise ValueError(
                "First BUY requires a Portfolio without existing Positions."
            )
        if event["position_id"] in lifecycle.seen_position_ids:
            raise ValueError("ENTRY_FILLED position_id must not repeat.")

        quantity = payload["quantity"]
        price = payload["entry_price"]
        gross_amount = quantity * payload["cost_per_share"]
        if portfolio.cash.amount < gross_amount:
            raise ValueError("Portfolio Cash is insufficient for the first BUY.")
        cash_balance_after = portfolio.cash.amount - gross_amount

        updated_portfolio = Portfolio(
            metadata=portfolio.metadata,
            cash=Cash(cash_balance_after),
            positions=portfolio.positions + (
                Position(
                    symbol=event["symbol"],
                    quantity=quantity,
                    average_cost=payload["cost_per_share"],
                ),
            ),
            statistics=portfolio.statistics,
        )
        transaction_fields = {
            "schema_version": "portfolio-transaction-v1",
            "transaction_type": BUY_TRANSACTION,
            "portfolio_id": portfolio.metadata.portfolio_id,
            "source_event_id": event["event_id"],
            "execution_run_id": event["execution_run_id"],
            "position_id": event["position_id"],
            "symbol": event["symbol"],
            "transaction_date": event["event_date"],
            "quantity": quantity,
            "price": price,
            "gross_amount": gross_amount,
            "cash_delta": -gross_amount,
            "cash_balance_after": cash_balance_after,
        }
        transaction = PortfolioTransaction(
            transaction_id=_transaction_id(transaction_fields),
            **transaction_fields,
        )
        lifecycle.pending_intents.pop(intent_id)
        lifecycle.seen_position_ids.add(event["position_id"])
        lifecycle.active_positions[event["position_id"]] = _ActivePosition(
            symbol=event["symbol"],
            quantity=quantity,
            position_version=payload["position_version"],
        )
        return updated_portfolio, (transaction,)

    def _validate_entry_filled(self, context, event, payload):
        required_payload = (
            "position_id",
            "position_version",
            "quantity",
            "entry_date",
            "entry_price",
            "cost_per_share",
            "initial_stop",
            "target_price",
        )
        missing = tuple(field for field in required_payload if field not in payload)
        if missing:
            raise ValueError(
                "ENTRY_FILLED payload is missing required evidence: "
                + ", ".join(missing)
                + "."
            )
        expected_metadata = (
            ("schema_version", "execution-event-v1"),
            ("event_type", "ENTRY_FILLED"),
            ("reason_code", "ENTRY_FILLED"),
            ("strategy_version", context.strategy_version),
            ("dataset_version", context.dataset_version),
            (
                "execution_config_version",
                context.execution_configuration_version,
            ),
        )
        if any(event.get(field) != expected for field, expected in expected_metadata):
            raise ValueError("ENTRY_FILLED metadata does not match ExecutionContext.")
        if event.get("symbol") not in context.universe:
            raise ValueError("ENTRY_FILLED symbol is outside ExecutionContext universe.")
        for field in ("event_id", "execution_run_id", "position_id"):
            value = event.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ENTRY_FILLED {field} must be a non-empty string.")
        if event["position_id"] != payload["position_id"]:
            raise ValueError("ENTRY_FILLED position_id evidence is inconsistent.")
        if payload["position_version"] != 1:
            raise ValueError("First BUY requires position_version 1.")
        if payload["entry_date"] != event["event_date"]:
            raise ValueError("ENTRY_FILLED entry_date must equal event_date.")
        for field in (
            "quantity",
            "entry_price",
            "cost_per_share",
            "initial_stop",
            "target_price",
        ):
            _require_positive_number(payload[field], f"ENTRY_FILLED payload.{field}")
        if payload["cost_per_share"] != payload["entry_price"]:
            raise ValueError("ENTRY_FILLED cost_per_share must equal entry_price in V1.")
        configured_quantity = context.execution_configuration_snapshot.get(
            "entry_quantity"
        )
        if payload["quantity"] != configured_quantity:
            raise ValueError(
                "ENTRY_FILLED quantity does not match ExecutionContext configuration."
            )

    def _handle_target_triggered(self, context, portfolio, event, lifecycle):
        return self._handle_exit_triggered(
            context, portfolio, event, lifecycle, "TARGET_TRIGGERED"
        )

    def _handle_stop_triggered(self, context, portfolio, event, lifecycle):
        return self._handle_exit_triggered(
            context, portfolio, event, lifecycle, "STOP_TRIGGERED"
        )

    def _handle_trend_exit_triggered(self, context, portfolio, event, lifecycle):
        return self._handle_exit_triggered(
            context, portfolio, event, lifecycle, "TREND_EXIT_TRIGGERED"
        )

    def _handle_exit_triggered(self, context, portfolio, event, lifecycle, event_type):
        del context
        payload = event["payload"]
        active_position = self._require_active_position(lifecycle, event, event_type)
        if (
            payload.get("position_id") != event["position_id"]
            or payload.get("position_version") != active_position.position_version
            or payload.get("trigger_reason") != event.get("reason_code")
        ):
            raise ValueError(f"{event_type} evidence does not match the open Position.")
        if active_position.trigger_reason is not None:
            raise ValueError("Open Position already has an exit trigger.")
        active_position.trigger_reason = event["reason_code"]
        return portfolio, ()

    def _handle_position_closed(self, context, portfolio, event, lifecycle):
        del context
        payload = event["payload"]
        active_position = self._require_active_position(lifecycle, event, "POSITION_CLOSED")
        if active_position.trigger_reason is None:
            raise ValueError("POSITION_CLOSED requires an accepted exit trigger.")
        expected_version = active_position.position_version + 1
        if (
            payload.get("position_id") != event["position_id"]
            or payload.get("position_version") != expected_version
            or payload.get("exit_date") != event.get("event_date")
            or payload.get("exit_reason") != active_position.trigger_reason
            or event.get("reason_code") != active_position.trigger_reason
        ):
            raise ValueError("POSITION_CLOSED evidence does not match the triggered Position.")
        _require_positive_number(payload.get("exit_price"), "POSITION_CLOSED payload.exit_price")
        if "quantity" in payload:
            _require_positive_number(
                payload["quantity"],
                "POSITION_CLOSED payload.quantity",
            )
            if payload["quantity"] != active_position.quantity:
                raise ValueError(
                    "POSITION_CLOSED quantity does not match the open Position."
                )
        positions = tuple(
            position
            for position in portfolio.positions
            if position.symbol != active_position.symbol
        )
        if len(positions) != len(portfolio.positions) - 1:
            raise ValueError("POSITION_CLOSED requires exactly one matching Portfolio Position.")
        gross_amount = active_position.quantity * payload["exit_price"]
        cash_balance_after = portfolio.cash.amount + gross_amount
        updated_portfolio = Portfolio(
            metadata=portfolio.metadata,
            cash=Cash(cash_balance_after),
            positions=positions,
            statistics=portfolio.statistics,
        )
        transaction_fields = {
            "schema_version": "portfolio-transaction-v1",
            "transaction_type": CLOSE_TRANSACTION,
            "portfolio_id": portfolio.metadata.portfolio_id,
            "source_event_id": event["event_id"],
            "execution_run_id": event["execution_run_id"],
            "position_id": event["position_id"],
            "symbol": active_position.symbol,
            "transaction_date": event["event_date"],
            "quantity": active_position.quantity,
            "price": payload["exit_price"],
            "gross_amount": gross_amount,
            "cash_delta": gross_amount,
            "cash_balance_after": cash_balance_after,
            "close_reason": payload["exit_reason"],
        }
        transaction = PortfolioTransaction(
            transaction_id=_transaction_id(transaction_fields),
            **transaction_fields,
        )
        lifecycle.active_positions.pop(event["position_id"])
        return updated_portfolio, (transaction,)

    def _require_active_position(self, lifecycle, event, event_type):
        active_position = lifecycle.active_positions.get(event.get("position_id"))
        if active_position is None:
            if lifecycle.active_positions:
                raise ValueError(
                    f"{event_type} Position identity does not match the open Position."
                )
            raise ValueError(f"{event_type} requires an open Portfolio Position.")
        if event.get("symbol") != active_position.symbol:
            raise ValueError(f"{event_type} Position identity does not match the open Position.")
        return active_position

    def _handle_not_implemented(self, context, portfolio, event, lifecycle):
        del context
        del portfolio
        del lifecycle
        raise NotImplementedError(
            f"Portfolio transition handler is not implemented for {event['event_type']}."
        )


def _require_positive_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a finite positive number.")
    if value <= 0 or (isinstance(value, float) and not _is_finite(value)):
        raise ValueError(f"{field} must be a finite positive number.")


def _is_finite(value):
    return value == value and value not in (float("inf"), float("-inf"))


def _transaction_id(fields):
    canonical = json.dumps(
        _canonical_transaction_value(fields),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "portfolio-transaction-v1-" + sha256(canonical).hexdigest()


def _canonical_transaction_value(value):
    if isinstance(value, dict):
        return {
            key: _canonical_transaction_value(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, float) and (value == 0 or value.is_integer()):
        return int(value)
    return value


__all__ = ["PortfolioEngine", "PortfolioEngineResult", "PortfolioTransaction"]
