#!/usr/bin/env python3
"""Classify worktree changes without staging, deleting, or publishing files."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

NEVER_PREFIXES = (
    "private/",
    "datasets/raw/",
    "datasets/interim/",
    "datasets/processed/",
    "backups/",
    "data/",
    "volumes/",
    "secrets/",
    "models/checkpoints/",
)
NEVER_SUFFIXES = (
    ".7z",
    ".bin",
    ".ckpt",
    ".db",
    ".docx",
    ".gguf",
    ".ipynb",
    ".key",
    ".pdf",
    ".pem",
    ".pt",
    ".pth",
    ".safetensors",
    ".zip",
)
ML_PREFIXES = (
    "scripts/datasets/",
    "scripts/huggingface/",
    "scripts/models/",
)
LOCAL_SENSITIVE_PREFIXES = (
    "docs/INFOQ_",
)
LOCAL_SENSITIVE_PATHS = {
    "docs/POMONA_MASTER_ROADMAP.md",
    "scripts/benchmark_article_runtime.py",
    "scripts/build_article_evidence.py",
    "scripts/capture_article_scenarios.py",
    "scripts/run_article_demo.sh",
}
TRACKED_REDACTION_PATHS = {
    "docs/EXECUTION_PLAN.md",
    "docs/UNPUBLISHED_MODEL_RELEASES.md",
}


@dataclass(frozen=True)
class Change:
    path: str
    state: str
    category: str
    batch: str
    reason: str
    size_bytes: int


def git_paths(*args: str) -> set[str]:
    result = subprocess.run(
        ["git", *args, "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return {
        item.decode("utf-8", "surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    }


def current_changes() -> dict[str, set[str]]:
    return {
        "staged": git_paths("diff", "--cached", "--name-only"),
        "modified": git_paths("diff", "--name-only"),
        "untracked": git_paths("ls-files", "--others", "--exclude-standard"),
        "ignored_local": local_sensitive_inventory(),
    }


def state_for(path: str, states: dict[str, set[str]]) -> str:
    present = [
        name
        for name in ("staged", "modified", "untracked", "ignored_local")
        if path in states[name]
    ]
    return "+".join(present)


def local_sensitive_inventory() -> set[str]:
    paths = {
        path.relative_to(ROOT).as_posix()
        for pattern in ("docs/INFOQ_*", "docs/assets/pomona-safety-architecture.*")
        for path in ROOT.glob(pattern)
        if path.is_file()
    }
    paths.update(
        path
        for path in LOCAL_SENSITIVE_PATHS
        if (ROOT / path).is_file()
    )
    return paths


def classify(path: str) -> tuple[str, str, str]:
    lower = path.lower()
    if (
        path == ".env"
        or path.startswith(NEVER_PREFIXES)
        or lower.endswith(NEVER_SUFFIXES)
        or (path.startswith("assets/") and path != "assets/README.md")
    ):
        return (
            "never_commit",
            "blocked_local_artifact",
            "Secret, private, raw, runtime, archive, or model artifact.",
        )

    if path.startswith("datasets/pomona-"):
        return (
            "hold_for_ml_repo",
            "ml_dataset_release",
            "Dataset and training artifacts are owned by the ML workflow.",
        )
    if path.startswith(ML_PREFIXES):
        return (
            "hold_for_ml_repo",
            "ml_training_tooling",
            "Training, evaluation, conversion, and HF publishing belong in the ML repo.",
        )

    if (
        path.startswith(LOCAL_SENSITIVE_PREFIXES)
        or path.startswith("docs/assets/pomona-safety-architecture.")
        or path in LOCAL_SENSITIVE_PATHS
    ):
        return (
            "local_sensitive",
            "local_publication_and_planning",
            "Owner draft, evidence, visual, or roadmap; keep outside open-source Git.",
        )

    if path in TRACKED_REDACTION_PATHS:
        return (
            "tracked_redaction_review",
            "tracked_operational_notes",
            "Already tracked; redact local paths and unpublished operational detail before commit.",
        )

    if path.startswith("services/"):
        return (
            "platform_candidate",
            "platform_services",
            "Runtime service code, configuration, or tests.",
        )
    if path.startswith(("schemas/", "examples/scenarios/")):
        return (
            "platform_candidate",
            "contracts_and_scenarios",
            "Public platform contracts and reproducible scenarios.",
        )
    if path.startswith("models/registry/"):
        return (
            "platform_candidate",
            "model_registry",
            "Metadata only; model weights remain outside GitHub.",
        )
    if path.startswith("scripts/"):
        return (
            "platform_candidate",
            "platform_operations",
            "Platform validation, backup, simulation, or evidence tooling.",
        )
    if path.startswith("docs/"):
        return (
            "platform_candidate",
            "public_documentation",
            "Public platform documentation.",
        )
    if path.startswith("examples/"):
        return (
            "platform_candidate",
            "simulator",
            "Public platform simulator.",
        )
    if path in {".env.example", ".gitignore", "Makefile", "README.md", "docker-compose.yml"}:
        return (
            "platform_candidate",
            "platform_foundation",
            "Repository configuration or public entry-point documentation.",
        )
    return (
        "manual_review",
        "unclassified",
        "No explicit ownership rule matched this path.",
    )


def file_size(path: str) -> int:
    candidate = ROOT / path
    try:
        return candidate.stat().st_size if candidate.is_file() else 0
    except OSError:
        return 0


def build_plan() -> list[Change]:
    states = current_changes()
    paths = sorted(set().union(*states.values()))
    changes = []
    for path in paths:
        category, batch, reason = classify(path)
        changes.append(
            Change(
                path=path,
                state=state_for(path, states),
                category=category,
                batch=batch,
                reason=reason,
                size_bytes=file_size(path),
            )
        )
    return changes


def render_markdown(changes: list[Change]) -> str:
    by_category: dict[str, list[Change]] = defaultdict(list)
    by_batch: dict[str, list[Change]] = defaultdict(list)
    for change in changes:
        by_category[change.category].append(change)
        by_batch[change.batch].append(change)

    staged = [change for change in changes if "staged" in change.state]
    lines = [
        "# Local Commit Control Plan",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
        "",
        "This report does not stage, delete, commit, push, or upload anything.",
        "Do not use `git add .` for this worktree.",
        "",
        "## Summary",
        "",
        f"- Changed paths: {len(changes)}",
        f"- Platform candidates: {len(by_category['platform_candidate'])}",
        f"- Hold for ML repo: {len(by_category['hold_for_ml_repo'])}",
        f"- Local sensitive and ignored: {len(by_category['local_sensitive'])}",
        f"- Tracked redaction review: {len(by_category['tracked_redaction_review'])}",
        f"- Manual review: {len(by_category['manual_review'])}",
        f"- Never commit: {len(by_category['never_commit'])}",
        f"- Already staged: {len(staged)}",
        "",
    ]
    if staged:
        lines.extend(
            [
                "## Staging Warning",
                "",
                "Files are already staged. Review or unstage them before following this plan:",
                "",
                *[f"- `{change.path}`" for change in staged],
                "",
            ]
        )

    category_titles = (
        ("never_commit", "Never Commit"),
        ("local_sensitive", "Local Sensitive - Never GitHub"),
        ("tracked_redaction_review", "Tracked Files Requiring Redaction Review"),
        ("hold_for_ml_repo", "Hold For ML Repo"),
        ("manual_review", "Manual Review"),
        ("platform_candidate", "Platform Commit Candidates"),
    )
    for category, title in category_titles:
        items = by_category[category]
        lines.extend([f"## {title}", ""])
        if not items:
            lines.extend(["None.", ""])
            continue
        for batch in sorted({item.batch for item in items}):
            batch_items = [item for item in items if item.batch == batch]
            lines.extend([f"### `{batch}` ({len(batch_items)})", ""])
            for item in batch_items:
                size = f", {item.size_bytes} bytes" if item.size_bytes else ""
                lines.append(f"- `{item.path}` ({item.state}{size})")
            lines.append("")

    lines.extend(
        [
            "## Recommended Sequence",
            "",
            "1. Keep all `never_commit` paths ignored and outside Git history.",
            "2. Keep `local_sensitive` material ignored; publish it elsewhere only after a separate owner decision.",
            "3. Redact or deliberately retain every `tracked_redaction_review` file.",
            "4. Move or recreate `hold_for_ml_repo` work in `pomona-agronomist-llm` after ownership review.",
            "5. Resolve every `manual_review` item.",
            "6. Review and stage one platform batch at a time using explicit paths.",
            "7. Run `make local-check` and `make publish-check` before asking to commit.",
            "8. Commit or push only after explicit owner approval.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="private/COMMIT_PLAN.md",
        help="Ignored Markdown report path relative to the repository root.",
    )
    parser.add_argument(
        "--json-output",
        default="private/commit-plan.json",
        help="Ignored machine-readable report path relative to the repository root.",
    )
    parser.add_argument(
        "--check-staged",
        action="store_true",
        help="Fail unless staged paths are platform candidates.",
    )
    args = parser.parse_args()

    changes = build_plan()
    output = ROOT / args.output
    json_output = ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(changes) + "\n")
    json_output.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "changes": [asdict(change) for change in changes],
            },
            indent=2,
        )
        + "\n"
    )

    counts: dict[str, int] = defaultdict(int)
    for change in changes:
        counts[change.category] += 1
    print(f"Commit plan: {output}")
    print(f"JSON plan:   {json_output}")
    print(f"Changed paths: {len(changes)}")
    for category in (
        "platform_candidate",
        "hold_for_ml_repo",
        "local_sensitive",
        "tracked_redaction_review",
        "manual_review",
        "never_commit",
    ):
        print(f"{category}: {counts[category]}")
    print("No files were staged, deleted, committed, pushed, or uploaded.")
    if args.check_staged:
        staged = [change for change in changes if "staged" in change.state]
        if not staged:
            print("ERROR: no files are staged.")
            return 2
        blocked = [
            change for change in staged if change.category != "platform_candidate"
        ]
        if blocked:
            print("ERROR: staged files outside the public platform allow-list:")
            for change in blocked:
                print(f"  {change.category}: {change.path}")
            return 1
        print(f"Staged public-platform check: {len(staged)} paths passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
