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
// 2.180.0 B (#2693): 00:00 of today in Berlin as a Date - time entries at "now - N h" start no earlier than this (an entry over
// the Berlin midnight is one row per day in the export and lies in yesterday / last week / last month)
const dayStart = () => {
  const g = Date.parse(today() + 'T00:00:00Z'), p = {};
  new Intl.DateTimeFormat('en-US', {timeZone: 'Europe/Berlin', hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit'}).formatToParts(g).forEach(x => { p[x.type] = x.value; });
  return new Date(g - (Date.UTC(+p.year, p.month - 1, +p.day, +p.hour, +p.minute) - g));
};
module.exports = {now, today, day, weekStart, dayStart};
