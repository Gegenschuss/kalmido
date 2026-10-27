// 2.126.2 UI tests of part A (own container, start.sh). jsdom:
// - #2357 a table shows "Mentioned in" with the pages that link it ([[tabelle:id]]), links to #wiki/<id>; nothing without pages
// - #2363 a) the [[datei: / [[tabelle: list sits above the on-screen keyboard (visualViewport stub), desktop keeps the CSS place
//   b) the "+" of checkbox lines is row-sized, its hit area only grows to the right (CSS)  c) a search with only name hits
//   draws no "Found in the text" section and no "Show more"
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21262A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki', 'sheets'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const T1 = (await call('POST', '/api/sheets', {title: 'Budget', space: 'private'})).id;
  const T2 = (await call('POST', '/api/sheets', {title: 'Alone', space: 'private'})).id;
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Plan', body: `See [[tabelle:${T1}]]\n\n- [ ] One\n- [ ] Two\n`})).id;
  check(T1 && T2 && PG, 'setup: tables and a page');

  // ================= #2357
  let w = await boot({user: 'alice', hash: 'sheets/' + T1}), d = w.document;
  const men = await until(() => d.querySelector('#view .shvmen'));
  const a = men && [...men.querySelectorAll('a')].find(x => x.getAttribute('href') === '#wiki/' + PG);
  check(a && /Mentioned in/.test(men.textContent) && a.textContent === 'Plan', '#2357: "Mentioned in" lists the page with its link');
  w.close();
  w = await boot({user: 'alice', hash: 'sheets/' + T2}); d = w.document;
  await until(() => d.querySelector('#view .shvsheet'));
  await sleep(500);
  check(!d.querySelector('#view .shvmen'), '#2357: no section without pages');
  w.close();

  // ================= #2363 a) suggestions above the keyboard
  w = await boot({user: 'alice', hash: 'wiki/' + PG, ls: {'tasks.wkSpace': JSON.stringify('private')}}); d = w.document;
  await until(() => d.querySelector('#view [data-wk="mode"][data-m="edit"]') && w.eval('WK.pg?.id') === PG);
  d.querySelector('#view [data-wk="mode"][data-m="edit"]')?.click();
  const ta = await until(() => d.querySelector('#wk-body'));
  const type = async txt => { ta.value = txt; ta.setSelectionRange(txt.length, txt.length); ta.dispatchEvent(new w.Event('input', {bubbles: true})); return until(() => { const b = d.querySelector('#wk-ac'); return b && !b.classList.contains('hidden') && b.textContent.includes('Budget') && b; }); };
  let box = await type('x [[tabelle:bud');
  check(box && box.style.position === '', '#2363: desktop (no visualViewport shift) keeps the CSS place');
  w.eval(`window.visualViewport = {height: 400, offsetTop: 0, addEventListener(t, f) { (window.__vv = window.__vv || {})[t] = f; }, removeEventListener() {}}; window.innerHeight = 800;`);
  box = await type('x [[tabelle:budg');
  await until(() => box.style.position === 'fixed');  // the 200 ms debounce redraws the list that is still shown
  check(box && box.style.position === 'fixed' && box.style.bottom === '408px', '#2363: keyboard open: the list is fixed above it ' + box?.style.position + ' ' + box?.style.bottom);
  w.eval(`window.visualViewport.height = 300`); w.eval(`window.__vv?.resize?.()`);
  check(box && box.style.bottom === '508px', '#2363: a visualViewport resize moves it ' + box?.style.bottom);
  w.close();

  // ================= #2363 b) the + of checkbox lines (CSS)
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'wiki.css'), 'utf8');
  const rule = (css.match(/\.md li\.cb \.wemcb\{[^}]*\}/) || [''])[0], after = (css.match(/\.md li\.cb \.wemcb::after\{[^}]*\}/) || [''])[0];
  check(rule && !/margin-top:-|margin-bottom:-|min-height:2\.75rem/.test(rule), '#2363: the + no longer reaches into the lines above and below');
  check(/left:0/.test(after) && /right:-[\d.]+rem/.test(after) && /top:0/.test(after) && /bottom:0/.test(after), '#2363: the hit area only grows to the right');

  // ================= #2363 c) the text search with only name hits
  w = await boot({user: 'alice', hash: 'wiki/' + PG}); d = w.document;
  await until(() => typeof w.wks_inner === 'function');
  check(w.eval(`wks_inner({pages: [{id: 1, path: 'Plan'}], more: true, busy: false}, [{id: 1}])`) === '', '#2363: only name hits: no section, no "Show more"');
  check(/Found in the text/.test(w.eval(`wks_inner({pages: [{id: 2, path: 'Other'}], more: true, busy: false}, [{id: 1}])`)), '#2363: a text hit keeps the section');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
