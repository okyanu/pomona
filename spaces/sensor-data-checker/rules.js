/*
 * Pomona sensor-quality rules, ported to JavaScript.
 *
 * Source of truth: services/model-router/app/sensor_quality.py (derive_sensor_quality).
 * Timestamp parsing mirrors CPython 3.11's C datetime.fromisoformat, which is what the
 * deployed service (python:3.11-slim) uses. tests/parity.test.mjs checks this file
 * against the Python rules; run it after changing either side.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PomonaRules = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const FIELD_LABELS = {
    ph: "missing_ph",
    ec_ms_cm: "missing_ec",
    air_temperature_c: "missing_temperature",
    water_temperature_c: "missing_temperature",
    substrate_temperature_c: "missing_temperature",
    humidity_pct: "missing_humidity",
    substrate_moisture_pct: "missing_moisture",
    soil_moisture_pct: "missing_moisture",
  };
  const STUCK_FIELDS = ["air_temperature_c", "water_temperature_c", "substrate_temperature_c",
    "humidity_pct", "substrate_moisture_pct", "soil_moisture_pct"];
  const BASELINE_DRIFT_FIELDS = ["ph", "ec_ms_cm"];
  const STUCK_WINDOW = 3;
  const FLATLINE_WINDOW = 6;
  const STUCK_EPSILON = 1e-9;
  const BASELINE_DRIFT_THRESHOLDS = { ph: 0.35, ec_ms_cm: 0.4 };
  const PLAUSIBLE_RANGES = { ph: [3.0, 11.0], ec_ms_cm: [0.0, 12.0] };
  const FLATLINE_EPSILON = { air_temperature_c: 0.05, water_temperature_c: 0.05, substrate_temperature_c: 0.05,
    humidity_pct: 0.25, substrate_moisture_pct: 0.25, soil_moisture_pct: 0.25 };
  const US_PER_S = 1000000n;

  const has = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  const isPlainObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
  const get = (obj, key) => (has(obj, key) ? obj[key] : undefined);
  const isNone = (v) => v === undefined || v === null;
  // Python truthiness for JSON values.
  const pyTruthy = (v) => {
    if (isNone(v) || v === false || v === 0 || v === "") return false;
    if (Array.isArray(v)) return v.length > 0;
    if (isPlainObject(v)) return Object.keys(v).length > 0;
    return true;
  };
  const addUnique = (items, value) => { if (!items.includes(value)) items.push(value); };

  // float(str) as Python parses it (ASCII digits; underscores between digits; inf/nan words).
  const PY_FLOAT_RE = /^[+-]?(?:(?:\d(?:_?\d)*)?\.\d(?:_?\d)*|\d(?:_?\d)*\.?)(?:[eE][+-]?\d(?:_?\d)*)?$/;
  const PY_SPECIAL_RE = /^[+-]?(?:inf|infinity|nan)$/i;
  // Python's float() accepts any Unicode decimal digit (e.g. full-width "１２"); map them to ASCII.
  const ND = /\p{Nd}/u;
  function asciiDigits(text) {
    return text.replace(/\p{Nd}/gu, (ch) => {
      let cp = ch.codePointAt(0);
      let start = cp;
      while (ND.test(String.fromCodePoint(start - 1))) start--;
      return String((cp - start) % 10);
    });
  }
  function pyFloat(text) {
    const s = asciiDigits(text).replace(/^[\s\u001c-\u001f\u0085]+|[\s\u001c-\u001f\u0085]+$/g, "");
    if (PY_SPECIAL_RE.test(s)) return NaN; // inf/nan are never finite readings
    if (!PY_FLOAT_RE.test(s)) return null;
    return Number(s.replace(/_/g, ""));
  }

  function numeric(value) {
    if (typeof value === "boolean" || isNone(value)) return null;
    if (typeof value === "number") return Number.isFinite(value) ? value : null;
    if (typeof value === "string") {
      const parsed = pyFloat(value);
      return parsed !== null && Number.isFinite(parsed) ? parsed : null;
    }
    return null;
  }

  // ---- CPython 3.11 C datetime.fromisoformat, on UTF-8 bytes with a trailing NUL -------------
  const isDigit = (b) => b >= 48 && b <= 57;
  function parseDigits(buf, p, n) {
    let v = 0;
    for (let i = 0; i < n; i++) {
      const b = buf[p + i];
      if (!isDigit(b)) return null;
      v = v * 10 + (b - 48);
    }
    return { p: p + n, v };
  }
  function findSeparator(b, len) {
    if (len === 7) return 7;
    if (b[4] === 45) { // '-'
      if (b[5] === 87) { // 'W'
        if (len < 8) return -1;
        if (len > 8 && b[8] === 45) {
          if (len === 9) return -1;
          if (len > 10 && isDigit(b[10])) return 8;
          return 10;
        }
        return 8;
      }
      return 10;
    }
    if (b[4] === 87) {
      let idx = 7;
      for (; idx < len; idx++) if (!isDigit(b[idx])) break;
      if (idx < 9) return idx;
      return idx % 2 === 0 ? 7 : 8;
    }
    return 8;
  }
  const isLeap = (y) => y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  const DAYS_IN_MONTH = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const daysInMonth = (y, m) => (m === 2 && isLeap(y) ? 29 : DAYS_IN_MONTH[m]);
  function ymdToOrdinal(y, m, d) { // proleptic Gregorian, 0001-01-01 = 1 (Python's toordinal)
    const y1 = y - 1;
    let days = y1 * 365 + Math.floor(y1 / 4) - Math.floor(y1 / 100) + Math.floor(y1 / 400);
    for (let i = 1; i < m; i++) days += daysInMonth(y, i);
    return days + d;
  }
  function ordinalToYmd(n) {
    let y = Math.floor((n - 1) / 365.2425) + 1;
    while (ymdToOrdinal(y + 1, 1, 1) <= n) y++;
    while (ymdToOrdinal(y, 1, 1) > n) y--;
    let m = 1;
    while (m < 12 && ymdToOrdinal(y, m + 1, 1) <= n) m++;
    return [y, m, n - ymdToOrdinal(y, m, 1) + 1];
  }
  function isoToYmd(year, week, day) {
    if (year < 1 || year > 9999) return null;
    if (!(week > 0 && week < 53)) {
      let bad = true;
      if (week === 53) {
        const first = ymdToOrdinal(year, 1, 1) % 7;
        if (first === 4 || (first === 3 && isLeap(year))) bad = false;
      }
      if (bad) return null;
    }
    if (!(day > 0 && day < 8)) return null;
    const firstDay = ymdToOrdinal(year, 1, 1);
    const firstWeekday = (firstDay + 6) % 7; // Monday = 0
    let week1Monday = firstDay - firstWeekday;
    if (firstWeekday > 3) week1Monday += 7;
    return ordinalToYmd(week1Monday + (week - 1) * 7 + (day - 1));
  }
  function parseDate(b, len) {
    let r = parseDigits(b, 0, 4);
    if (!r) return null;
    const year = r.v;
    let p = r.p;
    const sep = b[p] === 45;
    if (sep) p++;
    if (b[p] === 87) {
      p++;
      r = parseDigits(b, p, 2);
      if (!r) return null;
      const week = r.v;
      p = r.p;
      let day = 1;
      if (p < len) {
        if (sep && b[p++] !== 45) return null;
        r = parseDigits(b, p, 1);
        if (!r) return null;
        day = r.v;
      }
      return isoToYmd(year, week, day);
    }
    r = parseDigits(b, p, 2);
    if (!r) return null;
    const month = r.v;
    p = r.p;
    if (sep && b[p++] !== 45) return null;
    r = parseDigits(b, p, 2);
    if (!r) return null;
    return [year, month, r.v];
  }
  // Returns {rv, vals:[h,m,s,us]}; rv < 0 error, 0 clean end, 1 trailing characters.
  function parseHhMmSsFf(b, p, pEnd) {
    const vals = [0, 0, 0, 0];
    let hasSep = true;
    for (let i = 0; i < 3; i++) {
      const r = parseDigits(b, p, 2);
      if (!r) return { rv: -3 };
      vals[i] = r.v;
      p = r.p;
      const c = b[p++];
      if (i === 0) hasSep = c === 58; // ':'
      if (p >= pEnd) return { rv: c !== 0 ? 1 : 0, vals };
      if (hasSep && c === 58) continue;
      if (c === 46 || c === 44) break; // '.' or ','
      if (!hasSep) { p--; continue; }
      return { rv: -4 };
    }
    const remain = pEnd - p;
    const toParse = remain >= 6 ? 6 : remain;
    const r = parseDigits(b, p, toParse);
    if (!r) return { rv: -3 };
    vals[3] = toParse < 6 ? r.v * [100000, 10000, 1000, 100, 10][toParse - 1] : r.v;
    p = r.p;
    while (isDigit(b[p])) p++;
    return { rv: b[p] !== 0 ? 1 : 0, vals };
  }
  function parseTime(b, start, end) {
    let tz = start;
    do { const c = b[tz]; if (c === 90 || c === 43 || c === 45) break; } while (++tz < end);
    const t = parseHhMmSsFf(b, start, tz);
    if (t.rv < 0) return null;
    if (tz === end) return t.rv === 1 ? null : { time: t.vals, tz: null };
    if (b[tz] === 90) return b[tz + 1] !== 0 ? null : { time: t.vals, tz: 0n };
    const sign = b[tz] === 45 ? -1n : 1n;
    const z = parseHhMmSsFf(b, tz + 1, end);
    if (z.rv !== 0) return null;
    const [zh, zm, zs, zus] = z.vals;
    const offsetUs = sign * (BigInt(zh * 3600 + zm * 60 + zs) * US_PER_S + BigInt(zus));
    return { time: t.vals, tz: offsetUs };
  }
  // Epoch microseconds (BigInt) for a timezone-aware ISO string, else null.
  function fromIsoformatUs(text) {
    const bytes = new TextEncoder().encode(text);
    const len = bytes.length;
    if (len < 7) return null;
    const b = new Uint8Array(len + 1); // trailing NUL like the C string
    b.set(bytes);
    const sepAt = findSeparator(b, len);
    if (sepAt < 0) return null;
    const ymd = parseDate(b, sepAt);
    if (!ymd) return null;
    let time = [0, 0, 0, 0];
    let tz = null;
    let p = sepAt;
    if (p < len) {
      const lead = b[p];
      p += (lead & 0x80) === 0 ? 1 : (lead & 0xf0) === 0xe0 ? 3 : (lead & 0xf0) === 0xf0 ? 4 : 2;
      const parsed = parseTime(b, p, len);
      if (!parsed) return null;
      time = parsed.time;
      tz = parsed.tz;
    }
    const [year, month, day] = ymd;
    const [h, mi, s, us] = time;
    if (year < 1 || year > 9999 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) return null;
    if (h > 23 || mi > 59 || s > 59 || us > 999999) return null;
    if (tz === null) return null; // naive datetime: rejected by the rules
    const day24 = 86400n * US_PER_S;
    if (tz <= -day24 || tz >= day24) return null;
    const EPOCH_ORDINAL = 719163n; // 1970-01-01
    const local = (BigInt(ymdToOrdinal(year, month, day)) - EPOCH_ORDINAL) * day24 +
      BigInt(h * 3600 + mi * 60 + s) * US_PER_S + BigInt(us);
    return local - tz;
  }

  // parse_timestamp in sensor_quality.py: strings only, every "Z" becomes "+00:00", must be aware.
  function parseTimestampUs(value) {
    if (typeof value !== "string" || !value) return null;
    return fromIsoformatUs(value.split("Z").join("+00:00"));
  }

  function seriesValues(history, sensor, field) {
    const values = [];
    for (const packet of [...history, sensor]) {
      if (!isPlainObject(packet)) continue;
      const parsed = numeric(get(packet, field));
      if (parsed !== null) values.push(parsed);
    }
    return values;
  }

  function trailingRun(values) {
    let run = 0;
    for (let i = values.length - 1; i >= 0; i--) {
      if (run && Math.abs(values[i] - values[values.length - 1]) > STUCK_EPSILON) break;
      run++;
    }
    return run;
  }
  function longestRun(values) {
    let longest = 0, current = 0;
    values.forEach((v, i) => {
      current = i && Math.abs(v - values[i - 1]) <= STUCK_EPSILON ? current + 1 : 1;
      longest = Math.max(longest, current);
    });
    return longest;
  }
  function median(values) {
    const o = [...values].sort((a, b) => a - b);
    const m = Math.floor(o.length / 2);
    return o.length % 2 ? o[m] : (o[m - 1] + o[m]) / 2;
  }
  const steps = (v) => v.slice(1).map((b, i) => Math.abs(b - v[i]));

  function applyTemporalChecks(sensor, history, labels, suspect, checks) {
    if (!history.length) return;
    for (const field of STUCK_FIELDS) {
      const values = seriesValues(history, sensor, field);
      const run = trailingRun(values);
      const earlier = values.slice(0, values.length - run);
      if (earlier.length >= 2 && Math.max(...earlier) - Math.min(...earlier) > STUCK_EPSILON &&
          run >= Math.max(STUCK_WINDOW, 2 * longestRun(earlier))) {
        addUnique(labels, "stuck_value");
        addUnique(suspect, field);
        checks.push(`inspect ${field}: identical readings across ${run} fresh samples`);
        continue;
      }
      const epsilon = FLATLINE_EPSILON[field] || 0;
      if (values.length >= FLATLINE_WINDOW + 2) {
        const prior = values.slice(0, -FLATLINE_WINDOW);
        const window = values.slice(-FLATLINE_WINDOW);
        const priorStep = median(steps(prior));
        const span = Math.max(...window) - Math.min(...window);
        if (priorStep >= epsilon && span > STUCK_EPSILON && span <= epsilon) {
          addUnique(labels, "flatline_possible");
          addUnique(suspect, field);
          checks.push(`inspect ${field}: near-zero variance may indicate a stuck or clipped probe`);
        }
      }
    }
    for (const field of BASELINE_DRIFT_FIELDS) {
      const [low, high] = PLAUSIBLE_RANGES[field];
      let baseline = null;
      for (const packet of history) {
        if (!isPlainObject(packet)) continue;
        const v = numeric(get(packet, field));
        if (v !== null && v >= low && v <= high) { baseline = v; break; }
      }
      const current = numeric(get(sensor, field));
      if (baseline === null || current === null) continue;
      const threshold = BASELINE_DRIFT_THRESHOLDS[field];
      if (Math.abs(current - baseline) < threshold) continue;
      const recent = seriesValues(history.slice(-(STUCK_WINDOW - 1)), sensor, field);
      if (recent.length < STUCK_WINDOW) continue;
      if (recent.every((v) => Math.abs(v - baseline) >= threshold * 0.5)) {
        addUnique(labels, "baseline_drift_possible");
        addUnique(suspect, field);
        checks.push(`recalibrate or verify ${field}: reading drifted from stream startup baseline`);
      }
    }
  }

  /**
   * derive_sensor_quality(farm_context, sensor, expected_fields, now=..., history=...).
   * nowUs: epoch microseconds (BigInt) or null; history: array of prior packets (oldest first) or null.
   */
  function deriveSensorQuality(farmContext, sensor, expectedFields, nowUs = null, history = null) {
    const labels = [];
    const missing = [];
    const suspect = [];
    const checks = [];
    if (!isPlainObject(farmContext) || !isPlainObject(sensor) || !Array.isArray(expectedFields) ||
        expectedFields.some((f) => typeof f !== "string")) {
      return { data_quality_labels: ["insufficient_context"], missing_fields: [], suspect_fields: [],
        safe_next_checks: ["provide valid context, sensor object and field-name list"],
        human_review_required: true, rationale: "Malformed sensor-quality input requires review." };
    }
    if (history !== null && (!Array.isArray(history) || history.some((h) => h !== null && !isPlainObject(h)))) {
      return { data_quality_labels: ["insufficient_context"], missing_fields: [], suspect_fields: [],
        safe_next_checks: ["provide history as a list of prior sensor objects"],
        human_review_required: true, rationale: "Malformed sensor-quality history requires review." };
    }
    if (!pyTruthy(get(farmContext, "crop")) || !pyTruthy(get(farmContext, "system_type")) || !expectedFields.length) {
      addUnique(labels, "insufficient_context");
      checks.push("provide crop, system type, and expected sensor fields before downstream reasoning");
    }
    for (const field of expectedFields) {
      if (isNone(get(sensor, field))) {
        addUnique(missing, field);
        addUnique(labels, FIELD_LABELS[field] || "insufficient_context");
      }
    }
    const numericFields = new Set([...Object.keys(FIELD_LABELS), "previous_ph", "backup_air_temperature_c", "temperature_f"]);
    for (const field of new Set([...numericFields, ...expectedFields])) {
      if (numericFields.has(field) && has(sensor, field) && sensor[field] !== null && numeric(sensor[field]) === null) {
        addUnique(labels, "insufficient_context");
        addUnique(suspect, field);
        checks.push(`verify ${field}: expected a finite numeric reading, not a boolean or invalid value`);
      } else if (expectedFields.includes(field) && !has(FIELD_LABELS, field)) {
        addUnique(labels, "insufficient_context");
        checks.push(`define a supported sensor-quality contract for ${field}`);
      }
    }
    const sampled = parseTimestampUs(get(sensor, "timestamp"));
    if (sampled === null) {
      addUnique(labels, "insufficient_context");
      addUnique(suspect, "timestamp");
      checks.push("provide a valid timezone-aware sample timestamp");
    } else if (nowUs !== null && sampled - nowUs > 60n * US_PER_S) {
      addUnique(labels, "insufficient_context");
      addUnique(suspect, "timestamp");
      checks.push("verify device clock: sample timestamp is more than 60 seconds in the future");
    }
    const ph = numeric(get(sensor, "ph"));
    const previousPh = numeric(get(sensor, "previous_ph"));
    const ec = numeric(get(sensor, "ec_ms_cm"));
    const humidity = numeric(get(sensor, "humidity_pct"));
    const air = numeric(get(sensor, "air_temperature_c"));
    const backupAir = numeric(get(sensor, "backup_air_temperature_c"));
    const tempF = numeric(get(sensor, "temperature_f"));
    if (ph !== null) {
      if (ph < 3.0 || ph > 11.0) {
        addUnique(labels, "impossible_ph"); addUnique(suspect, "ph");
        checks.push("inspect pH probe calibration and units before using this reading");
      } else if (previousPh !== null && Math.abs(ph - previousPh) >= 0.8) {
        addUnique(labels, "sensor_drift_possible"); addUnique(suspect, "ph"); addUnique(suspect, "previous_ph");
        checks.push("repeat pH measurement and inspect probe drift before threshold reasoning");
      }
    }
    if (ec !== null && (ec < 0.0 || ec > 12.0)) {
      addUnique(labels, "impossible_ec"); addUnique(suspect, "ec_ms_cm");
      checks.push("inspect EC sensor units, sample availability, and calibration");
    }
    if (humidity !== null && (humidity < 0.0 || humidity > 100.0)) {
      addUnique(labels, "impossible_humidity"); addUnique(suspect, "humidity_pct");
      checks.push("validate humidity sensor range and compare with a backup reading");
    }
    if (air !== null) {
      if (air < -10.0 || air > 65.0) {
        addUnique(labels, "impossible_temperature"); addUnique(suspect, "air_temperature_c");
        checks.push("compare air temperature against a backup sensor and check units");
      }
      if (backupAir !== null && Math.abs(air - backupAir) >= 8.0) {
        addUnique(labels, "conflicting_readings"); addUnique(suspect, "air_temperature_c");
        addUnique(suspect, "backup_air_temperature_c");
        checks.push("compare primary and backup temperature probes before using the value");
      }
    }
    for (const [field, low, high, check] of [
      ["water_temperature_c", 0.0, 50.0, "compare water temperature with a second thermometer; -127 or 85 C are common probe error codes"],
      ["substrate_temperature_c", -10.0, 60.0, "compare substrate temperature with a second thermometer; -127 or 85 C are common probe error codes"],
    ]) {
      const value = numeric(get(sensor, field));
      if (value !== null && (value < low || value > high)) {
        addUnique(labels, "impossible_temperature"); addUnique(suspect, field);
        checks.push(check);
      }
    }
    if (tempF !== null && has(sensor, "air_temperature_c")) {
      addUnique(labels, "unit_mismatch"); addUnique(suspect, "air_temperature_c"); addUnique(suspect, "temperature_f");
      checks.push("verify temperature units and sensor mapping before comparing thresholds");
    }
    if (sampled !== null && nowUs !== null && nowUs - sampled > 3600n * US_PER_S) {
      addUnique(labels, "stale_reading"); addUnique(suspect, "timestamp");
      checks.push("confirm the latest telemetry timestamp before using this packet");
    }
    applyTemporalChecks(sensor, history || [], labels, suspect, checks);
    if (!checks.length) checks.push("continue routine monitoring");
    return {
      data_quality_labels: labels, missing_fields: missing, suspect_fields: suspect, safe_next_checks: checks,
      human_review_required: Boolean(labels.length || missing.length || suspect.length),
      rationale: labels.length ? "Sensor packet needs verification before downstream risk or action reasoning."
        : "Critical sensor readings are present and inside plausible ranges.",
    };
  }

  return { deriveSensorQuality, parseTimestampUs, numeric, FIELD_LABELS, US_PER_S };
});
