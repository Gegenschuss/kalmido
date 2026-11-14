// 2.1165.0 UI tests, part B (#6116, #6121): contacts - jsdom against the test container, invented data only:
// kalmido-suite: fresh
// #6116 - Save in the contact editor is locked until the look-alike check answered: a double click = ONE contact
//       - an error after api() is said once (no second toast from the catch: the trash's Restore refused)
//       - the link kind 'about' has its own key 'About|contact link': German "Betrifft" on the task panel and the card
//         (before: "Über Kalmido" of the About page); English stays "About"
// #6121 - the list: "Loading" from the shared block, a failed load = "Could not be loaded" + "Try again" (not "No contact
//         matches"), Try again brings the rows; the right column says nothing while the list is empty / failed
//       - a card being opened shows "Loading" in its place, not the contact before
//       - the trash and the groups dialog: a failed load is said with "Try again" (no "trash is empty", the dialog stays)
//       - the "Link a contact" box of the task panel: a failed search = error + Try again (no endless "Loading")
//       - no contacts at all: ONE hint with "New contact" and "Import…" (both work), as a person without an organisation
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
// requests matching re ("METHOD /url") wait in w.__held until go() (the real request) or fail() (a 500 with the text)
const hold = (w, re) => {
  w.__held = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => {
    const k = `${(o.method || 'GET').toUpperCase()} ${u}`;
    return re.test(k) ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: msg => res(new Response(JSON.stringify({error: msg}), {status: 500, headers: {'content-type': 'application/json'}}))})) : f1(u, o);
  };
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; };
const holdPoll = w => until(() => w.eval('td_polling ? false : (td_polling = true)'));
const freePoll = w => w.eval('td_polling = false');
// every toast of the page counted (its text)
const countToasts = w => w.eval(`(() => { window.__tc = []; if (!window.__tw) { window.__tw = 1; const t0 = toast; toast = function (m, ...a) { window.__tc.push(String(m)); return t0(m, ...a); }; } return 1; })()`);
const txt = (d, sel) => d.querySelector(sel)?.textContent || '';
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const rowNames = d => [...d.querySelectorAll('#view .ctlist .ctrow .ctn b')].map(b => b.textContent);
const ctOnServer = async (ck, q) => (await call(ck, 'GET', '/api/contacts?q=' + encodeURIComponent(q))).items || [];

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,contacts'});
  const BK = (await call(CA, 'POST', '/api/books', {name: 'People', org_id: null})).id;
  const ADA = (await call(CA, 'POST', '/api/contacts', {book_id: BK, given: 'Ada', family: 'Lovelace', groups: ['Customers']})).id;
  const BOB = (await call(CA, 'POST', '/api/contacts', {book_id: BK, given: 'Bob', family: 'Builder'})).id;
  const GONE = (await call(CA, 'POST', '/api/contacts', {book_id: BK, given: 'Gina', family: 'Gone'})).id;
  check((await call(CA, 'DELETE', `/api/contacts/${GONE}`)).http === 200, 'a contact in the trash');
  const L = (await call(CA, 'POST', '/api/lists', {name: 'House'})).id;
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Roof', list_id: L})).id;

  let w = await boot({user: 'alice', hash: 'contacts'}), d = w.document;
  check(await until(() => rowNames(d).includes('Ada Lovelace')), 'the contacts view shows its rows');
  await holdPoll(w);

  // ================= #6116: a double click on Save = one contact
  hold(w, /^POST \/api\/contacts\/dupcheck$/);
  w.eval(`ctEditor(null)`);
  await until(() => d.querySelector('#ct-given'));
  d.querySelector('#ct-given').value = 'Bea'; d.querySelector('#ct-family').value = 'Double';
  const sv = lastModal(d).querySelector('[data-ctm2="save"]');
  sv.click(); sv.click();
  check(await until(() => w.__held.length >= 1), '#6116 double: the look-alike check is on its way (held)');
  check(sv.disabled, '#6116 double: Save is locked while it runs');
  sv.click();
  await idle(w);
  check(w.__held.length === 1, `#6116 double: one check only, the further clicks did nothing (${w.__held.length})`);
  w.__held.forEach(h => h.go()); unhold(w);
  check(await until(async () => (await ctOnServer(CA, 'Double')).length >= 1), '#6116 double: the contact is created');
  await idle(w); await sleep(300); await idle(w);
  check((await ctOnServer(CA, 'Double')).length === 1, `#6116 double: exactly one contact on the server (${(await ctOnServer(CA, 'Double')).length})`);
  check(await until(() => rowNames(d).filter(n => n === 'Bea Double').length === 1), '#6116 double: one row');

  // ================= #6116: an error after api() is said once (the trash's Restore refused)
  w.eval(`CT.trash = {}; ctDraw()`);
  const rest = await until(() => d.querySelector(`#view [data-ctt="crest"][data-id="${GONE}"]`));
  check(rest, '#6121 trash: the deleted contact is listed');
  countToasts(w);
  hold(w, /^POST \/api\/contacts\/\d+\/restore$/);
  rest.click();
  check(await until(() => w.__held.length === 1), '#6116 toast: the restore is on its way (held)');
  w.__held[0].fail('Refused for the test');
  check(await until(() => w.eval(`__tc.some(m => /Refused for the test/.test(m))`)), '#6116 toast: the refusal is said');
  unhold(w); await idle(w); await sleep(300); await idle(w);
  const nRef = w.eval(`__tc.filter(m => /Refused for the test/.test(m)).length`);
  check(nRef === 1, `#6116 toast: said ONCE, no second toast from the catch (${nRef}: ${JSON.stringify(w.eval('__tc'))})`);

  // ================= #6121: the trash's failed load is said with Try again
  w.eval(`CT.trash = null; ctDraw()`);
  hold(w, /^GET \/api\/contacts\?trash=1/);
  w.eval(`CT.trash = {}; ctDraw()`);
  check(await until(() => w.__held.length === 1 && d.querySelector('#view .ctview .eload')), '#6121 trash: "Loading" from the shared block while it loads');
  w.__held[0].fail('Testfehler');
  check(await until(() => d.querySelector('#view .ctview .eerr')), '#6121 trash: a failed load shows the error block');
  check(/The trash could not be loaded/.test(txt(d, '#view .ctview .eerr')) && !/trash is empty/i.test(txt(d, '#view .ctview')), '#6121 trash: it says so, not "The trash is empty": ' + txt(d, '#view .ctview'));
  unhold(w);
  d.querySelector('#view .ctview .eerr [data-esretry]').click();
  check(await until(() => d.querySelector(`#view [data-ctt="crest"][data-id="${GONE}"]`)), '#6121 trash: Try again brings the deleted contact');
  w.eval(`ctt_close()`);
  await until(() => rowNames(d).includes('Ada Lovelace'));

  // ================= #6121: the list's failed load = error + Try again (not "No contact matches")
  hold(w, /^GET \/api\/contacts\?/);
  w.eval(`CT.items = null; CT.loading = false; CT.sel = null; CT.card = null; ctDraw()`);
  check(await until(() => w.__held.length === 1 && d.querySelector('#view .ctlistw .eload')), '#6121 list: "Loading" from the shared block while it loads');
  check(!/Select a contact/.test(txt(d, '#view .ctcols')), '#6121 list: the right column is quiet while it loads');
  w.__held[0].fail('Testfehler');
  check(await until(() => d.querySelector('#view .ctlistw .eerr')), '#6121 list: a failed load shows the error block');
  const le = txt(d, '#view .ctlistw');
  check(/Contacts could not be loaded/.test(le) && /Try again/.test(le) && !/No contact matches/.test(le), '#6121 list: "could not be loaded" + Try again, not "No contact matches": ' + le);
  check(!/Select a contact/.test(txt(d, '#view .ctcols')), '#6121 list: ONE message - the right column says nothing');
  unhold(w);
  d.querySelector('#view .ctlistw [data-esretry]').click();
  check(await until(() => rowNames(d).includes('Ada Lovelace') && rowNames(d).includes('Bob Builder')), '#6121 list: Try again brings the rows');
  check(await until(() => /Select a contact/.test(txt(d, '#view .ctcols'))), '#6121 list: with rows the right column says "Select a contact" again');

  // ================= #6121: a card being opened shows "Loading", not the one before
  d.querySelector(`#view [data-ctopen="${ADA}"]`).click();
  check(await until(() => txt(d, '#view #ct-h') === 'Ada Lovelace'), '#6121 card: Ada opens');
  hold(w, /^GET \/api\/contacts\/\d+$/);
  d.querySelector(`#view [data-ctopen="${BOB}"]`).click();
  check(await until(() => w.__held.length === 1 && d.querySelector('#view .ctcard.ctld .eload')), '#6121 card: Bob\'s place shows "Loading"');
  check(!/Ada Lovelace/.test(txt(d, '#view .ctcard')), '#6121 card: Ada\'s card is gone meanwhile');
  w.__held[0].go(); unhold(w);
  check(await until(() => txt(d, '#view #ct-h') === 'Bob Builder' && !d.querySelector('#view .ctcard.ctld')), '#6121 card: then Bob\'s card');

  // ================= #6121: the groups dialog stays on a failed load, with Try again
  hold(w, /^GET \/api\/contacts\/groups$/);
  w.eval(`ctx_groupsModal()`);
  check(await until(() => w.__held.length === 1 && d.querySelector('#ctg-body .eload')), '#6121 groups: "Loading" while it loads');
  w.__held[0].fail('Testfehler');
  check(await until(() => d.querySelector('#ctg-body .eerr')), '#6121 groups: a failed load is said in the dialog (it stays open)');
  check(/The groups could not be loaded/.test(txt(d, '#ctg-body')), '#6121 groups: in words: ' + txt(d, '#ctg-body'));
  unhold(w);
  d.querySelector('#ctg-body [data-esretry]').click();
  check(await until(() => /Customers/.test(txt(d, '#ctg-body'))), '#6121 groups: Try again lists the group');
  lastModal(d).querySelector('[data-ctg="close"]').click();

  // ================= #6121: the "Link a contact" box: a failed search = error + Try again; English "About" stays "About"
  w.eval(`go('l/${L}')`);
  await until(() => d.querySelector(`#view [data-id="${T}"]`));
  w.eval(`openDetail(${T})`);
  hold(w, /^GET \/api\/contacts\?limit=30/);
  (await until(() => d.querySelector('#detail [data-act="ct-link"]'))).click();
  check(await until(() => w.__held.length === 1 && d.querySelector('#pop #ctp-l .eload')), '#6121 link: "Loading" while it searches');
  w.__held[0].fail('Testfehler');
  check(await until(() => d.querySelector('#pop #ctp-l .eerr')), '#6121 link: a failed search says so (no endless "Loading")');
  check(!/Loading/.test(txt(d, '#pop #ctp-l')), '#6121 link: no "Loading" left');
  unhold(w);
  d.querySelector('#pop #ctp-l [data-esretry]').click();
  const pk = await until(() => d.querySelector(`#pop [data-ctpick="${ADA}"]`));
  check(pk, '#6121 link: Try again lists the contacts');
  check(/About/.test(txt(d, '#pop [data-ctpk="about"]')) && !/\|/.test(txt(d, '#pop .ctpk')), '#6116 link: the kind reads "About" in English (no key text): ' + txt(d, '#pop .ctpk'));
  pk.click();
  check(await until(() => d.querySelector(`#detail [data-ctunlink="${ADA}"]`)), '#6116 link: the chip shows');
  check(txt(d, '#detail .ctlk .muted') === 'About', '#6116 link: its kind reads "About": ' + txt(d, '#detail .ctlk .muted'));
  freePoll(w);
  w.close();

  // ================= a person without an organisation, German: no contacts = ONE hint with New contact + Import; "Betrifft"
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: 'comments,contacts'});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  const FB = (await call(CF, 'POST', '/api/books', {name: 'Kunden', org_id: null})).id;
  w = await boot({user: 'frida', hash: 'contacts'}); d = w.document;
  const em = await until(() => d.querySelector('#view .ctlistw .ctnoitems'));
  check(em, 'freelancer empty: the empty block shows');
  check(/Noch keine Kontakte/.test(txt(d, '#view .ctnoitems')), 'freelancer empty: "Noch keine Kontakte": ' + txt(d, '#view .ctnoitems'));
  check(d.querySelector('#view .ctnoitems [data-ct="new"]') && d.querySelector('#view .ctnoitems [data-ct="imp"]'), 'freelancer empty: with the buttons "Neuer Kontakt" and "Importieren…"');
  check(!/Wähle einen Kontakt|Select a contact/.test(txt(d, '#view')) && !txt(d, '#view .ctcard.ctnone').trim(), 'freelancer empty: ONE hint - the right column says nothing');
  w.eval(`(() => { const f = document.querySelector('#ct-impfile'); f.click = () => { window.__imp = 1; }; return 1; })()`);
  d.querySelector('#view .ctnoitems [data-ct="imp"]').click();
  check(w.eval('window.__imp') === 1, 'freelancer empty: "Importieren…" opens the file choice');
  d.querySelector('#view .ctnoitems [data-ct="new"]').click();
  check(await until(() => d.querySelector('#ct-given')), 'freelancer empty: "Neuer Kontakt" opens the editor');
  lastModal(d).querySelector('[data-ctm2="close"]').click();
  w.close();
  const FC = (await call(CF, 'POST', '/api/contacts', {book_id: FB, given: 'Petra', family: 'Kundin'})).id;
  const FL = (await call(CF, 'POST', '/api/lists', {name: 'Haus'})).id;
  const FT = (await call(CF, 'POST', '/api/tasks', {title: 'Dach', list_id: FL})).id;
  check((await call(CF, 'POST', `/api/tasks/${FT}/contacts`, {contact_id: FC, kind: 'about'})).http === 200, 'freelancer: the task is linked (about)');
  w = await boot({user: 'frida', hash: 'l/' + FL}); d = w.document;
  await until(() => d.querySelector(`#view [data-id="${FT}"]`));
  w.eval(`openDetail(${FT})`);
  check(await until(() => txt(d, '#detail .ctlk .muted') === 'Betrifft'), '#6116 freelancer: the task panel says "Betrifft" (not "Über Kalmido"): ' + txt(d, '#detail .ctlk .muted'));
  w.eval(`go('contacts/${FC}')`);
  check(await until(() => /Dach/.test(txt(d, '#view .ctcard')) && / · Betrifft/.test(txt(d, '#view .ctcard'))), '#6116 freelancer: the card\'s task says "Betrifft"');
  check(!/Über Kalmido/.test(txt(d, '#view .ctcard')), '#6116 freelancer: no "Über Kalmido" on the card');
  w.close();

  console.log(`p21165_b_contacts_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
