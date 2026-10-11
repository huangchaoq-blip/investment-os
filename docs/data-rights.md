# Data Rights and Release Scope

Reviewed on 2026-10-11. This is a conservative release decision, not legal advice
or a provider's individual clearance of retained artifacts.

J-Quants' official [usage FAQ](https://jpx-jquants.com/ja/help/usage) distinguishes
public descriptions of analysis methods from redistribution of source data.
Its cancellation/derivative and generative-AI provisions impose additional
constraints. The [Terms](https://jpx-jquants.com/ja/termsofservice) and
[subscription FAQ](https://jpx-jquants.com/ja/help/plan) must be read with the
user's contract. The Terms page was not retrievable during this release review;
no broader license interpretation is inferred from that failure.

## Allowed Release Classes

- Owner-authorized original algorithms/contracts without embedded observations.
- Separately authored engineering explanation and owner governance status.
- Independently generated synthetic examples and new mechanical tests.
- Code provenance checksums (not hashes of individual market observations).

## Excluded / Needs Provider Confirmation

No J-Quants raw or adjusted data, reconstructed derivatives, Parquet/CSV/DB,
real-data fixtures, per-security outcomes, episode distributions, historical
AI-generated investment judgments, charts or portfolio/account records are
included. Numerical historical research summaries are withheld, not assumed
publishable merely because they are aggregate or privately retainable. We do
not turn private Archive clearance into public clearance. No provider logo,
affiliation claim, credential or acquisition service is offered.

SSPL's case study publishes methodology and the owner's PAUSED/no-qualified-
strategy status, not original observation-derived/AI-generated reports.
If the provider's AI-result provision is interpreted to encompass even such
high-level governance descriptions, provider confirmation is required before
adding more detail; no substantive historical numerical output is released.

Dependency packages are not vendored; their own licenses govern their use.
The project's source-available license does not grant third-party data rights.
No blanket open-source grant is inferred from the user's authorization to publish.

## Dependency License Review

The clean local wheel environment used pandas 2.3.3 (BSD), PyArrow 23.0.1
(Apache-2.0), and PyYAML 6.0.3 (MIT). Build tooling used the `build` package
(MIT); setuptools and wheel have their own licenses. These are package-metadata
checks, not a grant covering every possible future dependency version.
No dependency implementation, provider SDK, or third-party dataset is vendored.
CI installs dependencies from the package registry under the declared constraints.
