import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PORTFOLIO_PATH = BASE_DIR / "config" / "portfolio.json"


class Portfolio:
    def __init__(self, path=DEFAULT_PORTFOLIO_PATH):
        self._path = Path(path)
        self._data = self._read()

    def cash(self):
        return self._data["cash"]

    def positions(self):
        return self._data["positions"]

    def position(self, code):
        code = str(code)
        for position in self.positions():
            if position["code"] == code:
                return position

        return None

    def market_value(self, price_map):
        total = 0
        for position in self.positions():
            code = position["code"]
            current_price = price_map.get(code)
            if current_price is None:
                continue

            total += position["shares"] * current_price

        return total

    def position_valuation(self, code, current_price):
        position = self.position(code)
        if position is None:
            return None

        shares = position["shares"]
        avg_cost = position["avg_cost"]
        cost_value = shares * avg_cost

        if current_price is None:
            return {
                "code": position["code"],
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": None,
                "cost_value": cost_value,
                "market_value": None,
                "unrealized_pnl": None,
                "unrealized_pnl_pct": None,
            }

        market_value = shares * current_price
        unrealized_pnl = market_value - cost_value
        unrealized_pnl_pct = unrealized_pnl / cost_value * 100

        return {
            "code": position["code"],
            "shares": shares,
            "avg_cost": avg_cost,
            "current_price": current_price,
            "cost_value": cost_value,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
        }

    def total_equity(self, price_map):
        return self.cash() + self.market_value(price_map)

    def portfolio_valuation(self, price_map):
        position_valuations = []

        for position in self.positions():
            code = position["code"]
            position_valuations.append(
                self.position_valuation(code, price_map.get(code))
            )

        market_value = self.market_value(price_map)

        return {
            "cash": self.cash(),
            "market_value": market_value,
            "total_equity": self.cash() + market_value,
            "positions": position_valuations,
        }

    def _read(self):
        with self._path.open("r", encoding="utf-8") as portfolio_file:
            return json.load(portfolio_file)
