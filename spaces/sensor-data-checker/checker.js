/*
 * Log-file checking on top of rules.js: CSV parsing, format detection, grouping readings
 * into packets per device stream, running the Pomona rules on each packet, and log-level
 * issues (gaps, reboots, out-of-order times).
 *
 * Time handling for logs: the rules judge "stale" against a check time. Applied to every
 * historical row that would flag the whole file, so only the LATEST packet in each stream
 * is judged against the check time (exactly as Pomona does live). Earlier packets get the
 * same rules with their own sample time as "now", plus the future-timestamp check against
 * the check time. Each packet sees the previous 11 packets of its stream as history, like
 * the Pomona dashboard.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./rules.js"));
  else root.PomonaChecker = factory(root.PomonaRules);
})(typeof self !== "undefined" ? self : this, function (R) {
  "use strict";

  const HISTORY_SIZE = 11;
  const US = R.US_PER_S;
  const FUTURE_CHECK = "verify device clock: sample timestamp is more than 60 seconds in the future";

  const ALIASES = {
    timestamp: ["timestamp", "timestamp_utc", "time", "datetime", "date_time", "ts", "created_at", "sample_time", "date"],
    device_id: ["device_id", "device", "node", "node_id", "sensor_node"],
    zone_id: ["zone_id", "zone"],
    air_temperature_c: ["air_temperature_c", "air_temperature", "air_temp", "temperature", "temp", "temperature_c", "temp_c", "air_temp_c"],
    temperature_f: ["temperature_f", "temp_f", "air_temperature_f"],
    humidity_pct: ["humidity_pct", "humidity", "rh", "relative_humidity", "hum", "humidity_percent"],
    ph: ["ph"],
    ec_ms_cm: ["ec_ms_cm", "ec", "ec_ms", "conductivity", "electrical_conductivity"],
    soil_moisture_pct: ["soil_moisture_pct", "soil_moisture", "moisture", "moisture_pct"],
    substrate_moisture_pct: ["substrate_moisture_pct", "substrate_moisture"],
    water_temperature_c: ["water_temperature_c", "water_temperature", "water_temp", "water_temp_c"],
    substrate_temperature_c: ["substrate_temperature_c", "substrate_temperature", "substrate_temp", "soil_temperature", "soil_temp"],
    previous_ph: ["previous_ph"],
    backup_air_temperature_c: ["backup_air_temperature_c"],
  };
  const SENSOR_FIELDS = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "soil_moisture_pct",
    "substrate_moisture_pct", "water_temperature_c", "substrate_temperature_c"];

  function normalizeHeader(h) {
    return String(h).trim().toLowerCase()
      .replace(/\(.*?\)|\[.*?\]/g, "")
      .replace(/[°%]/g, "")
      .trim()
      .replace(/[\s\-/.]+/g, "_")
      .replace(/^_+|_+$/g, "");
  }
  function lookupAlias(h) {
    const n = normalizeHeader(h);
    for (const [field, names] of Object.entries(ALIASES)) if (names.includes(n)) return field;
    return null;
  }

  function parseCsv(text) {
    text = text.replace(/^﻿/, "");
    const lines = text.split(/\r?\n/).filter((l) => l.trim() && !l.trimStart().startsWith("#"));
    const first = lines[0] || "";
    const delim = [",", ";", "\t"].map((d) => [d, first.split(d).length]).sort((a, b) => b[1] - a[1])[0][0];
    const rows = [];
    for (const line of lines) {
      const cells = [];
      let cell = "", quoted = false;
      for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (quoted) {
          if (ch === '"' && line[i + 1] === '"') { cell += '"'; i++; }
          else if (ch === '"') quoted = false;
          else cell += ch;
        } else if (ch === '"' && cell === "") quoted = true;
        else if (ch === delim) { cells.push(cell); cell = ""; }
        else cell += ch;
      }
      cells.push(cell);
      rows.push(cells);
    }
    return { headers: rows.shift() || [], rows, delimiter: delim };
  }

  const cellValue = (v) => {
    if (v === undefined) return null;
    const t = v.trim();
    return t === "" ? null : t;
  };

  function buildPackets(headers, rows) {
    const norm = headers.map(normalizeHeader);
    const idx = (name) => norm.indexOf(name);
    const long = idx("measurement") >= 0 && idx("value") >= 0;
    const streams = new Map();
    const fieldsPresent = new Set();
    const notes = [];
    let duplicates = 0;
    const streamOf = (device, zone) => {
      const key = `${device || "device"} · ${zone || "zone"}`;
      if (!streams.has(key)) streams.set(key, { key, packets: [], byTime: new Map() });
      return streams.get(key);
    };

    if (long) {
      const tsCol = ["timestamp_utc", "timestamp", "time", "datetime"].map(idx).find((i) => i >= 0) ?? -1;
      const col = (name) => idx(name);
      rows.forEach((cells, n) => {
        const stream = streamOf(cellValue(cells[col("device_id")]), cellValue(cells[col("zone_id")]));
        const ts = tsCol >= 0 ? cellValue(cells[tsCol]) : null;
        const field = normalizeHeader(cells[col("measurement")] || "");
        if (!field) return;
        let packet = ts === null ? null : stream.byTime.get(ts);
        if (!packet) {
          packet = { rows: [], packet: {}, bootId: cellValue(cells[col("boot_id")]) };
          if (ts !== null) { packet.packet.timestamp = ts; stream.byTime.set(ts, packet); }
          stream.packets.push(packet);
        }
        packet.rows.push(n + 2);
        if (Object.prototype.hasOwnProperty.call(packet.packet, field)) { duplicates++; return; }
        packet.packet[field] = cellValue(cells[col("value")]);
        if (SENSOR_FIELDS.includes(field)) fieldsPresent.add(field);
      });
    } else {
      const mapping = headers.map(lookupAlias);
      if (!mapping.includes("timestamp")) notes.push("No timestamp column found; every row will be flagged for a missing timestamp.");
      const ignored = headers.filter((h, i) => mapping[i] === null);
      if (ignored.length) notes.push(`Ignored columns: ${ignored.join(", ")}.`);
      const seen = new Set();
      mapping.forEach((f, i) => { if (f && seen.has(f)) notes.push(`Two columns map to ${f}; using the first ("${headers[mapping.indexOf(f)]}").`); if (f) seen.add(f); });
      rows.forEach((cells, n) => {
        const get = (field) => { const i = mapping.indexOf(field); return i >= 0 ? cellValue(cells[i]) : null; };
        const stream = streamOf(get("device_id"), get("zone_id"));
        const packet = {};
        mapping.forEach((field, i) => {
          if (!field || field === "device_id" || field === "zone_id" || Object.prototype.hasOwnProperty.call(packet, field)) return;
          packet[field] = cellValue(cells[i]);
          if (SENSOR_FIELDS.includes(field)) fieldsPresent.add(field);
        });
        stream.packets.push({ rows: [n + 2], packet, bootId: null });
      });
    }
    for (const s of streams.values()) delete s.byTime;
    return { format: long ? "long" : "wide", streams: [...streams.values()], fieldsPresent: [...fieldsPresent], notes, duplicates };
  }

  function evaluatePacket(ctx, packet, expected, history, nowUs, isLatest) {
    if (isLatest) return R.deriveSensorQuality(ctx, packet, expected, nowUs, history);
    const sampled = R.parseTimestampUs(packet.timestamp);
    const out = R.deriveSensorQuality(ctx, packet, expected, sampled, history);
    if (sampled !== null && nowUs !== null && sampled - nowUs > 60n * US) {
      if (!out.data_quality_labels.includes("insufficient_context")) out.data_quality_labels.push("insufficient_context");
      if (!out.suspect_fields.includes("timestamp")) out.suspect_fields.push("timestamp");
      out.safe_next_checks = out.safe_next_checks.filter((c) => c !== "continue routine monitoring");
      out.safe_next_checks.push(FUTURE_CHECK);
      out.human_review_required = true;
      out.rationale = "Sensor packet needs verification before downstream risk or action reasoning.";
    }
    return out;
  }

  function median(values) {
    if (!values.length) return null;
    const s = [...values].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    return s[Math.floor(s.length / 2)];
  }

  function checkLog(built, ctx, expected, nowUs) {
    const results = [];
    const issues = { gaps: [], outOfOrder: [], reboots: [], latest: [] };
    for (const stream of built.streams) {
      const packets = stream.packets;
      packets.forEach((p, i) => {
        const history = packets.slice(Math.max(0, i - HISTORY_SIZE), i).map((h) => h.packet);
        const isLatest = i === packets.length - 1;
        results.push({ stream: stream.key, rows: p.rows, isLatest, packet: p.packet,
          out: evaluatePacket(ctx, p.packet, expected, history, nowUs, isLatest) });
      });
      const times = packets.map((p) => R.parseTimestampUs(p.packet.timestamp));
      const deltas = [];
      for (let i = 1; i < times.length; i++) {
        if (times[i] === null || times[i - 1] === null) continue;
        const d = times[i] - times[i - 1];
        if (d < 0n) issues.outOfOrder.push({ stream: stream.key, row: packets[i].rows[0], at: packets[i].packet.timestamp });
        else deltas.push(d);
      }
      const typical = median(deltas);
      // Future-dated rows are reported per packet; they would only create fake gaps here.
      const future = (t) => nowUs !== null && t !== null && t - nowUs > 60n * US;
      if (typical !== null) {
        const limit = [typical * 3n, 600n * US].reduce((a, b) => (a > b ? a : b));
        for (let i = 1; i < times.length; i++) {
          if (times[i] === null || times[i - 1] === null || future(times[i]) || future(times[i - 1])) continue;
          const d = times[i] - times[i - 1];
          if (d > limit) issues.gaps.push({ stream: stream.key, from: packets[i - 1].packet.timestamp,
            to: packets[i].packet.timestamp, seconds: Number(d / US), typicalSeconds: Number(typical / US) });
        }
      }
      for (let i = 1; i < packets.length; i++) {
        const a = packets[i - 1].bootId, b = packets[i].bootId;
        if (a && b && a !== b) issues.reboots.push({ stream: stream.key, at: packets[i].packet.timestamp, row: packets[i].rows[0] });
      }
      // "Latest" is the last packet in file order: the one judged against the check time.
      const last = times[times.length - 1];
      if (last !== null && last !== undefined && nowUs !== null) issues.latest.push({ stream: stream.key, ageSeconds: Number((nowUs - last) / US) });
    }
    return { results, issues };
  }

  function resultsToCsv(results) {
    const esc = (v) => { const s = String(v ?? ""); return /[",\n]/.test(s) || /^[=+\-@]/.test(s) ? `"${(/^[=+\-@]/.test(s) ? "'" : "") + s.replace(/"/g, '""')}"` : s; };
    const lines = [["stream", "csv_rows", "timestamp", "latest_in_stream", "labels", "missing_fields", "suspect_fields",
      "human_review_required", "safe_next_checks"].join(",")];
    for (const r of results) {
      lines.push([r.stream, r.rows.join(" "), r.packet.timestamp ?? "", r.isLatest, r.out.data_quality_labels.join(" "),
        r.out.missing_fields.join(" "), r.out.suspect_fields.join(" "), r.out.human_review_required,
        r.out.safe_next_checks.join(" | ")].map(esc).join(","));
    }
    return lines.join("\n") + "\n";
  }

  return { parseCsv, buildPackets, checkLog, resultsToCsv, SENSOR_FIELDS, lookupAlias, HISTORY_SIZE };
});
