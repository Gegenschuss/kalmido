// kalmido-suite:
// 2.488.0 A UI test, own container (start.sh), Firefox. Invented data only.
// - #3988: desktop head bar: a Back arrow (greyed out at the start, active after a change of view, click = history.back(),
//   greyed out again at the first view); Alt+Left goes back; Alt+Left inside an input does not; the phone view has no arrow
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2488_back_arrow_ui', check, shots: 'P2488A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2488A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal'});
  const lid = (await call('POST', '/api/lists', {name: 'Project one'})).id;
  const lid2 = (await call('POST', '/api/lists', {name: 'Project two'})).id;

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1200, height: 800}});
    await nav(B + '#today');
    const btn = `document.querySelector('#top [data-act="nav-back"]')`;
    const route = k => ready(ev, `S.route.key === '${k}' && !!${btn}`);
    const off = () => ev(`${btn}.disabled`);
    const key = (init) => ev(`(() => { const e = new KeyboardEvent('keydown', {key: 'ArrowLeft', altKey: true, bubbles: true, cancelable: true}); (${init}).dispatchEvent(e); return e.defaultPrevented; })()`);
    check(await route('today'), 'the arrow is in the head bar');
    check(await off() === true, 'greyed out at the start');
    check(await ev(`getComputedStyle(${btn}).display !== 'none' && ${btn}.getBoundingClientRect().left < document.querySelector('#top h1').getBoundingClientRect().left`), 'visible, left of the title');
    check(/Back/.test(await ev(`${btn}.title`)) && /Alt|⌘/.test(await ev(`${btn}.title`)), 'tooltip with the shortcut: ' + await ev(`${btn}.title`));

    // a change of view
    await ev(`location.hash = '#l/${lid}'`);
    check(await route(`l:${lid}`), 'the project opens');
    check(await ready(ev, `${btn}.disabled === false`, 12), 'active after a change of view');
    await ev(`${btn}.click()`);
    check(await route('today'), 'a click goes back');
    check(await ready(ev, `${btn}.disabled === true`, 12), 'greyed out again at the first view');
    await ev(`${btn}.click()`);  // disabled: nothing
    await sleep(300);
    check(await ev(`location.hash`) === '#today', 'greyed out arrow does nothing');

    // Alt+Left
    await ev(`location.hash = '#l/${lid}'`);
    await route(`l:${lid}`);
    check(await key('document.body') === true, 'Alt+Left is taken over (no second Back from the browser)');
    check(await route('today'), 'Alt+Left goes back');
    check(await ready(ev, `${btn}.disabled === true`, 12), 'greyed out after Alt+Left');
    check(await key('document.body') === true && await ev(`location.hash`) === '#today', 'Alt+Left at the start stays in Kalmido');

    // mouse Back button
    await ev(`location.hash = '#l/${lid}'`);
    await route(`l:${lid}`);
    await ev(`document.body.dispatchEvent(new MouseEvent('mouseup', {button: 3, bubbles: true, cancelable: true}))`);
    check(await route('today'), 'the mouse Back button goes back');

    // inside an input: not taken over
    await ev(`location.hash = '#l/${lid}'`);
    await route(`l:${lid}`);
    await ev(`(() => { const i = document.createElement('input'); i.id = 'bn-in'; document.body.appendChild(i); i.focus(); })()`);
    check(await key(`document.getElementById('bn-in')`) === false, 'Alt+Left in an input is left alone');
    await sleep(300);
    check(await ev(`location.hash`) === '#l/' + lid, 'no step back from an input');
    await ev(`document.getElementById('bn-in').remove()`);

    // 2.488.0 (#3988, self-review): history.length stops at 50 in Firefox / WebKit - a new view must still count as a step
    // (before, every view after the 50th looked like a step back and the arrow greyed out)
    await nav(B + '#today');
    await route('today');
    await ev(`Object.defineProperty(history, 'length', {configurable: true, get: () => 50})`);
    await ev(`location.hash = '#l/${lid}'`);
    await route(`l:${lid}`);
    await ev(`location.hash = '#l/${lid2}'`);
    check(await route(`l:${lid2}`), 'a third view opens');
    check(await ready(ev, `${btn}.disabled === false`, 12), 'active with a full history (length frozen at 50)');
    await ev(`history.back()`);
    check(await route(`l:${lid}`) && await ready(ev, `${btn}.disabled === false`, 12), 'one step back: still active');
    await ev(`history.back()`);
    check(await route('today') && await ready(ev, `${btn}.disabled === true`, 12), 'two steps back: greyed out at the first view');
    // a pushState to a new hash (the note view does that) is a new view
    await ev(`history.pushState(null, '', '#l/${lid}')`);
    check(await ready(ev, `${btn}.disabled === false`, 12), 'pushState to a new hash makes the arrow active');
    await ev(`history.back()`);
    check(await ready(ev, `${btn}.disabled === true`, 12), 'and Back from it greys it out again');
    await ev(`delete history.length`);

    // the phone view: no arrow
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#today');
    await ready(ev, `!!S.booted && !!document.querySelector('#top .menu')`);
    check(await ev(`!${btn}`), 'the phone view has no arrow');
  }, false);

  console.log(`p2488_back_arrow_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
