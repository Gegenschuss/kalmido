// 2.422.0 A (#3468) UI tests (jsdom), fresh DB: a save still waiting when the page goes away is not lost
// - the list dialog: a name / hourly rate typed within the 0.9 s of its autosave goes out with keepalive at pagehide (a list has
//   no queue: closing / reloading asks while it waits); the autosave after it sends nothing twice
// - a project's custom field typed in but never left (it saves on "change"): pagehide puts it into the queue and out with
//   keepalive; no question, the queue keeps it
// - formguard: fgPending registers a waiting save (pagehide sends, beforeunload asks while ask() says so); ended = gone
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
// every request that leaves the window {m, p, keep, body}
const stub = w => { const calls = [], of = w.fetch; w.fetch = (u, o = {}) => { const m = (o.method || 'GET').toUpperCase(), p = new URL(String(u), B).pathname;
  calls.push({m, p, keep: !!o.keepalive, key: (o.headers || {})['Idempotency-Key'] || '', body: typeof o.body === 'string' ? o.body : ''}); return of(u, o); }; return calls; };
const type = (w, sel, v) => { const el = w.document.querySelector(sel); el.focus(); el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); return el; };
const asks = w => { const e = new w.Event('beforeunload', {cancelable: true}); w.dispatchEvent(e); return e.defaultPrevented; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const FB = (await call('POST', `/api/lists/${P}/fields`, {name: 'Budget', type: 'text'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Plant tulips', list_id: P})).id;
  check(P && FB && T1, 'setup: a list with a custom field and a task');
  const w = await boot({user: 'alice', hash: 'l/' + P});
  const calls = stub(w);
  check(await until(() => w.eval('OUT.me === S.me.id')), 'setup: the server said who is logged in');

  // ================= formguard: the registration itself
  w.eval('window.__sent = 0; window.__wait = true; window.__off = fgPending(() => { window.__sent++; }, () => window.__wait)');
  check(asks(w) === true, 'fgPending: beforeunload asks while ask() says something waits');
  w.dispatchEvent(new w.Event('pagehide'));
  check(w.eval('window.__sent') === 1, 'fgPending: pagehide runs send()');
  w.eval('window.__wait = false');
  check(asks(w) === false, 'fgPending: nothing waits = no question');
  w.eval('window.__wait = true; window.__off()');
  w.dispatchEvent(new w.Event('pagehide'));
  check(w.eval('window.__sent') === 1 && asks(w) === false, 'fgPending: an ended registration neither sends nor asks');

  // ================= the list dialog: typed within the debounce, then the page goes away
  w.eval(`listModal(${P})`);
  check(await until(() => !!w.document.querySelector('.modal #l-name') && !!w.document.querySelector('.modal #l-rate')), 'the list dialog is open');
  check(asks(w) === false, 'list dialog: nothing typed = no question');
  type(w, '.modal #l-name', 'Garden 2027');
  type(w, '.modal #l-rate', '85');
  check(asks(w) === true, 'list dialog: a change waiting for its autosave asks before the page closes');
  calls.length = 0;
  w.dispatchEvent(new w.Event('pagehide'));
  const kl = calls.filter(c => c.m === 'PATCH' && c.p === '/api/lists/' + P);
  const kb = kl[0] ? JSON.parse(kl[0].body) : {};
  check(kl.length === 1 && kl[0].keep && kb.name === 'Garden 2027' && +kb.rate === 85 && kb._prev?.name === 'Garden', 'list dialog: pagehide sends the waiting fields with keepalive ' + JSON.stringify(kl));
  check(await until(async () => { const l = (await call('GET', '/api/state')).lists.find(x => x.id === P); return l?.name === 'Garden 2027' && +l.rate === 85; }), 'list dialog: the server has the name and the rate');
  // the page stayed (kept for "back"): the debounce runs and sends nothing twice
  check(await until(() => asks(w) === false, {timeout: 5000}), 'list dialog: after the autosave nothing waits');
  check(calls.filter(c => c.m === 'PATCH' && c.p === '/api/lists/' + P).length === 1, 'list dialog: the autosave after it sends nothing twice ' + JSON.stringify(calls.filter(c => c.p === '/api/lists/' + P)));
  w.eval("document.querySelectorAll('.modal').forEach(m => m.remove())");
  check(asks(w) === false, 'list dialog closed: its registration ended');

  // ================= a custom field typed in but never left
  await w.eval('load()');
  w.eval(`openDetail(${T1})`);
  check(await until(() => !!w.document.querySelector(`#detail [data-cf="${FB}"]`)), 'the task with its custom field is open');
  type(w, `#detail [data-cf="${FB}"]`, 'Forty euros');
  check(asks(w) === false, 'custom field: no question (the queue keeps it)');
  calls.length = 0;
  w.dispatchEvent(new w.Event('pagehide'));
  const qf = w.eval('outSync()').filter(x => x.url === '/api/tasks/' + T1 && x.body?.fields);
  check(qf.length === 1 && qf[0].body.fields[FB] === 'Forty euros', 'custom field: pagehide puts the value into the queue ' + JSON.stringify(qf));
  const kf = calls.find(c => c.m === 'PATCH' && c.p === '/api/tasks/' + T1);
  check(!!kf && kf.keep && kf.key === qf[0]?.k, 'custom field: pagehide sends it with keepalive under the queue key ' + JSON.stringify(kf));
  check(await until(async () => (await call('GET', '/api/tasks/' + T1)).fields?.[FB] === 'Forty euros'), 'custom field: the server has the value');
  w.eval('flush()');
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing')), 'custom field: the queued copy went out');
  check(!w.eval('S.conflicts').length, 'custom field: no conflict from the second copy');
  w.dispatchEvent(new w.Event('pagehide'));
  check(w.eval('outSync()').filter(x => x.url === '/api/tasks/' + T1 && x.body?.fields).length === 0, 'custom field: sent once, a second pagehide sends nothing');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`p2422_a_forms_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
