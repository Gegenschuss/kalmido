// kalmido-suite: fresh
// 2.501.0 (#4296) UI test (jsdom, own container, mode workspaces; invented data only): the four importers of #2934 ask for the target
// before they store anything, seen by behaviour (tests/p2356_b_import_target_test.py only reads their source): each is driven to its
// real store step with the shared question stubbed: "no" = no storing request, "yes" = the request goes out after the question.
// freelancer-matrix: office  tenant-matrix: office
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, idle, until, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2501BUI_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const FEAT = 'cal,comments,collab,office,clients';
const camt = `<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Ntry><Amt Ccy="EUR">12.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>${TC.today()}</Dt></BookgDt><AcctSvcrRef>P2501B-0</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Dbtr><Pty><Nm>Kunde Beispiel</Nm></Pty></Dbtr></RltdPties><RmtInf><Ustrd>Zahlung</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>`;
const COMPANY = {name: 'Beispiel GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE', vat_id: 'DE123456789', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'};

// the storing requests, in a list the page cannot lose (fetch is wrapped before the app starts); the previews do not count
const watch = x => { x.__log = []; const f0 = x.fetch; x.fetch = (u, o = {}) => {
  const url = String(u);
  if ((o.method || 'GET') === 'POST' && /\/import|\/consent\/import/.test(url) && !/preview/.test(url) && (!/leads\/import/.test(url) || /"commit":\s*true/.test(String(o.body || '')))
      && !(/consent\/import/.test(url) && !/"apply":\s*true/.test(String(o.body || '')))) x.__log.push('post ' + url);
  return f0(u, o); }; };

async function importer(w, who, name, open, go, url) {
  const d = w.document;
  w.eval(`window.__ask = []; window.__ans = false; importTargetConfirm = async o => { __log.push('ask'); __ask.push(o); return __ans; };`);
  w.__log.length = 0;
  await open(d);
  const btn = await until(() => go(d));
  check(btn, `${who} ${name}: the dialog reaches its store button`);
  if (!btn) return null;
  btn.click();
  check(await until(() => w.__log.includes('ask')), `${who} ${name}: the question comes`);
  await idle(w);
  check(w.__log.join() === 'ask', `${who} ${name}: "no" stores nothing: ${w.__log.join()}`);
  w.__log.length = 0; w.eval(`__ans = true`);
  const again = await until(() => { const b = go(d); return b && !b.disabled ? b : null; });
  check(again, `${who} ${name}: after "no" the button works again`);
  if (!again) return null;
  again.click();
  check(await until(() => w.__log.some(x => x.startsWith('post ') && url.test(x))), `${who} ${name}: "yes" sends the import: ${w.__log.join()}`);
  check(w.__log[0] === 'ask', `${who} ${name}: the question before the request: ${w.__log.join()}`);
  await idle(w);
  return w.eval(`__ask[0]`);
}

async function all(user, who, isOrg) {
  const w = await boot({user, hash: 'today', setup: watch});
  const ws = o => check(o && (isOrg ? String(o.ws).startsWith('org:') : !String(o.ws || 'private').startsWith('org:')), `${who}: the question names the right workspace: ${o && o.ws}`);
  ws(await importer(w, who, 'bank statement', () => w.eval(`bnkImpModal(${JSON.stringify(camt)}, 'auszug.xml')`),
    d => d.querySelector('.foot button.pri[data-bi]'), /office\/bank\/import/));
  [...w.document.querySelectorAll('[data-bi="close"]')].forEach(b => b.click());
  ws(await importer(w, who, 'DATEV', () => w.eval(`dimp_dialog(); DIMP.file = new File(['x'], 'datev.csv', {type: 'text/csv'});`),
    d => [...d.querySelectorAll('[data-m="ok"]')].pop(), /office\/datev\/import/));
  [...w.document.querySelectorAll('[data-m="close"]')].forEach(b => b.click());
  const csv = 'Name,E-Mail\\nNeu GmbH,neu-' + who + '@example.com\\n';
  ws(await importer(w, who, 'leads', () => w.eval(`leadImpModal('${csv}', {count: 1, rows: [{title: 'Neu GmbH', contact: 'Neu GmbH', email: 'neu-${who}@example.com'}]})`),
    d => d.querySelector('[data-li="go"]'), /office\/leads\/import/));
  [...w.document.querySelectorAll('[data-li="close"]')].forEach(b => b.click());
  // the newsletter consents: its handler sits on the document, its dialog is only the frame of the button
  await importer(w, who, 'newsletter consents', d => { w.eval(`NWL.ws = ${JSON.stringify(isOrg ? w.eval('S.settings.workspace') : 'private')}; NWL.imp = {text: 'email\\nkontakt-${who}@example.com\\n', name: 'consents.csv'};`);
    if (!d.querySelector('.nwl-md')) d.body.insertAdjacentHTML('beforeend', '<div class="nwl-md"><button type="button" data-nwl="imp-go">Go</button></div>'); },
  d => d.querySelector('.nwl-md [data-nwl="imp-go"]'), /newsletter\/consent\/import/);
  w.close();
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'PUT', '/api/office/settings', {company_fields: COMPANY});
  // a person without an organisation: the same importers in the private office
  const u = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', orgs: []});
  check(u.id, 'setup: frida ' + JSON.stringify(u).slice(0, 160));
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CF, 'PUT', '/api/office/settings', {company_fields: COMPANY});

  await all('alice', 'org', true);
  await all('frida', 'frei', false);

  // 2.501.0 (#4296): a module that does not load stops a suite: tests/boot.js throws, tests/ff.js fails a check; a window started
  // offline on purpose may fail. ld_all is replaced as soon as the page has it, the helper itself stays the real one
  const breakIt = x => { const t = x.setInterval(() => { if (typeof x.ld_all === 'function') { x.ld_all = () => Promise.reject(new Error('planned')); x.clearInterval(t); } }, 1); };
  const stop = await boot({user: 'alice', hash: 'today', setup: breakIt}).then(w => { w.close(); return ''; }, e => e.message);
  check(/ld_all failed: planned/.test(stop), 'boot.js: a rejected ld_all stops the suite: ' + stop);
  const off = await boot({user: 'alice', hash: 'today', setup: x => { breakIt(x); x.__offline = true; }}).then(w => { w.close(); return 'started'; }, e => e.message);
  check(off === 'started', 'boot.js: a window started offline on purpose may fail: ' + off);
  const seen = [];
  await require('./ff')({tag: 'p2501_b_ff', check: (c, m) => { if (!c) seen.push(m); }})(async ({cmd, nav}) => {
    await cmd('script.addPreloadScript', {functionDeclaration: `() => { const t = setInterval(() => { if (typeof window.ld_all === 'function') { window.ld_all = () => Promise.reject(new Error('planned')); clearInterval(t); } }, 1); }`});
    await nav(B);
  });
  check(seen.some(m => /ld_all failed .*planned/.test(m)), 'ff.js: a rejected ld_all fails a check: ' + seen.join(' | '));

  console.log(`p2501_b_import_target_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
