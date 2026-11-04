// 2.536.0 (#4567) UI tests (jsdom), fresh DB: a note's change goes into the outbox at once, online too
// kalmido-suite: fresh
// - typing with a slow server: "Saved" at once (the server still holds the request), the server gets it in the background,
//   after a reload the text is there
// - a new note and the pin: drawn at once with the server still busy, then on the server (the temporary id swapped)
// - a 409 of a change sent from the queue opens the note's own conflict dialog (both versions), the change still waiting
//   behind it is folded in (one dialog), "Keep mine" saves mine; nothing lands as "rejected" in the conflicts list
// - a locked list's note never waits in the queue: nothing in localStorage, straight to the server as before
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const type = (w, sel, v) => { const el = w.document.querySelector(sel); el.focus(); el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); return el; };
// a slow server: writes to notes wait in w.__held until release (reads go on)
const hold = w => {
  w.__held = []; w.__holdOn = true; const f0 = w.fetch;
  w.fetch = (u, o = {}) => w.__holdOn && /\/api\/(notes\/\d+|lists\/\d+\/notes)$/.test(String(u)) && (o.method || 'GET') !== 'GET'
    ? new Promise((res, rej) => w.__held.push(() => f0(u, o).then(res, rej))) : f0(u, o);
};
const release = w => { w.__holdOn = false; for (const go of w.__held.splice(0)) go(); };
const saved = w => (w.document.querySelector('#nt-saved')?.textContent || '') === 'Saved';
// noteFlush while the server holds the request: what the note says the moment it returned ('timeout' = it waited for the server)
const flushSays = w => Promise.race([w.eval(`noteFlush().then(() => document.querySelector('#nt-saved')?.textContent || '')`), new Promise(ok => setTimeout(ok, 3000, 'timeout'))]);
const openEdit = async (w, id) => {
  w.location.hash = '#note/' + id;
  check(await until(() => w.eval(`S.nt.id === ${id}`) && !!w.document.querySelector('#nt-title')), 'the note is open ' + id);
  w.document.querySelector('[data-act="nt-mode"][data-m="edit"]')?.click();
  check(!!await until(() => w.document.querySelector('#nt-body')), '… in edit mode');
};

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab'});
  const P = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const N1 = await call('POST', `/api/lists/${P}/notes`, {title: 'Briefing', body: 'Start'});
  let w = await boot({user: 'alice', hash: 'notes/' + P});
  check(await until(() => w.eval('!!S.me && S.lists.length > 0')), 'setup: the app is up');

  // ================= typing with a slow server: "Saved" at once
  await openEdit(w, N1.id);
  hold(w);
  type(w, '#nt-body', 'Typed on a slow line');
  const said = await flushSays(w);
  check(said === 'Saved', 'slow server: "Saved" at once ' + said);
  check(await until(() => w.__held.length === 1), 'the request is on its way, held by the server ' + w.__held.length);
  check((await call('GET', `/api/notes/${N1.id}`)).body === 'Start', '… the server has the old text still');
  check(w.eval('OUT.q.length') === 1 && w.eval('OUT.q[0].url') === `/api/notes/${N1.id}`, 'the change waits in the queue');
  check(!/offline/i.test(w.document.querySelector('#nt-saved')?.textContent || ''), 'no offline hint while online');
  release(w);
  check(await until(async () => (await call('GET', `/api/notes/${N1.id}`)).body === 'Typed on a slow line' && w.eval('OUT.q.length') === 0), 'in the background: on the server, the queue empty');

  // ================= the pin: at once
  hold(w);
  w.document.querySelector('[data-act="nt-pin"]').click();
  check(await until(() => w.eval(`S.nt.notes.find(n => n.id === ${N1.id}).pinned`) === true && w.document.querySelector('[data-act="nt-pin"]')?.classList.contains('on')), 'pin: drawn at once');
  check((await call('GET', `/api/notes/${N1.id}`)).pinned === false, '… the server not yet');
  release(w);
  check(await until(async () => (await call('GET', `/api/notes/${N1.id}`)).pinned === true && w.eval('OUT.q.length') === 0), 'pin: on the server');

  // ================= a new note: at once, its temporary id swapped
  hold(w);
  w.document.querySelector('[data-act="nt-new"]').click();
  check(await until(() => w.eval('S.nt.id') < 0 && !!w.document.querySelector('#nt-title')), 'new note: open at once with a temporary id ' + w.eval('S.nt.id'));
  type(w, '#nt-title', 'Plan B');
  const said2 = await flushSays(w);
  check(said2 === 'Saved', 'new note: "Saved" at once ' + said2);
  release(w);
  const nb = async () => ((await call('GET', `/api/lists/${P}/notes`)).notes || []).filter(n => n.title === 'Plan B');
  check(await until(async () => (await nb()).length === 1 && w.eval('OUT.q.length') === 0), 'new note: once on the server with its title');
  const NB = (await nb())[0]?.id;
  check(await until(() => w.eval('S.nt.id') === NB && w.location.hash === '#note/' + NB), 'the open note has its real id ' + w.location.hash);
  w.close();

  // ================= after a reload: the text from the server
  w = await boot({user: 'alice', hash: 'note/' + N1.id});
  check(await until(() => w.eval(`(S.nt.notes || []).find(n => n.id === ${N1.id})?.body`) === 'Typed on a slow line' && /Typed on a slow line/.test(w.document.querySelector('#nt-md')?.textContent || '')), 'reloaded: the text is there');

  // ================= a 409 from the queue: the note's own dialog, the later change folded in
  const N3 = await call('POST', `/api/lists/${P}/notes`, {title: 'Agenda', body: 'Old'});
  await w.eval('load()'); await w.eval('loadNotes(S.nt.lid)');
  await openEdit(w, N3.id);
  await call('PATCH', `/api/notes/${N3.id}`, {body: 'Changed elsewhere'});
  w.__dialogs = 'manual';
  hold(w);
  type(w, '#nt-body', 'Mine one');
  w.eval('noteFlush()');
  check(await until(() => w.__held.length === 1), 'the first change is on its way');
  type(w, '#nt-body', 'Mine one two');
  w.eval('noteFlush()');
  check(await until(() => w.eval('OUT.q.length') === 2), 'a second change waits behind it');
  release(w);
  const cd = await until(() => [...w.document.querySelectorAll('.modal.cdlg')].pop());
  check(cd && /Changed in the meantime/.test(cd.textContent) && cd.textContent.includes('Changed elsewhere') && cd.textContent.includes('Mine one two'), '409 from the queue: the dialog with both versions (the later text folded in)');
  check(w.document.querySelectorAll('.modal.cdlg').length === 1, '… one dialog only');
  check(!w.eval("(S.conflicts || []).some(c => c.field === 'rejected')"), '… not as "rejected" in the conflicts list');
  check(await until(() => w.eval('OUT.q.length') === 0), '… the waiting change left the queue');
  cd.querySelector('[data-cd="yes"]').click();
  check(await until(async () => (await call('GET', `/api/notes/${N3.id}`)).body === 'Mine one two' && w.eval('OUT.q.length') === 0), '"Keep mine" saves mine');
  w.__dialogs = undefined;

  // ================= a locked list: never in the queue, nothing in localStorage
  const L2 = (await call('POST', '/api/lists', {name: 'Safe box'})).id;
  const N4 = await call('POST', `/api/lists/${L2}/notes`, {title: 'Locked', body: 'Inside'});
  await w.eval(`load()`);
  // the server of this suite has no lock set up: the list is marked locked in the page, its texts leave as they are
  w.eval(`le2eOut = (m, u, b) => b; { const fix = j => { for (const l of j.lists || []) if (l.id === ${L2}) l.e2e = 'on'; }; fix({lists: S.lists}); const as0 = applyState; applyState = j => { fix(j); return as0(j); }; } 1`);
  check(w.eval(`ntLocked(${L2})`) === true, 'the list counts as locked');
  await openEdit(w, N4.id);
  hold(w);
  const MK = 'Zq7secretmarker';
  type(w, '#nt-body', 'Inside ' + MK);
  w.eval('noteFlush()');
  check(await until(() => w.__held.length === 1), 'locked: the change goes straight to the server');
  check(w.eval('OUT.q.length') === 0, 'locked: nothing in the queue');
  const inLs = () => w.eval(`Object.keys(localStorage).filter(k => (localStorage.getItem(k) || '').includes('${MK}')).join(',')`);
  check(inLs() === '', 'locked: the text in no localStorage entry ' + inLs());
  release(w);
  check(await until(async () => (await call('GET', `/api/notes/${N4.id}`)).body === 'Inside ' + MK), 'locked: on the server');
  check(await until(() => saved(w)), 'locked: "Saved" after the answer');
  w.document.querySelector('[data-act="nt-new"]').click();
  check(await until(() => w.eval('S.nt.id') > 0 && w.eval('S.nt.lid') === L2), 'locked: a new note straight from the server (no temporary id) ' + w.eval('S.nt.id'));
  check(w.eval('OUT.q.length') === 0 && inLs() === '', 'locked: still nothing waiting, nothing kept');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`p2536_notequeue_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
