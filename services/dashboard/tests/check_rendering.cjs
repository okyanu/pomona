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
})().catch(error => { console.error(error); process.exitCode = 1; });
