// Runs the demo page's real JavaScript in Node and compares it with the Python code.
//  1. rules.js must be a byte-for-byte copy of the Sensor Data Checker's (Spaces are separate repos).
//  2. The inline tomato rules match app.tomato_reasoner.derive_tomato_risk (parity_cases.json).
//  3. The chain rules.js -> trust_gate.js -> tomato rules (evaluateChain) matches the sensor_quality,
//     trust_gate and crop_risk answers of app.pipeline.evaluate_pipeline (chain_cases.json).
// Usage: node spaces/pomona-greenhouse-demo/tests/parity.test.cjs   (after make_parity_cases.py)
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const demo = path.join(__dirname, '..');
const vendored = fs.readFileSync(path.join(demo, 'rules.js'));
const original = fs.readFileSync(path.join(demo, '..', 'sensor-data-checker', 'rules.js'));
assert.ok(vendored.equals(original), 'spaces/pomona-greenhouse-demo/rules.js differs from spaces/sensor-data-checker/rules.js; run: cp spaces/sensor-data-checker/rules.js spaces/pomona-greenhouse-demo/rules.js');
console.log('rules.js is an exact copy of the Sensor Data Checker rules.js');

const html = fs.readFileSync(path.join(demo, 'index.html'), 'utf8');
for (const file of ['rules.js', 'trust_gate.js']) assert.ok(html.includes(`<script src="${file}"></script>`), `index.html does not load ${file}`);
const start = html.indexOf('<script>') + '<script>'.length;
const end = html.indexOf('// -- UI wiring --');
assert.ok(start > 8 && end > start, 'could not find the rules section of index.html');
const sandbox = { TextEncoder }; // browser globals the vendored rules.js uses
vm.createContext(sandbox);
for (const file of ['rules.js', 'trust_gate.js']) vm.runInContext(fs.readFileSync(path.join(demo, file), 'utf8'), sandbox, { filename: file });
vm.runInContext(html.slice(start, end) + '\nthis.derive = deriveTomatoRisk;\nthis.chain = evaluateChain;', sandbox);
const plain = (value) => JSON.parse(JSON.stringify(value));
// The Python sensor check walks a set of field names, so the order of its label/field/check lists depends on
// PYTHONHASHSEED; compare those four lists as sorted lists (the Sensor Data Checker's parity test does too).
const sortedQuality = (answer) => {
  const quality = { ...answer.sensor_quality };
  ['data_quality_labels', 'missing_fields', 'suspect_fields', 'safe_next_checks'].forEach((key) => { quality[key] = [...quality[key]].sort(); });
  return { ...answer, sensor_quality: quality };
};

let bad = 0;
function compare(label, input, got, want) {
  try {
    assert.deepEqual(got, want);
  } catch (error) {
    if (bad++ < 5) console.log(`MISMATCH (${label})`, JSON.stringify(input), '\n got', JSON.stringify(got), '\n exp', JSON.stringify(want));
  }
}

const tomato = JSON.parse(fs.readFileSync(path.join(__dirname, 'parity_cases.json'), 'utf8'));
tomato.cases.forEach((input, i) => compare('tomato', input, plain(sandbox.derive(input)), tomato.expected[i]));
console.log(`${tomato.cases.length - bad}/${tomato.cases.length} tomato cases match the Python tomato rules`);
const tomatoBad = bad;

const chain = JSON.parse(fs.readFileSync(path.join(__dirname, 'chain_cases.json'), 'utf8'));
const nowUs = sandbox.PomonaRules.parseTimestampUs(chain.now);
assert.ok(nowUs !== null, 'chain_cases.json has an invalid "now"');
const verdicts = {};
chain.cases.forEach((input, i) => {
  const out = sandbox.chain(input.farm, input.sensor, nowUs);
  const got = plain({ sensor_quality: out.quality, trust_gate: out.gate, crop_risk: out.tomato });
  compare('chain', input, sortedQuality(got), sortedQuality(chain.expected[i]));
  verdicts[got.trust_gate.trust_verdict] = (verdicts[got.trust_gate.trust_verdict] || 0) + 1;
});
console.log(`${chain.cases.length - (bad - tomatoBad)}/${chain.cases.length} chain cases match the Python chain (now ${chain.now}); verdicts ${JSON.stringify(verdicts)}`);
process.exit(bad ? 1 : 0);
