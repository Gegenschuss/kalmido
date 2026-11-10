// 2.892.0 A (#5449, #5455) Polish office, own container (start.sh). Invented data only.
// kalmido-suite: fresh
// - #5455 (jsdom, with and without an organisation): the fixed-cost dialog (cash flow): Cancel left of the main button, Delete
//   "danger solid" left of the spacer; Cancel closes without a change, Delete removes the entry; the PDF question of a draft
//   (askDialog): Cancel | Show as draft | Finalise now; a destructive confirmation is a danger dialog (Cancel focused)
// - #5455 (Firefox, phone 360 px): the delete dialog: Cancel left of the main button, Delete solid red, all on the screen
// - #5449 (Firefox, phone): a new office (no country yet): the big country card only on the start page; Quotations and
//   Receipts show the slim line whose button leads to the start page; the second choice has a visible label
// Screenshots into $P2892A_SHOTS.
// freelancer-matrix: office (frida and gina have no organisation)
// usage: node p2892_a_office_ui.js <datadir>
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2892_a', check, shots: 'P2892A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,office,clients';
const labels = foot => [...foot.querySelectorAll('button')].map(b => b.textContent.trim());

async function run(user, ck, tag) {
  await call('GET', '/api/office/settings', null, ck);
  await call('PUT', '/api/office/settings', {lang: 'en'}, ck);
  const mk = await call('POST', '/api/office/fixed-costs', {label: 'Beispielmiete', amount: 500, repeat: 'monthly', start: '2026-01-01'}, ck);
  check(mk.http === 201 && mk.id, `${tag}: fixed cost created ` + mk.http);
  const w = await boot({user, hash: 'office/cashflow'}), d = w.document;
  await until(() => typeof w.rk_fixedModal === 'function' && d.querySelector('.office'), 60);
  const items = () => call('GET', '/api/office/fixed-costs', null, ck).then(j => j.items || []);
  const f = (await items()).find(x => x.id === mk.id);
  w.rk_fixedModal(f);
  let md = await until(() => d.querySelector('.modal.ofcdlg'), 30);
  const foot = md && md.querySelector('.foot');
  check(foot && labels(foot).filter(x => !/^Move/.test(x)).join('|') === 'Delete|Cancel|Save', `${tag}: foot order Delete | Cancel | Save ` + (foot && labels(foot)));
  check(foot && foot.querySelector('[data-m="del"]').matches('.danger.solid') && foot.querySelector('[data-m="save"]').matches('.pri') && foot.querySelector('.spacer'), `${tag}: Delete is danger solid, Save is the main button`);
  const kids = [...foot.children];
  check(kids.indexOf(foot.querySelector('[data-m="close"]')) < kids.indexOf(foot.querySelector('[data-m="save"]')) && kids.indexOf(foot.querySelector('[data-m="save"]')) === kids.length - 1, `${tag}: Cancel left of the main button, the main button last`);
  click(w, foot.querySelector('[data-m="close"]'));
  await until(() => !d.querySelector('.modal.ofcdlg'), 30);
  check(!d.querySelector('.modal.ofcdlg') && (await items()).some(x => x.id === mk.id), `${tag}: Cancel closes the dialog and changes nothing`);
  w.rk_fixedModal(f);
  md = await until(() => d.querySelector('.modal.ofcdlg'), 30);
  click(w, md.querySelector('[data-m="del"]'));
  await until(() => !d.querySelector('.modal.ofcdlg'), 30);
  let gone = false; for (let i = 0; i < 30 && !gone; i++) { gone = !(await items()).some(x => x.id === mk.id); if (!gone) await sleep(150); }
  check(gone, `${tag}: Delete removes the entry`);

  // the PDF question of a draft
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'}, ck)).id;
  const q = await call('POST', '/api/office/docs', {client_id: CL, project_title: 'Imagefilm', items: [{title: 'Konzept', qty: 1, rate: 800}]}, ck);
  const p = w.ofdPdfAsk();
  const pa = await until(() => d.querySelector('.modal.ofdpa'), 30);
  const pf = pa.querySelector('.foot');
  check(labels(pf).join('|') === 'Cancel|Show as draft|Finalise now', `${tag}: PDF question order ` + labels(pf));
  check(pf.querySelector('[data-cd="yes"]').matches('.pri') && d.activeElement !== pf.querySelector('[data-pa="draft"]'), `${tag}: main button Finalise now, focus not on the draft button`);
  click(w, pf.querySelector('[data-cd="no"]'));
  check(await p === null && q.http === 201, `${tag}: Cancel gives null`);
  const p2 = w.ofdPdfAsk(); click(w, (await until(() => d.querySelector('.modal.ofdpa [data-pa="draft"]'), 30)));
  check(await p2 === 'draft', `${tag}: Show as draft gives "draft"`);
  const p3 = w.ofdPdfAsk(); click(w, (await until(() => d.querySelector('.modal.ofdpa [data-cd="yes"]'), 30)));
  check(await p3 === 'final', `${tag}: Finalise now gives "final"`);

  // a destructive confirmation is a danger dialog (Cancel focused, solid red main button)
  const c = w.eval("askConfirm('Delete this entry?', '', {ok: 'Delete', danger: true})");
  const cd = await until(() => d.querySelector('.modal.cdlg'), 30);
  check(cd.querySelector('[data-cd="yes"]').matches('.danger.solid') && labels(cd.querySelector('.foot')).join('|') === 'Cancel|Delete', `${tag}: confirmation: Cancel | Delete (danger solid)`);
  click(w, cd.querySelector('[data-cd="no"]'));
  check(await c === false, `${tag}: Cancel of a confirmation gives false`);
  w.close();
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Beispiel Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await run('alice', CK, 'org');
  // two people without an organisation (freelancer-matrix: office): frida with documents, gina with a new, empty office
  for (const u of ['frida', 'gina']) check((await call('POST', '/api/users', {username: u, display_name: u, password: 'password123', email: u + '@example.com', orgs: []})).http < 300, 'user ' + u);
  const FK = await login('frida'), GK = await login('gina');
  for (const k of [FK, GK]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, k);
  await run('frida', FK, 'freelancer');

  await call('PUT', '/api/office/settings', {pack: 'DE', company_fields: {name: 'Studio Beispiel', street: 'Hafenstrasse 12', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}}, FK);
  const FC = (await call('POST', '/api/office/fixed-costs', {label: 'Beispielmiete', amount: 500, repeat: 'monthly', start: '2026-01-01'}, FK)).id;
  check(!!FC, 'a fixed cost for the phone dialog');

  const signIn = (ev, user) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  const R = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const b = e.getBoundingClientRect(); return b.width || b.height ? {top: b.top, bottom: b.bottom, left: b.left, right: b.right, h: b.height} : null; })()`;
  // a solid red button: its background is red (not transparent), its text readable on it
  const RED = sel => `(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return null; const m = getComputedStyle(b).backgroundColor.match(/\\d+(\\.\\d+)?/g); if (!m) return null; const [r, g, bl, a = 1] = m.map(Number); return {bg: getComputedStyle(b).backgroundColor, red: a > 0.5 && r > g + 60 && r > bl + 60}; })()`;
  // Cancel left of the main button, both whole on the 360 px screen
  const ORDER = (no, yes) => `(() => { const a = document.querySelector(${JSON.stringify(no)}), b = document.querySelector(${JSON.stringify(yes)}); if (!a || !b) return null; const x = a.getBoundingClientRect(), y = b.getBoundingClientRect(); return {left: x.right <= y.left + 1, onScreen: x.left >= 0 && y.right <= innerWidth && x.width > 0 && y.width > 0, no: x.left, yes: y.left}; })()`;


  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev, 'frida') === 200, 'phone: frida signed in');
    // ================= #5455: the delete dialog on a phone: Cancel left of the main button, Delete solid red
    await nav(B + '#office/cashflow');
    check(await until(`typeof rk_fixedModal === 'function' && !!document.querySelector('.office')`, {timeout: 20000}), 'phone: the cash flow page');
    await ev(`api('GET', '/api/office/fixed-costs').then(j => { rk_fixedModal((j.items || []).find(x => x.id === ${FC})); return 1; })`);
    check(await until(`!!document.querySelector('.modal.ofcdlg [data-m="del"]')`), '#5455 phone: the fixed cost dialog opens');
    const o1 = await ev(ORDER('.modal.ofcdlg [data-m="close"]', '.modal.ofcdlg [data-m="save"]'));
    check(o1 && o1.left && o1.onScreen, '#5455 phone: Cancel left of Save, both on the screen ' + JSON.stringify(o1));
    const r1 = await ev(RED('.modal.ofcdlg [data-m="del"]'));
    check(r1 && r1.red, '#5455 phone: Delete is solid red ' + JSON.stringify(r1));
    await shot('p2892a-handy-loeschen-dialog.png');
    await ev(`(() => { document.querySelector('.modal.ofcdlg [data-m="close"]').click(); return 1; })()`);
    check(await until(`!document.querySelector('.modal.ofcdlg')`), '#5455 phone: Cancel closes the dialog');
    // a delete confirmation (askConfirm with danger): Cancel left, the red main button right, Cancel has the focus
    await ev(`(() => { window.__cf = askConfirm('Delete this entry?', '', {ok: 'Delete', danger: true}); return 1; })()`);
    check(await until(`!!document.querySelector('.modal.cdlg [data-cd="yes"]') && document.activeElement === document.querySelector('.modal.cdlg [data-cd="no"]')`), '#5455 phone: the confirmation opens with the focus on Cancel');
    const o2 = await ev(ORDER('.modal.cdlg [data-cd="no"]', '.modal.cdlg [data-cd="yes"]')), r2 = await ev(RED('.modal.cdlg [data-cd="yes"]'));
    check(o2 && o2.left && o2.onScreen && r2 && r2.red, '#5455 phone: confirmation Cancel | Delete (red) ' + JSON.stringify({o2, r2}));
    await shot('p2892a-handy-loeschen-frage.png');
    await ev(`(() => { document.querySelector('.modal.cdlg [data-cd="no"]').click(); return 1; })()`);
    check(await ev(`window.__cf.then(v => v === false)`), '#5455 phone: Cancel answers no');

    // ================= #5449: gina's new office (no country yet): the big card only on the phone's start page
    await nav(B + 'static/icon.svg');  // a new page load: the app must not keep frida's office in memory
    check(await signIn(ev, 'gina') === 200, 'phone: gina signed in');
    await nav(B + '#office/offers');
    check(await until(`!!document.querySelector('#view .ocf-choose')`, {timeout: 20000}), '#5449 phone: the country question shows on Quotations');
    check(await ev(`!!document.querySelector('#view .ocf-choose.ocf-slim') && !document.querySelector('#view .ocf-choose:not(.ocf-slim)')`), '#5449 phone: Quotations shows the slim line, not the big card');
    check(await ev(`document.querySelector('#view .ocf-slim [data-go]')?.dataset.go === 'office/start' && /Select country/.test(document.querySelector('#view .ocf-slim').textContent)`), '#5449 phone: its button "Select country" leads to the start page');
    const slim = await ev(R('#view .ocf-slim'));
    check(slim && slim.h < 100, '#5449 phone: the slim line stays small: ' + JSON.stringify(slim));
    await shot('p2892a-handy-angebote-leer.png');
    await nav(B + '#office/receipts');
    check(await until(`!!document.querySelector('#view .ocf-slim')`, {timeout: 20000}) && await ev(`!document.querySelector('#view .ocf-choose:not(.ocf-slim)')`), '#5449 phone: Receipts shows the slim line too');
    await ev(`(() => { document.querySelector('#view .ocf-slim [data-go]').click(); return 1; })()`);
    check(await until(`location.hash === '#office/start' && !!document.querySelector('#view .ocf-choose:not(.ocf-slim) #ocf-ch')`), '#5449 phone: the button opens the start page with the big card ' + await ev('location.hash'));
    const lab = await ev(`(() => { const l = document.querySelector('#view .ocf-choose label[for="ocf-eb"]'), s = document.querySelector('#ocf-eb'); if (!l || !s) return null; const a = l.getBoundingClientRect(), b = s.getBoundingClientRect(); return {t: l.textContent.trim(), w: a.width, above: a.bottom <= b.top + 2}; })()`);
    check(lab && /Basis of the income statement/.test(lab.t) && lab.w > 0 && lab.above, '#5449 phone: the second choice has a visible name above it ' + JSON.stringify(lab));
    await shot('p2892a-handy-start-leer.png');
  }, true);

  console.log(`p2892_a_office_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
