"""Deterministic historical scheduling for the frozen Execution contracts."""

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from types import MappingProxyType

import pandas as pd

from data.historical_ingestion import DEFAULT_DATASET_ROOT, load_versioned_dataset
from data_platform.publisher import DatasetPublisher, PublicationState
from data_platform.registration import read_publication_evidence
from execution import ExecutionContext, ExecutionEngine
from facts import build_pullback_facts
from portfolio.aggregate import Cash, Metadata, Portfolio
from portfolio.engine import PortfolioEngine
from portfolio.persistence import portfolio_to_representation
from projection import PositionProjectionError, project_position
from strategy import evaluate_pullback_candidate, produce_execution_intent


REPLAY_SCHEMA_VERSION = "historical-replay-v1"
VALID_STATUSES = {
    "COMPLETED",
    "COMPLETED_WITH_OPEN_POSITION",
    "BLOCKED_CORPORATE_ACTION",
    "NO_DATA",
}


class ReplayInputError(ValueError):
    """Raised for inputs that cannot satisfy the frozen replay boundary."""


@dataclass(frozen=True)
class ReplayRequest:
    symbol: str
    dataset_version: str
    requested_start_date: str
    requested_end_date: str
    strategy_version: str
    execution_configuration_version: str
    execution_configuration_snapshot: dict
    corporate_action_version: str
    initial_events: tuple = ()


@dataclass(frozen=True)
class SharedPortfolioReplayRequest:
    """Additive input for a fixed multi-symbol Replay against one Portfolio."""

    symbols: tuple[str, ...]
    dataset_version: str
    requested_start_date: str
    requested_end_date: str
    strategy_version: str
    execution_configuration_version: str
    execution_configuration_snapshot: dict
    corporate_action_version: str
    initial_shared_cash: int | float
    portfolio_id: str

    def __post_init__(self):
        if isinstance(self.symbols, (str, bytes)) or not isinstance(
            self.symbols, (tuple, list)
        ):
            raise ReplayInputError("symbols must be a sequence of non-empty symbols.")
        symbols = tuple(sorted({str(symbol).strip() for symbol in self.symbols}))
        if not symbols or any(not symbol for symbol in symbols):
            raise ReplayInputError("symbols must contain non-empty symbols.")
        object.__setattr__(self, "symbols", symbols)


@dataclass(frozen=True)
class DailyPortfolioSnapshot:
    """Deterministic end-of-day valuation for one shared Portfolio."""

    trading_date: str
    cash: int | float
    holding_market_value: int | float
    total_equity: int | float
    open_position_count: int


@dataclass(frozen=True)
class SharedPortfolioReplayResult:
    """Immutable result of the additive shared-Portfolio Replay path."""

    execution_run_id: str
    symbols: tuple[str, ...]
    dataset_version: str
    strategy_version: str
    execution_configuration_version: str
    requested_start_date: str
    requested_end_date: str
    events: tuple
    final_portfolio: Portfolio
    final_position_projections: MappingProxyType
    portfolio_transactions: tuple
    daily_portfolio_snapshots: tuple[DailyPortfolioSnapshot, ...]
    status: str
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    result_checksum: str


@dataclass(frozen=True)
class ReplayResult:
    execution_run_id: str
    symbol: str
    dataset_version: str
    strategy_version: str
    execution_configuration_version: str
    requested_start_date: str
    requested_end_date: str
    actual_start_date: str | None
    actual_end_date: str | None
    events: tuple
    final_position: object
    status: str
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]


class HistoricalReplayOrchestrator:
    """Advance fixed historical bars without owning execution business rules."""

    def __init__(
        self,
        dataset_root=DEFAULT_DATASET_ROOT,
        execution_engine=None,
        facts_builder=build_pullback_facts,
        strategy_evaluator=evaluate_pullback_candidate,
        intent_producer=produce_execution_intent,
        dataset_loader=None,
    ):
        self._dataset_root = Path(dataset_root)
        self._execution_engine = execution_engine or ExecutionEngine()
        self._facts_builder = facts_builder
        self._strategy_evaluator = strategy_evaluator
        self._intent_producer = intent_producer
        self._dataset_loader = dataset_loader or _load_dataset

    def replay(self, request):
        self._validate_request(request)
        run_id = _execution_run_id(request)
        events = list(request.initial_events)
        _validate_initial_events(events, request, run_id)
        next_sequence = 1 if not events else events[-1]["sequence_number"] + 1

        dataset = self._dataset_loader(request.dataset_version, self._dataset_root)
        bars = _market_bars(dataset["bars"], request)
        limitations = tuple(dataset.get("limitations", ()))
        if bars.empty:
            return self._result(request, run_id, (), None, "NO_DATA", (), limitations)

        actions = dataset.get("corporate_actions", pd.DataFrame())
        pending_intent = None
        actual_start = bars.iloc[0]["date"]
        actual_end = bars.iloc[-1]["date"]

        for _, row in bars.iterrows():
            current_date = row["date"]
            context = _context(
                request=request,
                run_id=run_id,
                next_sequence=next_sequence,
                row=row,
                actions=_actions_for_day(actions, request.symbol, current_date),
                position=_project(events),
            )
            tick_events = self._execution_engine.execute(context, pending_intent)
            _validate_tick_events(tick_events, next_sequence, request, run_id)
            events.extend(tick_events)
            next_sequence += len(tick_events)
            pending_intent = None

            if any(event["event_type"] == "CORPORATE_ACTION_BLOCKED" for event in tick_events):
                return self._result(
                    request, run_id, events, _project(events), "BLOCKED_CORPORATE_ACTION",
                    (), limitations, actual_start, current_date,
                )

            facts = self._facts_builder(
                request.symbol,
                current_date,
                request.dataset_version,
                self._dataset_root,
            )
            strategy_result = self._strategy_evaluator(facts)
            pending_intent = self._intent_producer(
                facts, strategy_result, _project(events)
            )

        if pending_intent is not None:
            context = _context(
                request=request,
                run_id=run_id,
                next_sequence=next_sequence,
                row=None,
                actions=(),
                position=_project(events),
                execution_date=actual_end,
            )
            end_events = self._execution_engine.execute(context, pending_intent)
            _validate_tick_events(end_events, next_sequence, request, run_id)
            events.extend(end_events)

        final_position = _project(events)
        status = "COMPLETED_WITH_OPEN_POSITION" if _is_open(final_position) else "COMPLETED"
        return self._result(
            request, run_id, events, final_position, status, (), limitations,
            actual_start, actual_end,
        )

    def replay_shared_portfolio(self, request):
        """Replay a fixed Symbol set in global date order against one Portfolio."""

        self._validate_shared_request(request)
        run_id = _shared_execution_run_id(request)
        dataset = self._dataset_loader(request.dataset_version, self._dataset_root)
        limitations = tuple(dataset.get("limitations", ()))
        actions = dataset.get("corporate_actions", pd.DataFrame())
        bars_by_symbol = {
            symbol: _market_bars(dataset["bars"], request, symbol)
            for symbol in request.symbols
        }
        missing = tuple(symbol for symbol, bars in bars_by_symbol.items() if bars.empty)
        if missing:
            raise ReplayInputError(
                "Dataset has no bars for shared Replay symbols: " + ", ".join(missing)
            )

        rows_by_date = {}
        for symbol, bars in bars_by_symbol.items():
            for _, row in bars.iterrows():
                rows_by_date.setdefault(row["date"], {})[symbol] = row

        events = []
        pending_intents = {symbol: None for symbol in request.symbols}
        active_positions = {}
        position_event_streams = {symbol: [] for symbol in request.symbols}
        next_sequence = 1
        snapshots = []
        status = "COMPLETED"

        for current_date in sorted(rows_by_date):
            rows = rows_by_date[current_date]

            # Phase 1: positions already open at this day's open exit before entries.
            for symbol in request.symbols:
                position = active_positions.get(symbol)
                if position is None or symbol not in rows:
                    continue
                tick_events = self._execution_engine.execute(
                    _context(
                        request=request,
                        run_id=run_id,
                        next_sequence=next_sequence,
                        row=rows[symbol],
                        actions=_actions_for_day(actions, symbol, current_date),
                        position=position,
                    ),
                    pending_intents[symbol],
                )
                _validate_tick_events(tick_events, next_sequence, request, run_id)
                events.extend(tick_events)
                _update_shared_position_cache(
                    active_positions, position_event_streams, tick_events
                )
                next_sequence += len(tick_events)
                pending_intents[symbol] = None
                if any(event["event_type"] == "CORPORATE_ACTION_BLOCKED" for event in tick_events):
                    status = "BLOCKED_CORPORATE_ACTION"
                    break
            if status == "BLOCKED_CORPORATE_ACTION":
                break

            # Phase 2: cash released by exits is available to same-day entries.
            for symbol in request.symbols:
                intent = pending_intents[symbol]
                if (
                    intent is None
                    or _intent_action(intent) != "ENTER_LONG"
                    or symbol in active_positions
                    or symbol not in rows
                ):
                    continue
                available_cash = _shared_portfolio_result(request, events).updated_portfolio.cash.amount
                tick_events = self._execution_engine.execute(
                    _context(
                        request=request,
                        run_id=run_id,
                        next_sequence=next_sequence,
                        row=rows[symbol],
                        actions=_actions_for_day(actions, symbol, current_date),
                        position=None,
                        shared_available_cash=available_cash,
                    ),
                    intent,
                )
                _validate_tick_events(tick_events, next_sequence, request, run_id)
                events.extend(tick_events)
                _update_shared_position_cache(
                    active_positions, position_event_streams, tick_events
                )
                next_sequence += len(tick_events)
                pending_intents[symbol] = None

            # Phase 3: close-based decisions are queued for each symbol's next bar.
            for symbol in request.symbols:
                if symbol not in rows:
                    continue
                position = active_positions.get(symbol)
                facts = self._facts_builder(
                    symbol,
                    current_date,
                    request.dataset_version,
                    self._dataset_root,
                )
                strategy_result = self._strategy_evaluator(facts)
                pending_intents[symbol] = self._intent_producer(
                    facts, strategy_result, position
                )

            portfolio_result = _shared_portfolio_result(request, events)
            snapshots.append(
                _daily_snapshot(current_date, portfolio_result.updated_portfolio, rows)
            )

        if status == "COMPLETED":
            # Preserve the single-symbol end-of-data evidence for unfilled entries.
            for symbol in request.symbols:
                intent = pending_intents[symbol]
                if intent is None or _intent_action(intent) != "ENTER_LONG":
                    continue
                tick_events = self._execution_engine.execute(
                    _context(
                        request=request,
                        run_id=run_id,
                        next_sequence=next_sequence,
                        row=None,
                        actions=(),
                        position=None,
                    ),
                    intent,
                )
                _validate_tick_events(tick_events, next_sequence, request, run_id)
                events.extend(tick_events)
                next_sequence += len(tick_events)

        portfolio_result = _shared_portfolio_result(request, events)
        final_positions = MappingProxyType(
            {
                symbol: _position_mapping(active_positions.get(symbol))
                for symbol in request.symbols
            }
        )
        if status == "COMPLETED" and final_positions and any(
            value is not None for value in final_positions.values()
        ):
            status = "COMPLETED_WITH_OPEN_POSITION"
        checksum = _shared_result_checksum(
            request,
            run_id,
            events,
            portfolio_result.updated_portfolio,
            snapshots,
            status,
        )
        return SharedPortfolioReplayResult(
            execution_run_id=run_id,
            symbols=request.symbols,
            dataset_version=request.dataset_version,
            strategy_version=request.strategy_version,
            execution_configuration_version=request.execution_configuration_version,
            requested_start_date=request.requested_start_date,
            requested_end_date=request.requested_end_date,
            events=tuple(events),
            final_portfolio=portfolio_result.updated_portfolio,
            final_position_projections=final_positions,
            portfolio_transactions=portfolio_result.transactions,
            daily_portfolio_snapshots=tuple(snapshots),
            status=status,
            warnings=(),
            limitations=limitations,
            result_checksum=checksum,
        )

    def _result(
        self, request, run_id, events, position, status, warnings, limitations,
        actual_start=None, actual_end=None,
    ):
        if status not in VALID_STATUSES:
            raise ReplayInputError(f"Unsupported ReplayResult status: {status}.")
        return ReplayResult(
            execution_run_id=run_id,
            symbol=request.symbol,
            dataset_version=request.dataset_version,
            strategy_version=request.strategy_version,
            execution_configuration_version=request.execution_configuration_version,
            requested_start_date=request.requested_start_date,
            requested_end_date=request.requested_end_date,
            actual_start_date=actual_start,
            actual_end_date=actual_end,
            events=tuple(events),
            final_position=position,
            status=status,
            warnings=tuple(warnings),
            limitations=tuple(limitations),
        )

    def _validate_request(self, request):
        if not isinstance(request, ReplayRequest):
            raise ReplayInputError("request must be a ReplayRequest.")
        for field in (
            "symbol", "dataset_version", "strategy_version",
            "execution_configuration_version", "corporate_action_version",
        ):
            if not isinstance(getattr(request, field), str) or not getattr(request, field):
                raise ReplayInputError(f"{field} must be a non-empty string.")
        start = _date(request.requested_start_date, "requested_start_date")
        end = _date(request.requested_end_date, "requested_end_date")
        if start > end:
            raise ReplayInputError("requested_start_date must be <= requested_end_date.")
        if not isinstance(request.execution_configuration_snapshot, dict):
            raise ReplayInputError("execution_configuration_snapshot must be a dict.")

    def _validate_shared_request(self, request):
        if not isinstance(request, SharedPortfolioReplayRequest):
            raise ReplayInputError("request must be a SharedPortfolioReplayRequest.")
        for field in (
            "dataset_version",
            "strategy_version",
            "execution_configuration_version",
            "corporate_action_version",
            "portfolio_id",
        ):
            if not isinstance(getattr(request, field), str) or not getattr(request, field):
                raise ReplayInputError(f"{field} must be a non-empty string.")
        start = _date(request.requested_start_date, "requested_start_date")
        end = _date(request.requested_end_date, "requested_end_date")
        if start > end:
            raise ReplayInputError("requested_start_date must be <= requested_end_date.")
        if not isinstance(request.execution_configuration_snapshot, dict):
            raise ReplayInputError("execution_configuration_snapshot must be a dict.")
        if not _finite_positive(request.initial_shared_cash):
            raise ReplayInputError("initial_shared_cash must be a finite positive number.")


def _load_dataset(dataset_version, dataset_root):
    dataset_root = Path(dataset_root)
    try:
        publisher = DatasetPublisher(dataset_root.parents[1])
        if publisher.published_root.resolve() != dataset_root.resolve():
            raise ReplayInputError("Dataset root is not a canonical published-data root.")
        verified = publisher.verify_published(dataset_version)
        latest = publisher.read_latest_index()
        if latest is None:
            raise ReplayInputError("Published-data root has no registration index.")
        dataset = load_versioned_dataset(dataset_version, dataset_root)
        publication = read_publication_evidence(
            publisher,
            dataset_version,
            dataset_path=dataset["dataset_path"],
        )
        state = publication.get("state", publication.get("publication_state"))
        if state != PublicationState.PUBLISHED.value:
            raise ReplayInputError("Dataset publication state is not PUBLISHED.")
        if publication.get("dataset_version") != dataset_version:
            raise ReplayInputError("Publication evidence references another dataset version.")
        if publication.get("content_checksum") != verified["checksum"]:
            raise ReplayInputError("Publication evidence checksum does not match dataset content.")
        if publication.get("provider_id") != dataset["manifest"].source:
            raise ReplayInputError("Publication evidence provider does not match dataset source.")
    except Exception as error:
        raise FileNotFoundError(
            "Published dataset is unavailable, unregistered, or invalid: "
            f"{dataset_version}."
        ) from error
    return {**dataset, "limitations": tuple(dataset["quality"].get("limitations", ())) }


def _market_bars(bars, request, symbol=None):
    required = {"code", "date", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(bars.columns))
    if missing:
        raise ReplayInputError("Dataset bars missing fields: " + ", ".join(missing))
    symbol = request.symbol if symbol is None else symbol
    filtered = bars[bars["code"].astype(str) == symbol].copy()
    filtered["date"] = pd.to_datetime(filtered["date"], errors="raise").dt.date.astype(str)
    filtered = filtered[
        (filtered["date"] >= request.requested_start_date)
        & (filtered["date"] <= request.requested_end_date)
    ].sort_values("date", kind="stable").reset_index(drop=True)
    if filtered["date"].duplicated().any():
        raise ReplayInputError("Dataset contains duplicate market dates for symbol.")
    for field in ("open", "high", "low", "close", "volume"):
        if not pd.to_numeric(filtered[field], errors="coerce").map(_finite_positive).all():
            raise ReplayInputError(f"Dataset contains invalid {field} values.")
    if (filtered["low"] > filtered["high"]).any():
        raise ReplayInputError("Dataset contains low > high.")
    return filtered


def _actions_for_day(actions, symbol, current_date):
    if actions.empty:
        return ()
    date_field = "effective_date" if "effective_date" in actions.columns else "event_date"
    selected = actions[(actions["code"].astype(str) == symbol)].copy()
    selected[date_field] = pd.to_datetime(selected[date_field]).dt.date.astype(str)
    selected = selected[selected[date_field] == current_date].sort_values(date_field, kind="stable")
    return tuple(MappingProxyType(record) for record in selected.to_dict("records"))


def _context(
    request,
    run_id,
    next_sequence,
    row,
    actions,
    position,
    execution_date=None,
    shared_available_cash=None,
):
    snapshot = None if row is None else MappingProxyType({
        field: float(row[field]) for field in ("open", "high", "low", "close")
    })
    configuration = dict(request.execution_configuration_snapshot)
    if shared_available_cash is not None:
        configuration["shared_available_cash"] = shared_available_cash
    return MappingProxyType({
        "execution_date": execution_date or row["date"],
        "market_data_snapshot": snapshot,
        "corporate_action_snapshot": actions,
        "current_position_projection": _position_mapping(position),
        "execution_configuration_version": request.execution_configuration_version,
        "execution_configuration_snapshot": MappingProxyType(configuration),
        "next_event_sequence_number": next_sequence,
        "execution_run_id": run_id,
        "strategy_version": request.strategy_version,
        "dataset_version": request.dataset_version,
    })


def _position_mapping(position):
    return None if position is None else MappingProxyType(position.__dict__.copy())


def _project(events):
    try:
        return project_position(events)
    except PositionProjectionError as error:
        raise ReplayInputError("ExecutionEvent stream cannot form Position projection.") from error


def _validate_initial_events(events, request, run_id):
    if events:
        raise ReplayInputError("Non-empty initial_events are not supported by the V1 Replay contract.")


def _validate_tick_events(events, next_sequence, request, run_id):
    for offset, event in enumerate(events):
        if event["sequence_number"] != next_sequence + offset:
            raise ReplayInputError("Execution returned non-continuous Event sequence.")
        if event["execution_run_id"] != run_id:
            raise ReplayInputError("Execution returned an Event for another execution run.")
        if (
            event["strategy_version"] != request.strategy_version
            or event["dataset_version"] != request.dataset_version
            or event["execution_config_version"] != request.execution_configuration_version
        ):
            raise ReplayInputError("Execution returned Event metadata that differs from Replay input.")


def _execution_run_id(request):
    payload = {
        "replay_schema_version": REPLAY_SCHEMA_VERSION,
        "dataset_version": request.dataset_version,
        "symbol": request.symbol,
        "strategy_version": request.strategy_version,
        "execution_configuration_version": request.execution_configuration_version,
        "execution_configuration_snapshot": request.execution_configuration_snapshot,
        "corporate_action_version": request.corporate_action_version,
        "requested_start_date": request.requested_start_date,
        "requested_end_date": request.requested_end_date,
        "initial_events": "EMPTY",
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "execution-run-v1-" + sha256(encoded.encode("utf-8")).hexdigest()


def _shared_execution_run_id(request):
    payload = {
        "replay_schema_version": REPLAY_SCHEMA_VERSION,
        "dataset_version": request.dataset_version,
        "symbols": request.symbols,
        "strategy_version": request.strategy_version,
        "execution_configuration_version": request.execution_configuration_version,
        "execution_configuration_snapshot": request.execution_configuration_snapshot,
        "corporate_action_version": request.corporate_action_version,
        "requested_start_date": request.requested_start_date,
        "requested_end_date": request.requested_end_date,
        "initial_shared_cash": request.initial_shared_cash,
        "portfolio_id": request.portfolio_id,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "shared-execution-run-v1-" + sha256(encoded.encode("utf-8")).hexdigest()


def _intent_action(intent):
    if isinstance(intent, MappingProxyType):
        return intent.get("requested_action")
    if isinstance(intent, dict):
        return intent.get("requested_action")
    return getattr(intent, "requested_action", None)


def _shared_open_positions(events, symbols):
    positions = {}
    for symbol in symbols:
        symbol_events = [event for event in events if event["symbol"] == symbol]
        if not symbol_events:
            continue
        rebased = tuple(
            MappingProxyType({**dict(event), "sequence_number": index})
            for index, event in enumerate(symbol_events, start=1)
        )
        position = _project(rebased)
        if _is_open(position):
            positions[symbol] = position
    return positions


def _update_shared_position_cache(active_positions, position_event_streams, tick_events):
    """Update per-symbol projections only for Symbols whose event stream changed."""

    changed_symbols = set()
    for event in tick_events:
        symbol = event["symbol"]
        position_event_streams[symbol].append(event)
        changed_symbols.add(symbol)
    for symbol in changed_symbols:
        rebased = tuple(
            MappingProxyType({**dict(event), "sequence_number": index})
            for index, event in enumerate(position_event_streams[symbol], start=1)
        )
        position = _project(rebased)
        if _is_open(position):
            active_positions[symbol] = position
        else:
            active_positions.pop(symbol, None)


def _shared_initial_portfolio(request):
    return Portfolio.create_empty(
        metadata=Metadata(
            portfolio_id=request.portfolio_id,
            portfolio_name="Shared Portfolio Replay",
            strategy_id=request.strategy_version,
        ),
        cash=Cash(request.initial_shared_cash),
    )


def _shared_portfolio_context(request):
    return ExecutionContext(
        execution_date=request.requested_start_date,
        market_data_snapshot=None,
        corporate_action_snapshot=(),
        current_position_projection=None,
        execution_configuration_version=request.execution_configuration_version,
        execution_configuration_snapshot=dict(request.execution_configuration_snapshot),
        strategy_version=request.strategy_version,
        dataset_version=request.dataset_version,
        cache_manifest_id=None,
        timeline_position=0,
        runtime_mode="SIMULATION",
        universe_id="shared-universe-v1-" + sha256(
            "|".join(request.symbols).encode("utf-8")
        ).hexdigest(),
        universe=request.symbols,
        replay_version=REPLAY_SCHEMA_VERSION,
        portfolio_id=request.portfolio_id,
        calendar_identity="jpx-calendar-v1",
        execution_workflow_version="execution-workflow-spec-v1",
    )


def _shared_portfolio_result(request, events):
    return PortfolioEngine().apply(
        _shared_portfolio_context(request),
        portfolio_to_representation(_shared_initial_portfolio(request)),
        tuple(events),
    )


def _daily_snapshot(trading_date, portfolio, rows):
    holding_market_value = 0.0
    for position in portfolio.positions:
        row = rows.get(position.symbol)
        if row is None or not _finite_positive(row.get("close")):
            raise ReplayInputError(
                "Missing valid close for active Position on shared snapshot date: "
                f"{position.symbol} {trading_date}."
            )
        holding_market_value += float(position.quantity) * float(row["close"])
    total_equity = float(portfolio.cash.amount) + holding_market_value
    return DailyPortfolioSnapshot(
        trading_date=trading_date,
        cash=portfolio.cash.amount,
        holding_market_value=holding_market_value,
        total_equity=total_equity,
        open_position_count=len(portfolio.positions),
    )


def _shared_result_checksum(request, run_id, events, portfolio, snapshots, status):
    payload = {
        "request": {
            "symbols": request.symbols,
            "dataset_version": request.dataset_version,
            "requested_start_date": request.requested_start_date,
            "requested_end_date": request.requested_end_date,
            "strategy_version": request.strategy_version,
            "execution_configuration_version": request.execution_configuration_version,
            "corporate_action_version": request.corporate_action_version,
            "initial_shared_cash": request.initial_shared_cash,
            "portfolio_id": request.portfolio_id,
        },
        "execution_run_id": run_id,
        "events": [_plain_value(event) for event in events],
        "final_portfolio": portfolio_to_representation(portfolio),
        "daily_portfolio_snapshots": [asdict(snapshot) for snapshot in snapshots],
        "status": status,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(encoded.encode("utf-8")).hexdigest()


def _plain_value(value):
    if isinstance(value, MappingProxyType):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    return value


def _date(value, field):
    if not isinstance(value, str):
        raise ReplayInputError(f"{field} must use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ReplayInputError(f"{field} must use YYYY-MM-DD.") from error


def _finite_positive(value):
    try:
        return isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def _is_open(position):
    return position is not None and position.position_status == "OPEN"
