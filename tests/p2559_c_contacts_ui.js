// 2.559.0 UI tests, part C (#4660): contacts saved / deleted and linked to a task show at once (optimistic as #1501), jsdom:
// kalmido-suite: fresh
// - a new contact: the editor closes and its row shows (a stand-in id below 0) while the server's answer is still held; the
//   answer brings the real id and opens its card; no GET /api/state for it
// - an edit: the new name shows at once; a refusal (500) puts the old name back with the server's message
// - a delete (after the question): gone at once
// - the task panel: a contact linked shows its chip at once; unlinking it is gone at once, a refusal brings it back
// - a person without an organisation (freelancer parity): a new contact shows at once, too
// The held answers wait in the page (window.fetch wrapped) until the test lets them go: every wait is on a real state.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
// the page's requests: those matching re ("METHOD /url") wait in w.__held until go() (the real request) or fail() (a 500 with
// the text); every GET /api/state is counted (w.__st). The change poll is held meanwhile (holdPoll): a poll of its own that saw
// the new server version would count as a GET /api/state of the action
const hold = (w, re) => {
  w.__held = []; w.__st = w.__st || 0; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => {
    const k = `${(o.method || 'GET').toUpperCase()} ${u}`;
    if (/^GET \/api\/state/.test(k)) w.__st++;
    return re.test(k) ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: msg => res(new Response(JSON.stringify({error: msg}), {status: 500, headers: {'content-type': 'application/json'}}))})) : f1(u, o);
  };
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; };
const holdPoll = w => until(() => w.eval('td_polling ? false : (td_polling = true)'));
const freePoll = w => w.eval('td_polling = false');
const toastHas = (d, re) => until(() => re.test(d.querySelector('#toast')?.textContent || ''));
const setupAlice = async features => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features});
  return CA;
};
// a person without an organisation (freelancer parity)
const setupFrida = async (CA, features) => {
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  return CF;
};
const FEAT = 'comments,contacts';
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const rowNames = d => [...d.querySelectorAll('#view .ctlist .ctrow .ctn b')].map(b => b.textContent);
const ctOnServer = async (ck, q) => (await call(ck, 'GET', '/api/contacts?q=' + encodeURIComponent(q))).items || [];
const newContact = async (w, d, given, family) => {
  w.eval(`ctEditor(null)`);
  await until(() => d.querySelector('#ct-given'));
  d.querySelector('#ct-given').value = given; d.querySelector('#ct-family').value = family;
  lastModal(d).querySelector('[data-ctm2="save"]').click();
};

(async () => {
  const CA = await setupAlice(FEAT);
  await call(CA, 'POST', '/api/books', {name: 'People', org_id: null});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'House'})).id;
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Roof', list_id: L})).id;

  let w = await boot({user: 'alice', hash: 'contacts'}), d = w.document;
  check(await until(() => d.querySelector('#view [data-ct="new"]') && w.eval('Array.isArray(CT.items)')), 'the contacts view shows');
  await holdPoll(w);

  // ================= a new contact: its row shows at once
  hold(w, /^POST \/api\/contacts$/);
  await newContact(w, d, 'Ada', 'Lovelace');
  check(await until(() => w.__held.length === 1), 'new: the request is on its way (held)');
  const st0 = w.__st;
  check(!d.querySelector('#ct-given'), 'new: the editor closed at once');
  check(await until(() => rowNames(d).includes('Ada Lovelace')), 'new: its row shows before the answer');
  check(w.eval(`CT.items.find(c => c.fn === 'Ada Lovelace')?.id`) < 0, 'new: with a stand-in id');
  check(!(await ctOnServer(CA, 'Lovelace')).length, 'new: the server has none yet');
  w.__held[0].go();
  check(await until(() => w.eval(`CT.card?.fn === 'Ada Lovelace' && CT.sel > 0 && !CT.items.some(c => c.id < 0)`)), 'new: the answer brings the real id and opens the card');
  const CID = w.eval('CT.sel');
  check((await ctOnServer(CA, 'Lovelace')).length === 1, 'new: one contact on the server');
  await idle(w);
  check(w.__st === st0, 'new: no GET /api/state for it (' + (w.__st - st0) + ')');

  // ================= an edit: shown at once, a refusal puts the old name back
  hold(w, /^PATCH \/api\/contacts\/\d+$/);
  w.eval(`ctEditor(CT.card)`);
  await until(() => d.querySelector('#ct-family'));
  d.querySelector('#ct-family').value = 'King';
  lastModal(d).querySelector('[data-ctm2="save"]').click();
  check(await until(() => w.__held.length === 1), 'edit: the request is held');
  check(!d.querySelector('#ct-family') && await until(() => rowNames(d).includes('Ada King') && w.eval(`CT.card.fn`) === 'Ada King'), 'edit: the new name shows at once');
  w.__held[0].fail('Refused for the test');
  check(await until(() => rowNames(d).includes('Ada Lovelace') && !rowNames(d).includes('Ada King') && w.eval(`CT.card.fn`) === 'Ada Lovelace'), 'edit: the refusal puts the old name back');
  check(await toastHas(d, /Refused for the test/), 'edit: with the server\'s message');
  check((await ctOnServer(CA, 'Lovelace')).length === 1, 'edit: the server kept the old name');
  unhold(w);

  // ================= the task panel: linking / unlinking
  w.eval(`go('l/${L}')`);
  await until(() => d.querySelector(`#view [data-id="${T}"]`));
  w.eval(`openDetail(${T})`);
  (await until(() => d.querySelector('#detail [data-act="ct-link"]'))).click();
  const pk = await until(() => d.querySelector(`#pop [data-ctpick="${CID}"]`));
  hold(w, /^POST \/api\/tasks\/\d+\/contacts$/);
  pk.click();
  check(await until(() => w.__held.length === 1), 'link: the request is held');
  const st1 = w.__st;
  check(await until(() => d.querySelector(`#detail [data-ctunlink="${CID}"]`)), 'link: the chip shows before the answer');
  check(!((await call(CA, 'GET', '/api/state')).tcontacts || {})[T]?.length, 'link: the server has none yet');
  w.__held[0].go();
  check(await until(async () => ((await call(CA, 'GET', '/api/state')).tcontacts || {})[T]?.length === 1), 'link: the server follows');
  await idle(w);
  check(w.__st === st1, 'link: no GET /api/state for it');
  hold(w, /^DELETE \/api\/tasks\/\d+\/contacts\/\d+$/);
  d.querySelector(`#detail [data-ctunlink="${CID}"]`).click();
  check(await until(() => w.__held.length === 1 && !d.querySelector(`#detail [data-ctunlink="${CID}"]`)), 'unlink: gone at once');
  w.__held[0].fail('Refused for the test');
  check(await until(() => d.querySelector(`#detail [data-ctunlink="${CID}"]`)), 'unlink: the refusal brings the chip back');
  unhold(w);

  // ================= a delete: gone at once
  w.eval(`go('contacts/${CID}')`);
  check(await until(() => w.eval(`CT.card?.id`) === CID && d.querySelector('#view [data-ct="cmenu"]')), 'delete: the card shows');
  hold(w, /^DELETE \/api\/contacts\/\d+$/);
  d.querySelector('#view [data-ct="cmenu"]').click();
  (await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Delete/.test(b.textContent)))).click();
  check(await until(() => w.__held.length === 1), 'delete: the request is held (after the question)');
  check(await until(() => !rowNames(d).includes('Ada Lovelace')) && w.eval(`CT.card`) === null, 'delete: gone at once');
  w.__held[0].go(); unhold(w);
  check(await until(async () => !(await ctOnServer(CA, 'Lovelace')).length), 'delete: the server follows');
  check(await toastHas(d, /Contact deleted/), 'delete: the toast says it');
  freePoll(w);
  w.close();

  // ================= a person without an organisation: the same at once
  const CF = await setupFrida(CA, FEAT);
  await call(CF, 'POST', '/api/books', {name: 'Clients', org_id: null});
  w = await boot({user: 'frida', hash: 'contacts'}); d = w.document;
  check(await until(() => d.querySelector('#view [data-ct="new"]') && w.eval('Array.isArray(CT.items)')), 'freelancer: the contacts view shows');
  await holdPoll(w);
  hold(w, /^POST \/api\/contacts$/);
  await newContact(w, d, 'Grace', 'Hopper');
  check(await until(() => w.__held.length === 1), 'freelancer: the request is held');
  check(await until(() => rowNames(d).includes('Grace Hopper')) && !d.querySelector('#ct-given'), 'freelancer: its row shows at once');
  w.__held[0].go(); unhold(w); freePoll(w);
  check(await until(async () => (await ctOnServer(CF, 'Hopper')).length === 1), 'freelancer: the server follows');
  w.close();

  console.log(`p2559_c_contacts_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
