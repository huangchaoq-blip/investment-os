# ADR-005: Portfolio Engine Architecture

Status: Accepted

Date: 2026-07-17

## Objective

This Architecture Decision Record freezes Portfolio Engine as the sole business
component responsible for Portfolio state transitions. It defines ownership
and long-term architecture only. It does not define implementation,
persistence, storage format, API shape, or runtime mechanics.

## Context

ADR-004 defines Portfolio as the current investment state of one investment
account operating under one Strategy and one ExecutionContext. Portfolio owns
Cash, Positions, derived Statistics, and descriptive Metadata. It does not own
execution, Replay, Workflow, Checkpoint, or history.

The remaining architectural question is how Portfolio state is allowed to
change without moving business logic into the passive Portfolio domain object
or into the Execution Workflow.

ADR-003 already establishes that Execution Workflow executes a Portfolio
Engine and persists the resulting PortfolioState as part of one complete
Checkpoint. This ADR defines the ownership boundary of that Engine.

## Decision

Investment OS introduces a Portfolio Engine.

Portfolio Engine is the only business component permitted to calculate and
produce a transition from one Portfolio state to the next. Portfolio remains a
passive domain object representing current investment state.

"Modify Portfolio state" means producing a new deterministic Portfolio state.
It does not authorize in-place mutation of a persisted Checkpoint or of the
prior Portfolio input.

## Responsibilities

Portfolio Engine:

- receives the current Portfolio;
- receives the Replay Decision evidence;
- validates business state;
- calculates the Portfolio state transition;
- updates Cash in the resulting Portfolio;
- updates Positions in the resulting Portfolio;
- updates derived Statistics in the resulting Portfolio;
- produces Transactions; and
- returns the new Portfolio state.

Portfolio Engine owns business state transitions. It does not own the market,
Strategy, execution, orchestration, or persistence decisions that precede or
follow that transition.

## Replay Decision Terminology

This ADR uses `Replay Decision` as a descriptive name for the existing
canonical decision evidence delivered by Replay to the Portfolio Engine. It
does not create a new Contract or a new evidence type.

For compatibility with ADR-003, DEC-007, DEC-008, and the Frozen Execution
Workflow Specification, the Portfolio Engine receives:

- the same ExecutionContext;
- the prior PortfolioState; and
- the ordered immutable ExecutionEvents produced for the session and returned
  through Replay.

Replay coordinates Facts, Strategy, Intent, Projection, and Execution under
their accepted ownership boundaries. Strategy produces ExecutionIntent, and
only Execution Engine produces ExecutionEvents. Replay does not recreate those
business decisions. Portfolio Engine consumes the resulting immutable evidence
and must not infer a fill or bypass ExecutionEvent.

## Inputs

Portfolio Engine's business inputs are:

- Portfolio; and
- Replay Decision evidence as defined above.

Execution Workflow supplies the shared ExecutionContext required by ADR-003.
Portfolio Engine does not retrieve Context, market data, Replay output, or any
other input itself.

## Outputs

Portfolio Engine produces:

- an updated Portfolio;
- a Transaction collection; and
- updated derived Statistics within the resulting Portfolio.

Outputs are deterministic. Identical accepted inputs and versions produce
identical outputs.

Transaction represents a state transition and remains separate from current
Portfolio state under ADR-004. This ADR does not freeze Transaction fields,
serialization, persistence, or history retention.

## Architectural Principles

### Portfolio Engine is the sole Portfolio transition owner

No other component may calculate or apply changes to Cash, Positions,
Statistics, or other current Portfolio state.

### Portfolio Engine is deterministic

Identical Portfolio, Replay Decision evidence, ExecutionContext, and governed
versions always produce identical updated Portfolio, Transactions, and derived
Statistics.

Portfolio Engine must not depend on the system clock, network, mutable global
state, implicit files, or unversioned configuration.

### Portfolio Engine is independent of market-data retrieval and interpretation

Portfolio Engine does not access a Provider, Historical Cache, Canonical
Dataset, or market-data repository. Replay coordinates market interpretation
through the accepted Facts, Strategy, and Execution components.

Portfolio Engine operates on current business state and the canonical evidence
already delivered to it. It does not query or reinterpret source market data.

### Portfolio Engine does not perform execution

Portfolio Engine never:

- submits Orders;
- communicates with Brokers;
- creates or modifies ExecutionEvents;
- infers execution fills;
- accesses external services; or
- manages runtime Workflow.

### Portfolio Engine produces Transactions

Portfolio represents current state. Transactions represent state transitions.
Portfolio Engine produces Transactions but Portfolio does not store Transaction
history.

### Portfolio Engine does not own persistence

Portfolio Engine returns state-transition outputs. Checkpoint remains the only
persistence and recovery unit under ADR-003.

Portfolio Engine does not write, publish, activate, or restore Checkpoints.

## Ownership

Portfolio Engine owns:

- business state-transition calculation;
- Cash update calculation;
- Position update calculation;
- Statistics derivation; and
- Transaction generation.

Portfolio Engine does not own:

- Workflow;
- Replay;
- Timeline;
- Historical Cache;
- Canonical Dataset;
- Checkpoint;
- runtime execution;
- ExecutionEvent creation or mutation;
- reporting; or
- persistence.

## Architecture Boundary

```text
Facts / Strategy / Execution
             |
             v
           Replay
             |
             v
 Replay Decision Evidence
   (ExecutionEvents)
             |
             v
      Portfolio Engine
             |
             +--> Updated Portfolio
             `--> Transactions
                      |
                      v
                  Checkpoint
```

Execution Workflow remains responsible for orchestration. Portfolio Engine
remains responsible for Portfolio business-state transitions. Checkpoint
remains responsible for atomic persistence and recovery.

## Compatibility with ADR-003

This decision preserves ADR-003:

- ExecutionContext remains the single runtime Context.
- Execution metadata remains separate from Context.
- Workflow remains an orchestrator and executes Portfolio Engine after Replay.
- Portfolio Engine consumes the same Context, prior PortfolioState, and ordered
  immutable ExecutionEvents.
- Checkpoint remains the complete persistence and recovery unit.
- Timeline advances only after successful Checkpoint persistence.
- Portfolio Engine does not import data, synchronize a Provider, report,
  interact with a Broker, perform risk management, or send notifications.

No Execution Kernel 1.0 responsibility moves into Portfolio Engine.

## Compatibility with ADR-004

This decision preserves ADR-004:

- Portfolio remains current state, not history.
- Position remains current holding state, not trading activity.
- Portfolio owns Cash, Positions, derived Statistics, and Metadata.
- Portfolio Engine owns state-transition decisions.
- Transaction remains separate from Portfolio state.
- Portfolio does not acquire Replay, Workflow, Checkpoint, market-data, or
  history ownership.

ADR-004 defines what Portfolio is. ADR-005 defines the only business component
allowed to transition it.

## Out of Scope

The following remain outside V1:

- Broker execution;
- Order lifecycle;
- Fill handling;
- Settlement;
- Margin;
- Tax;
- Corporate Actions;
- Multi-account;
- Multi-currency; and
- Risk Management.

This ADR also does not define Portfolio formulas, sizing, accounting rules,
Transaction schema, persistence, API, CLI, reporting, or implementation.

## Consequences

### Benefits

- One business transition point;
- deterministic state updates;
- Replay-friendly architecture;
- Checkpoint-friendly state; and
- clear ownership boundaries.

### Trade-offs

- Future execution adapters require additional governed layers.
- Advanced Broker workflows remain deferred.
- Portfolio formulas and Transaction semantics require later specification
  before implementation.

## Architecture References

- [Investment OS Constitution](../docs/omitted-archive-references.md)
- [ADR-003: Execution Workflow Architecture Review](../docs/omitted-archive-references.md)
- [ADR-004: Portfolio Domain Model](ADR-004-portfolio-domain-model.md)
- [DEC-007: ExecutionEvent Contract](DEC-007-execution-event-contract.md)
- [DEC-008: ExecutionContext Contract](DEC-008-execution-context-contract.md)
- [Execution Workflow Specification](../docs/omitted-archive-references.md)
- [Execution Kernel 1.0 Capability Registry](../docs/omitted-archive-references.md)

## Decision Summary

Portfolio represents current investment state. Portfolio Engine performs the
state transition. Execution Kernel performs orchestration. Replay delivers the
canonical investment-decision evidence produced through the accepted Strategy
and Execution boundaries. These responsibilities remain permanently
separated.
