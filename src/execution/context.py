"""The single immutable runtime Context defined by ADR-003 and DEC-008."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import ClassVar

from .runtime_values import (
    freeze_value,
    require_nonnegative_integer,
    require_text,
    thaw_value,
)


EXECUTION_CONTEXT_SCHEMA_VERSION = "execution-context-v1"
EXECUTION_METADATA_SCHEMA_VERSION = "execution-metadata-v1"


@dataclass(frozen=True)
class ExecutionContext(Mapping):
    execution_date: str | None
    market_data_snapshot: Mapping | None
    corporate_action_snapshot: tuple
    current_position_projection: Mapping | None
    execution_configuration_version: str
    execution_configuration_snapshot: Mapping
    strategy_version: str
    dataset_version: str | None
    cache_manifest_id: str | None
    timeline_position: int
    runtime_mode: str
    universe_id: str
    universe: tuple[str, ...]
    replay_version: str
    portfolio_id: str
    calendar_identity: str
    execution_workflow_version: str
    schema_version: str = EXECUTION_CONTEXT_SCHEMA_VERSION

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "execution_date",
        "market_data_snapshot",
        "corporate_action_snapshot",
        "current_position_projection",
        "execution_configuration_version",
        "execution_configuration_snapshot",
        "strategy_version",
        "dataset_version",
        "cache_manifest_id",
        "timeline_position",
        "runtime_mode",
        "universe_id",
        "universe",
        "replay_version",
        "portfolio_id",
        "calendar_identity",
        "execution_workflow_version",
    )

    def __post_init__(self):
        if self.schema_version != EXECUTION_CONTEXT_SCHEMA_VERSION:
            raise ValueError("Unsupported ExecutionContext schema_version.")
        if self.execution_date is not None:
            _require_date(self.execution_date, "execution_date")
        require_nonnegative_integer(self.timeline_position, "timeline_position")
        for field in (
            "execution_configuration_version",
            "strategy_version",
            "runtime_mode",
            "universe_id",
            "replay_version",
            "portfolio_id",
            "calendar_identity",
            "execution_workflow_version",
        ):
            require_text(getattr(self, field), field)
        require_text(self.dataset_version, "dataset_version", optional=True)
        require_text(self.cache_manifest_id, "cache_manifest_id", optional=True)
        if self.dataset_version is None and self.cache_manifest_id is None:
            raise ValueError(
                "ExecutionContext requires dataset_version or cache_manifest_id."
            )

        if isinstance(self.universe, (str, bytes)):
            raise TypeError("universe must be a sequence of symbols.")
        universe = tuple(str(symbol).strip() for symbol in self.universe)
        if not universe or any(not symbol for symbol in universe):
            raise ValueError("universe must contain non-empty symbols.")
        if len(set(universe)) != len(universe):
            raise ValueError("universe must not contain duplicate symbols.")
        object.__setattr__(self, "universe", universe)
        market_data = freeze_value(self.market_data_snapshot)
        if market_data is not None and not isinstance(market_data, Mapping):
            raise TypeError("market_data_snapshot must be a mapping or None.")
        object.__setattr__(self, "market_data_snapshot", market_data)
        if not isinstance(self.corporate_action_snapshot, (tuple, list)):
            raise TypeError("corporate_action_snapshot must be a sequence.")
        object.__setattr__(
            self,
            "corporate_action_snapshot",
            freeze_value(self.corporate_action_snapshot),
        )
        position = freeze_value(self.current_position_projection)
        if position is not None and not isinstance(position, Mapping):
            raise TypeError("current_position_projection must be a mapping or None.")
        object.__setattr__(self, "current_position_projection", position)
        configuration = freeze_value(self.execution_configuration_snapshot)
        if not isinstance(configuration, Mapping):
            raise TypeError("execution_configuration_snapshot must be a mapping.")
        object.__setattr__(self, "execution_configuration_snapshot", configuration)

    def __getitem__(self, key):
        if key not in self._FIELDS:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._FIELDS)

    def __len__(self):
        return len(self._FIELDS)

    def to_dict(self):
        return {field: thaw_value(getattr(self, field)) for field in self._FIELDS}

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, Mapping):
            raise TypeError("ExecutionContext payload must be a mapping.")
        missing = [field for field in cls._FIELDS if field not in payload]
        unknown = sorted(set(payload) - set(cls._FIELDS))
        if missing or unknown:
            detail = []
            if missing:
                detail.append("missing: " + ", ".join(missing))
            if unknown:
                detail.append("unknown: " + ", ".join(unknown))
            raise ValueError("Invalid ExecutionContext fields (" + "; ".join(detail) + ").")
        return cls(**{field: payload[field] for field in cls._FIELDS})

    def at_timeline_position(self, position, execution_date):
        return replace(
            self,
            timeline_position=position,
            execution_date=execution_date,
        )


@dataclass(frozen=True)
class ExecutionMetadata:
    execution_run_id: str
    event_cursor: int = 0
    trace_id: str | None = None
    schema_version: str = EXECUTION_METADATA_SCHEMA_VERSION

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "execution_run_id",
        "event_cursor",
        "trace_id",
    )

    def __post_init__(self):
        if self.schema_version != EXECUTION_METADATA_SCHEMA_VERSION:
            raise ValueError("Unsupported ExecutionMetadata schema_version.")
        require_text(self.execution_run_id, "execution_run_id")
        require_text(self.trace_id, "trace_id", optional=True)
        require_nonnegative_integer(self.event_cursor, "event_cursor")

    @property
    def next_event_sequence_number(self):
        return self.event_cursor + 1

    def advance_event_cursor(self, event_count):
        require_nonnegative_integer(event_count, "event_count")
        return replace(self, event_cursor=self.event_cursor + event_count)

    def to_dict(self):
        return {
            "schema_version": self.schema_version,
            "execution_run_id": self.execution_run_id,
            "event_cursor": self.event_cursor,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, Mapping):
            raise TypeError("ExecutionMetadata payload must be a mapping.")
        missing = [field for field in cls._FIELDS if field not in payload]
        unknown = sorted(set(payload) - set(cls._FIELDS))
        if missing or unknown:
            raise ValueError("Invalid ExecutionMetadata fields.")
        return cls(
            schema_version=payload.get("schema_version"),
            execution_run_id=payload.get("execution_run_id"),
            event_cursor=payload.get("event_cursor"),
            trace_id=payload.get("trace_id"),
        )


def _require_date(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must use YYYY-MM-DD.")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must use YYYY-MM-DD.") from error
