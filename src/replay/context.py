from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from data.storage import load_processed_daily


@dataclass(frozen=True)
class ReplayContext:
    replay_date: str | None = None
    strategy_version: str = "Unknown"

    def is_replay(self):
        return self.replay_date is not None

    def validate(self):
        if self.replay_date is None:
            return True

        try:
            self._parsed_replay_date()
        except ValueError:
            return False

        return True

    def filter_until_replay_date(self, dataframe):
        if not self.is_replay():
            return dataframe.copy()

        replay_date = self._parsed_replay_date()
        filtered = dataframe.copy()
        filtered["date"] = pd.to_datetime(filtered["date"]).dt.date
        filtered = filtered[filtered["date"] <= replay_date]
        filtered = filtered.sort_values("date").reset_index(drop=True)
        filtered["date"] = filtered["date"].astype(str)
        return filtered

    def load_processed_daily(self, code):
        dataframe = load_processed_daily(code)
        return self.filter_until_replay_date(dataframe)

    def _parsed_replay_date(self):
        return datetime.strptime(self.replay_date, "%Y-%m-%d").date()
