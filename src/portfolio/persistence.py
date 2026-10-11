"""Canonical Portfolio persistence representation and deterministic JSON codec."""

from collections.abc import Mapping
import json

from .aggregate import (
    PORTFOLIO_SCHEMA_VERSION,
    Cash,
    Metadata,
    Portfolio,
    Position,
    Statistics,
)


class PortfolioPersistenceError(ValueError):
    """Base error for unsupported or malformed Portfolio persistence state."""


class PortfolioSchemaVersionError(PortfolioPersistenceError):
    """Raised when a Portfolio schema version is not supported."""


class PortfolioRepresentationError(PortfolioPersistenceError):
    """Raised when a Portfolio representation is structurally invalid."""


def portfolio_to_representation(portfolio):
    """Return the canonical JSON-compatible representation of a Portfolio."""

    if type(portfolio) is not Portfolio:
        raise TypeError("portfolio must be a Portfolio aggregate.")

    return {
        "schema_version": portfolio.metadata.schema_version,
        "metadata": {
            "portfolio_id": portfolio.metadata.portfolio_id,
            "portfolio_name": portfolio.metadata.portfolio_name,
            "strategy_id": portfolio.metadata.strategy_id,
        },
        "cash": {
            "amount": _canonical_number(portfolio.cash.amount),
        },
        "positions": [
            {
                "symbol": position.symbol,
                "quantity": _canonical_number(position.quantity),
                "average_cost": _canonical_number(position.average_cost),
            }
            for position in portfolio.positions
        ],
        "statistics": {},
    }


def portfolio_from_representation(representation):
    """Reconstruct a Portfolio from the exact canonical V1 representation."""

    root = _require_mapping(representation, "portfolio")
    _require_fields(
        root,
        {"schema_version", "metadata", "cash", "positions", "statistics"},
        "portfolio",
    )

    schema_version = root["schema_version"]
    if schema_version != PORTFOLIO_SCHEMA_VERSION:
        raise PortfolioSchemaVersionError("Unsupported Portfolio schema_version.")

    metadata_state = _require_mapping(root["metadata"], "metadata")
    _require_fields(
        metadata_state,
        {"portfolio_id", "portfolio_name", "strategy_id"},
        "metadata",
    )
    cash_state = _require_mapping(root["cash"], "cash")
    _require_fields(cash_state, {"amount"}, "cash")
    statistics_state = _require_mapping(root["statistics"], "statistics")
    _require_fields(statistics_state, set(), "statistics")

    position_states = root["positions"]
    if not isinstance(position_states, list):
        raise PortfolioRepresentationError("positions must be a JSON array.")

    try:
        positions = []
        for index, state in enumerate(position_states):
            path = f"positions[{index}]"
            position_state = _require_mapping(state, path)
            _require_fields(
                position_state,
                {"symbol", "quantity", "average_cost"},
                path,
            )
            positions.append(
                Position(
                    symbol=position_state["symbol"],
                    quantity=position_state["quantity"],
                    average_cost=position_state["average_cost"],
                )
            )

        symbols = tuple(position.symbol for position in positions)
        if symbols != tuple(sorted(symbols)):
            raise PortfolioRepresentationError(
                "positions must use canonical Symbol order."
            )

        return Portfolio(
            metadata=Metadata(
                portfolio_id=metadata_state["portfolio_id"],
                portfolio_name=metadata_state["portfolio_name"],
                strategy_id=metadata_state["strategy_id"],
                schema_version=schema_version,
            ),
            cash=Cash(cash_state["amount"]),
            positions=tuple(positions),
            statistics=Statistics(),
        )
    except PortfolioPersistenceError:
        raise
    except (TypeError, ValueError) as error:
        raise PortfolioRepresentationError(
            "Portfolio representation contains invalid aggregate state."
        ) from error


def serialize_portfolio(portfolio):
    """Serialize a Portfolio to canonical compact JSON text."""

    return json.dumps(
        portfolio_to_representation(portfolio),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def deserialize_portfolio(payload):
    """Deserialize canonical UTF-8 JSON text or bytes into a Portfolio."""

    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PortfolioRepresentationError(
                "Portfolio payload must be valid UTF-8."
            ) from error
    if not isinstance(payload, str):
        raise TypeError("payload must be JSON text or UTF-8 bytes.")

    try:
        representation = json.loads(
            payload,
            object_pairs_hook=_object_without_duplicate_fields,
        )
    except PortfolioPersistenceError:
        raise
    except json.JSONDecodeError as error:
        raise PortfolioRepresentationError(
            "Portfolio payload is invalid JSON."
        ) from error
    return portfolio_from_representation(representation)


def _require_mapping(value, path):
    if not isinstance(value, Mapping):
        raise PortfolioRepresentationError(f"{path} must be an object.")
    if any(not isinstance(key, str) for key in value):
        raise PortfolioRepresentationError(f"{path} field names must be strings.")
    return value


def _require_fields(value, expected, path):
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if not missing and not unknown:
        return

    details = []
    if missing:
        details.append("missing: " + ", ".join(missing))
    if unknown:
        details.append("unknown: " + ", ".join(unknown))
    raise PortfolioRepresentationError(
        f"Invalid {path} fields ({'; '.join(details)})."
    )


def _object_without_duplicate_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PortfolioRepresentationError(
                "Portfolio JSON must not contain duplicate fields."
            )
        result[key] = value
    return result


def _canonical_number(value):
    if isinstance(value, float) and (value == 0 or value.is_integer()):
        return int(value)
    return value


__all__ = [
    "PortfolioPersistenceError",
    "PortfolioRepresentationError",
    "PortfolioSchemaVersionError",
    "deserialize_portfolio",
    "portfolio_from_representation",
    "portfolio_to_representation",
    "serialize_portfolio",
]
