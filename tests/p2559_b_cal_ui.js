// 2.559.0 UI test, part B (#4659): calendar writes show at once (optimistic like optWrite), jsdom, invented names only:
// kalmido-suite: fresh
// - a new event: the editor closes and the event stands (a stand-in with a negative id) while the answer is held; the answer
//   brings the real id; a refused one (500) is taken back and the editor opens again with the title typed
// - a changed title shows at once; a refusal (409) puts the old one back and opens the editor again with what was typed
// - deleting: gone at once, a refusal (500) brings it back; Undo of the toast puts it back at once (restore held)
// - "Show in my calendar" off: c.hidden and its events go at once, a refusal switches it back
// - dragging an event an hour later: it stands at the new time before the answer, a refusal puts it back
// - a range fetched again while a write is held (calInvalidate + ensureCalEv) keeps the own change on top
// - none of these actions fetches GET /api/state
// freelancer-matrix: events (alice has no organisation: her private workspace)
// The held answers wait in the page (window.fetch wrapped) until the test lets them go: every wait is on a real state.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until: until0, undoToast} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const D0 = dstr(new Date());
// requests matching re ("METHOD /url") wait in w.__held until the test calls go() (the real request) or fail(status); every
// request of the page is noted in w.__log (to see that no GET /api/state follows an action)
const hold = (w, re) => {
  w.__held = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => { const k = `${o.method || 'GET'} ${u}`; (w.__log = w.__log || []).push(k);
    return re.test(k) ? new Promise(res => w.__held.push({u: String(u), go: () => { w.__goAt = w.__log.length; res(f1(u, o)); }, fail: (st = 500) => res(new Response(JSON.stringify({error: 'Refused for the test'}), {status: st, headers: {'content-type': 'application/json'}}))})) : f1(u, o); };
};
// no load() of the own action since mark i (no GET /api/state before or after the answer): load() is wrapped once and notes
// whether it was the live update's (load(true, ...), it may come on its own after any write) or an action's own (load())
const mark = w => {
  if (!w.__lw) { w.__lw = 1; w.eval(`{ const l0 = load; load = (...a) => { (window.__loads = window.__loads || []).push(a[0] ? 'auto' : 'own'); return l0(...a); }; }`); }
  return (w.__loads || []).length;
};
const noState = (w, i) => !(w.__loads || []).slice(i).includes('own');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events'});
  const W = await call('POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  const P = await call('POST', '/api/evcals', {name: 'Private', color: '#f472b6'});
  const SU = await call('POST', '/api/events', {title: 'Standup', cal_id: W.id, start: `${D0}T09:00`, end: `${D0}T09:30`, reminders: []});
  const DE = await call('POST', '/api/events', {title: 'Dentist', cal_id: P.id, start: `${D0}T15:00`, end: `${D0}T16:00`, reminders: []});
  check(SU.id && DE.id, 'two events on the server');

  const w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}), d = w.document;
  await until(() => w.eval(`typeof cg_end === 'function' && typeof evEditor === 'function' && typeof evOpt === 'function'`));
  const item = t => `S.cal.items.find(x => x.own && x.title === ${JSON.stringify(t)})`;
  const chip = t => d.querySelector(`#view .cev[title=${JSON.stringify(t)}]`);
  check(await until(() => chip('Standup') && chip('Dentist')), 'the month shows both events');
  hold(w, /^$/);  // only the log for now

  // ================= a new event: the dialog closes, the stand-in stands, the answer held
  hold(w, /^POST \/api\/events$/);
  w.eval(`evEditor({start: '${D0}T11:00', end: '${D0}T12:00'})`);
  let md = await until(() => d.querySelector('.modal.evmodal #ev-title') && d.querySelector('.modal.evmodal'));
  md.querySelector('#ev-title').value = 'Review';
  let i0 = mark(w);
  click(w, md.querySelector('[data-evm="save"]'));
  check(await until(() => w.__held.length === 1), 'new: the request is on its way (held)');
  check(!d.querySelector('.modal.evmodal'), 'new: the dialog closed at once');
  check(w.eval(`(${item('Review')} || {}).eid < 0`), 'new: the event stands with a negative stand-in id');
  check(await until(() => chip('Review')), 'new: the month shows it before the answer');
  // a range fetched again meanwhile keeps it (the stand-in is put on top of the new answer)
  await w.eval(`(() => { const k = (S.cal.key || '${D0}|${D0}').split('|'); calInvalidate(); return ensureCalEv(k[0], k[1]); })()`);
  check(w.eval(`!!${item('Review')} && ${item('Review')}.eid < 0`), 'new: a range fetched meanwhile keeps the stand-in');
  w.__held[0].go();
  check(await until(() => w.eval(`(${item('Review')} || {}).eid > 0`)), 'new: the answer brings the real id');
  check(await until(async () => (await call('GET', `/api/events?from=${D0}&to=${D0}`)).items?.filter(x => x.title === 'Review').length === 1), 'new: one event on the server');
  check(noState(w, i0), 'new: no GET /api/state');

  // a refused new event: taken back, the editor opens again with the title
  hold(w, /^POST \/api\/events$/);
  w.eval(`evEditor({start: '${D0}T13:00', end: '${D0}T14:00'})`);
  md = await until(() => d.querySelector('.modal.evmodal #ev-title') && d.querySelector('.modal.evmodal'));
  md.querySelector('#ev-title').value = 'Refused one';
  click(w, md.querySelector('[data-evm="save"]'));
  check(await until(() => w.__held.length === 1 && chip('Refused one')), 'refused new: shown at once');
  w.__held[0].fail(500);
  check(await until(() => !w.eval(`!!${item('Refused one')}`) && !chip('Refused one')), 'refused new: the stand-in goes again');
  check(await until(() => d.querySelector('.modal.evmodal #ev-title')?.value === 'Refused one'), 'refused new: the editor opens again with the title typed');
  d.querySelectorAll('.modal').forEach(m => m.remove());

  // ================= a changed title shows at once; a refusal (409) puts the old one back
  const openEdit = async () => {
    const ev = await call('GET', `/api/events/${SU.id}`);
    w.eval(`evEditor({ev: ${JSON.stringify(ev)}})`);
    return until(() => d.querySelector('.modal.evmodal #ev-title') && d.querySelector('.modal.evmodal'));
  };
  hold(w, /^PATCH \/api\/events\/\d+/);
  md = await openEdit();
  md.querySelector('#ev-title').value = 'Standup moved';
  i0 = mark(w);
  click(w, md.querySelector('[data-evm="save"]'));
  check(await until(() => w.__held.length === 1), 'edit: held');
  check(!d.querySelector('.modal.evmodal') && await until(() => chip('Standup moved') && !chip('Standup')), 'edit: the new title shows at once');
  w.__held[0].fail(409);
  check(await until(() => chip('Standup') && !chip('Standup moved')), 'edit: a refusal (409) puts the old title back');
  check(await until(() => d.querySelector('.modal.evmodal #ev-title')?.value === 'Standup moved'), 'edit: after the refusal the editor opens again with what was typed');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  hold(w, /^PATCH \/api\/events\/\d+/);
  md = await openEdit();
  md.querySelector('#ev-title').value = 'Standup moved';
  click(w, md.querySelector('[data-evm="save"]'));
  check(await until(() => w.__held.length === 1 && chip('Standup moved')), 'edit again: at once');
  w.__held[0].go();
  check(await until(async () => (await call('GET', `/api/events/${SU.id}`)).title === 'Standup moved'), 'edit: saved on the server');
  await until(() => (w.__log || []).slice(w.__goAt).some(k => /^GET \/api\/calendars\/events/.test(k)));  // the follow-up after the answer ran (the old way: load() first)
  check(noState(w, i0), 'edit: no GET /api/state');

  // ================= dragging an hour later: at the new time before the answer, a refusal puts it back
  const startOf = t => w.eval(`(${item(t)} || {}).start`);
  const s0 = startOf('Standup moved');
  const drag = mins => w.eval(`(() => { const ev = ${item('Standup moved')}; CG.st = {kind: 'move', ev, active: true, on: true, dd: 0, dm: ${mins}, ghost: document.createElement('i')}; cg_end(); return 1; })()`);
  hold(w, /^PATCH \/api\/events\/\d+/);
  i0 = mark(w);
  drag(60);
  check(await until(() => startOf('Standup moved') === new Date(+new Date(s0) + 3600e3).toISOString().replace(/\.\d{3}Z$/, 'Z')), 'drag: the new time shows at once ' + startOf('Standup moved'));
  check(await until(() => w.__held.length === 1), 'drag: the request is held');
  w.__held[0].fail(500);
  check(await until(() => startOf('Standup moved') === s0), 'drag: a refusal puts the old time back');
  hold(w, /^PATCH \/api\/events\/\d+/);
  drag(60);
  check(await until(() => w.__held.length === 1 && startOf('Standup moved') !== s0), 'drag again: at once');
  w.__held[0].go();
  check(await until(async () => (await call('GET', `/api/events/${SU.id}`)).start === `${D0}T10:00`), 'drag: saved on the server (10:00)');
  await until(() => (w.__log || []).slice(w.__goAt).some(k => /^GET \/api\/calendars\/events/.test(k)));  // the follow-up after the answer ran (the old way: load() first)
  check(noState(w, i0), 'drag: no GET /api/state');

  // ================= delete: gone at once, a refusal brings it back; Undo puts it back at once
  const del = async () => {
    w.eval(`evDelete(${JSON.stringify(await call('GET', `/api/events/${DE.id}`))}, null)`);
    const q = await until(() => d.querySelector('.modal [data-cd="yes"]'));
    click(w, q);
  };
  hold(w, /^DELETE \/api\/events\/\d+/);
  i0 = mark(w);
  await del();
  check(await until(() => w.__held.length === 1), 'delete: held');
  check(await until(() => !chip('Dentist') && !w.eval(`!!${item('Dentist')}`)), 'delete: gone at once');
  w.__held[0].fail(500);
  check(await until(() => chip('Dentist')), 'delete: a refusal brings it back');
  hold(w, /^(DELETE \/api\/events\/\d+|POST \/api\/events\/\d+\/restore)$/);
  await del();
  check(await until(() => w.__held.length === 1 && !chip('Dentist')), 'delete again: gone at once');
  w.__held[0].go();
  check(await until(async () => (await call('GET', `/api/events?from=${D0}&to=${D0}`)).items?.every(x => x.title !== 'Dentist')), 'delete: gone on the server');
  await until(() => (w.__log || []).slice(w.__goAt).some(k => /^GET \/api\/calendars\/events/.test(k)));  // the follow-up after the answer ran (the old way: load() first)
  check(noState(w, i0), 'delete: no GET /api/state');
  check(await undoToast(w, 'Event deleted'), 'delete: the toast offers Undo');
  check(await until(() => w.__held.length === 2), 'undo: the restore is held');
  check(await until(() => chip('Dentist')), 'undo: the event is back at once');
  w.__held[1].go();
  check(await until(async () => (await call('GET', `/api/events?from=${D0}&to=${D0}`)).items?.some(x => x.title === 'Dentist')), 'undo: restored on the server');
  check(await until(() => chip('Dentist')), 'undo: it stays after the range came again');

  // ================= "Show in my calendar" off: at once; a refusal switches it back
  click(w, d.querySelector('#view [data-act="ev-cals"]'));
  md = await until(() => d.querySelector(`.modal.evcmodal [data-evcshow="${P.id}"]`) && d.querySelector('.modal.evcmodal'));
  const flip = () => { const sw = md.querySelector(`[data-evcshow="${P.id}"]`); sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true})); };
  hold(w, /^PATCH \/api\/evcals\/\d+$/);
  i0 = mark(w);
  flip();
  check(await until(() => w.__held.length === 1), 'hide: held');
  check(w.eval(`evCal(${P.id}).hidden === true`) && !md.querySelector(`[data-evcshow="${P.id}"]`).checked, 'hide: c.hidden at once, the switch off');
  check(await until(() => !chip('Dentist')), 'hide: its events leave the month at once');
  w.__held[0].fail(500);
  check(await until(() => w.eval(`evCal(${P.id}).hidden === false`) && md.querySelector(`[data-evcshow="${P.id}"]`).checked), 'hide: a refusal switches it back');
  check(await until(() => chip('Dentist')), 'hide: a refusal brings its events back');
  hold(w, /^PATCH \/api\/evcals\/\d+$/);
  flip();
  check(await until(() => w.__held.length === 1 && !chip('Dentist')), 'hide again: at once');
  w.__held[0].go();
  check(await until(async () => (await call('GET', '/api/evcals')).items.find(c => c.id === P.id)?.hidden === true), 'hide: saved on the server');
  await until(() => (w.__log || []).slice(w.__goAt).some(k => /^GET \/api\/calendars\/events/.test(k)));  // the follow-up after the answer ran (the old way: load() first)
  check(noState(w, i0), 'hide: no GET /api/state');
  check(await until(() => !chip('Dentist') && chip('Standup moved')), 'hide: stays hidden after the range came again');

  w.close();
  console.log(`p2559_b_cal_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
