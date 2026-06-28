# Model registry

Metadata only — **no training code, no weights**.

Each `*.yaml` file describes a model Pomona can use at runtime. Weights are loaded from Hugging Face.

| File | Hugging Face |
|------|--------------|
| `agronomist-gemma4.yaml` | [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) |

Training code lives in a separate GitHub repo: [pomona-agronomist-llm](https://github.com/Okyanus/pomona-agronomist-llm).

Future models add a new YAML here (e.g. `tomato-reasoner-v1.yaml`).
