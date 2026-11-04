/*
 * Pomona sensor-quality veto, ported to JavaScript.
 *
 * Source of truth: services/model-router/app/trust_gate.py (apply_sensor_veto, neutral_specialists).
 * The page runs sensor quality (rules.js) -> this veto -> the tomato rules, like the platform pipeline.
 * tests/parity.test.cjs checks the whole chain against the Python one; run it after changing either side.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PomonaTrustGate = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Labels that make the whole packet untrustworthy, not one probe.
  const GLOBAL_VETO_LABELS = ["stale_reading", "insufficient_context", "unit_mismatch"];
  // Fields that describe one measurement: vetoing one vetoes the others.
  const COMPANION_GROUPS = [
    ["ph", "previous_ph"],
    ["air_temperature_c", "backup_air_temperature_c", "temperature_f"],
  ];
  const VETO_CHECK = "resolve the sensor-quality flags before domain reasoning";

  const isPlainObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
  const mask = (packet, vetoed) => {
    if (!isPlainObject(packet)) return packet;
    const out = {};
    Object.keys(packet).forEach((key) => { if (!vetoed.has(key)) out[key] = packet[key]; });
    return out;
  };

  // Returns { sensor, history, gate }. Vetoed fields are removed, never rewritten.
  function applySensorVeto(sensor, history, quality, expectedFields) {
    const labels = new Set(quality.data_quality_labels || []);
    const vetoed = new Set([...(quality.suspect_fields || []), ...(quality.missing_fields || [])]);
    const frames = history || [];
    const present = new Set();
    [sensor, ...frames].forEach((frame) => { if (isPlainObject(frame)) Object.keys(frame).forEach((key) => present.add(key)); });
    COMPANION_GROUPS.forEach((group) => {
      if (group.some((field) => vetoed.has(field))) group.forEach((field) => { if (present.has(field)) vetoed.add(field); });
    });
    const expected = new Set(expectedFields || []);
    const globalLabels = GLOBAL_VETO_LABELS.filter((label) => labels.has(label)).sort();
    const globalVeto = globalLabels.length > 0 || vetoed.has("timestamp");
    if (globalVeto) expected.forEach((field) => vetoed.add(field));

    let verdict;
    if (globalVeto || (expected.size > 0 && [...expected].every((field) => vetoed.has(field)))) verdict = "cannot_confirm";
    else if (labels.size || vetoed.size) verdict = "partial";
    else verdict = "trusted";

    const vetoedSorted = [...vetoed].sort();
    let reason;
    if (verdict === "trusted") reason = "all expected readings passed the sensor check";
    else if (globalVeto) reason = `packet could not be confirmed (${globalLabels.join(", ") || "timestamp"}); no readings used`;
    else reason = `${vetoedSorted.join(", ") || "readings"} failed the sensor check and were not used`;
    const gate = { trust_verdict: verdict, vetoed_fields: vetoedSorted, global_veto: globalVeto, reason };
    return { sensor: mask(sensor, vetoed), history: frames.map((frame) => mask(frame, vetoed)), gate };
  }

  // The tomato result for a vetoed packet (same shape the tomato rules return).
  function neutralTomato() {
    return { risk_labels: [], missing_data: [], safe_next_checks: [VETO_CHECK], blocked_actions: [],
      human_review_required: false, vpd_kpa: null };
  }

  return { applySensorVeto, neutralTomato, GLOBAL_VETO_LABELS, COMPANION_GROUPS, VETO_CHECK };
});
