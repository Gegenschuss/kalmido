// 2.21.0 UI tests: package "Events & contacts" (#659 #658) + #673, own container (start.sh, isolated test database).
// jsdom: switched off nothing shows; on: own events in the month / week / agenda views (colour of the calendar), the popover
// (details, reply, edit, delete with "only this date"), the editor (all day, repeat, reminders, people from the server, an
// address, a contact; saving), the "Event" button of the quick sheet, the calendars dialog (hide, share), the phone guide,
// News of an invitation; the contacts view (search, group filter, the card, the editor with phone / e-mail / birthday
// without the year, delete), the task panel ("People and dates": link a contact, schedule as an event), German texts, and
// #673: a server that answers 502 while the device is online -> the cached data + "Server not reachable – changes are
// sent later" instead of the error page.
// Firefox: a phone (390 touch), the Fold unfolded upright (690 x 829) and across (829 x 690) with touch, a desktop (1440,
// mouse): nothing sideways, 44 px targets on touch, axe (WCAG 2.2 A + AA) over the calendar, the editor, the calendars
// dialog, the contacts view + card and the task panel, a drag over free time in the week creates an event, Tab stays in the
// editor. Screenshots with P2210_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2210_ui', check, shots: 'P2210_SHOTS'});
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const change = (w, el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const ALL = 'cal,timeline,comments,collab,events,contacts';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.org'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, tour: 'done', lang: 'en'}, CB);

  // ================= switched off: nothing
  let w = await boot({user: 'alice', hash: 'cal'}), d = w.document;
  await until(() => d.querySelector('#view .calbar'));
  check(!d.querySelector('#view [data-act="ev-new"]') && !d.querySelector('#side [data-go="contacts"]') && !d.querySelector('#view .calbar [data-k="agenda"]'),
    'off: no "+ Event", no Agenda, no Contacts in the sidebar');
  w.close();
  await call('PATCH', '/api/settings', {features: ALL});
  const W = await call('POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  const P = await call('POST', '/api/evcals', {name: 'Private', color: '#f87171'});
  const t0 = day(0), t1 = day(1), t2 = day(2);
  const E1 = await call('POST', '/api/events', {title: 'Dentist', cal_id: P.id, start: `${t1}T15:00`, end: `${t1}T16:00`, location: 'Main St 1', reminders: [30]});
  const SU = await call('POST', '/api/events', {title: 'Standup', cal_id: W.id, start: `${t1}T09:00`, end: `${t1}T09:15`, rrule: 'FREQ=DAILY;COUNT=5', attendees: [{user_id: BOB}]});
  await call('POST', '/api/events', {title: 'Holiday', cal_id: P.id, all_day: true, start: t2, end: day(4)});
  await call('POST', '/api/tasks', {title: 'Buy flowers', due: t1});
  const C1 = await call('POST', '/api/contacts', {given: 'Erika', family: 'Mustermann', org: 'ACME', emails: [{value: 'erika@example.org', type: ['work']}],
    phones: [{value: '+49 170 1234567', type: ['cell']}], bday: '1964-08-12', groups: ['Customers']});
  await call('POST', '/api/contacts', {fn: 'Plumber Joe', phones: [{value: '030 999'}], groups: ['Home']});

  // ================= the calendar views
  w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}); d = w.document;
  await until(() => d.querySelector('#view .cal .cev'));
  w.eval(`S.calSel = '${t1}'; renderView()`); await sleep(200);
  const chips = [...d.querySelectorAll('#view .cal .cev')].map(c => c.textContent);
  check(chips.some(x => /Dentist/.test(x)) && chips.some(x => /Standup/.test(x)) && chips.some(x => /Holiday/.test(x)), 'month: own events as chips ' + chips.slice(0, 6));
  const dc = [...d.querySelectorAll('#view .cal .cev')].find(c => /Dentist/.test(c.textContent));
  check(/f87171/i.test(dc.getAttribute('style')), 'the chip has the colour of its calendar');
  check(d.querySelector('#view [data-act="ev-new"]') && d.querySelector('#view [data-act="ev-cals"]') && d.querySelector('#view .calbar [data-k="agenda"]'),
    'on: "+ Event", "Calendars", the Agenda mode');
  // the popover
  click(w, d.querySelector('#view .agenda .cevrow[data-cev]') ? [...d.querySelectorAll('#view .agenda .cevrow')].find(r => /Dentist/.test(r.textContent)) : dc);
  await until(() => d.querySelector('#pop .evpop [data-evp="edit"]'));
  let pop = d.querySelector('#pop .evpop');
  check(/Dentist/.test(pop.textContent) && /Main St 1/.test(pop.textContent) && /Private/.test(pop.textContent) && /30 min/.test(pop.textContent),
    'popover: title, place, calendar, reminder: ' + pop.textContent.slice(0, 160));
  click(w, pop.querySelector('[data-evp="edit"]'));
  await until(() => d.querySelector('.modal.evmodal'));
  let md = d.querySelector('.modal.evmodal');
  check(md.querySelector('#ev-title').value === 'Dentist' && md.querySelector('#ev-sd').value === t1 && md.querySelector('#ev-stm').value === '15:00' && md.querySelector('#ev-etm').value === '16:00'
    && md.querySelector('#ev-loc').value === 'Main St 1' && md.querySelector('[data-evrem="30"].on'), 'the editor shows the event');
  check(md.getAttribute('role') === 'dialog' && md.getAttribute('aria-labelledby') && [...md.querySelectorAll('input:not([type=hidden]), select, textarea')].every(i => i.id ? md.querySelector(`label[for="${i.id}"]`) || i.getAttribute('aria-label') || i.getAttribute('aria-labelledby') : i.getAttribute('aria-label')),
    'the editor: a named dialog, every field labelled');
  md.querySelector('#ev-title').value = 'Dentist (check-up)';
  click(w, md.querySelector('[data-evrem="60"]'));
  click(w, md.querySelector('[data-evm="save"]'));
  check(await until(async () => { const e = await call('GET', `/api/events/${E1.id}`); return e.title === 'Dentist (check-up)' && e.reminders.sort().join() === '30,60'; }), 'saved: title + a second reminder');
  check(await until(() => !d.querySelector('.modal.evmodal') && /Event saved/.test(d.querySelector('#toast').textContent)), 'closed, toast');
  // a new event with "+ Event": all day, weekly, a person from the server, an address
  click(w, d.querySelector('#view [data-act="ev-new"]'));
  await until(() => d.querySelector('.modal.evmodal'));
  md = d.querySelector('.modal.evmodal');
  md.querySelector('#ev-title').value = 'Team day';
  change(w, md.querySelector('#ev-cal'), String(W.id));
  md.querySelector('#ev-allday').checked = true; change(w, md.querySelector('#ev-allday'));
  check(md.querySelector('.evtm').hidden && md.querySelector('[data-evrem="-540"]'), 'all day: no times, the all-day reminders ("On the day at 9:00")');
  w.eval(`dpSet(document.querySelector('#ev-sd'), '${t2}'); dpSet(document.querySelector('#ev-ed'), '${t2}')`);
  change(w, md.querySelector('#ev-rep'), 'W');
  check(!md.querySelector('#ev-repend').hidden, 'a repeat shows how it ends');
  change(w, md.querySelector('#ev-repend'), 'count'); md.querySelector('#ev-count').value = '3';
  input(w, md.querySelector('#ev-attin'), 'Bo'); await sleep(150);
  check([...md.querySelectorAll('#ev-attl option')].some(o => o.value === 'Bob'), 'people: Bob is suggested');
  md.querySelector('#ev-attin').value = 'Bob'; click(w, md.querySelector('[data-evm="attadd"]'));
  md.querySelector('#ev-attin').value = 'guest@example.net'; click(w, md.querySelector('[data-evm="attadd"]'));
  md.querySelector('#ev-attin').value = 'not an address'; click(w, md.querySelector('[data-evm="attadd"]'));
  check(md.querySelectorAll('#ev-atts .evatp').length === 2 && /Pick a person/.test(d.querySelector('#toast').textContent), 'two people; something else is refused with a hint');
  click(w, md.querySelector('[data-evm="save"]'));
  const TD = await until(async () => (await call('GET', `/api/events?from=${t2}&to=${day(30)}`)).items.find(x => x.title === 'Team day'));
  const td = TD && await call('GET', `/api/events/${TD.eid}`);
  check(td && td.all_day && td.start === t2 && td.end === day(3) && /^FREQ=WEEKLY;BYDAY=\w\w;COUNT=3$/.test(td.rrule) && td.attendees.length === 2 && td.cal_id === W.id && td.reminders.join() === '-540',
    'created: all day, weekly x3, two people, Work, the 9:00 reminder ' + JSON.stringify(td && {s: td.start, e: td.end, r: td.rrule, rem: td.reminders}));
  // only this date of the repeating Standup
  w.eval(`calInvalidate(); S.calMode = 'day'; S.calSel = '${day(2)}'; renderView()`);
  await until(() => [...d.querySelectorAll('#view .wcev')].some(x => /Standup/.test(x.textContent)));
  click(w, [...d.querySelectorAll('#view .wcev')].find(x => /Standup/.test(x.textContent)));
  await until(() => d.querySelector('#pop .evpop [data-evp="edit"]'));
  check(/Daily/.test(d.querySelector('#pop .evpop').textContent), 'popover: the repeat');
  click(w, d.querySelector('#pop [data-evp="edit"]'));
  await until(() => d.querySelector('.modal.evmodal [data-evsc="one"]'));
  md = d.querySelector('.modal.evmodal');
  click(w, md.querySelector('[data-evsc="one"]'));
  check(md.querySelector('.evrep').hidden && md.querySelector('#ev-sd').value === day(2), '"Only this date": its date, no repeat / people');
  w.eval(`dpSet(document.querySelector('#ev-stm'), '10:00'); dpSet(document.querySelector('#ev-etm'), '10:30')`);
  click(w, md.querySelector('[data-evm="save"]'));
  check(await until(async () => (await call('GET', `/api/events/${SU.id}`)).overrides?.[0]?.start === `${day(2)}T10:00`), 'saved as a changed date');
  // delete one date
  w.eval(`calInvalidate(); renderView()`);
  await until(() => [...d.querySelectorAll('#view .wcev')].some(x => /Standup/.test(x.textContent)));
  click(w, [...d.querySelectorAll('#view .wcev')].find(x => /Standup/.test(x.textContent)));
  await until(() => d.querySelector('#pop [data-evp="del"]'));
  click(w, d.querySelector('#pop [data-evp="del"]'));
  await until(() => d.querySelector('.modal [data-sc="one"]'));
  click(w, d.querySelector('.modal [data-sc="one"]'));
  check(await until(async () => (await call('GET', `/api/events/${SU.id}`)).exdates.length === 1), '"Only this date" deleted: left out');
  // the quick sheet from a free slot: "Event"
  w.eval(`S.calMode = 'week'; S.calSel = '${t1}'; renderView()`); await sleep(100);
  const col = d.querySelector(`#view .wcol[data-day="${t1}"]`);
  click(w, col); await sleep(150);
  const qb = d.querySelector('.qadd.sheet .qevbtn');
  check(qb && qb.getAttribute('aria-label') === 'Create an event at this time instead', 'the quick sheet has "Event" (with its name)');
  d.querySelector('#qsheet').value = 'Lunch';
  click(w, qb); await until(() => d.querySelector('.modal.evmodal'));
  md = d.querySelector('.modal.evmodal');
  check(md.querySelector('#ev-title').value === 'Lunch' && md.querySelector('#ev-sd').value === t1 && /^\d\d:\d\d$/.test(md.querySelector('#ev-stm').value), 'the typed title and the slot go into the editor');
  click(w, md.querySelector('[data-evm="close"]'));
  // agenda
  click(w, d.querySelector('#view .calbar [data-k="agenda"]')); await sleep(200);
  w.eval(`S.calSel = '${t0}'; renderView()`);
  await until(() => d.querySelector('#view .agview .agday'));
  const ag = d.querySelector('#view .agview').textContent;
  check(/Dentist \(check-up\)/.test(ag) && /Buy flowers/.test(ag) && /Team day/.test(ag) && d.querySelector('#view .agday h3'), 'agenda: events and tasks by day');
  // calendars dialog: hide, share
  click(w, d.querySelector('#view [data-act="ev-cals"]'));
  await until(() => d.querySelector('.modal.evcmodal .evcrow'));
  md = d.querySelector('.modal.evcmodal');
  check(md.querySelectorAll('.evcrow').length === 2 && md.querySelector('[data-evcshow]').getAttribute('type') === 'checkbox', 'calendars: two, each with "show"');
  const sw = md.querySelector(`[data-evcshow="${P.id}"]`); sw.checked = false; change(w, sw);
  check(await until(async () => (await call('GET', '/api/evcals')).items.find(c => c.id === P.id)?.hidden), 'Private hidden');
  await until(() => !w.eval(`S.cal.items.some(e => e.title.startsWith('Dentist'))`) || true);
  click(w, md.querySelector(`[data-evcmenu="${W.id}"]`)); await sleep(100);
  const share = [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Share/.test(b.textContent));
  check(share, 'the menu of an own calendar has Share');
  click(w, share); await until(() => d.querySelector('#evs-user'));
  change(w, d.querySelector('#evs-role'), 'edit');
  click(w, d.querySelector('[data-evs="add"]'));
  check(await until(async () => (await call('GET', '/api/evcals')).items.find(c => c.id === W.id)?.members?.[0]?.role === 'edit'), 'Work shared with Bob (edit)');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  await call('PATCH', `/api/evcals/${P.id}`, {hidden: false});
  // the phone guide
  w.eval(`davGuide()`); await sleep(100);
  md = d.querySelector('.modal.dgmodal');
  check(md && md.querySelectorAll('.dgstep').length === 3 && /\/dav\//.test(md.textContent) && /app password/i.test(md.textContent), 'phone guide: address, app password, iPhone / Android / Thunderbird');
  md.remove();
  w.close();
  // Bob: the invitation (News + reply)
  w = await boot({user: 'bob', hash: 'news'}); d = w.document;
  await until(() => d.querySelector('#view .nitem'));
  check([...d.querySelectorAll('#view .nitem')].some(n => /Alice invited you: Team day/.test(n.textContent)) && [...d.querySelectorAll('#view .nitem')].some(n => /shared the calendar Work with you/.test(n.textContent)),
    'News: the invitation and the shared calendar');
  w.eval(`go('cal'); S.calMode = 'day'; S.calSel = '${t2}'; renderView()`);
  await until(() => d.querySelector('#view .cev, #view .wcev'));
  const tdc = [...d.querySelectorAll('#view .cev')].find(x => /Team day/.test(x.textContent));
  click(w, tdc); await until(() => d.querySelector('#pop .evrsvp'));
  click(w, d.querySelector('#pop [data-evps="accepted"]'));
  check(await until(async () => (await call('GET', `/api/events/${TD.eid}`, null, CB)).partstat === 'accepted'), 'Bob accepts in the popover');
  w.close();

  // ================= the contacts view
  w = await boot({user: 'alice', hash: 'contacts'}); d = w.document;
  await until(() => d.querySelector('#view .ctrow'));
  check(d.querySelector('#side [data-go="contacts"]') && d.querySelector('#top h1')?.textContent.includes('Contacts'), 'the sidebar row + the title');
  check(d.querySelectorAll('#view .ctrow').length === 2 && /Erika Mustermann/.test(d.querySelector('#view .ctlist').textContent), 'the list');
  input(w, d.querySelector('#ct-q'), 'plumb');
  check(await until(() => d.querySelectorAll('#view .ctrow').length === 1 && /Joe/.test(d.querySelector('#view .ctrow').textContent)), 'search');
  input(w, d.querySelector('#ct-q'), '');
  await until(() => d.querySelectorAll('#view .ctrow').length === 2);
  change(w, d.querySelector('#ct-group'), 'Customers');
  check(await until(() => d.querySelectorAll('#view .ctrow').length === 1), 'group filter');
  change(w, d.querySelector('#ct-group'), '');
  await until(() => d.querySelectorAll('#view .ctrow').length === 2);
  click(w, [...d.querySelectorAll('#view .ctrow')].find(r => /Erika/.test(r.textContent)));
  await until(() => d.querySelector('#view .ctcard h3'));
  const card = d.querySelector('#view .ctcard');
  check(/Erika Mustermann/.test(card.querySelector('h3').textContent) && card.querySelector('a[href="tel:+491701234567"]') && card.querySelector('a[href="mailto:erika@example.org"]')
    && /12.*1964/.test(card.textContent) && /Work/.test(card.textContent), 'the card: phone + e-mail as links, the birthday, the kind');
  click(w, card.querySelector('[data-ct="edit"]'));
  await until(() => d.querySelector('.modal.ctmodal'));
  md = d.querySelector('.modal.ctmodal');
  check(md.querySelector('#ct-given').value === 'Erika' && md.querySelectorAll('[data-ctm="phones"] .ctmi').length === 1, 'the editor shows the contact');
  click(w, md.querySelector('[data-ctadd="phones"]'));
  const ph = [...md.querySelectorAll('[data-ctm="phones"] input[data-cf="value"]')].pop();
  input(w, ph, '030 123'); change(w, [...md.querySelectorAll('[data-ctm="phones"] .ctty')].pop(), 'work');
  md.querySelector('#ct-bday-noy').checked = true;
  click(w, md.querySelector('[data-ctm2="save"]'));
  check(await until(async () => { const c = await call('GET', `/api/contacts/${C1.id}`); return c.phones?.length === 2 && c.phones[1].type[0] === 'work' && c.bday === '--08-12'; }), 'saved: a second phone (work), the birthday without the year');
  // new contact
  click(w, d.querySelector('#view [data-ct="new"]'));
  await until(() => d.querySelector('.modal.ctmodal'));
  md = d.querySelector('.modal.ctmodal');
  click(w, md.querySelector('[data-ctm2="save"]'));
  check(/A name or a company/.test(d.querySelector('#toast').textContent) && d.querySelector('.modal.ctmodal'), 'no name: a hint, nothing saved');
  md.querySelector('#ct-given').value = 'Max'; md.querySelector('#ct-family').value = 'Power';
  input(w, md.querySelector('[data-ctm="emails"] input[data-cf="value"]'), 'max@example.org');
  click(w, md.querySelector('[data-ctm2="save"]'));
  check(await until(async () => (await call('GET', '/api/contacts?q=power')).items?.[0]?.email === 'max@example.org'), 'a new contact');
  w.close();
  // the task panel: link a contact, schedule as an event
  const T = await call('POST', '/api/tasks', {title: 'Wait for the offer', due: t2});
  w = await boot({user: 'alice', hash: 't/' + T.id}); d = w.document;
  await until(() => d.querySelector('#detail .lksec'));
  const lk = d.querySelector('#detail .lksec');
  check(/People and dates/.test(lk.textContent) && lk.querySelector('[data-act="ct-link"]') && lk.querySelector('[data-act="ev-from-task"]'), 'the task panel: "People and dates"');
  click(w, lk.querySelector('[data-act="ct-link"]'));
  await until(() => d.querySelector('#pop .ctpick [data-ctpick]'));
  click(w, d.querySelector('#pop [data-ctpk="waiting"]'));
  click(w, [...d.querySelectorAll('#pop [data-ctpick]')].find(b => /Erika/.test(b.textContent)));
  check(await until(() => /Erika Mustermann/.test(d.querySelector('#detail .lksec')?.textContent || '') && /Waiting on/.test(d.querySelector('#detail .lksec').textContent)), 'linked: Erika, waiting on');
  check(await until(async () => (await call('GET', '/api/state')).tcontacts[T.id]?.[0]?.kind === 'waiting'), '… on the server');
  click(w, d.querySelector('#detail [data-act="ev-from-task"]'));
  await until(() => d.querySelector('.modal.evmodal'));
  md = d.querySelector('.modal.evmodal');
  check(md.querySelector('#ev-title').value === 'Wait for the offer' && md.querySelector('#ev-allday').checked && md.querySelector('#ev-sd').value === t2, 'scheduled from the task: its title and day');
  click(w, md.querySelector('[data-evm="save"]'));
  check(await until(() => /Wait for the offer/.test(d.querySelector('#detail .lksec [data-evopen]')?.textContent || '')), 'the task panel lists the event');
  click(w, d.querySelector('#detail [data-ctunlink]'));
  check(await until(async () => !(await call('GET', '/api/state')).tcontacts[T.id]), 'unlinked');
  w.close();
  // German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'contacts'}); d = w.document;
  await until(() => d.querySelector('#view .ctrow'));
  check(d.querySelector('#ct-q').placeholder === 'Kontakte suchen' && /Neuer Kontakt/.test(d.querySelector('#view [data-ct="new"]').textContent), 'German: the contacts view');
  w.eval(`evEditor({})`); await until(() => d.querySelector('.modal.evmodal'));
  check(/Neuer Termin/.test(d.querySelector('.modal.evmodal h3').textContent) && d.querySelector('.modal.evmodal label[for="ev-loc"]').textContent === 'Ort', 'German: the editor');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= #673: the server is down, the device online
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  await until(() => d.querySelector('#view'));
  w.eval(`(() => { const f = window.fetch; window.__f0 = f; window.fetch = (u, o) => String(u).includes('/api/') ? Promise.resolve(new Response('<html><h1>502 Bad Gateway</h1></html>', {status: 502, headers: {'content-type': 'text/html'}})) : f(u, o); return 1; })()`);
  const reloads0 = w.eval('typeof __reloads === "number" ? __reloads : 0');
  await w.eval(`load().catch(e => (window.__lerr = e.message))`); await sleep(200);
  w.eval('staleDraw()');
  check(w.eval('OUT.online === false && OUT.down === true') && /Server not reachable – changes are sent later/.test(d.querySelector('#stale')?.textContent || ''), '#673: 502 = server not reachable, the calm hint');
  check(w.eval('S.lists.length > 0') && reloads0 === 0, '… the cached data stays, no reload loop');
  const n0 = (await call('GET', '/api/state')).tasks.length;
  await w.eval(`createTask({title: 'Written while the server is down', list_id: inbox().id}).catch(() => 0)`); await sleep(200);
  check(w.eval('OUT.q.length') === 1, '… a change waits in the outbox');
  w.eval(`window.fetch = window.__f0`);
  await w.eval(`flush()`);
  check(await until(async () => (await call('GET', '/api/state')).tasks.length === n0 + 1) && w.eval('OUT.online && !OUT.down'), '… and is sent once the server answers');
  w.close();
  // boot while the server answers 502: the cached state instead of the error page
  const st0 = await call('GET', '/api/state');
  w = await boot({user: 'alice', hash: 'inbox', ls: {'tasks.cache': JSON.stringify(st0), 'tasks.uid': '1'}, setup: win => {
    const f = win.fetch; win.fetch = (u, o) => String(u).includes('/api/') ? Promise.resolve(new Response('bad gateway', {status: 502, headers: {'content-type': 'text/html'}})) : f(u, o);
  }}); d = w.document;
  await sleep(500);
  check(!/Server not reachable\./.test(d.querySelector('#view')?.textContent || '') && d.querySelector('#side') && w.eval('S.lists.length') > 0, '#673: start with the server down: the cached tasks, not the error page');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, user, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel = '#top h1', n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(700); };
  const SMALL = sel => `(() => { const coarse = matchMedia('(pointer: coarse)').matches, min = coarse ? 43.5 : 23.5; return [...document.querySelectorAll('${sel}')].filter(b => { const r = b.getBoundingClientRect(), cs = getComputedStyle(b); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && !b.closest('[hidden]'); })
    .filter(b => { const r = b.getBoundingClientRect(); return r.width < min || r.height < min; }).map(b => (b.dataset.act || b.dataset.evm || b.dataset.ct || b.className) + ' ' + Math.round(b.getBoundingClientRect().width) + 'x' + Math.round(b.getBoundingClientRect().height)).slice(0, 8); })()`;
  const axe = async (ev, where) => {
    if ((await ev(`typeof axe`)) === 'undefined') await ev(AXE + '\n;1');
    const r = await ev(`axe.run(document, {runOnly: {type: 'tag', values: ${JSON.stringify(TAGS)}}, resultTypes: ['violations']}).then(r => r.violations.map(v => ({id: v.id, n: v.nodes.length, nodes: v.nodes.slice(0, 2).map(x => x.target.join(' ') + ' ' + (x.failureSummary || '').slice(0, 120))})))`);
    check(!r.length, `${where}: no axe violations: ` + r.map(v => `${v.id}(${v.n}) ${v.nodes[0]}`).join(' | ').slice(0, 700));
  };
  const sideways = ev => ev(`document.documentElement.scrollWidth - innerWidth`);
  for (const [vw, vh, th] of [[390, 844, 'dark'], [690, 829, 'light'], [829, 690, 'dark']]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = `${vw}x${vh} ${th}`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    check(await ffLogin(o, 'alice', th) === 200, tag + ': login');
    await o.nav(B + '#cal'); await ready(ev, '#view .calbar');
    await ev(`(() => { S.calMode = 'week'; S.calSel = '${t1}'; calInvalidate(); renderView(); return 1; })()`); await sleep(900);
    check(await sideways(ev) <= 0, `${tag}: week: nothing sideways`);
    check(await ev(`[...document.querySelectorAll('#view .wcev')].length > 0`), `${tag}: week: own events as blocks`);
    const sm0 = await ev(SMALL('#view .calbar button'));
    check(!sm0.length, `${tag}: calendar bar: 44 px ` + JSON.stringify(sm0));
    if (vw === 390) await axe(ev, `${tag} week view`);
    await shot(`p2210-${vw}x${vh}-${th}-week.png`);
    await ev(`(() => { S.calMode = 'agenda'; S.calSel = '${t0}'; renderView(); return 1; })()`); await sleep(500);
    check(await sideways(ev) <= 0, `${tag}: agenda: nothing sideways`);
    if (vw === 390) await axe(ev, `${tag} agenda`);
    await shot(`p2210-${vw}x${vh}-${th}-agenda.png`);
    await ev(`(() => { evEditor({ev: null}); return 1; })()`); await sleep(600);
    check(await ev(`(() => { const c = document.querySelector('.modal.evmodal .card').getBoundingClientRect(); return c.left >= 0 && c.right <= innerWidth + .5; })()`), `${tag}: the editor fits`);
    const sm1 = await ev(SMALL('.modal.evmodal button, .modal.evmodal select, .modal.evmodal .dpbtn'));
    check(!sm1.length, `${tag}: editor: 44 px ` + JSON.stringify(sm1));
    if (vw !== 829) await axe(ev, `${tag} event editor`);
    await shot(`p2210-${vw}x${vh}-${th}-editor.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    await o.nav(B + '#contacts'); await ready(ev, '#view .ctrow');
    check(await sideways(ev) <= 0, `${tag}: contacts: nothing sideways`);
    const sm2 = await ev(SMALL('#view .ctview button, #view .ctview input, #view .ctview select'));
    check(!sm2.length, `${tag}: contacts: 44 px ` + JSON.stringify(sm2));
    if (vw === 390) await axe(ev, `${tag} contacts`);
    await ev(`(() => { [...document.querySelectorAll('#view .ctrow')].find(r => /Erika/.test(r.textContent)).click(); return 1; })()`); await sleep(900);
    check(await ev(`!!document.querySelector('#view .ctcard h3')`) && await sideways(ev) <= 0, `${tag}: the card, nothing sideways`);
    const sm3 = await ev(SMALL('#view .ctcard button, #view .ctcard a'));
    check(!sm3.length, `${tag}: card: 44 px ` + JSON.stringify(sm3));
    if (vw !== 829) await axe(ev, `${tag} contact card`);
    await shot(`p2210-${vw}x${vh}-${th}-card.png`);
    await o.nav(B + '#t/' + T.id); await ready(ev, '#detail .lksec');
    check(await sideways(ev) <= 0, `${tag}: task panel: nothing sideways`);
    const sm4 = await ev(SMALL('#detail .lksec button'));
    check(!sm4.length, `${tag}: "People and dates": 44 px ` + JSON.stringify(sm4));
    if (vw === 390) await axe(ev, `${tag} task panel`);
  }, true);
  await firefox(async o => {
    const {cmd, ev, ctx, shot, drag} = o, tag = '1440 light';
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    check(await ffLogin(o, 'alice', 'light') === 200, tag + ': login');
    await o.nav(B + '#cal'); await ready(ev, '#view .calbar');
    await ev(`(() => { S.calMode = 'week'; S.calSel = '${t1}'; calInvalidate(); renderView(); document.querySelector('#wbody').scrollTop = 8 * weekH(); return 1; })()`); await sleep(900);
    check(await sideways(ev) <= 0, `${tag}: week: nothing sideways`);
    await axe(ev, `${tag} week view`);
    // drag over free time: 13:00-14:30 of the day after tomorrow
    const r = await ev(`(() => { const c = document.querySelector('#view .wcol[data-day="${t2}"]'), b = c.getBoundingClientRect(), H = weekH(); return {x: b.left + b.width / 2, y: b.top + 13 * H + 2, dy: 1.5 * H}; })()`);
    await drag(r.x, r.y, 0, r.dy);
    await sleep(600);
    const got = await ev(`(() => { const m = document.querySelector('.modal.evmodal'); return m ? [m.querySelector('#ev-sd').value, m.querySelector('#ev-stm').value, m.querySelector('#ev-etm').value] : null; })()`);
    check(got && got[0] === t2 && got[1] === '13:00' && got[2] === '14:30', `${tag}: a drag over free time opens the editor with that time ${JSON.stringify(got)}`);
    // Tab stays in the editor
    await ev(`(() => { document.querySelector('#ev-title').focus(); return 1; })()`);
    let inside = true;
    for (let i = 0; i < 30; i++) { await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'kb', actions: [{type: 'keyDown', value: '\uE004'}, {type: 'keyUp', value: '\uE004'}]}]}); await sleep(40); inside = inside && await ev(`!!document.activeElement.closest('.modal.evmodal')`); }
    check(inside, `${tag}: Tab stays in the editor`);
    await shot('p2210-1440-editor.png');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); document.querySelector('#view [data-act="ev-cals"]').click(); return 1; })()`); await sleep(700);
    await axe(ev, `${tag} calendars dialog`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); davGuide(); return 1; })()`); await sleep(400);
    await axe(ev, `${tag} phone guide`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    await o.nav(B + '#contacts'); await ready(ev, '#view .ctrow');
    await ev(`(() => { document.querySelector('#view .ctrow').click(); return 1; })()`); await sleep(700);
    check(await ev(`(() => { const l = document.querySelector('#view .ctlistw').getBoundingClientRect(), c = document.querySelector('#view .ctcard').getBoundingClientRect(); return c.left >= l.right - 1; })()`), `${tag}: list and card side by side`);
    await axe(ev, `${tag} contacts with the card`);
    await ev(`(() => { ctEditor(CT.card); return 1; })()`); await sleep(500);
    await axe(ev, `${tag} contact editor`);
    await shot('p2210-1440-contacts.png');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
