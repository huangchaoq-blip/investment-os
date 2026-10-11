"""Deterministic diagnostics for the passive Portfolio aggregate."""

from dataclasses import dataclass

from .aggregate import (
    PORTFOLIO_SCHEMA_VERSION,
    Cash,
    Metadata,
    Portfolio,
    Position,
    Statistics,
)
from .invariants import (
    NUMBER_BELOW_MINIMUM,
    NUMBER_NONFINITE,
    NUMBER_NOT_GREATER_THAN,
    NUMBER_TYPE_INVALID,
    is_canonical_required_text,
    numeric_violation,
)


@dataclass(frozen=True, slots=True)
class PortfolioValidationIssue:
    code: str
    path: str
    description: str

    def __post_init__(self):
        for field in ("code", "path", "description"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-empty string.")


@dataclass(frozen=True, slots=True)
class PortfolioValidationResult:
    issues: tuple[PortfolioValidationIssue, ...] = ()

    def __post_init__(self):
        issues = tuple(self.issues)
        if any(not isinstance(issue, PortfolioValidationIssue) for issue in issues):
            raise TypeError("issues must contain PortfolioValidationIssue values.")
        object.__setattr__(
            self,
            "issues",
            tuple(
                sorted(
                    issues,
                    key=lambda issue: (issue.path, issue.code, issue.description),
                )
            ),
        )

    @property
    def valid(self):
        return not self.issues


def validate_portfolio(value):
    """Return complete deterministic structural diagnostics for current state."""

    issues = []
    if type(value) is not Portfolio:
        issues.append(
            _issue(
                "PORTFOLIO_TYPE_INVALID",
                "portfolio",
                "Value must be a Portfolio aggregate.",
            )
        )
        return PortfolioValidationResult(tuple(issues))

    _validate_metadata(getattr(value, "metadata", None), issues)
    _validate_cash(getattr(value, "cash", None), issues)
    _validate_positions(getattr(value, "positions", None), issues)
    _validate_statistics(getattr(value, "statistics", None), issues)
    return PortfolioValidationResult(tuple(issues))


def _validate_metadata(metadata, issues):
    if type(metadata) is not Metadata:
        issues.append(
            _issue(
                "METADATA_TYPE_INVALID",
                "metadata",
                "Portfolio metadata must be Metadata.",
            )
        )
        return

    fields = (
        (
            "portfolio_id",
            "METADATA_PORTFOLIO_ID_INVALID",
            "Portfolio ID must be a canonical non-empty string.",
        ),
        (
            "portfolio_name",
            "METADATA_PORTFOLIO_NAME_INVALID",
            "Portfolio Name must be a canonical non-empty string.",
        ),
        (
            "strategy_id",
            "METADATA_STRATEGY_ID_INVALID",
            "Strategy ID must be a canonical non-empty string.",
        ),
    )
    for field, code, description in fields:
        if not is_canonical_required_text(getattr(metadata, field, None)):
            issues.append(_issue(code, f"metadata.{field}", description))

    if getattr(metadata, "schema_version", None) != PORTFOLIO_SCHEMA_VERSION:
        issues.append(
            _issue(
                "METADATA_SCHEMA_VERSION_UNSUPPORTED",
                "metadata.schema_version",
                "Portfolio schema version is unsupported.",
            )
        )


def _validate_cash(cash, issues):
    if type(cash) is not Cash:
        issues.append(
            _issue(
                "CASH_TYPE_INVALID",
                "cash",
                "Portfolio cash must be Cash without unsupported state.",
            )
        )
        return

    violation = numeric_violation(getattr(cash, "amount", None), minimum=0)
    code_and_description = {
        NUMBER_TYPE_INVALID: (
            "CASH_AMOUNT_TYPE_INVALID",
            "Cash amount must be numeric.",
        ),
        NUMBER_NONFINITE: (
            "CASH_AMOUNT_NONFINITE",
            "Cash amount must be finite.",
        ),
        NUMBER_BELOW_MINIMUM: (
            "CASH_AMOUNT_NEGATIVE",
            "Cash amount must be non-negative.",
        ),
    }.get(violation)
    if code_and_description is not None:
        code, description = code_and_description
        issues.append(_issue(code, "cash.amount", description))


def _validate_positions(positions, issues):
    if not isinstance(positions, (tuple, list)):
        issues.append(
            _issue(
                "POSITIONS_COLLECTION_TYPE_INVALID",
                "positions",
                "Positions must be an immutable ordered collection.",
            )
        )
        return
    if not isinstance(positions, tuple):
        issues.append(
            _issue(
                "POSITIONS_COLLECTION_TYPE_INVALID",
                "positions",
                "Positions must be an immutable ordered collection.",
            )
        )

    canonical_symbols = []
    for index, position in enumerate(positions):
        path = f"positions[{index}]"
        if type(position) is not Position:
            issues.append(
                _issue(
                    "POSITION_TYPE_INVALID",
                    path,
                    "Position collection must contain only Position values.",
                )
            )
            continue

        symbol = getattr(position, "symbol", None)
        if not is_canonical_required_text(symbol):
            issues.append(
                _issue(
                    "POSITION_SYMBOL_INVALID",
                    f"{path}.symbol",
                    "Position Symbol must be a canonical non-empty string.",
                )
            )
        else:
            canonical_symbols.append(symbol)

        _validate_position_number(
            getattr(position, "quantity", None),
            path=f"{path}.quantity",
            type_code="POSITION_QUANTITY_TYPE_INVALID",
            nonfinite_code="POSITION_QUANTITY_NONFINITE",
            range_code="POSITION_QUANTITY_NONPOSITIVE",
            type_description="Position Quantity must be numeric.",
            nonfinite_description="Position Quantity must be finite.",
            range_description="Position Quantity must be positive.",
            greater_than=0,
            issues=issues,
        )
        _validate_position_number(
            getattr(position, "average_cost", None),
            path=f"{path}.average_cost",
            type_code="POSITION_AVERAGE_COST_TYPE_INVALID",
            nonfinite_code="POSITION_AVERAGE_COST_NONFINITE",
            range_code="POSITION_AVERAGE_COST_NEGATIVE",
            type_description="Position Average Cost must be numeric.",
            nonfinite_description="Position Average Cost must be finite.",
            range_description="Position Average Cost must be non-negative.",
            minimum=0,
            issues=issues,
        )

    if len(canonical_symbols) != len(set(canonical_symbols)):
        issues.append(
            _issue(
                "POSITION_SYMBOL_DUPLICATE",
                "positions",
                "Portfolio must not contain duplicate Position Symbols.",
            )
        )

    if len(canonical_symbols) == len(positions):
        if tuple(canonical_symbols) != tuple(sorted(canonical_symbols)):
            issues.append(
                _issue(
                    "POSITIONS_ORDER_INVALID",
                    "positions",
                    "Position collection must use canonical Symbol order.",
                )
            )


def _validate_position_number(
    value,
    *,
    path,
    type_code,
    nonfinite_code,
    range_code,
    type_description,
    nonfinite_description,
    range_description,
    issues,
    minimum=None,
    greater_than=None,
):
    violation = numeric_violation(
        value,
        minimum=minimum,
        greater_than=greater_than,
    )
    if violation == NUMBER_TYPE_INVALID:
        issues.append(_issue(type_code, path, type_description))
    elif violation == NUMBER_NONFINITE:
        issues.append(_issue(nonfinite_code, path, nonfinite_description))
    elif violation in (NUMBER_BELOW_MINIMUM, NUMBER_NOT_GREATER_THAN):
        issues.append(_issue(range_code, path, range_description))


def _validate_statistics(statistics, issues):
    if type(statistics) is not Statistics:
        issues.append(
            _issue(
                "STATISTICS_TYPE_INVALID",
                "statistics",
                "Statistics must be the supported structural placeholder.",
            )
        )


def _issue(code, path, description):
    return PortfolioValidationIssue(
        code=code,
        path=path,
        description=description,
    )


__all__ = [
    "PortfolioValidationIssue",
    "PortfolioValidationResult",
    "validate_portfolio",
]
