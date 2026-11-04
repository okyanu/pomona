/* Try to fool Pomona: the page. Pomona's real Python runs in a Web Worker (Pyodide, see worker.js); this file only
 * shows it. Nothing is sent to any server. The page keeps the scenario (seed + commands + ticks) and sends it to the
 * worker with every request, so a reload loses nothing: the worker replays it. Replay links carry the same scenario in
 * the URL hash. */
(() => {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const STORE_KEY = "fool-pomona-scenario-v1";
  const state = { info: null, scenario: null, view: null, busy: false, loaded: false,
                  ui: { trick: "stuck", zone: null, field: null, calZone: null, calField: null }, nextFocus: null };

  // ---- small helpers -------------------------------------------------------------------------

  const $ = (selector) => document.querySelector(selector);
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }
  function svg(tag, attrs) {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    return node;
  }
  function fill(node, ...kids) {
    node.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
    return node;
  }
  function safe(fn) { try { return fn(); } catch (e) { return null; } }
  const pad = (n) => String(n).padStart(2, "0");
  const letter = (zone) => state.info.zones.find((z) => z.id === zone)?.letter || zone;
  const fieldWord = (key) => (state.info.fields[key]?.label || key).toLowerCase().replace(/^ph$/, "pH").replace(/^ec$/, "EC");

  function tickDate(tick) {
    return new Date(Date.parse(state.view.clock.start_time) + tick * state.view.clock.tick_seconds * 1000);
  }
  function clockText(tick) {
    const d = tickDate(tick);
    return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  }
  function dayClock(isoOrDate) {
    const d = new Date(isoOrDate);
    const day = Math.floor((d - Date.parse(state.view.clock.start_time)) / 86400000) + 1;
    return `Day ${day}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  }
  function minutes(total) {
    const h = Math.floor(total / 60), m = Math.round(total % 60);
    return h ? `${h} h ${pad(m)} min` : `${m} min`;
  }
  function fmt(key, value) {
    if (value === null || value === undefined) return "–";
    return (key === "ph" || key === "ec_ms_cm") ? value.toFixed(2) : value.toFixed(1);
  }

  // ---- talking to the worker ---------------------------------------------------------------------

  let workingTimer = null;
  function showStatus(message, isError, working) {
    const box = $("#status");
    if (!message) { box.hidden = true; return; }
    box.textContent = message;
    box.className = "status wrap" + (isError ? " error" : "") + (working ? " working" : "");
    box.hidden = false;
  }

  const worker = new Worker("worker.js", { type: "module" });
  const pending = new Map();
  let nextId = 1;

  function showLoading(fraction, text) {
    $("#load-progress").value = Math.round(fraction * 100);
    $("#load-text").textContent = text;
  }
  function loadFailed(message) {
    $("#loading").classList.add("failed");
    $("#load-title").textContent = "Pomona's engine could not start in this browser";
    $("#load-text").textContent = message || "The page needs a current browser with WebAssembly and module workers.";
  }

  worker.onmessage = ({ data }) => {
    if (data.type === "progress" && data.phase === "load") return showLoading(data.fraction, data.text);
    if (data.type === "ready") return;
    if (data.type === "fatal") return loadFailed(data.error);
    const entry = pending.get(data.id);
    if (!entry) return;
    if (data.type === "progress") return entry.onProgress && entry.onProgress(data);
    pending.delete(data.id);
    if (data.error) {
      const err = new Error(data.error);
      err.refused = Boolean(data.refused);
      entry.reject(err);
    } else {
      entry.resolve(data.result);
    }
  };
  worker.onerror = (event) => {
    event.preventDefault();
    loadFailed("The worker could not be loaded" + (event.message ? ": " + event.message : "."));
    for (const entry of pending.values()) entry.reject(new Error("Pomona's engine is not running."));
    pending.clear();
  };

  function request(type, body, onProgress) {
    return new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject, onProgress });
      worker.postMessage({ id, type, body });
    });
  }

  async function act(payload) {
    if (state.busy) return;
    setBusy(true);
    clearTimeout(workingTimer);
    const ticks = payload.advance || 0;
    // A long fast-forward takes a moment: say so once it is noticeable. The page stays responsive (the worker computes).
    workingTimer = setTimeout(() => showStatus(ticks >= 120
      ? `Simulating ${ticks / 120} greenhouse hours, one reading every 30 seconds. This takes a few seconds.`
      : "Simulating…", false, true), 400);
    const onProgress = (p) => {
      clearTimeout(workingTimer);
      showStatus(`Rebuilding your run: ${Math.min(100, Math.floor((p.tick / Math.max(p.total, 1)) * 100))}%`, false, true);
    };
    try {
      const result = await request("act", payload, onProgress);
      state.scenario = result.scenario;
      state.view = result.view;
      persist();
      showStatus("");
      render();
    } catch (error) {
      showStatus(error.message || "Something went wrong.", true);
    } finally {
      clearTimeout(workingTimer);
      setBusy(false);
    }
  }

  function setBusy(busy) {
    state.busy = busy;
    document.body.setAttribute("aria-busy", busy ? "true" : "false");
    updateDisabled();
  }

  function updateDisabled() {
    const view = state.view;
    const atCap = view?.clock.at_cap;
    document.querySelectorAll(".needs-idle").forEach((node) => {
      let off = state.busy || !state.loaded;
      if (!off && atCap && (node.dataset.ticks || node.id === "start-trick" || node.id === "hidden-btn" || node.id === "cal-btn")) off = true;
      if (!off && node.id === "reveal-btn") off = !view || view.hidden.total === 0 || view.hidden.revealed;
      if (!off && node.id === "hidden-btn") off = !view || view.hidden.revealed || view.hidden.total >= 3;
      node.disabled = off;
    });
  }

  // ---- saving and sharing the scenario ----------------------------------------------------------------

  function persist() {
    safe(() => localStorage.setItem(STORE_KEY, JSON.stringify(state.scenario)));
  }
  function zoneShort(zone) { return zone ? zone.replace("greenhouse-", "") : 0; }
  function zoneLong(zone) { return zone ? (zone.length === 1 ? "greenhouse-" + zone : zone) : undefined; }

  function encodeScenario(sc) {
    const compact = { v: 1, s: sc.seed, n: sc.ticks, c: sc.commands.map((c) => [c.t, c.op, c.name || 0, zoneShort(c.zone), c.field || 0]) };
    return btoa(JSON.stringify(compact)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function decodeScenario(text) {
    const b64 = text.replace(/-/g, "+").replace(/_/g, "/");
    const compact = JSON.parse(atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4)));
    if (compact.v !== 1 || !Array.isArray(compact.c)) throw new Error("bad link");
    return { v: 1, seed: compact.s, ticks: compact.n, commands: compact.c.map(([t, op, name, zone, field]) => {
      const cmd = { t, op };
      if (name) cmd.name = name;
      if (zone) cmd.zone = zoneLong(zone);
      if (field) cmd.field = field;
      return cmd;
    }) };
  }
  function replayLink() {
    return `${location.origin}${location.pathname}#r=${encodeScenario(state.scenario)}`;
  }

  async function copyLink() {
    const link = replayLink();
    const field = $("#link-field");
    field.value = link;
    field.hidden = false;
    let copied = false;
    try { await navigator.clipboard.writeText(link); copied = true; } catch (e) { /* fall through to manual copy */ }
    if (!copied) { field.focus(); field.select(); }
    $("#copy-link").textContent = copied ? "Link copied" : "Copy the link below";
    setTimeout(() => { $("#copy-link").textContent = "Copy replay link"; }, 2500);
  }

  function downloadScenario() {
    const blob = new Blob([JSON.stringify(state.view.export, null, 2) + "\n"], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = el("a");
    link.href = url;
    link.download = `try-to-fool-pomona-${state.scenario.seed}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ---- rendering -------------------------------------------------------------------------------------

  const TRUST = {
    trusted: ["Trusted", "Pomona trusts these readings."],
    partial: ["Partly trusted", "Pomona is not using the marked readings and works from the rest."],
    cannot_confirm: ["Can't confirm", "Pomona can't confirm these readings, so it holds back advice."],
  };

  function sparkline(values) {
    const real = values.filter((v) => v !== null);
    const node = svg("svg", { viewBox: "0 0 120 28", class: "spark", role: "img", preserveAspectRatio: "none" });
    if (real.length < 2) return node;
    let low = Math.min(...real), high = Math.max(...real);
    if (high - low < 1e-9) { low -= 1; high += 1; }
    const span = high - low;
    const x = (i) => (i / Math.max(values.length - 1, 1)) * 118 + 1;
    const y = (v) => 26 - ((v - low) / span) * 24;
    let run = [];
    const flush = () => {
      if (run.length > 1) node.append(svg("polyline", { points: run.map(([i, v]) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ") }));
      else if (run.length === 1) node.append(svg("circle", { class: "dot", r: 1.5, cx: x(run[0][0]).toFixed(1), cy: y(run[0][1]).toFixed(1) }));
      run = [];
    };
    values.forEach((v, i) => { if (v === null) flush(); else run.push([i, v]); });
    flush();
    node.setAttribute("aria-label", `Last 2 simulated hours: from ${fmt("x", real[0])} to ${fmt("x", real[real.length - 1])}`);
    return node;
  }

  function renderZones() {
    const root = $("#zones");
    fill(root, state.view.zones.map((zone) => {
      const [badge, line] = zone.trust ? TRUST[zone.trust] : ["Waiting", "No reading has reached Pomona yet."];
      const box = el("article", "zone");
      box.setAttribute("aria-labelledby", `zone-${zone.id}`);
      const head = el("div", "zone-head");
      const title = el("h2", null, `Zone ${zone.letter} · ${zone.system}`);
      title.id = `zone-${zone.id}`;
      head.append(title, el("span", `badge ${zone.trust || "none"}`, badge));
      box.append(head, el("p", "trust-line", line));
      if (zone.note) box.append(el("p", "zone-note", zone.note));

      const grid = el("div", "readings");
      for (const f of zone.fields) {
        const cell = el("div", "reading" + (f.vetoed ? " vetoed" : ""));
        cell.append(el("div", "name", f.label));
        const val = el("div", "val", fmt(f.key, f.value));
        if (f.unit) val.append(" ", el("span", "unit", f.unit));
        cell.append(val);
        if (f.vetoed) cell.append(el("div", "flag", "Pomona is not using this reading"));
        cell.append(sparkline(f.series));
        grid.append(cell);
      }
      box.append(grid, el("p", "spark-cap", "Sparklines: the last 2 simulated hours, one point every 2 minutes."));

      box.append(el("h4", null, "What Pomona thinks"));
      const tags = el("div", "tags");
      if (zone.labels.length) zone.labels.forEach((label) => tags.append(el("span", "tag", label)));
      else tags.append(el("span", "muted small", "Nothing flagged in the latest reading."));
      box.append(tags);

      box.append(el("h4", null, "Open cards"));
      const cards = el("ul", "plain cards-open");
      if (zone.cards.length === 0) cards.append(el("li", null, "No open cards."));
      zone.cards.forEach((card) => {
        const li = el("li", (card.sensor ? "sensor" : "") + (card.state === "pending" ? " pending" : ""));
        li.append(el("span", "ctitle", card.title),
          el("span", "cstate", card.state === "pending" ? "watching, not raised yet" : card.state === "recovering" ? "open, clearing" : `open since ${clockText(card.since_tick)}`));
        if (card.state !== "pending") li.append(el("div", "small muted", card.message));
        cards.append(li);
      });
      box.append(cards);

      if (zone.tricks.length) {
        box.append(el("h4", null, "Your tricks running here"));
        const list = el("ul", "plain active-tricks");
        zone.tricks.forEach((t) => {
          const li = el("li");
          const what = t.title + (t.field ? ` (${fieldWord(t.field)})` : "") + (t.stopping ? ", winding down" : t.pending ? ", starting" : "");
          li.append(el("span", null, what));
          if (!t.stopping) {
            const stop = el("button", "small-btn needs-idle", "Stop");
            stop.type = "button";
            stop.addEventListener("click", () => send([{ op: "stop", name: t.name, zone: zone.id, ...(t.field ? { field: t.field } : {}) }], 1));
            li.append(stop);
          }
          list.append(li);
        });
        box.append(list);
      }
      return box;
    }));
  }

  function renderClock() {
    const c = state.view.clock;
    $("#clock-text").textContent = dayClock(c.sim_time);
    $("#clock-sub").textContent = `${minutes(c.elapsed_min)} of ${c.cap_min / 60} h simulated`;
    $("#clock-progress").value = (c.elapsed_min / c.cap_min) * 100;
    const w = state.info.windows;
    $("#time-note").textContent = `Cards wait until a problem has lasted ${w.default_min} minutes (${w.humidity_min} for humidity), so one odd reading doesn't wake a grower at 3 am. `
      + `A session is capped at ${c.cap_min / 60} simulated hours${c.at_cap ? " and this one has used them all. Start a new session to keep playing." : "."}`;
  }

  // The trick picker ---------------------------------------------------------------------------------

  function trickByName(name) { return state.info.tricks.find((t) => t.name === name); }
  function zoneInfo(id) { return state.info.zones.find((z) => z.id === id); }

  function renderPicker() {
    const ui = state.ui, trick = trickByName(ui.trick);
    for (const group of ["lie", "hurt"]) {
      const holder = $(`#chips-${group}`);
      fill(holder, state.info.tricks.filter((t) => t.group === group).map((t) => {
        const chip = el("button", "chip needs-idle", t.title);
        chip.type = "button";
        chip.setAttribute("role", "radio");
        chip.setAttribute("aria-checked", String(t.name === ui.trick));
        chip.addEventListener("click", () => { ui.trick = t.name; renderPicker(); updateDisabled(); });
        return chip;
      }));
    }
    $("#trick-blurb").textContent = trick.blurb;
    if (!trick.zones.includes(ui.zone)) ui.zone = trick.zones[0];
    fill($("#pick-zone"), trick.zones.map((id) => { const o = el("option", null, `Zone ${letter(id)} · ${zoneInfo(id).system}`); o.value = id; o.selected = id === ui.zone; return o; }));
    const wrap = $("#field-wrap");
    wrap.hidden = !trick.takes_field;
    if (trick.takes_field) {
      const fields = zoneInfo(ui.zone).fields;
      if (!fields.includes(ui.field)) ui.field = fields.includes(trick.default_field) ? trick.default_field : fields[0];
      fill($("#pick-field"), fields.map((f) => { const o = el("option", null, state.info.fields[f].label); o.value = f; o.selected = f === ui.field; return o; }));
    }
    $("#start-trick").textContent = `Start: ${trick.title}${trick.takes_field ? ` (${fieldWord(ui.field)})` : ""} in zone ${letter(ui.zone)}`;

    // calibration picker
    if (!ui.calZone) ui.calZone = state.info.zones[0].id;
    fill($("#cal-zone"), state.info.zones.map((z) => { const o = el("option", null, `Zone ${z.letter}`); o.value = z.id; o.selected = z.id === ui.calZone; return o; }));
    const cals = zoneInfo(ui.calZone).calibratable;
    if (!cals.includes(ui.calField)) ui.calField = cals[0];
    fill($("#cal-field"), cals.map((f) => { const o = el("option", null, state.info.fields[f].label); o.value = f; o.selected = f === ui.calField; return o; }));
  }

  function renderHidden() {
    const hidden = state.view.hidden;
    const list = $("#hidden-list");
    const items = [];
    if (hidden.total > 0 && !hidden.revealed) {
      items.push(el("li", null, `${hidden.total} hidden ${hidden.total === 1 ? "trick" : "tricks"} started. Fast-forward and watch Pomona, then reveal.`));
    }
    if (hidden.revealed) {
      hidden.items.forEach((h) => items.push(el("li", null, `${h.title}${h.field ? ` (${fieldWord(h.field)})` : ""} in zone ${letter(h.zone)}, from ${clockText(h.started_tick)}.`)));
      if (!hidden.items.length) items.push(el("li", null, "The hidden trick was queued but never started."));
    }
    fill(list, items);
  }

  // Scoreboard and timeline ------------------------------------------------------------------------------

  function renderScore() {
    const t = state.view.totals;
    const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
    const summary = t.fooled + t.caught + t.unfair === 0 && t.false_alarms === 0
      ? "No finished tricks yet. Start one, let it run, then stop it or fast-forward."
      : `You fooled Pomona ${plural(t.fooled, "time", "times")}, it caught ${t.caught}, ${t.unfair} unfair.`;
    $("#score-summary").textContent = summary;
    const extra = [];
    if (t.too_short) extra.push(`${t.too_short} too short to count`);
    if (t.false_alarms) extra.push(`Pomona cried wolf ${plural(t.false_alarms, "time", "times")}`);
    if (t.not_scored) extra.push(`${t.not_scored} not scored (no data arrived)`);
    if (t.running) extra.push(`${t.running} still running`);
    if (t.hidden_waiting) extra.push(`${t.hidden_waiting} hidden ${t.hidden_waiting === 1 ? "verdict waits" : "verdicts wait"} for the reveal`);
    $("#score-extra").textContent = extra.join(" · ");

    fill($("#episodes"), state.view.episodes.map((ep) => {
      const li = el("li", ep.class);
      const title = el("div", "ep-title");
      title.append(el("strong", null, `${ep.title}${ep.field ? ` (${fieldWord(ep.field)})` : ""}`),
        el("span", "ep-when", `zone ${letter(ep.zone)} · ${clockText(ep.start_tick)}${ep.end_tick !== ep.start_tick ? ` to ${clockText(ep.end_tick)}` : ""}${ep.kind === "real" ? " · real event" : ep.kind === "fault" ? " · sensor lie" : ""}`));
      li.append(title, el("div", "ep-head", ep.headline));
      if (ep.why) {
        const why = el("p", "ep-why", ep.why + " ");
        if (ep.doc) { const a = el("a", null, "Why?"); a.href = ep.doc; a.target = "_blank"; a.rel = "noopener"; why.append(a); }
        li.append(why);
      }
      return li;
    }).reverse());
    renderTimelines();
  }

  function packLanes(bands, width, total) {
    const lanes = [];
    for (const band of bands) {
      const x0 = (band.start / total) * width;
      const x1 = Math.max(x0 + 3, (band.end / total) * width);
      const labelEnd = x0 + band.label.length * 5.4 + 6;
      const right = Math.max(x1, labelEnd);
      let lane = lanes.findIndex((end) => end <= x0 - 2);
      if (lane < 0) { lanes.push(0); lane = lanes.length - 1; }
      lanes[lane] = right;
      band.lane = lane; band.x0 = x0; band.x1 = x1;
    }
    return lanes.length;
  }

  function strip(bands, cls, width, total) {
    const lanes = Math.max(packLanes(bands, width, total), 1);
    const H = lanes * 16 + 4;
    const s = svg("svg", { class: "tl", viewBox: `0 0 ${width} ${H}`, width: "100%", height: H, role: "img" });
    bands.forEach((b) => {
      const y = 2 + b.lane * 16;
      const rect = svg("rect", { x: b.x0.toFixed(1), y, width: Math.max(b.x1 - b.x0, 3).toFixed(1), height: 13, rx: 3, class: `${cls} ${b.extra || ""}` });
      rect.append(svg("title"));
      rect.firstChild.textContent = b.tip;
      s.append(rect);
      const text = svg("text", { x: (b.x0 + 4).toFixed(1), y: y + 10 });
      text.setAttribute("class", b.x1 - b.x0 > b.label.length * 5.4 + 8 ? "lane-label" : "");
      text.textContent = b.label;
      s.append(text);
    });
    s.setAttribute("aria-label", bands.length ? bands.map((b) => b.tip).join("; ") : "Nothing yet");
    return s;
  }

  function renderTimelines() {
    const host = $("#timelines");
    const width = Math.max(host.clientWidth || 340, 260);
    const total = Math.max(state.view.clock.tick, 120);
    const last = state.view.clock.tick;
    fill(host, state.view.zones.map((zone) => {
      const tl = state.view.timeline;
      const trickBands = tl.tricks[zone.id].map((b) => ({
        start: b.start_tick, end: b.end_tick + 1, label: b.hidden ? "Hidden trick" : `${b.title}${b.field ? ` (${fieldWord(b.field)})` : ""}`,
        extra: b.hidden ? "hidden-band" : "",
        tip: `${b.hidden ? "Hidden trick" : b.title}, ${clockText(b.start_tick)} to ${clockText(b.end_tick + 1)}`,
      }));
      const cardBands = tl.cards[zone.id].map((b) => ({
        start: b.start_tick, end: b.end_tick === null ? last : b.end_tick, label: b.title, extra: b.sensor ? "sensor-band" : "",
        tip: `${b.title} card, ${clockText(b.start_tick)} to ${b.end_tick === null ? "now" : clockText(b.end_tick)}`,
      }));
      const box = el("figure", "timeline");
      box.style.margin = "0";
      box.append(el("h4", null, `Zone ${zone.letter} timeline`), el("div", "tl-title", "Your tricks"),
        strip(trickBands, "trick-band", width, total), el("div", "tl-title", "Pomona's cards"), strip(cardBands, "card-band", width, total));
      const axis = svg("svg", { class: "tl", viewBox: `0 0 ${width} 16`, width: "100%", height: 16, "aria-hidden": "true" });
      const stepTicks = total > 960 ? 240 : total > 360 ? 120 : 60;
      for (let t = 0; t <= total; t += stepTicks) {
        const x = Math.min((t / total) * width, width - 1);
        axis.append(svg("line", { x1: x, x2: x, y1: 0, y2: 4, class: "axis", stroke: "currentColor" }));
        const text = svg("text", { x: Math.min(x + 2, width - 30), y: 13, class: "axis-text" });
        text.textContent = clockText(t);
        axis.append(text);
      }
      box.append(axis);
      return box;
    }));
  }

  function renderVerdictTable() {
    const rows = state.info.verdicts.filter((v) => v.code !== "accepted_by_core");
    const plan = ["caught", "caught_cant_confirm", "missed", "caught_at_recovery", "wrong_card", "no_card_rule", "too_short_to_raise", "undetectable", "false_alarm"];
    fill($("#verdict-rows"), rows.map((v) => {
      const tr = el("tr", plan.includes(v.code) ? "" : "also");
      const shown = v.headline.replace("{after}", " (after N min)").replace("{card}", "X").replace("{n}", "N");
      const why = el("td", null, v.why + " ");
      const a = el("a", null, "More");
      a.href = v.doc; a.target = "_blank"; a.rel = "noopener";
      why.append(a);
      tr.append(el("td", null, v.scorer), el("td", null, shown), why);
      return tr;
    }));
  }

  function renderFooter() {
    const b = state.info.build;
    const line = $("#build-line");
    if (b.short_commit) {
      const link = el("a", null, b.short_commit);
      link.href = `https://github.com/okyanu/pomona/commit/${b.commit}`;
      link.target = "_blank"; link.rel = "noopener";
      fill(line, "This page runs Pomona's real code (commit ", link, b.dirty ? ", plus local changes" : "",
        ") in your browser with Pyodide, not a copy. Nothing is sent to any server.");
    } else {
      line.textContent = "This page runs Pomona's real code in your browser with Pyodide, not a copy. Nothing is sent to any server.";
    }
  }

  function render() {
    renderClock();
    renderZones();
    renderPicker();
    renderHidden();
    renderScore();
    updateDisabled();
  }

  // ---- actions --------------------------------------------------------------------------------------

  function send(commands, advance) {
    return act({ scenario: state.scenario, commands, advance });
  }
  function newSession() {
    state.scenario = null;
    return act({});
  }

  function wire() {
    document.querySelectorAll("[data-ticks]").forEach((b) => b.addEventListener("click", () => send([], Number(b.dataset.ticks))));
    $("#new-session").addEventListener("click", newSession);
    $("#pick-zone").addEventListener("change", (e) => { state.ui.zone = e.target.value; renderPicker(); updateDisabled(); });
    $("#pick-field").addEventListener("change", (e) => { state.ui.field = e.target.value; renderPicker(); updateDisabled(); });
    $("#start-trick").addEventListener("click", () => {
      const trick = trickByName(state.ui.trick);
      const cmd = { op: "start", name: trick.name, zone: state.ui.zone };
      if (trick.takes_field) cmd.field = state.ui.field;
      send([cmd], 1);
    });
    $("#hidden-btn").addEventListener("click", () => send([{ op: "hidden" }], 1));
    $("#reveal-btn").addEventListener("click", () => send([{ op: "reveal" }], 12));
    $("#cal-zone").addEventListener("change", (e) => { state.ui.calZone = e.target.value; renderPicker(); updateDisabled(); });
    $("#cal-field").addEventListener("change", (e) => { state.ui.calField = e.target.value; });
    $("#cal-btn").addEventListener("click", () => send([{ op: "calibrate", zone: state.ui.calZone, field: state.ui.calField }], 1));
    $("#copy-link").addEventListener("click", copyLink);
    $("#download").addEventListener("click", downloadScenario);
    let resizeTimer = null;
    window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => state.view && renderTimelines(), 150); });
  }

  async function boot() {
    wire();
    try {
      state.info = await request("info");
    } catch (error) {
      loadFailed(error.message);
      return;
    }
    $("#loading").hidden = true;
    $("#play").hidden = false;
    renderVerdictTable();
    renderFooter();
    let scenario = null;
    const hash = location.hash.match(/^#r=([A-Za-z0-9_-]+)$/);
    if (hash) {
      try { scenario = decodeScenario(hash[1]); } catch (e) { showStatus("That replay link could not be read, so a new session started.", true); }
      history.replaceState(null, "", location.pathname + location.search);
    }
    if (!scenario) scenario = safe(() => JSON.parse(localStorage.getItem(STORE_KEY)));
    state.loaded = true;
    state.ui.zone = state.info.zones[0].id;
    state.scenario = scenario;
    await act(scenario ? { scenario } : {});
    if (scenario && !state.view) {  // a saved scenario the engine refused: begin again
      safe(() => localStorage.removeItem(STORE_KEY));
      state.scenario = null;
      await act({});
    }
    if (hash && state.view) showStatus("Replaying a shared run: this is exactly what its author saw. Keep playing from here, or start a new session.");
  }

  boot();
})();
