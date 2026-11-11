// 2.905.0 UI test, part A (#5255): undo across devices, stage 7 - the browser keeps no copies, the steps are the server's.
// kalmido-suite: fresh
// freelancer-matrix: undo (a person without an organisation: tick, Undo in the toast, Ctrl+Z, the list)
// jsdom, fresh container. Invented names only. Used like a person does it:
//  - tick a task off: the toast "… completed · Undo"; its button opens the task again (on the server, the row is open again)
//  - tick it again, Ctrl+Z (focus outside a field): open again; Ctrl+Shift+Z: done again; the arrow names the step
//  - the entry holds no copy and no function of its own, only the server's group (header X-Kalmido-Undo-Gid of the write)
//  - right-click on the arrow: "Recent steps" lists the step once ("This device"), no "only this device" twin
//  - a change made on another device of the same person (the API) is the newest step: Ctrl+Z here takes it back
//  - offline: a change still waiting in the outbox is taken out of the queue by Ctrl+Z (never sent)
//  - a list's type (a server step since #5476, recorded before its answer) goes back on the server, no second step
//  - a step of an area without server steps yet (a list's folder) still goes back as "only this device"
// The waits are on states (rows, values on the server, the toast), never on a fixed time.
const {boot, errs, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DEV = {'X-Kalmido-Device-Name': 'Laptop (Test)'};
const until = (fn, ms) => until0(fn, {timeout: ms || 20000, step: 100});
const call = async (ck, method, url, body, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...hd, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };

async function round(who, ck, tag) {
  const L = (await call(ck, 'POST', '/api/lists', {name: `Work ${tag}`})).id;
  const T = (await call(ck, 'POST', '/api/tasks', {title: `Pay invoice ${tag}`, list_id: L})).id;
  const get = () => call(ck, 'GET', `/api/tasks/${T}`);
  const w = await boot({user: who, hash: 'l/' + L}); const d = w.document;
  const idle = () => until(() => !w.eval('HIST.busy') && w.eval('OUT.q.length') === 0);
  const toastText = () => d.querySelector('#toast:not(.hidden)')?.textContent || '';
  const chk = () => d.querySelector(`#view .trow[data-id="${T}"] .chk`);
  const key = (k, o = {}) => d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, ctrlKey: true, bubbles: true, cancelable: true, ...o}));
  const btn = dir => d.querySelector(`#top [data-act="hist-${dir}"]`);

  // ---- tick off, the toast's Undo
  check(await until(() => chk()), `${tag}: the task row with its check box`);
  chk().click();
  check(await until(async () => (await get()).status === 2), `${tag}: ticked off on the server`);
  check(await until(() => /completed/i.test(toastText()) && d.querySelector('#toast:not(.hidden) button:not(.tx)')), `${tag}: the toast "… completed · Undo" (${toastText()})`);
  const e1 = w.eval('(() => { const e = HIST.undo.at(-1); return e ? {gids: histGids(e), snaps: e.snaps.length, after: e.after.length, fn: typeof e.undo, label: e.label} : null; })()');
  check(e1 && e1.gids.length === 1 && !e1.snaps && !e1.after && e1.fn === 'undefined', `${tag}: the entry holds only the server's group, no copy, no function ${JSON.stringify(e1)}`);
  d.querySelector('#toast:not(.hidden) button:not(.tx)').click();
  check(await until(async () => (await get()).status === 0), `${tag}: Undo in the toast opens it again on the server`);
  check(await until(() => chk() && !chk().classList.contains('on')), `${tag}: the row is open again`);
  check(await until(() => /Undone/.test(toastText())), `${tag}: "Undone: …" (${toastText()})`);
  await idle();

  // ---- tick again, Ctrl+Z, Ctrl+Shift+Z
  chk().click();
  check(await until(async () => (await get()).status === 2), `${tag}: ticked off again`);
  await idle();
  check(await until(() => /^Undo: Completed/.test(btn('undo').getAttribute('aria-label') || '')), `${tag}: the arrow names the step (${btn('undo').getAttribute('aria-label')})`);
  key('z');
  check(await until(async () => (await get()).status === 0), `${tag}: Ctrl+Z opens it again`);
  await idle();
  check(btn('redo') && !btn('redo').disabled && /^Redo: Completed/.test(btn('redo').getAttribute('aria-label') || ''), `${tag}: → offers the step again`);
  key('z', {shiftKey: true});
  check(await until(async () => (await get()).status === 2), `${tag}: Ctrl+Shift+Z: done again`);
  await idle();

  // ---- the list "Recent steps": the step once, of this device
  btn('undo').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  check(await until(() => [...d.querySelectorAll('#pop .ulbody .ulrow.ul-s')].some(r => /Pay invoice/.test(r.textContent) && /This device/.test(r.textContent))), `${tag}: the list shows the step of this device`);
  check(![...d.querySelectorAll('#pop .ulbody .ulrow.ul-l')].some(r => /Pay invoice/.test(r.textContent)), `${tag}: no second row "only this device"`);
  w.eval('closePop()');

  // ---- another device of the same person: its rename is the newest step, Ctrl+Z here takes it back
  const rn = await call(ck, 'PATCH', `/api/tasks/${T}`, {title: `Pay invoice ${tag} today`}, DEV);
  check(rn.http === 200, `${tag}: renamed on the other device (${rn.http})`);
  key('z');
  check(await until(async () => (await get()).title === `Pay invoice ${tag}`), `${tag}: Ctrl+Z takes the other device's newer step back`);
  check((await get()).status === 2, `${tag}: the older step (ticked off) stays`);
  await idle();

  // ---- offline: a change waiting in the outbox goes out of the queue
  w.__offline = true; w.eval('setOnline(false)');
  await w.eval(`patchUndoable(${T}, {priority: 5}, 'Priority')`);
  check(await until(() => w.eval('OUT.q.length') === 1), `${tag}: offline the change waits in the outbox`);
  key('z');
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('HIST.busy')), `${tag}: Ctrl+Z took it out of the queue`);
  w.__offline = false; await w.eval('flush()').catch(() => {});
  check((await get()).priority === 0, `${tag}: it never reached the server`);

  // ---- a list's type: since #5476 a step on the server; the entry takes the group of its answer (recorded before the answer,
  // dialogs.js listPatch -> undo.js histOwn) and goes back there - no second step that a later Ctrl+Z would take back
  const kindOf = async () => (await call(ck, 'GET', '/api/state')).lists.find(l => l.id === L)?.kind;
  await w.eval(`listPatch(${L}, {kind: 'project'}, 'Type of “Work ${tag}”: Project')`);
  check(await until(async () => await kindOf() === 'project'), `${tag}: the list became a project`);
  check(w.eval('(() => { const e = HIST.undo.at(-1); return !!e && histGids(e).length === 1; })()'), `${tag}: the type's entry holds the server's group`);
  key('z');
  check(await until(async () => await kindOf() === 'list'), `${tag}: Ctrl+Z took the list type back (on the server: lists.kind, undo_free)`);
  await idle();
  const top = ((await call(ck, 'GET', '/api/undo?limit=1')).items || [])[0];
  check(top && top.state === 'undone', `${tag}: no new step for the way back: ` + JSON.stringify(top));

  // ---- an area without server steps yet (a list's folder: not a plain setting): still back, as "only this device"
  const folderOf = async () => (await call(ck, 'GET', '/api/state')).lists.find(l => l.id === L)?.folder || '';
  await w.eval(`listPatch(${L}, {folder: 'Later ${tag}'}, 'Folder of “Work ${tag}”')`);
  check(await until(async () => await folderOf() === `Later ${tag}`), `${tag}: the list went into a folder`);
  check(w.eval('(() => { const e = HIST.undo.at(-1); return !!e && !histSrv(e) && typeof e.undo === "function"; })()'), `${tag}: its entry is this device's own`);
  key('z');
  check(await until(async () => await folderOf() === ''), `${tag}: Ctrl+Z took the folder back`);
  w.close();
}

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ALICE = (await call(CA, 'GET', '/api/state')).me.id;
  const ORG = (await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: ALICE})).id;
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${ORG}`});
  await round('alice', CA, 'Alpha');

  // a person without an organisation (freelancer parity)
  await call(CA, 'POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com', orgs: []});
  const CF = await login('fiona');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'private'});
  await round('fiona', CF, 'Frei');

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2905_a_undo_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
