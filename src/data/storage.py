from datetime import date
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RAW_DAILY_DIR = DATA_DIR / "raw" / "jp" / "daily"
RAW_INDEX_DIR = DATA_DIR / "raw" / "jp" / "index"
PROCESSED_DAILY_DIR = DATA_DIR / "processed" / "jp" / "daily"
PROCESSED_INDEX_DIR = DATA_DIR / "processed" / "jp" / "index"
METADATA_DIR = DATA_DIR / "metadata"

RAW_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def ensure_data_directories():
    for path in [
        RAW_DAILY_DIR,
        RAW_INDEX_DIR,
        PROCESSED_DAILY_DIR,
        PROCESSED_INDEX_DIR,
        METADATA_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def raw_daily_path(code):
    return RAW_DAILY_DIR / f"{code}.parquet"


def processed_daily_path(code):
    return PROCESSED_DAILY_DIR / f"{code}.parquet"


def save_raw_daily(code, dataframe):
    ensure_data_directories()
    raw = dataframe[RAW_COLUMNS].copy()
    raw.to_parquet(raw_daily_path(code), index=False)
    return raw_daily_path(code)


def load_raw_daily(code):
    return pd.read_parquet(raw_daily_path(code))


def load_raw_daily_with_manifest(code, dataset_version):
    from .manifest import load_dataset_manifest

    manifest = load_dataset_manifest(dataset_version)
    if str(code) not in manifest.symbols:
        raise ValueError(
            f"Code {code} is not included in dataset {manifest.dataset_version}."
        )

    return load_raw_daily(code), manifest


def save_processed_daily(code, dataframe):
    ensure_data_directories()
    dataframe.to_parquet(processed_daily_path(code), index=False)
    return processed_daily_path(code)


def load_processed_daily(code):
    return pd.read_parquet(processed_daily_path(code))


def list_raw_daily_files():
    ensure_data_directories()
    return sorted(RAW_DAILY_DIR.glob("*.parquet"))


def create_sample_raw_from_watchlist(watchlist_path=None, rows=220):
    ensure_data_directories()
    watchlist_path = watchlist_path or BASE_DIR / "config" / "watchlist.csv"
    watchlist = pd.read_csv(watchlist_path, dtype={"code": str})
    dates = pd.bdate_range(end=date.today(), periods=rows)
    output_paths = []

    for stock_index, stock in watchlist.iterrows():
        code = str(stock["code"])
        path = raw_daily_path(code)
        if path.exists():
            output_paths.append(path)
            continue

        output_paths.append(save_raw_daily(code, _sample_ohlcv(dates, stock_index)))

    return output_paths


def _sample_ohlcv(dates, stock_index):
    base_price = 1000 + stock_index * 500
    rows = []

    for index, current_date in enumerate(dates):
        trend = index * (2 + stock_index)
        cycle = (index % 10) - 5
        close = float(base_price + trend + cycle)
        open_price = close - 2
        high = close + 8
        low = close - 8
        volume = 100000 + stock_index * 50000 + index * 1000
        rows.append(
            {
                "date": current_date.date().isoformat(),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

    return pd.DataFrame(rows, columns=RAW_COLUMNS)
