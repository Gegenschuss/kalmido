// 2.138.4 UI test, part A (phone surfaces: #2359 fixed-cost import rows, #2372 sheet bar above the tab bar, #2370 print view kept
// until the print media ends, #2362 documents / file request / tax dates targets, #2367 bookmarks targets), own container
// (start.sh, mode workspaces), Firefox at 390 px. Invented names and figures only. freelancer-matrix: office
// An organisation's admin (alice) and a person without organisation (frida) alike.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21383_a_ui', check, shots: 'P21383A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files,reading,sheets';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Nordwind', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const data = {};
  for (const [u, ck] of [['alice', CA], ['frida', CF]]) {
    const s = await call(ck, 'POST', '/api/sheets', {title: 'Small table', space: 'private'});
    const b1 = await call(ck, 'POST', '/api/bookmarks', {url: 'https://example.com/one', title: 'One', tags: ['recipes', 'travel']});
    data[u] = {sheet: s.id, bm: b1.bookmark?.id};
    check(s.id && b1.bookmark?.id, `${u}: a table and a bookmark ${s.http} ${b1.http}`);
  }

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const hOf = (ev, sel) => ev(`(() => { const e = document.querySelector('${sel}'); return e ? e.getBoundingClientRect().height : 0; })()`);
  await firefox(async ({cmd, ev, ctx, nav}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    for (const u of ['alice', 'frida']) {
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await signIn(ev, u);
      // ---- #2359: nine preview rows, every amount line inside its row
      await nav(B + '#office/cashflow');
      check(await ready(ev, `typeof fci_modal === 'function' && !!document.querySelector('.office')`, 80), `${u}: the cash flow`);
      await ev(`(() => { fci_modal(Array.from({length: 9}, (_, i) => ({row: i + 2, status: 'new', sel: true, label: 'Cost ' + (i + 1), amount: 100 + i, repeat: 'monthly', start: '2026-11-01', category: 'IT', vat_rate: 19})), 'many.xlsx'); return 1; })()`);
      check(await ready(ev, `document.querySelectorAll('.fcidlg .fcirow').length === 9`), `${u}: nine preview rows`);
      check(await ev(`[...document.querySelectorAll('.fcidlg .fcirow')].every(r => { const a = r.querySelector('.fciamt').getBoundingClientRect(), o = r.getBoundingClientRect(); return o.height >= 44 && a.top >= o.top - 1 && a.bottom <= o.bottom + 1; })`),
        `${u}: #2359 every amount line lies inside its row ` + await ev(`[...document.querySelectorAll('.fcidlg .fcirow')].map(r => Math.round(r.getBoundingClientRect().height)).join(',')`));
      await ev(`(() => { document.querySelector('.fcidlg [data-fci="close"]')?.click(); return 1; })()`);

      // ---- #2372: a short table: the sheet bar ends above the tab bar without scrolling
      await nav(B + '#sheets/' + data[u].sheet);
      check(await ready(ev, `!!document.querySelector('.shbbar')`, 80), `${u}: the sheet bar`);
      await sleep(400);
      check(await ev(`(() => { const b = document.querySelector('.shbbar').getBoundingClientRect(), t = document.getElementById('tabs').getBoundingClientRect(); return b.bottom <= t.top + 1 && getComputedStyle(document.querySelector('.shbbar')).position === 'sticky'; })()`),
        `${u}: #2372 the sheet bar is above the tab bar ` + await ev(`document.querySelector('.shbbar').getBoundingClientRect().bottom + '/' + document.getElementById('tabs').getBoundingClientRect().top`));

      // ---- #2370: an early afterprint keeps the print view until the print media ends
      const pr = await ev(`(async () => {
        const out = {}; let mqL = null; const mq = {matches: false, addEventListener: (t, f) => { mqL = f; }, removeEventListener: () => { mqL = null; }};
        const mm = window.matchMedia; window.matchMedia = q => q === 'print' ? mq : mm.call(window, q);
        window.print = () => { mq.matches = true; mqL?.(); dispatchEvent(new Event('afterprint')); };  // Android: afterprint right after print()
        shk_print();
        await new Promise(r => setTimeout(r, 300));
        out.kept = document.body.classList.contains('shkprint') && !!document.getElementById('shk-print');
        mq.matches = false; mqL?.();  // the print media ends
        out.gone = !document.body.classList.contains('shkprint') && !document.getElementById('shk-print');
        window.matchMedia = mm; return JSON.stringify(out);
      })()`);
      const prj = JSON.parse(pr || '{}');
      check(prj.kept, `${u}: #2370 the early afterprint keeps the print view`);
      check(prj.gone, `${u}: #2370 the print view goes when the print media ends`);

      // ---- #2362: documents
      await nav(B + '#docs');
      check(await ready(ev, `!!document.querySelector('.dc-seg button') && !!document.getElementById('dc-q')`, 80), `${u}: the documents`);
      check(await ev(`[...document.querySelectorAll('.dc-seg button')].every(b => b.getBoundingClientRect().height >= 43.5)`), `${u}: #2362 the segment buttons are 44 px`);
      await ev(`(() => { const q = document.getElementById('dc-q'); q.focus(); q.value = 'invoice'; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
      await sleep(700);
      check(await ready(ev, `!!document.querySelector('.tsfx[data-dcx="q"]')`), `${u}: the search chip`);
      check(await ev(`document.querySelector('.tsfx[data-dcx="q"]').getBoundingClientRect().height >= 43.5`), `${u}: #2362 the filter chip is 44 px ` + await hOf(ev, '.tsfx[data-dcx="q"]'));
      await ev(`(() => { document.getElementById('dc-q').focus(); document.querySelector('.tsfx[data-dcx="q"]').click(); return 1; })()`);
      await sleep(900);
      check(await ev(`document.getElementById('dc-q').value === '' && !document.querySelector('.tsfx[data-dcx="q"]')`), `${u}: #2362 removing the search chip empties the search field`);
      // the file request form: the note as wide as the title
      await ev(`(() => { frq_new({name: 'Folder', id: 1}, {types: ['image', 'pdf'], default_types: ['image'], default_days: 14, max_mb: 50, default_mb: 20, max_files: 20, default_files: 10}, () => {}); return 1; })()`);
      check(await ready(ev, `!!document.getElementById('frq-note')`), `${u}: the file request form`);
      check(await ev(`(() => { const a = document.getElementById('frq-note').getBoundingClientRect(), b = document.getElementById('frq-title').getBoundingClientRect(); return Math.abs(a.width - b.width) <= 2; })()`),
        `${u}: #2362 the note field is as wide as the title ` + await ev(`document.getElementById('frq-note').getBoundingClientRect().width + '/' + document.getElementById('frq-title').getBoundingClientRect().width`));
      await ev(`(() => { document.querySelector('.modal [data-frq="close"]')?.click(); return 1; })()`);

      // ---- #2367: bookmarks
      await nav(B + '#bookmarks');
      check(await ready(ev, `document.querySelectorAll('.bmtag').length > 0`, 80), `${u}: the bookmark tags`);
      check(await ev(`[...document.querySelectorAll('.bmtag')].every(b => b.getBoundingClientRect().height >= 43.5)`), `${u}: #2367 the tag targets are 44 px ` + await hOf(ev, '.bmtag'));
      await ev(`(() => { bm_detail(${data[u].bm}); return 1; })()`);
      check(await ready(ev, `!!document.getElementById('bmd-state')`), `${u}: the bookmark dialog`);
      check(await ev(`document.getElementById('bmd-state').getBoundingClientRect().height >= 43.5`), `${u}: #2367 the state select is 44 px ` + await hOf(ev, '#bmd-state'));
    }
  }, false);

  console.log(`p21383_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
