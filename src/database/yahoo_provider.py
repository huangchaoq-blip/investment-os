import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pandas as pd


class YahooProvider:
    BASE_URL = "https://query2.finance.yahoo.com/v8/finance/chart"

    def fetch_daily(self, code: str):
        yahoo_ticker = self._to_yahoo_ticker(code)
        payload = self._fetch_chart(yahoo_ticker)
        dataframe = self._to_dataframe(payload)

        if dataframe.empty:
            raise RuntimeError(f"Yahoo returned no daily data for {yahoo_ticker}.")

        return dataframe

    def _to_yahoo_ticker(self, code):
        code = str(code).strip()
        if code.endswith(".T"):
            return code

        return f"{code}.T"

    def _fetch_chart(self, yahoo_ticker):
        params = urlencode(
            {
                "range": "1y",
                "interval": "1d",
            }
        )
        url = f"{self.BASE_URL}/{quote(yahoo_ticker, safe='')}?{params}"
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
            raise RuntimeError(error)

        return payload

    def _to_dataframe(self, payload):
        results = payload.get("chart", {}).get("result") or []
        if not results:
            raise RuntimeError("Yahoo returned no chart result.")

        result = results[0]
        timestamps = result.get("timestamp") or []
        quote_data = result.get("indicators", {}).get("quote", [{}])[0]
        meta = result.get("meta", {})
        market_timezone = timezone(timedelta(seconds=meta.get("gmtoffset", 0)))
        rows = []

        for index, timestamp in enumerate(timestamps):
            close = self._at(quote_data, "close", index)
            if close is None:
                continue

            rows.append(
                {
                    "date": datetime.fromtimestamp(
                        timestamp,
                        market_timezone,
                    ).date().isoformat(),
                    "open": self._at(quote_data, "open", index),
                    "high": self._at(quote_data, "high", index),
                    "low": self._at(quote_data, "low", index),
                    "close": close,
                    "volume": self._at(quote_data, "volume", index),
                }
            )

        dataframe = pd.DataFrame(
            rows,
            columns=["date", "open", "high", "low", "close", "volume"],
        )
        return dataframe

    def _at(self, quote_data, field, index):
        values = quote_data.get(field, [])
        if index >= len(values):
            return None

        return values[index]
