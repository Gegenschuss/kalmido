// kalmido-suite: fresh
// 2.490.0 A (#4021) UI test (jsdom), own container, German: on Today the block "Termine heute" folds events whose end has
// passed into a quiet line "N vorbei" (tap unfolds them, pale), the running event gets the mark "jetzt", all-day events stay,
// the count in the head is upcoming + running only; all past -> only the line. Events are built relative to now.
const {boot, sleep, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const ck = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url, {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('PATCH', 'api/settings', {lang: 'de', tour: 'done', features: 'cal,events'});
  const W = await call('POST', 'api/evcals', {name: 'Work', color: '#2dd4bf'});
  const w = await boot({user: 'alice', ls: {'tasks.lastKey': '"today"'}}), d = w.document;
  await until(() => d.querySelector('#view'));
  await until(() => w.eval('S.evcals.length > 0 && S.cal.loading === ""'));
  const MIN = 60000;
  const setItems = specs => w.eval(`(() => {
    const t0 = today(), now = Date.now();
    S.cal.items = ${JSON.stringify(specs)}.map((x, i) => ({id: 'x' + i, title: x.t, all_day: !!x.all, own: true, cal: ${W.id}, start: '', end: '',
      s: new Date(now + x.s * 60000), e: new Date(now + x.e * 60000), d0: t0, d1: t0}));
    S.cal.key = t0 + '|' + t0; S.collapsed.delete('cev-past'); S.collapsed.delete('cev-today'); renderView();
  })()`);
  const blk = () => d.querySelector('.cevtoday');
  setItems([{t: 'Past A', s: -180, e: -120}, {t: 'Past B', s: -90, e: -30}, {t: 'Running', s: -30, e: 30}, {t: 'Coming', s: 60, e: 120}, {t: 'Whole day', s: 0, e: 0, all: 1}]);
  await until(() => blk() && blk().textContent.includes('Running'));
  check(blk().querySelector('.ghead .c').textContent.trim() === '3', 'head counts upcoming + running + all-day: ' + blk().querySelector('.ghead .c').textContent);
  check(!blk().textContent.includes('Past A') && !blk().textContent.includes('Past B'), 'past events are gone from the list');
  const pl = blk().querySelector('.cevpastl');
  check(pl && pl.textContent.trim() === '2 vorbei', 'quiet line "2 vorbei": ' + (pl && pl.textContent.trim()));
  const rows = [...blk().querySelectorAll('.cevrow')];
  const run = rows.find(r => r.textContent.includes('Running'));
  check(run && run.querySelector('.cevnow') && run.querySelector('.cevnow').textContent === 'jetzt', 'the running event carries "jetzt"');
  check(rows.filter(r => r.querySelector('.cevnow')).length === 1, 'only the running one is marked');
  check(rows.some(r => r.textContent.includes('Whole day')) && rows.some(r => r.textContent.includes('Coming')), 'all-day and upcoming stay');
  click(w, pl);
  await until(() => blk().querySelectorAll('.cevrow.cevpast').length === 2);
  check(blk().querySelectorAll('.cevrow.cevpast').length === 2 && blk().querySelector('.cevpastl').getAttribute('aria-expanded') === 'true', 'a tap unfolds the two past events (pale)');
  check(blk().querySelector('.ghead .c').textContent.trim() === '3', 'the count is unchanged when unfolded');
  click(w, blk().querySelector('.cevpastl'));
  check(await until(() => !blk().querySelector('.cevrow.cevpast')), 'a second tap folds them again');  // 2.501.0 (#4296): was check(true) after the wait
  // all past: only the line
  setItems([{t: 'Past A', s: -180, e: -120}, {t: 'Past B', s: -90, e: -30}]);
  await until(() => blk() && blk().querySelector('.cevpastl') && !blk().textContent.includes('Running'));
  check(blk().querySelector('.ghead .c').textContent.trim() === '0' && !blk().querySelector('.cevrow') && /2 vorbei/.test(blk().textContent), 'all past: count 0, only the line');
  // one past: singular text
  setItems([{t: 'Past A', s: -180, e: -120}, {t: 'Coming', s: 60, e: 120}]);
  await until(() => blk() && blk().textContent.includes('Coming'));
  check(blk().querySelector('.cevpastl').textContent.trim() === '1 vorbei', '"1 vorbei"');
  // the minute tick redraws only when the content changed: an event that ends now moves into the line
  setItems([{t: 'Ending', s: -60, e: 1}, {t: 'Coming', s: 60, e: 120}]);
  await until(() => blk() && blk().textContent.includes('Ending'));
  check(!blk().querySelector('.cevpastl'), 'before its end the event is listed');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
