import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pandas as pd


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.manifest import (  # noqa: E402
    DataClass,
    DatasetManifest,
    assert_historical_market_dataset,
    calculate_dataset_checksum,
    create_dataset_manifest,
)
from data.provider_qualification import validate_ohlcv  # noqa: E402
from database.yahoo_provider import YahooProvider  # noqa: E402


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_ROOT = BASE_DIR / "data" / "raw" / "versioned"
BAR_COLUMNS = [
    "code",
    "market",
    "date",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "currency",
    "source",
    "source_symbol",
    "fetched_at",
    "schema_version",
]
CORPORATE_ACTION_COLUMNS = [
    "code",
    "market",
    "event_date",
    "action_type",
    "value",
    "numerator",
    "denominator",
    "currency",
    "source",
    "fetched_at",
    "raw_reference",
]
RAW_SCHEMA_VERSION = "raw-daily-v1"
ADJUSTMENT_POLICY_VERSION = "RAW_WITH_PROVIDER_ADJCLOSE_AND_EVENTS_V1"


class IngestionError(RuntimeError):
    pass


class DataQualityError(IngestionError):
    pass


@dataclass(frozen=True)
class HistoricalFetch:
    bars: pd.DataFrame
    corporate_actions: pd.DataFrame
    requested_symbol: str
    actual_symbol: str


@dataclass(frozen=True)
class IngestionResult:
    status: str
    dataset_version: str
    dataset_path: Path
    manifest: DatasetManifest
    coverage: dict
    quality: dict


class YahooHistoricalProvider:
    name = "yahoo"

    def __init__(self):
        self._provider = YahooProvider()

    def fetch_history(self, code, date_from, date_to, fetched_at):
        requested_symbol = self._provider._to_yahoo_ticker(code)
        payload = self._fetch_chart(requested_symbol, date_from, date_to)
        result = payload["chart"]["result"][0]
        meta = result.get("meta", {})
        market_timezone = timezone(timedelta(seconds=meta.get("gmtoffset", 0)))
        source_symbol = meta.get("symbol") or requested_symbol
        market = meta.get("exchangeName") or meta.get("fullExchangeName")
        currency = meta.get("currency")
        timestamps = result.get("timestamp") or []
        quote_data = result.get("indicators", {}).get("quote", [{}])[0]
        adjusted = result.get("indicators", {}).get("adjclose", [{}])[0]
        adjusted_values = adjusted.get("adjclose", [])
        bars = []

        for index, timestamp in enumerate(timestamps):
            close = self._at(quote_data, "close", index)
            if close is None:
                continue
            bars.append(
                {
                    "code": str(code),
                    "market": market,
                    "date": datetime.fromtimestamp(
                        timestamp,
                        market_timezone,
                    ).date().isoformat(),
                    "open": self._at(quote_data, "open", index),
                    "high": self._at(quote_data, "high", index),
                    "low": self._at(quote_data, "low", index),
                    "close": close,
                    "adjusted_close": self._at_values(adjusted_values, index),
                    "volume": self._at(quote_data, "volume", index),
                    "currency": currency,
                    "source": self.name,
                    "source_symbol": source_symbol,
                    "fetched_at": fetched_at,
                    "schema_version": RAW_SCHEMA_VERSION,
                }
            )

        if not bars:
            raise IngestionError(f"Yahoo returned no daily bars for {requested_symbol}.")

        actions = _yahoo_corporate_actions(
            result=result,
            code=str(code),
            market=market,
            currency=currency,
            source_symbol=source_symbol,
            fetched_at=fetched_at,
            market_timezone=market_timezone,
        )
        return HistoricalFetch(
            bars=pd.DataFrame(bars, columns=BAR_COLUMNS),
            corporate_actions=actions,
            requested_symbol=requested_symbol,
            actual_symbol=source_symbol,
        )

    def _fetch_chart(self, symbol, date_from, date_to):
        params = urlencode(
            {
                "period1": _unix_timestamp(date_from),
                "period2": _unix_timestamp(date_to + timedelta(days=1)),
                "interval": "1d",
                "events": "div,splits",
            }
        )
        url = f"{self._provider.BASE_URL}/{quote(symbol, safe='')}?{params}"
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        error = payload.get("chart", {}).get("error")
        if error:
            raise IngestionError(str(error))
        if not payload.get("chart", {}).get("result"):
            raise IngestionError("Yahoo returned no chart result.")
        return payload

    def _at(self, values, field, index):
        return self._at_values(values.get(field, []), index)

    def _at_values(self, values, index):
        return values[index] if index < len(values) else None


def ingest_historical_dataset(
    provider,
    symbols,
    date_from,
    date_to,
    output_root=DEFAULT_DATASET_ROOT,
    creation_context="WO-035 versioned historical ingestion",
):
    symbols = tuple(sorted(str(symbol) for symbol in symbols))
    if not symbols:
        raise IngestionError("At least one symbol is required.")
    fetched_at = _now_iso()
    fetches = [
        provider.fetch_history(symbol, date_from, date_to, fetched_at)
        for symbol in symbols
    ]
    bars = pd.concat([fetch.bars for fetch in fetches], ignore_index=True)
    action_records = [
        record
        for fetch in fetches
        for record in fetch.corporate_actions.to_dict("records")
    ]
    actions = pd.DataFrame(action_records, columns=CORPORATE_ACTION_COLUMNS)
    bars = bars.sort_values(["code", "date"]).reset_index(drop=True)
    actions = actions.sort_values(["code", "event_date", "action_type"]).reset_index(
        drop=True
    )
    quality = build_quality_report(bars, actions)
    if quality["overall_status"] == "FAIL":
        raise DataQualityError("Historical dataset quality validation failed.")

    checksum = calculate_dataset_checksum(bars, actions)
    manifest = create_dataset_manifest(
        dataframe=bars,
        data_class=DataClass.HISTORICAL_MARKET,
        source=provider.name,
        schema_version=RAW_SCHEMA_VERSION,
        adjustment_policy_version=ADJUSTMENT_POLICY_VERSION,
        creation_context=creation_context,
        notes=(
            f"corporate_action_row_count={len(actions)}; "
            "Preliminary pipeline-development dataset. Raw OHLC is unadjusted; "
            "adjusted_close and corporate actions are provider evidence only."
        ),
        fetched_at=fetched_at,
        content_checksum=checksum,
    )
    assert_historical_market_dataset(manifest, actual_checksum=checksum)
    quality["checksum_validation"] = "PASS"
    quality["manifest_validation"] = "PASS"
    coverage = build_coverage_report(fetches, bars, actions, date_from, date_to)
    return _commit_versioned_dataset(
        bars=bars,
        actions=actions,
        manifest=manifest,
        coverage=coverage,
        quality=quality,
        output_root=output_root,
    )


def load_versioned_dataset(dataset_version, output_root=DEFAULT_DATASET_ROOT):
    dataset_path = Path(output_root) / dataset_version
    required_paths = {
        "bars": dataset_path / "bars.parquet",
        "corporate_actions": dataset_path / "corporate_actions.parquet",
        "manifest": dataset_path / "manifest.json",
        "coverage": dataset_path / "coverage.json",
        "quality": dataset_path / "quality.json",
    }
    missing = [name for name, path in required_paths.items() if not path.exists()]
    if missing:
        raise IngestionError(
            f"Dataset {dataset_version} is incomplete: missing " + ", ".join(missing)
        )
    bars = pd.read_parquet(required_paths["bars"])
    actions = pd.read_parquet(required_paths["corporate_actions"])
    manifest = DatasetManifest.from_json(
        required_paths["manifest"].read_text(encoding="utf-8")
    )
    checksum = calculate_dataset_checksum(bars, actions)
    try:
        assert_historical_market_dataset(manifest, actual_checksum=checksum)
    except Exception as error:
        raise IngestionError(
            f"Dataset {dataset_version} failed manifest checksum validation."
        ) from error
    return {
        "bars": bars,
        "corporate_actions": actions,
        "manifest": manifest,
        "coverage": json.loads(required_paths["coverage"].read_text(encoding="utf-8")),
        "quality": json.loads(required_paths["quality"].read_text(encoding="utf-8")),
        "dataset_path": dataset_path,
    }


def build_coverage_report(fetches, bars, actions, date_from, date_to):
    coverage = {
        "requested_date_from": date_from.isoformat(),
        "requested_date_to": date_to.isoformat(),
        "codes": {},
        "gap_interpretation": "Observed calendar gaps only; no exchange calendar is inferred.",
    }
    fetch_by_code = {str(fetch.bars.iloc[0]["code"]): fetch for fetch in fetches}
    for code, group in bars.groupby("code", sort=True):
        ordered = group.sort_values("date")
        dates = pd.to_datetime(ordered["date"])
        gaps = dates.diff().dt.days.dropna()
        code_actions = actions[actions["code"] == code]
        fetch = fetch_by_code[str(code)]
        coverage["codes"][str(code)] = {
            "requested_symbol": fetch.requested_symbol,
            "actual_symbol": fetch.actual_symbol,
            "requested_date_from": date_from.isoformat(),
            "requested_date_to": date_to.isoformat(),
            "actual_date_from": dates.min().date().isoformat(),
            "actual_date_to": dates.max().date().isoformat(),
            "row_count": len(ordered),
            "missing_adjusted_close_count": int(ordered["adjusted_close"].isna().sum()),
            "corporate_action_count": len(code_actions),
            "duplicate_date_count": int(dates.duplicated().sum()),
            "longest_observed_calendar_gap_days": int(gaps.max()) if not gaps.empty else 0,
            "first_available_bar": dates.min().date().isoformat(),
            "last_available_bar": dates.max().date().isoformat(),
        }
    return coverage


def build_quality_report(bars, actions):
    ohlcv = validate_ohlcv(bars)
    invalid_actions = _invalid_corporate_action_count(actions)
    missing_adjusted_close = int(bars["adjusted_close"].isna().sum())
    limitations = []
    if missing_adjusted_close:
        limitations.append(
            f"adjusted_close is missing for {missing_adjusted_close} raw bars."
        )

    overall_status = "PASS"
    if ohlcv["status"] == "FAIL" or invalid_actions:
        overall_status = "FAIL"
    elif limitations:
        overall_status = "PASS_WITH_LIMITATIONS"

    return {
        "overall_status": overall_status,
        "duplicate_rows": ohlcv["duplicate_dates"],
        "out_of_order_rows": ohlcv["out_of_order_rows"],
        "invalid_ohlc_rows": ohlcv["invalid_ohlc_relationships"],
        "zero_or_negative_price_rows": ohlcv["zero_or_negative_prices"],
        "negative_volume_rows": ohlcv["negative_volume"],
        "missing_ohlc_rows": ohlcv["missing_ohlc"],
        "missing_volume_rows": ohlcv["missing_volume"],
        "missing_adjusted_close_rows": missing_adjusted_close,
        "invalid_corporate_action_rows": invalid_actions,
        "checksum_validation": "PENDING",
        "manifest_validation": "PENDING",
        "limitations": limitations,
    }


def _commit_versioned_dataset(
    bars,
    actions,
    manifest,
    coverage,
    quality,
    output_root,
):
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    dataset_path = output_root / manifest.dataset_version
    if dataset_path.exists():
        existing = load_versioned_dataset(manifest.dataset_version, output_root)
        if existing["manifest"].checksum != manifest.checksum:
            raise IngestionError(
                f"Dataset version collision for {manifest.dataset_version}."
            )
        return IngestionResult(
            status="ALREADY_EXISTS",
            dataset_version=manifest.dataset_version,
            dataset_path=dataset_path,
            manifest=existing["manifest"],
            coverage=existing["coverage"],
            quality=existing["quality"],
        )

    temporary_path = Path(
        tempfile.mkdtemp(prefix=".ingestion-", dir=output_root.parent)
    )
    try:
        _write_dataset_files(
            temporary_path,
            bars,
            actions,
            manifest,
            coverage,
            quality,
        )
        temporary_path.replace(dataset_path)
    except Exception:
        shutil.rmtree(temporary_path, ignore_errors=True)
        raise

    return IngestionResult(
        status="CREATED",
        dataset_version=manifest.dataset_version,
        dataset_path=dataset_path,
        manifest=manifest,
        coverage=coverage,
        quality=quality,
    )


def _write_dataset_files(directory, bars, actions, manifest, coverage, quality):
    bars.to_parquet(directory / "bars.parquet", index=False)
    actions.to_parquet(directory / "corporate_actions.parquet", index=False)
    (directory / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    (directory / "coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (directory / "quality.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _yahoo_corporate_actions(
    result,
    code,
    market,
    currency,
    source_symbol,
    fetched_at,
    market_timezone,
):
    rows = []
    events = result.get("events", {})
    for event_key, event in (events.get("dividends") or {}).items():
        event_date = _event_date(event, event_key, market_timezone)
        rows.append(
            {
                "code": code,
                "market": market,
                "event_date": event_date,
                "action_type": "CASH_DIVIDEND",
                "value": event.get("amount"),
                "numerator": None,
                "denominator": None,
                "currency": currency,
                "source": "yahoo",
                "fetched_at": fetched_at,
                "raw_reference": f"{source_symbol}:dividend:{event_key}",
            }
        )
    for event_key, event in (events.get("splits") or {}).items():
        event_date = _event_date(event, event_key, market_timezone)
        rows.append(
            {
                "code": code,
                "market": market,
                "event_date": event_date,
                "action_type": "STOCK_SPLIT",
                "value": _split_value(event.get("numerator"), event.get("denominator")),
                "numerator": event.get("numerator"),
                "denominator": event.get("denominator"),
                "currency": currency,
                "source": "yahoo",
                "fetched_at": fetched_at,
                "raw_reference": f"{source_symbol}:split:{event_key}",
            }
        )
    return pd.DataFrame(rows, columns=CORPORATE_ACTION_COLUMNS)


def _event_date(event, event_key, market_timezone):
    timestamp = event.get("date", event_key)
    return datetime.fromtimestamp(int(timestamp), market_timezone).date().isoformat()


def _split_value(numerator, denominator):
    if numerator is None or denominator in {None, 0}:
        return None
    return float(numerator) / float(denominator)


def _invalid_corporate_action_count(actions):
    if actions.empty:
        return 0
    invalid = (
        actions["code"].isna()
        | actions["event_date"].isna()
        | actions["action_type"].isna()
        | ~actions["action_type"].isin({"CASH_DIVIDEND", "STOCK_SPLIT"})
    )
    return int(invalid.sum())


def _unix_timestamp(value):
    return int(datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc).timestamp())


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description="Ingest a versioned historical dataset.")
    parser.add_argument("--provider", choices=["yahoo"], required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--max-history", action="store_true")
    parser.add_argument("--cutoff-date", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_DATASET_ROOT))
    args = parser.parse_args()

    if not args.max_history:
        raise SystemExit("--max-history is required for WO-035 ingestion.")

    cutoff_date = datetime.strptime(args.cutoff_date, "%Y-%m-%d").date()
    provider = YahooHistoricalProvider()
    result = ingest_historical_dataset(
        provider=provider,
        symbols=args.symbols,
        date_from=datetime(1970, 1, 1).date(),
        date_to=cutoff_date,
        output_root=args.output_root,
        creation_context=(
            "WO-035 --provider yahoo --symbols "
            + " ".join(sorted(args.symbols))
            + f" --max-history --cutoff-date {args.cutoff_date}"
        ),
    )
    print(f"Status: {result.status}")
    print(f"Dataset Version: {result.dataset_version}")
    print(f"Dataset Path: {result.dataset_path}")


if __name__ == "__main__":
    main()
