// D3 UI test (jsdom), fresh DB: touch tablets (Galaxy Fold unfolded, iPad) at 1000 x 800 with hover:none. The "+"
// button shows there like on a phone (the stylesheet rule for >= 900 px without a mouse, bottom right, moved left of
// an open detail pane), respects the views without it and multi-select, and opens the quick-add sheet (a centred
// bottom sheet there). jsdom applies no CSS: the rule is checked in the stylesheet, the behaviour in the app.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  const call = async (method, url, body) => (await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined})).json();
  const T = (await call('POST', '/api/tasks', {title: 'Water plants'})).id;
  const css = await (await fetch(B + 'static/app.css')).text();
  const m = css.match(/@media \(min-width:900px\) and \(hover:none\),\(min-width:900px\) and \(pointer:coarse\)\{([\s\S]*?)\n\}/);
  check(m && /#fab\{display:grid;[^}]*position:fixed;right:1\.25rem;bottom:calc\(var\(--safe-b\) \+ 1\.25rem\)/.test(m[1]), 'stylesheet: the "+" button on touch screens >= 900 px, bottom right with the safe area, no tab bar offset');
  check(m && /#fab\.gone\{display:none\}/.test(m[1]) && /#app\.detail-open #fab\{right:calc\((?:var\(--detW,25\.5rem\)|25\.5rem) \+ 1\.25rem\)\}/.test(m[1]), 'stylesheet: hidden where it does not belong, left of the open detail pane');
  check(m && /\.qadd\.sheet\{[^}]*bottom:0;left:50%;transform:translateX\(-50%\);width:min\(40rem,100vw\)/.test(m[1]), 'stylesheet: quick add as a centred bottom sheet, at most 40rem wide');

  const w = await boot({user: 'alice', hash: 'today', media: {'(hover: none)': true, '(pointer: coarse)': true}}); const d = w.document;
  w.innerWidth = 1000; w.innerHeight = 800;
  const fab = d.querySelector('#fab');
  check(!w.eval('isMobile()') && w.eval('isTouch()'), 'tablet: not the phone layout, but touch');
  // 2.13.0 (#453): where the list has its docked "Add task" bar, a tablet shows only the bar (no second "+")
  check(fab && fab.classList.contains('gone') && fab.getAttribute('aria-label') === 'New task' && d.querySelector('#view .qdock'), 'Today: the add bar only, no "+" button next to it');
  w.eval('openQuickSheet()'); await sleep(100);
  check(d.querySelector('.qadd.sheet #qsheet'), 'tap: the quick-add sheet opens');
  const inp = d.querySelector('#qsheet'); inp.value = 'Call Anna tomorrow';
  d.querySelector('[data-act="qsheet-send"]').click(); await sleep(600);
  check((await call('GET', '/api/state')).tasks.some(t => t.title === 'Call Anna'), 'the task is added');
  w.location.hash = 'habits'; await sleep(400);
  check(fab.classList.contains('gone'), 'habits (no tasks): no "+" button');
  w.location.hash = 'today'; await sleep(400);
  w.eval('S.multiMode = true; renderMultiBar()'); await sleep(50);
  check(fab.classList.contains('gone'), 'multi-select: no "+" button');
  w.eval('S.multiMode = false; renderMultiBar(); render()');
  w.eval(`openDetail(${T})`); await sleep(300);
  check(d.querySelector('#app.detail-open') && fab.classList.contains('gone'), 'detail open: still only the bar');
  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
