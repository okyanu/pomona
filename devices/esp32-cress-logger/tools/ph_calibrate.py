#!/usr/bin/env python3
"""Turn pH buffer readings into PH_SLOPE / PH_OFFSET and sanity-check them (stdlib only).

Read the logger's raw volts (the `raw` column of the SD CSV, or the serial output) with the probe
in each buffer, after it has settled, then:

  python3 tools/ph_calibrate.py --v7 2.503 --v4 3.041
  python3 tools/ph_calibrate.py --v7 2.503 --v4 3.041 --v10 1.97 --expected-mv 180 --expected-sign -1

Same rules as include/ph_calibration.h (keep the two in step). Exit 1 if the calibration fails.
"""
import argparse
import math
import sys

ABS_MIN_MV, ABS_MAX_MV = 20.0, 600.0
V7_MIN, V7_MAX = 0.05, 3.4
SENS_MIN_PCT, SENS_MAX_PCT = 75.0, 125.0


def check(slope, offset, expected_mv=0.0, expected_sign=0):
    if slope == 0:
        return "uncalibrated: slope is 0", 0.0, 0.0
    if not (math.isfinite(slope) and math.isfinite(offset)):
        return "slope or offset is not a number (identical buffer readings?)", 0.0, 0.0
    mv, v7 = 1000.0 / abs(slope), (7.0 - offset) / slope
    if not ABS_MIN_MV <= mv <= ABS_MAX_MV:
        return "sensitivity outside 20-600 mV/pH: identical, swapped or wrong buffers?", mv, v7
    if not V7_MIN <= v7 <= V7_MAX:
        return "pH 7 voltage outside 0.05-3.4 V: check the ADS1115 supply and readings", mv, v7
    if (expected_sign > 0 and slope < 0) or (expected_sign < 0 and slope > 0):
        return "slope direction is opposite to the board: buffers swapped?", mv, v7
    if expected_mv > 0:
        pct = 100.0 * mv / expected_mv
        if pct < SENS_MIN_PCT:
            return f"sensitivity {pct:.0f} % of expected: worn probe or bad buffer", mv, v7
        if pct > SENS_MAX_PCT:
            return f"sensitivity {pct:.0f} % of expected: wrong buffer or gain", mv, v7
    return "", mv, v7


def evaluate(v7, v4, v10=None, expected_mv=0.0, expected_sign=0):
    """Everything main() prints, as data (also the reference for spaces/ph-calibration-checker)."""
    if v7 == v4:
        return {"ok": False, "reason": "the pH 7 and pH 4 readings are identical; was the probe moved between buffers?",
                "slope": None, "offset": None, "mv_per_ph": None, "v_at_ph7": None, "direction": 0,
                "ph10_predicted": None, "ph10_error": None, "ph10_ok": None}
    slope = (7.0 - 4.0) / (v7 - v4)
    offset = 7.0 - slope * v7
    reason, mv, v7_expected = check(slope, offset, expected_mv, expected_sign)
    out = {"ok": not reason, "reason": reason, "slope": slope, "offset": offset, "mv_per_ph": mv,
           "v_at_ph7": v7_expected, "direction": -1 if slope < 0 else 1,
           "ph10_predicted": None, "ph10_error": None, "ph10_ok": None}
    if v10 is not None:
        out["ph10_predicted"] = slope * v10 + offset
        out["ph10_error"] = out["ph10_predicted"] - 10.0
        out["ph10_ok"] = abs(out["ph10_error"]) <= 0.3
        out["ok"] = out["ok"] and out["ph10_ok"]
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--v7", type=float, required=True, help="volts in pH 7 buffer")
    p.add_argument("--v4", type=float, required=True, help="volts in pH 4 buffer")
    p.add_argument("--v10", type=float, help="optional third point, volts in pH 10 buffer (checks linearity)")
    p.add_argument("--expected-mv", type=float, default=0.0, help="expected sensitivity of your board, mV per pH")
    p.add_argument("--expected-sign", type=int, choices=(-1, 0, 1), default=0,
                   help="-1 if volts fall as pH rises, +1 if they rise, 0 = do not check")
    a = p.parse_args()
    r = evaluate(a.v7, a.v4, a.v10, a.expected_mv, a.expected_sign)
    if r["slope"] is None:
        print(f"FAIL: {r['reason']}")
        return 1
    print(f"#define PH_SLOPE  {r['slope']:.4f}f")
    print(f"#define PH_OFFSET {r['offset']:.4f}f")
    print(f"# sensitivity {r['mv_per_ph']:.1f} mV/pH, pH 7 expected at {r['v_at_ph7']:.3f} V, slope direction {'-1 (volts fall as pH rises)' if r['direction'] < 0 else '+1 (volts rise with pH)'}")
    print(f"# optional: #define PH_EXPECTED_MV_PER_PH {r['mv_per_ph']:.0f}   #define PH_EXPECTED_SLOPE_SIGN {r['direction']}")
    status = 0
    if r["reason"]:
        print(f"FAIL: {r['reason']}")
        status = 1
    if r["ph10_predicted"] is not None:
        print(f"# pH 10 check: the two-point line predicts {r['ph10_predicted']:.2f} at the pH 10 voltage (error {r['ph10_error']:+.2f})")
        if not r["ph10_ok"]:
            print("FAIL: the pH 10 point is off the line by more than 0.3 pH: probe is nonlinear or a buffer is bad")
            status = 1
    if not status:
        print("OK: calibration looks sane. Record it in Core (see docs/WATERCRESS_PILOT.md).")
    return status


if __name__ == "__main__":
    sys.exit(main())
