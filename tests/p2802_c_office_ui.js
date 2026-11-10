// kalmido-suite: fresh
// 2.855.0 part C (#5451) UI test: an error in the office is said once and in plain words. Own container (start.sh, mode
// workspaces), jsdom, invented data only. freelancer-matrix: office (an organisation's admin and a person without one)
// - api() marks an error it said (x.shown): the office's ofcErr says nothing more; an error nobody said yet is said once, an empty
//   one as a plain sentence (never "unknown" or an empty toast)
// - the invoice editor: a field whose save is refused says it once, at the field ("Not saved: ..."), keeps the typed value;
//   nothing raw in the head next to the buttons, no toast left
// - the send dialog: no variable name (KALMIDO_SMTP_HOST) for an admin either; a part that could not be loaded (recipients)
//   is named in the dialog instead of silently missing
// - the bank page: the fetch switched off says so without "FinTS" / "product registration"
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); let j = null; try { j = await r.json(); } catch { j = null; } j = j || {}; j.http = r.status; return j; };
const until = async (fn, n = 120) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,files,docs,office,clients';
const ERR = 'Testfehler Nordwind';
const count = (s, t) => s.split(t).length - 1;
// the visible toast's text ('' = none shown)
// the text a person sees on the page: without the toast (toastTxt), the screen-reader-only parts (#srlive, .sr)
const seen = d => { const c = d.body.cloneNode(true); c.querySelectorAll('#toast, #srlive, .sr').forEach(x => x.remove()); return c.textContent; };
const toastTxt = d => { const t = d.querySelector('#toast'); return t && !t.classList.contains('hidden') ? t.textContent : ''; };
// every toast() call of the page is recorded in window.__T (the global function, so office_*.js calls go through it)
const spyToast = w => w.eval(`window.__T = []; { const t0 = toast; toast = (...a) => { window.__T.push(String(a[0])); return t0(...a); }; } 1`);
// the page's fetch answers a matching request with an error of the server (status, JSON {error})
const failFetch = (w, method, re, status, msg) => w.eval(`{ const f0 = window.fetch; window.fetch = (u, o) => (o?.method || 'GET') === ${JSON.stringify(method)} && ${re}.test(String(u))
  ? Promise.resolve(new Response(JSON.stringify({error: ${JSON.stringify(msg)}}), {status: ${status}, headers: {'Content-Type': 'application/json'}})) : f0(u, o); } 1`);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, CK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CK);
  const me = (await call('GET', '/api/state', null, CK)).me;
  const org = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id}, CK);
  await call('PATCH', '/api/settings', {workspace: `org:${org.id}`}, CK);
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'}, FCK);
  const ms = await call('GET', '/api/office/mail-status', null, CK);

  for (const [who, ck] of [['alice', CK], ['frida', FCK]]) {
    await call('PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Studio Nordwind', street: 'Hafenstraße 12', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', iban: 'DE02120300000000202051'}}, ck);
    const cl = await call('POST', '/api/clients', {name: 'Beispielkunde Süd', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE', email: 'info@kunde.example'}, ck);
    const inv = await call('POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, service_from: '2026-10-01', items: [{title: 'Schnitt', qty: 1, rate: 100}]}, ck);
    check(inv.http === 201, `${who}: an invoice draft ${inv.http}`);

    // ---- the helper: said by api() = not again; nobody said it = once; empty = a plain sentence
    let w = await boot({user: who, hash: 'office/offers/' + inv.id}), d = w.document;
    check(!!await until(() => d.querySelector('#ofd-order_ref')), `${who}: the invoice editor is open (field "Order number")`);
    await idle(w);  // the editor's later loads may draw it again: the field taken after them
    spyToast(w);
    await w.eval(`api('POST', '/api/office/docs/99999999/status', {status: 'sent'}).catch(ofcErr)`);
    const t1 = w.eval('window.__T.slice()');
    check(t1.length === 1 && t1[0] && !/^unknown$/i.test(t1[0]), `${who}: a refused request is said exactly once (api(), no second toast) ${JSON.stringify(t1)}`);
    w.eval(`window.__T.length = 0; ofcErr(new Error('')); ofcErr(new Error('${ERR}')); 1`);
    const t2 = w.eval('window.__T.slice()');
    check(t2.length === 2 && t2[0] === 'That did not work. Please try again.' && t2[1] === ERR, `${who}: an error nobody said yet: once, an empty one in plain words ${JSON.stringify(t2)}`);

    // ---- the editor: the field's refused save is said once, at the field, the value stays and is marked "not saved"
    w.eval('window.__T.length = 0; 1');
    failFetch(w, 'PATCH', `/\\/api\\/office\\/docs\\/${inv.id}(\\?|$)/`, 400, ERR);
    const f = d.querySelector('#ofd-order_ref');
    f.value = 'PO-4711'; f.dispatchEvent(new w.Event('change', {bubbles: true}));
    const mk = await until(() => d.querySelector('.ostok.err'));
    const mt = mk?.textContent || '';
    check(mt.includes('Not saved: ' + ERR), `${who}: the field says "Not saved: ..." ${JSON.stringify(mt)}`);
    check(d.querySelector('#ofd-order_ref')?.value === 'PO-4711' && d.querySelector('#ofd-order_ref')?.getAttribute('aria-invalid') !== null, `${who}: the typed value stays in the field, marked invalid`);
    const head = d.querySelector('.ofdhead .ofdsave')?.textContent || '';
    check(!head.includes(ERR), `${who}: nothing raw in the head next to the buttons ${JSON.stringify(head)}`);
    check(!toastTxt(d).includes(ERR), `${who}: no toast left beside the field's message ${JSON.stringify(toastTxt(d))}`);
    check(count(seen(d) + toastTxt(d), ERR) === 1, `${who}: the error is on the page exactly once (${count(seen(d) + toastTxt(d), ERR)})`);
    w.close();

    // ---- the send dialog: no variable name, a part that failed to load is named in the dialog (no toast for it)
    w = await boot({user: who, hash: 'office/offers/' + inv.id}); d = w.document;
    await until(() => d.querySelector('#ofd-order_ref')); await idle(w);
    w.eval('S.me.is_admin = true; 1');
    spyToast(w);
    failFetch(w, 'GET', `/\\/api\\/office\\/docs\\/${inv.id}\\/recipients$/`, 500, ERR);
    w.eval('ofdSendDialog(OFD.doc); 1');
    const md = await until(() => d.querySelector('#ofd-s-to')?.closest('.modal'));
    const mtx = md?.textContent || '';
    check(!!md && !/KALMIDO_/.test(mtx), `${who}: the send dialog names no server variable (admin) ${mtx.slice(0, 160)}`);
    if (!ms.smtp) check(/whoever runs the server/.test(md?.querySelector('.ofdwarn')?.textContent || ''), `${who}: mail not set up: who sets it up, in plain words`);
    const miss = md?.querySelector('.ofdmiss')?.textContent || '';
    check(/Could not be loaded: Recipients/.test(miss), `${who}: the recipients that failed to load are named in the dialog ${JSON.stringify(miss)}`);
    check(!toastTxt(d).includes(ERR) && count(seen(d), ERR) === 0, `${who}: no toast and no raw text for the failed part ${JSON.stringify(toastTxt(d))}`);
    md?.querySelector('[data-m="close"]')?.click();
    w.close();

    // ---- the bank page: the fetch switched off, in plain words
    w = await boot({user: who, hash: 'office/bank'}); d = w.document;
    const off = await until(() => d.querySelector('#bnk-fnt-off'));
    const ot = off?.textContent || '';
    check(!!off && /not set up on this server/.test(ot) && !/FinTS|registration/i.test(ot), `${who}: the bank fetch off: plain words, no "FinTS" ${JSON.stringify(ot)}`);
    w.close();
  }

  console.log(`p2802_c_office_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
