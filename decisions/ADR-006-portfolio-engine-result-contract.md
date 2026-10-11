# ADR-006: Portfolio Engine Result Contract

Status: Accepted

Date: 2026-07-17

## Objective

Freeze the canonical output boundary of Portfolio Engine without redefining
Portfolio behavior, Execution evidence, Workflow responsibility, or
Checkpoint ownership.

## Context

ADR-005 defines the responsibilities and ownership boundaries of Portfolio
Engine. Execution Workflow invokes Portfolio Engine during deterministic
session execution.

No canonical Result Contract currently binds the updated Portfolio,
Transaction evidence, Portfolio validation evidence, and deterministic state
identity into one immutable outcome. Existing architecture therefore refers
to compatible but incomplete return semantics, preventing implementation of a
single Portfolio Engine boundary.

A stable Result Contract is required before Portfolio Engine implementation.

## Decision

Investment OS introduces one canonical immutable result object:

`PortfolioEngineResult`

This ADR defines only the Portfolio Engine output Contract. It does not
redefine Portfolio Engine responsibilities, ExecutionEvent, ExecutionContext,
Workflow responsibilities, Checkpoint ownership, or Portfolio behavior.

## Purpose

PortfolioEngineResult represents the complete deterministic outcome of
processing one execution session.

## Ownership

PortfolioEngineResult is produced only by Portfolio Engine.

Consumers may include:

- Execution Workflow;
- Checkpoint;
- Reporting; and
- Replay Verification.

PortfolioEngineResult is immutable.

## Required Components

### Updated Portfolio

The Result contains the complete Portfolio state after processing the ordered
ExecutionEvents for the session.

### Transaction Evidence

The Result contains the collection of Portfolio Transactions produced during
processing. The collection may be empty.

This ADR does not define Transaction fields, serialization, persistence, or
business semantics.

### Validation Outcome

The Result contains validation evidence describing whether the produced
Portfolio satisfies the Portfolio Capability Contract.

This component does not create new validation rules. Portfolio validation
semantics remain governed by the accepted Portfolio validation boundary.

### State Fingerprint

The Result contains a deterministic fingerprint representing the resulting
Portfolio state. The fingerprint supports deterministic verification.

This ADR does not select a hashing algorithm, encoding, or fingerprint
version. Those implementation details must preserve the canonical Portfolio
persistence representation and require explicit governance if they become a
public compatibility Contract.

## Deferred Components

The following are excluded from V1:

- Market valuation;
- Performance metrics;
- Reporting output;
- Runtime diagnostics; and
- Broker responses.

## Behavior

PortfolioEngineResult contains no business logic, performs no calculations,
and permits no mutation.

Portfolio Engine calculates the outcome. The Result only represents that
outcome.

## Determinism

Equivalent governed inputs always produce an equivalent
PortfolioEngineResult.

Result equivalence includes the updated Portfolio, ordered Transaction
evidence, Validation Outcome, and State Fingerprint.

## Architecture

```text
ExecutionContext
        +
Portfolio
        +
ordered ExecutionEvents
        |
        v
Portfolio Engine
        |
        v
PortfolioEngineResult
```

## Compatibility

### ADR-003

Checkpoint remains the complete persistence and recovery unit. This Result
Contract does not create a second recovery boundary or permit independent
Portfolio recovery.

### ADR-005

Portfolio Engine remains the sole Portfolio transition owner. The Result binds
the updated Portfolio, Transaction collection, and validation evidence without
moving transition logic into Portfolio or Workflow.

### DEC-007

Only Execution Engine creates ExecutionEvents. PortfolioEngineResult does not
create, replace, mutate, or reinterpret Execution evidence.

### Portfolio Persistence

The updated Portfolio uses the canonical Portfolio persistence representation
when it becomes Checkpoint PortfolioState. Validation evidence, Transaction
evidence, and the Result wrapper do not become fields inside the Portfolio
aggregate.

## Consequences

- Execution Workflow depends on PortfolioEngineResult at the Portfolio Engine
  boundary.
- Portfolio Engine has one complete deterministic session outcome.
- Updated Portfolio state remains distinct from Transaction and Validation
  evidence.
- Existing Workflow implementation requires a later governed alignment from
  its direct state-mapping return adapter to this Result Contract.
- Future optional fields may be added only when they preserve V1 semantic
  meaning and compatibility requirements.

## Out of Scope

This ADR does not define:

- Portfolio Engine implementation;
- BUY processing;
- SELL processing;
- Statistics calculation;
- Replay behavior;
- Workflow implementation;
- Checkpoint implementation;
- Transaction schema;
- validation rules;
- fingerprint algorithm;
- Reporting implementation; or
- Broker integration.

## Architecture References

- [ADR-003: Execution Workflow Architecture Review](../docs/omitted-archive-references.md)
- [ADR-004: Portfolio Domain Model](ADR-004-portfolio-domain-model.md)
- [ADR-005: Portfolio Engine Architecture](ADR-005-portfolio-engine-architecture.md)
- [DEC-007: ExecutionEvent Contract](DEC-007-execution-event-contract.md)
- [Execution Workflow Specification](../docs/omitted-archive-references.md)
- [Portfolio Capability Specification](../docs/omitted-archive-references.md)
- [Portfolio Persistence Contract](../docs/omitted-archive-references.md)

## Decision Summary

Portfolio Engine consumes the accepted session inputs and produces one
immutable PortfolioEngineResult. The Result contains the updated Portfolio,
Transaction evidence, Validation Outcome, and State Fingerprint without
changing the ownership of Portfolio transitions, Execution evidence,
Workflow, or Checkpoint recovery.
