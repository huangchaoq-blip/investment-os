"""Independently invented fixtures; no market observations or network access."""
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from data_platform.qualification_engine import evaluate
from data_platform.qualification_schemas import (
    CapabilitySupportStatus, EvidenceAssessmentStatus, EvidenceCoverage,
    OperationQualificationProfile, ProviderCapabilityCatalogue, ProviderCapabilityEvidence,
    QualificationRequirement, QualificationScope, RequestedOperationalStatus,
    RequirementClassification, STRICT_SCOPE_QUALIFIED_V1,
)
from data_platform.qualification_serialization import (
    canonical_json_bytes, canonical_sha256_hex, parse_json_payload,
    CanonicalQualificationSerializationError,
)
from execution.context import ExecutionContext
from execution.exceptions import InvalidExecutionContextError
from portfolio.aggregate import Cash, Metadata, Portfolio, Position
from portfolio.persistence import serialize_portfolio, portfolio_from_representation
from public_demo.replay import DATES, run, synthetic_bars
from replay.orchestrator import ReplayInputError
from strategy.engine import evaluate_strategy
from data.manifest import (
    create_dataset_manifest, DataClass, DatasetEligibilityError,
    assert_historical_market_dataset, calculate_checksum,
)
from execution.engine import ExecutionEngine
from public_demo.replay import CONFIG, VERSION, scripted_intent


class PublicMechanicsTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('socket.socket.connect', side_effect=AssertionError('NETWORK_PROHIBITED'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_original_replay_next_open(self):
        result = run()
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['visited_contexts'], list(DATES))
        entry = next(e for e in result['events'] if e['event_type'] == 'ENTRY_FILLED')
        self.assertEqual(entry['event_date'], DATES[1])
        self.assertEqual(entry['payload']['entry_price'], 102)
        close = next(e for e in result['events'] if e['event_type'] == 'POSITION_CLOSED')
        self.assertEqual(close['event_date'], DATES[2])
        self.assertEqual(result['closed_trade_count'], 1)

    def test_original_portfolio_cash_and_empty_position(self):
        result = run()
        self.assertEqual(result['portfolio']['cash']['amount'], 100010)
        self.assertEqual(result['portfolio']['positions'], [])
        self.assertTrue(all(state == 'BLOCKED' for state in result['economic_metrics'].values()))

    def test_identical_replay(self):
        self.assertEqual(run(), run())

    def test_fresh_process_determinism(self):
        outputs = [subprocess.check_output([sys.executable, '-B', '-m', 'public_demo.replay'],
                                          text=True) for _ in range(2)]
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(json.loads(outputs[0])['checksum'], run()['checksum'])

    def test_duplicate_observation_rejected(self):
        bars = synthetic_bars()
        import pandas as pd
        with self.assertRaises(ReplayInputError):
            run(pd.concat([bars, bars.iloc[:1]], ignore_index=True))

    def test_nonfinite_price_rejected(self):
        bars = synthetic_bars()
        bars.loc[1, 'open'] = float('nan')
        with self.assertRaises(ReplayInputError):
            run(bars)

    def test_future_rows_excluded_from_requested_window(self):
        import pandas as pd
        bars = synthetic_bars()
        future = dict(bars.iloc[-1]); future['date'] = '2040-01-09'
        future['close'] = 777
        self.assertEqual(run(bars), run(pd.concat([bars, pd.DataFrame([future])], ignore_index=True)))

    def test_portfolio_roundtrip(self):
        portfolio = Portfolio(Metadata('synthetic', 'Synthetic', 'script'), Cash(9000),
                              (Position('SYNTHETIC_B', 10, 37),))
        self.assertEqual(portfolio_from_representation(json.loads(serialize_portfolio(portfolio))), portfolio)

    def test_negative_cash_rejected(self):
        with self.assertRaises(ValueError):
            Cash(-1)

    def test_duplicate_holdings_rejected(self):
        with self.assertRaises(ValueError):
            Portfolio(Metadata('fixture', 'Fixture', 'script'), Cash(50),
                      (Position('SYNTHETIC_A', 1, 2), Position('SYNTHETIC_A', 1, 3)))

    def test_original_strategy_decision_boundary(self):
        yes = SimpleNamespace(above_ma75=True, ma75_rising=True,
                              breakout60=True, volume_above_20=True)
        self.assertEqual(evaluate_strategy(yes).decision, 'BUY')
        yes.breakout60 = False
        self.assertEqual(evaluate_strategy(yes).decision, 'WAIT')

    def test_canonical_identity_order_independent(self):
        self.assertEqual(canonical_sha256_hex({'b': 2, 'a': 1}),
                         canonical_sha256_hex({'a': 1, 'b': 2}))

    def test_duplicate_json_rejected(self):
        with self.assertRaises(CanonicalQualificationSerializationError):
            parse_json_payload('{"same":1,"same":2}')

    def test_nonfinite_serialization_rejected(self):
        with self.assertRaises(CanonicalQualificationSerializationError):
            canonical_json_bytes({'synthetic': float('inf')})

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(CanonicalQualificationSerializationError):
            canonical_json_bytes(datetime(2040, 1, 1))

    def test_required_evidence_missing_blocks(self):
        self.assertEqual(self.qualification(False).overall_outcome.value, 'BLOCKED')

    def test_scoped_synthetic_evidence_qualifies(self):
        first = self.qualification(True)
        second = self.qualification(True)
        self.assertEqual(first.overall_outcome.value, 'QUALIFIED')
        self.assertEqual(first, second)

    def test_synthetic_cannot_claim_historical_market_eligibility(self):
        manifest = create_dataset_manifest(
            synthetic_bars(), DataClass.SYNTHETIC_TEST, 'invented-fixture',
            'raw-daily-v1', 'synthetic-no-actions', 'public-mechanics-only',
            fetched_at='2040-01-05T00:00:00+00:00')
        with self.assertRaises(DatasetEligibilityError):
            assert_historical_market_dataset(manifest)

    def test_manifest_changes_with_input_content(self):
        bars = synthetic_bars()
        changed = bars.copy()
        changed.loc[0, 'close'] += 1
        self.assertNotEqual(calculate_checksum(bars), calculate_checksum(changed))

    def test_unknown_corporate_action_blocks_execution(self):
        context = self.execution_tick()
        context['corporate_action_snapshot'] = ({'code': 'SYNTHETIC_A',
                                                'normalization_status': 'UNKNOWN'},)
        events = ExecutionEngine().execute(context, scripted_intent({'date': DATES[0]}, None, None))
        self.assertEqual([event['event_type'] for event in events], ['CORPORATE_ACTION_BLOCKED'])

    def test_insufficient_cash_rejects_entry(self):
        context = self.execution_tick()
        context['execution_configuration_snapshot'] = {**CONFIG, 'shared_available_cash': 1}
        events = ExecutionEngine().execute(context, scripted_intent({'date': DATES[0]}, None, None))
        self.assertEqual(events[-1]['reason_code'], 'ENTRY_INSUFFICIENT_CASH')

    def test_execution_event_is_immutable(self):
        context = self.execution_tick()
        events = ExecutionEngine().execute(context, scripted_intent({'date': DATES[0]}, None, None))
        with self.assertRaises(TypeError):
            events[-1]['payload']['entry_price'] = 888

    def execution_tick(self):
        return {'execution_date': DATES[1],
                'market_data_snapshot': {'open': 102, 'high': 106, 'low': 100, 'close': 103},
                'corporate_action_snapshot': (), 'current_position_projection': None,
                'execution_configuration_version': 'synthetic-execution-v1',
                'execution_configuration_snapshot': CONFIG, 'next_event_sequence_number': 1,
                'execution_run_id': 'synthetic-run', 'strategy_version': 'scripted-fixture-v1',
                'dataset_version': VERSION}

    def qualification(self, supported):
        capability = 'CANONICAL_OHLCV_COMPLETENESS'
        coverage = EvidenceCoverage('JP', 'EQUITY', symbols=('SYNTHETIC_A',),
                                    start_date=date(2040, 1, 2), end_date=date(2040, 1, 4),
                                    permitted_uses=('synthetic-mechanics',))
        evidence = ProviderCapabilityEvidence(
            capability, 'synthetic-provider', 'v1', CapabilitySupportStatus.SUPPORTED,
            EvidenceAssessmentStatus.QUALIFIED, coverage, ('synthetic-evidence-only',),
            datetime(2040, 1, 5, tzinfo=timezone.utc))
        catalogue = ProviderCapabilityCatalogue('synthetic-provider', 'v1', 'v1',
                                                (evidence,) if supported else ())
        requirement = QualificationRequirement(capability, RequirementClassification.REQUIRED,
                                               ('replay',), 'Synthetic mechanics', STRICT_SCOPE_QUALIFIED_V1)
        profile = OperationQualificationProfile('synthetic-profile', 1,
            RequestedOperationalStatus.QUALIFIED_FOR_RESEARCH, 'synthetic-mechanics',
            'JP', 'EQUITY', (requirement,))
        scope = QualificationScope('synthetic-provider', 'v1', 'synthetic-profile', 1,
            'JP', 'EQUITY', 'synthetic-mechanics', symbols=('SYNTHETIC_A',),
            start_date=date(2040, 1, 2), end_date=date(2040, 1, 4))
        return evaluate(catalogue, profile, scope, ())


if __name__ == '__main__':
    unittest.main()
