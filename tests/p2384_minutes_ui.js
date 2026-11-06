// 2.384.0 (#1958): minutes of a meeting as a knowledge page, made from an event. Own container (start.sh), jsdom,
// frida = a person WITHOUT an organisation (freelancer-matrix: knowledge), invented texts only:
// - "Minutes" in an event's popover makes Minutes/YYYY-MM-DD <title> in her private space (no template: the built-in one):
//   title, date, time, place, participants and the agenda (the event's notes, one item per line) filled in, the event in the
//   front matter (termin, datum) and as a link (#ev/<id>), decisions / action items as checkbox lines; the page opens
//   for writing at the notes
// - "Minutes" on the same event again opens that page (no second one); another event with the same title on the same
//   day gets "… (2)"
// - Templates/Besprechung is used when the space has one ({{titel}} {{datum}} {{teilnehmer}} {{tagesordnung}} {{termin}}
//   {{cursor}} filled, the front matter put in front), its open checkbox lines are what "Open items as tasks" offers
// - the new placeholders stay as they are in other templates; without the module "knowledge" the button is not there
// kalmido-suite: fresh
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return c; };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2384_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const day = n => require('./testclock').day(n);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const base = (st0.settings.features || '').split(',').filter(Boolean);
  const feats = [...new Set([...base, 'wiki', 'events'])].join(',');
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Test', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  check(fu.id && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  const cal = await call(CF, 'POST', '/api/evcals', {name: 'Frida Termine'}), cid = cal.id || cal.cal?.id;
  const d1 = day(2);
  const mkEv = async (title, extra = {}) => { const r = await call(CF, 'POST', '/api/events', {title, cal_id: cid, start: d1 + 'T10:00', end: d1 + 'T11:00', ...extra}); return r.id || r.event?.id; };
  const E1 = await mkEv('Planung Herbst', {location: 'Raum 2', description: 'Budget\n- Termine\n\n3. Sonstiges', attendees: [{email: 'gast@example.com', name: 'Gast Eins'}]});
  check(cid && E1, 'setup: frida\'s calendar and event ' + JSON.stringify([cid, E1]));
  const pages = async () => (await call(CF, 'GET', '/api/wiki?space=private')).pages || [];

  // ================= the built-in template
  const w = await boot({user: 'frida', hash: 'cal'}), d = w.document;
  const minutes = async eid => {
    w.eval(`closePop && closePop(); evOpen(${eid})`);
    const b = await until(() => d.querySelector('#pop:not(.hidden) [data-evp="minutes"]'));
    if (!b) return null;
    click(w, b);
    return until(() => w.eval('S.route.mod') === 'wiki' && w.eval('S.route.wid') && w.eval(`WK.pg && WK.pg.id === S.route.wid ? S.route.wid : 0`));
  };
  const id1 = await minutes(E1);
  check(id1, 'Minutes: the popover\'s button opens a knowledge page');
  const p1 = await call(CF, 'GET', '/api/wiki/pages/' + id1);
  const dd = w.eval(`fmtDate('${d1}')`);
  check(p1.space === 'private' && p1.path === `Minutes/${d1} Planung Herbst`, 'in her private space, named Minutes/<date> <title> ' + JSON.stringify([p1.space, p1.path]));
  const b1 = p1.body || '';
  check(b1.startsWith(`---\ntermin: ${E1}\ndatum: ${d1}\n---\n# Planung Herbst\n`), 'the event in the front matter, the title as heading ' + JSON.stringify(b1.slice(0, 120)));
  check(String(p1.attrs?.termin) === String(E1) && p1.attrs?.datum === d1, 'the front matter is read as attributes ' + JSON.stringify(p1.attrs));
  check(new RegExp(`\\*\\*Event:\\*\\* \\[Planung Herbst\\]\\(#ev/${E1}\\) · [^\\n]*10:00[^\\n]* · Raum 2\\n`).test(b1), 'a link to the event, its time and place ' + b1);
  check(/## Participants\n- Gast Eins\n/.test(b1), 'the participants as a list ' + b1);
  check(/## Agenda\n- Budget\n- Termine\n- Sonstiges\n/.test(b1), 'the agenda from the event\'s notes, one item per line (list marks taken off) ' + b1);
  check(/## Decisions\n- \[ \] \n/.test(b1) && /## Action items\n- \[ \] \n/.test(b1), 'decisions and action items as checkbox lines');
  check(!b1.includes('{{'), 'no placeholder left');
  check(w.eval('WK.edit') === true, 'the new page opens for writing');

  // ================= again: the same page; another event with the same title: (2)
  const n1 = (await pages()).length;
  const id1b = await minutes(E1);
  check(id1b === id1 && (await pages()).length === n1, 'Minutes again on the same event opens that page, no second one ' + JSON.stringify([id1, id1b]));
  const E2 = await mkEv('Planung Herbst');
  const id2 = await minutes(E2);
  const p2 = await call(CF, 'GET', '/api/wiki/pages/' + id2);
  check(id2 && id2 !== id1 && p2.path === `Minutes/${d1} Planung Herbst (2)` && String(p2.attrs?.termin) === String(E2), 'another event, same title and day: "… (2)" ' + p2.path);
  check(/## Participants\n- \n/.test(p2.body || '') && /## Agenda\n- \n/.test(p2.body || ''), 'no participants / notes: empty list items to fill');

  // ================= a template of the space
  const tid = (await call(CF, 'POST', '/api/wiki/pages', {space: 'private', path: 'Templates/Besprechung', body: '# Protokoll {{ titel }} am {{datum}}\n\n{{termin}}\n\nDabei: {{teilnehmer}}\n\n{{tagesordnung}}\n\n{{cursor}}\n\n- [ ] Beschluss eins\n- [ ] Aufgabe zwei'})).id;
  check(tid, 'setup: Templates/Besprechung');
  const E3 = await mkEv('Review', {description: 'Punkt A', attendees: [{email: 'x@example.com', name: 'Xaver'}]});
  w.eval('S.v++');
  const id3 = await minutes(E3);
  const p3 = await call(CF, 'GET', '/api/wiki/pages/' + id3);
  const b3 = p3.body || '';
  check(b3 === `---\ntermin: ${E3}\ndatum: ${d1}\n---\n# Protokoll Review am ${dd}\n\n[Review](#ev/${E3})\n\nDabei: - Xaver\n\n- Punkt A\n\n\n\n- [ ] Beschluss eins\n- [ ] Aufgabe zwei`, 'the template filled, the front matter in front ' + JSON.stringify(b3));
  const f3 = JSON.parse(w.eval(`JSON.stringify(wk_meetText('a\\n{{cursor}}b', {eid: 7, day: '${d1}', title: 'T'}, 'Minutes/T'))`));
  check(f3.text === `---\ntermin: 7\ndatum: ${d1}\n---\na\nb` && f3.text[f3.at] === 'b', 'writing starts at {{cursor}} (behind the front matter) ' + JSON.stringify(f3));
  const f4 = JSON.parse(w.eval(`JSON.stringify(wk_meetText('---\\ntags: [x]\\n---\\n{{cursor}}b', {eid: 7, day: '${d1}', title: 'T'}, 'Minutes/T'))`));
  check(f4.text === `---\ntermin: 7\ndatum: ${d1}\ntags: [x]\n---\nb` && f4.text[f4.at] === 'b', 'a template with its own front matter: the event goes into it ' + JSON.stringify(f4));
  check(w.eval(`wem_cbLines(${JSON.stringify(b3)}).map(L => L.text).join('|')`) === 'Beschluss eins|Aufgabe zwei', 'its checkbox lines are the open items "Open items as tasks" makes tasks of');

  // ================= the new placeholders stay elsewhere
  check(w.eval(`wk_tplFill('{{termin}} {{agenda}} {{titel}}', 'Ordner/X').text`) === '{{termin}} {{agenda}} X', 'the event\'s placeholders stay in other templates');
  w.close();

  // ================= without the module "knowledge": no button
  await call(CF, 'PATCH', '/api/settings', {features: [...new Set([...base, 'events'])].filter(x => x !== 'wiki').join(',')});
  const w2 = await boot({user: 'frida', hash: 'cal'}), d2 = w2.document;
  w2.eval(`evOpen(${E1})`);
  check(await until(() => d2.querySelector('#pop:not(.hidden) [data-evp="edit"]')) && !d2.querySelector('#pop [data-evp="minutes"]'), 'without knowledge pages the popover has no "Minutes"');
  w2.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
