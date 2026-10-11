"""Shared structural invariants for Portfolio construction and validation."""

from math import isfinite


NUMBER_TYPE_INVALID = "NUMBER_TYPE_INVALID"
NUMBER_NONFINITE = "NUMBER_NONFINITE"
NUMBER_BELOW_MINIMUM = "NUMBER_BELOW_MINIMUM"
NUMBER_NOT_GREATER_THAN = "NUMBER_NOT_GREATER_THAN"


def normalize_required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()


def is_canonical_required_text(value):
    return isinstance(value, str) and bool(value) and value == value.strip()


def numeric_violation(value, *, minimum=None, greater_than=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return NUMBER_TYPE_INVALID
    if isinstance(value, float) and not isfinite(value):
        return NUMBER_NONFINITE
    if minimum is not None and value < minimum:
        return NUMBER_BELOW_MINIMUM
    if greater_than is not None and value <= greater_than:
        return NUMBER_NOT_GREATER_THAN
    return None


def require_number(value, field, *, minimum=None, greater_than=None):
    violation = numeric_violation(
        value,
        minimum=minimum,
        greater_than=greater_than,
    )
    if violation == NUMBER_TYPE_INVALID:
        raise TypeError(f"{field} must be a finite numeric value.")
    if violation == NUMBER_NONFINITE:
        raise ValueError(f"{field} must be finite.")
    if violation == NUMBER_BELOW_MINIMUM:
        raise ValueError(f"{field} must be at least {minimum}.")
    if violation == NUMBER_NOT_GREATER_THAN:
        raise ValueError(f"{field} must be greater than {greater_than}.")
