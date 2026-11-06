// 2.551.0 (#4607) UI tests (jsdom), fresh DB: the menu of a note card
// - computer: a right click on a note card (a project's notes and the overview of all notes) opens that note's menu:
//   Open, Pin / Unpin, Copy link, Move to project…, Delete (the menu items by their data-act anchor, #4599)
// - the open note's "…" is the same menu without Open and Pin (its head has the pin button)
// - phone: a long press on a card opens the sheet with the note's title on top; the click ending the press does not open the note
// - a viewer's card: only Open and Copy link
// kalmido-suite: fresh
const {boot, errs, B, login, until, undoToast} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const rclick = (w, el) => { const ev = new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true, button: 2}); el.dispatchEvent(ev); return ev; };
const pe = (w, el, type) => {  // a touch pointer (jsdom: a MouseEvent with pointerType)
  const C = w.PointerEvent || w.MouseEvent, ev = new C(type, {bubbles: true, cancelable: true, clientX: 30, clientY: 30, button: 0});
  for (const [k, v] of [['pointerId', 1], ['pointerType', 'touch']]) if (ev[k] !== v) Object.defineProperty(ev, k, {value: v});
  el.dispatchEvent(ev); return ev;
};
const menuOpen = w => { const p = w.document.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menu"]') ? p : null; };
const acts = w => [...(menuOpen(w)?.querySelectorAll('[role="menuitem"][data-act]') || [])].map(b => b.dataset.act);
const pick = (w, act) => { const b = menuOpen(w)?.querySelector(`[data-act="${act}"]`); b?.click(); return !!b; };
const card = (w, id) => w.document.querySelector(`#view a.ntcard[href="#note/${id}"], #side a.ntcard[href="#note/${id}"]`);  // 2.602.0 (#4817): on a computer the cards are in the panel

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab'});
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id, L2 = (await call('POST', '/api/lists', {name: 'House'})).id;
  const N1 = (await call('POST', `/api/lists/${L}/notes`, {title: 'Seeds', body: 'tomatoes'})).id;
  const N2 = (await call('POST', `/api/lists/${L}/notes`, {title: 'Tools', body: 'spade'})).id;
  check(N1 && N2, 'setup: two notes ' + N1 + ' ' + N2);

  // ================= computer: a right click on a card of the project's notes
  let w = await boot({user: 'alice', hash: 'notes/' + L});
  check(await until(() => card(w, N1) && card(w, N2)), 'the project notes show both cards');
  const ev = rclick(w, card(w, N1));
  check(ev.defaultPrevented && await until(() => menuOpen(w)), 'right click: a menu, not the browser menu');
  check(['m-open', 'm-pin', 'm-copy-link', 'm-move', 'm-delete'].every(a => acts(w).includes(a)), 'the menu: open, pin, copy link, move, delete ' + acts(w));
  { const t = menuOpen(w).querySelector('[data-act="m-pin"]')?.textContent || ''; check(/Pin/.test(t) && !/Unpin/.test(t), 'not pinned: "Pin" ' + t); }
  pick(w, 'm-pin');
  check(await until(async () => (await call('GET', `/api/notes/${N1}`)).pinned === true), 'Pin: the note is pinned on the server');
  check(await until(() => card(w, N1)?.querySelector('.ntpin')), 'the card shows the pin');
  rclick(w, card(w, N1));
  check(await until(() => menuOpen(w)) && /Unpin/.test(menuOpen(w).querySelector('[data-act="m-pin"]')?.textContent || ''), 'pinned: "Unpin"');
  pick(w, 'm-open');
  check(await until(() => w.location.hash === '#note/' + N1 && w.eval('S.nt.id') === N1 && w.document.querySelector('#nt-title')), 'Open: the note opens ' + w.location.hash);

  // the open note's "…": the same menu, without Open / Pin (its head has the pin)
  w.document.querySelector('[data-act="nt-menu"]').click();
  check(await until(() => menuOpen(w)), "the open note's … opens its menu");
  check(acts(w).includes('m-delete') && acts(w).includes('m-copy-link') && !acts(w).includes('m-open') && !acts(w).includes('m-pin'), 'open note: delete, copy link, no open / pin ' + acts(w));
  w.eval('closePop()');

  // a right click on another card while one note is open: Delete there leaves the open note open
  rclick(w, card(w, N2));
  check(await until(() => menuOpen(w)), 'right click on the other card');
  pick(w, 'm-delete');
  check(await until(async () => (await call('GET', `/api/notes/${N2}`)).status === 404), 'Delete from the card: gone on the server');
  check(await until(() => !card(w, N2)) && w.location.hash === '#note/' + N1, 'its card is gone, the open note stays open ' + w.location.hash);
  check(await undoToast(w, /Note deleted/), 'Undo in the toast');
  check(await until(async () => (await call('GET', `/api/notes/${N2}`)).title === 'Tools'), 'Undo: the note is back');
  check(await until(() => card(w, N2)), 'its card is back');
  w.close();

  // ================= computer: the overview of all notes
  w = await boot({user: 'alice', hash: 'notes'});
  check(await until(() => card(w, N2)?.classList.contains('sbncard')), 'the overview shows the cards');
  rclick(w, card(w, N2));
  check(await until(() => menuOpen(w)) && acts(w).includes('m-move'), 'overview: right click opens the same menu ' + acts(w));
  pick(w, 'm-move');
  const pl = await until(() => [...w.document.querySelectorAll('#pop [role="menuitem"], #pop button')].find(b => /House/.test(b.textContent)));
  check(pl, 'Move: the project picker offers House');
  pl?.click();
  check(await until(async () => (await call('GET', `/api/notes/${N2}`)).list_id === L2), 'Move: the note is in House now');
  check(w.location.hash === '#notes', 'the overview stays ' + w.location.hash);
  w.close();

  // ================= phone: a long press opens the sheet, the click ending it does not open the note
  w = await boot({user: 'alice', hash: 'notes/' + L, mobile: true});
  check(await until(() => card(w, N1)), 'phone: the card');
  const c = card(w, N1);
  pe(w, c, 'pointerdown');
  check(await until(() => menuOpen(w)), 'phone: a long press opens the menu');
  check(/Seeds/.test(w.document.querySelector('#pop .tch-sht')?.textContent || ''), "phone: the sheet's head is the note's title " + w.document.querySelector('#pop .tch-sht')?.textContent);
  check(acts(w).includes('m-open') && acts(w).includes('m-delete'), 'phone: the same items ' + acts(w));
  pe(w, c, 'pointerup');
  const ck = new w.MouseEvent('click', {bubbles: true, cancelable: true, detail: 1}); c.dispatchEvent(ck);
  check(ck.defaultPrevented && w.location.hash === '#notes/' + L && !w.eval('S.nt.id'), 'phone: the click ending the press does not open the note ' + w.location.hash);
  check(menuOpen(w), 'phone: the sheet stays open');
  w.eval('closePop()');
  w.close();

  // ================= a viewer: only Open and Copy link
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  check(BOB, 'setup: Bob');
  {
    await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'view'});
    const CB = await login('bob');
    await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab'}, CB);
    w = await boot({user: 'bob', hash: 'notes/' + L});
    check(await until(() => card(w, N1)), 'viewer: the card');
    rclick(w, card(w, N1));
    check(await until(() => menuOpen(w)) && acts(w).sort().join() === 'm-copy-link,m-open', 'viewer: only open and copy link ' + acts(w));
    w.close();
  }

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2551_c_notemenu_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
