#!/usr/bin/env bash
# Pre-flight checks before publishing to GitHub or Hugging Face.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

ERRORS=0

warn() { echo "WARN: $*"; }
fail() { echo "ERROR: $*"; ERRORS=$((ERRORS + 1)); }
ok()   { echo "OK:   $*"; }

echo "==> Pomona publish pre-flight"
echo ""

# --- Secrets ---
if [[ -f .env ]]; then
  if git check-ignore -q .env 2>/dev/null; then
    ok ".env exists and is gitignored"
  else
    fail ".env is NOT gitignored"
  fi
else
  warn ".env not found (copy from .env.example if needed)"
fi

SECRET_FOUND=0
for pattern in 'hf_[A-Za-z0-9]{20,}' 'ghp_[A-Za-z0-9]{20,}' 'github_pat_[A-Za-z0-9_]{20,}'; do
  if git grep -El "$pattern" -- ':!scripts/publish/*' ':!docs/*' ':!*.example' ':!.env.example' 2>/dev/null; then
    fail "Possible credential-shaped secret in tracked files matching: $pattern"
    SECRET_FOUND=1
  fi
done
if [[ "$SECRET_FOUND" -eq 0 ]]; then
  ok "No credential-shaped secrets in tracked source"
fi

# --- Protected trees: every file must be gitignored except explicit allow-list ---
# Matches .gitignore intent (private/**, assets/**, ML paths) without hardcoding filenames.
ALLOWED_TRACKED=(
  private/README.example.md
  assets/README.md
)

PROTECTED_TREES=(
  private
  assets
  models/checkpoints
  models/agronomist-llm
  research
)

file_is_allowed() {
  local f="$1"
  for allowed in "${ALLOWED_TRACKED[@]}"; do
    [[ "$f" == "$allowed" ]] && return 0
  done
  return 1
}

check_protected_tree() {
  local tree="$1"
  [[ -d "$tree" ]] || return 0

  local leaked=()
  local rel
  while IFS= read -r rel; do
    if file_is_allowed "$rel"; then
      continue
    fi
    leaked+=("$rel")
  done < <(git ls-files --cached --others --exclude-standard -- "$tree" 2>/dev/null)

  if [[ ${#leaked[@]} -gt 0 ]]; then
    fail "${tree}/* — ${#leaked[@]} file(s) would NOT be gitignored:"
    printf '       %s\n' "${leaked[@]}"
  else
    ok "${tree}/* — all files gitignored (except allowed templates)"
  fi
}

for tree in "${PROTECTED_TREES[@]}"; do
  check_protected_tree "$tree"
done

# Dry-run: nothing sensitive would be staged on `git add .`
if git rev-parse --git-dir >/dev/null 2>&1; then
  STAGE_LEAKED=()
  while IFS= read -r line; do
    [[ "$line" =~ ^add\ \'(.+)\'$ ]] || continue
    rel="${BASH_REMATCH[1]}"
    if file_is_allowed "$rel"; then
      continue
    fi
    for tree in "${PROTECTED_TREES[@]}"; do
      if [[ "$rel" == "$tree"/* || "$rel" == "$tree" ]]; then
        STAGE_LEAKED+=("$rel")
        break
      fi
    done
    case "$rel" in
      .env|.env.local|.env.*.local|*.pem|*.key|secrets/*|*.pdf|*.safetensors|*.pt|*.pth|*.ckpt|*.gguf|*.bin)
        STAGE_LEAKED+=("$rel")
        ;;
    esac
  done < <(git add -n . 2>&1)

  if [[ ${#STAGE_LEAKED[@]} -gt 0 ]]; then
    fail "git add . would stage protected file(s):"
    printf '       %s\n' "${STAGE_LEAKED[@]}"
  else
    ok "git add . would not stage private/assets/ML/secrets"
  fi
fi

# --- Large files that would be staged ---
if git rev-parse --git-dir >/dev/null 2>&1; then
  LARGE=$(git ls-files -z 2>/dev/null | xargs -0 -I{} sh -c 'test -f "{}" && test $(stat -f%z "{}" 2>/dev/null || stat -c%s "{}" 2>/dev/null) -gt 10485760 && echo "{}"' 2>/dev/null || true)
  if [[ -n "$LARGE" ]]; then
    fail "Files >10MB would be committed:"
    echo "$LARGE"
  else
    ok "No tracked files >10MB"
  fi
fi

# --- Tests (optional, skip with SKIP_TESTS=1) ---
if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "==> Running tests..."
    if make test >/dev/null 2>&1; then
      ok "Tests passed"
    else
      warn "Tests failed or dependencies missing — run: make test"
    fi
  fi
fi

echo ""
if [[ "$ERRORS" -gt 0 ]]; then
  echo "FAILED: $ERRORS error(s). Fix before publishing."
  exit 1
fi

echo "PASSED: Safe to publish."
echo ""
echo "Next:"
echo "  GitHub:      ./scripts/publish/github.sh"
echo "  HuggingFace: HF_TOKEN=hf_... ./scripts/publish/huggingface.sh"
