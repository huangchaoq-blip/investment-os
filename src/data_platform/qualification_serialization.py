"""Canonical RFC-006 JSON serialization and deterministic identity helpers."""

from collections.abc import Mapping
from datetime import date, datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import math
import unicodedata


FINGERPRINT_ALGORITHM = "sha256"


class CanonicalQualificationSerializationError(ValueError):
    """Raised when a value cannot be represented by the RFC-006 codec."""


def canonical_json_bytes(value):
    """Return compact UTF-8 RFC-006 canonical JSON bytes."""

    normalized = canonical_value(value)
    try:
        text = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise CanonicalQualificationSerializationError(
            "Value cannot be serialized as canonical qualification JSON."
        ) from error
    return text.encode("utf-8")


def canonical_json_text(value):
    """Return compact RFC-006 canonical JSON text."""

    return canonical_json_bytes(value).decode("utf-8")


def canonical_sha256_hex(value):
    """Return the lowercase SHA-256 digest for canonical JSON content."""

    return sha256(canonical_json_bytes(value)).hexdigest()


def canonical_fingerprint(value):
    return f"{FINGERPRINT_ALGORITHM}:{canonical_sha256_hex(value)}"


def canonical_identity(prefix, value):
    prefix = _normalized_text(prefix)
    if not prefix:
        raise CanonicalQualificationSerializationError(
            "Identity prefix must not be empty."
        )
    return f"{prefix}:{canonical_sha256_hex(value)}"


def canonical_value(value):
    """Normalize one supported value into an RFC-006 JSON representation."""

    if hasattr(value, "to_representation"):
        value = value.to_representation()
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalQualificationSerializationError(
                "Canonical timestamps must be timezone-aware."
            )
        utc_value = value.astimezone(timezone.utc)
        return utc_value.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalQualificationSerializationError(
                "Canonical JSON does not permit non-finite numbers."
            )
        return value
    if isinstance(value, Mapping):
        normalized = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalQualificationSerializationError(
                    "Canonical JSON object keys must be strings."
                )
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise CanonicalQualificationSerializationError(
                    "Canonical key normalization produced a duplicate field."
                )
            normalized[normalized_key] = canonical_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        raise CanonicalQualificationSerializationError(
            "Unordered collections must be normalized before serialization."
        )
    raise CanonicalQualificationSerializationError(
        f"Unsupported canonical qualification value: {type(value).__name__}."
    )


def parse_json_payload(payload):
    """Parse UTF-8 JSON while rejecting duplicate object fields."""

    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CanonicalQualificationSerializationError(
                "Qualification payload must be valid UTF-8."
            ) from error
    if not isinstance(payload, str):
        raise TypeError("payload must be JSON text or UTF-8 bytes.")
    try:
        return json.loads(payload, object_pairs_hook=_without_duplicate_fields)
    except CanonicalQualificationSerializationError:
        raise
    except json.JSONDecodeError as error:
        raise CanonicalQualificationSerializationError(
            "Qualification payload is invalid JSON."
        ) from error


def _without_duplicate_fields(pairs):
    result = {}
    for key, value in pairs:
        normalized_key = unicodedata.normalize("NFC", key)
        if normalized_key in result:
            raise CanonicalQualificationSerializationError(
                "Qualification JSON must not contain duplicate fields."
            )
        result[normalized_key] = value
    return result


def _normalized_text(value):
    return unicodedata.normalize("NFC", str(value)).strip()


__all__ = [
    "CanonicalQualificationSerializationError",
    "FINGERPRINT_ALGORITHM",
    "canonical_fingerprint",
    "canonical_identity",
    "canonical_json_bytes",
    "canonical_json_text",
    "canonical_sha256_hex",
    "canonical_value",
    "parse_json_payload",
]
