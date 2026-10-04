/* UI for the Pomona pH Calibration Checker. All processing stays in the browser. */
(function () {
  "use strict";
  const C = window.PomonaCalibration;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (id) => { const t = $(id).value.trim(); return t === "" ? null : Number(t); };
  const valid = (x) => x !== null && Number.isFinite(x);

  function render() {
    const v7 = num("v7"), v4 = num("v4"), v10 = num("v10");
    const out = $("result");
    if (v7 === null || v4 === null) { out.innerHTML = '<p class="muted">Enter the two buffer readings above.</p>'; return; }
    if (!valid(v7) || !valid(v4) || (v10 !== null && !valid(v10))) { out.innerHTML = '<p class="muted">Readings must be numbers (volts).</p>'; return; }
    const expectedMv = num("expected-mv") || 0;
    const expectedSign = Number($("expected-sign").value);
    const r = C.evaluate(v7, v4, v10, expectedMv > 0 ? expectedMv : 0, expectedSign);
    if (r.slope === null) {
      out.innerHTML = `<span class="badge bad">Not usable</span><p>${esc(r.reason)}</p>`;
      return;
    }
    const problems = [];
    if (r.reason) problems.push(r.reason);
    if (r.ph10_ok === false) problems.push("the pH 10 point is off the line by more than 0.3 pH: probe is nonlinear or a buffer is bad");
    const badge = problems.length ? '<span class="badge bad">Check failed</span>' : '<span class="badge ok">Calibration looks sane</span>';
    let html = `${badge}
      <div class="tiles">
        <div class="tile"><div class="big">${r.mv_per_ph.toFixed(0)} mV/pH</div><div class="label">sensitivity</div></div>
        <div class="tile"><div class="big">${r.v_at_ph7.toFixed(3)} V</div><div class="label">expected in pH 7 buffer</div></div>
        <div class="tile"><div class="big">${r.direction < 0 ? "falls" : "rises"}</div><div class="label">volts as pH rises</div></div>
        ${r.ph10_predicted === null ? "" : `<div class="tile"><div class="big">${r.ph10_predicted.toFixed(2)}</div><div class="label">predicted pH at your pH 10 volts (error ${r.ph10_error >= 0 ? "+" : ""}${r.ph10_error.toFixed(2)})</div></div>`}
      </div>`;
    if (problems.length) html += `<ul class="problems">${problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>`;

    const f7 = num("first-v7"), f4 = num("first-v4");
    if (valid(f7) && valid(f4) && !problems.length) {
      const t = C.trend({ v7: f7, v4: f4 }, { v7, v4 });
      if (!t) html += '<p class="muted">The first calibration has identical pH 7 and pH 4 readings, so there is nothing to compare.</p>';
      else {
        const tone = t.status === "ok" ? "ok" : t.status === "weakening" ? "warn" : "bad";
        html += `<h3 style="font-size:15px;margin:14px 0 6px">Compared with the first calibration</h3>
          <span class="badge ${tone}">${esc(t.status)}</span>
          <div class="tiles">
            <div class="tile"><div class="big">${t.sensitivity_vs_first_pct.toFixed(0)} %</div><div class="label">of the first sensitivity (${t.first_mv_per_ph.toFixed(0)} to ${t.latest_mv_per_ph.toFixed(0)} mV/pH)</div></div>
            <div class="tile"><div class="big">${(t.v_at_ph7_shift_v * 1000).toFixed(0)} mV</div><div class="label">shift of the pH 7 voltage</div></div>
          </div>${t.reasons.length ? `<ul class="problems">${t.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}`;
      }
    }

    if (problems.length) {
      html += '<p class="muted">Not offering config values for a calibration that failed its check. Fix the cause (fresh buffers, settle time, wiring) and measure again.</p>';
      out.innerHTML = html;
      return;
    }
    const config = `#define PH_SLOPE  ${r.slope.toFixed(4)}f\n#define PH_OFFSET ${r.offset.toFixed(4)}f\n` +
      `// optional stricter check for this board:\n// #define PH_EXPECTED_MV_PER_PH ${r.mv_per_ph.toFixed(0)}\n// #define PH_EXPECTED_SLOPE_SIGN ${r.direction}`;
    html += `<h3 style="font-size:15px;margin:14px 0 6px">For <code>include/config.h</code></h3>
      <pre id="config">${esc(config)}</pre>
      <button id="copy" type="button">Copy</button> <span id="copied" class="muted"></span>
      <p class="muted">Then record the calibration in Pomona Core (<code>POST /v1/sensors/calibrations</code>, <code>raw</code> in volts) to track the probe over time.</p>`;
    out.innerHTML = html;
    $("copy").addEventListener("click", () => {
      navigator.clipboard.writeText(config).then(() => { $("copied").textContent = "Copied."; },
        () => { $("copied").textContent = "Select the text and copy it."; });
    });
  }

  for (const id of ["v7", "v4", "v10", "expected-mv", "expected-sign", "first-v7", "first-v4"]) $(id).addEventListener("input", render);
  $("example").addEventListener("click", () => {
    const values = { v7: "2.503", v4: "3.041", v10: "1.97", "expected-mv": "180", "expected-sign": "-1", "first-v7": "2.50", "first-v4": "3.04" };
    for (const [id, value] of Object.entries(values)) $(id).value = value;
    document.querySelectorAll("details").forEach((d) => { d.open = true; });
    render();
  });
  render();
})();
