"""Immutable Portfolio transaction evidence defined by ADR-007."""

from dataclasses import dataclass
from datetime import date

from .invariants import normalize_required_text, require_number


PORTFOLIO_TRANSACTION_SCHEMA_VERSION = "portfolio-transaction-v1"
BUY_TRANSACTION = "BUY"
CLOSE_TRANSACTION = "CLOSE"
SUPPORTED_TRANSACTION_TYPES = (BUY_TRANSACTION, CLOSE_TRANSACTION)


@dataclass(frozen=True, slots=True)
class PortfolioTransaction:
    """Evidence for one completed Portfolio state transition."""

    transaction_id: str
    transaction_type: str
    portfolio_id: str
    source_event_id: str
    execution_run_id: str
    position_id: str
    symbol: str
    transaction_date: str
    quantity: int | float
    price: int | float
    gross_amount: int | float
    cash_delta: int | float
    cash_balance_after: int | float
    close_reason: str | None = None
    schema_version: str = PORTFOLIO_TRANSACTION_SCHEMA_VERSION

    def __post_init__(self):
        if self.schema_version != PORTFOLIO_TRANSACTION_SCHEMA_VERSION:
            raise ValueError("Unsupported Portfolio Transaction schema_version.")
        for field in (
            "transaction_id",
            "portfolio_id",
            "source_event_id",
            "execution_run_id",
            "position_id",
            "symbol",
        ):
            object.__setattr__(
                self,
                field,
                normalize_required_text(getattr(self, field), field),
            )
        if not self.transaction_id.startswith("portfolio-transaction-v1-"):
            raise ValueError("transaction_id must use the V1 stable identity format.")
        if self.transaction_type not in SUPPORTED_TRANSACTION_TYPES:
            raise ValueError("Unsupported Portfolio Transaction type.")
        try:
            date.fromisoformat(self.transaction_date)
        except (TypeError, ValueError) as error:
            raise ValueError("transaction_date must use YYYY-MM-DD.") from error

        require_number(self.quantity, "quantity", greater_than=0)
        require_number(self.price, "price", greater_than=0)
        require_number(self.gross_amount, "gross_amount", greater_than=0)
        require_number(self.cash_delta, "cash_delta")
        require_number(self.cash_balance_after, "cash_balance_after", minimum=0)
        if self.gross_amount != self.quantity * self.price:
            raise ValueError("gross_amount must equal quantity multiplied by price.")
        expected_cash_delta = (
            -self.gross_amount
            if self.transaction_type == BUY_TRANSACTION
            else self.gross_amount
        )
        if self.cash_delta != expected_cash_delta:
            raise ValueError(
                "cash_delta does not match the Portfolio Transaction direction."
            )
        if self.transaction_type == CLOSE_TRANSACTION:
            object.__setattr__(
                self,
                "close_reason",
                normalize_required_text(self.close_reason, "close_reason"),
            )
        elif self.close_reason is not None:
            raise ValueError("BUY Portfolio Transaction must not carry close_reason.")


__all__ = [
    "PORTFOLIO_TRANSACTION_SCHEMA_VERSION",
    "BUY_TRANSACTION",
    "CLOSE_TRANSACTION",
    "SUPPORTED_TRANSACTION_TYPES",
    "PortfolioTransaction",
]
