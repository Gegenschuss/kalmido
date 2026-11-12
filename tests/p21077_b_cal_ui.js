// 2.1077.0 UI test, part B (#5461 calendar polish: loading, empty and error states from the shared block of #5440), jsdom,
// kalmido-suite: fresh
// own container (start.sh), invented names only. P21077B_NOSTART=1 = the container runs.
// freelancer-matrix: n/a (no new route; alice has no organisation, every check runs without one)
// - month: a failed GET /api/calendars/events says "Events could not be loaded" with "Try again" over the grid (not an empty
//   month), the view does not fetch again by itself on every drawing (no loop); "Try again" loads and the events show
// - month: while the range loads a quiet "Loading…" floats over the grid; it goes once the events are there
// - offline with a saved copy: the events of the copy show and the view says it is the saved copy
// - the day list under the month: a day with an event and no task has no "nothing" line, an empty day says "Nothing planned
//   on this day."; turning the month moves the day list along (no "Today" under another month), Today brings it back
// - week, day, year without any entry: a quiet hint "Nothing planned …"; the agenda's "nothing" is the shared block
// - the event editor: a refused save opens the editor again and it says "Not saved: …" (role=alert) with what was typed
// - the "Calendars" window: opens while the people still load; a failed trash says so with "Try again" and that loads it
// - Settings > Calendars: a failed load says so with "Try again" (not always "Only available online.")
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21077B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const txt = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const D0 = dstr(new Date());
// the page's requests: every one noted in w.__log; one matching w.__fail fails with 500, one matching w.__hold waits in
// w.__held until the test lets it go (go) - every wait below is on a real state
const wrap = w => {
  const f1 = w.fetch;
  w.__log = []; w.__held = []; w.__fail = null; w.__hold = null;
  w.fetch = (u, o = {}) => {
    const k = `${o.method || 'GET'} ${u}`; w.__log.push(k);
    if (w.__fail && w.__fail.test(k)) return Promise.resolve(new Response(JSON.stringify({error: 'Refused for the test'}), {status: 500, headers: {'content-type': 'application/json'}}));
    if (w.__hold && w.__hold.test(k)) return new Promise(res => w.__held.push({k, go: () => res(f1(u, o))}));
    return f1(u, o);
  };
};
const nEv = w => w.__log.filter(k => /^GET \/api\/calendars\/events/.test(k)).length;

(async () => {
  await sleep(600);
  check(await until(async () => (await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})}).catch(() => null))?.status < 500), 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events,collab'});
  const W = await call('POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  const SU = await call('POST', '/api/events', {title: 'Standup', cal_id: W.id, start: `${D0}T09:00`, end: `${D0}T09:30`, reminders: []});
  check(W.id && SU.id, 'set-up: a calendar with one event today');
  const me = (await call('GET', '/api/state')).me;
  check(!(me?.workspaces || []).length, 'alice: no organisation (freelancer)');

  const w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}), d = w.document;
  await until(() => w.eval(`typeof calEvState === 'function' && typeof evEditor === 'function' && typeof evCalsModal === 'function'`));
  wrap(w);
  const chip = t => d.querySelector(`#view .cev[title=${JSON.stringify(t)}]`);
  const st = () => d.querySelector('#view .calst');
  check(await until(() => chip('Standup')), 'the month shows the event');
  check(!st(), 'loaded: no state over the grid');

  // ================= a failed fetch: an error with "Try again", never an empty month, no loop of fetches
  w.eval(`LS.set('calev', {})`);  // no saved copy
  w.__fail = /^GET \/api\/calendars\/events/;
  w.eval('calInvalidate(); S.cal.items = []; renderView()');  // a range not loaded yet (a range loaded before keeps its events while it loads again)
  const err = await until(() => d.querySelector('#view .calst .eerr'));
  check(err && /Events could not be loaded/.test(txt(err)) && err.querySelector('[data-esretry]'), '#5461: a failed load says so with "Try again": ' + txt(err));
  check(err?.getAttribute('class').includes('es-row') && st()?.getAttribute('aria-live') === 'polite', '#5461: the shared block (row size), announced');
  check(!chip('Standup'), '#5461: a range that never loaded has no events and says why (not an empty month without a word)');
  const n1 = nEv(w);
  w.eval('renderView(); renderView(); renderView()'); await sleep(300);
  check(nEv(w) === n1 && d.querySelector('#view .calst .eerr'), '#5461: drawing again does not fetch again by itself (no loop), the error stays ' + (nEv(w) - n1));
  w.__fail = null;
  click(w, d.querySelector('#view .calst [data-esretry]'));
  check(await until(() => chip('Standup') && !d.querySelector('#view .calst')), '#5461: "Try again" loads, the events show, the state goes');

  // ================= loading: a quiet "Loading…" over the grid while the range has nothing yet
  w.__hold = /^GET \/api\/calendars\/events/;
  w.eval('calInvalidate(); S.cal.items = []; renderView()');
  check(await until(() => w.__held.length >= 1), 'loading: the request is on its way (held)');
  const ld = await until(() => d.querySelector('#view .calst .eload'));
  check(ld && /Loading…/.test(txt(ld)) && ld.getAttribute('role') === 'status', '#5461: while it loads the month says "Loading…" ' + txt(ld));
  check(d.querySelector('#view .cal.calv .cell'), '#5461: the grid is there under it (it floats, nothing jumps)');
  w.__hold = null; w.__held.splice(0).forEach(h => h.go());
  check(await until(() => chip('Standup') && !d.querySelector('#view .calst')), '#5461: loaded: the state goes, the event shows');

  // ================= offline with a saved copy: the copy shows and says so
  w.__fail = /^GET \/api\/calendars\/events/;
  w.eval('calInvalidate(); renderView()');
  const old = await until(() => d.querySelector('#view .calst .calold'));
  check(old && /Saved copy of the events/.test(txt(old)) && chip('Standup'), '#5461: a failed load with a saved copy shows the copy and says so');
  w.__fail = null; w.eval('calInvalidate(); renderView()');
  check(await until(() => chip('Standup') && !d.querySelector('#view .calst')), 'the fresh answer again: no state');

  // ================= the day list under the month
  w.eval(`S.calSel = '${D0}'; renderView()`);
  let ag = await until(() => d.querySelector('#view .agenda'));
  check(ag.querySelector('.cevrow') && !ag.querySelector('.agnone') && !/No tasks on this day/.test(txt(ag)), '#5461: a day with an event and no task: no "nothing" line ' + txt(ag).slice(0, 80));
  const other = D0.slice(8) === '15' ? D0.slice(0, 8) + '16' : D0.slice(0, 8) + '15';
  w.eval(`S.calSel = '${other}'; renderView()`);
  ag = await until(() => d.querySelector('#view .agenda .agnone') && d.querySelector('#view .agenda'));
  check(/Nothing planned on this day\./.test(txt(ag.querySelector('.agnone'))), '#5461: an empty day says "Nothing planned on this day."');
  w.eval(`S.calSel = '${D0}'; renderView()`);
  click(w, d.querySelector('#view [data-act="cal-next"]'));
  const nm = w.eval('S.calMonth');
  check(await until(() => w.eval('S.calSel').slice(0, 7) === nm && !/^Today/.test(txt(d.querySelector('#view .agenda h3')))), '#5461: turning the month moves the day list along (no "Today" under another month): ' + w.eval('S.calSel') + ' ' + txt(d.querySelector('#view .agenda h3')));
  check(w.eval('S.calSel') === `${nm}-01`, '#5461: the 1st of the month turned to');
  click(w, d.querySelector('#view [data-act="cal-prev"]'));
  check(await until(() => w.eval('S.calSel') === D0 && /^Today/.test(txt(d.querySelector('#view .agenda h3')))), '#5461: back in this month: today again');

  // ================= week, day, year without an entry; the agenda's "nothing"
  const far = '2099-03-10';
  w.eval(`S.calMode = 'week'; S.calSel = '${far}'; renderView()`);
  let none = await until(() => d.querySelector('#view .calst .calnone'));
  check(none && /Nothing planned in these days\./.test(txt(none)) && d.querySelector('#view .week .wbody'), '#5461: an empty week says so over its hours ' + txt(none));
  w.eval(`S.calMode = 'day'; renderView()`);
  none = await until(() => d.querySelector('#view .week.oneday') && d.querySelector('#view .calst .calnone'));
  check(none && /Nothing planned on this day\./.test(txt(none)), '#5461: an empty day view says so ' + txt(none));
  w.eval(`S.calMode = 'year'; renderView()`);
  none = await until(() => d.querySelector('#view #cyear') && d.querySelector('#view .calst .calnone'));
  check(none && /Nothing planned in this year\./.test(txt(none)), '#5461: an empty year says so ' + txt(none));
  w.eval(`S.calMode = 'agenda'; renderView()`);
  none = await until(() => d.querySelector('#view .agendav .empty.nempty'));
  check(none && /Nothing in the next two weeks\./.test(txt(none)) && none.className.includes('es-sec'), '#5461: the agenda\'s "nothing" is the shared block ' + txt(none));
  w.eval(`S.calMode = 'week'; S.calSel = '${D0}'; renderView()`);
  check(await until(() => d.querySelector(`#view .wcev[title="Standup"]`) && !d.querySelector('#view .calst')), 'a week with an entry: no hint');
  w.eval(`S.calMode = 'month'; renderView()`);
  await until(() => chip('Standup'));

  // ================= the editor: a refused save says so in the editor
  w.__fail = /^POST \/api\/events$/;
  w.eval(`evEditor({start: '${D0}T13:00', end: '${D0}T14:00'})`);
  let md = await until(() => d.querySelector('.modal.evmodal #ev-title') && d.querySelector('.modal.evmodal'));
  check(!md.querySelector('.evsaveerr'), 'editor: a fresh editor has no error line');
  md.querySelector('#ev-title').value = 'Refused one';
  click(w, md.querySelector('[data-evm="save"]'));
  md = await until(() => d.querySelector('.modal.evmodal .evsaveerr') && d.querySelector('.modal.evmodal'));
  const se = md?.querySelector('.evsaveerr');
  check(se && se.getAttribute('role') === 'alert' && /^Not saved: \S/.test(txt(se)), '#5461: the editor that opens again says it was not saved and why: ' + txt(se));
  check(md?.querySelector('#ev-title')?.value === 'Refused one', '#5461: with what was typed');
  w.__fail = null;
  d.querySelectorAll('.modal').forEach(m => m.remove());

  // ================= the "Calendars" window: open at once, a failed trash says so
  w.eval('EVU = null');
  w.__hold = /^GET \/api\/users/;
  w.eval('evCalsModal()');
  check(await until(() => d.querySelector('.modal.evcmodal #evc-body')), '#5461: the Calendars window opens while the people still load');
  check(w.__held.length >= 1, 'the people request is still held');
  w.__hold = null; w.__held.splice(0).forEach(h => h.go());
  md = await until(() => d.querySelector('.modal.evcmodal [data-evc="trash"]') && d.querySelector('.modal.evcmodal'));
  w.__fail = /^GET \/api\/evcals\/trash/;
  click(w, md.querySelector('[data-evc="trash"]'));
  const te = await until(() => md.querySelector('#evc-body .eerr'));
  check(te && /Could not be loaded/.test(txt(te)) && !/The trash is empty/.test(txt(md)), '#5461: a failed trash says so, not "The trash is empty" ' + txt(te));
  w.__fail = null;
  click(w, te.querySelector('[data-esretry]'));
  check(await until(() => /The trash is empty/.test(txt(md)) && !md.querySelector('#evc-body .eerr')), '#5461: "Try again" loads the trash');
  d.querySelectorAll('.modal').forEach(m => m.remove());

  // ================= Settings > Calendars: a failed load
  w.__fail = /^GET \/api\/calendars$/;
  w.eval(`(() => { const x = document.createElement('div'); x.id = 'p21077-cals'; x.innerHTML = '<div id="s-cals"></div>'; document.body.appendChild(x); calsDraw(x); })()`);
  const box = () => d.querySelector('#p21077-cals #s-cals');
  const ce = await until(() => box()?.querySelector('.eerr'));
  check(ce && ce.querySelector('[data-esretry]') && !/Only available online/.test(txt(box())), '#5461: Settings > Calendars: a failed load with "Try again" ' + txt(ce));
  w.__fail = null;
  click(w, ce.querySelector('[data-esretry]'));
  check(await until(() => /No calendars yet\./.test(txt(box()))), '#5461: "Try again" loads the list');

  w.close();
  console.log(`p21077_b_cal_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
