// kalmido-suite: fresh
// 2.540.0 (#4472) UI test: the toolbar of the documents has ONE height for search, switch, filter, sort and buttons (+-1 px, mouse
// 40 px / touch 44 px) and on a phone "To review" stands only once. Own container (start.sh), jsdom for setup, Firefox for the
// measuring and the pictures (computer 1440, phone 390). Invented names and files only.
// freelancer-matrix: documents of a person without an organisation (alice: her private workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p4472_toolbars_ui', check, shots: 'P4472_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P4472_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const menuItems = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(x => x.textContent.trim());
const pick = (d, label) => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => b.querySelector('.ml')?.textContent.trim().startsWith(label));
const up = async (url, field, name, text, extra = {}) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  fd.append(field, new Blob([text], {type: 'text/plain'}), name);
  return (await fetch(B + url, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json().catch(() => ({}));
};


(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'files', 'docs', 'office'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  const DOC = ((await up('api/docs', 'files', 'letter-alpha.txt', 'Letter of an invented insurance', {ws: 'private'})).ids || [])[0];
  check(DOC, 'setup: a document');
  await call('POST', `/api/docs/${DOC}/review`, {done: false});

  const run = (vp) => firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(st === 200, 'Firefox: login');
    const wait = async (js, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    // the heights of the controls that are shown (no space taken = not drawn)
    const MEASURE = `(() => { const out = {}; for (const [k, sel] of [['search', '.dc-bar .ctsearch'], ['switch', '.dc-bar .dc-seg'], ['filter', '.dc-bar [data-dc="more"]'], ['sort', '.dc-bar .dc-sortb'], ['add', '.dc-bar .dc-up'], ['scan', '.dc-bar [data-dc="scan"]']]) { const e = document.querySelector(sel); const b = e && e.getBoundingClientRect(); if (b && b.width) out[k] = b.height; } return JSON.stringify(out); })()`;
    { const [wd, h, tag, touch] = vp;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: h}});
      await o.nav(B + '#docs');
      check(await wait(`!!document.querySelector('.dc-view .dc-bar [data-dc="more"]')`), `${tag}: the toolbar is drawn`);
      await sleep(500);
      const m = JSON.parse(await ev(MEASURE));
      const hs = Object.values(m);
      check(hs.length >= 5, `${tag}: search, (phone: switch,) filter, sort and the buttons are measured (${Object.keys(m).join()})`);
      check(hs.length && Math.max(...hs) - Math.min(...hs) <= 1, `${tag}: every control of the toolbar has the same height (${JSON.stringify(m)})`);
      if (hs.length) check(Math.abs(hs[0] - (touch ? 44 : 40)) <= 1.5, `${tag}: the height is ${touch ? '44' : '40'} px (${hs[0]})`);
      if (wd < 500) {
        const n = await ev(`document.querySelectorAll('.dc-view [data-dc="review"], .dc-view [data-go="ablage/review"]').length`);
        check(n === 1, `${tag}: "To review" stands only once (${n})`);
      }
      await shot(`p4472-${tag}-docs.png`);
      // 2.540.0 (#4472): the chosen part of the switch is marked (it was drawn like the other one)
      // 2.752.0 (#4887): with the panel (a computer) the switch is gone: the panel has "All documents" / "To review"
      if (await ev(`typeof sbb_on === 'function' && sbb_on()`)) check(await ev(`!document.querySelector('.dc-bar .dc-seg') && !!document.querySelector('#side [data-go="ablage/review"]')`), `${tag}: no switch beside the panel's rows`);
      else check(await ev(`(() => { const [a, b] = document.querySelectorAll('.dc-bar .dc-seg button'); return !!a && a.classList.contains('on') && !b.classList.contains('on') && getComputedStyle(a).backgroundColor !== getComputedStyle(b).backgroundColor; })()`), `${tag}: the chosen part of the switch is marked`);
      if (!touch) {  // the receipt filters: the labels on one line, the two ticks on one line, "Date by"
        await o.nav(B + '#office/books/receipts');
        check(await wait(`!!document.querySelector('.rcl-filters #rcl-novat')`), `${tag}: the receipt filters are drawn`);
        await ev(`(() => { const d = document.querySelector('.rcl-filters'); if (!d.open) d.open = true; return 1; })()`);
        await sleep(300);
        const lab = JSON.parse(await ev(`JSON.stringify([...document.querySelectorAll('.rcl-filters .rcl-f>.muted:first-child')].filter(e => e.getClientRects().length).map(e => [e.textContent, Math.round(e.getBoundingClientRect().top)]))`));
        check(lab.some(([t]) => t === 'Date by'), `${tag}: the label is "Date by" (${lab.map(x => x[0]).join()})`);
        const rows = {}; for (const [t, y] of lab) (rows[y] = rows[y] || []).push(t);
        const cat = lab.find(([t]) => t === 'Category');
        check(cat && lab.some(([t, y]) => t !== 'Category' && Math.abs(y - cat[1]) <= 1), `${tag}: "Category" stands on the line of the other labels (${JSON.stringify(rows)})`);
        const ticks = JSON.parse(await ev(`JSON.stringify(['#rcl-novat', '#rcl-hints'].map(s => { const b = document.querySelector(s).getBoundingClientRect(); return Math.round(b.top + b.height / 2); }))`));
        check(Math.abs(ticks[0] - ticks[1]) <= 1, `${tag}: both ticks on one line (${ticks})`);
        await shot(`p4472-${tag}-receipts.png`);
      }
    }
  }, vp[3]);
  await run([1440, 900, '1440', false]);
  await run([390, 844, '390', true]);

  console.log(`p4472_toolbars_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})();
