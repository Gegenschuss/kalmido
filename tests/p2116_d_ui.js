// 2.116.0 D (#2066) UI test (jsdom), fresh DB: the repeat dialog of the date popover offers "Several times a day" (two times
// to start with, the app's own time pickers, adding / removing a time), the task shows "Daily at 08:00, 20:00" and the server
// keeps the sorted rule; the plain "Daily" stays; a rule with times is kept when the popover is opened again.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, ms = 5000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(80); } return false; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Medication'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Vitamin', list_id: L, due: today(), due_time: '08:00'})).id;
  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  await sleep(600);
  w.__dialogs = 'manual';
  w.eval(`datePop(document.querySelector('#top h1'), ${T})`); await sleep(400);
  const rep = () => d.querySelector('#pop #p-rep');
  check(rep() && [...rep().options].some(o => o.value === '__multi' && /Several times a day/.test(o.textContent)), 'the repeat list offers "Several times a day"');
  rep().value = '__multi'; rep().dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(400);
  const tin = () => [...d.querySelectorAll('#pop .rrtimes input[type=hidden]')].map(x => x.value);
  check(JSON.stringify(tin()) === '["08:00","20:00"]', 'two times to start with: ' + JSON.stringify(tin()));
  check(d.querySelectorAll('#pop .rrtimes .dpbtn').length === 2 && !d.querySelector('#pop .rrtimes input[type=time]'), 'the app\'s own time pickers, no native inputs');
  click(w, d.querySelector('#pop [data-q="rtadd"]')); await sleep(300);
  check(tin().length === 3, 'a third time can be added: ' + JSON.stringify(tin()));
  w.eval(`dpSet(document.querySelector('#p-tm1'), '13:30')`); await sleep(400);
  check(JSON.stringify(tin()) === '["08:00","09:00","13:30"]' || tin().includes('13:30'), 'a time can be changed: ' + JSON.stringify(tin()));
  click(w, d.querySelector('#pop [data-rtdel="1"]')); await sleep(300);
  check(tin().length === 2, 'a time can be removed');
  click(w, d.querySelector('#pop [data-q="done"]')); await sleep(1200);
  const t = (await call('GET', '/api/state')).tasks.find(x => x.id === T);
  check(/^FREQ=DAILY;TIMES=\d{4},\d{4}$/.test(t.repeat) && t.repeat.split('=')[2] === t.repeat.split('=')[2].split(',').sort().join(','), 'the server keeps the sorted rule: ' + t.repeat);
  check(t.due_time === '08:00', 'the task time is the first one: ' + t.due_time);
  const label = w.eval(`repeatLabel(${JSON.stringify(t.repeat)})`);
  check(/^Daily at /.test(label) && /8:00|08:00/.test(label), 'the label names the times: ' + label);
  w.eval(`datePop(document.querySelector('#top h1'), ${T})`); await sleep(400);
  check(rep() && /Daily at/.test(rep().selectedOptions[0]?.textContent || ''), 'opened again: the rule is shown as set');
  rep().value = 'FREQ=DAILY'; rep().dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(300);
  click(w, d.querySelector('#pop [data-q="done"]')); await sleep(1200);
  const t2 = (await call('GET', '/api/state')).tasks.find(x => x.id === T);
  check(t2.repeat === 'FREQ=DAILY', 'plain Daily has no times: ' + t2.repeat);
  w.close();
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
