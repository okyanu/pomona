// Parity: rules.js must match services/model-router/app/sensor_quality.py.
// Generate cases first:  python3.11 spaces/sensor-data-checker/tests/make_parity_cases.py
// Then run:              node spaces/sensor-data-checker/tests/parity.test.mjs
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const R = require("../rules.js");
const cases = JSON.parse(readFileSync(new URL("./parity_cases.json", import.meta.url)));

const sortedJson = (a) => JSON.stringify([...a].sort());
let failures = 0;
const fail = (kind, detail) => { if (failures++ < 15) console.error(`FAIL ${kind}:`, JSON.stringify(detail).slice(0, 600)); };

for (const c of cases.timestamps) {
  const got = R.parseTimestampUs(c.text);
  const want = c.us === null ? null : BigInt(c.us);
  if (got !== want) fail("timestamp", { text: c.text, want: c.us, got: got === null ? null : String(got) });
}
for (const c of cases.numeric) {
  const got = R.numeric(c.value);
  if (got !== c.out && !(got === 0 && c.out === 0)) fail("numeric", { value: c.value, want: c.out, got });
}
for (const c of cases.derive) {
  const got = R.deriveSensorQuality(c.farm, c.sensor, c.expected, c.now_us === null ? null : BigInt(c.now_us), c.history);
  const want = c.out;
  const same = ["data_quality_labels", "missing_fields", "suspect_fields", "safe_next_checks"]
    .every((k) => sortedJson(got[k]) === sortedJson(want[k])) &&
    got.human_review_required === want.human_review_required && got.rationale === want.rationale;
  if (!same) fail("derive", { sensor: c.sensor, want, got });
}
const total = cases.timestamps.length + cases.numeric.length + cases.derive.length;
console.log(`python ${cases.python}: ${total - failures}/${total} cases match` +
  ` (derive ${cases.derive.length}, timestamps ${cases.timestamps.length}, numeric ${cases.numeric.length})`);
process.exit(failures ? 1 : 0);
