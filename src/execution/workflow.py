"""ADR-003 execution orchestration without engine business rules."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from .checkpoint import Checkpoint, CheckpointError
from .context import ExecutionContext
from .runtime_values import freeze_value, thaw_value
from .timeline import TradingTimeline


class ExecutionWorkflowError(RuntimeError):
    """Raised when runtime boundaries cannot form a complete Checkpoint."""


class WorkflowCycleStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FINISHED = "FINISHED"


@dataclass(frozen=True)
class ReplayStepResult:
    execution_context: ExecutionContext
    events: tuple

    def __post_init__(self):
        if not isinstance(self.execution_context, ExecutionContext):
            raise TypeError("ReplayStepResult requires an ExecutionContext.")
        object.__setattr__(self, "events", freeze_value(self.events))


@dataclass(frozen=True)
class WorkflowCycleResult:
    status: WorkflowCycleStatus
    checkpoint: Checkpoint
    timeline: TradingTimeline
    events: tuple

    def __post_init__(self):
        object.__setattr__(self, "events", freeze_value(self.events))


class ExecutionWorkflow:
    """Coordinates one session and commits one complete recovery boundary."""

    def __init__(self, *, checkpoint_store, timeline, replay_executor, portfolio_executor):
        if not isinstance(timeline, TradingTimeline):
            raise TypeError("timeline must be a TradingTimeline.")
        self._checkpoint_store = checkpoint_store
        self._timeline = timeline
        self._replay_executor = replay_executor
        self._portfolio_executor = portfolio_executor

    def run_cycle(self):
        try:
            checkpoint = self._checkpoint_store.load_current()
        except CheckpointError as error:
            raise ExecutionWorkflowError("Checkpoint restoration failed.") from error
        if checkpoint is None:
            raise ExecutionWorkflowError("Execution Workflow requires an initial Checkpoint.")
        timeline = self._restore_timeline(checkpoint)
        if timeline.completed:
            return WorkflowCycleResult(
                status=WorkflowCycleStatus.FINISHED,
                checkpoint=checkpoint,
                timeline=timeline,
                events=(),
            )

        context = checkpoint.execution_context
        session = timeline.current_session

        replay_result = self._execute_replay(
            context=context,
            metadata=checkpoint.execution_metadata,
            session=session,
        )
        self._validate_replay_result(checkpoint, replay_result)
        events = replay_result.events

        next_portfolio_state = self._execute_portfolio(
            context=replay_result.execution_context,
            portfolio_state=thaw_value(checkpoint.portfolio_state),
            events=thaw_value(events),
        )
        if not isinstance(next_portfolio_state, Mapping):
            raise ExecutionWorkflowError("Portfolio Engine must return a state mapping.")

        next_position = timeline.position + 1
        next_session = (
            None
            if next_position == len(timeline.sessions)
            else timeline.sessions[next_position]
        )
        next_context = replay_result.execution_context.at_timeline_position(
            next_position,
            next_session,
        )
        next_metadata = checkpoint.execution_metadata.advance_event_cursor(len(events))
        next_checkpoint = Checkpoint.create(
            timeline_id=timeline.timeline_id,
            execution_context=next_context,
            execution_metadata=next_metadata,
            portfolio_state=next_portfolio_state,
            parent_checkpoint_id=checkpoint.checkpoint_id,
        )

        try:
            self._checkpoint_store.save(
                next_checkpoint,
                expected_current_id=checkpoint.checkpoint_id,
            )
        except CheckpointError as error:
            raise ExecutionWorkflowError("Checkpoint persistence failed.") from error

        next_timeline = timeline.advance()
        return WorkflowCycleResult(
            status=WorkflowCycleStatus.COMPLETED,
            checkpoint=next_checkpoint,
            timeline=next_timeline,
            events=events,
        )

    def _restore_timeline(self, checkpoint):
        if checkpoint.timeline_id != self._timeline.timeline_id:
            raise ExecutionWorkflowError("Checkpoint belongs to another TradingTimeline.")
        context = checkpoint.execution_context
        if context.calendar_identity != self._timeline.calendar_identity:
            raise ExecutionWorkflowError("Checkpoint calendar identity mismatch.")
        try:
            timeline = self._timeline.at_position(context.timeline_position)
        except ValueError as error:
            raise ExecutionWorkflowError("Checkpoint Timeline position is invalid.") from error
        if context.execution_date != timeline.current_session:
            raise ExecutionWorkflowError(
                "ExecutionContext execution_date differs from the resolved session."
            )
        return timeline

    def _execute_replay(self, **kwargs):
        execute = getattr(self._replay_executor, "execute", None)
        if not callable(execute):
            raise ExecutionWorkflowError("Replay boundary must provide execute().")
        result = execute(**kwargs)
        if not isinstance(result, ReplayStepResult):
            raise ExecutionWorkflowError(
                "Replay boundary must return ReplayStepResult."
            )
        return result

    def _execute_portfolio(self, **kwargs):
        apply_events = getattr(self._portfolio_executor, "apply", None)
        if not callable(apply_events):
            raise ExecutionWorkflowError("Portfolio boundary must provide apply().")
        return apply_events(**kwargs)

    def _validate_replay_result(self, checkpoint, replay_result):
        before = checkpoint.execution_context
        after = replay_result.execution_context
        stable_fields = (
            "execution_date",
            "execution_configuration_version",
            "execution_configuration_snapshot",
            "strategy_version",
            "dataset_version",
            "cache_manifest_id",
            "timeline_position",
            "runtime_mode",
            "universe_id",
            "universe",
            "replay_version",
            "portfolio_id",
            "calendar_identity",
            "execution_workflow_version",
        )
        if any(before[field] != after[field] for field in stable_fields):
            raise ExecutionWorkflowError(
                "Replay changed an immutable ExecutionContext binding."
            )

        expected = checkpoint.execution_metadata.next_event_sequence_number
        for offset, event in enumerate(replay_result.events):
            if not isinstance(event, Mapping):
                raise ExecutionWorkflowError("Replay Events must be mappings.")
            if event.get("sequence_number") != expected + offset:
                raise ExecutionWorkflowError(
                    "Replay returned a non-continuous Event sequence."
                )
            if event.get("execution_run_id") != checkpoint.execution_metadata.execution_run_id:
                raise ExecutionWorkflowError("Replay returned an Event for another Run.")
