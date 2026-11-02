// kalmido-suite: fresh
// 2.368.5 (#2991) tests for the English wording pass. Own container (start.sh). API + Firefox (layout).
// freelancer-matrix: personal -- alice has no organisation
// - a shopping amount typed as text: "1,000" in English is 1000, in German 1 (the server read 1 in every language)
// - the app bar: "Knowledge" stays one word at 1280 px (the fix came with #3880, this keeps it)
// - no German examples or quotation marks in the English source, the manifest says what the server hands out
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const SRC = process.env.KALMIDO_SRC || path.join(__dirname, '..');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p23685_a_ui', check, shots: 'P23685A_SHOTS'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); try { return await r.json(); } catch { return {}; } };
const qty = async (lid, title, text) => { const t = await call('POST', '/api/tasks', {title, list_id: lid, fam: {kind: 'shop', qty: text}}); return (await call('GET', '/api/state')).tasks.find(x => x.id === t.id)?.fam?.qty; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'family'});

  const SH = (await call('POST', '/api/lists', {name: 'Shop', family: 'shopping'})).id;
  check(await qty(SH, 'Flour', '1,000') === 1000, 'English: 1,000 is a thousand');
  check(await qty(SH, 'Milk', '1,5') === 1.5, 'English: 1,5 stays 1.5');
  await call('PATCH', '/api/settings', {lang: 'de'});
  check(await qty(SH, 'Mehl', '1,000') === 1, 'German: 1,000 is one');
  check(await qty(SH, 'Zucker', '1.500') === 1500, 'German: 1.500 is 1500');
  await call('PATCH', '/api/settings', {lang: 'en'});

  const code = f => fs.readFileSync(path.join(SRC, f), 'utf8');
  check(!/„\$\{esc\(q\)\}“/.test(code('static/js/docs.js')), 'the search filter takes its quotation marks from the language');
  check(!/Imagefilm|Beispiel-AG/.test(code('static/js/office.js')), 'the number schemes have no German example in the code');
  const m = JSON.parse(code('static/manifest.json'));
  check(m.description === (await (await fetch(B + 'manifest.json')).json()).description, 'static/manifest.json says what the server hands out');

  if (!process.env.NOFF) await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + '#today');
    const sel = `#srail .srb .srbn`;
    for (let i = 0; i < 60 && !(await ev(`[...document.querySelectorAll('${sel}')].filter(x => x.offsetParent).length > 2`).catch(() => false)); i++) await sleep(200);
    // the widest word of the bar: an extra line of text means the word broke
    const lines = await ev(`(() => {
      const e = document.createElement('span'); e.className = 'srbn'; e.textContent = 'Knowledge';
      const b = [...document.querySelectorAll('#srail .srb')].find(x => x.offsetParent && x.querySelector('.srbn')); b.appendChild(e);
      const h = e.getBoundingClientRect().height, lh = parseFloat(getComputedStyle(e).fontSize) * 1.15; e.remove();
      return Math.round(h / lh);
    })()`);
    check(lines === 1, 'the bar at 1280 px: Knowledge on one line: ' + lines);
    await shot('p23685a-bar.png');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
