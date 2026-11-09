// kalmido-suite: fresh
// 2.794.0 (#5392) UI test (jsdom), own container (start.sh): Settings > Modules > Office & finance > "Also private"
//  - with an organisation the module row of the office has the switch "Also private" (on by default); off: in the workspace
//    Private the office is gone (no area in the sidebar, the page does not open), contacts and clients stay; in the
//    organisation the office opens with its own office; "All workspaces" offers only the organisation's office
//  - the switch saves ws_mods_off {"private": ["office"]}; switched on again, Private opens its office with the same data
//  - with the module itself off the switch is hidden; a person without an organisation is not offered it
// freelancer-matrix: settings (the switch needs an organisation: alone, Private is the only workspace and the module switch is the switch)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEATS = 'cal,collab,comments,contacts,files,clients,office';

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const me = await call('GET', '/api/state');
  const org = await call('POST', '/api/admin/orgs', {name: 'Nordwind', admin_id: me.me.id});
  check(org.id, 'an organisation');
  const WS = `org:${org.id}`;
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEATS, workspace: WS});
  check((await call('PUT', '/api/office/settings', {company_fields: {name: 'Nordwind Studio GmbH', country: 'de'}, lang: 'en', currency: 'EUR'})).status === 200, 'the organisation\'s office');
  await call('PATCH', '/api/settings', {workspace: 'private'});
  check((await call('PUT', '/api/office/settings', {company_fields: {name: 'Alice Privatbuero', country: 'de'}, lang: 'en', currency: 'EUR'})).status === 200, 'the private office');
  const cl = await call('POST', '/api/clients', {name: 'Privatkunde Beispiel'});
  check(cl.id, 'a private client');

  const w = await boot({user: 'alice'}), d = w.document, ev = s => w.eval(s);
  check(ev('wsCur()') === 'private', '(setup) Private is shown');
  check(ev('officeOn()') === true, 'Private, default: the office is on');
  const company = () => JSON.stringify(ev('OFC.info?.company_fields || null') || '');
  ev(`go('office/settings')`);
  check(await until(() => company().includes('Alice Privatbuero')), 'Private, default: the private office opens with its own data ' + company());

  // ================= Settings > Modules: the switch under Office & finance
  ev(`settingsModal('modules')`);
  const sw = await until(() => d.querySelector('.smodal input[data-ofpriv]'));
  check(sw && sw.checked, 'the switch "Also private" is there and on');
  const row = sw?.closest('[data-modrow="office"]');
  check(row && !row.classList.contains('off') && row.textContent.includes('Also private') && row.textContent.includes('Nothing is deleted'), 'it sits in the row of Office & finance, with its text');
  sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  const st = await until(async () => { const s = JSON.parse((await call('GET', '/api/state')).settings.ws_mods_off || '{}'); return (s.private || []).includes('office') && s; });
  check(st, 'off: saved as ws_mods_off private ' + JSON.stringify(st));
  check(await until(() => ev('officeOn()') === false), 'off: no office in Private');
  check(ev(`feat('contacts')`) === true && ev(`feat('clients')`) === true, 'off: contacts and clients stay in Private');
  check(d.querySelector('.smodal input[data-feat="office"]')?.checked === true, 'off: the module switch itself stays on');

  // with the module itself off the switch is hidden, on again it is there again (unchanged)
  const mo = d.querySelector('.smodal input[data-feat="office"]');
  mo.checked = false; mo.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => row.classList.contains('off')), 'module off: the row is off (the switch hidden with it, .modrow.off .mopt)');
  check(w.getComputedStyle(row.querySelector('.ofpriv')).display === 'none', 'module off: "Also private" is not shown');
  mo.checked = true; mo.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/state')).settings.features.split(',').includes('office') && !row.classList.contains('off')), 'module on again');
  check(sw.checked === false, 'the switch kept its value (off)');
  d.querySelector('.smodal')?.remove();

  // ================= Private without office, the organisation with its own
  ev('render()');
  const offLinks = () => [...d.querySelectorAll('#side [data-go^="office"], #srail [data-go^="office"], #tabs [data-go^="office"]')].map(b => b.dataset.go);
  check(await until(() => offLinks().length === 0), 'Private: no way to Office & finance in the bar / sidebar ' + JSON.stringify(offLinks()));
  check(ev(`mg_parts(mg_area('office')).map(p => p[0]).join()`) === 'contacts,clients', 'Private: the area keeps contacts and clients only ' + ev(`mg_parts(mg_area('office')).map(p => p[0]).join()`));
  ev(`go('office')`);
  check(await until(() => d.querySelector('#main')?.textContent.includes('Office & finance is off')), 'Private: the private office does not open, the page says it is off');
  check(!d.querySelector('#main')?.textContent.includes('Alice Privatbuero'), 'Private: no data of the private office on the page');
  await w.eval(`wsSet('${WS}')`);
  check(await until(() => ev('officeOn()') === true), 'organisation: the office is on');
  ev(`go('office/settings')`);
  check(await until(() => company().includes('Nordwind Studio GmbH')), 'organisation: its office opens with its data ' + company());
  await w.eval(`wsSet('all')`);
  check(await until(() => JSON.stringify(ev('ofc_spaces()')) === JSON.stringify([WS])), 'All workspaces: only the organisation\'s office is offered ' + JSON.stringify(ev('ofc_spaces()')));

  // ================= on again: Private as before
  await w.eval(`wsSet('private')`);
  ev(`settingsModal('modules')`);
  const sw2 = await until(() => d.querySelector('.smodal input[data-ofpriv]'));
  check(sw2 && !sw2.checked, 'the switch shows off');
  sw2.checked = true; sw2.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => { const s = JSON.parse((await call('GET', '/api/state')).settings.ws_mods_off || '{}'); return !(s.private || []).includes('office'); }), 'on again: saved');
  d.querySelector('.smodal')?.remove();
  check(await until(() => ev('officeOn()') === true), 'on again: the office is back in Private');
  ev(`go('office/start')`); await sleep(100); ev(`go('office/settings')`);
  check(await until(() => company().includes('Alice Privatbuero')), 'on again: the private office with the same data ' + company());
  const cls = await call('GET', '/api/clients');
  check(JSON.stringify(cls).includes('Privatkunde Beispiel'), 'on again: the private client is still there');
  w.close();

  // ================= a person without an organisation: not offered
  check((await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []})).id, 'frida without an organisation');
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEATS}, CF);
  const wf = await boot({user: 'frida'}), df = wf.document;
  wf.eval(`settingsModal('modules')`);
  check(await until(() => df.querySelector('.smodal input[data-feat="office"]')), 'frida: the module row of the office');
  check(!df.querySelector('.smodal input[data-ofpriv]'), 'frida: no "Also private" (Private is her only workspace)');
  check(wf.eval('officeOn()') === true, 'frida: her office as before');
  wf.close();

  console.log(`p5392_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
