"""Parity checks for constants and functions copied across services.

The services cannot import each other, so the dashboard keeps copies of the router's veto labels and of
Core's ``alert_detail``. These tests read the source files as text and fail when the copies drift apart.
"""

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ROUTER_TRUST_GATE = REPO_ROOT / "services/model-router/app/trust_gate.py"
DASHBOARD_MAIN = REPO_ROOT / "services/dashboard/app/main.py"
CORE_OUTCOME_FEED = REPO_ROOT / "services/core/app/outcome_feed.py"


def _global_veto_labels(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "GLOBAL_VETO_LABELS" for t in node.targets):
            values.append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "GLOBAL_VETO_LABELS" and node.value is not None:
            values.append(node.value)
    assert len(values) == 1, f"expected one GLOBAL_VETO_LABELS assignment in {path}, found {len(values)}"
    value = values[0]
    # The dashboard writes frozenset({...}); the router writes a plain set literal.
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in ("frozenset", "set") and len(value.args) == 1 and not value.keywords:
        value = value.args[0]
    return set(ast.literal_eval(value))


def _function_source(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(matches) == 1, f"expected one top-level def {name} in {path}, found {len(matches)}"
    func = matches[0]
    # Docstrings may differ between the copies; only the code is compared.
    if func.body and isinstance(func.body[0], ast.Expr) and isinstance(func.body[0].value, ast.Constant) and isinstance(func.body[0].value.value, str):
        func.body = func.body[1:]
    return ast.unparse(func)


def test_global_veto_labels_match_router():
    router_labels = _global_veto_labels(ROUTER_TRUST_GATE)
    dashboard_labels = _global_veto_labels(DASHBOARD_MAIN)
    assert router_labels, "router GLOBAL_VETO_LABELS is empty"
    assert dashboard_labels == router_labels


def test_alert_detail_matches_core():
    assert _function_source(DASHBOARD_MAIN, "alert_detail") == _function_source(CORE_OUTCOME_FEED, "alert_detail")
