// kalmido-suite: fresh
// 2.438.0 A (#3322): the agent's colour tints its answer bubbles (agent chat, shared window = same markup, team chat per sender),
// a new colour acts at once without reloading, no colour = today's tone; text contrast on the tint >= 4.5:1 light + dark (computed).
// freelancer-matrix: settings -- the person has no organisation; no new route (colour route /api/agents/<id>/color exists).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, TOK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + TOK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 200 : 15000, step: 200});
const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const lum = c => { const [r, g, b] = c.map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
const mix = (c, base, p) => c.map((v, i) => v * p + base[i] * (1 - p));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Dev Bot'});
  const CL = ag.id; TOK = ag.token;
  await call('PATCH', `/api/admin/agents/${CL}`, {org_id: ORG});
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: CL, role: 'edit'});
  await call('POST', `/api/agents/${CL}/chat`, {body: 'Hello bot'});
  await v1('POST', `/agent/chats/${me.id}`, {body: 'Plain answer'});
  const w = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}), d = w.document;
  await until(() => d.querySelector('#chat-msgs'), 25);
  if (!d.querySelector('#chat-msgs')) w.eval(`chatOpen(${CL})`);
  await until(() => d.querySelectorAll('#chat-msgs .cmsg.agc').length >= 1, 100);
  const col = w.eval(`ac_color(${CL})`), msgs = d.querySelector('#chat-msgs');
  check(col && msgs.style.getPropertyValue('--agcol') === col && msgs.dataset.agid === String(CL), 'agent chat: the message area carries the colour and the agent id');

  // immediate effect: picking another colour repaints without re-reading the page
  const pick = w.eval('AC_COLORS').find(c => c !== col);
  w.eval(`S.colors[${CL}] = '${pick}'; document.querySelectorAll('[data-agid="${CL}"]').forEach(el => el.style.setProperty('--agcol', '${pick}'))`);
  check(msgs.style.getPropertyValue('--agcol') === pick, 'the colour change reaches the open messages at once');
  // the real handler: a click on a palette button of the agent
  d.body.insertAdjacentHTML('beforeend', `<div id="pk">${w.eval(`ac_pickHtml('', '${CL}')`)}</div>`);
  const b2 = [...d.querySelectorAll('#pk [data-accol]')].find(x => x.dataset.accol !== pick);
  b2.click();
  await until(() => msgs.style.getPropertyValue('--agcol') === b2.dataset.accol, 50);
  check(msgs.style.getPropertyValue('--agcol') === b2.dataset.accol, 'a click on a palette colour repaints the open chat');

  // team chat: the agent's bubbles carry its colour, a person's and mine do not; no colour known = no style
  const html = w.eval(`(() => { const now = new Date().toISOString(), mk = (id, uid) => ({id, user_id: uid, body: 'x' + id, created_at: now, reactions: [], attachments: []});
    S.tc = {...S.tc, rid: 1, room: {id: 1, members: [{id: ${CL}, agent: true}]}, users: {}, msgs: [mk(1, ${CL}), mk(2, ${me.id})], more: false, th: null};
    return tcMsgsHtml(); })()`);
  const box = d.createElement('div'); box.innerHTML = html;
  const am = box.querySelector('.cmsg.agc'), mm = box.querySelector('.cmsg.me');
  check(am && am.style.getPropertyValue('--agcol') === b2.dataset.accol && am.dataset.agid === String(CL), 'team chat: the agent message carries its colour');
  check(mm && !mm.hasAttribute('style') && !mm.dataset.agid, 'team chat: my message has no agent colour');
  w.eval(`delete S.colors[${CL}]`);
  box.innerHTML = w.eval('tcMsgsHtml()');
  check(box.querySelector('.cmsg.agc') && !box.querySelector('.cmsg.agc').hasAttribute('style'), 'team chat: without a colour no style (today\'s tone)');

  // CSS: edge 25 %, no edge without colour, tint mixed into --bg3
  const css = require('./boot').allCssSync();
  check(/\.cmsg\.agc:not\(\.jobm\):not\(\.apv\) \.cbub:not\(\.del\):not\(\.tcedit\)\{box-shadow:inset 0 0 0 1px color-mix\(in srgb,var\(--agcol,transparent\) 25%,transparent\)\}/.test(css), 'CSS: 25 % edge in the agent colour');
  check(/\.cmsg\.agc \.cbub\{background:color-mix\(in srgb,var\(--agcol,var\(--agent-bg\)\) var\(--agent-tint\),var\(--bg3\)\)/.test(css), 'CSS: tint into --bg3, fallback = today\'s tone');

  // contrast of the text on the tinted bubble for every palette colour, light + dark
  const first = re => { const m = css.match(re); return m && m[1]; };
  const dark = {bg3: first(/--bg3:(#[0-9a-f]{6})/i), text: first(/--text:(#[0-9a-f]{6})/i), tint: 0.26};
  const lt = css.match(/:root\[data-theme="light"\]\{--bg:#ffffff;--bg2:#[0-9a-f]{6};--bg3:(#[0-9a-f]{6});[^}]*--text:(#[0-9a-f]{6})/i);
  const light = {bg3: lt && lt[1], text: lt && lt[2], tint: 0.14};
  for (const [name, t] of [['dark', dark], ['light', light]]) {
    check(t.bg3 && t.text, name + ': tokens found');
    const worst = Math.min(...w.eval('AC_COLORS').map(c => ratio(mix(rgb(c), rgb(t.bg3), t.tint), rgb(t.text))));
    check(worst >= 4.5, `${name}: text contrast on the tinted bubble >= 4.5 (worst ${worst.toFixed(2)})`);
  }
  console.log(`p2438_a_ui: ${ok} ok, ${F.length} failed`);
  w.close();
  process.exit(F.length ? 1 : 0);
})();
