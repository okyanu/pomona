// Checks that every fault planted in samples/ is found (and clean data stays clean).
// Run: node spaces/sensor-data-checker/tests/checker.test.mjs
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const R = require("../rules.js");
const C = require("../checker.js");
const read = (name) => readFileSync(new URL(`../samples/${name}`, import.meta.url), "utf8");
const NOW = R.parseTimestampUs("2026-10-06T09:00:00+00:00");

function run(name, ctx, expectedFn) {
  const csv = C.parseCsv(read(name));
  const built = C.buildPackets(csv.headers, csv.rows);
  return { built, ...C.checkLog(built, ctx, expectedFn(built), NOW) };
}
const labelsAt = (results, stream, ts) => results.find((r) => r.stream.startsWith(stream) && r.packet.timestamp === ts)?.out.data_quality_labels ?? null;
const flagged = (results) => results.filter((r) => r.out.data_quality_labels.length);

// ---- Pomona SD log (long format, two streams) ----
{
  const ctx = { crop: "watercress", system_type: "hydroponic_dwc" };
  const byStream = (b) => b.fieldsPresent; // each stream only has its own fields, see below
  const { built, results, issues } = run("pomona_sd_log_example.csv", ctx, byStream);
  assert.equal(built.format, "long");
  assert.equal(built.streams.length, 2);
  // expected_fields = all fields in the file, so each stream misses the other's fields: re-run per stream.
  const per = {};
  for (const s of built.streams) {
    const fields = [...new Set(s.packets.flatMap((p) => Object.keys(p.packet)).filter((f) => C.SENSOR_FIELDS.includes(f)))];
    per[s.key] = C.checkLog({ ...built, streams: [s] }, ctx, fields, NOW).results;
  }
  const hydro = per["cress-hydro-node · cress-hydro-a"], soil = per["cress-soil-node · cress-soil-a"];
  // flatline_possible may also appear: slow signals at 5-minute steps trip its 0.05 C / 0.25 % tolerance.
  const serious = (l) => (l || []).filter((x) => x !== "flatline_possible");
  assert.deepEqual(serious(labelsAt(hydro, "cress-hydro", "2026-10-06T06:40:00Z")), ["missing_ph"]);
  assert.deepEqual(serious(labelsAt(hydro, "cress-hydro", "2026-10-06T06:50:00Z")), ["missing_ph"]);
  assert.ok(labelsAt(hydro, "cress-hydro", "2026-10-06T08:40:00Z").includes("baseline_drift_possible"));
  assert.deepEqual(serious(labelsAt(soil, "cress-soil", "2026-10-06T06:30:00Z")), ["insufficient_context"]); // "err" moisture
  assert.ok(soil.some((r) => r.out.data_quality_labels.includes("stuck_value")));
  assert.ok(soil.some((r) => r.packet.timestamp === "2026-10-07T08:45:00Z" && r.out.suspect_fields.includes("timestamp")));
  assert.equal(issues.reboots.length, 1);
  assert.ok(issues.gaps.some((g) => g.stream.startsWith("cress-soil") && g.seconds === 35 * 60));
  // Clean early packets stay clean.
  assert.deepEqual(labelsAt(hydro, "cress-hydro", "2026-10-06T06:00:00Z"), []);
  console.log(`SD log: hydro ${flagged(hydro).length}/${hydro.length} flagged, soil ${flagged(soil).length}/${soil.length} flagged, ` +
    `gaps ${issues.gaps.length}, reboots ${issues.reboots.length}`);
}

// ---- Wide spreadsheet log ----
{
  const ctx = { crop: "lettuce", system_type: "hydroponic" };
  const { built, results } = run("wide_log_example.csv", ctx, (b) => b.fieldsPresent);
  assert.equal(built.format, "wide");
  assert.deepEqual([...built.fieldsPresent].sort(), ["air_temperature_c", "ec_ms_cm", "humidity_pct", "ph"]);
  const at = (i) => results[i].out.data_quality_labels.filter((x) => x !== "flatline_possible");
  assert.deepEqual(at(10), ["impossible_ph"]);
  assert.deepEqual(at(17), ["impossible_humidity"]);
  assert.deepEqual(at(22), ["missing_ec"]);
  assert.deepEqual(at(30), ["insufficient_context"]); // timestamp without timezone
  assert.deepEqual(at(40), ["insufficient_context"]); // NaN temperature
  assert.deepEqual(at(0), []);
  // Known rules quirk (reproduced faithfully): 11 packets after the impossible pH 14.9 at index 10,
  // that packet becomes the oldest history entry and serves as the drift baseline, so index 21 gets
  // baseline_drift_possible. The Pomona dashboard behaves the same way.
  assert.deepEqual(at(21), ["baseline_drift_possible"]);
  const unexpected = results.filter((r, i) => at(i).length && ![10, 17, 21, 22, 30, 40, results.length - 1].includes(i));
  assert.deepEqual(unexpected.map((r) => [r.rows, r.out.data_quality_labels]), []);
  console.log(`wide log: ${flagged(results).length}/${results.length} flagged (5 planted + latest-reading age)`);
}

// ---- CSV parsing edge cases ----
{
  const p = C.parseCsv('﻿time;"Temp (°C)";RH\n2026-01-01T00:00:00Z;"21,5";60\n');
  assert.equal(p.delimiter, ";");
  assert.deepEqual(p.headers, ["time", "Temp (°C)", "RH"]);
  assert.equal(C.lookupAlias("Temp (°C)"), "air_temperature_c");
  assert.equal(C.lookupAlias("RH"), "humidity_pct");
  console.log("csv parsing: ok");
}
console.log("all checker tests passed");
