# Publish scripts

| Script | Target |
|--------|--------|
| `check.sh` | Pre-flight before any upload |
| `github.sh` | **Platform** → GitHub (`pomona`) |
| `huggingface.sh` | **Weights** → Hugging Face |

**Multi-repo layout:** platform and ML training should be **separate GitHub repos**.  
See [docs/MULTI_REPO.md](../../docs/MULTI_REPO.md).

```bash
# Platform repo (this folder)
./scripts/publish/github.sh

# Weights (from any clone that has the adapter)
HF_TOKEN=hf_... ./scripts/publish/huggingface.sh

# ML training repo — after split, push from pomona-agronomist-llm/ separately
```
