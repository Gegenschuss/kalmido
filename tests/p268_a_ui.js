// 2.68.0 UI tests, part A (#1839: old data into the office with the person's own agent), own container (start.sh, mode
// workspaces), Firefox (desktop + phone width). Invented names and figures only.
// - the agent's import card: the preview rows of the spreadsheet import (new ticked, already there unticked, an error greyed
//   out without a tick), the office it goes into, the VAT per row with net and gross, "Take over N rows"
// - a script in a row's name stays text
// - unticking / another VAT rate, take over -> exactly these rows in the fixed costs of the cash flow
// - on a phone the rows stay inside the screen with large tap targets
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p268_a_ui', check, shots: 'P268A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (hd, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...hd}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');
const FEAT = 'cal,comments,collab,office,clients';
const ym = new Date().toISOString().slice(0, 7);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = {Cookie: await login('alice')};
  await call(CK, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CK, 'GET', '/api/state')).me;
  const org = await call(CK, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CK, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const f0 = await call(CK, 'POST', '/api/office/fixed-costs', {label: 'Miete', amount: 900, start: ym + '-01', repeat: 'monthly'});
  check(f0.http === 201, 'setup: a fixed cost ' + f0.http);
  const ag = await call(CK, 'POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude', scopes: ['read', 'comments', 'import']});
  sql('UPDATE agents SET org_id=NULL, owner_id=? WHERE user_id=?', [me.id, ag.id]);  // alice's personal agent
  const jp = await call({Authorization: 'Bearer ' + ag.token}, 'POST', '/api/v1/agent/proposals/import', {area: 'fixed_costs', summary: 'From the old sheet',
    items: [{label: 'Miete', amount: 900, start: ym + '-01', repeat: 'monthly'},
      {label: 'Software subscription', amount: 29.9, start: '2026-01-01', vat_rate: 19},
      {label: 'Liability insurance', amount: '240,00', repeat: 'yearly', start: '2026-03-01', category: 'Insurances'},
      {label: '', amount: 5, start: '2026-01-01'},
      {label: '<img src=x onerror="window.__aimx=1">Cleaning', amount: 50, start: '2026-01-01'}]});
  check(jp.http === 201 && jp.kind === 'import', 'setup: an import proposal ' + jp.http + JSON.stringify(jp.error || ''));

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const noSide = sel => `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('${sel}')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const row = t => `[...document.querySelectorAll('.ppm .aim-l .fcirow')].find(x => x.textContent.includes(${JSON.stringify(t)}))`;
  const apply = `document.querySelector('.ppm [data-pp="apply"]')`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await nav(B + '#prop/' + jp.id);
    check(await ready(ev, `document.querySelectorAll('.ppm .aim-l .fcirow').length === 5`, 80), 'the card with the five rows');
    check(await ev(`/Proposal by Claude/.test(document.querySelector('.ppm').textContent) && /Into: Alpha/.test(document.querySelector('.ppm .aim-to')?.textContent || '') && /From the old sheet/.test(document.querySelector('.ppm .ppsum')?.textContent || '')`),
      'who proposes it, why and into which office');
    check(await ev(`(() => { const d = ${row('Miete')}; return d.classList.contains('dup') && !d.querySelector('input').checked && /Already there/.test(d.textContent); })()`), 'already there: marked, not ticked');
    check(await ev(`(() => { const e = document.querySelector('.ppm .aim-l .fcirow.err'); return !!e && !e.querySelector('input') && /Row 4/.test(e.textContent); })()`), 'an error row greyed out without a tick, with its row');
    check(await ev(`${row('Liability insurance')}.querySelector('select').value === '0' && ${row('Software subscription')}.querySelector('select').value === '19'`), 'VAT per row: the insurance 0 %, else 19 %');
    check(await ev(`/Take over 3 rows/.test(${apply}.textContent) && !${apply}.disabled`), 'Take over 3 rows');
    check(await ev(`window.__aimx === undefined && !document.querySelector('.ppm .aim-l img') && /<img/.test(${row('Cleaning')}.textContent)`), 'a script in a name stays text');
    await shot('p268-a-card.png');
    await ev(`(() => { const s = ${row('Software subscription')}.querySelector('select'); s.value = '7'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `/31\\.99/.test(${row('Software subscription')}.querySelector('.aim-g').textContent)`), 'another VAT rate: the gross follows (31.99)');
    await ev(`(() => { const c = ${row('Liability insurance')}.querySelector('input'); c.checked = false; c.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `/Take over 2 rows/.test(${apply}.textContent)`), 'unticking counts down');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide('.ppm .aim-l .fcirow *')), 'on a phone the rows stay inside the screen');
    check(await ev(`[...document.querySelectorAll('.ppm .aim-l .fcick')].every(x => x.getBoundingClientRect().height >= 43 && x.getBoundingClientRect().width >= 43)`), 'large tap targets for the ticks');
    check(await ev(`${apply}.getBoundingClientRect().height >= 36 && ${apply}.getBoundingClientRect().right <= document.documentElement.clientWidth + 1`), 'the take over button reachable on a phone');
    await shot('p268-a-card-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`(() => { ${apply}.click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.ppm')`), 'the card closes after taking over');
    check(await ready(ev, `fetch('/api/office/fixed-costs', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.items.length === 3 && j.items.some(i => i.label === 'Software subscription' && i.vat_rate === 7) && !j.items.some(i => /Liability/.test(i.label)))`),
      'exactly the two ticked rows, with the changed rate');
    await nav(B + '#office/cashflow');
    check(await ready(ev, `[...document.querySelectorAll('[data-rkf="fixed"]')].some(b => /Software subscription/.test(b.textContent) && /VAT 7 %/.test(b.textContent))`, 80), 'the fixed costs of the cash flow show them');
    await shot('p268-a-cashflow.png');
  }, false);

  console.log(`p268_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
