from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from data.historical_ingestion import DEFAULT_DATASET_ROOT
from data.manifest import (
    DataClass,
    DatasetManifest,
    DatasetEligibilityError,
    calculate_dataset_checksum,
    assert_historical_market_dataset,
)
from data.corporate_action_normalization import (
    load_canonical_actions,
    normalize_corporate_actions,
)


SIGNAL_COLUMNS = ["signal_open", "signal_high", "signal_low", "signal_close", "signal_volume"]
REQUIRED_BAR_COLUMNS = {"code", "date", "open", "high", "low", "close", "volume"}
REQUIRED_ACTION_COLUMNS = {
    "code",
    "event_date",
    "action_type",
    "numerator",
    "denominator",
}
_DATASET_CACHE = {}


@dataclass(frozen=True)
class PullbackFacts:
    code: str
    requested_date: str
    facts_date: Optional[str]
    dataset_version: str
    data_class: Optional[str]
    adjustment_policy_version: Optional[str]
    canonical_corporate_action_version: Optional[str]
    raw_open: Optional[float]
    raw_high: Optional[float]
    raw_low: Optional[float]
    raw_close: Optional[float]
    raw_volume: Optional[float]
    signal_open: Optional[float]
    signal_high: Optional[float]
    signal_low: Optional[float]
    signal_close: Optional[float]
    signal_volume: Optional[float]
    ma25: Optional[float]
    ma75: Optional[float]
    ma75_5d_ago: Optional[float]
    atr14: Optional[float]
    volume20: Optional[float]
    volume_ratio: Optional[float]
    pullback_low_5: Optional[float]
    previous_close: Optional[float]
    previous_ma25: Optional[float]
    close_above_ma75: Optional[bool]
    ma25_above_ma75: Optional[bool]
    ma75_not_lower_than_5d_ago: Optional[bool]
    previous_close_at_or_below_previous_ma25: Optional[bool]
    current_close_above_current_ma25: Optional[bool]
    current_close_above_previous_close: Optional[bool]
    current_close_within_3pct_of_ma25: Optional[bool]
    provisional_stop_below_signal_close: Optional[bool]
    estimated_risk_within_5pct: Optional[bool]
    provisional_stop: Optional[float]
    estimated_risk: Optional[float]
    estimated_risk_pct: Optional[float]
    applied_split_events: tuple[dict, ...]
    rejected_corporate_action_events: tuple[dict, ...]
    cumulative_price_adjustment_factor: Optional[float]
    cumulative_volume_adjustment_factor: Optional[float]
    corporate_action_status: str
    status: str
    missing_fields: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]

    def to_dict(self):
        return asdict(self)


def build_pullback_facts(code, requested_date, dataset_version, dataset_root=DEFAULT_DATASET_ROOT):
    """Build deterministic Pullback evidence from one versioned local dataset.

    This function intentionally emits facts and availability state only. It never
    decides BUY, WAIT, PASS, or any recommendation.
    """

    code = str(code)
    requested_date = str(requested_date)
    dataset_version = str(dataset_version)
    try:
        dataset = _load_dataset(dataset_version, dataset_root)
    except Exception as error:
        return _unavailable_facts(
            code=code,
            requested_date=requested_date,
            dataset_version=dataset_version,
            status="INVALID_DATASET",
            reason=f"code={code}; dataset_version={dataset_version}; {error}",
        )

    manifest = dataset["manifest"]
    if manifest.data_class is DataClass.HISTORICAL_MARKET:
        try:
            assert_historical_market_dataset(
                manifest,
                actual_checksum=dataset["checksum"],
            )
        except DatasetEligibilityError as error:
            return _unavailable_facts(
                code=code,
                requested_date=requested_date,
                dataset_version=dataset_version,
                data_class=manifest.data_class.value,
                adjustment_policy_version=manifest.adjustment_policy_version,
                status="INVALID_DATASET",
                reason=f"code={code}; dataset_version={dataset_version}; {error}",
            )
    elif manifest.data_class is not DataClass.SYNTHETIC_TEST:
        return _unavailable_facts(
            code=code,
            requested_date=requested_date,
            dataset_version=dataset_version,
            data_class=manifest.data_class.value,
            adjustment_policy_version=manifest.adjustment_policy_version,
            status="INVALID_DATASET",
            reason=(
                f"code={code}; dataset_version={dataset_version}; "
                f"unsupported data_class={manifest.data_class.value}"
            ),
        )

    code_bars = dataset["bars_by_code"].get(code)
    if code_bars is not None:
        code_bars = code_bars.copy()
    if code_bars is None or code_bars.empty:
        return _unavailable_facts(
            code=code,
            requested_date=requested_date,
            dataset_version=dataset_version,
            data_class=manifest.data_class.value,
            adjustment_policy_version=manifest.adjustment_policy_version,
            status="NO_FACTS_DATE",
            reason=f"code={code}; dataset_version={dataset_version}; code is absent.",
        )

    try:
        requested_timestamp = pd.Timestamp(requested_date).normalize()
    except (TypeError, ValueError):
        return _unavailable_facts(
            code=code,
            requested_date=requested_date,
            dataset_version=dataset_version,
            data_class=manifest.data_class.value,
            adjustment_policy_version=manifest.adjustment_policy_version,
            status="NO_FACTS_DATE",
            reason=(
                f"code={code}; requested_date={requested_date}; "
                f"dataset_version={dataset_version}; invalid requested date."
            ),
        )

    code_bars["date"] = pd.to_datetime(code_bars["date"]).dt.normalize()
    code_bars = code_bars[code_bars["date"] <= requested_timestamp]
    if code_bars.empty:
        return _unavailable_facts(
            code=code,
            requested_date=requested_date,
            dataset_version=dataset_version,
            data_class=manifest.data_class.value,
            adjustment_policy_version=manifest.adjustment_policy_version,
            status="NO_FACTS_DATE",
            reason=(
                f"code={code}; requested_date={requested_date}; "
                f"dataset_version={dataset_version}; no record on or before requested date."
            ),
        )

    facts_date = code_bars["date"].max()
    try:
        signal, action_evidence = build_point_in_time_signal_series(
            code=code,
            bars=code_bars,
            corporate_actions=dataset["canonical_corporate_actions"],
            facts_date=facts_date,
        )
    except CorporateActionUnknownError as error:
        rejected_events = _canonical_rejections(
            dataset["canonical_corporate_actions"], code, facts_date
        )
        return _unavailable_facts(
            code=code,
            requested_date=requested_date,
            facts_date=facts_date.date().isoformat(),
            dataset_version=dataset_version,
            data_class=manifest.data_class.value,
            adjustment_policy_version=manifest.adjustment_policy_version,
            canonical_corporate_action_version=dataset["canonical_corporate_action_version"],
            status="UNKNOWN_CORPORATE_ACTION",
            corporate_action_status="UNKNOWN_CORPORATE_ACTION",
            rejected_corporate_action_events=rejected_events,
            reason=f"code={code}; facts_date={facts_date.date()}; {error}",
        )

    featured = build_pullback_features(signal)
    return _facts_from_featured(
        code=code,
        requested_date=requested_date,
        facts_date=facts_date.date().isoformat(),
        manifest=manifest,
        featured=featured,
        action_evidence=action_evidence,
        canonical_corporate_action_version=dataset["canonical_corporate_action_version"],
    )


class CorporateActionUnknownError(ValueError):
    pass


def build_point_in_time_signal_series(code, bars, corporate_actions, facts_date):
    """Create DEC-005 split-adjusted signal OHLCV through the given facts date."""

    missing = sorted(REQUIRED_BAR_COLUMNS - set(bars.columns))
    if missing:
        raise ValueError("Missing raw bar columns: " + ", ".join(missing))
    canonical = "normalization_status" in corporate_actions.columns
    required_action_columns = (
        {"code", "effective_date", "action_type", "split_ratio", "normalization_status"}
        if canonical else REQUIRED_ACTION_COLUMNS
    )
    if not set(corporate_actions.columns).issuperset(required_action_columns):
        missing = sorted(required_action_columns - set(corporate_actions.columns))
        raise ValueError("Missing corporate action columns: " + ", ".join(missing))

    facts_date = pd.Timestamp(facts_date).normalize()
    signal = bars.copy()
    signal["date"] = pd.to_datetime(signal["date"]).dt.normalize()
    signal = signal.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    signal = signal[signal["date"] <= facts_date].copy()
    signal_actions = corporate_actions[
        (corporate_actions["code"].astype(str) == str(code))
        & (corporate_actions["action_type"] == "STOCK_SPLIT")
    ].copy()
    date_column = "effective_date" if canonical else "event_date"
    signal_actions[date_column] = pd.to_datetime(signal_actions[date_column]).dt.normalize()
    signal_actions = signal_actions[signal_actions[date_column] <= facts_date]
    if canonical:
        rejected = signal_actions[signal_actions["normalization_status"] != "READY"]
        if not rejected.empty:
            statuses = ", ".join(sorted(rejected["normalization_status"].astype(str).unique()))
            raise CorporateActionUnknownError(f"canonical action status: {statuses}.")
        split_events = _canonical_split_events(signal_actions)
    else:
        split_events = _validated_split_events(signal_actions)

    price_factors = []
    volume_factors = []
    for bar_date in signal["date"]:
        factor = 1.0
        for event in split_events:
            if bar_date < event["event_date"] <= facts_date:
                factor /= event["split_ratio"]
        price_factors.append(factor)
        volume_factors.append(1.0 / factor)

    signal["signal_open"] = signal["open"].astype(float) * price_factors
    signal["signal_high"] = signal["high"].astype(float) * price_factors
    signal["signal_low"] = signal["low"].astype(float) * price_factors
    signal["signal_close"] = signal["close"].astype(float) * price_factors
    signal["signal_volume"] = signal["volume"].astype(float) * volume_factors
    signal["price_adjustment_factor"] = price_factors
    signal["volume_adjustment_factor"] = volume_factors
    evidence = {
        "applied_split_events": tuple(
            {
                "event_date": event["event_date"].date().isoformat(),
                "split_ratio": event["split_ratio"],
                "numerator": event["numerator"],
                "denominator": event["denominator"],
            }
            for event in split_events
        ),
        "rejected_corporate_action_events": (),
        "cumulative_price_adjustment_factor": float(price_factors[-1]),
        "cumulative_volume_adjustment_factor": float(volume_factors[-1]),
        "corporate_action_status": "READY",
    }
    return signal, evidence


def build_pullback_features(signal_dataframe):
    """Calculate only backward-looking technical evidence on one signal series."""

    featured = signal_dataframe.copy().sort_values("date").reset_index(drop=True)
    featured["MA25"] = featured["signal_close"].rolling(25, min_periods=25).mean()
    featured["MA75"] = featured["signal_close"].rolling(75, min_periods=75).mean()
    featured["MA75_5d_ago"] = featured["MA75"].shift(5)
    featured["Volume20"] = featured["signal_volume"].rolling(20, min_periods=20).mean()
    featured["PullbackLow5"] = featured["signal_low"].rolling(5, min_periods=5).min()
    featured["PreviousClose"] = featured["signal_close"].shift(1)
    featured["PreviousMA25"] = featured["MA25"].shift(1)

    previous_close = featured["signal_close"].shift(1)
    true_range = pd.concat(
        [
            featured["signal_high"] - featured["signal_low"],
            (featured["signal_high"] - previous_close).abs(),
            (featured["signal_low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=False)
    featured["TrueRange"] = true_range
    featured["ATR14"] = _wilder_atr(true_range)
    return featured


def _wilder_atr(true_range):
    atr = pd.Series(float("nan"), index=true_range.index, dtype="float64")
    valid = true_range.dropna()
    if len(valid) < 14:
        return atr
    first_index = valid.index[13]
    atr.loc[first_index] = valid.iloc[:14].mean()
    previous_atr = atr.loc[first_index]
    for index in valid.index[14:]:
        previous_atr = (previous_atr * 13 + valid.loc[index]) / 14
        atr.loc[index] = previous_atr
    return atr


def _validated_split_events(actions):
    events = []
    for record in actions.sort_values("event_date").to_dict("records"):
        numerator = _positive_float(record["numerator"])
        denominator = _positive_float(record["denominator"])
        value = _positive_float(record.get("value"))
        if numerator is None or denominator is None:
            raise CorporateActionUnknownError("split numerator or denominator is missing.")
        ratio = numerator / denominator
        if value is not None and abs(value - ratio) > 1e-10:
            raise CorporateActionUnknownError("split ratio conflicts with numerator/denominator.")
        event = {
            "event_date": pd.Timestamp(record["event_date"]).normalize(),
            "split_ratio": ratio,
            "numerator": numerator,
            "denominator": denominator,
        }
        if events and (event["event_date"] - events[-1]["event_date"]).days <= 5:
            raise CorporateActionUnknownError(
                "multiple split events occur within five calendar days; "
                "effective-date semantics are ambiguous."
            )
        events.append(event)
    return events


def _canonical_split_events(actions):
    events = []
    for record in actions.sort_values("effective_date").to_dict("records"):
        ratio = _positive_float(record.get("split_ratio"))
        if ratio is None:
            raise CorporateActionUnknownError("canonical split ratio is missing.")
        events.append(
            {
                "event_date": pd.Timestamp(record["effective_date"]).normalize(),
                "split_ratio": ratio,
                "numerator": None,
                "denominator": None,
                "canonical_event_id": record.get("canonical_event_id"),
            }
        )
    return events


def _positive_float(value):
    if value is None or pd.isna(value):
        return None
    value = float(value)
    return value if value > 0 else None


def _facts_from_featured(
    code, requested_date, facts_date, manifest, featured, action_evidence,
    canonical_corporate_action_version=None,
):
    current = featured.iloc[-1]
    values = {
        "ma25": _number(current["MA25"]),
        "ma75": _number(current["MA75"]),
        "ma75_5d_ago": _number(current["MA75_5d_ago"]),
        "atr14": _number(current["ATR14"]),
        "volume20": _number(current["Volume20"]),
        "pullback_low_5": _number(current["PullbackLow5"]),
        "previous_close": _number(current["PreviousClose"]),
        "previous_ma25": _number(current["PreviousMA25"]),
    }
    missing = tuple(name for name, value in values.items() if value is None)
    signal_close = _number(current["signal_close"])
    signal_volume = _number(current["signal_volume"])
    volume_ratio = (
        signal_volume / values["volume20"]
        if signal_volume is not None and values["volume20"] not in {None, 0}
        else None
    )
    provisional_stop = (
        values["pullback_low_5"] - 0.5 * values["atr14"]
        if values["pullback_low_5"] is not None and values["atr14"] is not None
        else None
    )
    estimated_risk = (
        signal_close - provisional_stop
        if signal_close is not None and provisional_stop is not None
        else None
    )
    estimated_risk_pct = (
        estimated_risk / signal_close
        if estimated_risk is not None and signal_close not in {None, 0}
        else None
    )
    status = "READY" if not missing else "INSUFFICIENT_HISTORY"
    reasons = () if status == "READY" else ("Insufficient history for: " + ", ".join(missing),)

    def comparison(left, operator, right):
        return None if left is None or right is None else operator(left, right)

    return PullbackFacts(
        code=code,
        requested_date=requested_date,
        facts_date=facts_date,
        dataset_version=manifest.dataset_version,
        data_class=manifest.data_class.value,
        adjustment_policy_version=manifest.adjustment_policy_version,
        canonical_corporate_action_version=canonical_corporate_action_version,
        raw_open=_number(current["open"]), raw_high=_number(current["high"]),
        raw_low=_number(current["low"]), raw_close=_number(current["close"]),
        raw_volume=_number(current["volume"]), signal_open=_number(current["signal_open"]),
        signal_high=_number(current["signal_high"]), signal_low=_number(current["signal_low"]),
        signal_close=signal_close, signal_volume=signal_volume, **values,
        volume_ratio=volume_ratio, provisional_stop=provisional_stop,
        estimated_risk=estimated_risk, estimated_risk_pct=estimated_risk_pct,
        close_above_ma75=comparison(signal_close, lambda a, b: a > b, values["ma75"]),
        ma25_above_ma75=comparison(values["ma25"], lambda a, b: a > b, values["ma75"]),
        ma75_not_lower_than_5d_ago=comparison(values["ma75"], lambda a, b: a >= b, values["ma75_5d_ago"]),
        previous_close_at_or_below_previous_ma25=comparison(values["previous_close"], lambda a, b: a <= b, values["previous_ma25"]),
        current_close_above_current_ma25=comparison(signal_close, lambda a, b: a > b, values["ma25"]),
        current_close_above_previous_close=comparison(signal_close, lambda a, b: a > b, values["previous_close"]),
        current_close_within_3pct_of_ma25=comparison(signal_close, lambda a, b: a <= b * 1.03, values["ma25"]),
        provisional_stop_below_signal_close=comparison(provisional_stop, lambda a, b: a < b, signal_close),
        estimated_risk_within_5pct=(
            None if estimated_risk_pct is None else 0 < estimated_risk_pct <= 0.05
        ),
        applied_split_events=action_evidence["applied_split_events"],
        rejected_corporate_action_events=action_evidence["rejected_corporate_action_events"],
        cumulative_price_adjustment_factor=action_evidence["cumulative_price_adjustment_factor"],
        cumulative_volume_adjustment_factor=action_evidence["cumulative_volume_adjustment_factor"],
        corporate_action_status=action_evidence["corporate_action_status"],
        status=status, missing_fields=missing, unavailable_reasons=reasons,
    )


def _number(value):
    return None if value is None or pd.isna(value) else float(value)


def _canonical_rejections(canonical_actions, code, facts_date):
    if "normalization_status" not in canonical_actions.columns:
        return ()
    actions = canonical_actions[
        (canonical_actions["code"].astype(str) == str(code))
        & (pd.to_datetime(canonical_actions["effective_date"]).dt.normalize() <= facts_date)
        & (canonical_actions["normalization_status"] != "READY")
    ]
    return tuple(
        {
            "canonical_event_id": record["canonical_event_id"],
            "effective_date": str(record["effective_date"]),
            "normalization_status": record["normalization_status"],
            "normalization_reason": record["normalization_reason"],
        }
        for record in actions.sort_values("effective_date").to_dict("records")
    )


def _unavailable_facts(
    code, requested_date, dataset_version, status, reason, facts_date=None,
    data_class=None, adjustment_policy_version=None,
    canonical_corporate_action_version=None,
    rejected_corporate_action_events=(),
    corporate_action_status="NOT_EVALUATED",
):
    return PullbackFacts(
        code=code, requested_date=requested_date, facts_date=facts_date,
        dataset_version=dataset_version, data_class=data_class,
        adjustment_policy_version=adjustment_policy_version,
        canonical_corporate_action_version=canonical_corporate_action_version,
        raw_open=None, raw_high=None, raw_low=None, raw_close=None, raw_volume=None,
        signal_open=None, signal_high=None, signal_low=None, signal_close=None, signal_volume=None,
        ma25=None, ma75=None, ma75_5d_ago=None, atr14=None, volume20=None,
        volume_ratio=None, pullback_low_5=None, previous_close=None, previous_ma25=None,
        close_above_ma75=None, ma25_above_ma75=None, ma75_not_lower_than_5d_ago=None,
        previous_close_at_or_below_previous_ma25=None,
        current_close_above_current_ma25=None, current_close_above_previous_close=None,
        current_close_within_3pct_of_ma25=None, provisional_stop_below_signal_close=None,
        estimated_risk_within_5pct=None, provisional_stop=None, estimated_risk=None,
        estimated_risk_pct=None, applied_split_events=(),
        rejected_corporate_action_events=rejected_corporate_action_events,
        cumulative_price_adjustment_factor=None, cumulative_volume_adjustment_factor=None,
        corporate_action_status=corporate_action_status, status=status,
        missing_fields=(), unavailable_reasons=(reason,),
    )


def _load_dataset(dataset_version, dataset_root):
    path = Path(dataset_root) / dataset_version
    required = [path / name for name in ("bars.parquet", "corporate_actions.parquet", "manifest.json")]
    missing = [str(item.name) for item in required if not item.exists()]
    if missing:
        raise FileNotFoundError("Missing dataset files: " + ", ".join(missing))
    optional = [
        path / "canonical_corporate_actions.parquet",
        path / "corporate_action_manifest.json",
    ]
    watched = required + [item for item in optional if item.exists()]
    cache_key = (
        str(path.resolve()),
        tuple((item.name, item.stat().st_mtime_ns, item.stat().st_size) for item in watched),
    )
    cached = _DATASET_CACHE.get(cache_key)
    if cached is not None:
        return cached
    bars = pd.read_parquet(path / "bars.parquet")
    actions = pd.read_parquet(path / "corporate_actions.parquet")
    manifest = DatasetManifest.from_json((path / "manifest.json").read_text(encoding="utf-8"))
    checksum = calculate_dataset_checksum(bars, actions)
    if checksum != manifest.checksum:
        raise DatasetEligibilityError("manifest checksum mismatch.")
    canonical, canonical_manifest = load_canonical_actions(path)
    if canonical is None:
        canonical, summary = normalize_corporate_actions(bars, actions)
        canonical_version = "in-memory-" + summary["canonical_checksum"].split(":", 1)[1][:16]
    else:
        canonical_version = canonical_manifest["corporate_action_version"]
    dataset = {
        "bars": bars,
        "bars_by_code": {
            str(code): group.copy()
            for code, group in bars.groupby(bars["code"].astype(str), sort=False)
        },
        "corporate_actions": actions,
        "canonical_corporate_actions": canonical,
        "canonical_corporate_action_version": canonical_version,
        "manifest": manifest,
        "checksum": checksum,
    }
    _DATASET_CACHE.clear()
    _DATASET_CACHE[cache_key] = dataset
    return dataset
