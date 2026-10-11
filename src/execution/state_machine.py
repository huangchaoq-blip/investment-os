from collections.abc import Mapping

from .exceptions import InvalidPositionTransitionError
from .position_state import PositionState
from .state import PositionStatus


# These RFC-002 lifecycle marker Events map to the WO-041 minimal state slice.
EVENT_TRANSITIONS = {
    "INTENT_RECEIVED": (PositionStatus.NONE, PositionStatus.PENDING),
    "ENTRY_FILLED": (PositionStatus.PENDING, PositionStatus.OPEN),
    "POSITION_CLOSED": (PositionStatus.OPEN, PositionStatus.CLOSED),
}


class PositionStateMachine:
    """Applies ordered ExecutionEvent lifecycle markers deterministically."""

    def __init__(self, initial_state=None):
        self._state = initial_state or PositionState()

    @property
    def current_state(self):
        return self._state

    def apply(self, events):
        for event in events:
            self.apply_event(event)
        return self.current_state

    def apply_event(self, event):
        if not isinstance(event, Mapping):
            raise InvalidPositionTransitionError("ExecutionEvent must be a mapping.")
        event_type = event.get("event_type")
        if event_type not in EVENT_TRANSITIONS:
            raise InvalidPositionTransitionError(
                f"ExecutionEvent {event_type!r} is not a lifecycle transition marker."
            )

        expected, target = EVENT_TRANSITIONS[event_type]
        if self._state.status is not expected:
            raise InvalidPositionTransitionError(
                f"Illegal transition {self._state.status.value} -> {target.value} "
                f"for {event_type}; expected {expected.value}."
            )
        self._state = PositionState(status=target)
        return self.current_state
