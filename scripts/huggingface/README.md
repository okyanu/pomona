# Hugging Face publish scripts

Local helpers that copy **release artifacts** into `~/Desktop/hf-repos/` checkouts. They do not replace GitHub publishing.

| Script | HF target | Run when |
|--------|-----------|----------|
| `publish_tomato_reasoner_to_hf.sh` | [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) | **New adapter checkpoint only** — skip if v0.1.7 is already live |
| `publish_water_irrigation_reasoner_to_hf.sh` | [Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) | Release-candidate adapter only |
| `publish_actuator_command_gate_reasoner_to_hf.sh` | [Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora) | Research preview; deterministic gate remains final |
| `publish_dataset_to_hf.sh` | [Okyanus/pomona-tomato-risk-v0.1](https://huggingface.co/datasets/Okyanus/pomona-tomato-risk-v0.1) | JSONL or schema changes ready for dataset release |

Set `PUSH_TO_HF=1` to commit/push after reviewing the local HF checkout.

Full matrix of what belongs where: [docs/PUBLISHING.md](../docs/PUBLISHING.md).
