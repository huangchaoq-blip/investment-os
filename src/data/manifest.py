from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
import re

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[2]
MANIFEST_DIR = BASE_DIR / "data" / "metadata" / "manifests"
CANONICAL_BAR_COLUMNS = ["code", "date", "open", "high", "low", "close", "volume"]
CANONICAL_CORPORATE_ACTION_COLUMNS = [
    "code",
    "event_date",
    "action_type",
    "value",
    "numerator",
    "denominator",
    "currency",
    "source",
    "raw_reference",
]
CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
DATASET_VERSION_PATTERN = re.compile(r"^ds-v1-[0-9a-f]{16}$")


class DataClass(str, Enum):
    SYNTHETIC_TEST = "SYNTHETIC_TEST"
    HISTORICAL_MARKET = "HISTORICAL_MARKET"


class ManifestValidationError(ValueError):
    pass


class DatasetEligibilityError(ValueError):
    pass


@dataclass(frozen=True)
class DatasetManifest:
    dataset_version: str
    data_class: DataClass
    source: str
    symbols: tuple[str, ...]
    date_from: str
    date_to: str
    row_count: int
    fetched_at: str
    schema_version: str
    adjustment_policy_version: str
    checksum: str
    creation_context: str
    notes: str

    def validate(self):
        if not DATASET_VERSION_PATTERN.fullmatch(self.dataset_version):
            raise ManifestValidationError(
                f"Invalid dataset_version: {self.dataset_version}"
            )
        if not isinstance(self.data_class, DataClass):
            raise ManifestValidationError(
                f"Invalid data_class: {self.data_class}"
            )
        if not self.source.strip():
            raise ManifestValidationError("source must not be empty.")
        if not self.symbols:
            raise ManifestValidationError("symbols must not be empty.")
        if tuple(sorted(self.symbols)) != self.symbols:
            raise ManifestValidationError("symbols must be sorted.")
        if len(set(self.symbols)) != len(self.symbols):
            raise ManifestValidationError("symbols must not contain duplicates.")
        if self.row_count < 0:
            raise ManifestValidationError("row_count must be >= 0.")
        if not CHECKSUM_PATTERN.fullmatch(self.checksum):
            raise ManifestValidationError(f"Invalid checksum: {self.checksum}")
        if not self.schema_version.strip():
            raise ManifestValidationError("schema_version must not be empty.")
        if not self.adjustment_policy_version.strip():
            raise ManifestValidationError(
                "adjustment_policy_version must not be empty."
            )
        if not self.creation_context.strip():
            raise ManifestValidationError("creation_context must not be empty.")

        date_from = _parse_date(self.date_from, "date_from")
        date_to = _parse_date(self.date_to, "date_to")
        if date_from > date_to:
            raise ManifestValidationError("date_from must be <= date_to.")
        _parse_iso_datetime(self.fetched_at)

    def to_dict(self):
        self.validate()
        return {
            "dataset_version": self.dataset_version,
            "data_class": self.data_class.value,
            "source": self.source,
            "symbols": list(self.symbols),
            "date_from": self.date_from,
            "date_to": self.date_to,
            "row_count": self.row_count,
            "fetched_at": self.fetched_at,
            "schema_version": self.schema_version,
            "adjustment_policy_version": self.adjustment_policy_version,
            "checksum": self.checksum,
            "creation_context": self.creation_context,
            "notes": self.notes,
        }

    def to_json(self):
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        ) + "\n"

    @classmethod
    def from_dict(cls, payload):
        required_fields = {
            "dataset_version",
            "data_class",
            "source",
            "symbols",
            "date_from",
            "date_to",
            "row_count",
            "fetched_at",
            "schema_version",
            "adjustment_policy_version",
            "checksum",
            "creation_context",
            "notes",
        }
        missing_fields = sorted(required_fields - set(payload))
        if missing_fields:
            raise ManifestValidationError(
                "Missing manifest fields: " + ", ".join(missing_fields)
            )

        try:
            data_class = DataClass(payload["data_class"])
        except ValueError as error:
            raise ManifestValidationError(
                f"Invalid data_class: {payload['data_class']}"
            ) from error

        manifest = cls(
            dataset_version=str(payload["dataset_version"]),
            data_class=data_class,
            source=str(payload["source"]),
            symbols=tuple(str(symbol) for symbol in payload["symbols"]),
            date_from=str(payload["date_from"]),
            date_to=str(payload["date_to"]),
            row_count=int(payload["row_count"]),
            fetched_at=str(payload["fetched_at"]),
            schema_version=str(payload["schema_version"]),
            adjustment_policy_version=str(payload["adjustment_policy_version"]),
            checksum=str(payload["checksum"]),
            creation_context=str(payload["creation_context"]),
            notes=str(payload["notes"]),
        )
        manifest.validate()
        return manifest

    @classmethod
    def from_json(cls, value):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as error:
            raise ManifestValidationError("Invalid manifest JSON.") from error

        if not isinstance(payload, dict):
            raise ManifestValidationError("Manifest JSON must be an object.")
        return cls.from_dict(payload)


def canonicalize_daily_bars(dataframe):
    missing_columns = [
        column for column in CANONICAL_BAR_COLUMNS if column not in dataframe.columns
    ]
    if missing_columns:
        raise ManifestValidationError(
            "Missing canonical bar columns: " + ", ".join(missing_columns)
        )

    rows = []
    for record in dataframe[CANONICAL_BAR_COLUMNS].to_dict("records"):
        rows.append(
            {
                "code": str(record["code"]).strip(),
                "date": _normalize_date(record["date"]),
                "open": _normalize_number(record["open"]),
                "high": _normalize_number(record["high"]),
                "low": _normalize_number(record["low"]),
                "close": _normalize_number(record["close"]),
                "volume": _normalize_number(record["volume"]),
            }
        )

    return sorted(
        rows,
        key=lambda row: tuple(
            "" if row[column] is None else str(row[column])
            for column in CANONICAL_BAR_COLUMNS
        ),
    )


def calculate_checksum(dataframe):
    canonical_rows = canonicalize_daily_bars(dataframe)
    return _checksum_for_rows(canonical_rows)


def canonicalize_corporate_actions(dataframe):
    missing_columns = [
        column
        for column in CANONICAL_CORPORATE_ACTION_COLUMNS
        if column not in dataframe.columns
    ]
    if missing_columns:
        raise ManifestValidationError(
            "Missing canonical corporate action columns: " + ", ".join(missing_columns)
        )

    rows = []
    for record in dataframe[CANONICAL_CORPORATE_ACTION_COLUMNS].to_dict("records"):
        rows.append(
            {
                "code": _normalize_text(record["code"]),
                "event_date": _normalize_date(record["event_date"]),
                "action_type": _normalize_text(record["action_type"]),
                "value": _normalize_number(record["value"]),
                "numerator": _normalize_number(record["numerator"]),
                "denominator": _normalize_number(record["denominator"]),
                "currency": _normalize_text(record["currency"]),
                "source": _normalize_text(record["source"]),
                "raw_reference": _normalize_text(record["raw_reference"]),
            }
        )

    return sorted(
        rows,
        key=lambda row: tuple(
            "" if row[column] is None else str(row[column])
            for column in CANONICAL_CORPORATE_ACTION_COLUMNS
        ),
    )


def calculate_corporate_actions_checksum(dataframe):
    return _checksum_for_rows(canonicalize_corporate_actions(dataframe))


def calculate_dataset_checksum(bars_dataframe, corporate_actions_dataframe):
    payload = json.dumps(
        {
            "bars_checksum": calculate_checksum(bars_dataframe),
            "corporate_actions_checksum": calculate_corporate_actions_checksum(
                corporate_actions_dataframe
            ),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def create_dataset_manifest(
    dataframe,
    data_class,
    source,
    schema_version,
    adjustment_policy_version,
    creation_context,
    notes="",
    fetched_at=None,
    content_checksum=None,
):
    normalized_class = _coerce_data_class(data_class)
    canonical_rows = canonicalize_daily_bars(dataframe)
    if not canonical_rows:
        raise ManifestValidationError("Cannot create a manifest for an empty dataset.")

    symbols = tuple(sorted({row["code"] for row in canonical_rows}))
    if not all(symbols):
        raise ManifestValidationError("code must not be empty.")

    dates = [row["date"] for row in canonical_rows]
    checksum = content_checksum or _checksum_for_rows(canonical_rows)
    dataset_version = generate_dataset_version(
        data_class=normalized_class,
        source=source,
        symbols=symbols,
        date_from=min(dates),
        date_to=max(dates),
        schema_version=schema_version,
        adjustment_policy_version=adjustment_policy_version,
        checksum=checksum,
    )
    manifest = DatasetManifest(
        dataset_version=dataset_version,
        data_class=normalized_class,
        source=str(source),
        symbols=symbols,
        date_from=min(dates),
        date_to=max(dates),
        row_count=len(canonical_rows),
        fetched_at=fetched_at or _now_iso(),
        schema_version=str(schema_version),
        adjustment_policy_version=str(adjustment_policy_version),
        checksum=checksum,
        creation_context=str(creation_context),
        notes=str(notes),
    )
    manifest.validate()
    return manifest


def generate_dataset_version(
    data_class,
    source,
    symbols,
    date_from,
    date_to,
    schema_version,
    adjustment_policy_version,
    checksum,
):
    normalized_class = _coerce_data_class(data_class)
    identity = {
        "data_class": normalized_class.value,
        "source": str(source),
        "symbols": sorted(str(symbol) for symbol in symbols),
        "date_from": str(date_from),
        "date_to": str(date_to),
        "schema_version": str(schema_version),
        "adjustment_policy_version": str(adjustment_policy_version),
        "checksum": str(checksum),
    }
    payload = json.dumps(identity, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return "ds-v1-" + sha256(payload.encode("utf-8")).hexdigest()[:16]


def save_dataset_manifest(manifest, manifest_dir=MANIFEST_DIR):
    manifest.validate()
    manifest_dir = Path(manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / f"{manifest.dataset_version}.json"
    path.write_text(manifest.to_json(), encoding="utf-8")
    return path


def load_dataset_manifest(dataset_version, manifest_dir=MANIFEST_DIR):
    path = Path(manifest_dir) / f"{dataset_version}.json"
    if not path.exists():
        raise DatasetEligibilityError(
            f"Dataset version {dataset_version}, data class UNCLASSIFIED: manifest is missing."
        )
    return DatasetManifest.from_json(path.read_text(encoding="utf-8"))


def assert_historical_market_dataset(manifest, actual_checksum=None, dataset_version=None):
    if manifest is None:
        version = dataset_version or "unknown"
        raise DatasetEligibilityError(
            f"Dataset version {version}, data class UNCLASSIFIED: manifest is required."
        )

    manifest.validate()
    if manifest.data_class is not DataClass.HISTORICAL_MARKET:
        raise DatasetEligibilityError(
            f"Dataset version {manifest.dataset_version}, data class "
            f"{manifest.data_class.value}: historical market data is required."
        )
    if actual_checksum is not None and actual_checksum != manifest.checksum:
        raise DatasetEligibilityError(
            f"Dataset version {manifest.dataset_version}, data class "
            f"{manifest.data_class.value}: checksum mismatch."
        )
    return manifest


def create_synthetic_sample_manifest(codes=("7203", "6758"), fetched_at=None):
    from .storage import load_raw_daily

    frames = []
    for code in sorted(str(code) for code in codes):
        raw = load_raw_daily(code).copy()
        raw.insert(0, "code", code)
        frames.append(raw)

    dataframe = pd.concat(frames, ignore_index=True)
    return create_dataset_manifest(
        dataframe=dataframe,
        data_class=DataClass.SYNTHETIC_TEST,
        source="deterministic_sample",
        schema_version="raw-daily-v1",
        adjustment_policy_version="unadjusted-v1",
        creation_context="WO-033 deterministic sample manifest",
        notes="Deterministic smoke-test data only. Not eligible for formal Replay.",
        fetched_at=fetched_at,
    )


def _checksum_for_rows(canonical_rows):
    payload = json.dumps(
        canonical_rows,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def _coerce_data_class(value):
    if isinstance(value, DataClass):
        return value
    try:
        return DataClass(value)
    except ValueError as error:
        raise ManifestValidationError(f"Invalid data_class: {value}") from error


def _normalize_date(value):
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError) as error:
        raise ManifestValidationError(f"Invalid date: {value}") from error


def _normalize_number(value):
    if pd.isna(value):
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ManifestValidationError(f"Invalid numeric value: {value}") from error
    if not decimal.is_finite():
        raise ManifestValidationError(f"Invalid numeric value: {value}")
    normalized = format(decimal.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _normalize_text(value):
    if pd.isna(value):
        return None
    return str(value).strip()


def _parse_date(value, field_name):
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ManifestValidationError(f"Invalid {field_name}: {value}") from error


def _parse_iso_datetime(value):
    if "T" not in value:
        raise ManifestValidationError(f"Invalid fetched_at: {value}")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ManifestValidationError(f"Invalid fetched_at: {value}") from error


def _now_iso():
    return datetime.now(timezone.utc).isoformat()
