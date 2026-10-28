// kalmido-suite: fresh
// 2.364.0 A (#3015) UI test (jsdom): the first-run setup ("What do you use Kalmido for?") and Settings > Modules
//  - a tap on "Office & finance" marks only that tile (Team / Software projects / Office & finance offer the same modules
//    in the setup, matching by modules alone marked all three); each of the three names what it adds
//  - ONE module count: the setup's "x of y modules on" equals the count of Settings > Modules right after the setup
//  - "Switch on all modules" with some modules on shows half (indeterminate), in the setup and in Settings > Modules
//  - the switch's title and note are not glued together ("Switch on all modulesOff: …")
// freelancer-matrix: settings (alice sets up without an organisation; frida is a person without organisation)
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true})});
  check(r.ok, 'setup');
  CK = await login('alice');
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  await until(() => d.querySelector('.authscreen .supresets'));
  const on = () => [...d.querySelectorAll('.supreset.on')].map(b => b.dataset.suPreset);
  check(on().join() === 'me', 'a new account starts with "For me" only: ' + on());
  const ma = () => d.querySelector('#su-modsall');
  check(ma() && !ma().checked && ma().indeterminate, '"For me" (some modules): "Switch on all modules" shows half in the setup');
  check(/Switch on all modules\s+Off:/.test(ma().closest('label').textContent), 'title and note of the switch apart: ' + ma().closest('label').textContent.slice(0, 60));
  click(w, d.querySelector('[data-su-preset="office"]'));
  await until(() => on().join() === 'office');
  check(on().join() === 'office', 'a tap on Office & finance marks only that tile (not Team, Software projects): ' + on());
  const adds = k => d.querySelector(`[data-su-preset="${k}"] .suadds`)?.textContent || '';
  check(adds('team') && adds('software') && adds('office') && new Set([adds('team'), adds('software'), adds('office')]).size === 3, 'Team, Software projects, Office & finance each name what they add: ' + [adds('team'), adds('software'), adds('office')].join(' | '));
  check(/Clients/.test(adds('office')) && !adds('me'), 'Office & finance adds clients; "For me" names nothing extra');
  click(w, d.querySelector('[data-su-preset="team"]'));
  await until(() => on().join() === 'team');
  check(on().join() === 'team', 'then Team: only Team marked');
  click(w, d.querySelector('[data-su-preset="office"]'));
  await until(() => on().join() === 'office');
  const cnt = d.querySelector('.authscreen .sucust summary .muted')?.textContent || '';
  check(/^\d+ of \d+ modules on$/.test(cnt), 'the setup counts "x of y modules on": ' + cnt);
  click(w, d.querySelector('[data-su="go"]'));
  const st = await until(async () => { const s = await call('GET', '/api/state'); return s.settings?.purpose === 'office' && s; });
  check(st && st.settings.purpose === 'office', 'the setup stored the purpose Office & finance');
  w.close();
  await call('PATCH', '/api/settings', {tour: 'done'});

  // ================= Settings > Modules counts the same
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('modules')`);
  const tot = await until(() => d.querySelector('.smodal #s-modtot')?.textContent);
  check(tot === cnt, `ONE count: the setup said "${cnt}", Settings > Modules says "${tot}"`);
  const sa = d.querySelector('.smodal #s-modsall');
  check(sa && !sa.checked && sa.indeterminate, 'Settings > Modules: "Switch on all modules" half while only some modules are on');
  check(/Switch on all modules\s+Off:/.test(sa.closest('label').textContent), 'Settings > Modules: title and note apart');
  click(w, sa);
  await until(() => /^(\d+) of \1 modules on$/.test(d.querySelector('.smodal #s-modtot')?.textContent || ''));
  check(/^(\d+) of \1 modules on$/.test(d.querySelector('.smodal #s-modtot')?.textContent || ''), 'switched on: every module counted: ' + d.querySelector('.smodal #s-modtot')?.textContent);
  check(d.querySelector('.smodal #s-modsall').checked && !d.querySelector('.smodal #s-modsall').indeterminate, 'switched on: every module on, no longer half');
  w.close();

  // ================= a person without organisation: the same switch in her settings
  check((await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []})).id, 'a person without organisation');
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,contacts'}, CF);
  check(((await call('GET', '/api/state', null, CF)).me.workspaces || []).length === 0, 'frida is in no organisation');
  w = await boot({user: 'frida'}); d = w.document;
  w.eval(`settingsModal('modules')`);
  const fa = await until(() => d.querySelector('.smodal #s-modsall'));
  check(fa && !fa.checked && fa.indeterminate, 'without organisation: "Switch on all modules" half with two modules on');
  check(/^2 of \d+ modules on$/.test(d.querySelector('.smodal #s-modtot')?.textContent || ''), 'without organisation: 2 modules counted: ' + d.querySelector('.smodal #s-modtot')?.textContent);
  w.close();

  console.log(`p2364_a_setup_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
