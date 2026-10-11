# ADR-004: Portfolio Domain Model

Status: Accepted

Date: 2026-07-17

## Objective

This Architecture Decision Record freezes the core Portfolio domain model and
its ownership boundaries for the Investment OS Domain Capability phase. It
defines long-term architecture only. It does not define runtime behavior,
persistence, APIs, storage formats, or implementation details.

## Context

Investment OS Architecture Baseline 1.0 has been established with two Frozen
foundation capabilities:

- Historical Cache 1.0; and
- Execution Kernel 1.0.

The next phase introduces domain capabilities on top of that foundation.
Portfolio state must integrate with the Execution Kernel's deterministic
Checkpoint boundary without absorbing execution, workflow, historical, or
market-data responsibilities.

## Decision

Investment OS uses a Portfolio-centric domain model for current investment
state.

Portfolio represents current state only. Trading history, Replay history, and
execution history remain separate concerns.

```text
Portfolio
|-- Cash
|-- Positions
|-- Statistics
`-- Metadata
```

## Portfolio

Portfolio represents the current investment state of one investment account
operating under one Strategy and one ExecutionContext.

Portfolio owns:

- Cash;
- a Position collection;
- Portfolio Statistics; and
- Portfolio Metadata.

Portfolio does not own:

- Replay;
- Workflow;
- Orders;
- Trade history;
- Event history;
- Checkpoints; or
- Market data.

## Cash

Cash represents currently available investment capital. Cash belongs to
exactly one Portfolio.

Cash changes only through Portfolio Engine decisions. This ownership rule does
not authorize any particular cash-calculation, settlement, fee, or accounting
semantics; those details are outside this ADR.

## Position

Position represents the current holding of one financial instrument. Each
Position corresponds to exactly one instrument and contains current holding
state only.

Typical attributes may include:

- Symbol;
- Quantity;
- Average Cost;
- Current Value; and
- Unrealized Profit/Loss.

This list illustrates the domain boundary and does not freeze a serialized
Position schema. Historical transactions are explicitly excluded from
Position.

## Statistics

Statistics represent derived information about the current Portfolio.
Examples include:

- Total Asset Value;
- Unrealized Profit/Loss;
- Cash Ratio; and
- Position Count.

Statistics are derived state. They never become the system of record and must
always be reproducible from Portfolio state.

## Metadata

Metadata contains descriptive information only. Examples include:

- Portfolio ID;
- Portfolio Name;
- Strategy ID; and
- Creation Version.

Metadata does not contain runtime state.

## Transaction

Transaction is not owned by Portfolio. Portfolio Engine produces a Transaction
to represent a Portfolio state transition.

Transaction belongs to execution history rather than current Portfolio state.
Portfolio does not retain Transaction history.

This ADR does not freeze a Transaction schema, storage model, or processing
API.

## Ownership Rules

Portfolio owns:

- Cash;
- Positions;
- Statistics; and
- Metadata.

Portfolio does not own:

- ExecutionContext;
- Timeline;
- Replay;
- Workflow;
- Checkpoint;
- Historical Cache; or
- Transaction history.

## Architectural Principles

### Portfolio represents state, not history

Portfolio contains the current investment state. Historical evidence remains
outside the Portfolio aggregate.

### Position represents state, not trading activity

A Position describes the current holding of one instrument. It does not record
the sequence of activity that created that holding.

### Transactions modify Portfolio; Portfolio does not store Transactions

Portfolio Engine owns Portfolio state-transition decisions. Transaction
history remains separate from the resulting current state.

### Statistics are derived

Statistics must always be reproducible from Portfolio state and cannot replace
the underlying Cash and Position state.

### Execution and Portfolio responsibilities do not overlap

Execution Kernel manages execution. Portfolio manages investment state.
Portfolio does not create or rewrite Execution evidence, and Execution Kernel
does not own Portfolio business rules.

## Checkpoint Compatibility

ADR-003 defines Checkpoint as the complete persistence and recovery unit and
includes PortfolioState as one of its conceptual members. This ADR defines the
domain ownership of that Portfolio state without changing Checkpoint
architecture.

Recovery continues to restore one complete Checkpoint. Portfolio is not
restored, persisted, or advanced independently of that boundary. This ADR does
not define the PortfolioState serialization or Checkpoint storage format.

## Out of Scope

The following concepts are intentionally excluded from V1:

- Order;
- Fill;
- Settlement;
- Broker;
- Margin;
- Tax;
- Dividend;
- Corporate Actions;
- Multi-currency;
- Lot Selection;
- Multi-account; and
- Risk Management.

Future ADRs may introduce these concepts if required.

This ADR also does not define Portfolio runtime implementation, persistence,
Transaction storage, calculation formulas, APIs, CLI behavior, or reporting.

## Consequences

### Benefits

- Clear ownership boundaries;
- deterministic Portfolio state;
- simplified recovery;
- Checkpoint-friendly architecture;
- straightforward Replay integration; and
- minimal domain complexity.

### Trade-offs

- Historical analysis depends on separate Transaction history.
- Advanced Broker functionality requires future extensions.
- Corporate-action handling within Portfolio is deferred.

## Architecture References

- [Investment OS Constitution](../docs/omitted-archive-references.md)
- [ADR-003: Execution Workflow Architecture Review](../docs/omitted-archive-references.md)
- [DEC-007: ExecutionEvent Contract](DEC-007-execution-event-contract.md)
- [DEC-008: ExecutionContext Contract](DEC-008-execution-context-contract.md)
- [DEC-013: Local Historical Cache](../docs/omitted-archive-references.md)
- [Execution Workflow Specification](../docs/omitted-archive-references.md)
- [Capability Registry](../docs/omitted-archive-references.md)

## Architecture Baseline 1.0 Compatibility

This decision is compatible with Architecture Baseline 1.0:

- Historical Cache remains the governed noncanonical runtime data layer.
- Execution Kernel remains the owner of runtime execution and Checkpoint
  orchestration.
- PortfolioState remains a Checkpoint member and is now given an explicit
  domain ownership boundary.
- Portfolio does not acquire Replay, Workflow, ExecutionEvent, Checkpoint, or
  market-data ownership.
- Portfolio capability remains Draft until implementation and verification are
  completed; accepting this domain model does not mark the capability Frozen.

No Frozen capability Contract or runtime behavior is changed by this decision.

## Decision Summary

Portfolio represents current investment state. Execution Kernel represents
runtime execution. Historical data represents facts. Transaction represents a
state transition. These responsibilities remain permanently separated.
