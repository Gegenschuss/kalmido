// 2.140.0 C UI test (jsdom), fresh DB, English: the journal history in the review (list newest first, load more, search with the
// match marked, mood filter, statistics, download links, an entry opens its day) (#2133); habits: several reminder times in the
// dialog (add a time, saved sorted), "3 of 5 this week" with segments (#2135).
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, ms = 5000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(80); } return false; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ymd = n => { const d = new Date(); d.setDate(d.getDate() - n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,habits,review,family'});
  for (let n = 0; n < 35; n++) await call('PUT', `/api/life/journal/${ymd(n)}`, {text: `Entry ${n} ${n === 3 ? 'about the Harbour walk' : 'ordinary'}`, mood: 1 + n % 5});
  // habit with a weekly target and ticks on the days of this week so far
  const hid = (await call('POST', '/api/habits', {name: 'Run', per_week: 5, remind_times: ['18:00']})).id;
  const mon = new Date(); mon.setDate(mon.getDate() - ((mon.getDay() + 6) % 7));
  let ticked = 0;
  for (let i = 0; i < 3; i++) { const d = new Date(mon); d.setDate(d.getDate() + i); if (d <= new Date()) { const s = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; await call('POST', `/api/habits/${hid}/log`, {day: s, count: 1}); ticked++; } }

  // ---- journal history
  let w = await boot({user: 'alice', hash: 'review'}), d = w.document;
  await sleep(800);
  check(d.querySelector('[data-act="rv-period"][data-p="hist"]'), 'the review has a History tab');
  click(w, d.querySelector('[data-act="rv-period"][data-p="hist"]'));
  check(await until(() => d.querySelectorAll('.jhrow').length === 30), 'the first page has 30 entries: ' + d.querySelectorAll('.jhrow').length);
  check(/Load more/.test(d.querySelector('#jh-list').textContent), 'a Load more button');
  click(w, d.querySelector('[data-act="rv-hmore"]'));
  check(await until(() => d.querySelectorAll('.jhrow').length === 35), 'more entries load: ' + d.querySelectorAll('.jhrow').length);
  const q = d.querySelector('#jh-q'); q.value = 'harbour'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => d.querySelectorAll('.jhrow').length === 1), 'search finds the one entry');
  check(d.querySelector('.jhtx mark')?.textContent.toLowerCase() === 'harbour', 'the match is marked');
  q.value = 'nothing-like-this'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => /No entries found/.test(d.querySelector('#jh-list').textContent)), 'no hit says so');
  q.value = ''; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => d.querySelectorAll('.jhrow').length === 30), 'cleared search: all again');
  click(w, d.querySelector('[data-act="rv-hmood"][data-v="5"]'));
  check(await until(() => { const r = d.querySelectorAll('.jhrow'); return r.length === 7; }), 'mood filter: 7 entries with mood 5: ' + d.querySelectorAll('.jhrow').length);
  click(w, d.querySelector('[data-act="rv-hmood"][data-v="0"]'));
  await until(() => d.querySelectorAll('.jhrow').length === 30);
  check(await until(() => d.querySelectorAll('.jhbar').length === 5 && d.querySelector('.jhline polyline')), 'statistics: five bars and a line');
  click(w, d.querySelector('[data-act="rv-hdays"][data-n="90"]'));
  check(await until(() => d.querySelector('[data-act="rv-hdays"][data-n="90"].on')), 'statistics: 90 days selectable');
  const links = [...d.querySelectorAll('.jhist a[download]')].map(a => a.getAttribute('href'));
  check(links.length === 2 && links.some(h => /format=md/.test(h)) && links.some(h => /format=csv/.test(h)), 'Markdown + CSV links: ' + links.join(' '));
  click(w, [...d.querySelectorAll('.jhrow')][2]);
  check(await until(() => d.querySelector('#rv-text')?.dataset.day === ymd(2)), 'an entry opens its day for editing');
  check(/Entry 2/.test(d.querySelector('#rv-text').value), 'the text is in the editor');
  w.close();

  // ---- habits
  w = await boot({user: 'alice', hash: 'habits'}); d = w.document;
  await sleep(800);
  const prog = d.querySelector('.hprog');
  check(prog && prog.querySelectorAll('i').length === 5 && prog.querySelectorAll('i.on').length === ticked, `week progress: ${ticked} of 5 segments (${prog && prog.querySelectorAll('i.on').length})`);
  check(new RegExp(`${ticked} of 5 this week`).test(d.querySelector('.hname small').textContent), 'text "n of 5 this week": ' + d.querySelector('.hname small').textContent);
  click(w, d.querySelector('[data-act="habit-open"]')); await sleep(500);
  const times = () => [...d.querySelectorAll('#h-rems input[data-dp]')].map(x => x.value);
  check(JSON.stringify(times()) === '["18:00"]', 'the dialog shows the saved time: ' + JSON.stringify(times()));
  click(w, d.querySelector('[data-m="remadd"]')); await sleep(300);
  check(times().length === 2, 'a time can be added: ' + JSON.stringify(times()));
  w.eval(`dpSet(document.querySelector('#h-rem1'), '07:30')`); await sleep(300);
  click(w, d.querySelector('[data-m="save"]')); await sleep(1200);
  const h = (await call('GET', '/api/state')).habits.find(x => x.id === hid);
  check(h.remind_times === '07:30,18:00' && h.remind_at === '07:30', 'saved sorted, first in remind_at: ' + h.remind_times);
  await call('PATCH', `/api/habits/${hid}`, {remind_times: ['07:30', '09:00', '10:00', '12:00', '15:00', '18:00']});
  w.close();
  w = await boot({user: 'alice', hash: 'habits'}); d = w.document; await sleep(800);
  click(w, d.querySelector('[data-act="habit-open"]')); await sleep(500);
  check(d.querySelectorAll('#h-rems input[data-dp]').length === 6 && !d.querySelector('[data-m="remadd"]'), 'at six times the add button is gone');
  w.close();
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
