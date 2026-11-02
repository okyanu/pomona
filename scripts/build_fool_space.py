#!/usr/bin/env python3
"""Fill spaces/try-to-fool-pomona/vendor/ with the exact repo files the "Try to fool Pomona" Space runs.

The Space is its own Hugging Face repo, so it cannot import from this one: the real code is copied in, byte for
byte, in the layout `examples/simulators/inprocess_pomona.py` expects (it finds the model-router, Core and
automation-engine files relative to its own location). `vendor/` is generated, never committed.

  build_fool_space.py           rebuild vendor/ and write vendor/BUILD_INFO.json (commit, dirty flag, sha256 per file)
  build_fool_space.py --check   fail when a vendored file no longer matches the repo (or the file list changed)

Stdlib only. The model-router `app` package is copied as the import closure of `app.pipeline`.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "spaces" / "try-to-fool-pomona"
VENDOR = SPACE / "vendor"
ROUTER = Path("services/model-router")

# Files copied as they are. The model-router closure below adds the rest of `app/`.
FIXED = [
    "examples/simulators/inprocess_pomona.py",          # the engine
    "examples/simulators/fake_greenhouse.py",            # the simulator (stdlib only)
    "scripts/score_fake_greenhouse.py",                  # the Grader (imports inprocess_pomona by name)
    "services/core/app/trusted_baseline.py",             # Core's sticky trusted baseline (loaded by path)
    "services/automation-engine/app/alerts.py",          # the alert monitor (loaded by path)
    "services/automation-engine/app/rules.yaml",         # the real card rules
    "services/automation-engine/app/config.py",          # alert window defaults (read as text)
    "services/safety-checker/app/actuator_gate_rules.py",  # loaded by path from model-router shared_chain.py
]


def router_closure() -> List[str]:
    """Repo paths of the model-router modules that `app.pipeline` imports, directly or not (AST walk)."""
    app_root = ROOT / ROUTER

    def module_file(module: str) -> Path:
        base = app_root.joinpath(*module.split("."))
        return base / "__init__.py" if base.is_dir() else base.with_suffix(".py")

    seen: Set[str] = set()
    todo = ["app.pipeline"]
    while todo:
        module = todo.pop()
        if module in seen:
            continue
        path = module_file(module)
        if not path.exists():
            raise SystemExit(f"model-router module {module} not found at {path}")
        seen.add(module)
        parts = module.split(".")
        todo += [".".join(parts[:i]) for i in range(1, len(parts))]  # parent packages (their __init__)
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                todo += [alias.name for alias in node.names if alias.name.split(".")[0] == "app"]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "app":
                todo.append(node.module)
                todo += [f"{node.module}.{alias.name}" for alias in node.names
                         if module_file(f"{node.module}.{alias.name}").exists()]  # `from app import pipeline`
    return sorted(str(module_file(m).relative_to(ROOT)) for m in seen)


def source_files() -> List[str]:
    return sorted(set(FIXED + router_closure()))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False).stdout


def build_info(files: List[str]) -> Dict[str, object]:
    commit = git("rev-parse", "HEAD").strip() or "unknown"
    dirty = [line[3:] for line in git("status", "--porcelain", "--", *files).splitlines()]
    return {"commit": commit, "short_commit": commit[:7], "dirty": bool(dirty), "dirty_files": sorted(dirty),
            "files": {name: sha256(ROOT / name) for name in files}}


def build() -> int:
    files = source_files()
    missing = [name for name in files if not (ROOT / name).is_file()]
    if missing:
        print(f"missing source files: {missing}", file=sys.stderr)
        return 1
    if VENDOR.exists():
        shutil.rmtree(VENDOR)
    for name in files:
        target = VENDOR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    info = build_info(files)
    (VENDOR / "BUILD_INFO.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
    state = "with uncommitted changes in " + ", ".join(info["dirty_files"]) if info["dirty"] else "clean"
    print(f"vendor/: {len(files)} files from commit {info['short_commit']} ({state})")
    return 0


def check() -> int:
    """Every vendored file must be a byte-for-byte copy of its repo file, and nothing else may be in vendor/."""
    info_path = VENDOR / "BUILD_INFO.json"
    if not info_path.is_file():
        print("vendor/BUILD_INFO.json is missing: run scripts/build_fool_space.sh", file=sys.stderr)
        return 1
    info = json.loads(info_path.read_text())
    expected = source_files()
    problems = []
    if sorted(info["files"]) != expected:
        problems.append("the vendored file list differs from what the engine needs now: "
                        f"{sorted(set(info['files']) ^ set(expected))}")
    for name in expected:
        vendored, source = VENDOR / name, ROOT / name
        if not vendored.is_file():
            problems.append(f"{name}: not vendored")
        elif sha256(vendored) != sha256(source):
            problems.append(f"{name}: differs from the repo file")
        elif info["files"].get(name) != sha256(vendored):
            problems.append(f"{name}: BUILD_INFO.json hash is stale")
    on_disk = {str(p.relative_to(VENDOR)) for p in VENDOR.rglob("*")
               if p.is_file() and "__pycache__" not in p.parts and p.name != "BUILD_INFO.json"}
    extra = sorted(on_disk - set(expected))
    if extra:
        problems.append(f"unexpected files in vendor/: {extra}")
    for problem in problems:
        print(f"vendor check: {problem}", file=sys.stderr)
    if not problems:
        print(f"vendor check: {len(expected)} files match the repo (commit {info['short_commit']})")
    return 1 if problems else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify vendor/ against the repo instead of rebuilding")
    sys.exit(check() if parser.parse_args().check else build())
