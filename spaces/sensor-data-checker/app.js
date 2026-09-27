/* UI for the Pomona Sensor Data Checker. All processing stays in the browser. */
(function () {
  "use strict";
  const R = window.PomonaRules;
  const C = window.PomonaChecker;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const MAX_ROWS = 400;

  const LABELS = {
    missing_ph: ["bad", "pH missing", "No pH value (empty, null or not logged)."],
    missing_ec: ["bad", "EC missing", "No EC value."],
    missing_temperature: ["bad", "Temperature missing", "An expected temperature reading is missing."],
    missing_humidity: ["bad", "Humidity missing", "No humidity value."],
    missing_moisture: ["bad", "Moisture missing", "No soil/substrate moisture value."],
    impossible_ph: ["bad", "Impossible pH", "pH below 3 or above 11: almost always a probe, wiring or calibration problem."],
    impossible_ec: ["bad", "Impossible EC", "EC below 0 or above 12 mS/cm. If you log µS/cm, divide by 1000."],
    impossible_temperature: ["bad", "Impossible temperature", "Air temperature below −10 °C or above 65 °C."],
    impossible_humidity: ["bad", "Impossible humidity", "Humidity below 0 % or above 100 %."],
    insufficient_context: ["bad", "Can't trust this packet", "A value isn't a number (e.g. \"err\", \"NaN\"), the timestamp is missing, has no timezone or is in the future, or crop/system/expected readings aren't set."],
    unit_mismatch: ["bad", "Unit mismatch", "Both Celsius and Fahrenheit temperatures are present; check which one is real."],
    conflicting_readings: ["bad", "Sensors disagree", "Primary and backup air temperature differ by 8 °C or more."],
    stale_reading: ["warn", "Stale", "The latest reading is more than 1 hour older than the check time: the logger may have stopped."],
    stuck_value: ["warn", "Stuck value", "Exactly the same value 3 times in a row after it had been changing: a frozen sensor or repeated cached value."],
    sensor_drift_possible: ["warn", "Sudden pH jump", "pH moved by 0.8 or more from the previous reading."],
    baseline_drift_possible: ["warn", "Drift", "pH (≥0.35) or EC (≥0.4 mS/cm) has stayed away from its value 11 readings earlier: recalibrate or verify with a handheld meter."],
    flatline_possible: ["hint", "Very flat (hint)", "Almost no change across 3 readings. Often fine for slow-changing values at short intervals; worth a glance if it persists."],
  };
  const info = (l) => LABELS[l] || ["warn", l, ""];
  const chip = (l, extra = "") => `<span class="chip ${info(l)[0]}" title="${esc(info(l)[2])}"${extra}>${esc(info(l)[1])}</span>`;

  let loaded = null;   // {name, csv, built}
  let last = null;     // {results, issues}
  let filterLabel = null;

  // ---- tabs ----
  for (const [tab, panel] of [["tab-csv", "panel-csv"], ["tab-json", "panel-json"]]) {
    $(tab).addEventListener("click", () => {
      for (const [t, p] of [["tab-csv", "panel-csv"], ["tab-json", "panel-json"]]) {
        $(t).setAttribute("aria-selected", String(t === tab));
        $(p).hidden = p !== panel;
      }
    });
  }

  // ---- check time ----
  const isoNow = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  $("now").value = isoNow();
  $("set-now").addEventListener("click", () => { $("now").value = isoNow(); });

  // ---- loading CSV ----
  function load(name, text) {
    $("csv-error").textContent = "";
    const csv = C.parseCsv(text);
    if (!csv.headers.length || !csv.rows.length) { $("csv-error").textContent = "The file has no data rows."; return; }
    const built = C.buildPackets(csv.headers, csv.rows);
    loaded = { name, csv, built };
    const packets = built.streams.reduce((n, s) => n + s.packets.length, 0);
    $("file-info").innerHTML = `<strong>${esc(name)}</strong>: ${csv.rows.length} rows → ${packets} readings from ${built.streams.length} device(s), ` +
      `${built.format === "long" ? "one row per measurement" : "one row per reading time"}. Recognised: ${built.fieldsPresent.map((f) => `<code>${esc(f)}</code>`).join(", ") || "no sensor columns"}.` +
      (built.duplicates ? ` ${built.duplicates} duplicate measurement rows ignored.` : "") +
      (built.notes.length ? `<br>${built.notes.map(esc).join(" ")}` : "");
    $("fields").innerHTML = C.SENSOR_FIELDS.map((f) =>
      `<label><input type="checkbox" value="${f}" ${built.fieldsPresent.includes(f) ? "checked" : ""}> ${f}</label>`).join("");
    $("expected-box").hidden = false;
    $("run").disabled = false;
    if (!built.fieldsPresent.length) $("csv-error").textContent = "No recognised sensor columns; see “Which CSV layouts work?”.";
  }
  $("file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) f.text().then((t) => load(f.name, t)); });
  const drop = $("drop");
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault(); drop.classList.remove("over");
    const f = e.dataTransfer.files[0]; if (f) f.text().then((t) => load(f.name, t));
  });
  $("use-text").addEventListener("click", () => load("pasted text", $("csv-text").value));
  document.querySelectorAll("[data-sample]").forEach((b) => b.addEventListener("click", async () => {
    const name = b.dataset.sample;
    try {
      const text = await (await fetch(`samples/${name}`)).text();
      load(name, text);
      if (name.startsWith("pomona")) { $("crop").value = "watercress"; $("system").value = "hydroponic"; $("now").value = "2026-10-06T09:00:00Z"; }
      else { $("crop").value = "lettuce"; $("system").value = "hydroponic"; $("now").value = "2026-10-06T08:00:00Z"; }
      run();
    } catch (err) { $("csv-error").textContent = `Could not load the example: ${err.message}`; }
  }));

  // ---- run ----
  function run() {
    if (!loaded) return;
    $("csv-error").textContent = "";
    const nowUs = R.parseTimestampUs($("now").value.trim());
    if (nowUs === null) { $("csv-error").textContent = "Check time must be an ISO time with a timezone, e.g. 2026-10-06T09:00:00Z."; return; }
    const ctx = { crop: $("crop").value.trim(), system_type: $("system").value };
    const manual = document.querySelector('input[name="expmode"]:checked').value === "manual";
    const chosen = [...document.querySelectorAll("#fields input:checked")].map((i) => i.value);
    const results = [];
    const issues = { gaps: [], outOfOrder: [], reboots: [], latest: [] };
    for (const stream of loaded.built.streams) {
      const own = [...new Set(stream.packets.flatMap((p) => Object.keys(p.packet)).filter((f) => C.SENSOR_FIELDS.includes(f)))];
      const out = C.checkLog({ ...loaded.built, streams: [stream] }, ctx, manual ? chosen : own, nowUs);
      results.push(...out.results);
      for (const k of Object.keys(issues)) issues[k].push(...out.issues[k]);
    }
    last = { results, issues };
    filterLabel = null;
    render();
  }
  $("run").addEventListener("click", run);
  $("show-all").addEventListener("change", renderTable);

  const human = (s) => {
    s = Math.abs(s);
    if (s < 90) return `${Math.round(s)} s`;
    if (s < 5400) return `${Math.round(s / 60)} min`;
    if (s < 172800) return `${(s / 3600).toFixed(1)} h`;
    return `${(s / 86400).toFixed(1)} days`;
  };

  function render() {
    const { results, issues } = last;
    const flagged = results.filter((r) => r.out.data_quality_labels.length);
    const serious = results.filter((r) => r.out.data_quality_labels.some((l) => info(l)[0] === "bad"));
    const counts = {};
    for (const r of results) for (const l of r.out.data_quality_labels) counts[l] = (counts[l] || 0) + 1;
    $("tiles").innerHTML = [
      [results.length, "readings checked"],
      [serious.length, "with a clear problem"],
      [flagged.length - serious.length, "worth a look"],
      [results.length - flagged.length, "clean"],
      [issues.gaps.length, "logging gaps"],
    ].map(([n, t]) => `<div class="tile"><div class="n">${n}</div><div class="t">${t}</div></div>`).join("");
    const order = { bad: 0, warn: 1, hint: 2 };
    const entries = Object.entries(counts).sort((a, b) => order[info(a[0])[0]] - order[info(b[0])[0]] || b[1] - a[1]);
    $("labels").innerHTML = entries.length ? entries.map(([l, n]) =>
      `<li><span class="count">${n}</span><span><button class="chip ${info(l)[0]}" data-label="${l}">${esc(info(l)[1])}</button> <span class="muted">${esc(info(l)[2])}</span></span></li>`).join("")
      : `<li><span class="chip ok">All clear</span> <span class="muted">No problems found in any reading.</span></li>`;
    $("labels").querySelectorAll("button[data-label]").forEach((b) => b.addEventListener("click", () => {
      filterLabel = filterLabel === b.dataset.label ? null : b.dataset.label;
      $("labels").querySelectorAll("button[data-label]").forEach((x) => x.classList.toggle("active", x.dataset.label === filterLabel));
      renderTable();
    }));
    const items = [];
    for (const l of issues.latest) items.push(`<li><strong>${esc(l.stream)}</strong>: latest reading is ${l.ageSeconds < 0 ? `${human(l.ageSeconds)} in the future` : `${human(l.ageSeconds)} old`} at the check time.</li>`);
    for (const g of issues.gaps) items.push(`<li><strong>${esc(g.stream)}</strong>: no readings for ${human(g.seconds)} (usually every ${human(g.typicalSeconds)}), ${esc(g.from)} → ${esc(g.to)}.</li>`);
    for (const r of issues.reboots) items.push(`<li><strong>${esc(r.stream)}</strong>: device restarted (new boot id) at ${esc(r.at)}, CSV row ${r.row}.</li>`);
    for (const o of issues.outOfOrder) items.push(`<li><strong>${esc(o.stream)}</strong>: time goes backwards at ${esc(o.at)} (CSV row ${o.row}); check the device clock.</li>`);
    $("issues").innerHTML = items.length ? `<h2 style="margin-top:18px">About the log itself</h2><ul class="issues">${items.join("")}</ul>` : "";
    $("summary-card").hidden = false;
    $("table-card").hidden = false;
    renderTable();
    $("summary-card").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderTable() {
    if (!last) return;
    let rows = last.results;
    if (filterLabel) rows = rows.filter((r) => r.out.data_quality_labels.includes(filterLabel));
    else if (!$("show-all").checked) rows = rows.filter((r) => r.out.data_quality_labels.length);
    const shown = rows.slice(0, MAX_ROWS);
    $("table-note").textContent = `${rows.length} reading(s)${filterLabel ? ` labelled “${info(filterLabel)[1]}”` : $("show-all").checked ? "" : " with findings"}` +
      (rows.length > MAX_ROWS ? `; showing the first ${MAX_ROWS}, download the CSV for all.` : ".");
    $("rows").innerHTML = shown.map((r) => {
      const o = r.out;
      const result = o.data_quality_labels.length ? o.data_quality_labels.map((l) => chip(l)).join("") : `<span class="chip ok">OK</span>`;
      const fields = [...o.missing_fields.map((f) => `missing <code>${esc(f)}</code>`), ...o.suspect_fields.map((f) => `suspect <code>${esc(f)}</code>`)];
      const checks = o.safe_next_checks.filter((c) => c !== "continue routine monitoring");
      const what = (fields.length ? `<div class="muted">${fields.join(", ")}</div>` : "") +
        (checks.length ? `<ul>${checks.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : "");
      return `<tr><td class="time">${esc(r.packet.timestamp ?? "(no time)")}${r.isLatest ? '<span class="latest">latest</span>' : ""}</td>` +
        `<td>${esc(r.stream)}</td><td>${result}</td><td>${what}</td><td data-k="CSV row">${r.rows.slice(0, 3).join(", ")}${r.rows.length > 3 ? "…" : ""}</td></tr>`;
    }).join("");
  }

  $("download").addEventListener("click", () => {
    if (!last) return;
    const blob = new Blob([C.resultsToCsv(last.results)], { type: "text/csv" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: "pomona-sensor-check.csv" });
    document.body.appendChild(a); a.click(); a.remove();
  });

  // ---- JSON packet ----
  $("json-text").value = JSON.stringify({
    farm_context: { crop: "watercress", system_type: "hydroponic" },
    sensor: { air_temperature_c: 21.4, humidity_pct: 66, ph: "broken", ec_ms_cm: 0.9, timestamp: "2026-10-06T08:55:00Z" },
    expected_fields: ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"],
    current_time: "2026-10-06T09:00:00Z",
  }, null, 2);
  $("run-json").addEventListener("click", () => {
    $("json-error").textContent = "";
    let data;
    try { data = JSON.parse($("json-text").value); } catch (err) { $("json-error").textContent = `Not valid JSON: ${err.message}`; return; }
    if (data === null || typeof data !== "object" || Array.isArray(data)) { $("json-error").textContent = "Expected a JSON object."; return; }
    const nowUs = data.current_time === undefined ? R.parseTimestampUs(isoNow()) : R.parseTimestampUs(data.current_time);
    if (nowUs === null) { $("json-error").textContent = "current_time must be an ISO time with a timezone."; return; }
    const out = R.deriveSensorQuality(data.farm_context, data.sensor, data.expected_fields, nowUs, data.history ?? null);
    $("json-result").innerHTML = `<p>${out.data_quality_labels.length ? out.data_quality_labels.map((l) => chip(l)).join("") : '<span class="chip ok">OK</span>'}</p>` +
      `<pre>${esc(JSON.stringify(out, null, 2))}</pre>`;
  });
})();
