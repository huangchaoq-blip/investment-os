# INVESTMENT_OS_PUBLIC_RELEASE_REPORT_001

Mission: INVESTMENT_OS_PUBLIC_GITHUB_RELEASE_REVISION_001

Current status: **PUBLIC_RELEASE_COMPLETE** for the reviewed source/synthetic scope.

## Target and Access

Public URL: https://github.com/huangchaoq-blip/investment-os

The target was absent before creation. Official GitHub login confirmed the owner
and a new PUBLIC repository was created with a fresh README-only root commit.
No existing repository was overwritten. The reviewed source was pushed and
its initial Python 3.11 and 3.12 build/test/verification jobs passed. A subsequent
commit-metadata audit found a non-noreply email in the GitHub-created root.
The address is not reproduced here. The Product Owner explicitly authorized
rebuilding only the new public history with public noreply identities and a
force-with-lease update. That update completed. The sanitized code revision
`7985e44a932de24cb7bad1c38e229de33faa8401` passed both Python 3.11 and 3.12 jobs in
[Actions run 38100045733](https://github.com/huangchaoq-blip/investment-os/actions/runs/38100045733).
The history/content verifier and local Git object integrity check passed.

Rewriting reachable history cannot guarantee immediate removal of previously
published commit objects from GitHub caches or third-party copies, as
[GitHub documents](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
No raw provider data or credential was involved; absolute remote erasure is not
claimed. The obsolete objects were pruned from this local public repository.

## Included Modules

Investment OS Core, original Execution and projections, Replay orchestrator,
Portfolio aggregate/persistence/bounded transitions, dataset identity and
publication, provider abstraction/scoped qualification, research ledger and
limited non-economic statistics. Selected DEC/ADR and RFC-006 are preserved as
design evidence. SSPL is a methodological case under
`case-studies/single-stock-pattern-lab/`, not the project identity.

See [actual status matrix](docs/module-status.md). Source presence does not imply
that original historical outcomes remain reproducible.

## Original vs New

59 unchanged original code/contract files selected from verified Archive HEAD
`8378e0845a89a204b4c10599d8da282bb541b438`, plus four package-export adaptations
and four navigation-only governance-document adaptations. The
[source index](provenance/source-index.json) binds original/adapted hashes.
The algorithms are not claimed to be newly written demos.

`public_demo` and the public tests are independently authored
REIMPLEMENTED_DEMO composition using invented observations and scripted intents
with the original engines. No historical series was transformed into a fixture.

## Excluded

Original Git objects/history, all real provider observations, reconstructable
derivatives, original tests of uncertain fixture provenance, historical AI
responses, economic/episode outcome payloads, private configurations/credentials,
account state, binaries and private local paths. Source for live Satellite,
financial/event pipelines, large study orchestration and SSPL evaluators remains
out of this public subset; source existence is not represented as a public
end-to-end capability. `data_loader.py` was not preserved in the verified Archive.

## Verification

The selected package builds as wheel and source distribution locally. All 22
synthetic tests passed on Python 3.12, including next-open Replay, cash/position transitions, exact repeated and
fresh-process output, bounded future-row exclusion, duplicate/nonfinite rejection,
qualification with missing/available scoped evidence, canonical serialization,
unsupported action blocking, cash rejection, event immutability and explicit
refusal to treat synthetic data as historical evidence. Final exact counts and
checksums are recorded in the
[verification record](provenance/release-verification.json). A clean isolated
wheel installation passed all 22 tests and `pip check`, using pandas 2.3.3,
PyArrow 23.0.1 and PyYAML 6.0.3. The original Archive's 63 selected source/contract
hashes were checked separately; its HEAD and clean status remain unchanged.

Security checks cover tracked files and all newly created Git-history blobs,
source hashes, no external object alternates, text-only scope, no credentials or
personal paths, file-size limits and local Markdown links. Scans are heuristic,
not a forensic absence guarantee. Commit identities are now checked explicitly
for public noreply addresses, rather than omitted from the gate.
No real market or investment-model call occurs.

## License Decision

Public-code selection is separate from private retention approval. Real-data
and historical AI-derived reports/numerical summaries remain excluded. Public
methodology and owner status do not purport to redistribute original analyses.
See [data rights](docs/data-rights.md). The publication permission is not silently
turned into a broad open-source or third-party-data license. Source is available
for inspection under the conservative [release license](LICENSE); dependencies
retain their own licenses.

## Git HEAD and Final Archive Index

Verified code HEAD: `7985e44a932de24cb7bad1c38e229de33faa8401`.
This report/index-only follow-up has a later commit; resolve its current HEAD
with `git rev-parse HEAD` or the repository's main commit link. The verification
record binds the tested code revision. The repository starts with a new root,
not the original or private Archive history. The final included/excluded file
index is [release index](provenance/release-index.json); original source evidence
is [source index](provenance/source-index.json). Build outputs and local virtual
environments are not part of public Git history.

## Stop Boundary

The requested source release is complete. No further research, historical data
acquisition, license cleanup, or other project change is authorized by this
report. This public scope uses a conservative source-available license; a broader
open-source grant or numerical historical-result publication needs separate
owner/provider clearance.
No old research, cleanup, private Archive editing, real trading or Alpha promotion
is part of this release. If a conflicting target or new license/secret risk is
found, stop rather than overwrite or relax the release scope.
