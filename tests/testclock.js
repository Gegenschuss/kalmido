// Test clock (2.85.0, #1863): "today" in the app's time zone (Europe/Berlin), not the one of the test process.
// KALMIDO_TEST_NOW (ISO instant, e.g. 2026-10-17T22:30:00Z) replaces the real time.
// 2.149.0 (#2512): with KALMIDO_TEST_NOW_AT (Unix seconds, run_all.sh `now <instant>; fresh`) the clock runs on from there
const now = () => {
  const v = process.env.KALMIDO_TEST_NOW;
  if (!v) return new Date();
  const at = Number(process.env.KALMIDO_TEST_NOW_AT || 0);
  return new Date(new Date(v).getTime() + (at ? Date.now() - at * 1000 : 0));
};
const fmt = new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Berlin', year: 'numeric', month: '2-digit', day: '2-digit'});
const today = () => fmt.format(now());
// the Berlin day n days from today (YYYY-MM-DD); calendar arithmetic on the date, no DST drift
const day = (n = 0) => { const d = new Date(today() + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
// Monday of the Berlin week of today (YYYY-MM-DD)
const weekStart = () => { const d = new Date(today() + 'T12:00:00Z'); return day(-((d.getUTCDay() + 6) % 7)); };
module.exports = {now, today, day, weekStart};
