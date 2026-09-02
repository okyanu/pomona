"""Pomona automation engine -- suggestions only, never direct actuator control.

Evaluates YAML rules against a guarded reasoner's risk labels and produces
human-approvable suggestions. Approving a suggestion only records a
decision; there is no execution path to any hardware or actuator in v0.1.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.rules import InvalidRuleError, evaluate_rules, load_rules
from app.store import suggestion_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

try:
    RULES = load_rules(settings.rules_path)
except InvalidRuleError as exc:
    logger.error("Refusing to start: invalid automation rules: %s", exc)
    raise


class HealthResponse(BaseModel):
    status: str
    service: str
    rules_loaded: int


class EvaluateRequest(BaseModel):
    risk_labels: List[str] = Field(default_factory=list)
    blocked_actions: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)


class Suggestion(BaseModel):
    id: str
    rule_id: str
    action: str
    message: str
    context: Dict[str, Any]
    requires_approval: bool
    status: str
    created_at: str
    decided_at: Optional[str] = None


class EvaluateResponse(BaseModel):
    suggestions: List[Suggestion]


class SuggestionListResponse(BaseModel):
    count: int
    suggestions: List[Suggestion]


app = FastAPI(
    title="Pomona Automation Engine",
    version="0.1.0",
    description="YAML-rule automation suggestions. Suggestions only -- never direct actuator control.",
)


LANDING_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pomona Automation Engine</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">
<style>
  :root {
    color-scheme: light dark;
    --ground: #f4f2ec;
    --ground-raised: #ebe8de;
    --ink: #201d17;
    --ink-soft: #5c5748;
    --line: #d8d3c4;
    --accent: #a8621a;
    --accent-ink: #fff8ee;
    --accent-2: #3f6650;
    --danger: #8a3324;
    --danger-ground: #f1e2da;
    --mono: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
    --serif: 'Source Serif 4', Georgia, 'Times New Roman', serif;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --ground: #17181a;
      --ground-raised: #202225;
      --ink: #e9e6dd;
      --ink-soft: #9a9587;
      --line: #333230;
      --accent: #d99a52;
      --accent-ink: #1a1512;
      --accent-2: #7fa88f;
      --danger: #d97a63;
      --danger-ground: #2b1e1a;
    }
  }

  * { box-sizing: border-box; }
  body {
    background: var(--ground);
    color: var(--ink);
    font-family: var(--serif);
    font-size: 17px;
    line-height: 1.6;
    margin: 0;
    padding: 0 1.25rem 6rem;
  }
  ::selection { background: var(--accent); color: var(--accent-ink); }

  main { max-width: 640px; margin: 0 auto; }

  header {
    padding-top: 3.5rem;
    padding-bottom: 2.25rem;
    border-bottom: 1px solid var(--line);
    margin-bottom: 2.5rem;
  }
  .eyebrow {
    font-family: var(--mono);
    font-size: 0.72rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--ink-soft);
    margin: 0 0 0.9rem;
  }
  h1 {
    font-family: var(--serif);
    font-weight: 600;
    font-size: 2.5rem;
    line-height: 1.08;
    letter-spacing: -0.01em;
    margin: 0 0 0.85rem;
    text-wrap: balance;
  }
  .thesis {
    font-size: 1.08rem;
    color: var(--ink-soft);
    max-width: 34rem;
    margin: 0 0 1.4rem;
    text-wrap: pretty;
  }
  .status-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem; }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-family: var(--mono);
    font-size: 0.76rem;
    letter-spacing: 0.03em;
    padding: 0.32rem 0.7rem;
    border-radius: 3px;
    border: 1px solid var(--line);
    color: var(--ink-soft);
  }
  .pill .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent-2); flex: none; }
  .links { display: flex; flex-wrap: wrap; gap: 0.6rem; margin-top: 1.5rem; }
  .links a {
    font-family: var(--mono);
    font-size: 0.82rem;
    color: var(--ink);
    text-decoration: none;
    border: 1px solid var(--line);
    border-radius: 3px;
    padding: 0.5rem 0.85rem;
    background: var(--ground-raised);
    transition: border-color 0.15s ease;
  }
  .links a:hover { border-color: var(--accent); }
  .links a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .links a.primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }

  section { margin-bottom: 3rem; }
  h2 {
    font-family: var(--mono);
    font-weight: 500;
    font-size: 0.8rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--ink-soft);
    margin: 0 0 1.1rem;
  }
  p { margin: 0 0 1rem; }
  p.lede { font-size: 1rem; }

  .flow { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.9rem; }
  .flow-step { border: 1px solid var(--line); border-radius: 4px; padding: 1rem 1rem 1.1rem; background: var(--ground-raised); }
  .flow-step .n { font-family: var(--mono); font-size: 0.72rem; color: var(--accent); margin-bottom: 0.5rem; }
  .flow-step h3 { font-family: var(--serif); font-size: 1rem; font-weight: 600; margin: 0 0 0.35rem; }
  .flow-step p { font-size: 0.88rem; color: var(--ink-soft); margin: 0; }

  .tablewrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
  th, td { text-align: left; padding: 0.65rem 0.9rem; border-bottom: 1px solid var(--line); vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  th {
    font-family: var(--mono);
    font-size: 0.7rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-soft);
    background: var(--ground-raised);
  }
  td.method { font-family: var(--mono); font-size: 0.78rem; font-weight: 600; }
  .m-get { color: var(--accent-2); }
  .m-post { color: var(--accent); }
  td.path { font-family: var(--mono); font-size: 0.82rem; }
  td.desc { color: var(--ink-soft); }

  .rule-row { display: grid; grid-template-columns: 1fr auto 1.3fr; align-items: center; gap: 0.8rem; padding: 0.8rem 0; border-bottom: 1px solid var(--line); }
  .rule-row:last-child { border-bottom: none; }
  .rule-trigger { font-family: var(--mono); font-size: 0.82rem; color: var(--ink); }
  .rule-arrow { font-family: var(--mono); color: var(--ink-soft); font-size: 0.82rem; }
  .rule-action { font-size: 0.92rem; color: var(--ink-soft); }

  .rails { border: 1px solid var(--danger); background: var(--danger-ground); border-radius: 4px; padding: 1.1rem 1.3rem 1.3rem; }
  .rails p.lede { color: var(--danger); font-weight: 600; margin-bottom: 0.75rem; font-size: 0.95rem; }
  .rails ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 0.4rem; }
  .rails li { font-family: var(--mono); font-size: 0.82rem; color: var(--ink); padding-left: 1.1rem; position: relative; }
  .rails li::before { content: "\\00d7"; position: absolute; left: 0; color: var(--danger); font-weight: 600; }
  .rails .fine { margin-top: 0.9rem; margin-bottom: 0; font-family: var(--serif); font-size: 0.86rem; color: var(--ink-soft); }

  .project-links { display: flex; flex-wrap: wrap; gap: 0.6rem; margin-bottom: 1.5rem; }
  .project-links a {
    font-family: var(--mono);
    font-size: 0.82rem;
    color: var(--ink);
    text-decoration: none;
    border: 1px solid var(--line);
    border-radius: 3px;
    padding: 0.5rem 0.85rem;
    background: var(--ground-raised);
  }
  .project-links a:hover { border-color: var(--accent); }

  footer { border-top: 1px solid var(--line); padding-top: 1.5rem; font-size: 0.86rem; color: var(--ink-soft); }
  footer code { font-family: var(--mono); background: var(--ground-raised); padding: 0.1rem 0.35rem; border-radius: 3px; font-size: 0.82rem; }

  @media (max-width: 560px) {
    h1 { font-size: 2rem; }
    .flow { grid-template-columns: 1fr; }
    .rule-row { grid-template-columns: 1fr; gap: 0.25rem; }
    .rule-arrow { display: none; }
  }
</style>
</head>
<body>
<main>
  <header>
    <p class="eyebrow">Pomona &middot; Specialist Service</p>
    <h1>Automation Engine</h1>
    <p class="thesis">Turns guarded risk labels from the reasoners into human-readable suggestions. It writes nothing to a valve, pump, or doser &mdash; every action here waits for a person to approve it.</p>
    <div class="status-row">
      <span class="pill"><span class="dot"></span>v0.1 &middot; suggestions only</span>
      <span class="pill">__RULES_LOADED__ rules loaded</span>
    </div>
    <div class="links">
      <a class="primary" href="/docs">Swagger UI &#8599;</a>
      <a href="/redoc">ReDoc &#8599;</a>
      <a href="/health">Health check &#8599;</a>
    </div>
  </header>

  <section>
    <h2>How a suggestion gets made</h2>
    <div class="flow">
      <div class="flow-step">
        <p class="n">01</p>
        <h3>Risk labels arrive</h3>
        <p>A reasoner posts labels like <code>high_ec</code> or <code>fungal_pressure</code> to <code>/v1/automation/evaluate</code>.</p>
      </div>
      <div class="flow-step">
        <p class="n">02</p>
        <h3>Rules are matched</h3>
        <p>Each label is checked against <code>app/rules.yaml</code>. A match produces one suggestion.</p>
      </div>
      <div class="flow-step">
        <p class="n">03</p>
        <h3>A person decides</h3>
        <p>The suggestion sits pending until someone approves or rejects it. Nothing runs on its own.</p>
      </div>
    </div>
  </section>

  <section>
    <h2>Endpoints</h2>
    <div class="tablewrap">
      <table>
        <thead><tr><th>Method</th><th>Path</th><th>Description</th></tr></thead>
        <tbody>
          <tr><td class="method m-get">GET</td><td class="path">/health</td><td class="desc">Service status and count of loaded rules.</td></tr>
          <tr><td class="method m-post">POST</td><td class="path">/v1/automation/evaluate</td><td class="desc">Submit risk labels, receive matching suggestions.</td></tr>
          <tr><td class="method m-get">GET</td><td class="path">/v1/automation/suggestions</td><td class="desc">List suggestions, optionally filtered by status.</td></tr>
          <tr><td class="method m-post">POST</td><td class="path">/v1/automation/suggestions/{id}/approve</td><td class="desc">Record a decision to approve.</td></tr>
          <tr><td class="method m-post">POST</td><td class="path">/v1/automation/suggestions/{id}/reject</td><td class="desc">Record a decision to reject.</td></tr>
        </tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>Current rules</h2>
    <div class="rule-row"><span class="rule-trigger">high_ph / low_ph</span><span class="rule-arrow">&rarr;</span><span class="rule-action">Check the water / dosing system</span></div>
    <div class="rule-row"><span class="rule-trigger">high_ec / low_ec</span><span class="rule-arrow">&rarr;</span><span class="rule-action">Review nutrient dosing</span></div>
    <div class="rule-row"><span class="rule-trigger">fungal_pressure</span><span class="rule-arrow">&rarr;</span><span class="rule-action">Consider ventilation, inspect canopy</span></div>
    <div class="rule-row"><span class="rule-trigger">water_level_risk</span><span class="rule-arrow">&rarr;</span><span class="rule-action">Check the irrigation system</span></div>
  </section>

  <section>
    <h2>Safety rails</h2>
    <div class="rails">
      <p class="lede">Rejected at startup, no matter what the rules file says:</p>
      <ul>
        <li>direct_pesticide_dosage</li>
        <li>autonomous_fertigation_change</li>
        <li>direct_actuator_control</li>
        <li>definitive_disease_diagnosis</li>
        <li>unsafe_chemical_recommendation</li>
      </ul>
      <p class="fine">A rule whose <code>action</code> matches this vocabulary fails to load and the service refuses to start. Editing the rules file alone can't make this service unsafe.</p>
    </div>
  </section>

  <section>
    <h2>Part of Pomona</h2>
    <p class="lede" style="font-size:0.95rem;color:var(--ink-soft);">This engine only consumes risk labels &mdash; the reasoners that produce them are fine-tuned models published separately.</p>
    <div class="project-links">
      <a href="https://okyanu.github.io/pomona/">Documentation &#8599;</a>
      <a href="https://github.com/okyanu/pomona">Source on GitHub &#8599;</a>
      <a href="https://huggingface.co/Okyanus">Models on Hugging Face &#8599;</a>
    </div>
  </section>

  <footer>
    Suggestions live in process memory only &mdash; restarting the service clears them.
  </footer>
</main>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing() -> str:
    return LANDING_PAGE.replace("__RULES_LOADED__", str(len(RULES)))


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="pomona-automation-engine", rules_loaded=len(RULES))


@app.post("/v1/automation/evaluate", response_model=EvaluateResponse)
def evaluate(request: EvaluateRequest) -> EvaluateResponse:
    matched_rules = evaluate_rules(RULES, request.risk_labels)
    created: List[Dict[str, Any]] = []
    for rule in matched_rules:
        suggestion = suggestion_store.add(
            rule_id=rule["id"],
            action=rule["action"],
            message=rule["message"],
            context=request.context,
        )
        created.append(suggestion)

    logger.info(
        "automation evaluate risk_labels=%s matched_rules=%s",
        ",".join(request.risk_labels) or "none",
        ",".join(rule["id"] for rule in matched_rules) or "none",
    )
    return EvaluateResponse(suggestions=created)


@app.get("/v1/automation/suggestions", response_model=SuggestionListResponse)
def list_suggestions(status: Optional[str] = Query(default=None)) -> SuggestionListResponse:
    if status is not None and status not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=422, detail="status must be pending, approved, or rejected")
    suggestions = suggestion_store.list(status=status)
    return SuggestionListResponse(count=len(suggestions), suggestions=suggestions)


@app.post("/v1/automation/suggestions/{suggestion_id}/approve", response_model=Suggestion)
def approve_suggestion(suggestion_id: str) -> Suggestion:
    suggestion = suggestion_store.decide(suggestion_id, "approved")
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    logger.info("suggestion approved id=%s action=%s", suggestion_id, suggestion["action"])
    return Suggestion(**suggestion)


@app.post("/v1/automation/suggestions/{suggestion_id}/reject", response_model=Suggestion)
def reject_suggestion(suggestion_id: str) -> Suggestion:
    suggestion = suggestion_store.decide(suggestion_id, "rejected")
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    logger.info("suggestion rejected id=%s action=%s", suggestion_id, suggestion["action"])
    return Suggestion(**suggestion)
