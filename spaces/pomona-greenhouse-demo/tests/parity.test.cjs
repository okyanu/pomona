// Runs the demo page's real <script> rules in Node and compares them with the Python rules.
// Usage: node spaces/pomona-greenhouse-demo/tests/parity.test.cjs   (after make_parity_cases.py)
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const start = html.indexOf('<script>') + '<script>'.length;
const end = html.indexOf('// -- UI wiring --');
assert.ok(start > 8 && end > start, 'could not find the rules section of index.html');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(html.slice(start, end) + '\nthis.derive = deriveTomatoRisk;', sandbox);

const { cases, expected } = JSON.parse(fs.readFileSync(path.join(__dirname, 'parity_cases.json'), 'utf8'));
let bad = 0;
cases.forEach((input, i) => {
  const got = JSON.parse(JSON.stringify(sandbox.derive(input)));
  try {
    assert.deepEqual(got, expected[i]);
  } catch (error) {
    if (bad++ < 3) console.log('MISMATCH', JSON.stringify(input), '\n got', JSON.stringify(got), '\n exp', JSON.stringify(expected[i]));
  }
});
console.log(`${cases.length - bad}/${cases.length} cases match the Python rules`);
process.exit(bad ? 1 : 0);
