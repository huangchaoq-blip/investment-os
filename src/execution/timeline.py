"""Session-based deterministic TradingTimeline."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256

from .runtime_values import canonical_json, require_nonnegative_integer, require_text


TRADING_TIMELINE_SCHEMA_VERSION = "trading-timeline-v1"


@dataclass(frozen=True)
class TradingTimeline:
    timeline_id: str
    calendar_identity: str
    sessions: tuple[str, ...]
    position: int = 0
    schema_version: str = TRADING_TIMELINE_SCHEMA_VERSION

    def __post_init__(self):
        if self.schema_version != TRADING_TIMELINE_SCHEMA_VERSION:
            raise ValueError("Unsupported TradingTimeline schema_version.")
        require_text(self.calendar_identity, "calendar_identity")
        sessions = tuple(self.sessions)
        if not sessions:
            raise ValueError("TradingTimeline requires at least one session.")
        for session in sessions:
            _require_date(session)
        if tuple(sorted(sessions)) != sessions or len(set(sessions)) != len(sessions):
            raise ValueError("TradingTimeline sessions must be unique and increasing.")
        require_nonnegative_integer(self.position, "position")
        if self.position > len(sessions):
            raise ValueError("TradingTimeline position exceeds its session count.")
        expected_id = _timeline_id(self.calendar_identity, sessions)
        if self.timeline_id != expected_id:
            raise ValueError("TradingTimeline identity does not match its content.")
        object.__setattr__(self, "sessions", sessions)

    @classmethod
    def create(cls, sessions, calendar_identity, position=0):
        normalized = tuple(str(session) for session in sessions)
        return cls(
            timeline_id=_timeline_id(calendar_identity, normalized),
            calendar_identity=calendar_identity,
            sessions=normalized,
            position=position,
        )

    @property
    def completed(self):
        return self.position == len(self.sessions)

    @property
    def current_session(self):
        return None if self.completed else self.sessions[self.position]

    @property
    def previous_session(self):
        if self.position == 0:
            return None
        return self.sessions[self.position - 1]

    @property
    def next_session(self):
        next_position = self.position + 1
        if self.completed or next_position >= len(self.sessions):
            return None
        return self.sessions[next_position]

    def at_position(self, position):
        return replace(self, position=position)

    def advance(self):
        if self.completed:
            return self
        return replace(self, position=self.position + 1)

    def to_dict(self):
        return {
            "schema_version": self.schema_version,
            "timeline_id": self.timeline_id,
            "calendar_identity": self.calendar_identity,
            "sessions": list(self.sessions),
            "position": self.position,
        }

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, Mapping):
            raise TypeError("TradingTimeline payload must be a mapping.")
        fields = {
            "schema_version",
            "timeline_id",
            "calendar_identity",
            "sessions",
            "position",
        }
        if set(payload) != fields:
            raise ValueError("Invalid TradingTimeline fields.")
        return cls(
            schema_version=payload.get("schema_version"),
            timeline_id=payload.get("timeline_id"),
            calendar_identity=payload.get("calendar_identity"),
            sessions=tuple(payload.get("sessions", ())),
            position=payload.get("position"),
        )


def _timeline_id(calendar_identity, sessions):
    payload = {
        "schema_version": TRADING_TIMELINE_SCHEMA_VERSION,
        "calendar_identity": calendar_identity,
        "sessions": list(sessions),
    }
    digest = sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return "timeline-v1-" + digest


def _require_date(value):
    if not isinstance(value, str):
        raise ValueError("TradingTimeline sessions must use YYYY-MM-DD.")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("TradingTimeline sessions must use YYYY-MM-DD.") from error
