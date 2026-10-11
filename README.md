# Investment OS

**A Reproducible Investment Research & Validation System**

[![Offline engineering verification](https://github.com/huangchaoq-blip/investment-os/actions/workflows/ci.yml/badge.svg)](https://github.com/huangchaoq-blip/investment-os/actions/workflows/ci.yml)

Investment OS separates investment ideas from the evidence required to trust
them. It was built to turn Japanese-equity research into explicit decisions,
point-in-time inputs, deterministic Replay and independently governed validation.
The original goal was practical investment decision support, not a chart viewer
or an indicator collection.

This repository is a **selected public engineering archive**, with fresh Git
history. It is not a mature trading product, a live service, or evidence of a
profitable strategy. The original project is retired; Single-Stock Pattern Lab
(SSPL), one research case, is PAUSED. No trading recommendation is made here.

## Start Here

- [Architecture and boundaries](docs/architecture.md)
- [Actual implementation status](docs/module-status.md)
- [Research methodology and limitations](docs/methodology.md)
- [SSPL case study](case-studies/single-stock-pattern-lab/README.md)
- [Data rights and release exclusions](docs/data-rights.md)
- [Source provenance index](provenance/source-index.json)
- [Release report](INVESTMENT_OS_PUBLIC_RELEASE_REPORT_001.md)

## What Is Real

The selected original code includes immutable runtime Contexts, ExecutionIntent
and events; an event-driven execution kernel; position/trade projections;
Portfolio aggregates, persistence, invariants and bounded transitions; historical
Replay scheduling; dataset checksums/publication; and provider-neutral
operation-scoped qualification. These files are hash-bound to the verified
private Archive. Four package initializers trim the public export surface; four
governance documents redirect omitted private links to an explicit notice.
These eight PUBLIC_ADAPTATION files do not change the preserved algorithms.

The public demonstration is **REIMPLEMENTED_DEMO composition**: new, independently
invented fixtures and a scripted intent source call the **original** Replay,
Execution, Projection and Portfolio implementations. The intent source is not
an Alpha strategy. Synthetic success proves mechanics, not investment ability.

```text
Provider boundary -> Candidate / Qualification -> immutable Publication
                                                     |
                                         point-in-time Facts
                                                     |
                                      Strategy -> ExecutionIntent
                                                     |
                       Replay scheduling -> Execution -> events
                                                     |
                              Projection -> Portfolio -> Research evidence
```

## Run Offline

Use Python 3.11 or later. No account, API key or market dataset is needed.

```sh
python -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m public_demo.replay
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/verify_release.py
```

The demonstration reports synthetic identities, events and a deterministic
checksum. It never downloads data, consults an AI, or executes real orders.
Legacy network-capable ingestion dependencies are preserved as code evidence,
not a qualified provider or a recommended acquisition command.

## Research Outcome

Engineering produced a way to record and reject hypotheses without silently
changing them. It did **not** establish a validated tradable Alpha. SSPL did not
establish a finally qualified Pattern; it was paused by the Product Owner when
further work lacked a sufficiently informative next question. This does not
mathematically disprove every possible stock-native pattern.

The original project was retired and its market-data-dependent storage was
handled through a separate license-compliance closure. This public release is
not a restoration of that storage or its historical Git objects. Numerical
market-derived results, historical AI responses and real observations are
withheld pending applicable public-use rights. See the case study for the
distinction between engineering evidence and historical claims.

## Limits

Legacy execution and portfolio kernels contain `int`/`float` arithmetic; this
release does not pretend they are a universal exact-Decimal accounting system.
Corporate-action support is bounded and unresolved actions fail closed.
Historical issuer/lifecycle facts, market calendars, filings, qualified
datasets, live scheduling, financial/valuation pipelines and research outcome
payloads are not bundled. A runnable synthetic Replay is not full historical
Replay or evidence of point-in-time completeness for a real security.

The source is available for inspection under [the release license](LICENSE),
not presented as an unrestricted open-source or third-party-data license.
