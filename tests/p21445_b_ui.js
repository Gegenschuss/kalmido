// 2.144.5 part B UI tests (jsdom), own container (start.sh). Invented names only.
// #2002 the target of an import:
//   (a) the task import with the sidebar on "All" goes into the private space by default; the question offers "Rather into
//       <organisation>" (the first one) instead, which files the new list there; Import keeps it private
//   (b) the event import into an organisation's calendar offers "Rather into private" also without a private calendar: one is
//       made then and the events land there
//   P4: a person without organisation imports privately, no button for another workspace
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21445B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const pick = (w, input, name, text) => {
  const f = new w.File([text], name);
  Object.defineProperty(input, 'files', {configurable: true, value: [f]});
  input.dispatchEvent(new w.Event('change', {bubbles: true}));
};
async function dataPane(w) {
  w.eval(`settingsModal()`); await sleep(400);
  const md = w.document.querySelector('.smodal');
  click(w, md.querySelector('.snav [data-sec="data"]')); await sleep(300);
  return md;
}
const CSV = name => `TYPE,CONTENT,PRIORITY\ntask,${name} eins,4\ntask,${name} zwei,4\n`;
const ICS = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Example//Test//EN', 'BEGIN:VEVENT', 'UID:p21445b-1@example', 'DTSTAMP:20261021T080000Z',
  'DTSTART:20261112T090000Z', 'DTEND:20261112T100000Z', 'SUMMARY:Importierter Termin', 'END:VEVENT', 'END:VCALENDAR', ''].join('\r\n');

// one task import through Settings > Data; answer = 'org' | 'yes' -> the dialog seen
async function taskImport(w, file, answer) {
  const d = w.document, md = await dataPane(w);
  pick(w, md.querySelector('#s-import'), file + '.csv', CSV(file));
  await until(() => md.querySelector('#s-imp-out .impbox [data-imp="go"]'), 60);
  click(w, md.querySelector('#s-imp-out .impbox [data-imp="go"]'));
  const dl = await until(() => d.querySelector('.itc-dlg'));
  const seen = {text: dl?.textContent || '', org: dl?.querySelector('[data-itc="org"]')?.textContent || '', priv: !!dl?.querySelector('[data-itc="private"]')};
  click(w, answer === 'org' ? dl?.querySelector('[data-itc="org"]') : dl?.querySelector('[data-cd="yes"]'));
  await until(() => /Imported/.test(md.querySelector('#s-imp-out')?.textContent || ''), 60);
  md.remove();
  return seen;
}

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const bob = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  await call(CA, 'POST', '/api/users', {username: 'erin', display_name: 'Erin', password: 'password123', email: 'erin@example.com', orgs: []});
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: bob.id});
  check(org.status === 201, 'setup: organisation Alpha with bob as admin');
  const CB = await login('bob'), CE = await login('erin');
  for (const ck of [CB, CE]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events', workspace: 'all'});
  const listOf = async (ck, name) => ((await call(ck, 'GET', '/api/state')).lists || []).find(l => l.name === name);

  // ================= #2002 (a) the task import with "All"
  let w = await boot({user: 'bob'}); w.__dialogs = 'manual';
  check(w.eval(`wsCur()`) === 'all', 'setup: the sidebar shows All');
  let seen = await taskImport(w, 'Umzug21445org', 'org');
  check(/your private space/.test(seen.text) && !seen.priv, '#2002: with All the import names the private space first ' + seen.text);
  check(/Rather into Alpha/.test(seen.org), '#2002: it offers the organisation instead ' + JSON.stringify(seen.org));
  let l = await listOf(CB, 'Umzug21445org');
  check(l && l.org_id === org.id, '#2002: "Rather into Alpha" files the new list in the organisation ' + JSON.stringify(l && l.org_id));
  seen = await taskImport(w, 'Umzug21445priv', 'yes');
  l = await listOf(CB, 'Umzug21445priv');
  check(l && !l.org_id, '#2002: Import keeps the new list private ' + JSON.stringify(l && l.org_id));
  // a chosen organisation in the sidebar stays the target (no "Rather into" the other way)
  w.eval(`S.settings.workspace = 'org:${org.id}'`);
  seen = await taskImport(w, 'Umzug21445ws', 'yes');
  check(/organisation Alpha/.test(seen.text) && !seen.org && seen.priv, '#2002: the shown organisation stays the target, "Rather into private" as before ' + seen.text);
  l = await listOf(CB, 'Umzug21445ws');
  check(l && l.org_id === org.id, '#2002: … and the list is the organisation\'s');
  w.close();

  // ================= #2002 (b) the event import from an organisation's calendar without a private calendar
  const oc = await call(CB, 'POST', '/api/evcals', {name: 'Alpha Termine', org_id: org.id});
  check(oc.id, 'setup: the organisation\'s calendar');
  const privCals = async () => ((await call(CB, 'GET', '/api/evcals')).items || (await call(CB, 'GET', '/api/state')).evcals || []).filter(c => !c.org_id && c.role === 'owner');
  check((await privCals()).length === 0, 'setup: bob has no private calendar');
  w = await boot({user: 'bob'}); w.__dialogs = 'manual';
  let d = w.document;
  w.eval(`window._done = 0; evImport(evCal(${oc.id}), () => { window._done = 1; }, new File([${JSON.stringify(ICS)}], 'termine.ics', {type: 'text/calendar'}))`);
  let dl = await until(() => d.querySelector('.itc-dlg'));
  const pb = dl?.querySelector('[data-itc="private"]');
  check(pb && /Rather into private/.test(pb.textContent), '#2002: "Rather into private" also without a private calendar');
  click(w, pb);
  check(await until(() => w._done === 1, 60), '#2002: the import ran');
  const pcs = await privCals();
  check(pcs.length === 1, '#2002: a private calendar was made ' + JSON.stringify(pcs.map(c => c.name)));
  const evs = await call(CB, 'GET', `/api/events?from=2026-11-01&to=2026-11-30&calendar_id=${pcs[0]?.id}`);
  check((evs.items || []).some(e => e.title === 'Importierter Termin'), '#2002: the event landed in the private calendar');
  const evo = await call(CB, 'GET', `/api/events?from=2026-11-01&to=2026-11-30&calendar_id=${oc.id}`);
  check(!(evo.items || []).some(e => e.title === 'Importierter Termin'), '#2002: nothing in the organisation\'s calendar');
  // a second import with the private calendar there: no second calendar
  w.eval(`window._done = 0; evImport(evCal(${oc.id}), () => { window._done = 1; }, new File([${JSON.stringify(ICS)}], 'termine.ics', {type: 'text/calendar'}))`);
  dl = await until(() => d.querySelector('.itc-dlg'));
  click(w, dl?.querySelector('[data-itc="private"]'));
  await until(() => w._done === 1, 60);
  check((await privCals()).length === 1, '#2002: the existing private calendar is used');
  w.close();

  // ================= P4: a person without organisation
  w = await boot({user: 'erin'}); w.__dialogs = 'manual';
  seen = await taskImport(w, 'Umzug21445erin', 'yes');
  check(/your private space/.test(seen.text) && !seen.org && !seen.priv && !/organisation/i.test(seen.text), 'P4: only the private space, no other workspace offered ' + seen.text);
  l = await listOf(CE, 'Umzug21445erin');
  check(l && !l.org_id, 'P4: the list is private');
  w.close();

  console.log(`p21445_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
