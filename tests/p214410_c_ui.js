// 2.144.10 part C UI test (#2576), own container (start.sh): trial documents in the office. "New quotation" opens a small
// dialog with the switch "Just to try" (off, Create focused); the first quotation / invoice of an office shows a hint once
// per person (X or Create remember it in the setting trial_hint_seen, it does not come back after a reload); a trial
// quotation carries the tag "Trial" in the list and the editor head; the list filter All / Real only / Trial only;
// "Delete all trial documents" for admins with a confirmation naming the number. Run for a member of an organisation
// (alice, admin) and a person without one (frida, her own admin). Invented names only.
// freelancer-matrix: office
// P214410C_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P214410C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"]')];
const FEAT = 'clients,office';
const pick = (w, sel, v) => { sel.value = v; sel.dispatchEvent(new w.Event('change', {bubbles: true})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments']});
  const ORG = (await call(CA, 'GET', '/api/state')).me.workspaces[0].id;
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');

  for (const [user, who, ck] of [['alice', 'org', CA], ['frida', 'freelancer', CF]]) {
    const asked = [];
    // ================= the create dialog: switch off, the first-time hint, X remembers it
    let w = await boot({user, hash: 'office/offers'}), d = w.document;
    w.confirm = m => { asked.push(String(m)); return true; };
    check(await until(() => d.querySelector('.office .ofdbar')), `${who}: the quotation list`);
    check(!d.querySelector('#ofd-trial') && !d.querySelector('.tri-delall'), `${who}: no trial filter / delete-all without trial documents`);
    d.querySelector('.office [data-ofd="new"]').click();
    let md = await until(() => d.querySelector('.modal.tri-dlg'));
    check(!!md && !!md.querySelector('#ofd-trial-new') && !md.querySelector('#ofd-trial-new').checked, `${who}: dialog with "Just to try", off by default`);
    check(/TEST number, watermark MUSTER, deletable any time/.test(md?.textContent || ''), `${who}: the explaining line`);
    check(!!md?.querySelector('.tri-hint[data-trial-hint="offer"]'), `${who}: the first-time hint for the first quotation`);
    await sleep(150);
    check(d.activeElement === md?.querySelector('[data-m="ok"]'), `${who}: the focus is on Create (${d.activeElement?.outerHTML?.slice(0, 80)})`);
    md.querySelector('.tri-hint [data-tri="x"]').click();
    check(!md.querySelector('.tri-hint'), `${who}: X removes the hint`);
    const seen = await until(async () => { const s = (await call(ck, 'GET', '/api/state')).settings?.trial_hint_seen; return s && String(s).includes(':offer') && s; });
    check(!!seen, `${who}: the hint is remembered on the server ${seen}`);
    // a trial quotation
    md.querySelector('#ofd-trial-new').checked = true;
    md.querySelector('[data-m="ok"]').click();
    check(await until(() => d.querySelector('.ofdeditor')), `${who}: the editor opens`);
    const tid = w.eval('S.route.id');
    const T = await call(ck, 'GET', '/api/office/docs/' + tid);
    check(T.trial === true && /^TEST-\d+/.test(T.number || ''), `${who}: a trial quotation with a TEST number ${T.trial} ${T.number}`);
    check(await until(() => d.querySelector('.ofdhead .tri-tag')), `${who}: the editor head shows "Trial"`);
    w.close();

    // ================= after a reload the hint does not come back (the office still has no real quotation)
    w = await boot({user, hash: 'office/offers'}); d = w.document;
    w.confirm = m => { asked.push(String(m)); return true; };
    (await until(() => d.querySelector('.office .ofdbar [data-ofd="new"]')))?.click();
    md = await until(() => d.querySelector('.modal.tri-dlg'));
    check(!!md && !md.querySelector('.tri-hint'), `${who}: after a reload the hint does not come back`);
    md?.querySelector('[data-m="close"]')?.click();
    const real = await call(ck, 'POST', '/api/office/docs', {project_title: 'Real film'});
    check(real.http < 300 && !real.trial, `${who}: a real quotation ${real.http}`);
    w.eval('ofdLoadList(true)');

    // ================= the list: tag, filter
    check(await until(() => d.querySelector(`.ofdrow[data-id="${tid}"] .tri-tag`)), `${who}: the list tags the trial quotation`);
    check(!d.querySelector(`.ofdrow[data-id="${real.id}"] .tri-tag`), `${who}: the real one has no tag`);
    const sel = await until(() => d.querySelector('#ofd-trial'));
    check(!!sel, `${who}: the trial filter`);
    pick(w, sel, '1');
    check(await until(() => d.querySelector(`.ofdrow[data-id="${tid}"]`) && !d.querySelector(`.ofdrow[data-id="${real.id}"]`)), `${who}: filter "Trial only"`);
    pick(w, d.querySelector('#ofd-trial'), '0');
    check(await until(() => d.querySelector(`.ofdrow[data-id="${real.id}"]`) && !d.querySelector(`.ofdrow[data-id="${tid}"]`)), `${who}: filter "Real only"`);
    pick(w, d.querySelector('#ofd-trial'), '');
    check(await until(() => d.querySelector(`.ofdrow[data-id="${real.id}"]`) && d.querySelector(`.ofdrow[data-id="${tid}"]`)), `${who}: filter "All"`);

    // ================= invoices: the "Empty invoice" dialog has the switch and its own first-time hint (Create remembers it)
    d.querySelector('.ofdkinds [data-kind="invoice"]').click();
    const ni = await until(() => d.querySelector('.office [data-ofd="new-inv"]'));
    ni.click();
    await until(() => items(d).length);
    items(d).find(b => b.textContent.trim() === 'Empty invoice')?.click();
    md = await until(() => d.querySelector('.modal.tri-dlg'));
    check(!!md?.querySelector('#ofd-trial-new') && !!md.querySelector('.tri-hint[data-trial-hint="invoice"]'), `${who}: the invoice dialog with switch + first-time hint`);
    md.querySelector('#ofd-trial-new').checked = true;
    md.querySelector('[data-m="ok"]').click();
    check(await until(() => d.querySelector('.ofdeditor') && d.querySelector('.ofdhead .tri-tag')), `${who}: a trial invoice opens with the tag`);
    const iid = w.eval('S.route.id');
    check((await call(ck, 'GET', '/api/office/docs/' + iid)).trial === true, `${who}: the invoice is a trial one`);
    check(await until(async () => String((await call(ck, 'GET', '/api/state')).settings?.trial_hint_seen || '').includes(':invoice')), `${who}: Create remembered the invoice hint`);
    w.close();

    // ================= "Delete all trial documents": confirmation with the number, real documents stay
    w = await boot({user, hash: 'office/offers'}); d = w.document;
    w.confirm = m => { asked.push(String(m)); return true; };
    const del = await until(() => d.querySelector('.tri-bar [data-ofd="tri-del-all"]'));
    check(!!del, `${who}: the admin sees "Delete all trial documents"`);
    asked.length = 0;
    del?.click();
    check(await until(async () => (await call(ck, 'GET', '/api/office/docs/' + tid)).http === 404 && (await call(ck, 'GET', '/api/office/docs/' + iid)).http === 404), `${who}: the trial documents are gone`);
    check(asked.some(m => /2 trial documents/.test(m)), `${who}: the confirmation names the number ${asked.join(' || ')}`);
    check((await call(ck, 'GET', '/api/office/docs/' + real.id)).http === 200, `${who}: the real quotation stays`);
    check(await until(() => !d.querySelector('.tri-bar') && !d.querySelector('#ofd-trial')), `${who}: no delete-all line and no filter left`);
    w.close();
  }

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
