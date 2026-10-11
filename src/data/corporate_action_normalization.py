"""Deterministic, conservative normalization for Yahoo corporate-action evidence."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import sys

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from data.historical_ingestion import DEFAULT_DATASET_ROOT, load_versioned_dataset
else:
    from .historical_ingestion import DEFAULT_DATASET_ROOT, load_versioned_dataset


NORMALIZATION_POLICY_VERSION = "YAHOO_CA_NORMALIZATION_V1"
CANONICAL_SCHEMA_VERSION = "canonical-corporate-actions-v1"
CANONICAL_FILENAME = "canonical_corporate_actions.parquet"
MANIFEST_FILENAME = "corporate_action_manifest.json"
CANONICAL_COLUMNS = [
    "canonical_event_id", "code", "market", "effective_date", "action_type",
    "split_ratio", "currency", "source", "raw_reference_count", "raw_references",
    "normalization_status", "normalization_reason", "confidence",
    "original_event_count", "observed_price_ratio", "expected_price_ratio",
    "observed_volume_ratio", "sanity_status", "limitation", "schema_version",
]


def normalize_split_ratio(raw_event):
    numerator = _positive_number(raw_event.get("numerator"))
    denominator = _positive_number(raw_event.get("denominator"))
    value = _positive_number(raw_event.get("value"))
    if numerator is None or denominator is None:
        return None, "INVALID_RATIO", "numerator or denominator is missing"
    ratio = numerator / denominator
    if value is not None and abs(value - ratio) > 1e-10:
        return None, "INVALID_RATIO", "value conflicts with numerator/denominator"
    return ratio, "READY", "ratio uses new_shares / old_shares"


def normalize_corporate_actions(bars, raw_actions):
    """Return canonical split rows plus a deterministic normalization summary."""

    actions = raw_actions.copy()
    splits = actions[actions["action_type"] == "STOCK_SPLIT"].copy()
    if splits.empty:
        canonical = pd.DataFrame(columns=CANONICAL_COLUMNS)
        return canonical, _summary(canonical, actions, calculate_canonical_checksum(canonical))

    splits["effective_date"] = pd.to_datetime(splits["event_date"]).dt.normalize()
    provisional = []
    for (code, date), group in splits.groupby(["code", "effective_date"], sort=True):
        parsed = [normalize_split_ratio(record) for record in group.to_dict("records")]
        ratios = {result[0] for result in parsed if result[0] is not None}
        invalid = [result for result in parsed if result[1] != "READY"]
        if invalid:
            provisional.append(_canonical_row(group, None, "INVALID_RATIO", invalid[0][2]))
        elif len(ratios) != 1:
            provisional.append(_canonical_row(group, None, "CONFLICT", "same-date split ratios conflict"))
        else:
            status = "READY"
            reason = "single confirmed split event"
            if len(group) > 1:
                status = "READY"
                reason = "EXACT_DUPLICATE merged with preserved raw references"
            provisional.append(_canonical_row(group, ratios.pop(), status, reason))

    canonical = pd.DataFrame(provisional, columns=CANONICAL_COLUMNS)
    canonical = _mark_near_date_duplicates(canonical)
    canonical = _add_sanity_evidence(canonical, bars)
    canonical = canonical.sort_values(["code", "effective_date", "canonical_event_id"]).reset_index(drop=True)
    canonical["effective_date"] = pd.to_datetime(canonical["effective_date"]).dt.date.astype(str)
    checksum = calculate_canonical_checksum(canonical)
    return canonical, _summary(canonical, actions, checksum)


def normalize_dataset(dataset_version, output_root=DEFAULT_DATASET_ROOT):
    dataset = load_versioned_dataset(dataset_version, output_root)
    canonical, summary = normalize_corporate_actions(
        dataset["bars"], dataset["corporate_actions"]
    )
    canonical_checksum = summary["canonical_checksum"]
    corporate_action_version = "ca-v1-" + sha256(
        (dataset_version + NORMALIZATION_POLICY_VERSION + canonical_checksum).encode("utf-8")
    ).hexdigest()[:16]
    composite = "sha256:" + sha256(
        (dataset["manifest"].checksum + canonical_checksum).encode("utf-8")
    ).hexdigest()
    manifest = {
        "dataset_version": dataset_version,
        "corporate_action_version": corporate_action_version,
        "corporate_action_schema_version": CANONICAL_SCHEMA_VERSION,
        "normalization_policy_version": NORMALIZATION_POLICY_VERSION,
        "canonical_corporate_action_checksum": canonical_checksum,
        "composite_dataset_fingerprint": composite,
        "raw_corporate_action_checksum": dataset["manifest"].checksum,
        "summary": summary,
    }
    _write_canonical_sidecar(dataset["dataset_path"], canonical, manifest)
    return canonical, manifest


def load_canonical_actions(dataset_path):
    dataset_path = Path(dataset_path)
    canonical_path = dataset_path / CANONICAL_FILENAME
    manifest_path = dataset_path / MANIFEST_FILENAME
    if not canonical_path.exists() or not manifest_path.exists():
        return None, None
    canonical = pd.read_parquet(canonical_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if calculate_canonical_checksum(canonical) != manifest.get("canonical_corporate_action_checksum"):
        raise ValueError("CHECKSUM_MISMATCH for canonical corporate actions.")
    return canonical, manifest


def calculate_canonical_checksum(canonical):
    records = canonical.to_dict("records")
    normalized = sorted(
        [
            {
                key: "" if value is None or pd.isna(value) else str(value)
                for key, value in record.items()
            }
            for record in records
        ],
        key=lambda record: json.dumps(record, sort_keys=True, separators=(",", ":")),
    )
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def _canonical_row(group, ratio, status, reason):
    first = group.iloc[0]
    references = tuple(sorted(str(value) for value in group["raw_reference"]))
    date = pd.Timestamp(first["effective_date"]).date().isoformat()
    event_id = "cae-" + sha256(
        (str(first["code"]) + date + str(ratio) + "|".join(references)).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "canonical_event_id": event_id,
        "code": str(first["code"]), "market": first.get("market"),
        "effective_date": first["effective_date"], "action_type": "STOCK_SPLIT",
        "split_ratio": ratio, "currency": first.get("currency"), "source": first.get("source"),
        "raw_reference_count": len(references), "raw_references": json.dumps(references),
        "normalization_status": status, "normalization_reason": reason,
        "confidence": "HIGH" if status == "READY" else "LOW",
        "original_event_count": len(group), "observed_price_ratio": None,
        "expected_price_ratio": None, "observed_volume_ratio": None,
        "sanity_status": "NOT_CHECKED", "limitation": None,
        "schema_version": CANONICAL_SCHEMA_VERSION,
    }


def _mark_near_date_duplicates(canonical):
    canonical = canonical.copy()
    for _, group in canonical.groupby("code", sort=False):
        group = group.sort_values("effective_date")
        previous_index = None
        for index, row in group.iterrows():
            if previous_index is not None:
                previous = canonical.loc[previous_index]
                date_gap = (pd.Timestamp(row["effective_date"]) - pd.Timestamp(previous["effective_date"])).days
                if date_gap <= 3:
                    if row["split_ratio"] == previous["split_ratio"]:
                        for target in (index, previous_index):
                            canonical.loc[target, "normalization_status"] = "AMBIGUOUS_DUPLICATE"
                            canonical.loc[target, "normalization_reason"] = (
                                "NEAR_DATE_POSSIBLE_DUPLICATE: same ratio without timezone proof"
                            )
                            canonical.loc[target, "confidence"] = "LOW"
                    else:
                        for target in (index, previous_index):
                            canonical.loc[target, "normalization_status"] = "CONFLICT"
                            canonical.loc[target, "normalization_reason"] = "near-date split ratios conflict"
                            canonical.loc[target, "confidence"] = "LOW"
            previous_index = index
    return canonical


def _add_sanity_evidence(canonical, bars):
    canonical = canonical.copy()
    local_bars = bars.copy()
    local_bars["date"] = pd.to_datetime(local_bars["date"]).dt.normalize()
    for index, event in canonical.iterrows():
        if event["normalization_status"] != "READY":
            continue
        if event["split_ratio"] is None or pd.isna(event["split_ratio"]):
            continue
        event_date = pd.Timestamp(event["effective_date"]).normalize()
        code_bars = local_bars[local_bars["code"].astype(str) == str(event["code"])]
        before = code_bars[code_bars["date"] < event_date].sort_values("date")
        after = code_bars[code_bars["date"] >= event_date].sort_values("date")
        if before.empty or after.empty:
            canonical.loc[index, "sanity_status"] = "INSUFFICIENT_BARS"
            canonical.loc[index, "limitation"] = "no adjacent raw bars"
            continue
        pre = before.iloc[-1]
        post = after.iloc[0]
        price_ratio = float(post["close"]) / float(pre["close"])
        volume_ratio = float(post["volume"]) / float(pre["volume"])
        expected_price = 1.0 / float(event["split_ratio"])
        expected_volume = float(event["split_ratio"])
        canonical.loc[index, "observed_price_ratio"] = price_ratio
        canonical.loc[index, "expected_price_ratio"] = expected_price
        canonical.loc[index, "observed_volume_ratio"] = volume_ratio
        # Broad bands permit ordinary market movement but reject clearly unadjusted-scale contradictions.
        price_ok = expected_price * 0.5 <= price_ratio <= expected_price * 1.5
        volume_ok = expected_volume * 0.1 <= volume_ratio <= expected_volume * 10.0
        if price_ok and volume_ok:
            canonical.loc[index, "sanity_status"] = "PASS"
            canonical.loc[index, "limitation"] = "sanity evidence only; not proof of event timing"
        else:
            canonical.loc[index, "normalization_status"] = "AMBIGUOUS_EFFECTIVE_DATE"
            canonical.loc[index, "normalization_reason"] = (
                "raw OHLCV scale conflicts with the reported split ratio"
            )
            canonical.loc[index, "confidence"] = "LOW"
            canonical.loc[index, "sanity_status"] = "CONFLICT"
            canonical.loc[index, "limitation"] = "Yahoo quote series may already be split adjusted"
    return canonical


def _summary(canonical, raw_actions, checksum):
    statuses = canonical.get("normalization_status", pd.Series(dtype=str))
    return {
        "policy_version": NORMALIZATION_POLICY_VERSION,
        "symbols": sorted(str(value) for value in raw_actions["code"].dropna().unique()),
        "raw_event_count": int(len(raw_actions)),
        "canonical_event_count": int(len(canonical)),
        "exact_duplicate_count": int(canonical["normalization_reason"].astype(str).str.contains("EXACT_DUPLICATE").sum()) if not canonical.empty else 0,
        "timezone_duplicate_count": 0,
        "ambiguous_duplicate_count": int((statuses == "AMBIGUOUS_DUPLICATE").sum()),
        "conflict_count": int((statuses == "CONFLICT").sum()),
        "ready_event_count": int((statuses == "READY").sum()),
        "unknown_event_count": int((statuses != "READY").sum()),
        "canonical_checksum": checksum,
    }


def _write_canonical_sidecar(dataset_path, canonical, manifest):
    dataset_path = Path(dataset_path)
    existing_canonical, existing_manifest = load_canonical_actions(dataset_path)
    if existing_manifest is not None:
        if existing_manifest["canonical_corporate_action_checksum"] != manifest["canonical_corporate_action_checksum"]:
            raise ValueError("Canonical corporate-action sidecar collision.")
        return
    temporary = Path(tempfile.mkdtemp(prefix=".ca-normalization-", dir=dataset_path.parent))
    try:
        canonical.to_parquet(temporary / CANONICAL_FILENAME, index=False)
        (temporary / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for name in (CANONICAL_FILENAME, MANIFEST_FILENAME):
            (temporary / name).replace(dataset_path / name)
    except Exception:
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _positive_number(value):
    if value is None or pd.isna(value):
        return None
    value = float(value)
    return value if value > 0 else None


def main():
    parser = argparse.ArgumentParser(description="Normalize Yahoo corporate-action evidence.")
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_DATASET_ROOT))
    args = parser.parse_args()
    canonical, manifest = normalize_dataset(args.dataset_version, args.output_root)
    print(f"Canonical Events: {len(canonical)}")
    print(f"Corporate Action Version: {manifest['corporate_action_version']}")
    print(f"Canonical Checksum: {manifest['canonical_corporate_action_checksum']}")


if __name__ == "__main__":
    main()
