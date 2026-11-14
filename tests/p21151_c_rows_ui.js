// 2.1151.0 UI test, part C (#3835 stages 3-5): the phone rows of the other lists, the sidebar and the settings
// kalmido-suite: fresh
// Own container (start.sh; P21151C_NOSTART=1 / KMT_NOSTART=1: a running server), jsdom like tests/p2451_a_office_rows_ui.js.
// Invented names only. freelancer-matrix: time (alice works without an organisation: her private workspace)
// - phone CSS (jsdom does not lay out: the rules themselves): a row button marked .ms-phsr leaves the row like .sr (stays for
//   screen readers), the one "…" of a settings row (.ms-phdots) shows only on a phone; bookmarks, feeds and the sidebar folder
//   "…" have their own rules
// - time entries (phone, 390 px rule): "Continue" stays in the row, edit + delete are hidden; a long press (touch pointer)
//   opens the menu with all three, the click ending the press opens nothing, "Edit" opens the entry's dialog with its note
// - bookmarks (phone): the row's symbols are hidden; a long press opens the menu "Mark read", "Archive", "Details";
//   "Archive" archives it on the server
// - a settings row (rules of a project, phone): edit + delete behind one "…"; it opens the menu, "Edit" clicks the hidden button
// - computer: no "…" of the settings rows in the page's look (CSS), the bookmark's right click opens its details as before
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {boot, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return !!c; };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21151C_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const pe = (w, el, type, x = 30, y = 30) => {  // a touch pointer (jsdom: a MouseEvent with pointerType)
  const C = w.PointerEvent || w.MouseEvent, ev = new C(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0});
  for (const [k, v] of [['pointerId', 1], ['pointerType', 'touch']]) if (ev[k] !== v) Object.defineProperty(ev, k, {value: v});
  el.dispatchEvent(ev); return ev;
};
const menuOpen = w => { const p = w.document.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menu"]') ? p : null; };
const labels = w => [...(menuOpen(w)?.querySelectorAll('[role="menuitem"]') || [])].map(b => b.textContent.trim()).filter(Boolean);
const pick = async (w, label) => { const it = await until(() => [...(menuOpen(w)?.querySelectorAll('[role="menuitem"]') || [])].find(b => b.textContent.trim() === label), {timeout: 5000}); it?.click(); return !!it; };
// the long press: hold until the menu is open (a real state), let go, then the click the finger makes
async function hold(w, el) {
  pe(w, el, 'pointerdown');
  const got = await until(() => menuOpen(w) && labels(w).length ? labels(w) : null, {timeout: 5000}) || [];
  pe(w, el, 'pointerup');
  el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, detail: 1}));
  return got;
}

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'time,reading,comments'});
  check(!((await call('GET', '/api/state')).orgs || []).length, 'a person without an organisation');
  const P = (await call('POST', '/api/lists', {name: 'Studio', kind: 'project', time_tracking: true})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Colour grading', list_id: P})).id;
  const E = await call('POST', '/api/time/entries', {task_id: T, start: new Date(Date.now() - 2 * 36e5).toISOString(), minutes: 30, note: 'first pass'});
  const BM = (await call('POST', '/api/bookmarks', {url: 'https://example.com/lens', title: 'Lens guide'})).bookmark?.id;
  check(P && T && E.id && BM, 'setup ' + JSON.stringify([P, T, E.id, BM]));

  // ================= the phone CSS (the rules themselves)
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'start-phrows-3835.css'), 'utf8');
  check(/@media \(max-width:767px\)\{\s*\.ms-phdots\{display:inline-flex\}\s*\.ms-phsr\{position:absolute!important;width:1px!important/.test(css), 'phone: a .ms-phsr button leaves the row like .sr');
  check(/^\.ms-phdots\{display:none\}/m.test(css) && /\.ms-phdots\{display:inline-flex\}/.test(css), 'the "…" of a settings row shows only on a phone');
  check(/#side \.fhead \.fmenu\{opacity:0;pointer-events:none\}/.test(css), 'phone: the sidebar folder\'s "…" is invisible (its long press opens the folder menu)');
  const bcss = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'bookmarks.css'), 'utf8');
  check(/\(#3835\)[\s\S]*@media \(max-width:767px\)\{\s*\.bmrow \.bmacts,[^{]*\{position:absolute!important/.test(bcss), 'phone: no symbols in a bookmark row / card');
  const fcss = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'feeds.css'), 'utf8');
  check(/\.rssitem \.rssacts\{position:absolute!important/.test(fcss), 'phone: no buttons under a feed article');

  // ================= time entries on the phone
  let w = await boot({user: 'alice', hash: 'l/' + P, mobile: true}), d = w.document;
  await until(() => w.eval(`!!taskById(${T})`), {timeout: 20000});
  w.eval(`openDetail(${T})`);
  const row = await until(() => d.querySelector('#d-time .terow.temine'), {timeout: 20000});
  if (check(row, 'phone: the own entry is shown in the task\'s time section')) {
    check(/first pass/.test(row.querySelector('.ten')?.textContent || ''), 'the entry\'s note is in the row');
    const resume = row.querySelector('[data-act="te-resume"]'), edit = row.querySelector('[data-act="te-edit"]'), del = row.querySelector('[data-act="te-del"]');
    check(resume && !resume.classList.contains('ms-phsr'), '"Continue" stays visible in the row');
    check(edit?.classList.contains('ms-phsr') && del?.classList.contains('ms-phsr'), 'edit and delete are hidden on the phone (still in the page for screen readers)');
    const h0 = w.location.hash, got = await hold(w, row.querySelector('.ten') || row);
    check(['Continue (same task and note)', 'Edit', 'Delete'].every(t => got.includes(t)), 'a long press opens the menu with all actions of the row: ' + got);
    check(w.location.hash === h0 && !d.querySelector('.modal'), 'the click that ends the press opens nothing (' + w.location.hash + ')');
    check(await pick(w, 'Edit'), 'the menu has "Edit"');
    check(await until(() => d.querySelector('#te-note')?.value === 'first pass', {timeout: 5000}), 'the menu entry opens the entry\'s dialog with its note');
    d.querySelector('.modal [data-m="close"], .modal [data-m="cancel"]')?.click();
  }

  // ================= a settings row on the phone: one "…" (the rules of a project)
  w.eval(`(() => {
    RUL[${P}] = {available: true, limit: 10, rules: [{id: 1, name: 'Close up', active: true, trigger: {kind: 'done'}, action: {kind: 'comment', text: 'done'}}]};
    const h = document.createElement('div'); h.id = 'tst'; h.className = 'members'; h.innerHTML = rul_rowsHtml(${P}); document.body.append(h);
    window.__ed = 0; h.querySelector('[data-rul-edit]').addEventListener('click', () => { __ed++; });
  })()`);
  const rr = d.querySelector('#tst .rul-row');
  check(rr && /Close up/.test(rr.textContent), 'the rule row is drawn');
  check(rr?.querySelector('[data-rul-edit].ms-phsr') && rr?.querySelector('[data-rul-del].ms-phsr'), 'edit and delete of the rule are hidden on the phone');
  const dots = rr?.querySelector('.ms-phdots');
  if (check(dots, 'the row has one "…"')) {
    dots.click();
    const it = await until(() => menuOpen(w) && labels(w).length ? labels(w) : null, {timeout: 5000}) || [];
    check(it.join() === 'Edit,Delete', 'the "…" opens the menu with the same actions: ' + it);
    await pick(w, 'Edit');
    check(await until(() => w.eval('__ed') === 1, {timeout: 3000}), '"Edit" in the menu clicks the hidden edit button');
  }
  w.close();

  // ================= bookmarks on the phone
  w = await boot({user: 'alice', hash: 'bookmarks', mobile: true}); d = w.document;
  const bm = await until(() => d.querySelector(`#view [data-id="${BM}"].bmcard, #view [data-id="${BM}"].bmrow`), {timeout: 20000});
  if (check(bm, 'phone: the bookmark is shown')) {
    check(/Lens guide/.test(bm.querySelector('.bmtitle')?.textContent || ''), 'its title is in the row');
    const got = await hold(w, bm.querySelector('.bmsite') || bm);
    check(['Mark read', 'Archive', 'Details'].every(t => got.includes(t)), 'a long press opens the menu with the row\'s symbols: ' + got);
    check(!d.querySelector('.bmdlg'), 'the click that ends the press opens no details');
    check(await pick(w, 'Archive'), 'the menu has "Archive"');
    check(await until(async () => (await call('GET', `/api/bookmarks/${BM}`)).state === 'archived', {timeout: 8000}), '"Archive" from the menu archives the bookmark');
  }
  w.close();

  // ================= the computer: unchanged
  await call('PATCH', `/api/bookmarks/${BM}`, {state: 'unread'});
  w = await boot({user: 'alice', hash: 'bookmarks'}); d = w.document;
  const bm2 = await until(() => d.querySelector(`#view [data-id="${BM}"].bmcard, #view [data-id="${BM}"].bmrow`), {timeout: 20000});
  if (check(bm2, 'computer: the bookmark is shown')) {
    check(bm2.querySelector('[data-bm="read"]') && bm2.querySelector('[data-bm="arch"]'), 'computer: the row keeps its symbols');
    bm2.querySelector('.bmsite').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true, button: 2}));
    check(await until(() => d.querySelector('.bmdlg'), {timeout: 5000}), 'computer: a right click opens the details as before');
  }
  w.close();

  console.log(`p21151_c_rows_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
