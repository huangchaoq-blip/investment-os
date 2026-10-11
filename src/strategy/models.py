from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyRuleResult:
    name: str
    passed: bool


@dataclass(frozen=True)
class StrategyResult:
    decision: str
    rule_results: list[StrategyRuleResult]
