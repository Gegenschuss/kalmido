// kalmido-suite: fresh
// 2.725.0 D (#5163) UI test, own container (start.sh), Firefox with touch at 412 and 600 px (a folded phone). Invented data only.
// The bars of the wiki list and of notes (.ntbar): the search field has its own line, buttons do not overlap or shrink under
// their text, nothing runs over the edge; the phone header's chips (#top) share one height. Shots: P2725D_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2725_d_ntbar_ui', check, shots: 'P2725D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2725D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };

// per bar: overlaps, overflow, buttons whose text is cut, the search field on its own line, the tallest/shortest header chip
const AUDIT = `(() => { const out = {bars: 0, lap: [], over: [], cut: [], shared: [], vw: innerWidth};
  for (const b of document.querySelectorAll('#view .ntbar')) { if (!b.offsetParent) continue; out.bars++;
    const kids = [...b.children].filter(e => e.offsetParent && e.getBoundingClientRect().width > 0), rs = kids.map(e => e.getBoundingClientRect());
    for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) { const a = rs[i], c = rs[j]; if (a.left < c.right - 1 && c.left < a.right - 1 && a.top < c.bottom - 1 && c.top < a.bottom - 1) out.lap.push(i + '/' + j); }
    if (b.scrollWidth > b.clientWidth + 1) out.over.push(b.className + ' ' + b.scrollWidth + '/' + b.clientWidth);
    for (const e of b.querySelectorAll('.btn, .iconbtn')) if (e.offsetParent && e.scrollWidth > e.clientWidth + 1) out.cut.push((e.textContent || e.className).trim().slice(0, 20));
    const s = b.querySelector('.ssearch, .ctsearch'); if (s) { const sr = s.getBoundingClientRect(); out.shared.push(kids.filter(e => e !== s && e.getBoundingClientRect().top < sr.bottom - 1 && e.getBoundingClientRect().bottom > sr.top + 1).length); } }
  return out; })()`;
const CHIPS = `(() => [...document.querySelectorAll('#top .achip, #top .stchip, #top .wschip, #top .tmini, #top .cfpill')].filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().height)))()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'de'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'de', collab_all: true, modules: ['cal', 'comments']});
  const st = await call(CA, 'GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean));
  ['wiki', 'notes'].forEach(x => feats.add(x));
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'de', workspace: 'all', features: [...feats].join(',')});
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    for (const w of [412, 600]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: 800}});
      for (const [name, hash] of [['wiki', '#wiki'], ['notes', '#notes']]) {
        await nav(B + hash);
        check(await ready(ev, `!!document.querySelector('#view .ntbar')`), `${name} ${w}: the bar is up`);
        const a = await ev(AUDIT), t = `${name} ${w}`;
        check(a && a.bars > 0, t + ': bars found ' + JSON.stringify(a));
        check(a && !a.lap.length, t + ': buttons of the bar do not overlap ' + JSON.stringify(a));
        check(a && !a.over.length, t + ': the bar does not overflow ' + JSON.stringify(a));
        check(a && !a.cut.length, t + ': no button text cut off ' + JSON.stringify(a));
        check(a && a.shared.length && a.shared.every(n => n === 0), t + ': the search field has its own line ' + JSON.stringify(a));
        const h = await ev(CHIPS);
        check(!h.length || Math.max(...h) - Math.min(...h) <= 1, t + ': header chips share one height ' + JSON.stringify(h));
        await o.shot(`p2725d-${name}-${w}.png`);
      }
    }
  }, true);
  console.log(`p2725_d_ntbar_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
