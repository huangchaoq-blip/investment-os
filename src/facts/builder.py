from dataclasses import dataclass


REQUIRED_COLUMNS = [
    "date",
    "close",
    "volume",
    "MA75",
    "High60",
    "Volume20",
]


@dataclass(frozen=True)
class StockFacts:
    code: str
    date: str
    close: float
    above_ma75: bool
    ma75_rising: bool
    breakout60: bool
    volume_above_20: bool


def build_facts(code, df):
    validate_processed_dataframe(df)

    processed = df.sort_values("date").reset_index(drop=True)
    previous = processed.iloc[-2]
    current = processed.iloc[-1]

    return StockFacts(
        code=str(code),
        date=str(current["date"]),
        close=float(current["close"]),
        above_ma75=bool(current["close"] > current["MA75"]),
        ma75_rising=bool(current["MA75"] > previous["MA75"]),
        breakout60=bool(current["close"] > previous["High60"]),
        volume_above_20=bool(current["volume"] > current["Volume20"]),
    )


def validate_processed_dataframe(df):
    if len(df) < 2:
        raise ValueError("At least 2 processed rows are required to build facts.")

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing_columns:
        raise ValueError(
            "Missing required processed columns: " + ", ".join(missing_columns)
        )
