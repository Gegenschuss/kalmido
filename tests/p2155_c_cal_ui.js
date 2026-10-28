// 2.155.0 part C UI test (jsdom), fresh DB, English: an own repeat rule in the event editor (#2075): "every 2nd Tuesday" and
// Mon + Wed + Fri are saved as the right RRULE, a saved rule opens the editor pre-filled, cancel keeps the old choice;
// the calendar's year view (#2078): twelve months, a day with an event is tinted, a tap on a day opens the day view, a tap on
// a month name the month view, the arrows turn the year, the chosen mode is remembered.
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events'});
  const W = await call('POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  const t0 = day(0);
  await call('POST', '/api/events', {title: 'Standup', cal_id: W.id, start: `${t0}T09:00`, end: `${t0}T09:15`});

  // ---- own repeat rules
  let w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}), d = w.document;
  await until(() => d.querySelector('#view [data-act="ev-new"]'));
  const newEvent = async title => {
    click(w, d.querySelector('#view [data-act="ev-new"]'));
    await until(() => d.querySelector('.modal.evmodal'));
    const md = d.querySelector('.modal.evmodal');
    md.querySelector('#ev-title').value = title;
    return md;
  };
  const openCustom = async md => {
    change(w, md.querySelector('#ev-rep'), '__custom');
    return until(() => d.querySelector('.modal.crrmodal'));
  };
  const saved = async title => until(async () => (await call('GET', `/api/events?from=${day(-1)}&to=${day(60)}`)).items.find(x => x.title === title));
  let md = await newEvent('Club night');
  check([...md.querySelectorAll('#ev-rep option')].some(o => o.value === '__custom' && /Custom/.test(o.textContent)), 'the Repeat list has "Custom…"');
  let cm = await openCustom(md);
  check(cm && cm.querySelector('#crr-f').value === 'WEEKLY' && cm.querySelectorAll('[data-crrwd].on').length === 1, 'the dialog opens with weekly and one weekday');
  change(w, cm.querySelector('#crr-f'), 'MONTHLY');
  cm = d.querySelector('.modal.crrmodal');
  check(cm.querySelector('#crr-pos') && cm.querySelector('#crr-wd') && cm.querySelector('#crr-md'), 'monthly: day of the month or n-th weekday');
  click(w, cm.querySelector('input[name="crr-m"][value="nth"]'));
  change(w, cm.querySelector('#crr-pos'), '2'); change(w, cm.querySelector('#crr-wd'), 'TU');
  check(/second Tuesday/.test(cm.querySelector('#crr-prev').textContent), 'the preview says it in words: ' + cm.querySelector('#crr-prev').textContent);
  click(w, cm.querySelector('[data-crr="ok"]'));
  await until(() => !d.querySelector('.modal.crrmodal'));
  md = d.querySelector('.modal.evmodal');
  await until(() => md.style.display !== 'none');
  check(md.querySelector('#ev-rep').value === 'custom' && /second Tuesday/.test(md.querySelector('#ev-rep').selectedOptions[0].textContent), 'the list shows the own rule');
  click(w, md.querySelector('[data-evm="save"]'));
  let ev = await saved('Club night');
  let full = ev && await call('GET', `/api/events/${ev.eid}`);
  check(full && /^FREQ=MONTHLY;BYDAY=2TU$/.test(full.rrule), 'saved: every 2nd Tuesday ' + (full && full.rrule));
  await until(() => !d.querySelector('.modal.evmodal'));

  md = await newEvent('Training');
  cm = await openCustom(md);
  for (const x of ['MO', 'WE', 'FR']) if (!cm.querySelector(`[data-crrwd="${x}"].on`)) click(w, d.querySelector(`.modal.crrmodal [data-crrwd="${x}"]`));
  for (const b of [...d.querySelectorAll('.modal.crrmodal [data-crrwd].on')]) if (!['MO', 'WE', 'FR'].includes(b.dataset.crrwd)) click(w, b);
  cm = d.querySelector('.modal.crrmodal');
  check([...cm.querySelectorAll('[data-crrwd].on')].map(b => b.dataset.crrwd).join() === 'MO,WE,FR', 'three weekdays selected');
  click(w, cm.querySelector('[data-crr="ok"]'));
  await until(() => !d.querySelector('.modal.crrmodal'));
  md = d.querySelector('.modal.evmodal');
  change(w, md.querySelector('#ev-repend'), 'count'); md.querySelector('#ev-count').value = '6';
  click(w, md.querySelector('[data-evm="save"]'));
  ev = await saved('Training');
  full = ev && await call('GET', `/api/events/${ev.eid}`);
  check(full && /^FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=6$/.test(full.rrule), 'saved: Mon + Wed + Fri, 6 times ' + (full && full.rrule));
  await until(() => !d.querySelector('.modal.evmodal'));

  // cancel keeps the old choice; a saved own rule opens the dialog pre-filled
  w.eval(`evEditor({ev: ${JSON.stringify(full)}})`);
  await until(() => d.querySelector('.modal.evmodal'));
  md = d.querySelector('.modal.evmodal');
  check(md.querySelector('#ev-rep').value === 'custom' && /Mon, Wed, Fri/.test(md.querySelector('#ev-rep').selectedOptions[0].textContent), 'reopened: the own rule is shown ' + md.querySelector('#ev-rep').selectedOptions[0].textContent);
  click(w, md.querySelector('[data-crredit]'));
  cm = await until(() => d.querySelector('.modal.crrmodal'));
  check(cm.querySelector('#crr-f').value === 'WEEKLY' && [...cm.querySelectorAll('[data-crrwd].on')].map(b => b.dataset.crrwd).join() === 'MO,WE,FR', 'reopened: the dialog is pre-filled');
  click(w, cm.querySelector('[data-crr="cancel"]'));
  await until(() => !d.querySelector('.modal.crrmodal'));
  change(w, d.querySelector('.modal.evmodal #ev-rep'), '__custom');
  cm = await until(() => d.querySelector('.modal.crrmodal'));
  click(w, cm.querySelector('[data-crr="cancel"]'));
  await until(() => !d.querySelector('.modal.crrmodal'));
  check(d.querySelector('.modal.evmodal #ev-rep').value === 'custom', 'cancel keeps the old choice');
  click(w, d.querySelector('.modal.evmodal [data-evm="close"]'));
  w.close();

  // ---- the year view
  w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}); d = w.document;
  await until(() => d.querySelector('#view .calbar [data-k="year"]'));
  click(w, d.querySelector('#view .calbar [data-k="year"]'));
  await until(() => d.querySelector('#view #cyear'));
  const y = +t0.slice(0, 4);
  check(d.querySelectorAll('#cyear .cymon').length === 12, 'year view: twelve months');
  check(new RegExp(String(y)).test(d.querySelector('#view .calbar h2').textContent) && d.querySelector('#view .calbar [data-k="year"].on'), 'the title is the year, the mode is marked');
  check(await until(() => d.querySelector(`#cyear [data-cyd="${t0}"]`)?.className.includes('lv')), 'a day with an event is tinted');
  check(d.querySelector(`#cyear [data-cyd="${t0}"]`)?.classList.contains('today'), 'today is marked');
  check(d.querySelectorAll('#cyear [data-cyd]').length >= 365, 'every day of the year is a button');
  check(JSON.parse(w.localStorage.getItem('tasks.calMode') || '""') === 'year' || /year/.test(w.localStorage.getItem('tasks.calMode') || ''), 'the mode is remembered');
  click(w, d.querySelector('#view [data-act="cal-next"]'));
  await until(() => new RegExp(String(y + 1)).test(d.querySelector('#view .calbar h2').textContent));
  check(d.querySelectorAll('#cyear .cymon').length === 12, 'next: the following year');
  click(w, d.querySelector('#view [data-act="cal-today"]'));
  await until(() => new RegExp(String(y)).test(d.querySelector('#view .calbar h2').textContent));
  click(w, d.querySelector(`#cyear [data-cyd="${t0}"]`));
  check(await until(() => d.querySelector('#view .week.oneday')) && w.eval('S.calSel') === t0, 'a tap on a day opens the day view');
  click(w, d.querySelector('#view .calbar [data-k="year"]'));
  await until(() => d.querySelector('#view #cyear'));
  click(w, d.querySelector(`#cyear [data-cym="${t0.slice(0, 7)}"]`));
  check(await until(() => d.querySelector('#view .cal .cell')) && w.eval('S.calMonth') === t0.slice(0, 7), 'a tap on a month name opens the month view');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
