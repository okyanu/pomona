# Local Model Runtimes

Pomona keeps one reasoner API contract while allowing multiple local inference
runtimes. Runtime choice must not bypass deterministic safety checks.

## Water/Irrigation v0.1.8

Reference artifact:

```text
Qwen/Qwen2.5-0.5B-Instruct + Pomona PEFT LoRA adapter
```

Local generated artifacts are written under `private/models/`, which is
gitignored. Model weights, merged checkpoints, GGUF files, and MLX files must
not be committed to this repository.

### Ollama/GGUF

Prerequisites:

- an isolated Python environment with `torch`, `transformers`, `peft`, and
  `safetensors`;
- Ollama;
- a local `llama.cpp` checkout containing `convert_hf_to_gguf.py`.

```bash
LLAMA_CPP_DIR=~/Desktop/llama.cpp \
  ./scripts/models/build_water_irrigation_ollama.sh
```

Then configure `.env`:

```text
REASONER_BACKEND=ollama
WATER_IRRIGATION_OLLAMA_MODEL=pomona-water-irrigation:v0.1.8
```

### MLX

MLX runs on the macOS host so it can use Apple Metal directly.

```bash
Q_BITS=8 ./scripts/models/build_water_irrigation_mlx.sh
mlx_lm.server \
  --model private/models/mlx/water-irrigation-v0.1.8-8bit \
  --port 8083
```

Then configure `.env`:

```text
REASONER_BACKEND=mlx
MLX_HOST=http://host.docker.internal:8083
WATER_IRRIGATION_MLX_MODEL=
```

The MLX HTTP server is intended for local development and is not a hardened
production endpoint.

The unified `POST /v1/pipeline/evaluate` endpoint uses the configured local
backend for its water/irrigation specialist when the request mode is
`hybrid_guarded`:

```text
REASONER_BACKEND=ollama
WATER_IRRIGATION_OLLAMA_MODEL=pomona-water-irrigation:v0.1.8
```

The pipeline always retains the deterministic guard. Rules authoritatively
control risk labels, blocked actions, missing or suspect fields, safe checks,
and human review; a local model cannot add a false positive or authorize an
operational action. Use `REASONER_BACKEND=rules` for the default offline path.

The v0.1.8 4-bit MLX conversion failed the frozen holdout and must not be used.
Use 8-bit as the current MLX evaluation candidate; accept it only after it
passes the same holdout as the reference adapter and Ollama model.

## Local Acceptance Results

Frozen independent holdout: 168 cases, 24 per category.

| Runtime | Precision | Label F1 | Blocked F1 | Review match | Time |
|---|---:|---:|---:|---:|---:|
| Ollama GGUF | F16 | 1.0000 | 1.0000 | 1.0000 | 97.14 s |
| MLX | 8-bit | 1.0000 | 1.0000 | 1.0000 | 80.47 s |
| MLX | 4-bit | 0.7262 | 0.9762 | 0.5536 | 62.75 s |

Both accepted deployment formats are published on Hugging Face:

- [GGUF/Ollama F16](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-GGUF)
- [MLX 8-bit](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-MLX)

MLX 4-bit is a rejected regression because it lost required fields,
high-moisture and anomaly labels, and human-review decisions. It was not
published. Detailed evaluation reports remain private under
`private/colab/outputs/`.

## Nutrient / pH-EC v0.1.1 Local Candidate

The accepted local Nutrient/pH-EC candidate is still unpublished. Prepare
deployment conversions only after keeping the independent 140-case adapter
evaluation as the reference baseline:

```bash
LLAMA_CPP_DIR=~/Desktop/llama.cpp \
  ./scripts/models/build_nutrient_ph_ec_ollama.sh

MODEL_PYTHON=private/venvs/pomona-mlx/bin/python \
  Q_BITS=8 ./scripts/models/build_nutrient_ph_ec_mlx.sh
```

These scripts write only to `private/models/`. The GGUF/Ollama and MLX artifacts
are prepared locally. The latest exact-prompt raw Ollama runtime failed the
140-case holdout with allowed-label rate `0.8571`, label F1 `0.6690`,
blocked-action F1 `0.8571`, and human-review match `0.8571`. The MLX 8-bit
smoke test scored label F1 `0.8667` and has not passed the full holdout. Both
packages are structurally uploadable as experimental artifacts, but neither
is an approved standalone runtime release. The guarded hybrid path now passes
the same full holdout at `1.0000` on every gate for both Ollama and MLX. The
deterministic guard remains mandatory for API/runtime integration.

## API

```bash
curl -s http://localhost:8081/v1/reasoners/water-irrigation-risk \
  -H 'Content-Type: application/json' \
  -d '{
    "mode": "hybrid_guarded",
    "backend": "ollama",
    "input": {
      "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
      "sensor": {"substrate_moisture_pct": 24.0},
      "expected_fields": ["substrate_moisture_pct"]
    }
  }'
```

Modes:

- `rules_only`: deterministic classifier only;
- `hybrid_guarded`: local model output validated and strengthened by rules;
- `model_only`: model output validated but not merged with rules; evaluation use
only.

## Tomato Risk v0.1.7 Local Candidates

Tomato v0.1.7 is trained to return a compact JSON **list** of allowed risk
labels. It is advisory-only; the platform's deterministic tomato rules and
safety checks remain responsible for building guarded operational responses.

The following commands prepare private local deployment candidates only. They
do not create or update a Hugging Face repository.

```bash
LLAMA_CPP_DIR=~/Desktop/llama.cpp \
  ./scripts/models/build_tomato_risk_ollama.sh

Q_BITS=8 ./scripts/models/build_tomato_risk_mlx.sh
```

Evaluate Ollama against the small golden smoke suite:

```bash
python3 scripts/models/evaluate_tomato_risk_runtime.py \
  --backend ollama \
  --model pomona-tomato-risk:v0.1.7-local \
  --split golden_eval \
  --output private/colab/outputs/tomato-risk-v0.1.7-ollama-golden.json
```

For MLX, run a local server first and then use `--backend mlx --host
http://127.0.0.1:8085`. The golden suite has 15 hand-selected cases; the
larger test split is development data and must not be described as an
independent release benchmark. No Tomato GGUF or MLX candidate is published
until the owner explicitly approves a release.

If an Ollama or MLX output is unavailable or invalid, `hybrid_guarded` falls
back to deterministic rules. Direct actuator control remains forbidden.
