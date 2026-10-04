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
const decision = {risk_level: attack, blocked_actions: [attack]};
const specialist = {source: attack, data_quality_labels: [attack]};
const replies = {
  '/api/devices': {available: true, result: {devices: [{device_id: attack, last_seen: attack, quality: attack}]}},
  '/api/history': {available: true, result: {events: [event]}},
  '/api/overview': {core_available: true, latest_event: event, recent_events: [event]},
  '/api/pipeline': {available: true, result: {pipeline_id: attack, final_decision: decision,
    sensor_quality: specialist, agronomy_calc: {irrigation: {reference_et_mm_day: attack},
      fertilizer: {urea_g: attack}}}},
  '/api/audit': {available: true, result: {events: [{evaluated_at: attack, scenario_id: attack, ...decision}]}},
  '/api/risk': {available: true, result: {sensor_quality: specialist}},
  '/api/safety': {available: true, result: {safe_alternative: attack, safety_labels: [attack]}},
  '/api/automation': {available: true, result: {suggestions: [{id: attack, rule_id: attack,
    action: attack, message: attack, status: 'pending'}]}},
  '/api/advice-cards': {available: true, result: {cards: [{card_id: attack, title: attack,
    summary: attack, severity: 'warn', status: 'pending', opportunity: attack,
    evidence: {sample_time: attack, provenance_status: attack, readings: {[attack]: attack},
      sensor_snapshot: {ph: attack}}, safe_next_checks: [attack], blocked_actions: [attack],
    human_review_required: true}]}},
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
  assert.equal(vm.runInContext("escapeHtml(null)", context), '');
  assert.equal(vm.runInContext("escapeHtml(0)", context), '0');
  assert.ok(vm.runInContext("badge('routine', 'success')", context).includes('class="badge success"'));
  replies['/api/overview'].core_available = false;
  await vm.runInContext('refresh()', context);
  assert.ok(element('status').textContent.includes('STALE'));
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
})().catch(error => { console.error(error); process.exitCode = 1; });
