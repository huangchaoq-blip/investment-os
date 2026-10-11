from dataclasses import asdict, dataclass
from typing import Optional


STRATEGY_NAME = "Pullback Technical Candidate"
STRATEGY_VERSION = "PB-CANDIDATE-V0.1"
STRATEGY_STATUS = "Specification Candidate"


@dataclass(frozen=True)
class PullbackRuleResult:
    rule_id: str
    value: Optional[bool]
    status: str
    evidence_value: Optional[bool]
    failure_reason: Optional[str]

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class PullbackStrategyResult:
    code: Optional[str]
    requested_date: Optional[str]
    facts_date: Optional[str]
    dataset_version: Optional[str]
    data_class: Optional[str]
    strategy_name: str
    strategy_version: str
    strategy_status: str
    decision: str
    decision_reason: str
    facts_status: Optional[str]
    trend_status: str
    entry_status: str
    risk_status: str
    rule_results: tuple[PullbackRuleResult, ...]
    signal_close: Optional[float]
    ma25: Optional[float]
    ma75: Optional[float]
    ma75_5d_ago: Optional[float]
    atr14: Optional[float]
    volume_ratio: Optional[float]
    pullback_low_5: Optional[float]
    provisional_stop: Optional[float]
    estimated_risk_pct: Optional[float]

    def to_dict(self):
        return asdict(self)


RULES = (
    ("TR-PB-001", "close_above_ma75", "trend"),
    ("TR-PB-002", "ma25_above_ma75", "trend"),
    ("TR-PB-003", "ma75_not_lower_than_5d_ago", "trend"),
    (
        "EN-PB-001",
        "previous_close_at_or_below_previous_ma25",
        "entry",
    ),
    ("EN-PB-002", "current_close_above_current_ma25", "entry"),
    ("EN-PB-003", "current_close_above_previous_close", "entry"),
    ("EN-PB-004", "current_close_within_3pct_of_ma25", "entry"),
    ("RK-PB-001", "provisional_stop_below_signal_close", "risk"),
    ("RK-PB-002", "estimated_risk_within_5pct", "risk"),
)


def evaluate_pullback_candidate(facts):
    """Interpret PullbackFacts without recalculating or loading market data."""

    identity = _identity(facts)
    facts_status = getattr(facts, "status", None) if facts is not None else None
    identity_missing = [
        field for field in ("code", "facts_date", "dataset_version") if not identity[field]
    ]
    if not facts_status:
        identity_missing.append("status")
    if facts is None:
        return _unknown_result(identity, facts_status, "MISSING_FACTS_INPUT")
    if identity_missing:
        return _unknown_result(
            identity,
            facts_status,
            "MISSING_REQUIRED_FACT: " + ", ".join(identity_missing),
        )
    if facts_status != "READY":
        return _unknown_result(identity, facts_status, str(facts_status))

    rules = tuple(
        _rule_result(rule_id, getattr(facts, field_name, None))
        for rule_id, field_name, _ in RULES
    )
    if any(rule.status == "UNKNOWN" for rule in rules):
        return _result(
            identity=identity,
            facts=facts,
            decision="UNKNOWN",
            decision_reason="MISSING_REQUIRED_FACT",
            trend_status=_group_status(rules[:3]),
            entry_status=_group_status(rules[3:7]),
            risk_status=_group_status(rules[7:]),
            rules=rules,
        )

    trend_status = _group_status(rules[:3])
    entry_status = _group_status(rules[3:7])
    risk_status = _group_status(rules[7:])
    failed_ids = [rule.rule_id for rule in rules if rule.status == "FAIL"]
    if failed_ids:
        decision = "WAIT"
        reason = "FAILED_RULES: " + ", ".join(failed_ids)
    else:
        decision = "BUY_CANDIDATE"
        reason = "ALL_REQUIRED_RULES_PASSED"
    return _result(
        identity=identity,
        facts=facts,
        decision=decision,
        decision_reason=reason,
        trend_status=trend_status,
        entry_status=entry_status,
        risk_status=risk_status,
        rules=rules,
    )


def _rule_result(rule_id, value):
    if value is True:
        return PullbackRuleResult(rule_id, True, "PASS", True, None)
    if value is False:
        return PullbackRuleResult(rule_id, False, "FAIL", False, "VALUE_FALSE")
    return PullbackRuleResult(rule_id, None, "UNKNOWN", None, "MISSING_REQUIRED_FACT")


def _group_status(rules):
    statuses = {rule.status for rule in rules}
    if "UNKNOWN" in statuses:
        return "UNKNOWN"
    return "PASS" if statuses == {"PASS"} else "FAIL"


def _identity(facts):
    return {
        "code": getattr(facts, "code", None) if facts is not None else None,
        "requested_date": getattr(facts, "requested_date", None) if facts is not None else None,
        "facts_date": getattr(facts, "facts_date", None) if facts is not None else None,
        "dataset_version": getattr(facts, "dataset_version", None) if facts is not None else None,
        "data_class": getattr(facts, "data_class", None) if facts is not None else None,
    }


def _unknown_result(identity, facts_status, reason):
    rules = tuple(
        PullbackRuleResult(rule_id, None, "UNKNOWN", None, reason)
        for rule_id, _, _ in RULES
    )
    return _result(
        identity=identity,
        facts=None,
        decision="UNKNOWN",
        decision_reason=reason,
        trend_status="UNKNOWN",
        entry_status="UNKNOWN",
        risk_status="UNKNOWN",
        rules=rules,
        facts_status=facts_status,
    )


def _result(
    identity,
    facts,
    decision,
    decision_reason,
    trend_status,
    entry_status,
    risk_status,
    rules,
    facts_status=None,
):
    return PullbackStrategyResult(
        **identity,
        strategy_name=STRATEGY_NAME,
        strategy_version=STRATEGY_VERSION,
        strategy_status=STRATEGY_STATUS,
        decision=decision,
        decision_reason=decision_reason,
        facts_status=facts_status if facts_status is not None else facts.status,
        trend_status=trend_status,
        entry_status=entry_status,
        risk_status=risk_status,
        rule_results=rules,
        signal_close=_evidence(facts, "signal_close"),
        ma25=_evidence(facts, "ma25"),
        ma75=_evidence(facts, "ma75"),
        ma75_5d_ago=_evidence(facts, "ma75_5d_ago"),
        atr14=_evidence(facts, "atr14"),
        volume_ratio=_evidence(facts, "volume_ratio"),
        pullback_low_5=_evidence(facts, "pullback_low_5"),
        provisional_stop=_evidence(facts, "provisional_stop"),
        estimated_risk_pct=_evidence(facts, "estimated_risk_pct"),
    )


def _evidence(facts, field_name):
    return getattr(facts, field_name, None) if facts is not None else None
