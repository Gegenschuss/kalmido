// 2.250.0 UI tests, part C (#2994 #2995), own container (start.sh). jsdom, invented data only. freelancer-matrix: settings
// - #2994 settings search: titles / field names before explanation lines, at most ONE explanation per section, the cut at a word
//   boundary, a blank between a title and its text, synonyms ("Logo" finds "Symbol", never "Sign out" because "logout" starts with
//   "logo"), "Vacation" offers the absence sheet, the jump marks its target (class sflash)
// - #2995 "+ N more views" unfolds in place: the hidden views with a tick (= shows it in the sidebar, the same setting as
//   Settings > Appearance > Sidebar), a small "Customize…" link into the settings; folded/unfolded state survives a redraw;
//   also for a person without an organisation
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); let j = null; try { j = await r.json(); } catch {} return {http: r.status, ...(j || {})}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,time,progress,kanban,timeline,fields,team';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']}, CK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CK);
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  check(fr.http < 300, 'a person without an organisation');
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, FCK);

  // ================= #2994: the search engine on a small fixture
  let w = await boot({user: 'alice', hash: 'today'}); let d = w.document;
  await until(() => d.querySelector('#side'));
  const run = (q, fxHtml) => w.eval(`(() => {
    const md = document.createElement('div'); md.id = 'fx'; md.innerHTML = ${JSON.stringify(fxHtml)}; document.body.appendChild(md);
    const hits = ss_hits(md, ${JSON.stringify(q)}, () => true, [[['logout', 'sign out'], '[data-acc="logout"]']]);
    const out = hits.map(h => ({t: h.t, k: h.k, act: h.act || '', tag: h.el ? h.el.tagName : ''}));
    md.remove(); return JSON.stringify(out);
  })()`);
  const FX = `<div class="spane" data-pane="org"><h4>People</h4><div class="row"><label>Symbol</label><input></div>
    <p class="shint">Members of the organisation can see all shared projects of the organisation and more.</p>
    <p class="shint">Members may also connect their own agents.</p>
    <h4>Other</h4><p class="shint">Add members here.</p>
    <details><summary><b>Office &amp; finance</b><small>Everything from Team plus the office.</small></summary></details></div>
    <div class="spane" data-pane="account"><h4>Account</h4><button data-acc="logout">Sign out</button></div>`;
  let h = JSON.parse(await run('logo', FX));
  check(h.some(x => x.t === 'Symbol'), '#2994: "Logo" finds the field "Symbol" ' + JSON.stringify(h));
  check(!h.some(x => /sign out/i.test(x.t)), '#2994: "Logo" no longer finds "Sign out" (logout starts with logo) ' + JSON.stringify(h));
  h = JSON.parse(await run('logou', FX));
  check(h.some(x => /sign out/i.test(x.t)), '#2994: a prefix of a synonym still finds it ("logou")');
  h = JSON.parse(await run('members', FX));
  check(h.length && h[0].tag === 'H4' && h[0].t === 'People', '#2994: "Members" shows the section first ' + JSON.stringify(h));
  const hints = h.filter(x => x.tag === 'P');
  check(hints.length === 2, '#2994: at most one explanation per section (2 sections -> 2) ' + JSON.stringify(h));
  check(h.findIndex(x => x.tag === 'P') > h.findIndex(x => x.tag === 'H4'), '#2994: explanations come after the titles');
  h = JSON.parse(await run('finance', FX));
  check(h.length === 1 && /Office & finance Everything from Team/.test(h[0].t), '#2994: a blank between title and text ' + JSON.stringify(h));
  check(w.eval(`ss_cut('alpha beta gamma delta', 13)`) === 'alpha beta…' && w.eval(`ss_cut('short', 13)`) === 'short', '#2994: the cut is at a word boundary');
  h = JSON.parse(await run('vacation', FX));
  const wl = w.eval('workloadOn()');
  check(h.some(x => x.act === 'absence') === !!wl, '#2994: "Vacation" offers "Enter an absence" exactly when the module is on ' + JSON.stringify(h));

  // ================= #2994: the real dialog: type, jump, the target is marked
  w.eval(`settingsModal()`); await until(() => d.querySelector('#s-search'));
  const sq = d.querySelector('#s-search');
  sq.dispatchEvent(new w.FocusEvent('focus')); sq.value = 'logo'; sq.dispatchEvent(new w.Event('input', {bubbles: true}));
  const tx = [...d.querySelectorAll('#s-sres [data-hit]')].map(b => b.textContent);
  check(!tx.some(t => /sign out|log out/i.test(t)), '#2994: dialog: "Logo" finds no sign-out entry ' + JSON.stringify(tx));
  sq.value = 'sidebar'; sq.dispatchEvent(new w.Event('input', {bubbles: true}));
  const b0 = d.querySelector('#s-sres [data-hit="0"]');
  check(!!b0, '#2994: dialog: "sidebar" has a hit');
  if (b0) { click(w, b0); check(!!(await until(() => d.querySelector('.smodal .sflash, .modal .sflash'))), '#2994: the jump marks its target (sflash)'); }
  d.querySelector('.modal [data-m="close"]')?.click();
  w.close();

  // ================= #2995: "+ N more views" unfolds (a person with an organisation space, and one without)
  for (const [who, ck] of [['alice', CK], ['frida', FCK]]) {
    await call('PATCH', '/api/settings', {sidebar: JSON.stringify({order: [], hidden: ['e:tomorrow', 'e:week', 'e:doable']})}, ck);
    w = await boot({user: who, hash: 'today'}); d = w.document;
    const more = await until(() => d.querySelector('#side .srow.smore[data-act="side-more"]'));
    check(!!more && /3 more views/.test(more.textContent), `#2995 ${who}: "+ 3 more views" is there ` + (more && more.textContent.trim()));
    check(!d.querySelector('#side .smorebox') && more.getAttribute('aria-expanded') === 'false', `#2995 ${who}: folded at first`);
    click(w, more);
    await until(() => d.querySelector('#side .smorebox'));
    check(!d.querySelector('.smodal #s-sidebar'), `#2995 ${who}: no settings dialog opens any more`);
    check(d.querySelectorAll('#side .smorebox .smrow').length === 3 && d.querySelector('#side .srow.smore').getAttribute('aria-expanded') === 'true', `#2995 ${who}: the three hidden views with a tick`);
    check([...d.querySelectorAll('#side .smorebox .smrow .srow')].some(x => /Tomorrow/.test(x.textContent)) && !!d.querySelector('#side .smorebox [data-go]'), `#2995 ${who}: the name opens the view`);
    w.eval(`renderSide()`);
    check(!!d.querySelector('#side .smorebox'), `#2995 ${who}: stays unfolded on a redraw`);
    const tick = d.querySelector('#side .smorebox input[data-side-show="tomorrow"]');
    tick.checked = true; tick.dispatchEvent(new w.Event('change', {bubbles: true}));
    const gone = await until(async () => !JSON.parse((await call('GET', '/api/state', null, ck)).settings.sidebar).hidden.includes('e:tomorrow'));
    check(gone, `#2995 ${who}: the tick writes the sidebar setting (Tomorrow no longer hidden)`);
    const st = JSON.parse((await call('GET', '/api/state', null, ck)).settings.sidebar);
    check(st.hidden.includes('e:week') && st.hidden.includes('e:doable'), `#2995 ${who}: the others stay hidden ` + JSON.stringify(st));
    await until(() => d.querySelectorAll('#side .smorebox .smrow').length === 2);
    check(d.querySelectorAll('#side .smorebox .smrow').length === 2 && [...d.querySelectorAll('#side > * .srow, #side .srow')].some(x => /Tomorrow/.test(x.textContent) && !x.closest('.smorebox')), `#2995 ${who}: Tomorrow moved into the sidebar`);
    click(w, d.querySelector('#side .smcust'));
    check(!!(await until(() => d.querySelector('#s-sidebar'))), `#2995 ${who}: "Customize…" opens Settings > Appearance > Sidebar`);
    d.querySelector('.modal [data-m="close"]')?.click();
    click(w, d.querySelector('#side .srow.smore'));
    await sleep(50);
    check(!d.querySelector('#side .smorebox'), `#2995 ${who}: folds again`);
    w.close();
  }
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
