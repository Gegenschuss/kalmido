// 2.565.0 D (#4713) UI tests (agent chat), own container (start.sh):
// kalmido-suite: fresh
// - an answer button of 200 characters shows its whole text (no '…', no cut), short ones stay small pills; a long label
//   gets the class cchl (full width on a phone)
// Firefox 1280 mouse + 390 touch: the long button wraps onto several lines (taller than one line, nothing hidden, nothing
// sticks out sideways), at least 44 px high on touch, full width of the button row on the phone (screenshots)
// freelancer-matrix: agents (the long button in the chat of a person without an organisation with a personal agent)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2565_d_choices_ui', check, shots: 'P2565D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,team';
const V = B + 'api/v1';
const LONG = ('Run the whole release check on the test machine, compare the result with the last build and write a short list '
  + 'of every difference with its area, then wait for my answer before anything goes live on the server').slice(0, 200);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'App dev', org_id: ME.workspaces[0].id})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const sayTo = async (uid, hd, body, extra = {}) => (await fetch(V + `/agent/chats/${uid}`, {method: 'POST', headers: hd, body: JSON.stringify({body, ...extra})})).json();
  const cm = (d, id) => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${id}"]`);
  const q = await sayTo(ME.id, AGH, 'What next?', {choices: [{id: 'long', label: LONG, style: 'primary'}, {id: 'no', label: 'Later'}]});
  check(q.choices?.choices?.[0]?.label === LONG, 'the server keeps the 200 characters ' + JSON.stringify(q).slice(0, 200));

  // ================= jsdom: the whole text, class cchl only on the long one
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`chatOpen(${AG})`); await until(() => cm(d, q.id)?.querySelector('.cchb[data-cid="long"]'));
  const lb = cm(d, q.id).querySelector('.cchb[data-cid="long"]'), sb = cm(d, q.id).querySelector('.cchb[data-cid="no"]');
  check(lb && lb.textContent.trim() === LONG && !/…/.test(lb.textContent), 'the long button shows the whole text, no …');
  check(lb && (lb.classList.contains('cchl') || lb.closest('.cchw')?.classList.contains('cchl')), '... and is marked long (cchl)');
  check(sb && !sb.classList.contains('cchl') && !sb.closest('.cchw')?.classList.contains('cchl'), 'a short button is not marked long');
  w.close();

  // freelancer: the same in the own agent's chat
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, FK);
  const FU = (await call('GET', '/api/state', null, FK)).me;
  check((FU.workspaces || []).length === 0, 'freelancer: no organisation');
  const fa = await call('POST', '/api/my/agents', {username: 'fridabot', display_name: 'Frida bot', scopes: ['read', 'tasks:write', 'comments']}, FK);
  const ft = await call('POST', `/api/my/agents/${fa.id}/token`, {}, FK);
  const fq = await sayTo(FU.id, {Authorization: 'Bearer ' + ft.token, 'Content-Type': 'application/json'}, 'Next?', {choices: [{id: 'long', label: LONG}, 'Later']});
  check(fq.choices?.choices?.[0]?.label === LONG, 'freelancer: the server keeps the 200 characters ' + JSON.stringify(fq).slice(0, 200));
  w = await boot({user: 'frida'}); d = w.document;
  w.eval(`chatOpen(${fa.id})`); await until(() => cm(d, fq.id)?.querySelector('.cchb'));
  const fb = [...cm(d, fq.id).querySelectorAll('.cchb')].find(x => x.textContent.trim() === LONG);
  check(fb && (fb.classList.contains('cchl') || fb.closest('.cchw')?.classList.contains('cchl')), 'freelancer: the long button whole and marked long');
  w.close();

  // ================= Firefox: the real layout
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const sel = `#chat-msgs .cmsg[data-mid="a:${q.id}"]`;
  const ready = async (ev, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel} .cchb[data-cid="long"]')`).catch(() => false)); i++) await sleep(300); await sleep(400); };
  const geo = `(() => { const b = document.querySelector('${sel} .cchb[data-cid="long"]'), s = document.querySelector('${sel} .cchb[data-cid="no"]'); if (!b || !s) return null;
    const row = b.closest('.cchoices'), u = b.closest('.cchw') || b, br = b.getBoundingClientRect(), sr = s.getBoundingClientRect(), rr = row.getBoundingClientRect(), sp = b.querySelector('span'), cs = getComputedStyle(sp);
    const lh = parseFloat(cs.lineHeight) || 18;
    return {h: Math.round(br.height), sh: Math.round(sr.height), lines: Math.round(sp.getBoundingClientRect().height / lh), clip: sp.scrollWidth > sp.clientWidth + 1 || cs.textOverflow === 'ellipsis',
      ws: cs.whiteSpace, full: Math.abs(u.getBoundingClientRect().width - rr.width) <= 2, inRow: br.right <= rr.right + 1, wide: document.documentElement.scrollWidth <= innerWidth}; })()`;
  for (const [W, touch] of [[1280, false], [390, true]]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = String(W);
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 800}});
    await o.nav(B + '#agents/' + AG); await ready(ev);
    await ev(`(() => { document.querySelector('${sel}')?.scrollIntoView({block: 'center'}); return 1; })()`); await sleep(300);
    const g = await ev(geo);
    check(g && g.lines >= 2 && g.h > g.sh && !g.clip && g.ws !== 'nowrap', `${tag}: the long button wraps onto several lines, its height grows, nothing cut ` + JSON.stringify(g));
    check(g && g.inRow && g.wide, `${tag}: nothing sticks out sideways ` + JSON.stringify(g));
    if (touch) check(g && g.h >= 44 && g.sh >= 40 && g.full, `${tag}: touch: at least 44 px, the long one takes the full width ` + JSON.stringify(g));
    else check(g && g.sh <= 40, `${tag}: the short button stays a one-line pill ` + JSON.stringify(g));
    await shot(`p2565d-${W}-long-button.png`);
  }, touch);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
