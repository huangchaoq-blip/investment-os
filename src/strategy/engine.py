from .models import StrategyResult, StrategyRuleResult


def evaluate_strategy(facts):
    rule_results = [
        StrategyRuleResult(
            name="Trend",
            passed=facts.above_ma75 and facts.ma75_rising,
        ),
        StrategyRuleResult(
            name="Breakout",
            passed=facts.breakout60,
        ),
        StrategyRuleResult(
            name="Liquidity",
            passed=facts.volume_above_20,
        ),
    ]
    decision = "BUY" if all(rule.passed for rule in rule_results) else "WAIT"

    return StrategyResult(
        decision=decision,
        rule_results=rule_results,
    )
