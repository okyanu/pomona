/*
 * Pomona pH calibration rules in JavaScript.
 *
 * Sources of truth (keep in step; tests/parity.test.cjs checks this file against the Python):
 *   devices/esp32-cress-logger/tools/ph_calibrate.py   evaluate() / check()
 *   services/core/app/probe_health.py                   fit_calibration() / assess_probe()
 * and include/ph_calibration.h in the same firmware folder.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PomonaCalibration = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const ABS_MIN_MV = 20.0, ABS_MAX_MV = 600.0;   // any real probe + board lands in this window
  const V7_MIN = 0.05, V7_MAX = 3.4;             // ADS1115 on 3.3 V
  const SENS_MIN_PCT = 75.0, SENS_MAX_PCT = 125.0;
  const PH10_TOLERANCE = 0.3;
  const OK_PCT = 90.0, WORN_PCT = 80.0, V7_SHIFT_V = 0.10;   // trend vs the first calibration

  // Is the slope (pH per volt) believable for a pH probe board?
  function check(slope, offset, expectedMv = 0.0, expectedSign = 0) {
    if (slope === 0) return { reason: "uncalibrated: slope is 0", mv: 0.0, v7: 0.0 };
    if (!Number.isFinite(slope) || !Number.isFinite(offset)) {
      return { reason: "slope or offset is not a number (identical buffer readings?)", mv: 0.0, v7: 0.0 };
    }
    const mv = 1000.0 / Math.abs(slope);
    const v7 = (7.0 - offset) / slope;
    if (!(ABS_MIN_MV <= mv && mv <= ABS_MAX_MV)) {
      return { reason: "sensitivity outside 20-600 mV/pH: identical, swapped or wrong buffers?", mv, v7 };
    }
    if (!(V7_MIN <= v7 && v7 <= V7_MAX)) {
      return { reason: "pH 7 voltage outside 0.05-3.4 V: check the ADS1115 supply and readings", mv, v7 };
    }
    if ((expectedSign > 0 && slope < 0) || (expectedSign < 0 && slope > 0)) {
      return { reason: "slope direction is opposite to the board: buffers swapped?", mv, v7 };
    }
    if (expectedMv > 0) {
      const pct = 100.0 * mv / expectedMv;
      if (pct < SENS_MIN_PCT) return { reason: `sensitivity ${pct.toFixed(0)} % of expected: worn probe or bad buffer`, mv, v7 };
      if (pct > SENS_MAX_PCT) return { reason: `sensitivity ${pct.toFixed(0)} % of expected: wrong buffer or gain`, mv, v7 };
    }
    return { reason: "", mv, v7 };
  }

  // Same result object as ph_calibrate.evaluate().
  function evaluate(v7, v4, v10 = null, expectedMv = 0.0, expectedSign = 0) {
    if (v7 === v4) {
      return { ok: false, reason: "the pH 7 and pH 4 readings are identical; was the probe moved between buffers?",
               slope: null, offset: null, mv_per_ph: null, v_at_ph7: null, direction: 0,
               ph10_predicted: null, ph10_error: null, ph10_ok: null };
    }
    const slope = (7.0 - 4.0) / (v7 - v4);
    const offset = 7.0 - slope * v7;
    const c = check(slope, offset, expectedMv, expectedSign);
    const out = { ok: !c.reason, reason: c.reason, slope, offset, mv_per_ph: c.mv, v_at_ph7: c.v7,
                  direction: slope < 0 ? -1 : 1, ph10_predicted: null, ph10_error: null, ph10_ok: null };
    if (v10 !== null && v10 !== undefined) {
      out.ph10_predicted = slope * v10 + offset;
      out.ph10_error = out.ph10_predicted - 10.0;
      out.ph10_ok = Math.abs(out.ph10_error) <= PH10_TOLERANCE;
      out.ok = out.ok && out.ph10_ok;
    }
    return out;
  }

  // Sensitivity and pH 7 voltage of a two-buffer calibration (volts at pH 7 and at pH 4).
  function fit(v7, v4) {
    if (v7 === v4) return null;
    const slope = (v4 - v7) / (4.0 - 7.0);   // volts per pH (least squares through two points)
    return { sensitivity_mv_per_ph: Math.abs(slope) * 1000.0, v_at_ph7: v7 };
  }

  // Compare the latest calibration with the probe's first one (probe_health.assess_probe thresholds).
  function trend(first, latest) {
    const a = fit(first.v7, first.v4), b = fit(latest.v7, latest.v4);
    if (!a || !b) return null;
    const pct = 100.0 * b.sensitivity_mv_per_ph / a.sensitivity_mv_per_ph;
    const shift = Math.round((b.v_at_ph7 - a.v_at_ph7) * 10000) / 10000;   // 0.1 mV, as in Core
    const reasons = [];
    let status = "ok";
    if (pct < WORN_PCT) {
      status = "worn";
      reasons.push(`sensitivity is ${Math.round(pct)} % of the first calibration: clean the probe, check the buffers, then replace it if it stays low`);
    } else if (pct < OK_PCT) {
      status = "weakening";
      reasons.push(`sensitivity is ${Math.round(pct)} % of the first calibration: clean the probe and recalibrate soon`);
    }
    if (Math.abs(shift) >= V7_SHIFT_V) {
      reasons.push(`pH 7 voltage moved ${shift >= 0 ? "+" : "-"}${Math.abs(Math.round(shift * 1000))} mV since the first calibration: reference junction or cable?`);
      if (status === "ok") status = "weakening";
    }
    return { status, reasons, sensitivity_vs_first_pct: pct, v_at_ph7_shift_v: shift,
             first_mv_per_ph: a.sensitivity_mv_per_ph, latest_mv_per_ph: b.sensitivity_mv_per_ph };
  }

  return { check, evaluate, fit, trend, constants: { ABS_MIN_MV, ABS_MAX_MV, V7_MIN, V7_MAX, SENS_MIN_PCT, SENS_MAX_PCT, OK_PCT, WORN_PCT, V7_SHIFT_V } };
});
