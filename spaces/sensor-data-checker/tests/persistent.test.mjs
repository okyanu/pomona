// Parity: persistent.js (the trusted stream reference and the persistent checks) must match
// services/core/app/trusted_baseline.py and services/model-router/app/sensor_quality.py, and the checker's
// per-reading flow (checker.js) must give the answers the Python functions give run in the same order.
// Generate cases first:  python3.11 spaces/sensor-data-checker/tests/make_persistent_cases.py
// Then run:              node spaces/sensor-data-checker/tests/persistent.test.mjs
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const R = require("../rules.js");
const P = require("../persistent.js");
const C = require("../checker.js");
const here = (rel) => new URL(rel, import.meta.url);

// The vendored copies (Spaces are separate repos) must be exact.
const demo = (file) => readFileSync(here(`../../pomona-greenhouse-demo/${file}`));
assert.ok(readFileSync(here("../rules.js")).equals(demo("rules.js")), "rules.js differs from the greenhouse demo copy");
assert.ok(readFileSync(here("../trust_gate.js")).equals(demo("trust_gate.js")), "trust_gate.js differs from the greenhouse demo copy");
const html = readFileSync(here("../index.html"), "utf8");
for (const file of ["rules.js", "persistent.js", "trust_gate.js", "checker.js", "app.js"]) {
  assert.ok(html.includes(`<script src="${file}"></script>`), `index.html does not load ${file}`);
}

const cases = JSON.parse(readFileSync(here("./persistent_cases.json")));

// Python and JS agree number for number, including the sign of zero.
function same(a, b) {
  if (typeof a === "number" && typeof b === "number") return Object.is(a, b);
  if (Array.isArray(a)) return Array.isArray(b) && a.length === b.length && a.every((v, i) => same(v, b[i]));
  if (a && typeof a === "object") {
    if (!b || typeof b !== "object" || Array.isArray(b)) return false;
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => Object.hasOwn(b, k) && same(a[k], b[k]));
  }
  return a === b;
}
let failures = 0;
const fail = (kind, detail) => { if (failures++ < 12) console.error(`FAIL ${kind}:`, JSON.stringify(detail, (k, v) => (typeof v === "bigint" ? String(v) : v)).slice(0, 1500)); };
const nowOf = (text) => (text === null ? null : P.parseTime(text));

// ---- formatting, rounding, timedelta ----
const formats = {
  g: (x) => P.formatG(x), fixed1s: (x) => P.formatFixed(x, 1, true), fixed1: (x) => P.formatFixed(x, 1), pct0: (x) => P.formatPercent0(x),
  round6: (x) => P.pyRound(x, 6), round4: (x) => P.pyRound(x, 4),
  timedelta: (x) => String(P.timedeltaUs(x)), total_seconds: (x) => P.totalSeconds(BigInt(x)), isoformat: (x) => P.isoformatUs(BigInt(x)),
};
for (const c of cases.format) {
  const got = formats[c.kind](c.x);
  if (!same(got, c.out)) fail(`format ${c.kind}`, { x: c.x, want: c.out, got });
}

// ---- stream_baseline ----
for (const c of cases.baseline) {
  const got = P.streamBaseline(c.prior, c.calibrations, nowOf(c.now), c.window_s, c.min_n, c.max_age_s);
  if (!same(got, c.out)) fail("baseline", { now: c.now, want: c.out, got });
}

// ---- apply_persistent_checks ----
for (const c of cases.checks) {
  const [labels, suspect, checks] = c.pre ? c.pre.map((l) => [...l]) : [[], [], []];
  P.applyPersistentChecks(c.sensor, c.history, c.baseline, labels, suspect, checks);
  const got = { labels, suspect, checks };
  if (!same(got, c.out)) fail("checks", { sensor: c.sensor, baseline: c.baseline, want: c.out, got });
}

// ---- derive_sensor_quality with stream_baseline ----
for (const c of cases.derive) {
  const got = P.derive(c.farm, c.sensor, c.expected, c.now_us === null ? null : BigInt(c.now_us), c.history, c.baseline);
  const want = c.out;
  if (!same({ ...got }, { ...want })) fail("derive", { sensor: c.sensor, want, got });
}

// ---- whole streams through checkLog ----
let readings = 0;
for (const c of cases.streams) {
  const built = { streams: [{ key: "s", packets: c.packets.map((packet, i) => ({ rows: [i + 2], packet, bootId: null })) }] };
  const { results } = C.checkLog(built, c.ctx, c.expected, BigInt(c.now_us), c.scan_limit);
  readings += c.packets.length;
  if (results.length !== c.out.length) { fail("stream length", { note: c.note }); continue; }
  results.forEach((r, i) => {
    if (!same(r.out, c.out[i])) fail("stream", { note: c.note, index: i, packet: c.packets[i], want: c.out[i], got: r.out });
  });
}

const counts = { format: cases.format.length, baseline: cases.baseline.length, checks: cases.checks.length, derive: cases.derive.length, streams: cases.streams.length };
const total = Object.values(counts).reduce((a, b) => a + b, 0);
console.log(`python ${cases.python}: persistent ${failures ? "FAILED" : "all match"}: ` +
  Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(", ") + ` (${readings} readings in the streams, ${total} cases)`);
process.exit(failures ? 1 : 0);
