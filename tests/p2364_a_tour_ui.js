// kalmido-suite: fresh
// 2.364.0 A UI test (jsdom), own container (start.sh, KALMIDO_ONBOARDING=1): the first start of accounts an admin made
//  - #3032: first only "What do you use Kalmido for?" (preselected: For me without organisation, the inviting admin's
//    purpose for a member), then the "Getting started" list and the tour
//  - #3037: a member of an organisation: the tour has a step "You are in <organisation>" at the workspace switch, no
//    sample project offer, no "Getting started" list
//  - #3016: the agent button only when an agent is there; no sample project offer once there are projects; the phone's
//    bar step names what the bar holds (no "Tab bar", no "focus" that is not there)
// freelancer-matrix: onboarding (frida and gina have no organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KALMIDO_ONBOARDING: '1'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (f, ms = 8000) => { for (let t = 0; t < ms; t += 100) { if (await f()) return true; await sleep(100); } return !!(await f()); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const shown = d => !!d.querySelector('.tour .tcard h3') && d.querySelector('.tour').style.display !== 'none';
const toLast = async (w, d) => { for (let i = 0; i < 10 && /Next/.test(d.querySelector('[data-tour="next"]')?.textContent || ''); i++) { click(w, d.querySelector('[data-tour="next"]')); await sleep(60); } };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call(CA, 'POST', '/api/me/purpose', {purpose: 'team'});
  check((await call(CA, 'POST', '/api/admin/orgs', {name: 'Acme'})).http < 300, 'organisation Acme');
  const OID = (await call(CA, 'GET', '/api/state')).me.workspaces.find(o => o.name === 'Acme').id;

  // ================= (1) frida, no organisation: the question (For me), then the list and the tour
  check((await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []})).http < 300, 'P4: frida without organisation');
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en'});
  let w = await boot({user: 'frida', hash: 'today'}), d = w.document;
  check(await until(() => d.querySelector('.paskdlg .ptcards.purposes')), '#3032: the first start asks "What do you use Kalmido for?"');
  const onP = () => [...d.querySelectorAll('.paskdlg [data-pask].on')].map(b => b.dataset.pask).join();
  check(onP() === 'me', '#3032 P4: without organisation "For me" is preselected: ' + onP());
  check(!d.querySelector('.tour') && !w.eval('S.lists').some(l => l.name === 'Getting started'), '#3032: first the question - no tour, no list yet');
  click(w, d.querySelector('.paskdlg [data-pask="home"]'));
  await until(() => onP() === 'home');
  click(w, d.querySelector('.paskdlg [data-pask="me"]'));
  await until(() => onP() === 'me');
  click(w, d.querySelector('.paskdlg [data-pask-go]'));
  check(await until(() => !d.querySelector('.paskdlg') && w.eval('S.settings.purpose_ask') === 'done'), '#3032: Continue answers it, the dialog goes');
  check(await until(() => shown(d)), '#3032: then the tour');
  check(w.eval('S.lists').some(l => l.name === 'Getting started'), 'P4: the Getting started list comes (no organisation)');
  const fs = (await call(CF, 'GET', '/api/state')).settings.features.split(',').sort().join();
  check(fs === 'cal,contacts,events', '#3032: For me = calendar, events, contacts: ' + fs);
  check(!w.eval('TOUR.steps').some(s => s.id === 'org'), 'P4: no organisation step without organisation');
  await toLast(w, d);
  check(!!d.querySelector('.tour #t-sample'), 'P4: no projects yet: the last card offers the sample project');
  w.eval('tourEnd(true)'); await sleep(300);
  w.close();

  // ================= (2) bert, member of Acme: preselected with the admin's purpose, the organisation step, no sample offer
  check((await call(CA, 'POST', '/api/users', {username: 'bert', display_name: 'Bert', password: 'password123', email: 'bert@example.com', orgs: [OID]})).http < 300, 'bert: member of Acme');
  const CB = await login('bert');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en'});
  w = await boot({user: 'bert', hash: 'today'}); d = w.document;
  check(await until(() => d.querySelector('.paskdlg .ptcards.purposes')), '#3032: a member gets the question too');
  check(onP() === 'team', '#3032: preselected with the purpose of the inviting admin (Team): ' + onP());
  click(w, d.querySelector('.paskdlg [data-pask-go]'));
  check(await until(() => shown(d)), 'bert: then the tour');
  check(!w.eval('S.lists').some(l => !l.is_inbox && l.owner_id === w.eval('S.me.id')), '#3037: a member gets no Getting started list');
  check(w.eval('feat("agents")') && !(w.eval('S.agents') || []).length, '(setup) bert has the module Agents (Team) but no agent');
  const ids = w.eval('TOUR.steps.map(s => s.id)');
  check(ids.includes('org'), '#3037: the tour has the organisation step: ' + ids.join());
  w.eval(`tourGo(TOUR.steps.findIndex(s => s.id === 'org'))`); await sleep(100);
  const h3 = d.querySelector('.tour .tcard h3')?.textContent || '', p = d.querySelector('.tour .tcard p')?.textContent || '';
  check(/You are in Acme/.test(h3) && /team chat/.test(p) && /Acme/.test(p), '#3037: "You are in Acme", projects, team chat, workspace switch: ' + h3 + ' / ' + p);
  check(d.querySelector('.tour').dataset.sel === '[data-act="ws-menu"]', '#3037: the step points at the workspace switch');
  await toLast(w, d);
  check(!d.querySelector('.tour #t-sample'), '#3037: no sample project offer for a member');
  check(!d.querySelector('.tour [data-pk2="setup"]'), '#3016: no "Set up with your agent" without an agent');
  w.eval('tourEnd(true)'); await sleep(300);
  w.close();

  // ================= (3) gina, no organisation, already a project of her own: no sample offer; the phone's bar step
  check((await call(CA, 'POST', '/api/users', {username: 'gina', display_name: 'Gina', password: 'password123', email: 'gina@example.com', orgs: []})).http < 300, 'P4: gina without organisation');
  const CG = await login('gina');
  await call(CG, 'PATCH', '/api/settings', {lang: 'en'});
  await call(CG, 'POST', '/api/me/purpose', {purpose: 'me', only: true});
  await call(CG, 'POST', '/api/lists', {name: 'Film'});
  w = await boot({user: 'gina', hash: 'today', mobile: true}); d = w.document;
  check(await until(() => shown(d)), 'gina (question answered): the tour starts');
  const tabs = w.eval(`(() => { const s = TOUR.steps.find(x => x.id === 'tabs'); return s ? tr(s.t) + ' | ' + tr(s.d, ...(s.args || [])) : ''; })()`);
  const labels = w.eval(`$$('#tabs > button').map(b => b.querySelector('span:last-child')?.textContent.trim()).filter(Boolean)`);
  check(/^The bar at the bottom \| /.test(tabs) && !/Tab bar|habits|focus/i.test(tabs) && labels.length && labels.every(x => tabs.includes(x)), '#3016: the bar step names what the bar holds: ' + tabs + ' / ' + labels.join(','));
  await toLast(w, d);
  check(!d.querySelector('.tour #t-sample'), '#3016: a project of her own already: no sample project offer');
  w.eval('tourEnd(true)'); await sleep(300);
  w.close();

  console.log(`p2364_a_tour_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
