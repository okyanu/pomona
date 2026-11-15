# Local reliability hardening

2026-09-16 local checkpoint; not a deployment or model-release claim.

- Core rejects boolean/non-finite measurements and explicitly supplied naive timestamps. Sensor-quality rules flag invalid measurements and missing/invalid/future timestamps for review. Legacy Core events without timestamps still receive server time; devices should send measurement time.
- MQTT topic identities must match payload identities. Retained provenance comes from the broker message. Retained-only state does not prove a device is online.
- SQLite deduplicates samples and tracks per-stream sequences when `boot_id` and `sequence` are supplied. Without them, only identical sample content is deduplicated. Latest selection uses sample time and excludes ineligible sequence/future samples. This is not authenticated identity or exactly-once delivery; duplicate history is retention-bound and cursor cleanup/soak testing remain follow-ups.
- Suggestions expire after `SUGGESTION_TTL_SECONDS` (default 900), additionally bounded by sample age when supplied (`SUGGESTION_SAMPLE_MAX_AGE_SECONDS`, default 3600). Invalid/old sample context expires immediately. Legacy contexts without sensor timestamps use creation-time TTL only. The dashboard passes sample time. Expiry is checked on reads/decisions; expired approval returns 409, and retries do not renew the deadline. Newer samples do not yet automatically supersede suggestions. No hardware execution is added.
- Bounded growth (2026-11-14, tested in software): the model-router's pipeline audit file rotates to `<name>.1` at `AUDIT_LOG_MAX_BYTES` (default 20 MB, 0 = off; one rotated file is kept, on the data volume) and `GET /v1/pipeline/audit` reads the newest lines from the end of the file. The automation engine prunes decided and expired suggestions when one is added as well as when one is decided, `GET /v1/automation/suggestions` returns at most 500 (newest first; optional `limit` query parameter), and `POST /v1/automation/evaluate` answers 422 for more than 64 risk labels, a label over 80 characters, or a context over 64 KB. A silence of more than `ALERT_MAX_GAP_SECONDS` (default 1800, 0 = off) restarts the timers of pending alerts; a raised alert is not touched.
- Model backends (`REASONER_BACKEND=ollama`): the reasoners wait at most `REASONER_TIMEOUT_S` (default 60) and the advisor `ADVISOR_TIMEOUT_S` (default 60); the rules decide either way. `fallback_reason` names the exception class only (the full text goes to the log).
- Training preparation uses raw JSON and the canonical prompt contract. Four evaluation builders now use category-neutral entity IDs and separately named diagnostic outputs. Historical artifacts are preserved. Regenerated diagnostics are not untouched release holdouts.
- A separate 56-case synthetic sensor-quality candidate suite is prepared privately, pending label/overlap review and model evaluation. The private training notebook is syntax-checked only; no GPU training or model promotion occurred.

## Verification and remaining work

`make test-local` at the 2026-09-16 checkpoint: 172 passed, 1 skipped (optional
dependency), one upstream TestClient deprecation warning. That count is old. On
2026-11-07 the same command gave 14 passed + 1 skipped / 541 / 80 / 50 / 440 passed +
12 xfailed / 145, one figure per test group (groups named in [PROJECT_STATUS.md](./PROJECT_STATUS.md)). Notebook
JSON/Python syntax, shell syntax and `git diff --check` passed at the 2026-09-16 checkpoint. Live integration could not start because the approval
system hit a usage limit on the first attempt. An owner-authorized retry later
passed the live six-service HTTP validation, including scoped data, suggestion
retry handling, dashboard HTML and SQLite restart recovery. Real MQTT reconnects
and device tests remain outstanding. The 56-case candidate suite has no rule
disagreements or exact/identity-time-stripped matches against 18 local
sensor-quality JSONL files, but coverage must expand before release gating.
