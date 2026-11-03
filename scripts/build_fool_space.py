#!/usr/bin/env python3
"""Build the static "Try to fool Pomona" Space folder (spaces/try-to-fool-pomona/). Everything it generates is gitignored.

The Space is its own Hugging Face repo, so it cannot import from this one: the real code is copied in, byte for
byte, in the layout `examples/simulators/inprocess_pomona.py` expects (it finds the model-router, Core and
automation-engine files relative to its own location). The page runs that code in the visitor's browser with Pyodide,
all of it served from the Space itself (no CDN at runtime).

  vendor/                 the repo's engine files + vendor/BUILD_INFO.json (commit, dirty flag, sha256 per file)
  pomona.zip              game.py + engine_api.py + vendor/, what the worker unpacks into Pyodide's file system
  pyodide/                the pinned Pyodide files the page loads (runtime, standard library, lock file, the packages)
  wheels/                 the two pure-Python PyPI wheels Pyodide does not ship (pydantic-settings, python-dotenv)

  build_fool_space.py           rebuild all of it (downloads missing pinned files, checks their sha256)
  build_fool_space.py --check   fail when a vendored file no longer matches the repo, a pinned file is missing, has
                                the wrong hash or is not on the list, or pomona.zip is out of date

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
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "spaces" / "try-to-fool-pomona"
VENDOR = SPACE / "vendor"
PYODIDE_DIR = SPACE / "pyodide"
WHEELS_DIR = SPACE / "wheels"
APP_ZIP = SPACE / "pomona.zip"
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


# What the page loads, pinned: Pyodide 314.0.7 (Python 3.14) and the packages the engine imports. sha256 of every file.
PYODIDE_VERSION = "314.0.7"
PYODIDE_BASE = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
PYODIDE_FILES: Dict[str, str] = {
    "pyodide.mjs": "6f1d60f7bf529beb300f0f47983c921d3982363640ba20af0e38efdddbc66109",
    "pyodide.asm.mjs": "f7cdc8ece80678ceb712f8e65ebe6d3a83203a180c399865f49612a051693635",
    "pyodide.asm.wasm": "cc36e3cab04fdfc9a63ff13eb52eae2b911bf46c025cc7b281f394bd3de1d5e6",
    "python_stdlib.zip": "fa1957e5777068fc4f7437f96d860ae2fbe9c19732ba06c84e004ec16dd7dd7a",
    "pyodide-lock.json": "5dc2fc119108bc148c7457dc86e7675b5c87e1cafd420b9c34c1eaef7b36c010",
    # packages from the lock file (pydantic, httpx and their dependencies)
    "annotated_types-0.7.0-py3-none-any.whl": "6541523b4b16c1953d2fc9b82fb86c540eea9f78fca329ab371ed13a8b0faa51",
    "anyio-4.13.0-py3-none-any.whl": "ea08c971f29d33d940864407ceb08601836ac8924d3b4f27db6612ed47faeafc",
    "certifi-2026.4.22-py3-none-any.whl": "c2c0091986db798df5fd84582d289496f31244a898ec032b7015278c2d82c80c",
    "h11-0.16.0-py3-none-any.whl": "d920caa25363694bc8de71ba42e5e2bc3353c8df6bcf5025551386e279bca264",
    "httpcore-1.0.9-py3-none-any.whl": "27bc91994ad7e21a8333608b8ba5e2b9655ae9d86820d4cefb03dd8db8c5de48",
    "httpx-0.28.1-py3-none-any.whl": "830cb1ec73bb4c46f2e38ebeb3dd50ffb45f62b804dd040519d34fe36f8fdfc7",
    "idna-3.11-py3-none-any.whl": "1619419bc899f07c7a608a12e8238e5e0bc15bb25fec90cfe20a86bb849ba0d8",
    "pydantic-2.12.5-py3-none-any.whl": "04854875001e07a8a74d87b7c80296cba168773d8c9804e232d695f82484d7d7",
    "pydantic_core-2.41.5-cp314-cp314-pyemscripten_2026_0_wasm32.whl":
        "54703fa42a0d4d574283cfb8f08050ba7820c9a42b0a21bc1286407d9a9e54da",
    "sniffio-1.3.1-py3-none-any.whl": "1e0f350ca8eac5252c1af9a8d93a7edd70056c1eddf5661f6950688094d1f670",
    "typing_extensions-4.15.0-py3-none-any.whl": "4fec68770a05408e668a4fa53d6bf4f0f684b9dacf820c7c5d6e97d3ad225e29",
    "typing_inspection-0.4.2-py3-none-any.whl": "deb989630985f7a7296b90357a947a804a7612cecbb6439d6e71128e01f61051",
}
PYPI_WHEELS: Dict[str, Tuple[str, str]] = {  # file name -> (url, sha256)
    "pydantic_settings-2.11.0-py3-none-any.whl": (
        "https://files.pythonhosted.org/packages/83/d6/887a1ff844e64aa823fb4905978d882a633cfe295c32eacad582b78a7d8b/"
        "pydantic_settings-2.11.0-py3-none-any.whl",
        "fe2cea3413b9530d10f3a5875adffb17ada5c1e1bab0b2885546d7310415207c"),
    "python_dotenv-1.2.4-py3-none-any.whl": (
        "https://files.pythonhosted.org/packages/60/d1/38f3a3405989a89ac18390803e70c6ad7c7760da4f9b83cbeca0c44a0c72/"
        "python_dotenv-1.2.4-py3-none-any.whl",
        "42269a8a5b3fd54ffa6f3d84b18abed50064717576b4ecf03dc4a55d8aa04fdc"),
}
ZIP_DATE = (2026, 1, 1, 0, 0, 0)  # fixed, so pomona.zip is byte-identical for identical inputs


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
    try:
        fetch_pinned()
    except (OSError, ValueError) as error:
        print(f"download failed: {error}", file=sys.stderr)
        return 1
    build_zip()
    return 0


def fetch_pinned() -> None:
    """Download the pinned Pyodide and PyPI files that are missing or wrong, and verify every sha256."""
    wanted = [(PYODIDE_DIR, name, PYODIDE_BASE + name, digest) for name, digest in PYODIDE_FILES.items()]
    wanted += [(WHEELS_DIR, name, url, digest) for name, (url, digest) in PYPI_WHEELS.items()]
    fetched = 0
    for folder, name, url, digest in wanted:
        target = folder / name
        if target.is_file() and sha256(target) == digest:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        print(f"downloading {url}")
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (pinned https URLs)
            data = response.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"{name}: sha256 does not match the pinned value")
        partial = target.with_name(target.name + ".part")
        partial.write_bytes(data)
        partial.replace(target)
        fetched += 1
    for folder, names in ((PYODIDE_DIR, set(PYODIDE_FILES)), (WHEELS_DIR, set(PYPI_WHEELS))):
        for path in folder.iterdir():
            if path.name not in names:
                path.unlink()  # not on the pinned list: the Space ships only what the page loads
    total = sum(p.stat().st_size for d in (PYODIDE_DIR, WHEELS_DIR) for p in d.iterdir())
    print(f"pyodide/ + wheels/: {len(wanted)} pinned files, {total / 1e6:.1f} MB ({fetched} downloaded)")


def zip_members() -> Dict[str, Path]:
    """pomona.zip content: archive name -> file on disk. game.py and engine_api.py at the top, vendor/ beside them."""
    members = {"game.py": SPACE / "game.py", "engine_api.py": SPACE / "engine_api.py"}
    for path in sorted(VENDOR.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            members[path.relative_to(SPACE).as_posix()] = path
    return members


def build_zip() -> None:
    with zipfile.ZipFile(APP_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(zip_members().items()):
            entry = zipfile.ZipInfo(name, ZIP_DATE)
            entry.compress_type, entry.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            archive.writestr(entry, path.read_bytes(), compresslevel=9)
    print(f"pomona.zip: {len(zip_members())} files, {APP_ZIP.stat().st_size / 1e3:.0f} KB")


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
    problems += check_pinned() + check_zip()
    for problem in problems:
        print(f"vendor check: {problem}", file=sys.stderr)
    if not problems:
        print(f"vendor check: {len(expected)} files match the repo (commit {info['short_commit']}); "
              f"{len(PYODIDE_FILES) + len(PYPI_WHEELS)} pinned Pyodide/PyPI files and pomona.zip are in order")
    return 1 if problems else 0


def check_pinned() -> List[str]:
    problems = []
    for folder, pinned in ((PYODIDE_DIR, PYODIDE_FILES), (WHEELS_DIR, {k: v[1] for k, v in PYPI_WHEELS.items()})):
        for name, digest in pinned.items():
            path = folder / name
            if not path.is_file():
                problems.append(f"{path.relative_to(SPACE)}: missing (run scripts/build_fool_space.sh)")
            elif sha256(path) != digest:
                problems.append(f"{path.relative_to(SPACE)}: sha256 differs from the pinned value")
        extra = sorted(p.name for p in folder.iterdir() if p.name not in pinned) if folder.is_dir() else []
        if extra:
            problems.append(f"unexpected files in {folder.name}/: {extra}")
    return problems


def check_zip() -> List[str]:
    if not APP_ZIP.is_file():
        return ["pomona.zip: missing (run scripts/build_fool_space.sh)"]
    members = zip_members()
    with zipfile.ZipFile(APP_ZIP) as archive:
        names = sorted(archive.namelist())
        if names != sorted(members):
            return [f"pomona.zip: file list differs from the Space's files: {sorted(set(names) ^ set(members))}"]
        stale = [name for name, path in members.items() if archive.read(name) != path.read_bytes()]
    return [f"pomona.zip: {name} is out of date (run scripts/build_fool_space.sh)" for name in stale]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify vendor/ against the repo instead of rebuilding")
    sys.exit(check() if parser.parse_args().check else build())
