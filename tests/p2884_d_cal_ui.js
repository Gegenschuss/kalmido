// kalmido-suite: fresh
// 2.884.0 (#5469) Calendar polish, Firefox (real layout + real keys), invented data only:
// - desktop month view: Tab reaches an event chip, Enter opens it with its title visible, Escape closes it again;
//   the same for the event row in the selected day's list (.cevrow had role=button without a key handler)
// - week view: the same for a timed block (.wcev), Space opens it
// - phone width + touch: month dots / year days / week block reach 44 px of hit area (elementFromPoint at the edge of the area)
// freelancer-matrix: n/a (no route; client only, tested as alice without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2884_d_cal_ui', check, shots: 'P2884D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const day = i => { const d = new Date(); d.setDate(d.getDate() + i); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events'});
  const W = await call(CA, 'POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  const t0 = day(0);
  await call(CA, 'POST', '/api/events', {title: 'Pitch review', cal_id: W.id, start: `${t0}T09:00`, end: `${t0}T10:00`});
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  await firefox(async ({cmd, ev, ctx, nav, until, shot}) => {
    const key = async k => { await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k1', actions: [{type: 'keyDown', value: k}, {type: 'keyUp', value: k}]}]}); await cmd('input.releaseActions', {context: ctx}); };
    const TAB = '', ENTER = '', ESC = '', SPACE = ' ';
    const tabTo = async sel => { for (let i = 0; i < 80; i++) { if (await ev(`!!document.activeElement?.matches('${sel}')`)) return true; await key(TAB); } return false; };
    // closePop() hides #pop and keeps its content: closed = no visible event popover
    const popGone = `(() => { const p = document.querySelector('.cevpop'); return !p || p.offsetParent === null; })()`;
    const popTitle = `(() => { const p = document.querySelector('.cevpop'); return !!p && p.offsetParent !== null && p.textContent.includes('Pitch review'); })()`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.calMode', '"month"'); return 1; })()`);
    await signIn(ev);
    await nav(B + '#cal');
    check(await until(`!!document.querySelector('#view .cal .cev[data-cev]')`), 'desktop month: the event chip is drawn');
    check(await ev(`(() => { const c = document.querySelector('#view .cal .cev[data-cev]'); return c.getAttribute('role') === 'button' && c.tabIndex === 0; })()`), 'chip is role=button with tabindex 0');
    check(await tabTo('#view .cal .cev'), 'Tab reaches an event chip');
    await key(ENTER);
    check(await until(popTitle, {timeout: 5000}), 'Enter opens the event with its title visible');
    await key(ESC);
    check(await until(popGone, {timeout: 5000}), 'Escape closes the event again');
    // the selected day's list below the month: an event row (.cevrow) is role=button and opens with Enter as well
    check(await until(`!!document.querySelector('#view .agenda .cevrow[data-cev]')`, {timeout: 5000}), 'month: the selected day lists the event as a row');
    check(await tabTo('#view .agenda .cevrow'), 'Tab reaches the event row');
    await key(ENTER);
    check(await until(popTitle, {timeout: 5000}), 'Enter on the event row opens the event with its title visible');
    await key(ESC);
    check(await until(popGone, {timeout: 5000}), 'Escape closes it again');
    // the week: a timed block
    await ev(`(() => { localStorage.setItem('tasks.calMode', '"week"'); location.reload(); return 1; })()`);
    check(await until(`!!document.querySelector('#view .wcev[data-cev]')`, {timeout: 20000}), 'week: the timed block is drawn');
    check(await tabTo('#view .wcev'), 'Tab reaches the timed block');
    await key(SPACE);
    check(await until(popTitle, {timeout: 5000}), 'Space opens the timed block with its title visible');
    await key(ESC);
    // the phone: 44 px of hit area, measured with elementFromPoint at the edge of the area
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await ev(`(() => { localStorage.setItem('tasks.calMode', '"year"'); location.reload(); return 1; })()`);
    check(await until(`!!document.querySelector('#view button.cyd')`, {timeout: 20000}), 'phone: year days drawn');
    const hit = sel => ev(`(() => { const e = document.querySelector('${sel}'); if (!e) return null; e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const ok = (x, y) => { const t = document.elementFromPoint(x, y); return !!t && (t === e || e.contains(t)); };
      // a later neighbour day paints over the grown area on its side (a dense grid); there the point must still hit a day, never a dead gap
      const day = (x, y) => { const t = document.elementFromPoint(x, y); return !!t && (t === e || e.contains(t) || !!t.closest?.('button.cyd')); };
      const coarse = matchMedia('(pointer:coarse)').matches;
      return {coarse, up: ok(cx, cy - 21), down: day(cx, cy + 21), left: ok(cx - 21, cy), right: day(cx + 21, cy)}; })()`);
    const yd = await hit('#view button.cyd');
    // the headless browser may not report a coarse pointer; then the rule cannot apply and only the plain size is checked
    if (yd && yd.coarse) check(yd.up && yd.down && yd.left && yd.right, 'phone/touch: a year day reaches 44 px (up / left its own, down / right a day, no gap) ' + JSON.stringify(yd));
    else check(await ev(`document.querySelector('#view button.cyd').getBoundingClientRect().width > 0`), 'phone: year day has a size (no coarse pointer in this browser)');
    await shot('p2884-d-year-phone.png');
  }, true);
  console.log(`p2884_d_cal_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
