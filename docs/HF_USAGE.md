# Using the Hugging Face model

Platform registry: `models/registry/agronomist-gemma4.yaml`  
HF weights: [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4)

---

## Why default is `stub`, not Hugging Face

The platform **links** to your HF repo but does **not** load weights by default because:

| Reason | Detail |
|--------|--------|
| **LoRA adapter** | Your repo is a LoRA on `google/gemma-4-E2B-it` — not a tiny standalone model |
| **Heavy runtime** | Full local inference needs GPU + PyTorch + ~8GB+ VRAM |
| **Gated base model** | Base Gemma may require HF account + token |
| **No serverless provider** | HF page shows no Inference Provider deployed yet |
| **Works offline** | `stub` lets anyone clone and run without GPU or token |

So: **HF repo = where weights live**. **Pomona platform = how you run the stack.** They connect when you configure a backend.

---

## Three ways to use the real model

### 1. Hugging Face Inference API (easiest if provider exists)

In `.env`:

```bash
POMONA_LLM_BACKEND=huggingface
HF_TOKEN=hf_your_read_token
```

Restart:

```bash
./scripts/down.sh && ./scripts/up.sh
make advisor
```

Pomona calls the HF Inference API for `Okyanus/ai-pomona-agronomist-gemma4`.

**If it fails:** enable an [Inference Provider](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) on the model page, or create an [Inference Endpoint](https://huggingface.co/docs/inference-endpoints).

### 2. Local GPU (full quality)

From the ML repo `pomona-agronomist-llm`:

```bash
pip install -r deploy/requirements.txt
HF_TOKEN=hf_... python deploy/app.py
```

Gradio UI with transformers + PEFT — not inside the light Docker stack.

### 3. Ollama (when GGUF export exists)

```bash
POMONA_LLM_BACKEND=ollama
# Ollama running on host with compatible model
```

---

## What Pomona stores vs what HF stores

```text
pomona/models/registry/agronomist-gemma4.yaml   ← metadata (repo ID, safety, inputs)
huggingface.co/Okyanus/ai-pomona-agronomist-gemma4 ← weights + model card
```

Cloning `pomona` does **not** download GB of weights — that's intentional.

---

## Recommended setup for demos

| Audience | Backend |
|----------|---------|
| Anyone cloning (no GPU) | `stub` (default) |
| You with HF token + inference | `huggingface` |
| You with GPU | `pomona-agronomist-llm/deploy/app.py` |

---

## Enable HF for basic usage (checklist)

1. Create HF token: https://huggingface.co/settings/tokens (read access)
2. Accept license on base model if gated: `google/gemma-4-E2B-it`
3. Request/enable Inference Provider on your model page
4. Set in `.env`: `POMONA_LLM_BACKEND=huggingface` and `HF_TOKEN=hf_...`
5. `./scripts/up.sh` and `make advisor`

If inference still fails, use stub for platform demo and Gradio for real model demo until HF Endpoint is ready.
