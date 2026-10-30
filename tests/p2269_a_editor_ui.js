// 2.269.0 UI tests, part A (#3012, the document editor without silent loss), own container (start.sh), jsdom. Invented
// services and amounts only.
// - two saves right after each other (a new line, then its quantity): they run in one row, the second sends the new line's
//   id (one line on the server, not two) and the version of the first answer (no 409)
// - someone else saved in between: the next change of the editor gets 409, the bar "Changed in the meantime" with
//   "Reload" shows, the other one's state stays on the server; Reload shows it and the bar goes
// - a status change in between (its answer has no version): the next edit still saves (no false conflict)
// freelancer-matrix: office  (the person without an organisation uses the same editor code)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2269A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (!el) return; if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const svc = (title, qty, rate, unit = 'day') => ({kind: 'service', title, qty, unit, rate, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1});

async function editor(user) {
  const tag = ` (${user})`;
  const doc = await call('POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Spot', items: [svc('Concept', 1, 800)]});
  check(doc.status === 201, 'a quotation ' + doc.status + tag);
  const w = await boot({user, hash: `office/offers/${doc.id}`}), d = w.document;
  check(await until(() => d.querySelectorAll('.ofdeditor .ofdits .ofdit').length >= 1), 'the editor shows the line' + tag);
  // ---- two saves right after each other
  w.eval(`OFD.doc.items.push({kind: 'service', title: 'Editing', detail: '', qty: 1, unit: 'day', rate: 600, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1});
    window.__p1 = ofdPutItems(); OFD.doc.items[OFD.doc.items.length - 1].qty = 4; window.__p2 = ofdPutItems(); 1`);
  await w.eval('Promise.all([window.__p1, window.__p2])');
  let s = await call('GET', `/api/office/docs/${doc.id}`);
  check(s.items?.length === 2 && +s.items[1].qty === 4, `the new line once, with quantity 4 (${s.items?.length}, ${s.items?.[1]?.qty})` + tag);
  check(s.items?.[0]?.id === doc.items[0].id, 'the first line kept its id' + tag);
  check(!d.querySelector('.ofdcf') && w.eval('OFD.doc.updated_at') === s.updated_at, 'no conflict, the editor holds the current version' + tag);
  // ---- a status change in between: no false conflict
  await w.eval(`ofdSave('POST', '/api/office/docs/${doc.id}/status', {status: 'declined'}).then(() => ofdSave('POST', '/api/office/docs/${doc.id}/status', {status: 'draft'}))`);
  change(w, d.querySelector('.ofdits [data-i="0"][data-k="qty"]'), '2');
  s = await until(async () => { const x = await call('GET', `/api/office/docs/${doc.id}`); return +x.items?.[0]?.qty === 2 ? x : null; });
  check(s && !d.querySelector('.ofdcf'), 'after a status change the next edit saves' + tag);
  await until(() => w.eval('OFD.saving') === 0);
  // ---- someone else saves in between (another tab, the phone)
  s = await call('GET', `/api/office/docs/${doc.id}`);
  const other = s.items.map(x => ({id: x.id, kind: x.kind, title: x.title, qty: x.qty, unit: x.unit, rate: x.rate, tax: x.tax}));
  other[1].title = 'Editing (phone)';
  const r = await call('PUT', `/api/office/docs/${doc.id}/items`, {items: other, expect_updated_at: s.updated_at});
  check(r.status === 200, 'the other tab saves ' + r.status + tag);
  change(w, d.querySelector('.ofdits [data-i="0"][data-k="qty"]'), '7');
  check(await until(() => d.querySelector('.ofdcf [data-ofd="cf-reload"]')), 'the conflict bar with Reload' + tag);
  check(/Changed in the meantime/.test(d.querySelector('.ofdcf')?.textContent || ''), 'the bar says changed in the meantime' + tag);
  s = await call('GET', `/api/office/docs/${doc.id}`);
  check(s.items[1].title === 'Editing (phone)' && +s.items[0].qty === 2, 'the other one\'s save stays on the server' + tag);
  click(w, d.querySelector('[data-ofd="cf-reload"]'));
  check(await until(() => !d.querySelector('.ofdcf') && d.querySelectorAll('.ofdits [data-k="title"]')[1]?.value === 'Editing (phone)'), 'Reload shows the current state, the bar goes' + tag);
  await until(() => !w.eval('OFD.docLoading'));
  change(w, d.querySelector('.ofdits [data-i="0"][data-k="qty"]'), '5');
  s = await until(async () => { const x = await call('GET', `/api/office/docs/${doc.id}`); return +x.items?.[0]?.qty === 5 ? x : null; });
  check(s && s.items[1].title === 'Editing (phone)' && !d.querySelector('.ofdcf'), 'after Reload the next edit saves on the current state' + tag);
  check(!errs.length, 'no script errors ' + errs.join(' | ') + tag); errs.splice(0);
  w.close();
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  { const me = (await call('GET', '/api/state')).me; const org = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
    await call('PATCH', '/api/settings', {workspace: `org:${org.id}`}); }
  await editor('alice');

  // ================= freelancer-matrix: office - the same editor as a person without an organisation
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.status === 200 || fr.status === 201, 'freelancer created ' + fr.status);
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,office,clients'});
  check(!((await call('GET', '/api/state')).me?.workspaces || []).length, 'the freelancer is in no organisation');
  await editor('frida');

  console.log(`p2269_a_editor_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
