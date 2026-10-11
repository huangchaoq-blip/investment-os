"""Immutable provider-neutral acquisition contracts for the Data Platform."""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
import math
import re
from typing import Iterable, Mapping

from .errors import InvalidProviderDataError, UnsupportedProviderRequestError


class Market(str, Enum):
    JP = "JP"


class AssetType(str, Enum):
    EQUITY = "EQUITY"


class UpdateMode(str, Enum):
    FULL_BOOTSTRAP = "FULL_BOOTSTRAP"
    INCREMENTAL = "INCREMENTAL"


class ProviderQualificationStatus(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    PROVISIONAL = "PROVISIONAL"
    QUALIFIED_FOR_RESEARCH = "QUALIFIED_FOR_RESEARCH"
    QUALIFIED_FOR_DAILY_PAPER_OPERATION = "QUALIFIED_FOR_DAILY_PAPER_OPERATION"
    DISQUALIFIED = "DISQUALIFIED"


class ProviderFetchStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ProviderAcquisitionFailureCategory(str, Enum):
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    HTTP_ERROR = "HTTP_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    INCOMPLETE_RESPONSE = "INCOMPLETE_RESPONSE"
    PARSE_ERROR = "PARSE_ERROR"
    INVALID_PROVIDER_DATA = "INVALID_PROVIDER_DATA"
    UNSUPPORTED_REQUEST = "UNSUPPORTED_REQUEST"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"


class InvalidDataFailureStage(str, Enum):
    PROVIDER_RESPONSE_PARSE = "PROVIDER_RESPONSE_PARSE"
    PROVIDER_ROW_NORMALIZATION = "PROVIDER_ROW_NORMALIZATION"
    CANONICAL_CONVERSION = "CANONICAL_CONVERSION"
    CANONICAL_VALIDATION = "CANONICAL_VALIDATION"
    RESULT_ASSEMBLY = "RESULT_ASSEMBLY"


class CapabilitySupport(str, Enum):
    SUPPORTED = "SUPPORTED"
    LIMITED = "LIMITED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProviderInvalidDataEvidence:
    """Safe first-failure evidence for a rejected canonical acquisition."""

    failure_stage: InvalidDataFailureStage
    validation_rule: str
    affected_symbol: str | None = None
    affected_date: str | None = None
    affected_field: str | None = None
    safe_actual_value_summary: str | None = None
    safe_expected_constraint: str | None = None
    rejected_record_count: int = 1
    first_failure_only: bool = True
    additional_failure_count: int = 0
    all_canonical_bars_discarded: bool = False
    discarded_canonical_bar_count: int = 0
    discarded_symbols: tuple[str, ...] = ()

    def __post_init__(self):
        stage = InvalidDataFailureStage(self.failure_stage)
        rule = _safe_message(self.validation_rule)
        if not rule:
            raise ValueError("Invalid-data evidence requires a validation_rule.")
        if not isinstance(self.rejected_record_count, int) or self.rejected_record_count < 1:
            raise ValueError("rejected_record_count must be a positive integer.")
        if not isinstance(self.additional_failure_count, int) or self.additional_failure_count < 0:
            raise ValueError("additional_failure_count must be a non-negative integer.")
        if not isinstance(self.discarded_canonical_bar_count, int) or self.discarded_canonical_bar_count < 0:
            raise ValueError("discarded_canonical_bar_count must be a non-negative integer.")
        object.__setattr__(self, "failure_stage", stage)
        object.__setattr__(self, "validation_rule", rule)
        object.__setattr__(self, "affected_symbol", _optional_text(self.affected_symbol))
        object.__setattr__(self, "affected_date", _optional_text(self.affected_date))
        object.__setattr__(self, "affected_field", _optional_text(self.affected_field))
        object.__setattr__(self, "safe_actual_value_summary", _safe_message(self.safe_actual_value_summary))
        object.__setattr__(self, "safe_expected_constraint", _safe_message(self.safe_expected_constraint))
        object.__setattr__(self, "first_failure_only", bool(self.first_failure_only))
        object.__setattr__(self, "all_canonical_bars_discarded", bool(self.all_canonical_bars_discarded))
        object.__setattr__(self, "discarded_symbols", _normalize_symbols(self.discarded_symbols) if self.discarded_symbols else ())

    def to_dict(self):
        return {
            "failure_stage": self.failure_stage.value,
            "validation_rule": self.validation_rule,
            "affected_symbol": self.affected_symbol,
            "affected_date": self.affected_date,
            "affected_field": self.affected_field,
            "safe_actual_value_summary": self.safe_actual_value_summary,
            "safe_expected_constraint": self.safe_expected_constraint,
            "rejected_record_count": self.rejected_record_count,
            "first_failure_only": self.first_failure_only,
            "additional_failure_count": self.additional_failure_count,
            "all_canonical_bars_discarded": self.all_canonical_bars_discarded,
            "discarded_canonical_bar_count": self.discarded_canonical_bar_count,
            "discarded_symbols": list(self.discarded_symbols),
        }


@dataclass(frozen=True)
class ProviderRangeEvidence:
    """Safe audit evidence for provider over-fetch and canonical range selection."""

    provider_returned_earliest_date: date | None
    provider_returned_latest_date: date | None
    canonical_selected_earliest_date: date | None
    canonical_selected_latest_date: date | None
    records_before_requested_range: int = 0
    records_after_requested_range: int = 0
    out_of_range_records_discarded: int = 0
    per_symbol_out_of_range_counts: tuple[tuple[str, int, int], ...] = ()
    range_clipping_applied: bool = False
    requested_range_semantics: str = "INCLUSIVE"

    def __post_init__(self):
        for field_name in (
            "records_before_requested_range",
            "records_after_requested_range",
            "out_of_range_records_discarded",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer.")
        expected_discarded = self.records_before_requested_range + self.records_after_requested_range
        if self.out_of_range_records_discarded != expected_discarded:
            raise ValueError("Discarded range count must equal before plus after counts.")
        counts = []
        for symbol, before_count, after_count in self.per_symbol_out_of_range_counts:
            symbol = str(symbol).strip().upper()
            if not symbol:
                raise ValueError("Per-symbol range evidence requires a symbol.")
            if not isinstance(before_count, int) or before_count < 0:
                raise ValueError("Per-symbol before count must be a non-negative integer.")
            if not isinstance(after_count, int) or after_count < 0:
                raise ValueError("Per-symbol after count must be a non-negative integer.")
            counts.append((symbol, before_count, after_count))
        if len({item[0] for item in counts}) != len(counts):
            raise ValueError("Per-symbol range evidence must contain unique symbols.")
        if sum(item[1] for item in counts) != self.records_before_requested_range:
            raise ValueError("Per-symbol before counts must equal the aggregate count.")
        if sum(item[2] for item in counts) != self.records_after_requested_range:
            raise ValueError("Per-symbol after counts must equal the aggregate count.")
        if bool(self.range_clipping_applied) != (self.out_of_range_records_discarded > 0):
            raise ValueError("range_clipping_applied must reflect discarded records.")
        semantics = str(self.requested_range_semantics).strip().upper()
        if semantics != "INCLUSIVE":
            raise ValueError("Only INCLUSIVE requested range semantics are supported.")
        object.__setattr__(
            self,
            "provider_returned_earliest_date",
            _coerce_optional_date(
                self.provider_returned_earliest_date,
                "provider_returned_earliest_date",
            ),
        )
        object.__setattr__(
            self,
            "provider_returned_latest_date",
            _coerce_optional_date(
                self.provider_returned_latest_date,
                "provider_returned_latest_date",
            ),
        )
        object.__setattr__(
            self,
            "canonical_selected_earliest_date",
            _coerce_optional_date(
                self.canonical_selected_earliest_date,
                "canonical_selected_earliest_date",
            ),
        )
        object.__setattr__(
            self,
            "canonical_selected_latest_date",
            _coerce_optional_date(
                self.canonical_selected_latest_date,
                "canonical_selected_latest_date",
            ),
        )
        object.__setattr__(self, "per_symbol_out_of_range_counts", tuple(sorted(counts)))
        object.__setattr__(self, "range_clipping_applied", bool(self.range_clipping_applied))
        object.__setattr__(self, "requested_range_semantics", semantics)

    def to_dict(self):
        return {
            "provider_returned_earliest_date": _date_text(self.provider_returned_earliest_date),
            "provider_returned_latest_date": _date_text(self.provider_returned_latest_date),
            "canonical_selected_earliest_date": _date_text(self.canonical_selected_earliest_date),
            "canonical_selected_latest_date": _date_text(self.canonical_selected_latest_date),
            "records_before_requested_range": self.records_before_requested_range,
            "records_after_requested_range": self.records_after_requested_range,
            "out_of_range_records_discarded": self.out_of_range_records_discarded,
            "per_symbol_out_of_range_counts": {
                symbol: {
                    "before_requested_range": before_count,
                    "after_requested_range": after_count,
                }
                for symbol, before_count, after_count in self.per_symbol_out_of_range_counts
            },
            "range_clipping_applied": self.range_clipping_applied,
            "requested_range_semantics": self.requested_range_semantics,
        }


_SENSITIVE_PROVENANCE_KEY = re.compile(
    r"(?i)(api[_-]?key|token|password|authorization|cookie|secret)"
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(api[_ -]?key|token|password|authorization|cookie|secret)([=:]\s*)[^\s,;]+"
)


@dataclass(frozen=True)
class DailyBarRequest:
    """A normalized, credential-free request for canonical daily bar evidence."""

    request_id: str
    market: Market
    asset_type: AssetType
    symbols: tuple[str, ...]
    start_date: date
    end_date: date
    update_mode: UpdateMode
    previous_dataset_version: str | None = None
    overlap_window_days: int | None = None

    def __post_init__(self):
        if not str(self.request_id).strip():
            raise UnsupportedProviderRequestError("request_id must not be empty.")

        try:
            market = Market(self.market)
            asset_type = AssetType(self.asset_type)
            update_mode = UpdateMode(self.update_mode)
        except ValueError as error:
            raise UnsupportedProviderRequestError(
                "Unsupported market, asset type, or update mode."
            ) from error

        if market is not Market.JP or asset_type is not AssetType.EQUITY:
            raise UnsupportedProviderRequestError(
                "Only JP EQUITY daily-bar requests are supported."
            )

        symbols = _normalize_symbols(self.symbols)
        start_date = _coerce_date(self.start_date, "start_date")
        end_date = _coerce_date(self.end_date, "end_date")
        if start_date > end_date:
            raise UnsupportedProviderRequestError("start_date must be on or before end_date.")

        if self.overlap_window_days is not None:
            if not isinstance(self.overlap_window_days, int) or self.overlap_window_days < 0:
                raise UnsupportedProviderRequestError(
                    "overlap_window_days must be a non-negative integer."
                )

        previous_version = _optional_text(self.previous_dataset_version)
        object.__setattr__(self, "request_id", str(self.request_id).strip())
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "asset_type", asset_type)
        object.__setattr__(self, "symbols", symbols)
        object.__setattr__(self, "start_date", start_date)
        object.__setattr__(self, "end_date", end_date)
        object.__setattr__(self, "update_mode", update_mode)
        object.__setattr__(self, "previous_dataset_version", previous_version)


@dataclass(frozen=True)
class CanonicalDailyBar:
    """Source-returned raw daily-bar evidence before dataset publication."""

    code: str
    market: str
    date: str
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float | None
    volume: float
    currency: str
    source: str
    source_symbol: str
    fetched_at: str
    schema_version: str

    def __post_init__(self):
        if not str(self.code).strip() or not str(self.market).strip():
            raise InvalidProviderDataError("Canonical bar requires code and market.")
        _coerce_date(self.date, "bar date")
        values = (self.open, self.high, self.low, self.close)
        if any(not _finite_positive(value) for value in values):
            raise InvalidProviderDataError("OHLC values must be finite positive numbers.")
        if self.high < max(self.open, self.low, self.close):
            raise InvalidProviderDataError("high must be >= open, low, and close.")
        if self.low > min(self.open, self.high, self.close):
            raise InvalidProviderDataError("low must be <= open, high, and close.")
        if not _finite_nonnegative(self.volume):
            raise InvalidProviderDataError("volume must be a finite non-negative number.")
        if self.adjusted_close is not None and not _finite_positive(self.adjusted_close):
            raise InvalidProviderDataError("adjusted_close must be positive when supplied.")
        for field_name in ("currency", "source", "source_symbol", "fetched_at", "schema_version"):
            if not str(getattr(self, field_name)).strip():
                raise InvalidProviderDataError(f"Canonical bar requires {field_name}.")

    def to_record(self):
        return {
            "code": self.code,
            "market": self.market,
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "adjusted_close": self.adjusted_close,
            "volume": self.volume,
            "currency": self.currency,
            "source": self.source,
            "source_symbol": self.source_symbol,
            "fetched_at": self.fetched_at,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class CanonicalCorporateAction:
    """Raw provider action evidence using the existing DEC-004 fields."""

    code: str
    market: str
    event_date: str
    action_type: str
    value: float | None
    numerator: float | None
    denominator: float | None
    currency: str
    source: str
    fetched_at: str
    raw_reference: str

    def __post_init__(self):
        if not str(self.code).strip() or not str(self.market).strip():
            raise InvalidProviderDataError("Corporate action requires code and market.")
        _coerce_date(self.event_date, "event_date")
        if not str(self.action_type).strip() or not str(self.currency).strip():
            raise InvalidProviderDataError("Corporate action requires type and currency.")
        if not str(self.source).strip() or not str(self.fetched_at).strip():
            raise InvalidProviderDataError("Corporate action requires source and fetched_at.")
        if not str(self.raw_reference).strip():
            raise InvalidProviderDataError("Corporate action requires raw_reference.")

    def to_record(self):
        return {
            "code": self.code,
            "market": self.market,
            "event_date": self.event_date,
            "action_type": self.action_type,
            "value": self.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "currency": self.currency,
            "source": self.source,
            "fetched_at": self.fetched_at,
            "raw_reference": self.raw_reference,
        }


@dataclass(frozen=True)
class ProviderCapabilities:
    provider_id: str
    adapter_version: str
    qualification_status: ProviderQualificationStatus
    supported_markets: tuple[Market, ...]
    supported_asset_types: tuple[AssetType, ...]
    daily_bars: CapabilitySupport
    incremental_daily_bars: CapabilitySupport
    corporate_actions: CapabilitySupport
    raw_ohlc_semantics: str
    adjusted_close_semantics: str
    corporate_action_semantics: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self):
        if not str(self.provider_id).strip() or not str(self.adapter_version).strip():
            raise ValueError("Provider capabilities require stable identity and adapter version.")


@dataclass(frozen=True)
class ProviderFetchResult:
    """Immutable result for one acquisition request; it never publishes data."""

    status: ProviderFetchStatus
    request_id: str
    provider_id: str
    adapter_version: str
    qualification_status: ProviderQualificationStatus
    requested_symbols: tuple[str, ...]
    received_symbols: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    requested_start_date: date
    requested_end_date: date
    received_start_date: date | None
    received_end_date: date | None
    bars: tuple[CanonicalDailyBar, ...] = ()
    corporate_actions: tuple[CanonicalCorporateAction, ...] = ()
    warnings: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    retryable: bool = False
    error_code: str | None = None
    failure_category: ProviderAcquisitionFailureCategory | None = None
    safe_message: str | None = None
    http_status_code: int | None = None
    attempt_count: int = 1
    provenance: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    invalid_data_evidence: ProviderInvalidDataEvidence | None = None
    range_evidence: ProviderRangeEvidence | None = None

    def __post_init__(self):
        status = ProviderFetchStatus(self.status)
        qualification_status = ProviderQualificationStatus(self.qualification_status)
        requested = _normalize_symbols(self.requested_symbols)
        received = tuple(sorted({str(value).strip() for value in self.received_symbols}))
        missing = tuple(sorted({str(value).strip() for value in self.missing_symbols}))
        if set(received) - set(requested) or set(missing) - set(requested):
            raise ValueError("Received and missing symbols must be requested symbols.")
        if set(received) & set(missing):
            raise ValueError("A symbol cannot be both received and missing.")
        if status is ProviderFetchStatus.SUCCESS and (missing or self.blocking_reasons):
            raise ValueError("SUCCESS cannot contain missing symbols or blocking reasons.")
        if status is ProviderFetchStatus.PARTIAL and not (missing or self.warnings or self.blocking_reasons):
            raise ValueError("PARTIAL requires explicit incomplete-response evidence.")
        if status in {ProviderFetchStatus.BLOCKED, ProviderFetchStatus.FAILED} and not (
            self.blocking_reasons or self.error_code
        ):
            raise ValueError("BLOCKED and FAILED results require a reason or error code.")
        if status is ProviderFetchStatus.SUCCESS and set(received) != set(requested):
            raise ValueError("SUCCESS must cover every requested symbol.")

        bars = tuple(sorted(self.bars, key=lambda item: (item.code, item.date)))
        actions = tuple(
            sorted(
                self.corporate_actions,
                key=lambda item: (item.code, item.event_date, item.action_type, item.raw_reference),
            )
        )
        if bars and {bar.code for bar in bars} - set(received):
            raise ValueError("Bars must belong to received symbols.")
        if not isinstance(self.attempt_count, int) or self.attempt_count < 1:
            raise ValueError("attempt_count must be a positive integer.")
        if self.http_status_code is not None and (
            not isinstance(self.http_status_code, int) or not 100 <= self.http_status_code <= 599
        ):
            raise ValueError("http_status_code must be an HTTP status integer or None.")
        category = self.failure_category
        if category is not None:
            category = ProviderAcquisitionFailureCategory(category)
        elif status is not ProviderFetchStatus.SUCCESS:
            category = _failure_category_from_error_code(self.error_code)
        if status is ProviderFetchStatus.SUCCESS and category is not None:
            raise ValueError("SUCCESS cannot contain an acquisition failure category.")
        if self.invalid_data_evidence is not None:
            if not isinstance(self.invalid_data_evidence, ProviderInvalidDataEvidence):
                raise TypeError("invalid_data_evidence must be ProviderInvalidDataEvidence or None.")
            if category is not ProviderAcquisitionFailureCategory.INVALID_PROVIDER_DATA:
                raise ValueError("Invalid-data evidence requires INVALID_PROVIDER_DATA.")
        if self.range_evidence is not None and not isinstance(self.range_evidence, ProviderRangeEvidence):
            raise TypeError("range_evidence must be ProviderRangeEvidence or None.")

        object.__setattr__(self, "status", status)
        object.__setattr__(self, "qualification_status", qualification_status)
        object.__setattr__(self, "requested_symbols", requested)
        object.__setattr__(self, "received_symbols", received)
        object.__setattr__(self, "missing_symbols", missing)
        object.__setattr__(self, "requested_start_date", _coerce_date(self.requested_start_date, "requested_start_date"))
        object.__setattr__(self, "requested_end_date", _coerce_date(self.requested_end_date, "requested_end_date"))
        object.__setattr__(self, "received_start_date", _coerce_optional_date(self.received_start_date, "received_start_date"))
        object.__setattr__(self, "received_end_date", _coerce_optional_date(self.received_end_date, "received_end_date"))
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "corporate_actions", actions)
        object.__setattr__(self, "warnings", tuple(str(value) for value in self.warnings))
        object.__setattr__(self, "blocking_reasons", tuple(str(value) for value in self.blocking_reasons))
        object.__setattr__(self, "retryable", bool(self.retryable))
        object.__setattr__(self, "error_code", _optional_text(self.error_code))
        object.__setattr__(self, "failure_category", category)
        object.__setattr__(self, "safe_message", _safe_message(self.safe_message))
        object.__setattr__(self, "http_status_code", self.http_status_code)
        object.__setattr__(self, "attempt_count", self.attempt_count)
        object.__setattr__(self, "provenance", _freeze_provenance(self.provenance))


def _normalize_symbols(values: Iterable[str]):
    symbols = tuple(sorted({str(value).strip().upper() for value in values if str(value).strip()}))
    if not symbols:
        raise UnsupportedProviderRequestError("symbols must not be empty.")
    return symbols


def _coerce_date(value, field_name):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise InvalidProviderDataError(f"{field_name} must be an ISO date.") from error
    raise InvalidProviderDataError(f"{field_name} must be a date.")


def _coerce_optional_date(value, field_name):
    return None if value is None else _coerce_date(value, field_name)


def _date_text(value):
    return None if value is None else value.isoformat()


def _finite_positive(value):
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0


def _finite_nonnegative(value):
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) >= 0


def _optional_text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _safe_message(value):
    if value is None:
        return None
    message = _SENSITIVE_VALUE.sub(r"\1\2<redacted>", str(value)).strip()
    return message or None


def _failure_category_from_error_code(error_code):
    mapping = {
        "RATE_LIMIT": ProviderAcquisitionFailureCategory.RATE_LIMIT,
        "TIMEOUT": ProviderAcquisitionFailureCategory.TIMEOUT,
        "PROVIDER_UNAVAILABLE": ProviderAcquisitionFailureCategory.PROVIDER_UNAVAILABLE,
        "HTTP_ERROR": ProviderAcquisitionFailureCategory.HTTP_ERROR,
        "NETWORK_ERROR": ProviderAcquisitionFailureCategory.NETWORK_ERROR,
        "AUTHENTICATION_ERROR": ProviderAcquisitionFailureCategory.AUTHENTICATION_ERROR,
        "EMPTY_RESPONSE": ProviderAcquisitionFailureCategory.EMPTY_RESPONSE,
        "INCOMPLETE_RESPONSE": ProviderAcquisitionFailureCategory.INCOMPLETE_RESPONSE,
        "PARSE_ERROR": ProviderAcquisitionFailureCategory.PARSE_ERROR,
        "INVALID_PROVIDER_DATA": ProviderAcquisitionFailureCategory.INVALID_PROVIDER_DATA,
        "UNSUPPORTED_REQUEST": ProviderAcquisitionFailureCategory.UNSUPPORTED_REQUEST,
    }
    return mapping.get(str(error_code or "").strip(), ProviderAcquisitionFailureCategory.UNKNOWN_PROVIDER_ERROR)


def _freeze_provenance(values: Mapping[str, str] | Iterable[tuple[str, str]]):
    items = values.items() if isinstance(values, Mapping) else values
    frozen = []
    for key, value in items:
        key = str(key).strip()
        if not key:
            raise ValueError("Provenance keys must not be empty.")
        if _SENSITIVE_PROVENANCE_KEY.search(key):
            raise ValueError("Provenance must not contain credentials or secrets.")
        frozen.append((key, str(value)))
    return tuple(sorted(frozen))
