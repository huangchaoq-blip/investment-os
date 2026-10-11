"""Invented fixture + scripted intent source, not an investment strategy."""
import json
from types import MappingProxyType

import pandas as pd

from data_platform.qualification_serialization import canonical_sha256_hex
from execution.context import ExecutionContext
from portfolio.aggregate import Cash, Metadata, Portfolio
from portfolio.engine import PortfolioEngine
from portfolio.persistence import portfolio_to_representation
from projection import project_trades
from replay.orchestrator import HistoricalReplayOrchestrator, ReplayRequest
from research.ledger import build_research_ledger
from research.performance import project_research_performance


SYMBOL = 'SYNTHETIC_A'
DATES = ('2040-01-02', '2040-01-03', '2040-01-04')
VERSION = 'synthetic-public-fixture-v1'
CONFIG = {'max_initial_risk_pct': 0.10, 'target_r_multiple': 3,
          'entry_quantity': 10}


def synthetic_bars():
    return pd.DataFrame([
        {'code': SYMBOL, 'date': day, 'open': 101 + index,
         'high': 105 + index, 'low': 99 + index, 'close': 102 + index,
         'volume': 1000 + index}
        for index, day in enumerate(DATES)
    ])


def scripted_intent(facts, result, position):
    day = facts['date']
    if day == DATES[0]:
        action = 'ENTER_LONG'
    elif day == DATES[1] and position is not None:
        action = 'EXIT_POSITION'
    else:
        return None
    return MappingProxyType({
        'intent_id': 'synthetic-intent-' + day, 'requested_action': action,
        'symbol': SYMBOL, 'signal_date': day, 'facts_date': day,
        'strategy_version': 'scripted-fixture-v1', 'dataset_version': VERSION,
        # Reason codes are fixed by the original kernel; no strategy inference.
        'intent_reason_code': 'PULLBACK_ENTRY' if action == 'ENTER_LONG' else 'TREND_EXIT',
        'signal_stop': 95,
    })


def run(bars=None, actions=None):
    bars = synthetic_bars() if bars is None else bars
    actions = pd.DataFrame() if actions is None else actions
    request = ReplayRequest(
        symbol=SYMBOL, dataset_version=VERSION,
        requested_start_date=DATES[0], requested_end_date=DATES[-1],
        strategy_version='scripted-fixture-v1',
        execution_configuration_version='synthetic-execution-v1',
        execution_configuration_snapshot=dict(CONFIG),
        corporate_action_version='synthetic-no-actions-v1',
    )
    visited = []

    def facts_builder(symbol, day, version, root):
        visited.append(day)
        return {'date': day}

    engine = HistoricalReplayOrchestrator(
        dataset_loader=lambda version, root: {
            'bars': bars.copy(), 'corporate_actions': actions.copy(),
            'limitations': ('SYNTHETIC_ONLY_NO_MARKET_VALIDATION',)},
        facts_builder=facts_builder, strategy_evaluator=lambda facts: facts,
        intent_producer=scripted_intent,
    )
    replay = engine.replay(request)
    portfolio = Portfolio(Metadata('synthetic-account', 'Synthetic account',
                                   'scripted-fixture-v1'), Cash(100000))
    context = ExecutionContext(
        execution_date=DATES[0], market_data_snapshot=None,
        corporate_action_snapshot=(), current_position_projection=None,
        execution_configuration_version=request.execution_configuration_version,
        execution_configuration_snapshot=CONFIG, strategy_version=request.strategy_version,
        dataset_version=VERSION, cache_manifest_id=None, timeline_position=0,
        runtime_mode='SYNTHETIC', universe_id='synthetic-universe', universe=(SYMBOL,),
        replay_version='historical-replay-v1', portfolio_id='synthetic-account',
        calendar_identity='invented-three-session-calendar', execution_workflow_version='fixture-v1',
    )
    portfolio_result = PortfolioEngine().apply(
        context, portfolio_to_representation(portfolio), replay.events)
    trades = project_trades(replay.events)
    metrics = project_research_performance(build_research_ledger(trades))
    payload = {
        'origin': 'REIMPLEMENTED_DEMO', 'data_class': 'SYNTHETIC_TEST',
        'not_an_alpha_or_return_claim': True, 'status': replay.status,
        'run_id': replay.execution_run_id, 'visited_contexts': visited,
        'events': [{key: dict(value) if isinstance(value, MappingProxyType) else value
                    for key, value in event.items()} for event in replay.events],
        'portfolio': portfolio_to_representation(portfolio_result.updated_portfolio),
        'closed_trade_count': len(trades.closed_trades),
        'economic_metrics': {metric.name: metric.status for metric in metrics.metrics
                             if metric.name in ('cagr', 'profit_factor', 'expectancy')},
    }
    return {**payload, 'checksum': canonical_sha256_hex(payload)}


def main():
    print(json.dumps(run(), sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
