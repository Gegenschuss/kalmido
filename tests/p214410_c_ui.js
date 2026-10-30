// 2.144.10 part C UI test (#2576), own container (start.sh): trial documents in the office. 2.417.0 C (#3445): trial documents
// come from the test mode only (setting trial_mode, per person and office): "New quotation" / "Empty invoice" create at once,
// in the test mode as a trial document (tag "Trial" in the list and the editor head, TEST number); the list filter All /
// Real only / Trial only and the count line only while the test mode is on; "Delete all trial documents" sits in the test
// mode section of the office settings (admins) with a confirmation naming the number. Run for a member of an organisation
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
    const mode = async on => { const st = await call(ck, 'GET', '/api/office/settings'); return call(ck, 'PATCH', '/api/settings', {set_delta: {trial_mode: on ? {add: [String(st.org_id)]} : {remove: [String(st.org_id)]}}}); };
    let w = await boot({user, hash: 'office/offers'}), d = w.document;
    w.confirm = m => { asked.push(String(m)); return true; };
    check(await until(() => d.querySelector('.office .ofdbar')), `${who}: the quotation list`);
    check(await until(() => w.eval('Array.isArray(OFD.list) && !OFD.loading && OFD.first != null')), `${who}: the list has loaded`);
    check(!d.querySelector('#ofd-trial') && !d.querySelector('.tri-bar') && !d.querySelector('.tri-strip'), `${who}: test mode off: no trial filter / count line / strip`);
    // 2.308.0 (#3251): the list drawn into a box inside the tab body (the personal-office hint) must not wire the clicks a second time
    { const body = d.querySelector('.office .ofcbody'), box = d.createElement('div'); box.className = 'pboffers'; body.appendChild(box);
      w.eval('ofdOffersTab(document.querySelector(".office .ofcbody .pboffers"))');
      check(!!body._ofd && !box._ofd, `${who}: the click listeners sit on the tab body only`);
      box.remove(); }
    // ================= test mode off: "New quotation" creates a real draft at once
    d.querySelector('.office [data-ofd="new"]').click();
    check(await until(() => d.querySelector('.ofdeditor') && +w.eval('S.route.id')), `${who}: "New quotation" opens the new draft at once`);
    check(!d.querySelector('.modal') && !d.querySelector('.ofdhead .tri-tag'), `${who}: no dialog, a real quotation`);
    const real = await call(ck, 'GET', '/api/office/docs/' + w.eval('S.route.id'));
    check(real.kind === 'offer' && !real.trial && !/^TEST/.test(real.number || ''), `${who}: a real quotation ${real.kind} ${real.trial} ${real.number}`);
    w.close();

    // ================= test mode on (2.417.0 C, #3445): "New quotation" is a trial one
    check((await mode(true)).http < 300, `${who}: test mode on`);
    w = await boot({user, hash: 'office/offers'}); d = w.document;
    w.confirm = m => { asked.push(String(m)); return true; };
    check(await until(() => d.querySelector('.office .tri-strip')), `${who}: the test mode strip`);
    await until(() => d.querySelector('.office .ofdbar [data-ofd="new"]') && w.eval('Array.isArray(OFD.list) && !OFD.loading'));
    d.querySelector('.office .ofdbar [data-ofd="new"]').click();
    check(await until(() => d.querySelector('.ofdeditor') && d.querySelector('.ofdhead .tri-tag')), `${who}: the trial quotation opens with "Trial" in the editor head`);
    check(!d.querySelector('.modal'), `${who}: no create dialog`);
    const tid = w.eval('S.route.id');
    const T = await call(ck, 'GET', '/api/office/docs/' + tid);
    check(T.trial === true && /^TEST-\d+/.test(T.number || ''), `${who}: a trial quotation with a TEST number ${T.trial} ${T.number}`);
    w.location.hash = '#office/offers/offer';
    await until(() => d.querySelector('.office .ofdlist'));

    // ================= the list: tag, filter, count line
    check(await until(() => d.querySelector(`.ofdrow[data-id="${tid}"] .tri-tag`)), `${who}: the list tags the trial quotation`);
    check(!d.querySelector(`.ofdrow[data-id="${real.id}"] .tri-tag`), `${who}: the real one has no tag`);
    check(/1 trial document in this office/.test(d.querySelector('.tri-bar')?.textContent || '') && !d.querySelector('.tri-bar [data-ofd="tri-del-all"]'), `${who}: the count line, without "Delete all" (moved to the settings)`);
    const sel = await until(() => d.querySelector('#ofd-trial'));
    check(!!sel, `${who}: the trial filter`);
    pick(w, sel, '1');
    check(await until(() => d.querySelector(`.ofdrow[data-id="${tid}"]`) && !d.querySelector(`.ofdrow[data-id="${real.id}"]`)), `${who}: filter "Trial only"`);
    pick(w, d.querySelector('#ofd-trial'), '0');
    check(await until(() => d.querySelector(`.ofdrow[data-id="${real.id}"]`) && !d.querySelector(`.ofdrow[data-id="${tid}"]`)), `${who}: filter "Real only"`);
    pick(w, d.querySelector('#ofd-trial'), '');
    check(await until(() => d.querySelector(`.ofdrow[data-id="${real.id}"]`) && d.querySelector(`.ofdrow[data-id="${tid}"]`)), `${who}: filter "All"`);

    // ================= invoices: "Empty invoice" in the test mode is a trial invoice; no trial entry in the menu
    w.location.hash = '#office/invoices';  // 2.380.0 (#3409): the invoices' own area
    const ni = await until(() => d.querySelector('.office [data-ofd="new-inv"]'));
    ni.click();
    await until(() => items(d).length);
    check(!items(d).some(b => /Trial document/.test(b.textContent)), `${who}: no trial entry in "New invoice"`);
    items(d).find(b => b.textContent.trim() === 'Empty invoice')?.click();
    check(await until(() => d.querySelector('.ofdeditor') && d.querySelector('.ofdhead .tri-tag') && w.eval('OFD.doc?.kind') === 'invoice'), `${who}: a trial invoice opens with the tag`);
    const iid = w.eval('S.route.id');
    check((await call(ck, 'GET', '/api/office/docs/' + iid)).trial === true, `${who}: the invoice is a trial one`);
    w.close();

    // ================= "Delete all trial documents" in the settings: confirmation with the number, real documents stay
    w = await boot({user, hash: 'office/settings'}); d = w.document;
    w.confirm = m => { asked.push(String(m)); return true; };
    w.eval(`LS.set('ofcSetSub', 'docs'); ost_show('docs')`);
    const del = await until(() => { const b = d.querySelector('#tri-del-all'); return b && !b.hidden && b; }, 60);
    check(!!del && /2 trial documents/.test(del.textContent), `${who}: the admin sees "Delete all 2 trial documents" ${del?.textContent}`);
    asked.length = 0;
    del?.click();
    check(await until(async () => (await call(ck, 'GET', '/api/office/docs/' + tid)).http === 404 && (await call(ck, 'GET', '/api/office/docs/' + iid)).http === 404), `${who}: the trial documents are gone`);
    check(asked.some(m => /2 trial documents/.test(m)), `${who}: the confirmation names the number ${asked.join(' || ')}`);
    check((await call(ck, 'GET', '/api/office/docs/' + real.id)).http === 200, `${who}: the real quotation stays`);
    check(await until(() => d.querySelector('#tri-del-all')?.hidden), `${who}: the button is gone afterwards`);
    w.close();
    check((await mode(false)).http < 300, `${who}: test mode off again`);
  }

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
