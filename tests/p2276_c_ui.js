// 2.276.0 B (#3043): the knowledge editor without a Markdown hurdle (Firefox, real layout), computer 1280x800 and tablet 820x1180:
// - the field is written in the normal font (not the monospace one of notes)
// - a formatting bar above the field in ONE row (heading, bold, italic, list, checkbox, link + the insert button)
// - its buttons write the expected Markdown into the saved text, a second click takes it away again, Ctrl+I works,
//   the browser's undo takes back one step; [[links]] and file embeds stay untouched
// - the tablet run edits the private page of a person WITHOUT an organisation (freelancer parity, P4). Screenshots: P2276C_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2276C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2276_c_ui', check, shots: 'P2276C_SHOTS'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const BODY = 'Intro\n[[Other]]\n![pic](/api/files/nodes/999/content)\nAlpha\nBeta\nGamma\nSite\nMake it bold\n';
const WANT = '## Intro\n[[Other]]\n![pic](/api/files/nodes/999/content)\n- Alpha\n- Beta\n- [ ] Gamma\n[Site](https://)\nMake *it* **bold**\n';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call(CA, 'GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki', 'notes'])].join(',');
  await call(CA, 'PATCH', '/api/settings', {look: '{"wkEd":"text"}', tour: 'done', lang: 'en', features: feats});  // 2.350.0 (#3147): these checks drive the plain text editor (#wk-body)
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {look: '{"wkEd":"text"}', tour: 'done', lang: 'en', features: feats});  // 2.350.0 (#3147): these checks drive the plain text editor (#wk-body)
  check(fu.id && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'setup: frida has no organisation');
  const runs = [];
  for (const [who, ck] of [['alice', CA], ['frida', CF]]) {
    const id = (await call(ck, 'POST', '/api/wiki/pages', {space: 'private', path: 'Plan', body: BODY})).id;
    check(id, `setup: ${who}'s private page`); runs.push({who, ck, id});
  }

  for (const [[vw, vh], run] of [[[1280, 800], runs[0]], [[820, 1180], runs[1]]]) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const tag = `${vw} ${run.who}`;
    await nav(B + 'static/icon.svg');
    const lg = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${run.who}', password: 'password123'})}).then(r => r.status)`);
    check(lg === 200, `${tag}: login`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + `#wiki/${run.id}`);
    const until = (expr, n) => require('./boot').until(() => ev(expr).catch(() => null), {timeout: n ? n * 250 : 15000, step: 250});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
    await until(`!!document.querySelector('[data-wk="mode"][data-m="edit"]')`);
    await ev(`(() => { document.querySelector('[data-wk="mode"][data-m="edit"]').click(); return 1; })()`);
    await until(`!!document.querySelector('#wk-body') && !!document.querySelector('.wembar [data-wemf]')`);
    // the normal font once wiki.css is there (lazy)
    const ff = await until(`(() => { const f = getComputedStyle(document.querySelector('#wk-body')).fontFamily; return /mono/i.test(f) ? '' : f; })()`);
    check(ff && !/mono/i.test(ff), `${tag}: the field is in the normal font (${ff})`);
    const bar = await ev(`(() => { const b = document.querySelector('.wkedwrap .wembar'), r = b.getBoundingClientRect(), bs = [...b.querySelectorAll('[data-wemf]')];
      return {keys: bs.map(x => x.dataset.wemf).join(','), labels: bs.every(x => x.getAttribute('aria-label') && x.title), svg: bs.every(x => x.querySelector('svg')),
        h: r.height, ins: !!b.querySelector('[data-wem="ins"]'), sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth}; })()`);
    check(bar.keys === 'h,b,i,ul,cb,ln' && bar.labels && bar.svg && bar.ins, `${tag}: the bar has heading, bold, italic, list, checkbox, link (icons, labels) and the insert button: ${JSON.stringify(bar)}`);
    check(bar.h <= 48 && bar.sw <= bar.cw + 1, `${tag}: the bar is one row, nothing sticks out (${Math.round(bar.h)} px, ${bar.sw}/${bar.cw})`);
    // act: select a piece of the text, press a button (or a key)
    await ev(`(() => { window.__p = (t, a = 0, len) => { const ta = document.querySelector('#wk-body'), i = ta.value.indexOf(t); ta.focus(); ta.setSelectionRange(i + a, i + (len ?? t.length)); return i; };
      window.__b = k => { document.querySelector('.wembar [data-wemf="' + k + '"]').click(); return document.querySelector('#wk-body').value; }; return 1; })()`);
    const v1 = await ev(`(() => { __p('Intro', 2, 2); return __b('h'); })()`);
    check(v1.startsWith('## Intro\n'), `${tag}: heading prefixes the line of the cursor`);
    await ev(`(() => { __p('Alpha\\nBeta'); return __b('ul'); })()`);
    const v2 = await ev(`(() => { __p('Gamma', 1, 1); return __b('cb'); })()`);
    check(v2.includes('\n- Alpha\n- Beta\n- [ ] Gamma\n'), `${tag}: list on two selected lines, checkbox on the cursor's line`);
    const v3 = await ev(`(() => { __b('cb'); return document.querySelector('#wk-body').value; })()`);
    check(v3.includes('\n- Beta\nGamma\n'), `${tag}: a second click takes the checkbox away`);
    await ev(`(() => { __b('cb'); __p('Site'); return __b('ln'); })()`);
    const v4 = await ev(`(() => { const ta = document.querySelector('#wk-body'); return ta.value.slice(ta.selectionStart, ta.selectionEnd); })()`);
    check(v4 === 'https://', `${tag}: link wraps the selection, the address is selected next (${v4})`);
    const v5 = await ev(`(() => { __p('bold'); __b('b'); const a = document.querySelector('#wk-body').value; __b('b'); const b = document.querySelector('#wk-body').value; __b('b'); return [a, b]; })()`);
    check(v5[0].includes('Make it **bold**') && v5[1].includes('Make it bold\n'), `${tag}: bold wraps, a second click unwraps`);
    const v6 = await ev(`(() => { const ta = document.querySelector('#wk-body'); ta.focus(); const i = ta.value.indexOf('Make it') + 5; ta.setSelectionRange(i, i + 2);
      ta.dispatchEvent(new KeyboardEvent('keydown', {key: 'i', ctrlKey: true, bubbles: true, cancelable: true})); return ta.value; })()`);
    check(v6.includes('Make *it* **bold**'), `${tag}: Ctrl+I makes the selection italic`);
    const v7 = await ev(`(() => { const ta = document.querySelector('#wk-body'); ta.focus(); document.execCommand('undo'); const a = ta.value; document.execCommand('redo'); return [a, ta.value]; })()`);
    check(v7[0].includes('Make it **bold**') && v7[1].includes('Make *it* **bold**'), `${tag}: the browser's undo takes back one formatting step (and redo brings it again)`);
    check(v7[1] === WANT, `${tag}: the whole text as expected, [[link]] and embed untouched: ${JSON.stringify(v7[1])}`);
    await shot(`p2276_c_${vw}.png`);
    // saved like typing (no blur needed)
    let saved = '';
    for (let i = 0; i < 40 && saved !== WANT; i++) { await sleep(250); saved = (await call(run.ck, 'GET', `/api/wiki/pages/${run.id}`)).body; }
    check(saved === WANT, `${tag}: the saved text is the formatted Markdown: ${JSON.stringify(saved)}`);
  });
  console.log(`p2276_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
