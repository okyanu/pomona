// The page's JavaScript rules must give the same answers as the Python rules (see make_parity_cases.py).
const fs = require('node:fs');
const path = require('node:path');
const C = require('../calibration.js');

const { evaluate, trend } = JSON.parse(fs.readFileSync(path.join(__dirname, 'parity_cases.json'), 'utf8'));
const close = (a, b) => (a === null || b === null) ? a === b : Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
let bad = 0;
const fail = (kind, c, got) => { if (bad++ < 5) console.log('MISMATCH', kind, JSON.stringify(c).slice(0, 400), '\n got', JSON.stringify(got)); };

for (const c of evaluate) {
  const got = C.evaluate(c.v7, c.v4, c.v10, c.expected_mv, c.expected_sign);
  const e = c.expected;
  const same = got.ok === e.ok && got.reason === e.reason && got.direction === e.direction && got.ph10_ok === e.ph10_ok &&
    ['slope', 'offset', 'mv_per_ph', 'v_at_ph7', 'ph10_predicted', 'ph10_error'].every((k) => close(got[k], e[k]));
  if (!same) fail('evaluate', c, got);
}
for (const c of trend) {
  const got = C.trend(c.first, c.latest);
  const e = c.expected;
  const same = got && got.status === e.status && JSON.stringify(got.reasons) === JSON.stringify(e.reasons) &&
    Math.abs(got.sensitivity_vs_first_pct - e.sensitivity_vs_first_pct) <= 0.051 &&
    Math.abs(got.v_at_ph7_shift_v - e.v_at_ph7_shift_v) <= 0.00006;
  if (!same) fail('trend', c, got);
}
const total = evaluate.length + trend.length;
console.log(`${total - bad}/${total} cases match the Python rules (calibrations ${evaluate.length}, trends ${trend.length})` +
  (bad ? `, ${bad} MISMATCHES` : ''));
process.exit(bad ? 1 : 0);
