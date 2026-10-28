// 2.359.0 A (#3024) UI tests (jsdom), fresh DB: typed text is not lost between two saves
// - a task title typed and the page goes away right after (pagehide): the text waits in the offline queue at once and goes out
//   with keepalive under the same key; the queued copy sent later changes nothing twice and raises no conflict
// - the session ends (401) in the middle of a save, and while other typed text still waits: both are in the queue before the
//   reload and the local data is kept; sent after the next sign-in of the same account
// - a save that fails (500): the field says "Not saved yet", the text goes again later, the mark goes once it is saved
// - notes, the diary and the settings send their typed text with keepalive when the page goes (the diary and notes also queue it)
// - the automatic reload for a new version waits for a draft kept only in memory (S.drafts)
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const jres = (st, j) => new Response(JSON.stringify(j), {status: st, headers: {'content-type': 'application/json'}});
// every request that leaves the window {m, p, keep, key, body}; fake(m, p) may answer instead of the server
const stub = (w, fake) => { const calls = [], of = w.fetch; w.fetch = (u, o = {}) => { const m = (o.method || 'GET').toUpperCase(), p = new URL(String(u), B).pathname;
  if (w.__offline) return of(u, o);
  calls.push({m, p, keep: !!o.keepalive, key: (o.headers || {})['Idempotency-Key'] || '', body: typeof o.body === 'string' ? o.body : ''});
  const r = fake && fake(m, p); return r ? Promise.resolve(r) : of(u, o); }; return calls; };
const type = (w, sel, v) => { const el = w.document.querySelector(sel); el.focus(); el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); return el; };
const queued = (w, re) => w.eval('outSync()').filter(x => re.test(x.url));

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,review'});  // notes: the collaboration module, the diary: Review
  const P = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const mk = async title => (await call('POST', '/api/tasks', {title, list_id: P})).id;
  const T1 = await mk('Plant tulips'), T2 = await mk('Cut the hedge'), T3 = await mk('Water the roses');
  const w = await boot({user: 'alice', hash: 'l/' + P});
  let fake = null;
  const calls = stub(w, (m, p) => fake && fake(m, p));
  check(await until(() => w.eval('OUT.me === S.me.id')), 'setup: the server said who is logged in');

  // ================= typed, then the page goes away
  w.eval(`openDetail(${T1})`);
  check(await until(() => !!w.document.querySelector('#d-title')), 'the task is open');
  type(w, '#d-title', 'Plant tulips and daffodils');
  check(await until(() => w.eval(`!!saveTimers['${T1}:title']`)), 'the title waits for its save (5 s)');
  calls.length = 0;
  w.dispatchEvent(new w.Event('pagehide'));
  const q1 = queued(w, new RegExp(`^/api/tasks/${T1}$`));
  check(q1.length === 1 && q1[0].body.title === 'Plant tulips and daffodils' && q1[0].body._prev?.title === 'Plant tulips', 'pagehide: the text is in the queue at once ' + JSON.stringify(q1));
  check(/Plant tulips and daffodils/.test(w.__store['tasks.outbox'] || ''), 'pagehide: … kept on the device (survives the page)');
  const kc = calls.find(c => c.m === 'PATCH' && c.p === '/api/tasks/' + T1);
  check(!!kc && kc.keep && kc.key === q1[0]?.k, 'pagehide: sent with keepalive under the queue entry\'s key ' + JSON.stringify(kc));
  check(await until(async () => (await call('GET', '/api/tasks/' + T1)).title === 'Plant tulips and daffodils'), 'the server has the text');
  w.eval('flush()');
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'the queued copy went out');
  check(!w.eval('S.conflicts').length, 'no conflict from the second copy ' + JSON.stringify(w.eval('S.conflicts')));

  // ================= the session ends in the middle of a save
  w.eval(`queueSave(${T2}, 'content', 'Words typed before the session ended')`);
  fake = (m, p) => p.startsWith('/api/tasks/') ? jres(401, {error: 'not logged in'}) : null;
  const r401 = await w.eval(`api('POST', '/api/tasks/${T3}/complete', {}).then(() => 'ok', e => e.message)`);
  check(r401 === 'auth', 'setup: the session ended (' + r401 + ')');
  const qa = w.eval('outSync()');
  check(qa.some(x => x.url === `/api/tasks/${T3}/complete`), 'the write of that moment is in the queue ' + JSON.stringify(qa.map(x => x.url)));
  check(qa.some(x => x.url === '/api/tasks/' + T2 && x.body.content === 'Words typed before the session ended'), 'the typed text still waiting is in the queue');
  check(w.eval(`!saveTimers['${T2}:content']`) && /Words typed before the session ended/.test(w.__store['tasks.outbox'] || ''), '… kept on the device, the local data not cleared');
  fake = null;
  w.eval('flush()');  // the same account signed in again
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'after the sign-in: the queue went out');
  const t2 = await call('GET', '/api/tasks/' + T2), t3 = await call('GET', '/api/tasks/' + T3);
  check(t2.content === 'Words typed before the session ended' && t3.status !== 0, `the server has both (${t2.content}, status ${t3.status})`);

  // ================= a save fails: marked, tried again
  w.eval(`openDetail(${T1})`);
  check(await until(() => !!w.document.querySelector('#d-title')), 'the task is open again');
  let n500 = 1;
  fake = (m, p) => m === 'PATCH' && p === '/api/tasks/' + T1 && n500-- > 0 ? jres(500, {error: 'Server error'}) : null;
  type(w, '#d-title', 'Plant tulips in October');
  w.eval('flushSaves()');
  check(await until(() => !!w.document.querySelector('#d-title.unsaved') && /Not saved yet/.test(w.document.querySelector('.unsv')?.textContent || '')), 'the field says "Not saved yet"');
  check(w.eval(`!!saveTimers['${T1}:title'] && saveTimers['${T1}:title'].base`) === 'Plant tulips and daffodils', 'the retry keeps the base the server has');
  check(await until(async () => (await call('GET', '/api/tasks/' + T1)).title === 'Plant tulips in October', {timeout: 20000}), 'the retry saved it');
  check(await until(() => !w.document.querySelector('.unsv') && !w.document.querySelector('#d-title.unsaved')), 'the mark went');
  check(!w.eval('S.conflicts').length, 'no conflict after the retry');
  fake = null;

  // ================= notes
  const N1 = await call('POST', `/api/lists/${P}/notes`, {title: 'Seeds', body: 'Tulips'});
  await w.eval('load()');
  w.location.hash = '#note/' + N1.id;
  check(await until(() => w.eval(`!!(S.nt.notes || []).find(n => n.id === ${N1.id})`) && !!w.document.querySelector('.ntedit')), 'the note is open');
  if (!w.document.querySelector('#nt-body')) w.eval('S.nt.edit = true; renderView()');
  check(await until(() => !!w.document.querySelector('#nt-body')), 'the note is in edit mode');
  type(w, '#nt-body', 'Tulips, daffodils, crocus');
  check(await until(() => w.eval('S.nt.dirty')), 'the note waits for its save (1.2 s)');
  calls.length = 0;
  w.dispatchEvent(new w.Event('pagehide'));
  const qn = queued(w, new RegExp(`^/api/notes/${N1.id}$`));
  check(qn.length === 1 && qn[0].body.body === 'Tulips, daffodils, crocus', 'pagehide: the note\'s text is in the queue ' + JSON.stringify(qn));
  check(calls.some(c => c.p === '/api/notes/' + N1.id && c.keep && c.key === qn[0]?.k), 'pagehide: the note went with keepalive');
  check(await until(async () => (await call('GET', '/api/notes/' + N1.id)).body === 'Tulips, daffodils, crocus'), 'the server has the note');
  w.eval('flush()');
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'the note\'s queued copy went out');
  check(!w.eval('S.conflicts').length, 'no conflict for the note ' + JSON.stringify(w.eval('S.conflicts')));

  // ================= the diary
  const day = w.eval('today()');
  w.eval(`RV.data = {journal: []}; const ta = document.createElement('textarea'); ta.id = 'rv-text'; ta.dataset.day = '${day}'; ta.value = 'A calm day in the garden'; document.body.appendChild(ta); RV.t = setTimeout(() => {}, 60000)`);
  calls.length = 0;
  w.dispatchEvent(new w.Event('pagehide'));
  const qd = queued(w, /^\/api\/life\/journal\//);
  check(qd.length === 1 && qd[0].method === 'PUT' && qd[0].body.text === 'A calm day in the garden', 'pagehide: the diary entry is in the queue ' + JSON.stringify(qd));
  check(calls.some(c => c.m === 'PUT' && c.p === '/api/life/journal/' + day && c.keep), 'pagehide: the diary entry went with keepalive');
  w.eval('flush()');
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'the diary entry\'s queued copy went out');
  const jl = await call('GET', '/api/life/journal');
  check(JSON.stringify(jl).includes('A calm day in the garden') && !w.eval('S.conflicts').length, 'the server has the diary entry, no conflict ' + JSON.stringify(jl).slice(0, 200) + JSON.stringify(w.eval('S.conflicts')) + JSON.stringify(calls.filter(c => /journal/.test(c.p))));
  w.eval("document.querySelector('#rv-text').remove()");

  // ================= the settings (the display name)
  w.eval("settingsModal('account')");
  check(await until(() => !!w.document.querySelector('#a-name')), 'the settings are open');
  type(w, '#a-name', 'Alice Gardener');
  calls.length = 0;
  w.dispatchEvent(new w.Event('pagehide'));
  check(calls.some(c => c.m === 'PATCH' && c.p === '/api/me' && c.keep && /Alice Gardener/.test(c.body)), 'pagehide: the typed name went with keepalive ' + JSON.stringify(calls));
  check(await until(async () => (await call('GET', '/api/state')).me.display_name === 'Alice Gardener'), 'the server has the name');
  w.eval("document.querySelectorAll('.modal').forEach(m => m.remove())");

  // ================= the automatic reload waits for a draft kept only in memory
  w.eval("document.querySelectorAll('textarea, input').forEach(e => { e.defaultValue = e.value; })");  // the fields typed into above count as drawn
  check(w.eval('verDraft()') === false, 'no draft: the reload may come');
  w.eval("S.drafts[987654] = 'Half a comment'");
  check(w.eval('verDraft()') === true && w.eval('verQuiet()') === false, 'a draft in memory holds the automatic reload back');
  w.eval('delete S.drafts[987654]');

  // ================= 2.359.0 review: with the IndexedDB queue a text kept at pagehide goes AFTER what already waits (an older
  // text of the same field, the offline create of its task), never before it; at the next start just the same
  const ops = new Map(), cl = v => JSON.parse(JSON.stringify(v));
  const store = {all: async () => [...ops.values()].map(cl), write: async (put, del) => { for (const r of put) ops.set(r.k, cl(r)); for (const k of del) ops.delete(k); },
    meta: async () => undefined, setMeta: async () => {}, clear: async () => { ops.clear(); }};
  const w2 = await boot({user: 'alice', hash: 'l/' + P, setup: x => { x.__obxStore = store; }});
  check(await until(() => w2.eval('OBX.on === true && OUT.me === S.me.id')), 'setup: the window uses the IndexedDB queue');
  w2.eval('OUT.flushing = true');  // nothing goes out here: only the order counts
  w2.eval(`obxSave(() => OUT.q.push({method: 'PATCH', url: '/api/tasks/${T3}', body: {title: 'v1'}, uid: S.me.id, k: 'rv-q1'}))`);
  w2.eval(`outStash([{method: 'PATCH', url: '/api/tasks/${T3}', body: {title: 'v1 v2'}, uid: S.me.id, k: 'rv-s1'}])`);
  check(JSON.stringify(w2.eval('OUT.q.map(x => x.k)')) === '["rv-q1","rv-s1"]', 'the kept text waits after the older one ' + JSON.stringify(w2.eval('OUT.q.map(x => x.k)')));
  check(await until(() => ops.has('rv-s1') && ops.get('rv-s1').n > ops.get('rv-q1').n), 'in the store: the kept text has the later number');
  // the page went before the store took the kept text over: it is still in localStorage at the next start
  ops.delete('rv-s1');
  const ls2 = {'tasks.outbox': JSON.stringify([{method: 'PATCH', url: '/api/tasks/' + T3, body: {title: 'v1 v2'}, uid: (await call('GET', '/api/state')).me.id, k: 'rv-s1', n: ops.get('rv-q1').n + 1}])};
  w2.close();
  const w3 = await boot({user: 'alice', hash: 'l/' + P, ls: ls2, setup: x => { x.__obxStore = store; const of = x.fetch;
    x.fetch = (u, o = {}) => (o.method === 'PATCH' && new URL(String(u), B).pathname === '/api/tasks/' + T3 ? Promise.reject(new TypeError('offline')) : of(u, o)); }});
  check(await until(() => w3.eval('OBX.on === true') && w3.eval('OUT.q.length') === 2), 'next start: both entries are in the queue');
  check(JSON.stringify(w3.eval('OUT.q.map(x => x.k)')) === '["rv-q1","rv-s1"]', 'next start: the kept text still after the older one ' + JSON.stringify(w3.eval('OUT.q.map(x => x.k)')));
  // another account signs in while these wait: ONE question, not a new one at every poll
  w3.__dialogs = 'manual';  // the question stays open (nobody answers it)
  const asks = () => w3.document.querySelectorAll('.modal.cdlg').length;
  for (let i = 0; i < 3; i++) { try { w3.eval(`applyState({me: {id: 987654}})`); } catch { /* 'auth' */ } }
  check(await until(() => asks() >= 1), 'another account: the question comes');
  await w3.eval('i18nLoad(uiLang())');  // each further question would have come after this load
  check(asks() === 1, 'another account: the question comes once, not at every poll (' + asks() + ')');
  w3.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`p2359_a_autosave_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
