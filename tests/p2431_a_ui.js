// 2.431.0 A (#3593) UI test. Own container (start.sh). Firefox (layout), mouse.
// The task header (.dtop): at every panel width all icons are whole inside it, nothing scrolls sideways, the date is not cut;
// the words fall away step by step (dtl classes) instead; wide panels keep them.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2431_a_ui', check, shots: 'P2431A_SHOTS'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const lr = await fetch(B + 'api/auth/login', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', password: 'password123'})});
  CK = (lr.headers.getSetCookie?.() || []).map(c => c.split(';')[0]).join('; ');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Home'})).id;
  const T = (await call('POST', '/api/tasks', {list_id: L, title: 'Pay the rent', due: day(2), priority: 3, pinned: true})).id;

  const HEAD = `(() => { const d = document.querySelector('#detail .dtop'); if (!d) return null; const R = d.getBoundingClientRect();
    const vis = e => getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0;
    const kids = [...d.children].filter(vis), dct = d.querySelector('.dchip .dct');
    const words = [...d.querySelectorAll('.dql,.dpw')].filter(vis).length;
    return {w: Math.round(R.width), sw: d.scrollWidth - d.clientWidth, out: kids.filter(e => { const b = e.getBoundingClientRect(); return b.right > R.right + .5 || b.left < R.left - .5; }).length,
      clipped: dct.scrollWidth > dct.clientWidth + 1, words, cls: d.className, n: kids.length}; })()`;
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300);
    await ev(`(() => { openDetail(${T}); return 1; })()`);
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('#detail .dtop')`)); i++) await sleep(200);
    let wide = null;
    for (const px of [600, 500, 420, 360, 600]) {
      // the panel's own width (the chat beside it takes the rest)
      await ev(`(() => { const d = document.getElementById('detail'); d.style.setProperty('width', '${px}px', 'important'); d.style.setProperty('min-width', '0', 'important'); d.style.setProperty('max-width', '${px}px', 'important'); d.style.setProperty('flex', '0 0 ${px}px', 'important'); return 1; })()`);
      let x = null;
      for (let i = 0; i < 20; i++) { await sleep(200); x = await ev(HEAD); if (x && x.sw <= 0 && x.out === 0 && !x.clipped) break; }
      check(x && x.n >= 6, `${px}: icons there (${x && x.n})`);
      check(x && x.sw <= 0 && x.out === 0, `${px}: nothing cut or sideways ${JSON.stringify(x)}`);
      if (px >= 420) check(x && !x.clipped, `${px}: the whole date ${JSON.stringify(x)}`);
      if (px === 600 && !wide) wide = x;
      if (px === 360) check(x.words < wide.words || wide.words === 0, `360: fewer words than at 600 ${JSON.stringify([x, wide])}`);
      if (px === 600 && wide !== x) check(x.words === wide.words, `600 again: the words are back ${JSON.stringify([x, wide])}`);
    }
    check(await ev(`[...document.querySelectorAll('#detail .dtop [data-act="prio"], #detail .dtop [data-act="due-q"]')].every(b => b.title || b.getAttribute('aria-label'))`), 'words stay as tooltips');
  }, false);
  console.log(`p2431_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
