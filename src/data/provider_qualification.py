import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pandas as pd
import yaml


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.manifest import (  # noqa: E402
    DataClass,
    assert_historical_market_dataset,
    calculate_checksum,
    create_dataset_manifest,
)
from database.yahoo_provider import YahooProvider  # noqa: E402


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = BASE_DIR / "research" / "provider-qualification"
JQUANTS_CONFIG_PATH = BASE_DIR / "config" / "jquants.yaml"
TEST_CODES = ("7203", "6758")
SUSPICIOUS_GAP_DAYS = 10
SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|token|password|authorization|cookie)"
    r"([=:]\s*)([^\s,;]+)"
)


class QualificationStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    PARTIAL = "PARTIAL"
    UNSUITABLE = "UNSUITABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ProviderUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderFetchResult:
    dataframe: pd.DataFrame
    requested_symbol: str
    actual_symbol: str
    metadata: dict


class YahooQualificationProvider:
    name = "Yahoo"

    def __init__(self):
        self._provider = YahooProvider()

    def fetch_daily(self, code, date_from, date_to):
        requested_symbol = self._provider._to_yahoo_ticker(code)
        payload = self._fetch_chart(requested_symbol, date_from, date_to)
        dataframe = self._provider._to_dataframe(payload)
        if dataframe.empty:
            raise ProviderUnavailableError(
                f"Yahoo returned no daily data for {requested_symbol}."
            )

        result = payload["chart"]["result"][0]
        meta = result.get("meta", {})
        dataframe.insert(0, "code", str(code))
        return ProviderFetchResult(
            dataframe=dataframe,
            requested_symbol=requested_symbol,
            actual_symbol=meta.get("symbol") or requested_symbol,
            metadata={
                "currency": meta.get("currency"),
                "market": meta.get("exchangeName") or meta.get("fullExchangeName"),
                "timezone": meta.get("exchangeTimezoneName")
                or f"gmtoffset:{meta.get('gmtoffset')}",
                "adjustment": {
                    "adjusted_close": _capability(
                        bool(result.get("indicators", {}).get("adjclose"))
                    ),
                    "adjustment_factor": "UNKNOWN",
                    "split": _capability(bool(result.get("events", {}).get("splits"))),
                    "reverse_split": "UNKNOWN",
                    "cash_dividend": _capability(
                        bool(result.get("events", {}).get("dividends"))
                    ),
                    "special_dividend": "UNKNOWN",
                    "symbol_code_change": "UNKNOWN",
                    "delisting": "UNKNOWN",
                },
                "security_master": {
                    "security_name": _capability(
                        bool(meta.get("shortName") or meta.get("longName"))
                    ),
                    "exchange_market": _capability(
                        bool(meta.get("exchangeName") or meta.get("fullExchangeName"))
                    ),
                    "currency": _capability(bool(meta.get("currency"))),
                    "listing_date": "UNKNOWN",
                    "delisting_date": "UNKNOWN",
                    "trading_unit_lot_size": "UNKNOWN",
                    "security_type": _capability(bool(meta.get("instrumentType"))),
                },
            },
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
            raise ProviderUnavailableError(str(error))
        if not payload.get("chart", {}).get("result"):
            raise ProviderUnavailableError("Yahoo returned no chart result.")
        return payload


class JQuantsQualificationProvider:
    name = "J-Quants"

    def __init__(self, api_key=None):
        self._api_key = api_key or _read_jquants_api_key()

    def fetch_daily(self, code, date_from, date_to):
        if not self._api_key:
            raise ProviderUnavailableError("J-Quants API key is not configured.")

        try:
            import jquantsapi
        except ImportError as error:
            raise ProviderUnavailableError("jquants-api-client is not installed.") from error

        client = jquantsapi.ClientV2(api_key=self._api_key)
        bars = client.get_eq_bars_daily(
            code=str(code),
            from_yyyymmdd=date_from.strftime("%Y%m%d"),
            to_yyyymmdd=date_to.strftime("%Y%m%d"),
        )
        if bars.empty:
            raise ProviderUnavailableError(f"J-Quants returned no daily data for {code}.")

        dataframe = _jquants_bars_to_dataframe(bars, code)
        return ProviderFetchResult(
            dataframe=dataframe,
            requested_symbol=str(code),
            actual_symbol=_jquants_actual_symbol(bars, code),
            metadata={
                "currency": None,
                "market": None,
                "timezone": "provider_date_field",
                "adjustment": _jquants_adjustment_capabilities(bars),
                "security_master": {
                    "security_name": "UNKNOWN",
                    "exchange_market": "UNKNOWN",
                    "currency": "UNKNOWN",
                    "listing_date": "UNKNOWN",
                    "delisting_date": "UNKNOWN",
                    "trading_unit_lot_size": "UNKNOWN",
                    "security_type": "UNKNOWN",
                },
            },
        )


def run_qualifications(providers, codes=TEST_CODES, cutoff_date=None):
    cutoff_date = cutoff_date or (date.today() - timedelta(days=7))
    provider_results = []

    for provider in providers:
        try:
            provider_results.append(
                qualify_provider(provider, codes=codes, cutoff_date=cutoff_date)
            )
        except Exception as error:
            provider_results.append(
                {
                    "provider": getattr(provider, "name", provider.__class__.__name__),
                    "status": QualificationStatus.UNAVAILABLE.value,
                    "checks": [],
                    "known_limitations": [sanitize_error(error)],
                }
            )

    return {
        "generated_at": _now_iso(),
        "fixed_cutoff_date": cutoff_date.isoformat(),
        "test_codes": list(codes),
        "providers": provider_results,
        "recommendation": build_recommendation(provider_results),
        "suitability": build_suitability(provider_results),
        "disclaimer": (
            "Qualification evidence is not Production Baseline approval and does not "
            "promote any strategy."
        ),
    }


def qualify_provider(provider, codes, cutoff_date):
    checks = []
    for code in codes:
        checks.append(qualify_code(provider, code, cutoff_date))

    return {
        "provider": provider.name,
        "status": determine_provider_status(checks).value,
        "checks": checks,
        "known_limitations": _provider_limitations(checks),
    }


def qualify_code(provider, code, cutoff_date):
    requested_ranges = {
        "1y": (cutoff_date - timedelta(days=365), cutoff_date),
        "5y": (cutoff_date - timedelta(days=365 * 5), cutoff_date),
        "maximum": (date(1970, 1, 1), cutoff_date),
    }
    coverage = {}
    successful_fetches = {}

    for name, (date_from, date_to) in requested_ranges.items():
        outcome = _timed_fetch(provider, code, date_from, date_to)
        coverage[name] = _coverage_result(date_from, date_to, outcome)
        if outcome["success"]:
            successful_fetches[name] = outcome["result"]

    repeatability = _repeatability_result(provider, code, requested_ranges["1y"])
    primary_result = successful_fetches.get("5y") or successful_fetches.get("1y")
    if primary_result is None:
        return {
            "code": str(code),
            "request_success": False,
            "coverage": coverage,
            "repeatability": repeatability,
            "data_quality": None,
            "adjustment_corporate_actions": None,
            "security_master": None,
            "manifest_trial": None,
            "error_message": _first_error(coverage),
        }

    quality = validate_ohlcv(primary_result.dataframe)
    manifest_trial = run_manifest_trial(primary_result, provider.name)
    return {
        "code": str(code),
        "request_success": True,
        "requested_symbol": primary_result.requested_symbol,
        "actual_symbol": primary_result.actual_symbol,
        "currency": primary_result.metadata.get("currency"),
        "market": primary_result.metadata.get("market"),
        "timezone_date_normalization": primary_result.metadata.get("timezone"),
        "coverage": coverage,
        "repeatability": repeatability,
        "data_quality": quality,
        "adjustment_corporate_actions": primary_result.metadata.get("adjustment"),
        "security_master": primary_result.metadata.get("security_master"),
        "manifest_trial": manifest_trial,
        "error_message": None,
    }


def validate_ohlcv(dataframe):
    required_columns = ["code", "date", "open", "high", "low", "close", "volume"]
    missing_columns = [column for column in required_columns if column not in dataframe.columns]
    if missing_columns:
        return {
            "status": "FAIL",
            "reason": "Missing columns: " + ", ".join(missing_columns),
        }

    frame = dataframe.copy()
    parsed_dates = pd.to_datetime(frame["date"], errors="coerce")
    price_columns = ["open", "high", "low", "close"]
    numeric = frame[price_columns + ["volume"]].apply(pd.to_numeric, errors="coerce")
    duplicate_dates = int(frame.assign(_date=parsed_dates).duplicated(["code", "_date"]).sum())
    out_of_order_rows = 0
    suspicious_long_gaps = 0
    for _, group in frame.assign(_date=parsed_dates).groupby("code", sort=False):
        group_dates = group["_date"]
        out_of_order_rows += int((group_dates.diff().dt.total_seconds() < 0).sum())
        sorted_dates = group_dates.dropna().sort_values().reset_index(drop=True)
        gaps = sorted_dates.diff().dt.days.fillna(0)
        suspicious_long_gaps += int((gaps > SUSPICIOUS_GAP_DAYS).sum())
    missing_ohlc = int(numeric[price_columns].isna().any(axis=1).sum())
    missing_volume = int(numeric["volume"].isna().sum())
    invalid_prices = int((numeric[price_columns] <= 0).any(axis=1).sum())
    invalid_ohlc = int(
        (
            (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1))
            | (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1))
        ).sum()
    )
    negative_volume = int((numeric["volume"] < 0).sum())
    failures = (
        duplicate_dates
        + out_of_order_rows
        + missing_ohlc
        + missing_volume
        + invalid_prices
        + invalid_ohlc
        + negative_volume
    )

    return {
        "status": "PASS" if failures == 0 else "FAIL",
        "row_count": len(frame),
        "duplicate_dates": duplicate_dates,
        "out_of_order_rows": out_of_order_rows,
        "missing_ohlc": missing_ohlc,
        "missing_volume": missing_volume,
        "zero_or_negative_prices": invalid_prices,
        "invalid_ohlc_relationships": invalid_ohlc,
        "negative_volume": negative_volume,
        "suspicious_long_gaps": suspicious_long_gaps,
    }


def compare_repeatability(first, second):
    first_checksum = calculate_checksum(first.dataframe)
    second_checksum = calculate_checksum(second.dataframe)
    first_range = _actual_date_range(first.dataframe)
    second_range = _actual_date_range(second.dataframe)
    passed = (
        len(first.dataframe) == len(second.dataframe)
        and first_checksum == second_checksum
        and first_range == second_range
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "first_row_count": len(first.dataframe),
        "second_row_count": len(second.dataframe),
        "first_checksum": first_checksum,
        "second_checksum": second_checksum,
        "first_date_range": first_range,
        "second_date_range": second_range,
    }


def run_manifest_trial(fetch_result, provider_name):
    try:
        manifest = create_dataset_manifest(
            dataframe=fetch_result.dataframe,
            data_class=DataClass.HISTORICAL_MARKET,
            source=provider_name,
            schema_version="raw-daily-v1",
            adjustment_policy_version="provider-reported-v1",
            creation_context="WO-034 provider qualification trial",
            notes="In-memory qualification trial only. Not formal Benchmark data.",
        )
        assert_historical_market_dataset(
            manifest,
            actual_checksum=calculate_checksum(fetch_result.dataframe),
        )
        return {
            "status": "PASS",
            "dataset_version": manifest.dataset_version,
            "checksum": manifest.checksum,
            "data_class": manifest.data_class.value,
        }
    except Exception as error:
        return {
            "status": "FAIL",
            "error_message": sanitize_error(error),
        }


def determine_provider_status(checks):
    successful_checks = [check for check in checks if check["request_success"]]
    if not successful_checks:
        return QualificationStatus.UNAVAILABLE
    if any(
        check["data_quality"] and check["data_quality"]["status"] == "FAIL"
        for check in successful_checks
    ):
        return QualificationStatus.UNSUITABLE
    if all(
        check["coverage"].get("5y", {}).get("success")
        and check["repeatability"].get("status") == "PASS"
        for check in successful_checks
    ):
        return QualificationStatus.PARTIAL
    return QualificationStatus.PARTIAL


def build_recommendation(provider_results):
    candidates = [
        result
        for result in provider_results
        if result["status"] in {
            QualificationStatus.QUALIFIED.value,
            QualificationStatus.PARTIAL.value,
        }
    ]
    primary = candidates[0]["provider"] if candidates else None
    fallback = candidates[1]["provider"] if len(candidates) > 1 else None
    rejected = [
        result["provider"]
        for result in provider_results
        if result["status"] in {
            QualificationStatus.UNAVAILABLE.value,
            QualificationStatus.UNSUITABLE.value,
        }
    ]
    return {
        "primary_candidate": primary,
        "secondary_fallback_candidate": fallback,
        "rejected_or_unavailable": rejected,
        "approval_status": "Recommendation only. Product Review is required.",
    }


def build_suitability(provider_results):
    pipeline_providers = [
        result["provider"]
        for result in provider_results
        if result["status"]
        in {QualificationStatus.QUALIFIED.value, QualificationStatus.PARTIAL.value}
    ]
    preliminary_providers = [
        result["provider"]
        for result in provider_results
        if result["status"] == QualificationStatus.PARTIAL.value
    ]
    return {
        "pipeline_development": pipeline_providers,
        "preliminary_replay": preliminary_providers,
        "production_baseline_approval": [],
        "note": (
            "Provider qualification alone never permits Production Baseline approval. "
            "Historical dataset versioning, corporate-action coverage, and Product Review "
            "remain required."
        ),
    }


def write_qualification_reports(report, output_dir=DEFAULT_OUTPUT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "qualification.json"
    readme_path = output_dir / "README.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readme_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, readme_path


def render_markdown_report(report):
    lines = [
        "# Provider Qualification",
        "",
        f"Executed at: {report['generated_at']}",
        "",
        f"Fixed cutoff date: {report['fixed_cutoff_date']}",
        "",
        "Test codes: " + ", ".join(report["test_codes"]),
        "",
        "## Providers",
        "",
        "| Provider | Status | 1Y / 5Y / Maximum | Repeatability | Data Quality |",
        "| --- | --- | --- | --- | --- |",
    ]
    for provider in report["providers"]:
        checks = provider["checks"]
        coverage = "; ".join(
            f"{check['code']}: "
            f"{_coverage_label(check.get('coverage', {}), '1y')}/"
            f"{_coverage_label(check.get('coverage', {}), '5y')}/"
            f"{_coverage_label(check.get('coverage', {}), 'maximum')}"
            for check in checks
        ) or "No successful request"
        repeatability = "; ".join(
            f"{check['code']}: {check.get('repeatability', {}).get('status', 'UNKNOWN')}"
            for check in checks
        ) or "UNKNOWN"
        quality = "; ".join(
            f"{check['code']}: "
            f"{(check.get('data_quality') or {}).get('status', 'UNKNOWN')}"
            for check in checks
        ) or "UNKNOWN"
        lines.append(
            f"| {provider['provider']} | {provider['status']} | {coverage} | "
            f"{repeatability} | {quality} |"
        )

    lines.extend(["", "## Details", ""])
    for provider in report["providers"]:
        lines.extend([f"### {provider['provider']}", ""])
        for check in provider["checks"]:
            lines.extend(
                [
                    f"#### {check['code']}",
                    "",
                    f"Request success: {check['request_success']}",
                    "",
                    f"Error: {check.get('error_message') or 'None'}",
                    "",
                    "Adjustment / Corporate Actions: "
                    + json.dumps(
                        check.get("adjustment_corporate_actions"),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "",
                    "Security Master: "
                    + json.dumps(
                        check.get("security_master"),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "",
                ]
            )

    recommendation = report["recommendation"]
    suitability = report["suitability"]
    lines.extend(
        [
            "## Recommendation",
            "",
            f"Primary Candidate: {recommendation['primary_candidate'] or 'None'}",
            "",
            "Secondary/Fallback Candidate: "
            + (recommendation["secondary_fallback_candidate"] or "None"),
            "",
            "Rejected/Unavailable: "
            + ", ".join(recommendation["rejected_or_unavailable"]),
            "",
            "Known limitations: Provider qualification is not Production Baseline approval. "
            "Corporate-action completeness, Security Master coverage, and formal data "
            "version preservation remain separate requirements.",
            "",
        ]
    )
    lines.extend(
        [
            "## Intended Use",
            "",
            "Suitable for pipeline development: "
            + ", ".join(suitability["pipeline_development"]),
            "",
            "Suitable for preliminary replay: "
            + ", ".join(suitability["preliminary_replay"]),
            "",
            "Suitable for Production Baseline approval: None",
            "",
            suitability["note"],
            "",
        ]
    )
    return "\n".join(lines)


def sanitize_error(error):
    message = f"{error.__class__.__name__}: {error}"
    return SENSITIVE_VALUE_PATTERN.sub(r"\1\2<redacted>", message)


def main():
    parser = argparse.ArgumentParser(description="Qualify historical market data providers.")
    provider_group = parser.add_mutually_exclusive_group()
    provider_group.add_argument("--provider", choices=["yahoo", "jquants"])
    provider_group.add_argument("--all", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    providers = _selected_providers(args.provider)
    report = run_qualifications(providers)
    json_path, readme_path = write_qualification_reports(report, args.output_dir)
    print(f"Qualification JSON: {json_path}")
    print(f"Qualification README: {readme_path}")
    for provider in report["providers"]:
        print(f"{provider['provider']}: {provider['status']}")


def _selected_providers(provider_name):
    providers = {
        "yahoo": YahooQualificationProvider,
        "jquants": JQuantsQualificationProvider,
    }
    if provider_name:
        return [providers[provider_name]()]
    return [YahooQualificationProvider(), JQuantsQualificationProvider()]


def _timed_fetch(provider, code, date_from, date_to):
    started = time.perf_counter()
    try:
        result = provider.fetch_daily(code, date_from, date_to)
        return {
            "success": True,
            "result": result,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as error:
        return {
            "success": False,
            "error_message": sanitize_error(error),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def _coverage_result(date_from, date_to, outcome):
    result = {
        "requested_date_from": date_from.isoformat(),
        "requested_date_to": date_to.isoformat(),
        "request_duration_ms": outcome["duration_ms"],
        "success": outcome["success"],
    }
    if not outcome["success"]:
        result["error_message"] = outcome["error_message"]
        return result

    fetched = outcome["result"]
    result.update(
        {
            "requested_symbol": fetched.requested_symbol,
            "actual_symbol": fetched.actual_symbol,
            "row_count": len(fetched.dataframe),
            "actual_date_range": _actual_date_range(fetched.dataframe),
            "checksum": calculate_checksum(fetched.dataframe),
        }
    )
    return result


def _repeatability_result(provider, code, requested_range):
    first = _timed_fetch(provider, code, *requested_range)
    second = _timed_fetch(provider, code, *requested_range)
    if not first["success"] or not second["success"]:
        return {
            "status": "FAIL",
            "error_message": first.get("error_message") or second.get("error_message"),
        }
    return compare_repeatability(first["result"], second["result"])


def _actual_date_range(dataframe):
    dates = pd.to_datetime(dataframe["date"], errors="coerce").dropna()
    if dates.empty:
        return {"date_from": None, "date_to": None}
    return {
        "date_from": dates.min().date().isoformat(),
        "date_to": dates.max().date().isoformat(),
    }


def _provider_limitations(checks):
    limitations = []
    for check in checks:
        if not check["request_success"]:
            limitations.append(f"{check['code']}: {check['error_message']}")
        elif not check["coverage"]["5y"]["success"]:
            limitations.append(f"{check['code']}: 5-year coverage was unavailable.")
    return limitations


def _first_error(coverage):
    for result in coverage.values():
        if result.get("error_message"):
            return result["error_message"]
    return "No successful provider response."


def _coverage_label(coverage, name):
    result = coverage.get(name, {})
    if not result.get("success"):
        return "FAIL"
    actual = result.get("actual_date_range", {})
    return f"{actual.get('date_from')}..{actual.get('date_to')}"


def _jquants_bars_to_dataframe(bars, code):
    aliases = {
        "date": ["Date", "date"],
        "open": ["Open", "open", "O"],
        "high": ["High", "high", "H"],
        "low": ["Low", "low", "L"],
        "close": ["Close", "close", "C"],
        "volume": ["Volume", "volume", "Vo"],
    }
    output = {"code": [str(code)] * len(bars)}
    for target, candidates in aliases.items():
        source = next((column for column in candidates if column in bars.columns), None)
        if source is None:
            raise ProviderUnavailableError(
                f"J-Quants daily bars are missing {target}."
            )
        output[target] = bars[source].tolist()
    return pd.DataFrame(output)


def _jquants_actual_symbol(bars, code):
    if "Code" not in bars.columns or bars.empty:
        return str(code)
    return str(bars.iloc[0]["Code"])


def _jquants_adjustment_capabilities(bars):
    columns = set(bars.columns)
    return {
        "adjusted_close": _capability(
            bool({"AdjustmentClose", "AdjustedClose"} & columns)
        ),
        "adjustment_factor": _capability("AdjustmentFactor" in columns),
        "split": "UNKNOWN",
        "reverse_split": "UNKNOWN",
        "cash_dividend": "UNKNOWN",
        "special_dividend": "UNKNOWN",
        "symbol_code_change": "UNKNOWN",
        "delisting": "UNKNOWN",
    }


def _read_jquants_api_key():
    environment_value = os.getenv("JQUANTS_API_KEY")
    if environment_value and environment_value.strip():
        return environment_value.strip()
    if not JQUANTS_CONFIG_PATH.exists():
        return None
    with JQUANTS_CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}
    value = config.get("api_key")
    return str(value).strip() if value else None


def _capability(available):
    return "AVAILABLE" if available else "UNKNOWN"


def _unix_timestamp(value):
    return int(datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc).timestamp())


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
