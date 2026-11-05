// 2.477.0 (#3881) UI tests (jsdom), fresh DB: the quick note like Apple Notes
// - the key m (where it means nothing else) opens an empty note with the cursor in its one text field: no question for the
//   list, no title field; the first time it makes the private list "Notes" (a fixed row under the basket, not among the projects)
// - typing saves by itself, the first line is the title; left with text it stays
// - left empty: never on the server; typed and emptied again: gone for good (not in the trash)
// - "New note" in the command field and in the notes overview (no list filtered: the list "Notes", a filtered one: that one)
// - the phone: holding the Plus button opens a quick note, its end opens no task; a tap stays a new task
// - the list has no share button and the server refuses sharing it (PUT members = 409 quicknote_private)
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const type = (w, sel, v) => { const el = w.document.querySelector(sel); el.focus(); el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); return el; };
const key = (w, k) => { const ev = new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}); w.document.body.dispatchEvent(ev); return ev; };
const pe = (w, el, type) => {  // a touch pointer (jsdom: a MouseEvent with pointerType)
  const C = w.PointerEvent || w.MouseEvent, ev = new C(type, {bubbles: true, cancelable: true, clientX: 30, clientY: 30, button: 0});
  for (const [k, v] of [['pointerId', 1], ['pointerType', 'touch']]) if (ev[k] !== v) Object.defineProperty(ev, k, {value: v});
  el.dispatchEvent(ev); return ev;
};
const notesOf = async lid => (await call('GET', `/api/lists/${lid}/notes`)).notes || [];

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab'});
  const P = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const w = await boot({user: 'alice', hash: 'today'});
  const $ = s => w.document.querySelector(s);
  check(await until(() => w.eval('!!S.me && S.lists.length > 0') && !!$('#side')), 'setup: the app is up');
  check(!w.eval('qn_list()'), 'no list Notes before the first grip');

  // ================= key m: an empty note, cursor in the text, the list made by itself
  key(w, 'm');
  check(await until(() => w.eval('S.nt.id === QN_DRAFT') && !!$('#nt-body') && w.document.activeElement === $('#nt-body')), 'm: an empty note, the cursor in its text');
  check(!$('#nt-title') && $('#pop').classList.contains('hidden') && !$('.modal'), 'no title field, no question for the list');
  const Q = w.eval('qn_list()?.id');
  check(!!Q && w.eval(`listById(${Q}).quicknote`) === 1 && !w.eval(`listById(${Q}).org_id`), 'the private list Notes was made ' + Q);
  check((await notesOf(Q)).length === 0, 'nothing on the server yet');
  type(w, '#nt-body', 'Groceries\nmilk\nbread');
  check(await until(async () => (await notesOf(Q)).some(n => n.title === 'Groceries' && n.body === 'Groceries\nmilk\nbread')), 'saved by itself, the first line is the title');
  const N1 = (await notesOf(Q))[0]?.id;
  check(await until(() => w.location.hash === '#note/' + N1 && w.eval('S.nt.id') === N1), 'the address is the note now ' + w.location.hash);
  type(w, '#nt-body', 'Groceries\nmilk\nbread\neggs');
  check(await until(async () => (await notesOf(Q)).some(n => n.id === N1 && /eggs/.test(n.body))), 'typing on: saved into the same note');
  w.eval("go('today')");
  check(await until(() => w.eval("S.route.mod === 'tasks'")), 'left the note');
  check((await call('GET', '/api/notes/' + N1)).title === 'Groceries', 'left with text: it stays');

  // ================= 2.556.0 (#4665): no fixed row "Notes" under Plan any more (was a fixed row, #3881); the list is not among the projects either
  w.eval('renderSide()');
  check(!$('#side .srow.sqn') && !$(`#side [data-go="notes/${Q}"][data-qn]`) && !w.eval(`typeof qn_sideRow !== 'undefined'`), 'no fixed row Notes under Plan in the sidebar');
  check(!$(`#side .srow[data-list="${Q}"]`), '… not among the projects');
  check(w.eval(`shareOk(listById(${Q}))`) === false, 'no share button for the list Notes');
  const sh = await call('PUT', `/api/lists/${Q}/members`, {user_id: 1, role: 'edit'});
  check(sh.status === 409 && sh.code === 'quicknote_private', 'the server refuses to share it ' + JSON.stringify(sh));

  // ================= left empty: never on the server
  w.eval("palAll().find(x => x.id === 'a:newnote').fn()");
  check(await until(() => w.eval('S.nt.id === QN_DRAFT') && !!$('#nt-body')), 'command field "New note": an empty note');
  w.eval("go('today')");
  check(await until(() => w.eval("S.route.mod === 'tasks' && !S.nt.draft")), 'left empty: the draft is gone');
  check((await notesOf(Q)).length === 1, 'nothing reached the server');

  // ================= typed and emptied again: gone for good
  key(w, 'm');
  check(await until(() => w.eval('S.nt.id === QN_DRAFT') && !!$('#nt-body')), 'm again: a new note');
  type(w, '#nt-body', 'x');
  check(await until(async () => (await notesOf(Q)).length === 2), 'one character: the note is made');
  const N2 = (await notesOf(Q)).find(n => n.id !== N1)?.id;
  check(await until(() => w.eval('S.nt.id') === N2), 'it is the open note');
  type(w, '#nt-body', '');
  w.eval("go('today')");
  check(await until(async () => (await call('GET', '/api/notes/' + N2)).status === 404), 'emptied and left: gone for good');
  const tr = (await call('GET', `/api/lists/${Q}/notes?trash=1`)).notes || [];
  check(!tr.some(n => n.id === N2), 'not in the trash');
  check(!w.eval(`(S.notes || []).some(n => n.id === ${N2})`), 'not in the app either');

  // ================= the notes overview: no question
  w.eval("go('notes')");
  check(await until(() => !!$('[data-sb="note-new"]')), 'the notes overview');
  $('[data-sb="note-new"]').click();
  check(await until(() => w.eval(`S.nt.id === QN_DRAFT && S.nt.draft.list_id === ${Q}`)), 'overview without a filter: into the list Notes, no question');
  check($('#pop').classList.contains('hidden') && !$('.modal'), '… no list picker');
  w.eval("go('notes')");
  check(await until(() => w.eval("S.route.mod === 'notes' && !S.nt.lid && !S.nt.draft") && !!$('[data-sb="note-new"]')), 'back in the overview');
  w.eval(`S.sbn.lid = ${P}`);
  $('[data-sb="note-new"]').click();
  check(await until(() => w.eval(`S.nt.id === QN_DRAFT && S.nt.draft.list_id === ${P}`)), 'a list filtered: into that list');
  type(w, '#nt-body', 'Tulips in October\nand daffodils');
  check(await until(async () => (await notesOf(P)).some(n => n.title === 'Tulips in October')), 'saved in the filtered list, the first line the title');
  w.eval("go('today')");
  w.eval('S.sbn.lid = 0');

  // ================= the list Notes: Back from a note lands there
  key(w, 'm');
  check(await until(() => w.eval('S.nt.id === QN_DRAFT') && !!$('#nt-body')), 'm: a new note');
  $('[data-act="nt-close"]').click();
  check(await until(() => w.eval(`S.route.mod === 'notes' && S.nt.lid === ${Q} && !S.nt.id`) && !!$('.ntcards')), 'closed: the list Notes, newest first');
  check(!$('#nt-q'), 'the list Notes has no search field');

  // ================= the phone: hold the Plus button
  w.close();
  const m = await boot({user: 'alice', hash: 'today', mobile: true});
  const $m = s => m.document.querySelector(s);
  check(await until(() => m.eval('!!S.me && S.lists.length > 0') && !!$m('#fab')), 'phone: the app is up');
  const fab = $m('#fab');
  pe(m, fab, 'pointerdown'); pe(m, fab, 'pointerup'); fab.click();
  check(await until(() => !!$m('.qadd.sheet')), 'a tap on Plus: a new task as before');
  m.eval('closePop()');
  check(await until(() => !$m('.qadd.sheet')), 'the task sheet closed');
  pe(m, fab, 'pointerdown');
  check(await until(() => m.eval('S.nt.id === QN_DRAFT') && !!$m('#nt-body')), 'holding Plus: a quick note');
  pe(m, fab, 'pointerup'); fab.click();
  check(!$m('.qadd.sheet'), '… the end of the hold opens no task');
  check(m.eval(`S.nt.draft.list_id`) === Q, '… in the list Notes');
  type(m, '#nt-body', 'Call the plumber');
  check(await until(async () => (await notesOf(Q)).some(n => n.title === 'Call the plumber')), 'phone: saved, the first line the title');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  m.close();
  console.log(`p2477_quicknote_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
