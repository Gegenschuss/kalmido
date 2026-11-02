// kalmido-suite: fresh
// 2.470.0 (#3596, part A) UI tests: the bank accounts in Settings > Company & office > Bank & taxes. Own container (start.sh), jsdom,
// invented data only. freelancer-matrix: office
// - without accounts the company fields show IBAN and BIC; a saved IBAN makes the account, the list shows it as the default
// - with accounts the fields are gone (a link instead) and "Save all" leaves the bank data alone
// - new account, set as default, archive with undo; the settings search finds "IBAN" under Bank accounts
// - the same for a person without an organisation; a member sees no list
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); let j = null; try { j = await r.json(); } catch { j = null; } return {http: r.status, ...(j || {})}; };
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,files,docs,office,clients';
const BA = '/api/office/settings/bank-accounts';
const IBAN1 = 'DE02120300000000202051', IBAN2 = 'DE89370400440532013000';

const form = async who => {
  const w = await boot({user: who, hash: 'today'}), d = w.document;
  await until(() => d.querySelector('#side, main'));
  w.eval(`settingsModal('biz')`);
  await until(() => d.querySelector('.smodal #s-biz #ofc-set'), 100);
  return {w, d};
};

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
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'}, CK);
  await call('PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'}, CK);
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${org.id}`}, BCK);
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'}, FCK);

  for (const [who, ck] of [['alice', CK], ['frida', FCK]]) {
    let {w, d} = await form(who);
    check(!!d.querySelector('#ofc-set #osc-iban'), `${who}: without accounts the company fields offer the IBAN`);
    check(!!await until(() => d.querySelector('#ofc-set .bkaset .bkaempty')), `${who}: the area Bank accounts, empty`);
    // the settings search
    const sq = d.querySelector('#s-search');
    sq.dispatchEvent(new w.FocusEvent('focus')); sq.value = 'iban'; sq.dispatchEvent(new w.Event('input', {bubbles: true}));
    const hs = [...d.querySelectorAll('#s-sres [data-hit]')].map(b => b.textContent);
    check(hs.some(t => t.includes('Bank accounts')), `${who}: search "iban" finds Bank accounts ` + JSON.stringify(hs));
    sq.value = ''; sq.dispatchEvent(new w.Event('input', {bubbles: true}));
    // a new account through the dialog: a wrong IBAN is said in the dialog, the right one lands in the list
    click(w, d.querySelector('[data-bka="new"]'));
    const md = await until(() => d.querySelector('.bkadlg'));
    md.querySelector('#bka-label').value = 'Geschäftskonto'; md.querySelector('#bka-iban').value = 'DE00 1234';
    click(w, md.querySelector('[data-bkd="save"]'));
    check(await until(() => md.querySelector('.aerr').textContent.includes('IBAN')), `${who}: a wrong IBAN is refused in the dialog`);
    md.querySelector('#bka-iban').value = IBAN1.replace(/(.{4})/g, '$1 ');
    md.querySelector('[data-bkd="save"]').disabled = false; click(w, md.querySelector('[data-bkd="save"]'));
    const row = await until(() => d.querySelector('.bkalist .bkarow'));
    check(row && /Geschäftskonto/.test(row.textContent) && /Default/.test(row.textContent) && /DE02 1203/.test(row.textContent), `${who}: the account is the default in the list`);
    check(await until(() => !d.querySelector('#ofc-set #osc-iban') && d.querySelector('#ofc-set .ofcco [data-setgo="biz-tax"]')), `${who}: the company fields point to the accounts instead`);
    // the whole form sent without the fields must not empty the bank data
    const body = JSON.parse(w.eval(`JSON.stringify(ofcSettingsBody($('#ofc-set')).company_fields)`));
    check(!('iban' in body) && !('bic' in body) && !('bank_name' in body), `${who}: Save all leaves out the fields not shown ` + JSON.stringify(Object.keys(body)));
    // a second account, default, archive with undo
    const second = await call('POST', BA, {iban: IBAN2, label: 'Rücklagen'}, ck);
    check(second.http === 201, `${who}: a second account`);
    w.eval(`bka_load()`);
    await until(() => d.querySelectorAll('.bkalist .bkarow').length === 2);
    click(w, d.querySelector('[data-bka="default"]'));
    check(await until(async () => (await call('GET', BA, null, ck)).items?.find(x => x.is_default)?.iban === IBAN2), `${who}: set as default from the list`);
    await until(() => [...d.querySelectorAll('.bkalist .bkarow')][0]?.textContent.includes('Rücklagen'));
    click(w, d.querySelector('.bkalist [data-bka="archive"]'));
    check(await until(() => d.querySelectorAll('.bkalist .bkarow').length === 1 && d.querySelector('.bkaold')), `${who}: archived, in the folded part`);
    check(await until(async () => (await call('GET', BA, null, ck)).items?.find(x => x.is_default)?.iban === IBAN1), `${who}: the default went on`);
    w.eval(`histStep('undo')`);
    check(await until(async () => (await call('GET', BA, null, ck)).items?.find(x => x.is_default)?.iban === IBAN2), `${who}: undo brings it back as the default`);
    w.close();
  }
  // a member: no list, nothing asked of the server
  {
    const {w, d} = await form('bob');
    await sleep(600);
    check(!d.querySelector('.bkalist') && !d.querySelector('[data-bka="new"]'), 'a member sees no accounts');
    check(!(d.querySelector('#osc-iban')?.value), 'a member sees no IBAN');
    check((await call('GET', BA, null, BCK)).http === 403, 'the server says no');
    w.close();
  }
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
