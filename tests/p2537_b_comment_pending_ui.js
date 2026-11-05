// 2.537.0 B (#4569) UI tests (jsdom), fresh DB, as a person without an organisation: a comment stands in the list at once
// - a slow server: right after Send the comment is in the list as "Sending…", the box is empty, Send stays free; after the
//   answer it is there exactly once (no waiting entry left)
// - the server fails: the comment stays in the list with "Send again" (its text kept, also in this browser for a reload);
//   a second try whose first answer got lost (the server has it) carries the same client_ref: no double
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const jres = (st, j) => new Response(JSON.stringify(j), {status: st, headers: {'content-type': 'application/json'}});
// every request that leaves the window [method, path, body]; fake(m, p, o, pass) may answer instead (a Response or a Promise of one)
const stub = (w, fake) => { const calls = [], of = w.fetch; w.fetch = (u, o = {}) => { const m = (o.method || 'GET').toUpperCase(), p = new URL(String(u), B).pathname; calls.push([m, p, o.body]); const r = fake && fake(m, p, o, () => of(u, o)); return r ? Promise.resolve(r) : of(u, o); }; return calls; };
const gate = () => { let open; const p = new Promise(r => { open = r; }); return {p, open}; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CA);
  const CF = await login('frida');
  const stf = await call('GET', '/api/state', null, CF);
  check(!(stf.me.workspaces || []).length, 'setup: frida has no organisation');
  const feats = [...new Set([...(stf.settings.features || '').split(',').filter(Boolean), 'comments', 'collab'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats}, CF);
  const P = (await call('POST', '/api/lists', {name: 'Calls'}, CF)).id;
  const T = (await call('POST', '/api/tasks', {title: 'Call Acme', list_id: P}, CF)).id;
  const onServer = async txt => ((await call('GET', `/api/tasks/${T}/timeline`, null, CF)).comments || []).filter(c => c.body === txt).length;

  const w = await boot({user: 'frida', hash: 't/' + T}), d = w.document;
  const fid = w.eval('S.me.id');
  check(!!await until(() => d.querySelector('#c-input')) && await until(() => w.eval(`S.tl.id === ${T} && !!S.tl.comments`)), 'the comment box and the list are there');
  let fake = null;
  const calls = stub(w, (m, p, o, pass) => fake && fake(m, p, o, pass));
  const posts = () => calls.filter(([m, p]) => m === 'POST' && p === `/api/tasks/${T}/comments`);
  const shown = txt => [...d.querySelectorAll('#d-tl-items .cm')].filter(n => n.querySelector('.cbody')?.textContent.trim() === txt);
  const send = txt => { const ci = d.querySelector('#c-input'); ci.value = txt; ci.dispatchEvent(new w.Event('input', {bubbles: true})); d.querySelector('[data-act="c-send"]').click(); };

  // ================= a slow server: at once in the list
  let g = gate();
  fake = (m, p, o, pass) => m === 'POST' && p === `/api/tasks/${T}/comments` ? g.p.then(pass) : null;
  send('Called, they want an offer');
  const pend = shown('Called, they want an offer');
  check(pend.length === 1 && pend[0].classList.contains('cmpend') && /Sending…/.test(pend[0].textContent), 'slow server: in the list at once as "Sending…"');
  check(d.querySelector('#c-input').value === '' && !d.querySelector('[data-act="c-send"]').disabled, 'slow server: the box is empty, Send stays free');
  check(await until(() => posts().length === 1) && await onServer('Called, they want an offer') === 0, 'slow server: on its way, not on the server yet');
  w.eval('renderDetail()');  // the detail drawn anew meanwhile (a sync): the kept draft does not come back into the box
  check(d.querySelector('#c-input')?.value === '' && shown('Called, they want an offer').length === 1, 'slow server: a redraw keeps the box empty and the entry ' + JSON.stringify(d.querySelector('#c-input')?.value));
  g.open();
  check(await until(() => shown('Called, they want an offer').length === 1 && !d.querySelector('#d-tl-items .cmpend')), 'after the answer: exactly once, no waiting entry left');
  check(!!shown('Called, they want an offer')[0]?.dataset.cid && await onServer('Called, they want an offer') === 1, 'the real comment, once on the server');
  check(!w.__store[`tasks.fdc.${fid}.${T}`], 'sent: no kept draft left');

  // ================= the server fails: "Send again", the text stays; the second try makes no double
  let n = 1;
  fake = (m, p, o, pass) => m === 'POST' && p === `/api/tasks/${T}/comments` && n-- > 0 ? pass().then(() => jres(500, {error: 'Server error'})) : null;  // the server has it, its answer got lost
  send('Offer goes out on Monday');
  check(await until(() => d.querySelector('#d-tl-items .cmfail [data-act="c-resend"]')), 'failed: the comment stays with "Send again"');
  const fl = d.querySelector('#d-tl-items .cmfail');
  check(/Offer goes out on Monday/.test(fl?.textContent || '') && /Not sent/.test(fl?.textContent || '') && d.querySelector('#c-input').value === '', 'failed: its text in the list, the box stays free for the next one');
  check(/Offer goes out on Monday/.test(w.__store[`tasks.fdc.${fid}.${T}`] || ''), 'failed: the text is kept in this browser too (a reload gives it back)');
  d.querySelector('#d-tl-items .cmfail [data-act="c-resend"]').click();
  check(await until(() => posts().length === 3 && !d.querySelector('#d-tl-items .cmpend') && shown('Offer goes out on Monday').length === 1), 'Send again: once in the list ' + posts().length);
  const refs = posts().slice(1).map(c => JSON.parse(c[2] || '{}').client_ref);
  check(refs.length === 2 && refs[0] && refs[0] === refs[1], 'both tries carry the same client_ref ' + JSON.stringify(refs));
  check(await onServer('Offer goes out on Monday') === 1, 'no double on the server');
  check(!w.__store[`tasks.fdc.${fid}.${T}`], 'sent now: the kept text is gone');
  w.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2537_b_comment_pending_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
