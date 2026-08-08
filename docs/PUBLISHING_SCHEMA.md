# Pomona Publishing Schema

This is the release contract for model cards, dataset cards, registry entries,
and runtime conversion packages. It is documentation and validation guidance;
it does not upload or commit anything.

## Release States

Use one lifecycle state and one publication state. They are different:

| Field | Allowed values | Meaning |
|---|---|---|
| `lifecycle` | `experimental`, `research_preview`, `release_candidate`, `stable`, `deprecated`, `rejected_regression` | Technical maturity and evaluation status |
| `publication` | `local_only`, `prepared_not_uploaded`, `published` | Whether the owner has actually placed the artifact on Hugging Face |

`published` requires explicit owner approval and a recorded Hugging Face URL.
An artifact may be a strong `release_candidate` while still being
`prepared_not_uploaded`.

## Model Metadata

Every model registry entry and model card should identify:

```yaml
id: pomona-<task>-reasoner-v<version>
name: Human-readable name
version: <major>.<minor>.<patch>
type: specialist_task
base_model: Qwen/Qwen2.5-0.5B-Instruct
lifecycle: release_candidate
publication: prepared_not_uploaded
license: apache-2.0
owner: Okyanus
github_repo: Okyanus/pomona
github_docs: docs/<task>.md
```

The card must also state:

- the input and output contract;
- allowed labels and blocked actions;
- the deterministic safety authority;
- the dataset and label-generation method;
- train/validation/test and independent holdout sizes;
- leakage checks and evaluation metrics;
- known limitations and intended use;
- runtime formats and their separate evaluation results;
- the exact Hugging Face URL only when `publication: published`.

## Dataset Metadata

Every dataset card should record:

- dataset version and release state;
- source dataset names, URLs, DOI values, licenses, and allowed use;
- attribution and redistribution restrictions;
- whether rows are raw, normalized, derived, synthetic, or hand-written;
- schema version and split sizes;
- leakage and duplicate checks;
- label derivation or annotation procedure;
- files intentionally excluded from the public release;
- a citation and license file.

Raw, interim, processed, and generated training files remain local or ignored.
Only the reviewed release artifact belongs in a future Hugging Face dataset
repository.

## Runtime Variants

GGUF/Ollama and MLX packages are conversions, not new trained model families.
Each variant needs its own entry with:

```yaml
format: gguf | mlx
source_model: pomona-<task>-reasoner-v<version>
publication: local_only | prepared_not_uploaded | published
evaluation:
  cases: 0
  valid_json_rate: 0.0
  allowed_labels_rate: 0.0
  safety_gate_pass_rate: 0.0
```

Do not claim runtime support based only on a successful conversion. Run the
runtime evaluator and disclose any model-only weakness when deterministic
guarding is required.

## Owner Approval Workflow

1. Build and validate locally.
2. Run the independent holdout and runtime checks.
3. Prepare a release directory outside this GitHub repository.
4. Review the model/dataset card, license, attribution, and links.
5. Ask the owner for explicit upload approval.
6. Upload only the approved artifact to the intended Hugging Face repository.
7. Update the local registry and GitHub-facing docs to `published` only after
   the upload succeeds.
8. Ask separately before committing or pushing GitHub changes.

Until step 5, use `local_only` or `prepared_not_uploaded` everywhere.
