// 2.1130.0 (#6057): a chat push while a window shows the pop-up stays away on this device (static/sw.js pushShow)
// kalmido-suite: nodata
// No browser, no server: static/sw.js runs in a vm with fake clients and a fake registration.
// - a chat push (#team/<id>, #msg/t/<room>/<id>, #agents/<id>) and a visible window that answers {visible: true}: no notification
// - the window answers {visible: false} (pop-up off), is hidden, does not answer in time, or there is none: shown as before
// - another push (a task, a reminder) always shows, the window is not even asked
// - WebKit (Safari, the iPhone's Home Screen app): shown silently and closed at once (never a push without a notification)
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const SRC = process.env.KALMIDO_SRC || path.join(__dirname, '..');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };

(async () => {
  const SW = fs.readFileSync(path.join(SRC, 'static', 'sw.js'), 'utf8');
  let shown = [], closed = 0, asked = 0, wins = [], ua = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';
  const win = (vis, answer) => ({visibilityState: vis, url: 'https://kalmido.example/#today', postMessage(m, ports) {
    asked++;
    if (m?.type === 'msgpop?' && answer !== undefined) setTimeout(() => ports[0].postMessage(answer), 5);
  }});
  class Port { constructor() { this.other = null; this.onmessage = null; } postMessage(d) { const o = this.other; setTimeout(() => o.onmessage && o.onmessage({data: d}), 0); } }
  class MessageChannel { constructor() { this.port1 = new Port(); this.port2 = new Port(); this.port1.other = this.port2; this.port2.other = this.port1; } }
  const reg = {showNotification: async (t, o) => { shown.push({t, o}); }, getNotifications: async ({tag} = {}) => shown.filter(x => !tag || x.o.tag === tag).map(x => ({close: () => { closed++; }}))};
  const ctx = vm.createContext({
    self: {addEventListener() {}, location: {origin: 'https://kalmido.example'}, clients: {matchAll: async () => wins}, registration: reg,
      get navigator() { return {userAgent: ua}; }},
    caches: {open: async () => ({keys: async () => [], delete: async () => true, put: async () => {}}), match: async () => undefined},
    MessageChannel, URL, setTimeout, clearTimeout, console, JSON, Date,
  });
  vm.runInContext(SW, ctx);
  const push = async d => { shown = []; closed = 0; asked = 0; await vm.runInContext(`pushShow(${JSON.stringify(d)})`, ctx); };
  const team = {title: 'Shoot Berlin', body: 'Bob: The van is booked', url: '/#team/12', tag: 'team-12'};

  wins = [win('visible', {visible: true})];
  await push(team);
  check(shown.length === 0 && asked === 1, 'chat push + a visible window with the pop-up: no notification ' + JSON.stringify(shown));
  await push({...team, url: '/#msg/t/12/99'});
  check(shown.length === 0, 'a thread answer: no notification either');
  await push({title: 'Claude', body: 'Shall I send it?', url: '/#agents/5'});
  check(shown.length === 0, "an agent's answer: no notification either");
  await push({title: 'Due today', body: 'Call the client', url: '/#t/44', task: 44});
  check(shown.length === 1 && asked === 0, 'a task push always shows, nobody is asked');

  wins = [win('visible', {visible: false})];
  await push(team);
  check(shown.length === 1 && shown[0].o.body === team.body, 'the pop-up off on that window: shown as before');
  wins = [win('hidden', {visible: true})];
  await push(team);
  check(shown.length === 1 && asked === 0, 'a hidden window: shown, not asked');
  wins = [win('visible', undefined)];
  const t0 = Date.now();
  await push(team);
  check(shown.length === 1 && Date.now() - t0 < 2000, 'no answer in time: shown (after the short wait)');
  wins = [];
  await push(team);
  check(shown.length === 1, 'no window at all: shown');

  ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
  wins = [win('visible', {visible: true})];
  await push(team);
  check(shown.length === 1 && shown[0].o.silent === true && closed === 1, 'WebKit: shown silently and closed at once ' + JSON.stringify(shown.map(x => x.o.silent)) + ' closed ' + closed);

  console.log(F.length ? `FAILED ${F.length} of ${ok + F.length}` : `OK ${ok}`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
