# Dev Log

Dated, human-readable notes on what changed and why. For the full commit-by-commit
history see `git log`; this page is for the *why*, and for changes worth flagging
that don't fit neatly in the [Roadmap](Roadmap) table.

Newest first.

## 2026-08-29 — Phase 6 lands: automation engine, deployed and documented

Implemented the automation engine: YAML rules match risk labels from the
reasoners and produce suggestions a human must approve or reject before
anything happens. No suggestion has an execution path to hardware in v0.1 —
state is in-memory only, and rules referencing forbidden actions
(`direct_actuator_control`, `autonomous_fertigation_change`, etc.) are
rejected at load time, not just documented as unsafe.

Deployed it to Vercel at `automation-engine-fawn.vercel.app`, then gave it a
documentation-style landing page at `/` — the root route 404'd otherwise —
covering the request flow, endpoint table, active rules, and the safety-rails
list above.

Also added optional API-key auth to core sensor ingestion (Phase 2
hardening), so the endpoint isn't wide open by default without forcing auth
on local/dev setups that don't need it yet.

## Earlier

See `git log` for the full history — dashboard visual pass, Ollama runtime
wiring for the tomato/water/nutrient reasoners, the public greenhouse demo
Space, and the tomato risk reasoner LoRA publish are all worth reading if
you're new to the project.
