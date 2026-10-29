// kalmido-suite: fresh
// 2.436.0 (#3620) UI tests, own container (start.sh). jsdom:
// freelancer-matrix: settings -- carol has no organisation and is no server admin (P4): nothing to hide, no switch.
// - Settings > Account: "View as member" only for a person with something to hide (server admin, admin of an organisation)
// - on: the settings show the same areas and headings as a real member of the organisation (bob), the account reads
//   is_admin false and the organisation's role member (the real marks stay as real_admin / real_role); saved per person
// - the server keeps the rights: an admin route still answers, the setting changes nothing there
// - the office of the organisation hides Settings, Contracts & insurance and Bank; quotations and invoices stay; the private
//   office keeps all of them
// - the way back: "Show administration again" under the settings' areas and in the account menu, one click
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2436A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
// the settings' boxes that load on their own (organisation, forwardings, share inbox) are drawn: the view read twice the same
const settle = async w => { let a = null; for (let i = 0; i < 30; i++) { await sleep(500); const b = w.eval(VIEW); if (b && b === a) return b; a = b; } return a; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
// what the settings show: the areas and, per area (account and help aside: the switch itself / the about box), its headings
const VIEW = `(() => { const md = document.querySelector('.modal.smodal'); if (!md) return null;
  const secs = [...md.querySelectorAll('.snav [data-sec]')].filter(b => !b.hidden).map(b => b.dataset.sec);
  const heads = {}; for (const p of md.querySelectorAll('.spane')) if (!['account', 'help'].includes(p.dataset.pane)) heads[p.dataset.pane] = [...p.querySelectorAll('h4, .admsub button')].map(h => h.textContent.trim()).join('|');
  return JSON.stringify({secs, heads}); })()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = [...new Set([...(st.settings.features || '').split(',').filter(Boolean), 'agents', 'office'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', workspace: 'all', features: feats});
  const st1 = await call('GET', '/api/state'), ORG = st1.me.workspaces[0].id;
  check(st1.settings.member_view === '0', '#3620: the default is off ' + st1.settings.member_view);
  check((await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [ORG]})).id, 'setup: bob, a member of Alpha');
  check((await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123', email: 'carol@example.com'})).id, 'setup: carol, without an organisation');
  const BK = await login('bob'), CC = await login('carol');
  for (const ck of [BK, CC]) await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', workspace: 'all', features: feats}, ck);

  // ================= the real member: what bob sees
  let w = await boot({user: 'bob'}), d = w.document;
  await w.eval(`loadModule('settings')`); w.eval(`settingsModal('account')`);
  const bob = await settle(w);
  check(bob && JSON.parse(bob).secs.includes('account'), 'setup: bob\'s settings are open ' + bob);
  check(!d.getElementById('s-mview'), '#3620: a member has nothing to hide: no switch');
  w.close();

  // ================= carol (no organisation, P4): her own admin of her private area -- no switch either
  w = await boot({user: 'carol'}); d = w.document;
  await w.eval(`loadModule('settings')`); w.eval(`settingsModal('account')`);
  check(await until(() => d.querySelector('.modal.smodal #s-account-h')), 'setup: carol\'s settings are open');
  check(!d.getElementById('s-mview') && !w.eval('mvHas()'), '#3620: a person without an organisation: no switch (the private area stays hers)');
  w.close();

  // ================= alice, the admin: the switch
  w = await boot({user: 'alice'}); d = w.document;
  await w.eval(`loadModule('settings')`); w.eval(`settingsModal('account')`);
  const cb = await until(() => d.getElementById('s-mview'));
  check(cb && !cb.checked && /rights stay the same/.test(cb.closest('.row')?.nextElementSibling?.textContent || ''), '#3620: Settings > Account has "View as member", off, with its explanation');
  const adm0 = await settle(w);
  check(adm0 && adm0 !== bob, '#3620: switched off, the admin sees more than a member ' + adm0);
  check(!d.querySelector('.modal.smodal .snmv'), '#3620: no way back while it is off');
  // the office menu before: the organisation's office with its settings
  const ofmKeys = ws => w.eval(`(() => { S.settings.workspace = ${JSON.stringify(ws)}; return ofm_all().filter(i => !i.tpl && i.on() && ofm_ok(i)).map(i => i.key).join(); })()`);
  check(/(^|,)settings(,|$)/.test(ofmKeys('org:' + ORG)), 'setup: the office of Alpha has Settings in its menu ' + ofmKeys('org:' + ORG));
  w.eval(`S.settings.workspace = 'all'`);

  cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => w.eval(`S.me.is_admin === false && S.me.real_admin === true`)), '#3620: switched on: the account reads as a member\'s (is_admin false, real_admin kept)');
  check(w.eval(`S.me.workspaces.find(o => o.id === ${ORG})?.role === 'member' && S.me.workspaces.find(o => o.id === ${ORG})?.real_role === 'admin'`), '#3620: ... the organisation\'s role reads member (real_role admin)');
  check(await until(async () => (await call('GET', '/api/state')).settings.member_view === '1'), '#3620: ... saved for the person (all devices)');
  check(await until(() => d.querySelector('.modal.smodal .snmv') && d.getElementById('s-mview')?.checked), '#3620: the settings are drawn anew: the switch on, "Show administration again" under the areas');
  const mv = await settle(w);
  check(mv === bob, '#3620: the settings show what a real member sees\n   as member: ' + mv + '\n   bob:       ' + bob);
  // an answer of /api/orgs read later (the organisation's boxes) reads member too
  check(await w.eval(`api('GET', '/api/orgs').then(j => j.orgs.find(o => o.id === ${ORG}).role)`) === 'member', '#3620: GET /api/orgs reads member for the display');
  // the server's rights stay
  check((await call('GET', '/api/admin/orgs')).status === 200, '#3620: the server keeps the rights (an admin route still answers)');
  check((await call('GET', '/api/state')).me.is_admin === true, '#3620: ... and the state still says admin (only the client shows a member)');
  // the office: the organisation's settings and administration gone, the daily work stays; the private office untouched
  const org1 = ofmKeys('org:' + ORG).split(',');
  check(!org1.includes('settings') && !org1.includes('agreements') && !org1.includes('bank'), '#3620: the office of Alpha: no Settings, Contracts & insurance, Bank ' + org1);
  check(org1.includes('offers') && org1.includes('invoices'), '#3620: ... quotations and invoices stay ' + org1);
  check(ofmKeys('private').split(',').includes('settings'), '#3620: the private office keeps its settings ' + ofmKeys('private'));
  w.eval(`S.settings.workspace = 'all'`);

  // ================= the way back in the account menu
  d.querySelector('.modal.smodal')?.remove();
  const um = d.querySelector('[data-act="user-menu"]');
  check(!!um, 'setup: the account button');
  um?.click();
  const item = await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Show administration again/.test(b.textContent)));
  check(!!item, '#3620: the account menu offers "Show administration again"');
  item?.click();
  check(await until(() => w.eval(`S.me.is_admin === true && S.settings.member_view === '0'`)), '#3620: one click: the admin view is back');
  check(await until(async () => (await call('GET', '/api/state')).settings.member_view === '0'), '#3620: ... saved');
  um?.click();
  check(await until(() => d.querySelector('#pop [role="menuitem"]')) && ![...d.querySelectorAll('#pop [role="menuitem"]')].some(b => /Show administration again/.test(b.textContent)), '#3620: switched off, the menu has no such entry');
  w.eval(`document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))`);

  // ================= the way back under the settings' areas
  await call('PATCH', '/api/settings', {member_view: '1'});
  w.close();
  w = await boot({user: 'alice'}); d = w.document;
  check(w.eval(`S.me.is_admin === false && S.me.real_admin === true`), '#3620: a fresh start keeps the member view (the state carries the setting)');
  await w.eval(`loadModule('settings')`); w.eval(`settingsModal('general')`);
  const back = await until(() => d.querySelector('.modal.smodal .snmv'));
  check(back && /Show administration again/.test(back.textContent) && !back.closest('[role="tablist"]'), '#3620: the way back under the areas (not inside the tab list)');
  back?.click();
  check(await until(() => w.eval(`S.me.is_admin === true && S.settings.member_view === '0'`)), '#3620: one click there: the admin view is back');
  check(!d.querySelector('.modal.smodal .snmv') && await settle(w) === adm0, '#3620: ... the settings show the admin parts again');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
