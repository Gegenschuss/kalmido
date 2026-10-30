// kalmido-suite: now=wed10:00
// 2.381.0 B (#2713): the test clock in Firefox (tests/ff.js). run_all.sh runs this group at `now wed 10:00`: every page Firefox
// opens gets the shifted Date of boot.js before its own scripts, like the jsdom windows (2.192.0 A, p2192_a_clock_ui) - the
// browser's "now" is the test time (Wednesday 10:00 Berlin), the clock runs on, dates with arguments, Date.UTC and the time zone
// stay as they are; also after another page load. Without Firefox the browser part is skipped with a note (ff.js).
// Own container (start.sh). No data.
// freelancer-matrix: n/a (no route; the test clock is a test tool)
const path = require('path');
const {execFileSync} = require('child_process');
const {B, clockOffset, testNow} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2381_b_ffclock_ui', check, lazy: true});
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const berlin = ms => Object.fromEntries(new Intl.DateTimeFormat('en-US', {timeZone: 'Europe/Berlin', weekday: 'short', hour: '2-digit', hourCycle: 'h23'})
  .formatToParts(new Date(ms)).map(x => [x.type, x.value]));

(async () => {
  const set = !!(process.env.KALMIDO_TEST_NOW || '').trim();
  check(set, 'run_all.sh sets KALMIDO_TEST_NOW for this group (now wed 10:00)');
  const want = testNow().getTime();  // Node: the test time (boot.js)
  const b = berlin(want);
  check(!set || (b.weekday === 'Wed' && b.hour === '10'), `Node runs at the test time: ${b.weekday} ${b.hour} h Berlin`);
  const probe = `(() => [Date.now(), new Date().getTime(), Date(), new Date(0).getTime(), Date.UTC(2020, 0, 1), new Date() instanceof Date,
    Intl.DateTimeFormat().resolvedOptions().timeZone])()`;
  // Vorprüfung 28.10. (job #1656): the app was page 1 and the plain picture page 2; navigating away from the starting app (its own
  // start screen and requests still running, under a loaded runner) was answered NS_BINDING_ABORTED. Now the picture comes first
  // and the app last, like the other Firefox suites (p2149_b_ui), and the app is probed once its start screen is drawn (a real state)
  await firefox(async ({ev, nav}) => {
    const until = async expr => { for (let i = 0; i < 80; i++) { if (await ev(expr).catch(() => false)) return true; await new Promise(r => setTimeout(r, 250)); } return false; };
    for (const [n, url] of [[1, B + 'static/icon.svg'], [2, B]]) {
      await nav(url);
      if (n === 2) check(await until(`document.readyState === 'complete' && !!document.querySelector('.authscreen')`), 'page 2: the app has drawn its start screen');
      const [now, nd, str, zero, utc, inst, tz] = await ev(probe);
      const node = testNow().getTime();
      check(Math.abs(now - node) < 60000 && Math.abs(nd - node) < 60000, `page ${n}: Firefox's Date.now() / new Date() is the test time (${new Date(now).toISOString()} vs ${new Date(node).toISOString()})`);
      check(Math.abs(Date.parse(str) - node) < 60000, `page ${n}: Date() as text is the test time too: ${str}`);
      check(zero === 0 && utc === 1577836800000 && inst === true, `page ${n}: dates with arguments, Date.UTC and instanceof stay`);
      if (n === 2) console.log(`p2381_b_ffclock_ui: Firefox ${new Date(now).toISOString()} (offset ${Math.round(clockOffset / 1000)} s), time zone ${tz}`);
    }
  });

  console.log(`p2381_b_ffclock_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
