// 2.695.0 (#4619) UI test (jsdom), fresh DB: a long press (phone, pointerType touch) on a row with a "…" opens the same as
// kalmido-suite: fresh
// the "…" in every view the test can reach with data; the static side (every "…" of a row has a binding) is
// tests/p2695_a_rowmenu_coverage_test.py. Per view: the "…" (data-rowmenu) is clicked and what opens is noted (a menu: its
// items; a dialog: its title); a long press on the row opens the same, the click that ends the press opens nothing (no new
// route, the menu stays), a swipe (moving over the threshold) opens nothing, a right click opens the same. Views: projects
// page, notes cards, team chat message, section head of a list, own section of My tasks (new), table cards (new), bookmarks
// card (new), knowledge rows, contacts rows, the rows of the dialogs Calendars (new) and Address books (new).
const {boot, errs, B, login, until, sleep} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return !!c; };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const HOLD = 500, GUARD = 600;  // multisel.js: ms_longPress holds 500 ms; ms_lpRecent swallows the click 600 ms after the press
const pe = (w, el, type, x = 30, y = 30) => {  // a touch pointer (jsdom: a MouseEvent with pointerType)
  const C = w.PointerEvent || w.MouseEvent, ev = new C(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0});
  for (const [k, v] of [['pointerId', 1], ['pointerType', 'touch']]) if (ev[k] !== v) Object.defineProperty(ev, k, {value: v});
  el.dispatchEvent(ev); return ev;
};
const rclick = (w, el) => { const ev = new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true, button: 2}); el.dispatchEvent(ev); return ev; };
const menuOpen = w => { const p = w.document.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menu"]') ? p : null; };
const labels = w => [...(menuOpen(w)?.querySelectorAll('[role="menuitem"]') || [])].map(b => b.textContent.trim()).filter(Boolean);

// the same as the "…": equal, or the "…" menu with the row's name and "Select" on top (where rows can be chosen, #4612 cm_selHead)
const same = (got, want) => !!got && (!want || got === want || (got.startsWith('menu: ') && want.startsWith('menu: ') && got.endsWith(' | ' + want.slice(6))));
// one view: rowSel = the rows, target = where the finger lands inside the row (default: the row), btn = false: the row has no "…"
async function probe(w, name, rowSel, {target = '', btn = true} = {}) {
  const d = w.document;
  if (!check(await until(() => d.querySelector(rowSel)), `${name}: a row is shown (${rowSel})`)) return;
  const base = d.querySelectorAll('.modal').length;
  const what = () => {
    const l = labels(w); if (l.length) return 'menu: ' + l.join(' | ');
    const ms = [...d.querySelectorAll('.modal')]; return ms.length > base ? 'dialog: ' + (ms[ms.length - 1].querySelector('h1, h2, h3')?.textContent || '?').trim() : '';
  };
  const shut = async () => { w.eval('closePop()'); [...d.querySelectorAll('.modal')].slice(base).forEach(m => m.remove()); await until(() => !what(), {timeout: 3000}); };
  const tg = () => (target && d.querySelector(rowSel)?.querySelector(target)) || d.querySelector(rowSel);
  let want = '';
  if (btn) {
    const b = d.querySelector(rowSel).querySelector('[data-rowmenu]');
    if (check(b, `${name}: the row's "…" carries data-rowmenu`)) {
      b.click(); want = await until(() => what(), {timeout: 5000}) || '';
      check(want, `${name}: the "…" opens a menu or a dialog`);
      await shut();
    }
  }
  // the long press: hold until something opens (a real state), then let go and click as the finger does
  const h0 = w.location.hash;
  pe(w, tg(), 'pointerdown');
  const got = await until(() => what(), {timeout: 5000}) || '';
  check(same(got, want), `${name}: a long press opens the same as the "…" (${got} | ${want})`);
  pe(w, tg(), 'pointerup');
  tg().dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, detail: 1}));
  check(w.location.hash === h0 && what() === got, `${name}: the click that ends the press opens nothing (${h0} -> ${w.location.hash}, ${what()})`);
  await shut();
  await sleep(GUARD + 50);  // the click guard of the press is over (the mechanism's own time)
  // a swipe: the finger moves over the threshold (10 px) before the hold is over - nothing opens, also after the hold time
  pe(w, tg(), 'pointerdown', 30, 30);
  pe(w, tg(), 'pointermove', 30, 70);
  await sleep(HOLD + 150);  // longer than the hold (the mechanism's own time)
  check(!what(), `${name}: a swipe opens nothing (${what()})`);
  pe(w, tg(), 'pointerup', 30, 70);
  await shut();
  // a right click (computer) opens the same
  const ev = rclick(w, tg());
  const rc = await until(() => what(), {timeout: 5000}) || '';
  check(ev.defaultPrevented && same(rc, want), `${name}: a right click opens the same (${rc})`);
  await shut();
  console.log(`${name}: done (${ok} ok, ${F.length} failed so far)`);
}

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,cal,events,contacts,sheets,wiki,reading'});
  const P = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  const S1 = (await call('POST', '/api/sections', {list_id: P, name: 'Doing'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Page 1', list_id: P, section_id: S1})).id;
  await call('POST', '/api/tasks', {title: 'Pay the rent', list_id: P, section_id: S1, due: '2020-01-02'});  // overdue: My tasks "Now"
  const N1 = (await call('POST', `/api/lists/${P}/notes`, {title: 'Meeting notes', body: 'Agenda'})).id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});  // a shared project has its team room
  const RID = (await call('GET', '/api/team')).rooms?.find(r => r.list_id === P)?.id;
  const MA = RID && (await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'On it.'})).id;
  const SH = (await call('POST', '/api/sheets', {title: 'Small table', space: 'private'})).id;
  const BM = (await call('POST', '/api/bookmarks', {url: 'https://example.com/one', title: 'One'})).bookmark?.id;
  const WK = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Plan', body: 'Line one'})).id;
  const BK = (await call('POST', '/api/books', {name: 'Customers'})).id;
  const CT = BK && (await call('POST', '/api/contacts', {book_id: BK, fn: 'Anna Alpha', emails: [{value: 'anna@example.com'}]})).id;
  const CAL = (await call('POST', '/api/evcals', {name: 'Studio'})).id;
  check(BOB && T1 && N1 && MA && SH && BM && WK && BK && CT && CAL, 'setup ' + JSON.stringify([T1, N1, MA, SH, BM, WK, BK, CT, CAL]));

  let w = await boot({user: 'alice', hash: 'projects'}), d = w.document;
  await probe(w, 'projects page', '#view .pstart .psrow[data-pl]', {btn: false, target: '.n'});
  w.close();

  w = await boot({user: 'alice', hash: 'notes'}); d = w.document;
  await probe(w, 'notes', 'a.ntcard[href^="#note/"]', {btn: false});
  w.close();

  w = await boot({user: 'alice', hash: 'team/' + RID}); d = w.document;
  await probe(w, 'team chat', `#tc-msgs .cmsg[data-mid="t:${MA}"]`, {target: '.cbub'});
  w.close();

  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  await probe(w, 'section head', '#view .ghead[data-section]');
  w.close();

  w = await boot({user: 'alice', hash: 'assigned'}); d = w.document;
  await probe(w, 'own section of My tasks', '#view .ghead.mosec:not(.msrec)');
  w.close();

  w = await boot({user: 'alice', hash: 'sheets'}); d = w.document;
  await probe(w, 'table cards', `#view .shvcard[data-id="${SH}"]`, {target: 'b'});
  w.close();

  w = await boot({user: 'alice', hash: 'bookmarks'}); d = w.document;
  await probe(w, 'bookmarks', `#view [data-id="${BM}"].bmcard, #view [data-id="${BM}"].bmrow`, {target: '.bmsite'});
  w.close();

  w = await boot({user: 'alice', hash: 'wiki/'}); d = w.document;
  await probe(w, 'knowledge', '#view .wkrow', {target: '.wkitem'});
  w.close();

  w = await boot({user: 'alice', hash: 'contacts'}); d = w.document;
  await probe(w, 'contacts', '#view .ctrow[data-ctopen]', {btn: false});
  w.eval('ctBooksModal()');
  await probe(w, 'dialog Address books', '#cb-body .evcrow', {target: '.evcn'});
  w.close();

  w = await boot({user: 'alice', hash: 'cal'}); d = w.document;
  check(await until(() => w.eval(`typeof evCalsModal === 'function'`)), 'the calendar module is loaded');
  w.eval('evCalsModal()');
  await probe(w, 'dialog Calendars', '.evcmodal .evcrow', {target: '.evcn'});
  w.close();

  check(!errs.length, 'no page errors ' + JSON.stringify(errs.slice(0, 3)));
  console.log(`p2695_a_longpress_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(1); });
