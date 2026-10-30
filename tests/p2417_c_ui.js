// 2.417.0 part C UI tests (#3445 test mode, #2604), own container (start.sh). jsdom, invented data only, run for a member of
// an organisation (alice, admin; bob, member) and a person without one (frida, her own admin, phone width):
// - test mode off (default): one click on "New quotation" / "Empty invoice" = a real draft, no dialog, no trial menu, no
//   trial filter / count line / strip, even when the office has trial documents
// - the switch "Test mode" in the office settings (section Documents): on = the strip "Test mode - …" above the office with
//   "Switch off", a new quotation / invoice is a trial one, the list has the filter All / Real only / Trial only and the line
//   "N trial documents"; "Switch off" in the strip: strip, filter and line gone, the filter's memory (LS ofdTrial) reset,
//   the setting empty again, the next new quotation a real one
// - the test mode is personal: alice's switch leaves bob's office without strip; bob (member) sees the switch, not "Delete all"
// - "Delete all N trial documents" in the settings (admin) with the count, real documents stay
// - #2604: a finalised invoice offers no Delete in its menu (p2162_a_ui has the rest)
// freelancer-matrix: office
// kalmido-suite: fresh
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"], .sheet [role="menuitem"]')];
const FEAT = 'clients,office';
const COMPANY = {name: 'Studio Example GmbH', street: 'Hafenweg 1', zip: '20457', city: 'Hamburg', country: 'de', tax_number: '12/345/67890', vat_id: 'DE999999999', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Example Bank'};
const modes = async ck => { const v = (await call(ck, 'GET', '/api/state')).settings?.trial_mode; try { return JSON.parse(v || '[]'); } catch { return v; } };
const listed = w => w.eval('Array.isArray(OFD.list) && !OFD.loading');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments']});
  const ORG = (await call(CA, 'GET', '/api/state')).me.workspaces[0].id;
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  await call(CA, 'POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  for (const ck of [CA, CF]) await call(ck, 'PUT', '/api/office/settings', {company_fields: COMPANY, lang: 'en'});
  const C = await call(CA, 'POST', '/api/clients', {name: 'Example Client AG', street: 'Marktstrasse 5', zip: '50667', city: 'Koeln', country: 'DE', org_id: ORG});

  for (const [user, who, ck, mobile] of [['alice', 'org', CA, false], ['frida', 'freelancer', CF, true]]) {
    // an old trial document exists (made by an agent or before 2.417): with the test mode off it only carries its tag
    const old = await call(ck, 'POST', '/api/office/docs', {kind: 'offer', project_title: 'Old trial', trial: true});
    check(old.trial === true, `${who}: an old trial quotation ${old.http}`);
    // ================= test mode off: one click = a real draft, no trial filter / line / strip / menu
    let w = await boot({user, hash: 'office/offers', mobile}), d = w.document;
    check(await until(() => d.querySelector('.office .ofdbar') && listed(w)), `${who}: the quotation list`);
    check(await until(() => d.querySelector(`.ofdrow[data-id="${old.id}"] .tri-tag`)), `${who}: the old trial quotation keeps its tag`);
    check(!d.querySelector('#ofd-trial') && !d.querySelector('.tri-bar') && !d.querySelector('.tri-strip') && !d.querySelector('[data-ofd="new-more"]'),
      `${who}: test mode off: no filter, no count line, no strip, no trial menu`);
    d.querySelector('.office .ofdbar [data-ofd="new"]').click();
    check(await until(() => d.querySelector('.ofdeditor') && +w.eval('S.route.id') > old.id), `${who}: one click opens a new draft`);
    check(!d.querySelector('.modal'), `${who}: no dialog`);
    const real = await call(ck, 'GET', '/api/office/docs/' + w.eval('S.route.id'));
    check(real.trial === false, `${who}: a real quotation ${real.trial} ${real.number}`);
    w.close();

    // ================= the switch in the settings (section Documents)
    w = await boot({user, hash: 'office/settings', mobile}); d = w.document;
    w.eval(`LS.set('ofcSetSub', 'docs')`);
    const sw = await until(() => { const x = d.querySelector('#tri-mode'); if (x && x.closest('[data-ostp]')?.hidden) w.eval(`ost_show('docs')`); return x; }, 60);
    check(!!sw && !sw.checked && !sw.disabled, `${who}: the switch "Test mode", off`);
    check(/TEST number/.test(sw?.closest('.tri-row')?.textContent || ''), `${who}: the switch says what it does`);
    sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
    check(await until(async () => (await modes(ck)).length === 1), `${who}: the setting is saved (one office) ${JSON.stringify(await modes(ck))}`);
    check(await until(() => d.querySelector('.office .tri-strip')), `${who}: the strip appears above the office`);
    check(/Test mode - documents get a TEST number and the watermark MUSTER/.test(d.querySelector('.tri-strip')?.textContent || ''), `${who}: the strip text`);
    const del = await until(() => { const b = d.querySelector('#tri-del-all'); return b && !b.hidden && b; }, 60);
    check(!!del && /1 trial document/.test(del.textContent), `${who}: "Delete 1 trial document" in the settings ${del?.textContent}`);
    // review F4: a save the server refuses puts the test mode back on (no optimistic "off" left behind)
    w.eval(`window.__api = api; api = async (m, u, b) => { if (m === 'PATCH' && u === '/api/settings') throw new Error('refused'); return window.__api(m, u, b); }`);
    await w.eval(`tri_set(false)`);
    check(w.eval('tri_on()') === true, `${who}: review F4: a refused save keeps the test mode on`);
    w.eval(`api = window.__api`);
    w.close();

    // ================= test mode on: a new quotation and an empty invoice are trial ones; filter + count line
    w = await boot({user, hash: 'office/offers', mobile}); d = w.document;
    check(await until(() => d.querySelector('.office .tri-strip') && listed(w)), `${who}: the strip on the quotation list`);
    check(await until(() => d.querySelector('#ofd-trial')) && /1 trial document/.test(d.querySelector('.tri-bar')?.textContent || ''), `${who}: filter and count line`);
    d.querySelector('.office .ofdbar [data-ofd="new"]').click();
    check(await until(() => d.querySelector('.ofdeditor') && d.querySelector('.ofdhead .tri-tag')), `${who}: the new quotation opens as a trial one`);
    const tq = await call(ck, 'GET', '/api/office/docs/' + w.eval('S.route.id'));
    check(tq.trial === true && /^TEST/.test(tq.number || ''), `${who}: TEST number ${tq.number}`);
    w.location.hash = '#office/invoices';
    const ni = await until(() => d.querySelector('.office [data-ofd="new-inv"]'));
    ni?.click();
    await until(() => items(d).length);
    check(!items(d).some(b => /Trial document/.test(b.textContent)), `${who}: no trial entry in "New invoice"`);
    items(d).find(b => b.textContent.trim() === 'Empty invoice')?.click();
    check(await until(() => d.querySelector('.ofdeditor') && w.eval('OFD.doc?.kind') === 'invoice' && d.querySelector('.ofdhead .tri-tag')), `${who}: the empty invoice is a trial one`);
    // the filter remembers "Trial only" ...
    w.location.hash = '#office/offers/offer';
    const sel = await until(() => listed(w) && d.querySelector('#ofd-trial'));
    sel.value = '1'; sel.dispatchEvent(new w.Event('change', {bubbles: true}));
    check(await until(() => w.eval(`LS.get('ofdTrial', '')`) === '1' && !d.querySelector(`.ofdrow[data-id="${real.id}"]`)), `${who}: "Trial only" filters and is remembered`);
    // ... and "Switch off" in the strip resets it
    d.querySelector('.tri-strip [data-tri="off"]').click();
    check(await until(() => !d.querySelector('.tri-strip')), `${who}: "Switch off" removes the strip`);
    check(await until(() => listed(w) && !d.querySelector('#ofd-trial') && !d.querySelector('.tri-bar') && d.querySelector(`.ofdrow[data-id="${real.id}"]`)), `${who}: no filter, no count line, the real quotation listed again`);
    check(w.eval(`LS.get('ofdTrial', '')`) === '' && w.eval('OFD.trial') === '', `${who}: the filter's memory is reset`);
    check(await until(async () => (await modes(ck)).length === 0), `${who}: the setting is empty again`);
    d.querySelector('.office .ofdbar [data-ofd="new"]').click();
    check(await until(() => d.querySelector('.ofdeditor') && +w.eval('S.route.id') > tq.id), `${who}: a new draft after switching off`);
    check(!d.querySelector('.ofdhead .tri-tag') && (await call(ck, 'GET', '/api/office/docs/' + w.eval('S.route.id'))).trial === false, `${who}: a real one again`);
    w.close();

    // ================= "Delete all" in the settings: with the count, real documents stay
    w = await boot({user, hash: 'office/settings', mobile}); d = w.document;
    w.eval(`LS.set('ofcSetSub', 'docs')`);
    const asked = []; w.confirm = m => { asked.push(String(m)); return true; };
    const da = await until(() => { if (d.querySelector('#tri-mode')?.closest('[data-ostp]')?.hidden) w.eval(`ost_show('docs')`); const b = d.querySelector('#tri-del-all'); return b && !b.hidden && b; }, 60);
    check(!!da && /3 trial documents/.test(da.textContent), `${who}: "Delete all 3 trial documents" ${da?.textContent}`);
    da?.click();
    check(await until(async () => (await call(ck, 'GET', '/api/office/trial')).trial_count === 0), `${who}: all trial documents gone`);
    check(asked.some(m => /3 trial documents/.test(m)), `${who}: the confirmation names the number ${asked.join(' || ')}`);
    check((await call(ck, 'GET', '/api/office/docs/' + real.id)).http === 200, `${who}: the real quotation stays`);
    check(await until(() => d.querySelector('#tri-del-all')?.hidden), `${who}: the button hides afterwards`);
    w.close();
  }

  // ================= personal: alice's test mode leaves bob's office alone; bob sees the switch, not "Delete all"
  const st = await call(CA, 'GET', '/api/office/settings');
  await call(CA, 'PATCH', '/api/settings', {set_delta: {trial_mode: {add: [String(st.org_id)]}}});
  let w = await boot({user: 'bob', hash: 'office/offers'}), d = w.document;
  check(await until(() => d.querySelector('.office .ofdbar') && listed(w)), 'bob: the quotation list');
  check(!d.querySelector('.tri-strip') && !d.querySelector('#ofd-trial'), 'bob: no strip, no filter (alice\'s test mode is hers)');
  w.close();
  w = await boot({user: 'bob', hash: 'office/settings'}); d = w.document;
  w.eval(`LS.set('ofcSetSub', 'docs')`);
  const bsw = await until(() => d.querySelector('#tri-mode'), 60);
  check(!bsw || !d.querySelector('#tri-del-all'), 'bob: no "Delete all" for a member');

  // ================= #2604: a finalised invoice offers no Delete
  const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', project_title: 'Final', client_id: C.id, service_from: '2030-02-01', service_to: '2030-02-28'});
  await call(CA, 'PUT', '/api/office/docs/' + inv.id + '/items', {items: [{title: 'Shoot', qty: 1, rate: 900}]});
  await call(CA, 'PATCH', '/api/settings', {set_delta: {trial_mode: {remove: [String(st.org_id)]}}});
  const fin = await call(CA, 'POST', '/api/office/docs/' + inv.id + '/finalize');
  check(fin.locked === true, 'a finalised invoice ' + JSON.stringify(fin).slice(0, 120));
  w = await boot({user: 'alice', hash: 'office/invoices/' + inv.id}); d = w.document;
  const more = await until(() => d.querySelector('#view [data-ofd="more"]'), 60);
  more?.click();
  check(await until(() => items(d).length) && !items(d).some(b => b.textContent.trim() === 'Delete'), '#2604: no Delete in the menu of a finalised invoice ' + items(d).map(b => b.textContent.trim()).join(' | '));
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
