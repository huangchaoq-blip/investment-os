from dataclasses import dataclass

from .state import PositionStatus


@dataclass(frozen=True)
class PositionState:
    """Minimal lifecycle state, not a Position View or Ledger projection."""

    status: PositionStatus = PositionStatus.NONE
