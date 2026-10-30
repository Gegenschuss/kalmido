// 2.233.0 B (#3189) UI tests, own container (start.sh): the runtime section "Interim summary" (Zwischenstand).
// jsdom: the admin's agent dialog shows it below "Runtime" with session size, messages, minutes of pause and the existing
// nightly restart moved in as "Daily summary"; every field saves at once (no Save needed), a value out of range is refused in
// the dialog and changes nothing. A person without an organisation (freelancer-matrix: agents) finds it in the permissions
// dialog of the own agent, with its own daily-summary time picker, saved at once. German labels.
// Firefox at 360 and 412 px (touch): the permissions dialog with the section fits (no horizontal overflow, fields inside the
// viewport, at least 40 px high). Screenshots with P2233B_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const {idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2233_b_rotate_ui', check, shots: 'P2233B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const lastModal = d => [...d.querySelectorAll('.modal')].pop();

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {features: 'agents,comments,collab', lang: 'en', tour: 'done'});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'comments'], username: 'claude', display_name: 'Claude'});
  const adm = async id => (await call('GET', '/api/admin/agents')).agents.find(a => a.id === id);

  // ================= the admin's agent dialog
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`agModal(${JSON.stringify(await adm(ag.id))}, null)`);
  let md = await until(() => d.querySelector('#ag-model')?.closest('.modal'));
  const sec = md && md.querySelector('.agzsec');
  check(sec && /Interim summary/.test(sec.querySelector('h4')?.textContent || ''), 'agent dialog: section Interim summary');
  check(sec && sec.compareDocumentPosition(md.querySelector('#ag-rt-h')) & w.Node.DOCUMENT_POSITION_PRECEDING, 'below the section Runtime');
  check(sec && sec.querySelector('#agz-size').value === 'medium' && sec.querySelector('#agz-runs').value === '60' && sec.querySelector('#agz-idle').value === '45',
    'defaults: medium, 60 messages, 45 minutes');
  check(sec && sec.querySelector('#ag-nr') && /Daily summary/.test(sec.querySelector('#ag-nr').closest('.row').textContent) && md.querySelectorAll('#ag-nr').length === 1,
    'the nightly restart sits in the section as "Daily summary" (one field)');
  check(sec && /forget details/.test(sec.textContent), 'the explanation: saves cost, can forget details');
  change(w, sec.querySelector('#agz-runs'), '120');
  check(await until(async () => (await adm(ag.id)).runtime.rotate_runs === 120), 'messages saved at once (no Save)');
  change(w, sec.querySelector('#agz-size'), 'large');
  check(await until(async () => (await adm(ag.id)).runtime.rotate_size === 'large'), 'size saved at once');
  change(w, sec.querySelector('#agz-idle'), '0');
  check(await until(async () => (await adm(ag.id)).runtime.rotate_idle_min === 0), 'pause 0 = never, saved');
  change(w, sec.querySelector('#agz-runs'), '5'); await idle(w);
  check(sec.querySelector('#agz-runs').value === '120' && /10 to 500/.test(d.querySelector('#toast')?.textContent || ''), 'messages 5: refused in the dialog, the old value back');
  change(w, sec.querySelector('#agz-idle'), '3'); await idle(w);
  check(sec.querySelector('#agz-idle').value === '0' && (await adm(ag.id)).runtime.rotate_runs === 120 && (await adm(ag.id)).runtime.rotate_idle_min === 0, 'pause 3: refused, nothing changed');
  w.eval(`dpSet(document.querySelector('#ag-nr'), '04:30')`);
  check(await until(async () => (await adm(ag.id)).runtime.nightly_reset === '04:30'), 'daily summary time saved at once');
  click(w, md.querySelector('[data-m="close"]'));
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`agModal(${JSON.stringify(await adm(ag.id))}, null)`);
  md = await until(() => d.querySelector('#ag-model')?.closest('.modal'));
  const sd = md.querySelector('.agzsec');
  check(sd && /Zwischenstand/.test(sd.textContent) && /Sitzungsgröße/.test(sd.textContent) && /Tägliche Zusammenfassung/.test(sd.textContent)
    && sd.querySelector('#agz-size').value === 'large', 'German: Zwischenstand, Sitzungsgröße, Tägliche Zusammenfassung');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= a person without an organisation: the own agent's permissions dialog
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 2});
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.status < 300, 'a freelancer ' + fr.status);
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {features: 'agents,comments', lang: 'en', tour: 'done'}, CF);
  check(!((await call('GET', '/api/state', null, CF)).me.workspaces || []).length, 'frida has no organisation');
  const FB = (await call('POST', '/api/my/agents', {username: 'fridabot', display_name: 'Fridabot'}, CF)).id;
  const mine = async () => (await call('GET', '/api/my/agents', null, CF)).agents.find(a => a.id === FB);
  w = await boot({user: 'frida', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(500);
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  const prow = await until(() => d.querySelector(`#s-myown [data-myag="${FB}"]`));
  click(w, prow.querySelector('[data-myag-act="perm"]'));
  md = await until(() => lastModal(d)?.querySelector('.agzsec') && lastModal(d));
  const ps = md && md.querySelector('.agzsec');
  check(ps && ps.querySelector('#agz-nr') && /Daily summary/.test(ps.textContent) && ps.compareDocumentPosition(md.querySelector('.foot')) & w.Node.DOCUMENT_POSITION_FOLLOWING,
    'freelancer: the section in the permissions dialog, above its buttons, with its own time picker');
  change(w, ps.querySelector('#agz-runs'), '30');
  check(await until(async () => (await mine()).runtime.rotate_runs === 30), 'freelancer: messages saved at once');
  w.eval(`dpSet(document.querySelector('#agz-nr'), '05:15')`);
  check(await until(async () => (await mine()).runtime.nightly_reset === '05:15'), 'freelancer: daily summary time saved at once');
  w.close();

  // ================= Firefox: 360 and 412 px, touch
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const FIT = `(() => { const m = [...document.querySelectorAll('.modal')].pop(), s = m && m.querySelector('.agzsec'); if (!s) return null; s.scrollIntoView({block: 'center'});
    const f = [...s.querySelectorAll('select, input:not([type=hidden]), [data-dpfor]')].map(x => x.getBoundingClientRect());
    return {over: document.documentElement.scrollWidth - innerWidth, n: f.length, out: f.filter(r => r.right > innerWidth + 1 || r.left < -1).length,
      minH: Math.round(Math.min(...f.map(r => r.height))), top: (() => { const r = s.getBoundingClientRect(), e = document.elementFromPoint(innerWidth / 2, Math.max(1, Math.min(innerHeight - 1, r.top + 10))); return !!e && m.contains(e); })(),
      cls: m.className, z: getComputedStyle(m).zIndex, n2: document.querySelectorAll('.modal').length}; })()`;
  for (const vw of [360, 412]) await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    check(await ffLogin(o) === 200, vw + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: 800}});
    await nav(B + '#today'); await ready(ev);
    await ev(`(async () => { settingsModal('ai'); await new Promise(r => setTimeout(r, 500)); await aiSubShow(document.querySelector('.smodal'), 'setup', false); return 1; })()`);
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('#s-myown [data-myag="${FB}"] [data-myag-act="perm"]')`)); i++) await sleep(300);
    await ev(`(() => { document.querySelector('#s-myown [data-myag="${FB}"] [data-myag-act="perm"]').click(); return 1; })()`);
    let f = null;
    for (let i = 0; i < 20 && !(f = await ev(FIT)); i++) await sleep(300);
    check(f && f.n >= 4 && f.over <= 1 && f.out === 0 && f.top, `${vw}: the section fits and is on top ` + JSON.stringify(f));
    check(f && f.minH >= 40, `${vw}: fields at least 40 px high ` + JSON.stringify(f));
    await sleep(800); await ev(`(() => { [...document.querySelectorAll('.modal')].pop().querySelector('.agzsec').scrollIntoView({block: 'center'}); return 1; })()`);
    await shot(`p2233b-${vw}-perm.png`);
  }, true);

  console.log(`p2233_b_rotate_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
