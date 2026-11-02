// kalmido-suite: fresh
// 2.459.0 (#3883): saving a knowledge page never moves the view (Firefox, phone window 412x640 with a touch screen, the
// keyboard taken as a lower window). frida, a person WITHOUT an organisation. Long page, a tall block in the middle:
// - live preview: typing in the middle of the tall block and the autosave leave #view.scrollTop, the field and the cursor
//   as they are (wklv_fit set the field to height auto: the page collapsed, the view landed at its end)
// - wklv_fit keeps the page's height while it measures (Chrome clamps #view at once, Firefox only after the script: seen here
//   in the height at the moment of the measurement)
// - the file answers draw only what changed (wklv_redraw replaced every drawn block, its pictures lost their height)
// - plain text editor: the same; ntbFit (run by the "Saved" hint) does not grow the field by what is scrolled away
// freelancer-matrix: wiki
// Invented texts only. Screenshots: P2459A_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login, until: waitFor} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2459A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2459_a_wikisave_ui', check, shots: 'P2459A_SHOTS'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const BODY = [...Array.from({length: 12}, (_, i) => `Before ${i}\n`), Array.from({length: 90}, (_, i) => `Long line ${i}`).join('\n'), '', 'After one', '', 'After two'].join('\n');
const STATE = `(() => { const v = document.querySelector('#view'), t = document.activeElement; return {top: Math.round(v.scrollTop), left: Math.round(v.scrollHeight - v.clientHeight - v.scrollTop), id: t?.id, s: t?.selectionStart, e: t?.selectionEnd, fh: Math.round(t?.getBoundingClientRect().height || 0), fy: Math.round(t?.getBoundingClientRect().top || 0), ts: Math.round(t?.scrollTop || 0)}; })()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CK = await login('frida');
  await call(CK, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  check(((await call(CK, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  const id = (await call(CK, 'POST', '/api/wiki/pages', {space: 'private', path: 'Long', body: BODY})).id;
  check(id, 'setup: the long page');

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const until = expr => waitFor(() => ev(expr).catch(() => null), {timeout: 15000, step: 150});
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const type = s => act([{type: 'key', id: 'k', actions: [...s].flatMap(c => [{type: 'keyDown', value: c}, {type: 'keyUp', value: c}])}]);
    const size = height => cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height}});
    const body = () => call(CK, 'GET', `/api/wiki/pages/${id}`).then(p => p.body || '');
    const saved = want => waitFor(async () => (await body()).includes(want), {timeout: 15000, step: 200});
    const same = (a, b, L, n) => {
      check(Math.abs(a.top - b.top) <= 2, `${L}: the view stays where it is (${a.top} -> ${b.top}, ${b.left} px left to the end)`);
      check(b.id === a.id && b.s === a.s + n && b.e === a.e + n, `${L}: field and cursor stay: ${JSON.stringify([a, b])}`);
      check(Math.abs(a.fh - b.fh) <= 2 && Math.abs(a.fy - b.fy) <= 2 && Math.abs(a.ts - b.ts) <= 2, `${L}: the field neither moves nor changes its height: ${JSON.stringify([a, b])}`);
    };
    // types a word at the cursor and waits for the save and for its hint to come and go
    const save = async (word, L) => {
      await type(' ');  // the first key: the browser's own reveal of the cursor (#view's scroll padding) is not ours
      await sleep(150);
      const a = await ev(STATE);
      await type(word);
      check(await saved(word), `${L}: autosaved`);
      check(await until(`document.querySelector('#wk-saved')?.textContent === 'Saved'`), `${L}: the hint shows`);
      await until(`document.querySelector('#wk-saved')?.textContent === ''`);
      return {a, b: await ev(STATE)};
    };

    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await size(640);
    await nav(B + `#wiki/${id}`);
    await until(`!!document.querySelector('[data-wk="mode"][data-m="edit"]')`);
    await ev(`(() => { document.querySelector('[data-wk="mode"][data-m="edit"]').click(); return 1; })()`);
    await until(`[...document.querySelectorAll('#wk-live .wklb')].some(x => x.textContent.includes('Long line 45'))`);

    // the file answers: an unchanged block keeps its nodes (its pictures keep their height)
    const redraw = await ev(`(() => { const b = document.querySelector('#wk-live .wklb'), c = b.firstElementChild; wklv_redraw(); return b.firstElementChild === c; })()`);
    check(redraw, 'live: the answers leave an unchanged block as it is');

    // a real click into the middle of the tall block, the keyboard comes, the cursor in the visible part
    const c = await ev(`(() => { const e = [...document.querySelectorAll('#wk-live .wklb')].find(x => x.textContent.includes('Long line 45')); e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); return {x: Math.round(r.left + 30), y: Math.round(r.top + r.height / 2)}; })()`);
    await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: c.x, y: c.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]);
    check(await until(`document.activeElement?.id === 'wk-blk' && document.activeElement.value.includes('Long line 89')`), 'live: the tall block is open');
    await size(380);
    const put = `(() => { const t = document.querySelector('#wk-blk'), v = document.querySelector('#view'), at = t.value.indexOf('Long line 45'); t.setSelectionRange(at, at); const r = t.getBoundingClientRect(); v.scrollTop += r.top + r.height * at / t.value.length - 130; return 1; })()`;
    await ev(put); await sleep(100);
    const fit = await ev(`(() => { const t = document.querySelector('#wk-blk'), v = document.querySelector('#view'), g = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollHeight').get, was = v.scrollHeight; let at = 0;
      Object.defineProperty(t, 'scrollHeight', {configurable: true, get() { at = v.scrollHeight; return g.call(t); }}); wklv_fit(t); delete t.scrollHeight; return {was, at}; })()`);
    check(Math.abs(fit.was - fit.at) <= 2, 'live: the page keeps its height while the field is measured ' + JSON.stringify(fit));
    const live = await save('Zed', 'live');
    check(live.b.left > 300, `live: not at the end of the page (${live.b.left} px left)`);
    same(live.a, live.b, 'live', 3);
    await shot('p2459a-live.png');

    // the plain text editor, scrolled a little (the keyboard leaves little room), the cursor in the part of the field in view
    await ev(`(() => { document.querySelector('.wembar [data-wem="src"]').click(); return 1; })()`);
    check(await until(`!!document.querySelector('#wk-body') && !document.querySelector('#wk-live')`), 'text: the plain text field');
    await sleep(100);  // ntbFit after the redraw
    await ev(`(() => { const t = document.querySelector('#wk-body'), v = document.querySelector('#view'), at = t.value.indexOf('Long line 45'); t.focus({preventScroll: true}); t.setSelectionRange(at, at); v.scrollTop = 120; return v.scrollTop; })()`);
    await sleep(100);
    const text = await save('Yon', 'text');
    check(text.a.top > 50, `text: the view is scrolled (${text.a.top})`);
    same(text.a, text.b, 'text', 3);
    await shot('p2459a-text.png');
    await ev(`(() => { document.querySelector('.wembar [data-wem="src"]').click(); return 1; })()`);  // the account setting back
    await until(`!!document.querySelector('#wk-live')`);
  }, true);
  console.log(`p2459_a_wikisave_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
