// 2.172.0 A (#2683): the edit field of a wiki page and of a note fills the free height (Firefox, real layout):
// desktop 1280x800 and phone 390x844; the footer line stays visible below the field. Screenshots: P2172A_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2172A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2172_a_edit_ui', check, shots: 'P2172A_SHOTS'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki', 'notes'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Plan', body: 'Hello\n'})).id;
  check(PG, 'setup: a page');

  for (const [vw, vh] of [[1280, 800], [390, 844]]) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    const lg = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(lg === 200, `${vw}: login`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + `#wiki/${PG}`);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('[data-wk="mode"][data-m="edit"]')`).catch(() => false)); i++) await sleep(300);
    await ev(`(() => { document.querySelector('[data-wk="mode"][data-m="edit"]').click(); return 1; })()`);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#wk-body')`).catch(() => false)); i++) await sleep(300);
    await sleep(600);
    const r = await ev(`(() => { const t = document.querySelector('#wk-body').getBoundingClientRect(), f = document.querySelector('.ntfoot').getBoundingClientRect(), tb = document.getElementById('tabs');
      const tt = tb && tb.offsetParent !== null ? tb.getBoundingClientRect().top : innerHeight;
      return {h: t.height, top: t.top, free: Math.min(innerHeight, tt) - t.top, fb: f.bottom, ih: innerHeight, w: t.width, vw: document.documentElement.clientWidth, sw: document.documentElement.scrollWidth}; })()`);
    check(r.h >= 0.7 * r.free, `${vw}: field height ${Math.round(r.h)} >= 70% of the free ${Math.round(r.free)}`);
    check(r.fb <= r.ih + 1, `${vw}: the footer line is visible (${Math.round(r.fb)} / ${r.ih})`);
    check(r.sw <= r.vw + 1 && r.w >= 0.6 * r.vw, `${vw}: full width, nothing sticks out (${Math.round(r.w)} / ${r.vw})`);
    await shot(`p2172_a_wiki_${vw}.png`);
  });
  console.log(`p2172_a_edit_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
