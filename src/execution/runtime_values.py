"""Canonical immutable values used by the execution runtime."""

from collections.abc import Mapping
import json
from math import isfinite
from types import MappingProxyType


def freeze_value(value):
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Runtime mapping keys must be strings.")
        frozen = {}
        for key in sorted(value):
            frozen[key] = freeze_value(value[key])
        return MappingProxyType(frozen)
    if isinstance(value, (tuple, list)):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("Runtime numeric values must be finite.")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(
        f"Runtime values must be JSON-compatible, not {type(value).__name__}."
    )


def thaw_value(value):
    if isinstance(value, Mapping):
        return {str(key): thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_value(item) for item in value]
    return value


def canonical_json(value):
    return json.dumps(
        thaw_value(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def require_text(value, field, *, optional=False):
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")


def require_nonnegative_integer(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer.")
