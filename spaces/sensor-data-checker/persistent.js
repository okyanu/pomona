/*
 * Pomona persistent sensor checks, ported to JavaScript: Core's trusted per-stream reference and the
 * checks that judge a reading against it.
 *
 * Source of truth:
 *   services/core/app/trusted_baseline.py     stream_baseline (the one-pass reference; the incremental
 *                                             StreamBaseline tracker is byte-identical to it and not ported)
 *   services/model-router/app/sensor_quality.py  apply_persistent_checks and what it calls (adaptive pH/EC
 *                                             stuck, step check, noise check, level drift, persistent stuck limits)
 * tests/persistent.test.mjs checks this file against the Python code (cases from
 * tests/make_persistent_cases.py); run it after changing either side.
 *
 * rules.js (the stateless checks over the last 11 packets) is untouched and stays an exact copy of the one in
 * the greenhouse demo Space. This file sits next to it: `derive` is deriveSensorQuality plus the persistent step.
 *
 * Python things reproduced on purpose: round(x, n) is half-to-even on the exact binary value, `:g` / `:.1f` /
 * `:.0%` format the exact value half-to-even (toPrecision/toFixed round half up), timedelta arithmetic is exact
 * in microseconds, and total_seconds() is a correctly rounded int / 10**6.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./rules.js"));
  else root.PomonaPersistent = factory(root.PomonaRules);
})(typeof self !== "undefined" ? self : this, function (R) {
  "use strict";

  const US = R.US_PER_S;
  const numeric = R.numeric;
  const has = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  const isPlainObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
  const get = (obj, key) => (has(obj, key) ? obj[key] : undefined);
  const isNone = (v) => v === undefined || v === null;
  const addUnique = (items, value) => { if (!items.includes(value)) items.push(value); };
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

  // ---- constants (trusted_baseline.py) ------------------------------------------------------------
  const DEFAULT_WINDOW_S = 2 * 3600;
  const DEFAULT_MIN_N = 6;
  const DEFAULT_SCAN_LIMIT = 5000;
  const IDENTICAL_EPSILON = 1e-9;
  const NORM_STEPS = 200;
  const NORM_FIELDS = ["ph", "ec_ms_cm"];
  const SPREAD_LAG_S = 1800;
  const BASELINE_FIELDS = ["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct", "soil_moisture_pct",
    "substrate_moisture_pct", "substrate_temperature_c"];
  const MEASUREMENT_FIELDS = {
    ph: ["ph"], ec_ms_cm: ["ec_ms_cm"], air_temperature_c: ["air_temperature_c"], humidity_pct: ["humidity_pct"],
    soil_moisture_pct: ["soil_moisture_pct", "substrate_moisture_pct"],
  };
  const ALIASES = { soil_moisture_pct: "substrate_moisture_pct", substrate_moisture_pct: "soil_moisture_pct" };

  // ---- constants (sensor_quality.py) --------------------------------------------------------------
  const STUCK_EPSILON = 1e-9;
  const BASELINE_DRIFT_THRESHOLDS = { ph: 0.35, ec_ms_cm: 0.4 };
  const PLAUSIBLE_RANGES = { ph: [3.0, 11.0], ec_ms_cm: [0.0, 12.0] };
  const MINUTE_US = 60n * US;
  const HOUR_US = 3600n * US;
  const PERSISTENT_STUCK_LIMITS_US = { air_temperature_c: 45n * MINUTE_US, humidity_pct: 30n * MINUTE_US,
    substrate_temperature_c: 6n * HOUR_US, water_temperature_c: 3n * HOUR_US };
  const ADAPTIVE_STUCK_FIELDS = ["ph", "ec_ms_cm"];
  const ADAPTIVE_STUCK_FLOOR_US = 5n * MINUTE_US;
  const ADAPTIVE_STUCK_RUN_FACTOR = 4.0;
  const ADAPTIVE_STUCK_MIN_STEPS = 15;
  const ADAPTIVE_STUCK_MIN_CHANGE_SHARE = 0.7;
  const ADAPTIVE_STUCK_MIN_RUN = 3;
  // field: [smallest allowance, speed per minute, unit, instrument]
  const STEP_LIMITS = {
    air_temperature_c: [3.0, 1.0, "C", "a second thermometer"],
    humidity_pct: [12.0, 4.0, "%RH", "a second hygrometer"],
    soil_moisture_pct: [8.0, 2.0, "%", "a hand-held moisture meter"],
    substrate_moisture_pct: [8.0, 2.0, "%", "a hand-held moisture meter"],
    substrate_temperature_c: [1.5, 0.3, "C", "a second thermometer"],
  };
  const STEP_REWET_BELOW_PCT = { soil_moisture_pct: 15.0, substrate_moisture_pct: 15.0 };
  const NOISE_STEP_LIMIT_5MIN = { humidity_pct: 10.0, air_temperature_c: 2.0, ph: 0.5,
    soil_moisture_pct: 1.0, substrate_moisture_pct: 1.0, substrate_temperature_c: 0.4 };
  const NOISE_STEP_FLOOR = { humidity_pct: 3.0, air_temperature_c: 0.4, ph: 0.1,
    soil_moisture_pct: 2.5, substrate_moisture_pct: 2.5, substrate_temperature_c: 0.5 };
  const NOISE_REFERENCE_INTERVAL_S = 300.0;
  const NOISE_WINDOW = 12;
  const NOISE_MAX_NET_SHARE = 0.5;
  const NOISE_MIN_SAMPLES = 6;
  const DRIFT_SPREAD_FACTOR = 3.0;
  const LAGGED_SPREAD_FIELDS = ["ph"];
  const CALIBRATION_HINT = "if a meter agrees with the reading, it is real: record a calibration for this probe to accept it";
  const ROUTINE_CHECK = "continue routine monitoring";

  // ---- exact number work: Python's float formatting, round() and timedelta ----------------------------
  const F64 = new DataView(new ArrayBuffer(8));
  // |x| = m * 2^e exactly, for a finite double.
  function decompose(x) {
    F64.setFloat64(0, x);
    const hi = F64.getUint32(0), lo = F64.getUint32(4);
    const exp = (hi >>> 20) & 0x7ff;
    let m = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
    if (exp === 0) return { m, e: -1074 };
    return { m: m | (1n << 52n), e: exp - 1075 };
  }
  const pow10 = (k) => 10n ** BigInt(k);
  // round-half-even(|x| * 10^k) as a BigInt, from the exact binary value (k may be negative).
  function roundScaled(x, k) {
    const { m, e } = decompose(Math.abs(x));
    let num = m, den = 1n;
    if (k >= 0) num *= pow10(k); else den *= pow10(-k);
    if (e >= 0) num <<= BigInt(e); else den <<= BigInt(-e);
    const q = num / den, r2 = 2n * (num % den);
    return r2 > den || (r2 === den && (q & 1n) === 1n) ? q + 1n : q;
  }
  const isNeg = (x) => x < 0 || Object.is(x, -0);
  // Python round(x, ndigits) for ndigits >= 0 (half-to-even on the exact value, then the nearest double).
  function pyRound(x, ndigits) {
    if (!Number.isFinite(x) || x === 0) return x;
    const r = Number(`${roundScaled(x, ndigits)}e-${ndigits}`);
    return x < 0 ? -r : r;
  }
  // format(x, f"{'+' if signed}.{digits}f")
  function formatFixed(x, digits, signed = false) {
    const n = roundScaled(x, digits).toString().padStart(digits + 1, "0");
    const body = digits ? `${n.slice(0, -digits)}.${n.slice(-digits)}` : n;
    return (isNeg(x) ? "-" : signed ? "+" : "") + body;
  }
  // format(x, ".0%")
  const formatPercent0 = (x) => (Number.isFinite(x * 100) ? `${formatFixed(x * 100, 0)}%` : `${x < 0 ? "-" : ""}inf%`);
  // format(x, "g") (precision 6)
  function formatG(x, precision = 6) {
    if (x === 0) return Object.is(x, -0) ? "-0" : "0";
    const ax = Math.abs(x);
    let exp = Math.floor(Math.log10(ax));
    let n = roundScaled(ax, precision - 1 - exp);
    const top = pow10(precision);
    if (n >= top) { exp += 1; n = roundScaled(ax, precision - 1 - exp); }
    else if (n < top / 10n) { exp -= 1; n = roundScaled(ax, precision - 1 - exp); if (n >= top) { exp += 1; n = roundScaled(ax, precision - 1 - exp); } }
    const digits = n.toString();
    let body;
    if (exp >= -4 && exp < precision) {
      if (exp >= 0) {
        const frac = digits.slice(exp + 1).replace(/0+$/, "");
        body = digits.slice(0, exp + 1) + (frac ? `.${frac}` : "");
      } else {
        body = `0.${"0".repeat(-exp - 1)}${digits.replace(/0+$/, "")}`;
      }
    } else {
      const frac = digits.slice(1).replace(/0+$/, "");
      body = `${digits[0]}${frac ? `.${frac}` : ""}e${exp < 0 ? "-" : "+"}${String(Math.abs(exp)).padStart(2, "0")}`;
    }
    return (x < 0 ? "-" : "") + body;
  }
  // num / den as Python's int true division gives it (correctly rounded).
  const TWO_53 = 2n ** 53n;
  function ratioToDouble(num, den) {
    if (num >= -TWO_53 && num <= TWO_53 && den <= TWO_53) return Number(num) / Number(den);
    const neg = num < 0n;
    const a = neg ? -num : num;
    const bits = (v) => v.toString(2).length;
    const shift = Math.max(0, 64 + bits(den) - bits(a));
    let q = (a << BigInt(shift)) / den;
    if (((a << BigInt(shift)) % den) !== 0n) q |= 1n; // sticky bit: no double rounding
    const r = Number(q) * 2 ** -shift;
    return neg ? -r : r;
  }
  const totalSeconds = (us) => ratioToDouble(us, US);
  // Sample times travel as plain Numbers (microseconds) while they sit within +-2^52 of the epoch (years 1828 to 2112), where
  // sums and differences are exact; anything else stays a BigInt. Comparing the two kinds is exact.
  const SAFE_US = 2 ** 52;
  const toSafe = (us) => {
    if (typeof us !== "bigint") return us;
    const n = Number(us); // rounded beyond 2^53, but then it is far outside the safe range anyway
    return n >= -SAFE_US && n <= SAFE_US ? n : us;
  };
  const diffSeconds = (a, b) => (typeof a === "number" && typeof b === "number" ? (a - b) / 1e6 : totalSeconds(BigInt(a) - BigInt(b)));
  const floorDiv = (a, b) => { const q = a / b; return (a % b !== 0n && (a < 0n) !== (b < 0n)) ? q - 1n : q; };
  // C round(): half away from zero.
  function cRound(v) {
    const t = Math.trunc(v);
    return Math.abs(v - t) >= 0.5 ? t + Math.sign(v) : t;
  }
  // timedelta(seconds=x) in microseconds, as CPython's delta_new builds it from a float.
  function timedeltaUs(seconds) {
    const whole = Math.trunc(seconds);
    let us = BigInt(whole) * US;
    const frac = seconds - whole;
    if (frac === 0) return us;
    const scaled = 1e6 * frac;
    const intPart = Math.trunc(scaled);
    us += BigInt(intPart);
    const leftover = scaled - intPart;
    if (leftover !== 0) {
      let wholeUs = cRound(leftover);
      if (Math.abs(wholeUs - leftover) === 0.5) {
        const odd = us & 1n ? 1 : 0;
        wholeUs = 2.0 * cRound((leftover + odd) * 0.5) - odd;
      }
      us += BigInt(wholeUs);
    }
    return us;
  }

  // ---- time ----------------------------------------------------------------------------------------
  // trusted_baseline.parse_time as microseconds since the epoch (BigInt) or null: an ISO string (Z or an
  // offset; no zone means UTC) or an already parsed BigInt. rules.js (which mirrors sensor_quality.parse_timestamp)
  // rejects a zoneless time, so the common zoneless forms (date, date and time) are completed to UTC first; an
  // exotic zoneless spelling (week dates, basic format with a time) reads as unusable here, where Python assumes UTC.
  function parseTime(value) {
    if (typeof value === "bigint") return value;
    if (typeof value !== "string") return null;
    const text = value.trim().split("Z").join("+00:00");
    const aware = R.parseTimestampUs(text);
    if (aware !== null) return aware;
    if (/^\d{4}-\d{2}-\d{2}$/.test(text) || /^\d{8}$/.test(text)) return R.parseTimestampUs(`${text}T00:00:00+00:00`);
    if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}([.,]\d{1,6})?)?$/.test(text)) return R.parseTimestampUs(`${text}+00:00`);
    return null;
  }
  // datetime.isoformat() of an aware UTC time given as microseconds since the epoch.
  function isoformatUs(microseconds) {
    const us = BigInt(microseconds);
    const dayUs = 86400n * US;
    const days = floorDiv(us, dayUs);
    const rem = us - days * dayUs;
    // civil date from days since 1970-01-01 (proleptic Gregorian)
    const z = Number(days) + 719468;
    const era = Math.floor(z / 146097);
    const doe = z - era * 146097;
    const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
    const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
    const mp = Math.floor((5 * doy + 2) / 153);
    const day = doy - Math.floor((153 * mp + 2) / 5) + 1;
    const month = mp < 10 ? mp + 3 : mp - 9;
    const year = yoe + era * 400 + (month <= 2 ? 1 : 0);
    const secs = Number(rem / US), micro = Number(rem % US);
    const p = (n, w = 2) => String(n).padStart(w, "0");
    return `${p(year, 4)}-${p(month)}-${p(day)}T${p(Math.floor(secs / 3600))}:${p(Math.floor(secs / 60) % 60)}:${p(secs % 60)}` +
      `${micro ? `.${p(micro, 6)}` : ""}+00:00`;
  }

  // ---- trusted_baseline.py --------------------------------------------------------------------------
  const readNumber = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);

  // The values sorted ascending (a typed array when it is safe to use one: its order puts -0 before 0, where Python's stable sort keeps arrival order).
  function sortedCopy(values) {
    for (const v of values) if (v === 0 && 1 / v < 0) return [...values].sort(cmp);
    return Float64Array.from(values).sort();
  }
  // The 10th to 90th percentile range of values SORTED (at least one).
  function percentileRange(ordered) {
    const count = ordered.length;
    return ordered[Math.trunc(0.9 * (count - 1))] - ordered[Math.trunc(0.1 * (count - 1))];
  }
  // before: [stamp, value] rows, newest first.
  function norm(before) {
    if (before.length < 2) return {};
    let changes = 0, longest = 0.0;
    let groupNewest = before[0][0];
    let [lastStamp, lastValue] = before[0];
    for (let i = 1; i < before.length; i++) {
      const [stamp, value] = before[i];
      if (Math.abs(value - lastValue) > IDENTICAL_EPSILON) {
        changes += 1;
        longest = Math.max(longest, diffSeconds(groupNewest, lastStamp));
        groupNewest = stamp;
      }
      lastStamp = stamp; lastValue = value;
    }
    longest = Math.max(longest, diffSeconds(groupNewest, lastStamp));
    const steps = before.length - 1;
    return { change_share: pyRound(changes / steps, 4), change_steps: steps, longest_run_s: longest };
  }
  const lagged = (old, minN) => (old.length && old.length >= minN ? { spread_lag: pyRound(percentileRange(old), 6) } : {});
  function summary(ordered, windowS, changedAt, lastValue, anchor, before, lag) {
    const count = ordered.length;
    const middle = Math.floor(count / 2);
    return { median: count % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2, n: count, window_s: windowS,
      spread: pyRound(percentileRange(ordered), 6), last_change_at: isoformatUs(changedAt), last_value: lastValue,
      last_at: isoformatUs(anchor), ...norm(before), ...lag };
  }

  // One field's newest-first walk over its (sample time, value, vetoed) rows, one push per row.
  class Walk {
    constructor(field, windowS, startAt, normSteps = 0) {
      this.field = field;
      this.alias = has(ALIASES, field) ? ALIASES[field] : null;
      this.windowS = windowS;
      this.startAt = startAt;
      this.normSteps = normSteps;
      this.newest = null; this.changedAt = null; this.anchor = null;
      this.runOpen = true; this.windowOpen = true; this.open = true;
      this.normOpen = normSteps > 0;
      this.values = []; this.stamps = []; this.before = [];
    }
    push(stamp, value, vetoed) {
      const startAt = this.startAt;
      if (this.newest === null) { this.newest = value; this.changedAt = stamp; }
      else if (this.runOpen) {
        if (Math.abs(value - this.newest) <= IDENTICAL_EPSILON) this.changedAt = stamp;
        else this.runOpen = false;
      }
      if (this.windowOpen) {
        if (startAt !== null && stamp < startAt) this.windowOpen = false;
        else if (!vetoed) {
          if (this.anchor === null) this.anchor = stamp;
          else if (diffSeconds(this.anchor, stamp) > this.windowS) this.windowOpen = false;
          if (this.windowOpen) {
            this.values.push(value);
            if (this.normSteps > 0) this.stamps.push(stamp);
          }
        }
      }
      if (this.normOpen && !this.runOpen) {
        if (startAt !== null && stamp < startAt) this.normOpen = false;
        else if (!vetoed) {
          this.before.push([stamp, value]);
          this.normOpen = this.before.length <= this.normSteps;
        }
      }
      this.open = this.runOpen || this.windowOpen || this.normOpen;
      return this.open;
    }
    stats(minN, now = null, maxAgeS = null) {
      if (this.newest === null) return null;
      const values = this.values, anchor = this.anchor;
      const startAt = this.startAt;
      const changedAt = startAt === null ? this.changedAt : (this.changedAt > startAt ? this.changedAt : startAt);
      if (values.length < minN || (maxAgeS !== null && now !== null && diffSeconds(now, anchor) > maxAgeS)) return null;
      const old = [];
      values.forEach((v, i) => { if (i < this.stamps.length && diffSeconds(anchor, this.stamps[i]) > SPREAD_LAG_S) old.push(v); });
      return summary(sortedCopy(values), this.windowS, changedAt, values[0], anchor, this.before, lagged(sortedCopy(old), minN));
    }
  }

  function latestCalibrations(calibrations, limit) {
    const latest = {};
    for (const item of calibrations) {
      const stamp = toSafe(parseTime(get(item, "performed_at")));
      if (stamp === null || (limit !== null && stamp > limit)) continue;
      const measurement = get(item, "measurement");
      const fields = typeof measurement === "string" && has(MEASUREMENT_FIELDS, measurement) ? MEASUREMENT_FIELDS[measurement] : [];
      for (const field of fields) if (!has(latest, field) || stamp > latest[field]) latest[field] = stamp;
    }
    return latest;
  }

  /**
   * stream_baseline(prior, calibrations, now, window_s, min_n, max_age_s): {field: stats} for every field that has stats.
   * prior: the stream's readings sampled before the current one, oldest first, each {timestamp, <fields>, vetoed_fields}
   * (timestamp: ISO text or microseconds as BigInt; field values are numbers). now: BigInt microseconds or null.
   */
  function streamBaseline(prior, calibrations, now, windowS = DEFAULT_WINDOW_S, minN = DEFAULT_MIN_N, maxAgeS = null) {
    const limit = now === undefined || now === null ? null : toSafe(now);
    const latest = latestCalibrations(calibrations || [], limit);
    const walks = BASELINE_FIELDS.map((field) => new Walk(field, windowS, has(latest, field) ? latest[field] : null,
      NORM_FIELDS.includes(field) ? NORM_STEPS : 0));
    let openWalks = walks;
    for (let p = prior.length - 1; p >= 0; p--) {
      const packet = prior[p];
      let stamp = null, vetoed = null, closed = false;
      for (const walk of openWalks) {
        const value = readNumber(packet[walk.field]); // readings are plain objects: no inherited fields
        if (value === null) continue;
        if (stamp === null) {
          stamp = toSafe(parseTime(get(packet, "timestamp")));
          if (stamp === null || (limit !== null && stamp > limit)) stamp = false;
          else vetoed = get(packet, "vetoed_fields") || [];
        }
        if (stamp === false) break; // an unreadable or future sample time is no row for any field
        if (!walk.push(stamp, value, vetoed.includes(walk.field) || (walk.alias !== null && vetoed.includes(walk.alias)))) closed = true;
      }
      if (closed) {
        openWalks = openWalks.filter((walk) => walk.open);
        if (!openWalks.length) break;
      }
    }
    const out = {};
    for (const walk of walks) {
      const stats = walk.stats(minN, limit, maxAgeS);
      if (stats !== null) out[walk.field] = stats;
    }
    return out;
  }

  // ---- sensor_quality.py ----------------------------------------------------------------------------
  function seriesPoints(history, sensor, field) {
    const points = [];
    for (const packet of [...history, sensor]) {
      if (!isPlainObject(packet)) continue;
      const parsed = numeric(get(packet, field));
      if (parsed !== null) points.push([parsed, packet]);
    }
    return points;
  }
  function trailingRun(values) {
    let run = 0;
    for (let i = values.length - 1; i >= 0; i--) {
      if (run && Math.abs(values[i] - values[values.length - 1]) > STUCK_EPSILON) break;
      run++;
    }
    return run;
  }
  function median(values) {
    const o = [...values].sort(cmp);
    const m = Math.floor(o.length / 2);
    return o.length % 2 ? o[m] : (o[m - 1] + o[m]) / 2;
  }

  // The stream changed in at least 70 % of its last trusted steps (and has 15 of them).
  function isSteadyStream(stats) {
    const share = numeric(get(stats, "change_share"));
    const steps = numeric(get(stats, "change_steps"));
    return share !== null && steps !== null && steps >= ADAPTIVE_STUCK_MIN_STEPS && share >= ADAPTIVE_STUCK_MIN_CHANGE_SHARE;
  }
  // Microseconds, or null when the stream is not judged.
  function adaptiveStuckLimitUs(stats) {
    const share = numeric(get(stats, "change_share"));
    const steps = numeric(get(stats, "change_steps"));
    const longest = numeric(get(stats, "longest_run_s"));
    if (share === null || steps === null || longest === null || longest < 0 ||
        steps < ADAPTIVE_STUCK_MIN_STEPS || share < ADAPTIVE_STUCK_MIN_CHANGE_SHARE) return null;
    const run = timedeltaUs(ADAPTIVE_STUCK_RUN_FACTOR * longest);
    return run > ADAPTIVE_STUCK_FLOOR_US ? run : ADAPTIVE_STUCK_FLOOR_US;
  }

  function applyStepCheck(field, current, sampledUs, stats, labels, suspect, checks) {
    const lastValue = numeric(get(stats, "last_value"));
    const lastAt = R.parseTimestampUs(get(stats, "last_at"));
    if (lastValue === null || lastAt === null || sampledUs === null) return;
    if (current > lastValue && lastValue < (has(STEP_REWET_BELOW_PCT, field) ? STEP_REWET_BELOW_PCT[field] : -Infinity)) return;
    const [smallest, speed, unit, instrument] = STEP_LIMITS[field];
    const minutes = Math.max(totalSeconds(sampledUs - lastAt), 0.0) / 60;
    const allowed = Math.max(smallest, speed * minutes);
    if (Math.abs(current - lastValue) > allowed) {
      addUnique(labels, "sensor_drift_possible");
      addUnique(suspect, field);
      checks.push(`compare ${field} with ${instrument}: it moved ${formatFixed(current - lastValue, 1, true)} ${unit} in ` +
        `${formatFixed(minutes, 1)} minutes, faster than it can change; ${CALIBRATION_HINT}`);
    }
  }

  function applyNoiseCheck(field, sensor, history, labels, suspect, checks) {
    const points = seriesPoints(history, sensor, field).slice(-NOISE_WINDOW);
    if (points.length < NOISE_MIN_SAMPLES) return;
    const stamps = points.map(([, packet]) => R.parseTimestampUs(get(packet, "timestamp")));
    const gaps = [];
    for (let i = 1; i < stamps.length; i++) {
      if (stamps[i - 1] === null || stamps[i] === null) continue;
      const g = totalSeconds(stamps[i] - stamps[i - 1]);
      if (g > 0) gaps.push(g);
    }
    gaps.sort(cmp);
    if (!gaps.length) return;
    const limit = Math.max(NOISE_STEP_FLOOR[field],
      NOISE_STEP_LIMIT_5MIN[field] * Math.sqrt(median(gaps) / NOISE_REFERENCE_INTERVAL_S));
    const values = points.map((p) => p[0]);
    const steps = values.slice(1).map((b, i) => Math.abs(b - values[i]));
    let travelled = 0.0;
    for (const step of steps) travelled += step; // left to right, as the Python loop does
    if (median(steps) >= limit && Math.abs(values[values.length - 1] - values[0]) <= NOISE_MAX_NET_SHARE * travelled) {
      addUnique(labels, "noisy_signal_possible");
      addUnique(suspect, field);
      checks.push(`inspect ${field}: readings jump between samples; check probe shielding, wiring and averaging`);
    }
  }

  /** apply_persistent_checks: judge the reading against Core's trusted reference of its stream (mutates labels, suspect, checks). */
  function applyPersistentChecks(sensor, history, streamBaselineStats, labels, suspect, checks) {
    if (!isPlainObject(streamBaselineStats)) return;
    const sampled = R.parseTimestampUs(get(sensor, "timestamp"));
    let previousPacket = {};
    for (let i = history.length - 1; i >= 0; i--) if (isPlainObject(history[i])) { previousPacket = history[i]; break; }
    for (const field of Object.keys(streamBaselineStats)) {
      const stats = streamBaselineStats[field];
      const current = numeric(get(sensor, field));
      if (!isPlainObject(stats) || current === null) continue;
      const med = numeric(get(stats, "median"));
      let threshold = has(BASELINE_DRIFT_THRESHOLDS, field) ? BASELINE_DRIFT_THRESHOLDS[field] : null;
      const [low, high] = has(PLAUSIBLE_RANGES, field) ? PLAUSIBLE_RANGES[field] : [-Infinity, Infinity];
      let spread = numeric(get(stats, "spread")) || 0.0;
      const laggedSpread = numeric(get(stats, "spread_lag"));
      if (LAGGED_SPREAD_FIELDS.includes(field) && laggedSpread !== null && laggedSpread >= 0 && isSteadyStream(stats)) spread = laggedSpread;
      if (threshold !== null) threshold = Math.max(threshold, DRIFT_SPREAD_FACTOR * spread);
      if (med !== null && threshold !== null && low <= current && current <= high && Math.abs(current - med) >= threshold) {
        addUnique(labels, "baseline_drift_possible");
        addUnique(suspect, field);
        checks.push(`verify ${field} with a meter: ${formatG(current)} differs from the trusted level ${formatG(med)}; ${CALIBRATION_HINT}`);
      }
      let limit = has(PERSISTENT_STUCK_LIMITS_US, field) ? PERSISTENT_STUCK_LIMITS_US[field] : null;
      let habit = "";
      const adaptive = limit === null && ADAPTIVE_STUCK_FIELDS.includes(field);
      if (adaptive) {
        limit = adaptiveStuckLimitUs(stats);
        habit = `, though this probe normally changes on ${formatPercent0(numeric(get(stats, "change_share")) || 0)} of its readings`;
      }
      const changedAt = R.parseTimestampUs(get(stats, "last_change_at"));
      const previous = numeric(get(previousPacket, field));
      if (limit !== null && sampled !== null && changedAt !== null && previous !== null &&
          Math.abs(current - previous) <= STUCK_EPSILON && sampled - changedAt > limit &&
          (!adaptive || trailingRun(seriesPoints(history, sensor, field).map((p) => p[0])) >= ADAPTIVE_STUCK_MIN_RUN)) {
        addUnique(labels, "stuck_value");
        addUnique(suspect, field);
        checks.push(`inspect ${field}: the same value for ${floorDiv(sampled - changedAt, MINUTE_US)} minutes${habit}; ${CALIBRATION_HINT}`);
      }
      if (has(STEP_LIMITS, field)) applyStepCheck(field, current, sampled, stats, labels, suspect, checks);
      if (has(NOISE_STEP_LIMIT_5MIN, field)) applyNoiseCheck(field, sensor, history, labels, suspect, checks);
    }
  }

  // derive_sensor_quality's inputs are valid (otherwise it returns before any check runs).
  function validInputs(farmContext, sensor, expectedFields, history) {
    return isPlainObject(farmContext) && isPlainObject(sensor) && Array.isArray(expectedFields) &&
      expectedFields.every((f) => typeof f === "string") &&
      (history === null || (Array.isArray(history) && history.every((h) => h === null || isPlainObject(h))));
  }

  /**
   * derive_sensor_quality(..., history=..., stream_baseline=...): deriveSensorQuality (rules.js) and then the persistent
   * checks. In Python they run inside it, before the default "continue routine monitoring" check and the review
   * flag are set; this redoes those two from the final lists.
   */
  function derive(farmContext, sensor, expectedFields, nowUs = null, history = null, streamBaselineStats = null) {
    const out = R.deriveSensorQuality(farmContext, sensor, expectedFields, nowUs, history);
    if (!isPlainObject(streamBaselineStats) || !validInputs(farmContext, sensor, expectedFields, history)) return out;
    const labels = [...out.data_quality_labels], suspect = [...out.suspect_fields];
    const checks = out.safe_next_checks.length === 1 && out.safe_next_checks[0] === ROUTINE_CHECK ? [] : [...out.safe_next_checks];
    applyPersistentChecks(sensor, history || [], streamBaselineStats, labels, suspect, checks);
    if (!checks.length) checks.push(ROUTINE_CHECK);
    return {
      data_quality_labels: labels, missing_fields: out.missing_fields, suspect_fields: suspect, safe_next_checks: checks,
      human_review_required: Boolean(labels.length || out.missing_fields.length || suspect.length),
      rationale: labels.length ? "Sensor packet needs verification before downstream risk or action reasoning."
        : "Critical sensor readings are present and inside plausible ranges.",
    };
  }

  /**
   * The trusted reference of one stream that is checked reading by reading, as Core builds it: the stream's earlier
   * readings (at most `scanLimit` of them, newest by arrival), those sampled before the current one, in sample-time
   * order. `add` each reading after it was checked, with the fields the pipeline vetoed.
   */
  class StreamReference {
    constructor(scanLimit = DEFAULT_SCAN_LIMIT) {
      this.scanLimit = scanLimit;
      this.sorted = [];   // entries by sample time, equal times in arrival order
      this.arrival = [];  // the same entries by arrival
    }
    baseline(stampUs, calibrations = []) {
      const sorted = this.sorted;
      let lo = 0, hi = sorted.length; // entries sampled before stampUs
      while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid].timestamp < stampUs) lo = mid + 1; else hi = mid; }
      return streamBaseline(lo === sorted.length ? sorted : sorted.slice(0, lo), calibrations, stampUs);
    }
    add(packet, stampUs, vetoedFields) {
      const entry = { timestamp: stampUs, vetoed_fields: vetoedFields };
      for (const field of BASELINE_FIELDS) entry[field] = numeric(get(packet, field));
      const sorted = this.sorted;
      let lo = 0, hi = sorted.length; // after the entries sampled at the same time
      while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid].timestamp <= stampUs) lo = mid + 1; else hi = mid; }
      sorted.splice(lo, 0, entry);
      this.arrival.push(entry);
      if (this.arrival.length > this.scanLimit) {
        const oldest = this.arrival.shift();
        sorted.splice(sorted.indexOf(oldest), 1);
      }
    }
  }

  return { derive, applyPersistentChecks, streamBaseline, StreamReference, parseTime, isoformatUs,
    pyRound, formatG, formatFixed, formatPercent0, totalSeconds, timedeltaUs, adaptiveStuckLimitUs,
    BASELINE_FIELDS, DEFAULT_SCAN_LIMIT };
});
