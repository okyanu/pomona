# Pomona Versioning

Pomona versions the platform, models, datasets, and product phases separately.
A phase number is a roadmap milestone, not a software version.

## Platform Version

The GitHub platform follows semantic versioning:

```text
MAJOR.MINOR.PATCH[-PRERELEASE]
```

- `MAJOR`: incompatible public API, configuration, or deployment changes.
- `MINOR`: backward-compatible services, endpoints, or substantial workflows.
- `PATCH`: backward-compatible fixes and documentation corrections.
- `alpha.N`, `beta.N`, `rc.N`: maturity before a stable release.

The canonical human-readable version is in [`VERSION`](../VERSION). Python uses
the equivalent PEP 440 form in `pyproject.toml`.

Current platform release:

```text
v0.1.0-alpha.1
```

Git tags use the same value with a leading `v`, for example
`v0.1.0-alpha.1`.

## Model Versions

Each model family versions independently because training iterations do not
imply a new platform release:

```text
pomona-<task>-reasoner-v<MAJOR>.<MINOR>.<PATCH>-lora
```

- Increment `PATCH` for a new compatible checkpoint, focused correction, or
  evaluation-driven retraining that keeps the same input/output contract.
- Increment `MINOR` for new labels, changed thresholds, a materially different
  dataset contract, or new required fields.
- Increment `MAJOR` for an incompatible task or runtime contract.

Experiment numbers are chronological identifiers, not quality rankings. A
newer checkpoint can be rejected while an older version remains the retained
or published model.

Examples:

| Model | Version | Lifecycle |
|---|---|---|
| Tomato Risk Reasoner | `v0.1.7` | Published experimental specialist |
| Water/Irrigation Risk Reasoner | `v0.1.8` | Published release candidate |
| Actuator Command Gate | `v0.1.0` | Published research preview; below standalone gate |
| Actuator correction | `v0.1.2` | Rejected regression; not published |

## Dataset Versions

Datasets also version independently. Increment:

- `PATCH` for corrected metadata, documentation, or equivalent rows,
- `MINOR` for new records, labels, sources, splits, or schema additions,
- `MAJOR` for incompatible schemas or task definitions.

Every dataset release should record source licenses, transformation notes,
split-leakage checks, and a release date in its dataset card.

## Lifecycle Labels

Version numbers and lifecycle labels must both be shown:

| Label | Meaning |
|---|---|
| `experimental` | Early checkpoint; behavior still being explored |
| `research_preview` | Public for inspection, but below a release gate |
| `release_candidate` | Passed current numeric gates; real-world validation still limited |
| `stable` | Supported contract with field validation and operational documentation |
| `deprecated` | Still available but replaced; migration is recommended |
| `rejected_regression` | Failed evaluation; retained locally for comparison only |

No model lifecycle label grants actuator authority. Deterministic policy and
human authorization remain separate requirements.

## Release Checklist

For a platform release:

1. Update `VERSION` and `pyproject.toml` together.
2. Update `CHANGELOG.md` when one exists for the release line.
3. Run `make publish-check` and the service tests.
4. Commit the release metadata.
5. Create and push the matching Git tag.

For a model or dataset release, also update its registry YAML, model/dataset
card, evaluation summary, lifecycle label, and reciprocal GitHub/Hugging Face
links.
