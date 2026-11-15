// Runs the actual served JavaScript against API fixtures. No network or writes.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(0, 'utf8');
const attack = `<img src=x onerror="alert('x')"> & <svg onload=alert(1)>`;
const escaped = '&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt; &amp; &lt;svg onload=alert(1)&gt;';
const event = Object.fromEntries([
  'timestamp', 'farm_id', 'zone_id', 'crop', 'air_temperature_c', 'humidity_pct',
].map(key => [key, attack]));
const decision = {risk_level: attack, blocked_actions: [attack], trust_verdict: attack, vetoed_fields: [attack]};
const specialist = {source: attack, data_quality_labels: [attack]};
const dubai = {available: true, farm_timezone: 'Asia/Dubai', utc_offset_now: '+04:00', next_offset_change: null,
  offset_after_change: null, tzdata_version: null};
const goodEvent = {...event, timestamp: '2026-11-07T08:00:00+00:00'};
const replies = {
  '/api/farm-time': dubai,
  '/api/devices': {available: true, result: {devices: [{device_id: attack, last_seen: attack, quality: attack}]}},
  '/api/history': {available: true, result: {events: [event, goodEvent]}},
  '/api/overview': {core_available: true, latest_event: event, recent_events: [event, goodEvent]},
  '/api/pipeline': {available: true, result: {pipeline_id: attack, final_decision: decision,
    sensor_quality: specialist, agronomy_calc: {irrigation: {reference_et_mm_day: attack},
      fertilizer: {urea_g: attack}}}},
  '/api/audit': {available: true, result: {events: [{evaluated_at: attack, scenario_id: attack, ...decision}]}},
  '/api/risk': {available: true, result: {sensor_quality: specialist,
    trust_gate: {trust_verdict: attack, vetoed_fields: [attack]}}},
  '/api/safety': {available: true, result: {safe_alternative: attack, safety_labels: [attack]}},
  '/api/automation': {available: true, result: {suggestions: [{id: attack, rule_id: attack,
    action: attack, message: attack, status: 'pending', outcome_status: attack},
    {id: 'ok', rule_id: 'r', action: 'a', message: 'm', status: 'approved', outcome_status: 'confirmed'},
    {id: 'old', rule_id: 'r', action: 'a', message: 'm', status: 'approved', outcome_status: null}]}},
  '/api/advice-cards': {available: true, result: {cards: [{card_id: attack, title: attack,
    summary: attack, severity: 'warn', status: 'pending', opportunity: attack,
    evidence: {sample_time: attack, provenance_status: attack, readings: {[attack]: attack},
      trust_verdict: attack, vetoed_fields: [attack],
      sensor_snapshot: {ph: attack}}, safe_next_checks: [attack], blocked_actions: [attack],
    human_review_required: true, outcome: {status: attack, deadline: attack, clean_streak: attack,
      required_clean_readings: attack}}]}},
  '/api/probe-health': {available: true, result: {probes: [{sensor_id: attack, status: attack, reasons: [attack],
    latest: {sensitivity_mv_per_ph: 120}, sensitivity_vs_first_pct: attack, v_at_ph7_shift_v: 0.2, calibrations: attack,
    days_since_last_calibration: attack}, {sensor_id: attack, status: 'worn', reasons: [attack], calibrations: 1,
    days_since_last_calibration: null}]}},
  '/api/alerts': {available: true, result: {alerts: [{state: 'active', rule_id: attack, message: attack,
    since: attack, raised_at: attack, recovering_since: attack}, {state: attack, rule_id: attack, since: attack}],
    events: [{rule_id: attack, event: attack, sample_time: attack}]}},
  '/api/services': {services: {[attack]: {available: false, error: attack}}},
  '/api/runtimes': {available: true, result: {[attack]: {available: true, model: attack, models_seen: [attack]}}},
  '/api/digital-twin': {available: true, result: {mode: attack, safety_note: attack,
    trajectory: [{minutes_from_now: attack, air_temperature_c: attack}],
    guarded_evaluation: {final_decision: decision}}},
  '/api/explanation': {available: true, result: {explanation: attack}},
};
const elements = new Map();
const listeners = {};
const element = id => {
  if (!elements.has(id)) elements.set(id, {innerHTML: '', textContent: '', value: '', disabled: false, addEventListener() {}});
  return elements.get(id);
};
const requests = [];
let postResponse = () => ({ok: true, json: async () => ({available: true, result: {status: 'approved'}})});
const context = vm.createContext({
  URLSearchParams, location: {search: '?farm_id=farm-a&zone_id=zone-a'},
  document: {getElementById: element, querySelectorAll: () => [element('automation-evaluate')], body: {addEventListener: (type, fn) => {listeners[type] = fn;}}},
  fetch: async (url, options) => {
    requests.push({url, options});
    const parsed = new URL(url, 'http://localhost');
    assert.equal(parsed.searchParams.get('farm_id'), 'farm-a');
    assert.equal(parsed.searchParams.get('zone_id'), 'zone-a');
    url = parsed.pathname;
    if (options?.method === 'POST') return postResponse();
    assert.ok(url in replies, `Unexpected request: ${url}`);
    return {ok: true, json: async () => replies[url]};
  },
  setInterval() {},
});
(async () => {
  // Remove only the automatic startup call; drive and await refresh ourselves.
  const startup = "refresh().catch(() => $('status').textContent = 'Dashboard API unavailable');";
  assert.ok(source.includes(startup));
  vm.runInContext(source.replace(startup, ''), context);
  await vm.runInContext('refresh()', context);
  for (const id of ['events', 'pipeline', 'specialists', 'audit', 'risk', 'safety',
    'automation', 'advice-cards', 'services', 'runtimes', 'digital-twin', 'explanation', 'agronomy']) {
    const html = element(id).innerHTML;
    assert.ok(html.includes(escaped), `${id} should display escaped API data`);
    assert.ok(!html.includes('<img'), `${id} must not create an image element`);
    assert.ok(!html.includes('<svg onload'), `${id} must not create an injected SVG`);
    assert.ok(!html.includes('&amp;lt;'), `${id} must not double escape`);
  }
  assert.ok(element('events').innerHTML.includes('<th scope="col">Farm</th>'));
  assert.ok(element('automation').innerHTML.includes(`data-id="${escaped}"`));
  const automationHtml = element('automation').innerHTML;
  assert.ok(automationHtml.includes('<th scope="col">Outcome</th>'));
  assert.ok(automationHtml.includes(`<span class="badge neutral">${escaped}</span>`), 'unknown outcome is escaped, neutral');
  assert.ok(automationHtml.includes('<span class="badge success">confirmed</span>'));
  assert.ok(automationHtml.includes('<td>--</td><td>--</td>'), 'untracked outcome shows --');
  assert.ok(element('advice-cards').innerHTML.includes(`Outcome: <span class="badge neutral">${escaped}</span> · clean readings ${escaped}/${escaped} · until ${escaped}`));
  const trustAttack = `<span class="badge neutral">${escaped}</span> Can&#39;t confirm: ${escaped} not used`;
  for (const id of ['pipeline', 'risk', 'advice-cards']) {
    assert.ok(element(id).innerHTML.includes(`Sensor trust: ${trustAttack}`), `${id} shows the escaped sensor trust line`);
  }
  assert.equal(element('air').textContent, `${attack} °C`);
  // A suggestion ID stays one URL segment when a user clicks Approve.
  const id = 'odd/id?query#fragment';
  await listeners.click({target: {dataset: {id}, classList: {contains: name => name === 'automation-approve'}}});
  assert.ok(requests.some(r => r.url.startsWith(`/api/automation/suggestions/${encodeURIComponent(id)}/approve?`)));
  assert.ok(element('automation-feedback').textContent.includes('Decision recorded: approved'));
  const evaluateClick = {target: {id: 'automation-evaluate', classList: {contains: () => false}}};
  postResponse = () => ({ok: false, status: 503});
  await listeners.click(evaluateClick);
  assert.ok(element('automation-feedback').textContent.includes('HTTP 503'));
  assert.equal(element('automation-evaluate').disabled, false);
  postResponse = () => ({ok: true, json: async () => ({available: false, error: attack})});
  await listeners.click(evaluateClick);
  assert.ok(element('automation-feedback').textContent.includes(attack));
  postResponse = () => {throw new Error('Network offline');};
  await listeners.click(evaluateClick);
  assert.ok(element('automation-feedback').textContent.includes('Network offline'));
  assert.equal(element('automation-evaluate').disabled, false);
  let release;
  postResponse = () => new Promise(resolve => {release = resolve;});
  const pending = listeners.click(evaluateClick);
  assert.equal(element('automation-evaluate').disabled, true);
  const count = requests.length;
  await listeners.click(evaluateClick);
  assert.equal(requests.length, count, 'Ignore duplicate clicks during an in-flight request');
  release({ok: true, json: async () => ({available: true, result: {suggestions: []}})});
  await pending;
  assert.equal(element('automation-evaluate').disabled, false);
  assert.equal(element('automation-feedback').textContent, '0 suggestion(s) returned (existing retries reused).');
  replies['/api/explanation'].result.explanation = 'Tomato pH < 6 & EC > 2';
  await vm.runInContext('refresh()', context);
  assert.ok(element('explanation').innerHTML.includes('Tomato pH &lt; 6 &amp; EC &gt; 2'));
  const trust = (verdict, fields) => vm.runInContext(`trustLine(${JSON.stringify(verdict)}, ${JSON.stringify(fields)})`, context);
  assert.equal(trust('cannot_confirm', ['ph', 'previous_ph', 'ec_ms_cm']),
    `<span class="badge danger">cannot confirm</span> Can&#39;t confirm: pH, EC not used`);
  assert.ok(trust('partial', ['humidity_pct']).startsWith('<span class="badge warning">partial</span>'));
  assert.equal(trust('trusted', []), '<span class="badge success">trusted</span> All readings passed the sensor check');
  assert.equal(trust(undefined, []), 'not reported');
  assert.ok(trust('partial', ['constructor']).includes('Can&#39;t confirm: constructor not used'), 'inherited keys are not field names');
  assert.equal(vm.runInContext("escapeHtml(null)", context), '');
  assert.equal(vm.runInContext("escapeHtml(0)", context), '0');
  assert.ok(vm.runInContext("badge('routine', 'success')", context).includes('class="badge success"'));
  replies['/api/overview'].core_available = false;
  await vm.runInContext('refresh()', context);
  assert.ok(element('status').textContent.includes('STALE'));
  // Probe health comes from stored calibrations, not the latest full packet: a zone with only modular
  // observations (the cress logger) has no latest packet and must still show it.
  assert.ok(element('probe-health').innerHTML.includes(escaped), 'probe health must survive a missing latest packet');
  assert.ok(!element('probe-health').textContent.includes('Unavailable'), 'probe health must not be blanked as stale');
  assert.equal(element('automation-evaluate').disabled, true);
  const beforeUnavailableClick = requests.length;
  await listeners.click(evaluateClick);
  assert.equal(requests.length, beforeUnavailableClick);
  replies['/api/overview'].core_available = true;
  await vm.runInContext('refresh()', context);
  assert.equal(element('automation-evaluate').disabled, false);
  assert.ok(element('devices').innerHTML.includes(escaped));
  assert.ok(element('history').innerHTML.includes(escaped));
  assert.ok(element('history-download').href.includes('farm_id=farm-a'));
  // Farm time: Core stores UTC; the page shows the farm zone with its offset and keeps the stored string in a title.
  const farmCell = '<span title="2026-11-07T08:00:00+00:00">2026-11-07 12:00 +04</span>';
  assert.equal(element('farm-time').textContent,
    'Farm time: Asia/Dubai (UTC+04:00, no clock change in the next year) · times below are farm time (hover for the stored UTC time)');
  assert.ok(element('history').innerHTML.includes(`<td>${farmCell}</td>`), 'history shows farm time');
  assert.ok(element('events').innerHTML.includes(`<td>${farmCell}</td>`), 'recent events show farm time');
  assert.ok(element('history').innerHTML.includes(`<td>${escaped}</td>`), 'an unparseable time is still shown escaped');
  const cell = raw => vm.runInContext(`timeCell(${JSON.stringify(raw)})`, context);
  assert.equal(cell('2026-11-07T08:00:00Z'), '<span title="2026-11-07T08:00:00Z">2026-11-07 12:00 +04</span>');
  assert.equal(cell('2026-11-07 23:30:15.123456+00:00'), '<span title="2026-11-07 23:30:15.123456+00:00">2026-11-08 03:30 +04</span>');
  assert.equal(cell('2026-11-07T12:00:00+04:00'), '<span title="2026-11-07T12:00:00+04:00">2026-11-07 12:00 +04</span>');
  assert.equal(cell('2026-11-07T12:00:00'), '2026-11-07T12:00:00', 'no UTC offset: shown as sent, never guessed');
  assert.equal(cell('--'), '--');
  assert.equal(cell(undefined), '');
  assert.equal(cell('2026-13-45T25:00:00Z'), '2026-13-45T25:00:00Z');
  assert.equal(cell(attack), escaped);
  assert.ok(cell(`2026-11-07T08:00:00Z"><img src=x>`).startsWith('2026-11-07T08:00:00Z&quot;&gt;'), 'not a time: escaped, no markup');
  // A zone with a clock change names the date; a half-hour zone shows minutes; UTC is labelled UTC.
  replies['/api/farm-time'] = {available: true, farm_timezone: 'Europe/Berlin', utc_offset_now: '+01:00',
    next_offset_change: '2027-03-28T01:00:00+00:00', offset_after_change: '+02:00', tzdata_version: '2026.1'};
  await vm.runInContext('refresh()', context);
  assert.equal(element('farm-time').textContent,
    'Farm time: Europe/Berlin (UTC+01:00, clock changes to UTC+02:00 on 2027-03-28) · times below are farm time (hover for the stored UTC time)');
  assert.equal(cell('2026-11-07T08:00:00Z'), '<span title="2026-11-07T08:00:00Z">2026-11-07 09:00 +01</span>');
  assert.equal(cell('2027-06-01T08:00:00Z'), '<span title="2027-06-01T08:00:00Z">2027-06-01 10:00 +02</span>');
  replies['/api/farm-time'] = {...dubai, farm_timezone: 'Asia/Kolkata', utc_offset_now: '+05:30'};
  await vm.runInContext('refresh()', context);
  assert.equal(cell('2026-11-07T08:00:00Z'), '<span title="2026-11-07T08:00:00Z">2026-11-07 13:30 +05:30</span>');
  replies['/api/farm-time'] = {...dubai, farm_timezone: 'UTC', utc_offset_now: '+00:00'};
  await vm.runInContext('refresh()', context);
  assert.equal(cell('2026-11-07T08:00:00+04:00'), '<span title="2026-11-07T08:00:00+04:00">2026-11-07 04:00 UTC</span>');
  // Core unreachable, an unknown zone name or an older Core: UTC as before, times shown exactly as stored.
  for (const reply of [{available: false, farm_timezone: 'UTC'}, {...dubai, farm_timezone: 'Asia/Dubay'}]) {
    replies['/api/farm-time'] = reply;
    await vm.runInContext('refresh()', context);
    assert.ok(element('farm-time').textContent.startsWith('Farm time: UTC (Core did not report'));
    assert.equal(cell('2026-11-07T08:00:00Z'), '2026-11-07T08:00:00Z');
    assert.ok(element('history').innerHTML.includes('<td>2026-11-07T08:00:00+00:00</td>'));
  }
  // Old and missing data: the trust line says what is true instead of the last stored reading's green line.
  replies['/api/farm-time'] = dubai;
  const stamped = {...event, timestamp: '2026-11-07T08:00:00+00:00'};
  const overview = (age, after) => { replies['/api/overview'] = {core_available: true, latest_event: stamped,
    recent_events: [stamped], latest_age_s: age, stale_after_s: after}; };
  const goodDecision = {risk_level: 'low', blocked_actions: [], trust_verdict: 'trusted', vetoed_fields: []};
  replies['/api/pipeline'] = {available: true, result: {pipeline_id: 'p', final_decision: goodDecision, sensor_quality: {}}};
  replies['/api/risk'] = {available: true, result: {sensor_quality: {}, trust_gate: {trust_verdict: 'trusted', vetoed_fields: []}}};
  const green = '<span class="badge success">trusted</span> All readings passed the sensor check';
  const staleLine = (text) => `<span class="badge danger">cannot confirm</span> Can&#39;t confirm: ${text}`;
  overview(599, 600);  // at or under the threshold: the stored reading's own verdict
  await vm.runInContext('refresh()', context);
  for (const id of ['pipeline', 'risk']) assert.ok(element(id).innerHTML.includes(`Sensor trust: ${green}`), `${id}: fresh data keeps the green line`);
  assert.ok(!element('pipeline').innerHTML.includes('from the last reading at'));
  overview(720, 600);  // 12 minutes old: Dubai farm time, offset shown
  await vm.runInContext('refresh()', context);
  for (const id of ['pipeline', 'risk']) {
    assert.ok(element(id).innerHTML.includes(`Sensor trust: ${staleLine('no reading from this zone for 12 min (last 12:00 +04)')}`), `${id}: old data is not green`);
    assert.ok(!element(id).innerHTML.includes('All readings passed'), `${id}: no green line on old data`);
  }
  assert.ok(element('pipeline').innerHTML.includes('Pipeline result from the last reading at 2026-11-07 12:00 +04.'));
  overview(601, 600);
  await vm.runInContext('refresh()', context);
  assert.ok(element('pipeline').innerHTML.includes('no reading from this zone for 10 min'));
  overview(99999, 0);  // 0 turns it off (demos, fixed-timestamp replays)
  await vm.runInContext('refresh()', context);
  for (const id of ['pipeline', 'risk']) assert.ok(element(id).innerHTML.includes(`Sensor trust: ${green}`), `${id}: threshold 0 is off`);
  delete replies['/api/overview'].latest_age_s;  // an older dashboard server without the field
  replies['/api/overview'].stale_after_s = 600;
  await vm.runInContext('refresh()', context);
  assert.ok(element('pipeline').innerHTML.includes(`Sensor trust: ${green}`), 'no age: nothing to judge');
  overview(45 * 3600, 600);  // the date is named when the reading is not recent
  await vm.runInContext('refresh()', context);
  assert.ok(element('pipeline').innerHTML.includes('no reading from this zone for 45.0 h (last 2026-11-07 12:00 +04)'));
  replies['/api/farm-time'] = {available: false, farm_timezone: 'UTC'};  // no farm zone from Core: UTC, labelled
  overview(720, 600);
  await vm.runInContext('refresh()', context);
  assert.ok(element('pipeline').innerHTML.includes('(last 08:00 UTC)'));
  assert.ok(element('pipeline').innerHTML.includes('from the last reading at 2026-11-07 08:00 UTC.'));
  stamped.timestamp = attack;  // a time that cannot be read is never guessed
  await vm.runInContext('refresh()', context);
  assert.ok(element('pipeline').innerHTML.includes('(last an unknown time)'));
  stamped.timestamp = '2026-11-07T08:00:00+00:00';
  replies['/api/farm-time'] = dubai;
  const age = (seconds) => vm.runInContext(`ageText(${seconds})`, context);
  assert.deepEqual([age(0), age(45), age(119), age(120), age(720), age(7199), age(9000), age(172799), age(300000)],
    ['0 s', '45 s', '119 s', '2 min', '12 min', '120 min', '2.5 h', '48.0 h', '3 days']);
  // A probe that did not report reads "not reported"; a reading that was there but not used reads "not used".
  overview(10, 600);
  const quality = (missing) => ({data_quality_labels: ['x'], missing_fields: missing});
  replies['/api/pipeline'] = {available: true, result: {pipeline_id: 'p', sensor_quality: quality(['ec_ms_cm']),
    final_decision: {...goodDecision, trust_verdict: 'partial', vetoed_fields: ['ec_ms_cm']}}};
  replies['/api/risk'] = {available: true, result: {sensor_quality: quality(['ec_ms_cm']),
    trust_gate: {trust_verdict: 'partial', vetoed_fields: ['ec_ms_cm']}}};
  replies['/api/advice-cards'] = {available: true, result: {cards: [
    {card_id: 'm', title: 't', summary: 's', severity: 'warn', status: 'pending', evidence: {readings: {ec_ms_cm: null, ph: 6.1},
      units: {ph: 'pH'}, trust_verdict: 'partial', vetoed_fields: ['ec_ms_cm'], missing_fields: ['ec_ms_cm']}},
    {card_id: 'v', title: 't', summary: 's', severity: 'warn', status: 'pending', evidence: {readings: {},
      trust_verdict: 'partial', vetoed_fields: ['ec_ms_cm']}}]}};
  await vm.runInContext('refresh()', context);
  const notReported = '<span class="badge warning">partial</span> Can&#39;t confirm: EC not reported in the latest reading</p>';
  for (const id of ['pipeline', 'risk']) {
    assert.ok(element(id).innerHTML.includes(notReported), `${id}: a missing EC is "not reported"`);
    assert.ok(!element(id).innerHTML.includes('EC not used'), `${id}: and not also "not used"`);
  }
  const cards = element('advice-cards').innerHTML;
  assert.ok(cards.includes(notReported), 'the advice card says "not reported" for a missing probe');
  assert.ok(cards.includes('<span class="badge warning">partial</span> Can&#39;t confirm: EC not used</p>'), 'and "not used" for a vetoed reading');
  assert.ok(cards.includes('Readings: ec_ms_cm: –; ph: 6.1 pH</p>'), 'a null reading in a card is an en dash');
  assert.ok(cards.includes('Readings: not recorded</p>'));
  const trustWith = (verdict, vetoed, missing) => vm.runInContext(
    `trustLine(${JSON.stringify(verdict)}, ${JSON.stringify(vetoed)}, ${JSON.stringify(missing)})`, context);
  assert.equal(trustWith('partial', ['ph'], ['ec_ms_cm']),
    '<span class="badge warning">partial</span> Can&#39;t confirm: EC not reported in the latest reading; pH not used');
  assert.equal(trustWith('cannot_confirm', ['soil_moisture_pct'], ['substrate_moisture_pct']),
    '<span class="badge danger">cannot confirm</span> Can&#39;t confirm: moisture not reported in the latest reading');
  assert.equal(trustWith('partial', [], ['air_temperature_c', 'humidity_pct']),
    '<span class="badge warning">partial</span> Can&#39;t confirm: air temperature, humidity not reported in the latest reading');
  assert.equal(trustWith('partial', undefined, undefined), '<span class="badge warning">partial</span> Can&#39;t confirm: some readings not used');
  assert.equal(trustWith('trusted', [], []), '<span class="badge success">trusted</span> All readings passed the sensor check');
  // None renders as an en dash in the history rows (and the other panels already printed --).
  const gap = {...stamped, air_temperature_c: null, ph: 6.2, ec_ms_cm: null};
  replies['/api/history'] = {available: true, result: {events: [gap, {...stamped, air_temperature_c: 21.5, ph: null, ec_ms_cm: 2.1}]}};
  overview(10, 600);
  replies['/api/overview'].latest_event = gap;
  replies['/api/overview'].recent_events = [gap, stamped];
  await vm.runInContext('refresh()', context);
  const rows = element('history').innerHTML;
  assert.ok(rows.includes('Temperature – °C · pH 6.2 · EC –'));
  assert.ok(rows.includes('Temperature 21.5 °C · pH – · EC 2.1'));
  assert.equal(element('ec').textContent, '--', 'the panel value keeps its -- for a missing reading');
  // ---- Multi-device zones, slice 2 (docs/design/multi-device-zones-slice2.md 2.8) ------------------------------------
  const run = (code) => vm.runInContext(code, context);
  const zoneTrust = (verdict, vetoed, missing, zone) => run(
    `trustLine(${JSON.stringify(verdict)}, ${JSON.stringify(vetoed)}, ${JSON.stringify(missing)}, ${JSON.stringify(zone)})`);
  const device = (id, age, extra = {}) => ({device_id: id, age_s: age, stale: false, stale_limit_s: 600, supplied: [], ...extra});
  const zone = {
    sources: {air_temperature_c: ['climate-1'], humidity_pct: ['climate-1'], ph: ['substrate-1'], ec_ms_cm: ['substrate-1'],
      substrate_moisture_pct: ['substrate-1', 'substrate-2']},
    devices: [device('climate-1', 40, {supplied: ['air_temperature_c', 'humidity_pct']}),
      device('substrate-1', 100, {supplied: ['ph', 'ec_ms_cm']})],
    dashboard_judged: [],
  };
  const partial = '<span class="badge warning">partial</span> Can&#39;t confirm: ';
  assert.equal(zoneTrust('trusted', [], [], zone),
    '<span class="badge success">trusted</span> All readings passed the sensor check (2 devices)');
  assert.equal(zoneTrust('trusted', [], [], {...zone, devices: [zone.devices[0]]}),
    '<span class="badge success">trusted</span> All readings passed the sensor check (1 device)');
  assert.equal(zoneTrust('trusted', [], [], {...zone, dashboard_judged: ['substrate-1']}),
    '<span class="badge success">trusted</span> All readings passed the sensor check (2 devices, substrate-1 (checked by the dashboard))');
  assert.equal(zoneTrust('partial', ['humidity_pct'], [], zone), `${partial}humidity (climate-1) not used`);
  assert.equal(zoneTrust('partial', ['ph', 'previous_ph'], [], zone), `${partial}pH (substrate-1) not used`, 'a companion field is one pH part');
  assert.equal(zoneTrust('partial', ['humidity_pct'], [], {...zone, dashboard_judged: ['climate-1']}),
    `${partial}humidity (climate-1) (checked by the dashboard) not used`);
  assert.equal(zoneTrust('partial', [], ['ec_ms_cm'], {...zone, sources: {...zone.sources, ec_ms_cm: []}}),
    `${partial}EC not reported by any device in this zone`);
  assert.equal(zoneTrust('partial', ['humidity_pct'], ['ec_ms_cm'], zone),
    `${partial}humidity (climate-1) not used; EC not reported by any device in this zone`,
    'a vetoed field first, then a probe no live device reported');
  const quiet = {...zone, devices: [device('climate-1', 900, {stale: true}), zone.devices[1]]};
  assert.equal(zoneTrust('partial', [], ['air_temperature_c', 'humidity_pct'], quiet),
    `${partial}air temperature, humidity not reported: no reading from climate-1 for 15 min`);
  assert.equal(zoneTrust('partial', ['humidity_pct'], ['air_temperature_c', 'humidity_pct'], quiet),
    `${partial}air temperature, humidity not reported: no reading from climate-1 for 15 min`, 'missing and vetoed is said once, as missing');
  assert.equal(zoneTrust('partial', ['ph'], ['air_temperature_c', 'ec_ms_cm'], {...quiet, sources: {...zone.sources, ec_ms_cm: []}}),
    `${partial}pH (substrate-1) not used; air temperature not reported: no reading from climate-1 for 15 min; EC not reported by any device in this zone`);
  assert.equal(zoneTrust('partial', [], ['substrate_moisture_pct'], {...zone, devices: [device('substrate-1', 3000, {stale: true}), device('substrate-2', 3100, {stale: true})]}),
    `${partial}moisture not reported: no reading from substrate-1 for 50 min, substrate-2 for 52 min`);
  assert.equal(zoneTrust('partial', ['constructor'], [], zone), `${partial}constructor not used`, 'inherited keys are not field names');
  assert.equal(zoneTrust('cannot_confirm', undefined, undefined, zone),
    '<span class="badge danger">cannot confirm</span> Can&#39;t confirm: some readings not used');
  assert.equal(zoneTrust(undefined, [], [], zone), 'not reported');
  // The advice card variant: its own `sources` only, so no counts, ages or dashboard marks.
  assert.equal(zoneTrust('trusted', [], [], {sources: zone.sources}),
    '<span class="badge success">trusted</span> All readings passed the sensor check');
  assert.equal(zoneTrust('partial', ['humidity_pct'], ['ec_ms_cm'], {sources: {...zone.sources, ec_ms_cm: []}}),
    `${partial}humidity (climate-1) not used; EC not reported by any device in this zone`);
  assert.equal(zoneTrust('partial', ['ph'], [], {sources: {ph: [attack]}}), `${partial}pH (${escaped}) not used`);
  // Without a zone the text is exactly today's.
  assert.equal(zoneTrust('partial', ['humidity_pct'], ['ec_ms_cm'], undefined),
    `${partial}EC not reported in the latest reading; humidity not used`);

  // sparkline: one series with no times is today's drawing, by index.
  const spark = (series, color) => run(`sparkline(${JSON.stringify(series)}, ${JSON.stringify(color)})`);
  assert.equal(spark([{label: '', points: [{v: 1}, {v: 3}]}], '#fff'),
    '<svg viewBox="0 0 280 56" preserveAspectRatio="none"><polyline points="4.0,52.0 276.0,4.0" fill="none" stroke="#fff" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg><p class="status">min 1.0 · max 3.0 · latest 3.0</p>');
  assert.equal(spark([{label: '', points: [{v: 1}, {v: null}, {v: 'x'}]}], '#fff'), '<p class="status">Not enough data yet</p>');
  assert.equal(spark([], '#fff'), '<p class="status">Not enough data yet</p>');
  // Two devices against sample time: the newest point is the right edge, the window is 60 minutes, one y scale.
  const base = Date.parse('2026-11-07T08:00:00Z');
  const pt = (minute, v) => ({t: base + minute * 60000, v});
  const two = spark([{label: 'climate-1', dash: 0, points: [pt(0, 20), pt(30, 22)]},
    {label: 'climate-2', dash: 1, points: [pt(30, 30), pt(60, 40)]},
    {label: 'climate-3', dash: 2, points: [pt(50, 25)]}], '#f0883e');
  assert.ok(two.includes('<polyline points="4.0,52.0 140.0,47.2" fill="none" stroke="#f0883e" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'),
    'climate-1: x by time (0 and 30 min of 60), y on the card scale 20..40');
  assert.ok(two.includes('<polyline points="140.0,28.0 276.0,4.0" fill="none" stroke="#f0883e" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" stroke-dasharray="6 3"/>'),
    'climate-2 shares the scale and uses dash pattern 1');
  assert.equal((two.match(/<polyline/g) || []).length, 2, 'a device with one point is not drawn');
  for (const text of ['</svg>climate-1</span>', '</svg>climate-2</span>', '</svg>climate-3: not enough data</span>']) assert.ok(two.includes(text), text);
  assert.ok(two.includes('stroke-dasharray="2 3"/></svg>climate-3'), 'legend sample shows the device pattern');
  assert.ok(two.includes('climate-2: min 30.0 · max 40.0 · latest 40.0') && two.includes('climate-1: min 20.0 · max 22.0 · latest 22.0'));
  assert.ok(!two.includes('climate-3: min'));
  const old = spark([{label: 'a', points: [pt(-120, 1), pt(-90, 2)]}, {label: 'b', points: [pt(0, 5), pt(10, 6)]}], '#fff');
  assert.ok(!old.includes('a: min'), 'points more than 60 minutes before the newest are outside the window');
  assert.ok(old.includes('a: not enough data'));
  assert.ok(spark([{label: 'a', points: [pt(0, 1)]}], '#fff').startsWith('<p class="status">Not enough data yet</p><p class="status">'));
  assert.equal(spark([{label: 'a', dash: 5, points: [pt(0, 1), pt(1, 2)]}], '#fff').includes('stroke-dasharray="6 3"'), true, 'dash patterns cycle');

  // The page with a two-device zone view.
  const minute = (m) => new Date(base + m * 60000).toISOString();
  const climateEvents = [0, 10, 20, 30, 40, 50].map(m => ({device_id: 'climate-1', timestamp: minute(m), air_temperature_c: 24 + m / 10, humidity_pct: 60 - m / 10}));
  const substrateEvents = [0, 25, 50].map(m => ({device_id: 'substrate-1', timestamp: minute(m), ph: 6 + m / 100, ec_ms_cm: 2 + m / 50}));
  const pair = [10, 20, 30, 40, 50].map(m => ({device_id: 'climate-2', timestamp: minute(m), air_temperature_c: 23 + m / 10}));
  const snapshot = {
    multi_device: true, farm_id: 'farm-a', zone_id: 'zone-a', stale_after_s: 600, newest_age_s: 40,
    devices: [{...zone.devices[0], supplied: ['air_temperature_c', 'humidity_pct']}, device('climate-2', 70, {supplied: []}),
      {...zone.devices[1], age_s: 1200, stale_limit_s: 2700, supplied: ['ph', 'ec_ms_cm']}],
    fields: {
      air_temperature_c: {value: 24.5, device_id: 'climate-1', sample_time: minute(50), age_s: 40,
        others: [{device_id: 'climate-2', value: 23.6, sample_time: minute(50), vetoed: false}]},
      humidity_pct: {value: 55, device_id: 'climate-1', sample_time: minute(50), age_s: 40,
        others: [{device_id: 'climate-2', value: 58, sample_time: minute(50), vetoed: true}]},
      ph: {value: 6.5, device_id: 'substrate-1', sample_time: minute(50), age_s: 1200, others: []},
      ec_ms_cm: {value: 3, device_id: 'substrate-1', sample_time: minute(50), age_s: 1200, others: []}},
    sensor: {farm_id: 'farm-a', zone_id: 'zone-a', timestamp: minute(50), air_temperature_c: 24.5},
    sources: zone.sources, zone_device_fields: ['air_temperature_c', 'ec_ms_cm', 'humidity_pct', 'ph'],
    context: {growth_stage: 'fruiting', weather: {a: 1}}, context_source: {growth_stage: 'substrate-1', weather: 'climate-1'},
    context_conflicts: ['growth_stage', 'weather'],
  };
  const latest = {...climateEvents[5], farm_id: 'farm-a', zone_id: 'zone-a', crop: 'tomato'};
  const events = [latest, {...substrateEvents[2], farm_id: 'farm-a', zone_id: 'zone-a', crop: 'tomato'}];
  const multiOverview = (extra = {}, snap = snapshot) => { replies['/api/overview'] = {core_available: true, latest_event: latest,
    recent_events: events, latest_age_s: 40, stale_after_s: 600, zone_multi_device: true, zone_snapshot: snap,
    device_events: {'climate-1': climateEvents, 'climate-2': pair, 'substrate-1': substrateEvents}, zone_snapshot_error: null, ...extra}; };
  replies['/api/pipeline'] = {available: true, sources: zone.sources, dashboard_judged: ['substrate-1'],
    result: {pipeline_id: 'p', sensor_quality: {data_quality_labels: [], missing_fields: []},
      final_decision: {...goodDecision, trust_verdict: 'trusted'}}};
  replies['/api/risk'] = {available: true, result: {sensor_quality: {}, trust_gate: {trust_verdict: 'partial', vetoed_fields: ['humidity_pct']}}};
  replies['/api/alerts'] = {available: true, result: {alerts: [
    {state: 'active', rule_id: 'sensor_check', device_id: 'climate-1', message: 'Sensor check', detail: 'inspect humidity_pct: stuck', since: minute(0), raised_at: minute(5)},
    {state: 'pending', rule_id: 'high_ec_alert', device_id: 'substrate-1', message: 'EC high', detail: attack, since: minute(0)},
    {state: 'recovering', rule_id: 'x', device_id: null, message: 'm', since: minute(0)}],
    events: [{rule_id: 'sensor_check', device_id: 'climate-1', event: 'raised', sample_time: minute(5)},
      {rule_id: 'x', device_id: null, event: 'recovered', sample_time: minute(6)}]}};
  replies['/api/advice-cards'] = {available: true, result: {cards: [{card_id: 'c', title: 't', summary: 's', severity: 'warn', status: 'pending',
    evidence: {readings: {}, trust_verdict: 'partial', vetoed_fields: ['humidity_pct'], missing_fields: ['ec_ms_cm'],
      sources: {humidity_pct: ['climate-1'], ec_ms_cm: []}}}]}};
  multiOverview();
  await run('refresh()');
  const html = (id) => element(id).innerHTML;
  // tiles: the zone's value with its source line, a pair line, a (not used) pair line, the VPD cross-device line
  assert.equal(html('air'), '24.5 °C<div class="tile-src">climate-1 · 40 s</div><div class="tile-src">also climate-2: 23.6 °C</div>');
  assert.equal(html('humidity'), '55 %<div class="tile-src">climate-1 · 40 s</div><div class="tile-src">also climate-2: 58 % (not used)</div>');
  assert.equal(html('ph'), '6.5<div class="tile-src">substrate-1 · 20 min</div>');
  assert.equal(html('ec'), '3 mS/cm<div class="tile-src">substrate-1 · 20 min</div>');
  assert.equal(html('vpd'), '1.38 kPa<div class="tile-src">climate-1 · 40 s</div>');
  const crossFields = {...snapshot.fields, humidity_pct: {...snapshot.fields.humidity_pct, device_id: 'climate-2', others: []}};
  multiOverview({}, {...snapshot, fields: crossFields});
  await run('refresh()');
  assert.ok(html('vpd').includes('<div class="tile-src">air climate-1, humidity climate-2</div>'));
  multiOverview({}, {...snapshot, fields: {ph: snapshot.fields.ph}});
  await run('refresh()');
  assert.equal(element('air').textContent, '--');
  assert.equal(element('vpd').textContent, '--');
  assert.equal(element('humidity').textContent, '--');
  multiOverview();
  await run('refresh()');
  // context conflicts
  assert.equal(html('zone-notes'), '<p class="status">Devices disagree on growth_stage (using fruiting from substrate-1)</p><p class="status">Devices disagree on weather (using {&quot;a&quot;:1} from climate-1)</p>');
  // trust line of the zone: the pipeline and the risk panel
  assert.ok(html('pipeline').includes('Sensor trust: <span class="badge success">trusted</span> All readings passed the sensor check (2 devices, substrate-1 (checked by the dashboard))'));
  assert.ok(html('risk').includes(`Sensor trust: ${partial}humidity (climate-1) not used</p>`));
  assert.ok(html('advice-cards').includes(`Sensor trust: ${partial}humidity (climate-1) not used; EC not reported by any device in this zone</p>`));
  // the known slow-device case: age 20 min is live for a 45 min limit, so no zone-wide "no reading from this zone"
  multiOverview({latest_age_s: 1200}, {...snapshot, newest_age_s: 1200, devices: [snapshot.devices[2]]});
  await run('refresh()');
  for (const id of ['pipeline', 'risk']) assert.ok(!html(id).includes('no reading from this zone'), `${id}: a live slow device is not a quiet zone`);
  assert.ok(!html('pipeline').includes('from the last reading at'));
  assert.ok(html('pipeline').includes('<span class="badge success">trusted</span>'));
  // one device quiet: its probes are named in the trust line; the zone is not quiet
  replies['/api/pipeline'] = {available: true, sources: {air_temperature_c: ['climate-1'], humidity_pct: ['climate-1'], ph: ['substrate-1']},
    dashboard_judged: [], result: {pipeline_id: 'p', sensor_quality: {data_quality_labels: [], missing_fields: ['air_temperature_c', 'humidity_pct']},
      final_decision: {...goodDecision, trust_verdict: 'partial'}}};
  multiOverview({latest_age_s: 1200}, {...snapshot, newest_age_s: 1200, devices: [device('climate-1', 900, {stale: true}), snapshot.devices[2]],
    sources: {air_temperature_c: ['climate-1'], humidity_pct: ['climate-1'], ph: ['substrate-1']}});
  await run('refresh()');
  assert.ok(html('pipeline').includes(`Sensor trust: ${partial}air temperature, humidity not reported: no reading from climate-1 for 15 min</p>`));
  assert.ok(!html('pipeline').includes('no reading from this zone'));
  // every device quiet (sensor null): today's zone-wide line, from the newest device's age
  const allQuiet = {...snapshot, sensor: null, fields: {}, newest_age_s: 900, devices: [device('climate-1', 900, {stale: true}), device('substrate-1', 3000, {stale: true, stale_limit_s: 2700})]};
  multiOverview({latest_age_s: 900}, allQuiet);
  await run('refresh()');
  for (const id of ['pipeline', 'risk']) assert.ok(html(id).includes(`Sensor trust: ${staleLine('no reading from this zone for 15 min (last 12:50 +04)')}`), `${id}: all devices quiet`);
  assert.ok(html('pipeline').includes('Pipeline result from the last reading at'));
  // the newest packet (climate-1's, 29 °C) fills the tiles when there is no zone view: today's textContent path
  // (the fake element keeps innerHTML and textContent apart; in a browser the textContent assignment replaces the markup)
  assert.equal(element('air').textContent, `${latest.air_temperature_c} °C`);
  // a zone view without a sensor and a live device with no readings is not quiet
  multiOverview({latest_age_s: 900}, {...allQuiet, devices: [device('climate-1', 900, {stale: true}), device('substrate-1', 100)]});
  await run('refresh()');
  assert.ok(!html('pipeline').includes('no reading from this zone'));
  // snapshot unavailable: the newest packet, with the line saying so; today's stale rule applies to the newest packet
  multiOverview({zone_snapshot: null, device_events: null, zone_snapshot_error: 'Zone snapshot unavailable; check the service and the dashboard log.', latest_age_s: 900}, null);
  await run('refresh()');
  assert.equal(html('zone-notes'), `<p class="status">Zone view unavailable: showing the newest packet (climate-1)</p>`);
  assert.ok(html('pipeline').includes('no reading from this zone for 15 min'));
  assert.ok(html('events').includes('<th scope="col">Device</th>'), 'Device column also in the newest-packet fallback of a multi-device zone');
  // Device columns, detail line, Recent line (multi-device zones only)
  multiOverview();
  replies['/api/pipeline'].sources = zone.sources;
  await run('refresh()');
  const alertsHtml = html('alerts');
  assert.ok(alertsHtml.includes('<th scope="col">State</th><th scope="col">Device</th><th scope="col">Rule</th>'));
  assert.ok(alertsHtml.includes('<td>climate-1</td><td>sensor_check</td><td>Sensor check<div class="status">inspect humidity_pct: stuck</div></td>'));
  assert.ok(alertsHtml.includes(`<td>EC high<div class="status">${escaped}</div></td>`), 'detail is escaped');
  assert.ok(alertsHtml.includes('<td>--</td><td>x</td><td>m</td>'), 'no device: --, no detail line');
  assert.ok(alertsHtml.includes('Recent: sensor_check (climate-1) raised at'));
  assert.ok(alertsHtml.includes(' · x recovered at'), 'an event with no device has no (device)');
  assert.ok(html('events').includes('<th scope="col">Time</th><th scope="col">Device</th><th scope="col">Farm</th>'));
  assert.ok(html('events').includes('<td>substrate-1</td><td>farm-a</td>'));
  // trends: one line per device, legend, shared window; VPD only for devices with both readings
  const trends = html('trends');
  assert.equal((trends.match(/<div class="trend-card/g) || []).length, 5);
  const card = (name) => trends.split('<div class="trend-card ')[1 + ['temp', 'humidity', 'ph', 'ec', 'vpd'].indexOf(name)];
  assert.equal((card('temp').match(/<polyline/g) || []).length, 2, 'air temperature: climate-1 and climate-2');
  assert.ok(card('temp').includes('stroke-dasharray="6 3"') && card('temp').includes('</svg>climate-2</span>'));
  assert.equal((card('humidity').match(/<polyline/g) || []).length, 1, 'humidity: only climate-1 carries it');
  assert.equal((card('ph').match(/<polyline/g) || []).length, 1);
  assert.ok(card('ph').includes('stroke-dasharray="2 3"') && card('ph').includes('substrate-1: min'), 'substrate-1 is the third device: pattern 2');
  assert.equal((card('vpd').match(/<polyline/g) || []).length, 1, 'VPD: only climate-1 carries both');
  assert.ok(!trends.includes('not plotted'));
  multiOverview({device_events: {'climate-1': climateEvents.map(e => ({...e, air_temperature_c: null, humidity_pct: null}))}});
  await run('refresh()');
  assert.ok(html('trends').includes('No device carries both air temperature and humidity'));
  assert.ok(html('trends').includes('climate-2: not plotted · substrate-1: not plotted'), 'devices without trend data are named');
  // back to a single-device zone: nothing of the above remains
  replies['/api/overview'] = {core_available: true, latest_event: stamped, recent_events: [stamped], latest_age_s: 10, stale_after_s: 600};
  replies['/api/pipeline'] = {available: true, result: {pipeline_id: 'p', final_decision: goodDecision, sensor_quality: {}}};
  replies['/api/alerts'] = {available: true, result: {alerts: [{state: 'active', rule_id: 'r', device_id: 'd', message: 'm', detail: 'must not show', since: minute(0)}],
    events: [{rule_id: 'r', device_id: 'd', event: 'raised', sample_time: minute(1)}]}};
  await run('refresh()');
  assert.equal(html('zone-notes'), '');
  assert.equal(element('air').textContent, `${stamped.air_temperature_c} °C`, 'the single-device tile is the plain textContent again');
  assert.ok(!html('events').includes('<th scope="col">Device</th>'));
  assert.ok(!html('alerts').includes('Device') && !html('alerts').includes('must not show') && html('alerts').includes('Recent: r raised at'));
  assert.ok(!html('trends').includes('legend-item'));
  assert.ok(html('pipeline').includes(`Sensor trust: ${green}`));
})().catch(error => { console.error(error); process.exitCode = 1; });
