// 2.665.0 UI test, own container (start.sh), Firefox with "reduce motion" (ff.js sets ui.prefersReducedMotion). Invented data, a person without an organisation.
// kalmido-suite: fresh
// - #5115: under reduce motion only the visual properties keep their .01 ms transition; a size set and measured in the same
//   frame (render.js fitTop, areas.js sbb_fit, any spacer) gives the new value at once. The probe is checked against the former
//   rule (every property a transition) in the same page: there it must read the old value, so the probe really sees the fault
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2665_c_motion_ui', check, shots: 'P2665C_SHOTS'});

// a fresh box: font-size and width set, laid out, changed, read in the same frame (no frame in between)
const PROBE = `(() => {
  const d = document.createElement('div'); d.textContent = 'Messprobe'; d.style.cssText = 'font-size:10px;width:100px;opacity:1';
  document.body.append(d); void d.offsetWidth;
  d.style.fontSize = '20px'; d.style.width = '200px';
  const r = {fs: getComputedStyle(d).fontSize, w: d.offsetWidth, tp: getComputedStyle(d).transitionProperty, td: getComputedStyle(d).transitionDuration};
  d.remove(); return r; })()`;
// the real measuring place of the top bar (render.js fitTop): set h1's min-width, measure it in the same frame
const TOPH1 = `(() => {
  const h = document.querySelector('#top h1'); if (!h) return null;
  const old = h.style.minWidth; void h.offsetWidth; const want = Math.ceil(h.getBoundingClientRect().width) + 37;
  h.style.minWidth = want + 'px'; const got = h.getBoundingClientRect().width; h.style.minWidth = old; void h.offsetWidth;
  return {want, got}; })()`;
const OLD_ON = `(() => { const st = document.createElement('style'); st.id = 'p2665old'; st.textContent = '*,*::before,*::after{transition-property:all!important}'; document.head.append(st); return 1; })()`;
const OLD_OFF = `(() => { document.getElementById('p2665old')?.remove(); return 1; })()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  const call = async (method, url, body) => (await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined})).json().catch(() => ({}));
  await call('PATCH', '/api/settings', {lang: 'de', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Plan'})).id;
  await call('POST', '/api/tasks', {list_id: L, title: 'Linsensuppe mit Brot'});

  await firefox(async ({cmd, ev, nav, ctx, until}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1100, height: 760}});
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#l/' + L);
    check(await until(() => ev(`!!S.booted && !!document.querySelector('#top h1 .ht') && matchMedia('(prefers-reduced-motion: reduce)').matches`)), '#5115: the app is there, the browser asks for reduced motion');

    // the fix: sizes take effect in the same frame, visual properties keep the .01 ms transition
    const p = await ev(PROBE);
    check(p.fs === '20px' && p.w === 200, '#5115: font-size and width set and measured in the same frame give the new value: ' + JSON.stringify(p));
    const props = p.tp.split(',').map(s => s.trim());
    check(props.includes('opacity') && props.includes('transform') && props.includes('background-color'), '#5115: opacity, transform, background keep their transition: ' + p.tp);
    check(!props.some(x => ['all', 'font-size', 'width', 'height', 'max-height', 'padding', 'margin', 'top', 'left', 'min-width'].includes(x)), '#5115: no size or place in the reduced-motion transition: ' + p.tp);
    check(/^1e-05s|^0\.00001s/.test(p.td), '#5115: the visual transition stays .01 ms: ' + p.td);
    // a visual change still ends with transitionend (detail.js and others listen for it)
    const te = await ev(`new Promise(res => { const d = document.createElement('div'); d.style.cssText = 'opacity:1;width:10px;height:10px'; document.body.append(d); void d.offsetWidth;
      const t = setTimeout(() => { d.remove(); res('none'); }, 2000); d.addEventListener('transitionend', e => { clearTimeout(t); d.remove(); res(e.propertyName); }, {once: true}); d.style.opacity = '.5'; })`);
    check(te === 'opacity', '#5115: an opacity change still fires transitionend: ' + te);
    const h = await ev(TOPH1);
    check(h && Math.abs(h.got - h.want) < 1, '#5115: fitTop measuring place: the title min-width counts in the same frame: ' + JSON.stringify(h));
    const drw = await ev(`(() => { const n = document.querySelector('#srail .srbn, #side .srbn'); return n ? getComputedStyle(n).transitionProperty : 'none'; })()`);
    check(!/font-size|\ball\b/.test(drw), '#5115: sbb_fit measuring place: an area name has no font-size transition: ' + drw);

    // the counter-check: with the former rule (every property, .01 ms) the same probe reads the old value - the probe sees the fault
    await ev(OLD_ON);
    const o = await ev(PROBE), oh = await ev(TOPH1);
    await ev(OLD_OFF);
    check(o.fs === '10px' || o.w === 100, '#5115 counter-check: under the former rule the probe reads the old size: ' + JSON.stringify(o));
    check(oh && oh.got < oh.want - 1, '#5115 counter-check: under the former rule fitTop measured the old min-width: ' + JSON.stringify(oh));
    const p2 = await ev(PROBE);
    check(p2.fs === '20px' && p2.w === 200, '#5115: after the counter-check the fix holds again: ' + JSON.stringify(p2));
  });
  console.log(`p2665_c_motion_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL', e); process.exit(1); });
