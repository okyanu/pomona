# Publish scripts

| Script | Target |
|--------|--------|
| `commit_plan.py` | Classify worktree changes without staging or publishing |
| `check.sh` | Pre-flight before any upload |
| `github.sh` | **Platform** → GitHub (`pomona`) |
| `huggingface.sh` | **Weights** → Hugging Face |

**Multi-repo layout:** platform and ML training should be **separate GitHub repos**.  
See [docs/MULTI_REPO.md](../../docs/MULTI_REPO.md).

```bash
# Review the current worktree first; report is written under ignored private/
make commit-plan

# Platform repo (this folder)
git add <reviewed-explicit-platform-paths>
PUSH_TO_GITHUB=1 ./scripts/publish/github.sh push "your reviewed message"

# Weights (from any clone that has the adapter)
HF_TOKEN=hf_... ./scripts/publish/huggingface.sh

# ML training repo — after split, push from pomona-agronomist-llm/ separately
```

The GitHub helper never runs `git add`. It rejects staged files outside the
public-platform classification and refuses to commit or push unless
`PUSH_TO_GITHUB=1` is set after explicit owner approval.
