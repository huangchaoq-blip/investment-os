"""Passive Portfolio aggregate defined by ADR-004 and RFC-004-001."""

from dataclasses import dataclass, field

from .invariants import normalize_required_text, require_number


PORTFOLIO_SCHEMA_VERSION = "portfolio-aggregate-v1"


@dataclass(frozen=True, slots=True)
class Cash:
    """Current available capital owned by one Portfolio."""

    amount: int | float = 0

    def __post_init__(self):
        require_number(self.amount, "amount", minimum=0)


@dataclass(frozen=True, slots=True)
class Position:
    """Current holding state for exactly one instrument."""

    symbol: str
    quantity: int | float
    average_cost: int | float

    def __post_init__(self):
        object.__setattr__(
            self,
            "symbol",
            normalize_required_text(self.symbol, "symbol"),
        )
        require_number(self.quantity, "quantity", greater_than=0)
        require_number(self.average_cost, "average_cost", minimum=0)


@dataclass(frozen=True, slots=True)
class Statistics:
    """Empty placeholder for future derived Portfolio statistics."""


@dataclass(frozen=True, slots=True)
class Metadata:
    """Descriptive Portfolio identity without runtime metadata."""

    portfolio_id: str
    portfolio_name: str
    strategy_id: str
    schema_version: str = PORTFOLIO_SCHEMA_VERSION

    def __post_init__(self):
        if self.schema_version != PORTFOLIO_SCHEMA_VERSION:
            raise ValueError("Unsupported Portfolio schema_version.")
        for name in ("portfolio_id", "portfolio_name", "strategy_id"):
            object.__setattr__(
                self,
                name,
                normalize_required_text(getattr(self, name), name),
            )


@dataclass(frozen=True, slots=True)
class Portfolio:
    """Aggregate root containing complete current Portfolio state."""

    metadata: Metadata
    cash: Cash = field(default_factory=Cash)
    positions: tuple[Position, ...] = ()
    statistics: Statistics = field(default_factory=Statistics)

    def __post_init__(self):
        if type(self.metadata) is not Metadata:
            raise TypeError("metadata must be Metadata.")
        if type(self.cash) is not Cash:
            raise TypeError("cash must be Cash.")
        if type(self.statistics) is not Statistics:
            raise TypeError("statistics must be Statistics.")
        if not isinstance(self.positions, (tuple, list)):
            raise TypeError("positions must be a sequence of Position values.")

        positions = tuple(self.positions)
        if any(type(position) is not Position for position in positions):
            raise TypeError("positions must contain only Position values.")

        positions = tuple(sorted(positions, key=lambda position: position.symbol))
        symbols = tuple(position.symbol for position in positions)
        if len(symbols) != len(set(symbols)):
            raise ValueError("Portfolio must not contain duplicate Position symbols.")
        object.__setattr__(self, "positions", positions)

    @classmethod
    def create_empty(cls, *, metadata: Metadata, cash: Cash | None = None):
        """Create a valid Portfolio with no Positions and empty Statistics."""

        return cls(metadata=metadata, cash=Cash() if cash is None else cash)


__all__ = [
    "PORTFOLIO_SCHEMA_VERSION",
    "Cash",
    "Metadata",
    "Portfolio",
    "Position",
    "Statistics",
]
