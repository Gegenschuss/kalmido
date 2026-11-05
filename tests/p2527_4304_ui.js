// 2.527.0 (#4304) UI tests (jsdom), fresh DB: no typed or changed data gets lost offline or at the end of a session
// - A4: a conflict in the answer of /api/tasks/reorder or /api/tasks/batch (conflicts[{id, ...}], the answer has no id of its
//   own) belongs to that entry's task: the dialog names it, "Use mine" sends PATCH /api/tasks/<that id> (not /undefined)
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
// every request that leaves the window [method, path, body]; w.__offline = the network is gone
const stub = (w, fake) => { const calls = [], of = w.fetch; w.fetch = (u, o = {}) => { const m = (o.method || 'GET').toUpperCase(), p = new URL(String(u), B).pathname; if (w.__offline) return Promise.reject(new TypeError('Failed to fetch')); calls.push([m, p, o.body, !!o.keepalive]); const r = fake && fake(m, p, o); return r ? Promise.resolve(r) : of(u, o); }; return calls; };
const jres = (st, j) => new Response(JSON.stringify(j), {status: st, headers: {'content-type': 'application/json'}});
const clone = v => v === undefined ? v : JSON.parse(JSON.stringify(v));
// the wiki copy's store (window.__wkoStore, as tests/p2169_a_ui.js), shared by the windows of one browser
const wkoStore = () => { const db = new Map(); return {db, get: async k => clone(db.get(k)), put: async v => { db.set(v.k, clone(v)); }, del: async k => { db.delete(k); },
  all: async () => [...db.values()].map(clone), pre: async x => [...db.values()].filter(r => r.k.startsWith(x)).map(clone), clear: async () => { db.clear(); }, close: async () => {}}; };
const online = w => { w.__offline = false; w.eval('OUT.retryAt = 0'); w.dispatchEvent(new w.Event('online')); };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Cut the hedge', list_id: P})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Water the roses', list_id: P})).id;
  const w = await boot({user: 'alice', hash: 'l/' + P});
  check(await until(() => w.eval('S.booted') && w.eval('S.tasks.has(' + T1 + ')')), 'setup: the app is up');
  const calls = stub(w);

  // ================= A4: a conflict of /api/tasks/reorder sent from the queue
  w.__offline = true;
  await w.eval(`api('POST', '/api/tasks/reorder', {items: [{id: ${T1}, sort: 5, priority: 5, _prev: {priority: 0}}]})`);
  check(w.eval('OUT.q.length') === 1, 'A4: the reorder waits in the queue');
  await call('PATCH', '/api/tasks/' + T1, {priority: 3});  // meanwhile on another device
  online(w);
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'A4: the queue went through');
  let cf = w.eval('S.conflicts');
  check(cf.length === 1 && cf[0].tid === T1 && cf[0].field === 'priority' && cf[0].title === 'Cut the hedge', 'A4: the conflict names the task of its entry ' + JSON.stringify(cf));
  w.eval('conflictModal()');
  const md = await until(() => [...w.document.querySelectorAll('.modal')].find(x => x.querySelector('#cf-list .cfitem')));
  check(!!md && /Cut the hedge/.test(md.querySelector('#cf-list').textContent), 'A4: the dialog shows the task\'s title');
  calls.length = 0;
  md?.querySelector('[data-cf="mine"]')?.click();
  check(await until(() => calls.some(([m, p]) => m === 'PATCH' && p === '/api/tasks/' + T1)), 'A4: "Use mine" patches the right task ' + JSON.stringify(calls.map(c => c[0] + ' ' + c[1])));
  check(!calls.some(([, p]) => /undefined|null/.test(p)), 'A4: never PATCH /api/tasks/undefined');
  check(await until(async () => (await call('GET', '/api/tasks/' + T1)).priority === 5), 'A4: the server has my priority');
  // the resolved conflict leaves the list (a real state to wait for: the next case counts the entries)
  check(await until(() => w.eval('S.conflicts.length') === 0), 'A4: "Use mine" resolved the conflict ' + JSON.stringify(w.eval('S.conflicts')));
  md?.remove();

  // ================= A4: a batch answer with entries of two tasks (as the service worker hands it over: swres)
  w.eval(`addConflicts(undefined, [{id: ${T1}, title: 'Cut the hedge', field: 'due', server: '2026-11-10', mine: '2026-11-12'}, {id: ${T2}, title: 'Water the roses', field: 'due', server: null, mine: '2026-11-13'}], undefined)`);
  cf = w.eval('S.conflicts');
  check(cf.length === 2 && cf.some(c => c.tid === T1 && c.title === 'Cut the hedge') && cf.some(c => c.tid === T2 && c.title === 'Water the roses'), 'A4: two tasks of one batch, each its own entry ' + JSON.stringify(cf));
  // a PATCH of one task (no id per entry) keeps the id it was given
  w.eval(`addConflicts(${T2}, [{field: 'title', server: 'Water the roses', mine: 'Water all roses'}], 'Water the roses')`);
  check(w.eval('S.conflicts').some(c => c.tid === T2 && c.field === 'title'), 'A4: a single PATCH conflict keeps its task id');
  w.eval("S.conflicts = []; LS.set('conflicts', [])");

  w.close();

  // ================= A2 + A18: the knowledge page (a person without an organisation)
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  const stf = await call('GET', '/api/state', null, CF);
  check(!(stf.me.workspaces || []).length, 'setup: frida has no organisation');
  const feats = [...new Set([...(stf.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {look: '{"wkEd":"text"}', tour: 'done', lang: 'en', features: feats}, CF);
  const W1 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Notes/Plan', body: 'Old plan'}, CF)).id;
  const store = wkoStore(), wopt = {user: 'frida', hash: 'wiki/' + W1, shared: {store: {}, wins: []}, setup: x => { x.__wkoStore = store; }, ls: {'tasks.wkSpace': JSON.stringify('private')}};
  const edit = async (ww, text) => {
    // 2.554.0 (#4052): a computer writes at once (no Read / Edit switch; jsdom has no layout for CodeMirror: the plain field)
    const ta = await until(() => ww.document.querySelector('#wk-body'));
    ta.value = text; ta.dispatchEvent(new ww.Event('input', {bubbles: true}));
    return ta;
  };
  // review (#4304): a closed tab fires visibilitychange (hidden) before pagehide, as a browser does
  const tabClose = ww => { Object.defineProperty(ww.document, 'hidden', {value: true, configurable: true}); ww.document.dispatchEvent(new ww.Event('visibilitychange')); ww.dispatchEvent(new ww.Event('pagehide')); };
  let ww = await boot(wopt);
  check(await until(() => ww.eval(`WK.pg?.id === ${W1}`)), 'A2: the page is open');
  let wc = stub(ww);
  await edit(ww, 'Plan typed in the last second');
  tabClose(ww);
  // right away, without waiting: the queue has it and it went out with keepalive (the page is gone a moment later)
  const qn = ww.eval(`JSON.stringify(OUT.q.filter(x => x.url === '/api/wiki/pages/${W1}'))`);
  check(/Plan typed in the last second/.test(qn), 'A2: pagehide: the text is in the queue at once ' + qn);
  const ka = wc.filter(([m, p, , k]) => m === 'PATCH' && p === '/api/wiki/pages/' + W1 && k);
  check(ka.length === 1 && /Plan typed in the last second/.test(ka[0][2] || ''), 'A2: pagehide: sent with keepalive ' + JSON.stringify(wc.map(c => c[0] + ' ' + c[1] + (c[3] ? ' keepalive' : ''))));
  check(await until(async () => (await call('GET', '/api/wiki/pages/' + W1, null, CF)).body === 'Plan typed in the last second'), 'A2: the server has the text');
  ww.close();
  // the queued copy goes at the next start under the same key: applied once, nothing in the conflicts dialog
  ww = await boot(wopt);
  check(await until(() => ww.eval('OUT.q.length') === 0 && !ww.eval('OUT.flushing'), {timeout: 20000}), 'A2: the queued copy went at the next start');
  check((await call('GET', '/api/wiki/pages/' + W1, null, CF)).body === 'Plan typed in the last second' && !ww.eval('S.conflicts.length') && !store.db.has('x:' + W1), 'A2: applied once, no conflict');

  // an encrypted space (the lock stood in for: the cipher is a marked text): the pagehide takes the cipher made while typing
  check(await until(() => ww.eval(`WK.pg?.id === ${W1}`)), 'A2 e2e: the page is open');
  ww.eval(`window.__wke = [wkeOn, wkeReady, wkeSeal]; wkeOn = sp => sp === 'private'; wkeReady = sp => sp === 'private'; wkeSeal = async (sp, b) => ({...b, body: b.body == null ? b.body : 'SEALED[' + b.body.split('').reverse().join('') + ']'}); 1`);
  wc = stub(ww);
  await edit(ww, 'Secret plan');
  check(await until(() => ww.eval('WK.seal?.plain') === 'Secret plan'), 'A2 e2e: the cipher is made while typing');
  tabClose(ww);
  const qe = ww.eval(`JSON.stringify(OUT.q.filter(x => x.url === '/api/wiki/pages/${W1}'))`);
  check(/SEALED\[nalp terceS\]/.test(qe), 'A2 e2e: pagehide: the cipher is in the queue at once ' + qe);
  const kae = wc.filter(([m, p, , k]) => m === 'PATCH' && p === '/api/wiki/pages/' + W1 && k);
  check(kae.length === 1 && /SEALED/.test(kae[0][2] || ''), 'A2 e2e: pagehide: the cipher went with keepalive');
  check(!wc.some(([, , b]) => /Secret plan/.test(b || '')) && !/Secret plan/.test(JSON.stringify(ww.__store)), 'A2 e2e: the text in clear never left the page nor went into storage');
  // review (#4304): a cipher older than the last save is never sent (it would put the page back to an older text)
  wc.length = 0;
  ww.eval(`WK.seal = {id: ${W1}, plain: 'Secret pl', c: 'SEALED[lp terceS]', seq: 1}; WK.savedSeq = 2; WK.seq = 3; WK.dirty = true; WK.pg.body = 'Secret plan'; document.querySelector('#wk-body').value = 'Secret plan!'; wk_stash(); 1`);
  check(!wc.some(([m, p, b, k]) => m === 'PATCH' && k && /SEALED\[lp terceS\]/.test(b || '')) && !/SEALED\[lp terceS\]/.test(ww.eval('JSON.stringify(OUT.q)')), 'A2 e2e: a cipher older than the last save is not sent ' + JSON.stringify(wc));
  ww.close();

  // ================= A18: a text the server refuses (413) waits at the page as a draft
  ww = await boot(wopt);
  check(await until(() => ww.eval(`WK.pg?.id === ${W1}`) && ww.eval('OUT.q.length') === 0 && !ww.eval('OUT.flushing'), {timeout: 20000}), 'A18: the page is open');
  wc = stub(ww, (m, p) => m === 'PATCH' && p === '/api/wiki/pages/' + W1 ? jres(413, {error: 'Text too large'}) : null);
  await edit(ww, 'A very long plan');
  await ww.eval('wk_flush()');
  check(wc.some(([m, p]) => m === 'PATCH' && p === '/api/wiki/pages/' + W1), 'A18: the save was tried');
  const dr = await until(() => store.db.get('x:' + W1));
  check(dr && dr.mine === 'A very long plan' && /too large/i.test(dr.why || ''), 'A18: the refused text is kept as a draft of the page ' + JSON.stringify(dr));
  // the page opened again (a reload keeps the sign-in; a boot here would be a new sign-in, which empties the copy on purpose):
  // the draft comes from the copy's store, not from memory
  ww.eval(`WKO.cf = {}; WK.edit = false; WK.dirty = false; 1`);
  await ww.eval(`wk_loadPage(${W1}, true)`);
  check(ww.eval(`WKO.cf[${W1}]?.mine`) === 'A very long plan', 'A18: opened again, the draft is read from the copy');
  if (!ww.document.querySelector('#view .wkocf')) ww.eval('renderView(); 1');
  const bar = await until(() => ww.document.querySelector('#view .wkocf'), {timeout: 20000});
  check(bar && /not saved \(Text too large\)/.test(bar.textContent) && bar.querySelector('[data-wk="cfshow"]'), 'A18: the page shows the draft with Compare ' + (bar?.textContent || ''));
  ww.close();

  // ================= A20: the account switch keeps the conflict copies as a download
  const bob = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const asked = [], blobs = [], names = [];
  const cfl = [{tid: T1, title: 'Cut the hedge', field: 'title', server: 'Cut the hedge', mine: 'Cut the hedge on Friday', at: Date.now()}];
  const ent = [{method: 'PATCH', url: `/api/tasks/${T2}`, body: {title: 'Water the roses twice'}, uid: bob, k: 'bobk1'}];
  const wb = await boot({user: 'alice', hash: 'l/' + P, ls: {'tasks.uid': String(bob), 'tasks.outbox': JSON.stringify(ent), 'tasks.conflicts': JSON.stringify(cfl)},
    setup: x => { x.confirm = t => { asked.push(t); return true; }; const OB = x.Blob; x.Blob = class extends OB { constructor(parts, o) { super(parts, o); this.__txt = (parts || []).join(''); } }; x.URL.createObjectURL = b => { blobs.push(b); return 'blob:x'; }; x.URL.revokeObjectURL = () => {}; x.HTMLAnchorElement.prototype.click = function () { if (this.download) names.push(this.download); }; }});
  check(await until(() => asked.length > 0), 'A20: another account: asked first');
  check(/downloaded as a text file/.test(asked.join(' ')), 'A20: the question says a copy is downloaded ' + asked[0]);
  check(await until(() => names.length > 0), 'A20: "Delete and continue" downloads a file ' + JSON.stringify(names));
  check(/^kalmido-conflicts-\d{4}-\d{2}-\d{2}\.txt$/.test(names[0] || ''), 'A20: named kalmido-conflicts-<date>.txt ' + names[0]);
  const txt = blobs[0]?.__txt || '';
  check(/Cut the hedge on Friday/.test(txt) && /Water the roses twice/.test(txt), 'A20: the file holds the conflict copy and the waiting change ' + JSON.stringify(txt.slice(0, 300)));
  check(await until(() => !/Cut the hedge on Friday/.test(wb.__store['tasks.conflicts'] || '')), 'A20: then the local data of the previous account goes as before');
  wb.close();

  // ================= A5: the session ends while the client dialog / a comment waits (a person without an organisation)
  const featsC = [...new Set([...feats.split(','), 'clients', 'comments', 'collab'])].join(',');
  await call('PATCH', '/api/settings', {features: featsC}, CF);
  const CL = (await call('POST', '/api/clients', {name: 'Acme Testkunde'}, CF)).id;
  const FP = (await call('POST', '/api/lists', {name: 'Calls'}, CF)).id;
  const FT = (await call('POST', '/api/tasks', {title: 'Call Acme', list_id: FP}, CF)).id;
  check(CL && FT, 'A5 setup: a client and a task');
  const sh = {store: {}, wins: []}, fopt = h => ({user: 'frida', hash: h, shared: sh});
  const gone = (ww, re) => stub(ww, (m, p) => re.test(m + ' ' + p) ? jres(401, {error: 'Not signed in'}) : null);
  let wf = await boot(fopt('clients'));
  const fid = wf.eval('S.me.id');
  // review (#4304): a 401 at the start (S.me not there yet) still finds the kept input of this browser's account (uid)
  check(wf.eval(`(() => { const me = S.me; LS.set('uid', me.id); fdKeep('fdf', 'probe', {x: 1}); S.me = null; const r = fdAny(); S.me = me; fdDrop('fdf', 'probe'); return r; })()`) === true, 'A5: before /api/me answered, the kept input of the account is found (not wiped)');
  wf.eval(`clientModal(${JSON.stringify(await call('GET', '/api/clients/' + CL, null, CF))})`);
  let cmd = await until(() => wf.document.querySelector('.modal.cldlg'));
  const note = cmd?.querySelector('#cl-note');
  note.value = 'Call back on Monday'; note.dispatchEvent(new wf.Event('input', {bubbles: true}));
  check(await until(() => /Call back on Monday/.test(wf.__store[`tasks.fdf.${fid}.cl.${CL}`] || '')), 'A5 client: the input is kept while typing ' + Object.keys(wf.__store).filter(k => /fdf/.test(k)));
  gone(wf, /^PATCH \/api\/clients\//);
  cmd.querySelector('[data-m="save"]')?.click();
  await new Promise(r => setTimeout(r, 1500));  // the save met the ended session (401: authGone, then the reload)
  check((await call('GET', '/api/clients/' + CL, null, CF)).note !== 'Call back on Monday', 'A5 client: the server did not get it');
  check(/Call back on Monday/.test(wf.__store[`tasks.fdf.${fid}.cl.${CL}`] || ''), 'A5 client: the ended session kept the input (not wiped with the local data)');
  wf.dispatchEvent(new wf.Event('pagehide'));  // the reload to the sign-in page
  wf.close();
  check(/Call back on Monday/.test(sh.store[`tasks.fdf.${fid}.cl.${CL}`] || wf.__store[`tasks.fdf.${fid}.cl.${CL}`] || ''), 'A5 client: still kept after the page went');
  wf = await boot(fopt('clients'));  // signed in again, the page loads anew
  wf.eval(`clientModal(${JSON.stringify(await call('GET', '/api/clients/' + CL, null, CF))})`);
  cmd = await until(() => wf.document.querySelector('.modal.cldlg'));
  check(cmd?.querySelector('#cl-note')?.value === 'Call back on Monday', 'A5 client: the dialog opened again has the input back');
  cmd?.querySelector('[data-m="save"]')?.click();
  check(await until(async () => (await call('GET', '/api/clients/' + CL, null, CF)).note === 'Call back on Monday'), 'A5 client: saved now');
  check(await until(() => !wf.__store[`tasks.fdf.${fid}.cl.${CL}`]), 'A5 client: saved = the kept input is gone');
  wf.close();

  // the comment box
  wf = await boot(fopt('t/' + FT));
  let ci = await until(() => wf.document.querySelector('#c-input'));
  check(!!ci, 'A5 comment: the comment box is there');
  ci.value = 'Asked for the offer'; ci.dispatchEvent(new wf.Event('input', {bubbles: true}));
  check(/Asked for the offer/.test(wf.__store[`tasks.fdc.${fid}.${FT}`] || ''), 'A5 comment: kept while typing');
  gone(wf, /^POST \/api\/tasks\/\d+\/comments$/);
  await wf.eval('sendComment()').catch(() => {});
  await new Promise(r => setTimeout(r, 1500));
  check(/Asked for the offer/.test(wf.__store[`tasks.fdc.${fid}.${FT}`] || ''), 'A5 comment: the ended session kept it');
  wf.close();
  wf = await boot(fopt('t/' + FT));
  ci = await until(() => wf.document.querySelector('#c-input'));
  check(ci?.value === 'Asked for the offer', 'A5 comment: after the sign-in the box has it back ' + JSON.stringify(ci?.value));
  await wf.eval('sendComment()');
  check(await until(async () => ((await call('GET', `/api/tasks/${FT}/timeline`, null, CF)).comments || []).some(c => /Asked for the offer/.test(c.body))), 'A5 comment: sent now');
  check(!wf.__store[`tasks.fdc.${fid}.${FT}`], 'A5 comment: sent = the kept text is gone');

  // A6: a kept write (the list dialog's / the settings' pagehide) goes at the next start, once
  wf.eval(`fdWrite('PATCH', '/api/lists/${FP}', {name: 'Calls this week', _prev: {name: 'Calls'}}, {slot: 'list.${FP}', send: false}); 1`);
  check(!!wf.__store[`tasks.fdw.${fid}.list.${FP}`], 'A6: the write is kept');
  await wf.eval('fdWriteFlush()');
  check((await call('GET', '/api/state', null, CF)).lists.find(l => l.id === FP)?.name === 'Calls this week' && !wf.__store[`tasks.fdw.${fid}.list.${FP}`], 'A6: sent at the next start and then gone');
  wf.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2527_4304_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
