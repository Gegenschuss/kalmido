// kalmido-suite: fresh
// 2.1108.0 (#5965) UI test, Firefox with touch, own container (start.sh), invented data only. An open knowledge page on a phone
// shows its title exactly once and one "…": the head bar (#top) names the page (not the area "Knowledge pages") and has no "…" of
// its own, the page's head keeps the back arrow, the path and the page's "…" (which also carries the head bar's entries, e.g. the
// space's "Export as ZIP"; Delete stays last). A first heading that only repeats the title (an import's "# Title") is hidden in
// the drawn page, a different first heading stays; the text starts right under the page's head. Back in the folder the head bar
// names the area again. A computer keeps the page's own title and "…". P21108A_SHOTS=dir: pictures.
// freelancer-matrix: n/a - nur Oberfläche (no route changed; alice's private space works the same without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21108_a_wkhead_ui', check, shots: 'P21108A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P21108A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const MODS = 'wiki,comments';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const r = await fetch(B + 'api/auth/login', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', password: 'password123'})});
  const CA = (r.headers.get('set-cookie') || '').split(';')[0];
  const call = (method, url, body) => fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}).then(x => x.json());
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: MODS.split(',')});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: MODS + ',collab'});
  const DUP = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Wiki/2D/Color Management', body: '# color  management\n\nFirst line of the text.\n\n## Profiles\n\nMore text.\n'})).id;
  const OWN = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Wiki/2D/Lenses', body: '# Primes and zooms\n\nAbout lenses.\n'})).id;
  check(DUP && OWN, 'two pages made ' + JSON.stringify({DUP, OWN}));

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // what a person sees at the top of the page
  const HEAD = `(() => { const R = e => e.getBoundingClientRect(), vis = e => !!e && !!e.offsetParent && R(e).width > 0 && R(e).height > 0, norm = s => s.toLowerCase().replace(/\\s+/g, '');
    const t = document.querySelector('#top'), h1 = t.querySelector('h1 .ht'), md = document.querySelector('#wk-md'), first = md && [...md.querySelectorAll('p')].find(vis);
    const dots = [...document.querySelectorAll('#top [aria-haspopup="menu"], #view .nthead [aria-haspopup="menu"]')].filter(b => vis(b) && /^More( actions)?$/.test(b.getAttribute('aria-label') || ''));
    const title = document.querySelector('#view .wkpage') && document.querySelector('#view .wkpage').getAttribute('aria-label');
    const seen = [...document.querySelectorAll('#top h1, #view .wkpage h1, #view .wkpage h2, #view .wkpage .wktitle')].filter(vis).filter(e => norm(e.textContent).includes(norm(title || '?'))).length;
    return {top: h1 ? h1.textContent : null, topMore: !!t.querySelector('[data-act="top-more"]:not([hidden])'), dots: dots.length, pmenu: vis(document.querySelector('#view [data-wk="pmenu"]')),
      seen, title, crumbs: (document.querySelector('#view .wkcrumbs') || {}).textContent || '', back: vis(document.querySelector('#view .nthead [data-wk="close"]')),
      dup: !!md && !!md.querySelector('[data-wkdup]') && !vis(md.querySelector('[data-wkdup]')), hs: md ? [...md.querySelectorAll('h1, h2, h3, h4, h5, h6')].filter(vis).map(e => e.textContent) : [], gap: first ? Math.round(R(first).top - R(t).bottom) : null}; })()`;
  const items = async ev => {
    await ev(`(() => { document.querySelector('#view [data-wk="pmenu"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`, 20);
    const t = await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim())`);
    await ev(`(() => { closePop(); return 1; })()`); await ready(ev, `!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`, 20);
    return t || [];
  };

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height: 860}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login in the browser');
    // ---- phone: the page that repeats its title
    await nav(B + `#wiki/${DUP}`);
    check(await ready(ev, `!!S.booted && !!document.querySelector('#wk-md p') && document.querySelector('#top h1 .ht')?.textContent === 'Color Management'`, 80), 'phone: the page is drawn, the head bar names it');
    const a = await ev(HEAD);
    await shot('p21108a-phone-page.png');
    check(a.top === 'Color Management' && !a.topMore && a.dots === 1, 'phone: the head bar shows the page title, not "Knowledge pages", and no "…" of its own ' + JSON.stringify(a));
    check(a.seen === 1, 'phone: the title is visible exactly once ' + JSON.stringify(a));
    check(a.dup && a.hs.length === 1 && a.hs[0] === 'Profiles', 'phone: the repeated "# color  management" is hidden, the next heading stays ' + JSON.stringify(a));
    check(a.pmenu && a.back && /Wiki/.test(a.crumbs) && /2D/.test(a.crumbs) && !/Color Management/.test(a.crumbs), 'phone: the page head has back, the path and one "…" ' + JSON.stringify(a));
    check(a.gap !== null && a.gap < 90, 'phone: the text starts right under the page head ' + JSON.stringify(a));
    const it = await items(ev);
    check(it.includes('Rename…') && it.includes('Export as ZIP') && it[it.length - 1] === 'Delete', 'phone: the one "…" holds the page\'s and the head bar\'s entries, Delete last ' + JSON.stringify(it));
    check(await ev(`document.querySelector('#wk-md').textContent.includes('First line of the text.')`) && (await call('GET', `/api/wiki/pages/${DUP}`)).body.startsWith('# color  management'), 'phone: the text keeps its heading (only the view hides it)');
    // ---- a first heading that differs stays
    await nav(B + `#wiki/${OWN}`);
    check(await ready(ev, `document.querySelector('#top h1 .ht')?.textContent === 'Lenses' && !!document.querySelector('#wk-md p')`, 60), 'phone: the second page is drawn');
    const b = await ev(HEAD);
    check(!b.dup && b.hs.includes('Primes and zooms') && b.top === 'Lenses', 'phone: a different first heading stays visible ' + JSON.stringify(b));
    // ---- back: the folder names the area again
    await ev(`(() => { document.querySelector('#view .nthead [data-wk="close"]').click(); return 1; })()`);
    check(await ready(ev, `!S.route.wid && document.querySelector('#top h1 .ht')?.textContent === 'Knowledge pages'`, 40), 'phone: back in the list the head bar names the area again');
    await shot('p21108a-phone-back.png');
    // ---- computer: the page keeps its title and its "…"
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg'); await nav(B + `#wiki/${DUP}`);
    check(await ready(ev, `!!S.booted && !!document.querySelector('#view .wktitle h2') && !!document.querySelector('#view [data-wk="pmenu"]')`, 80), 'computer: the page shows its title and its "…"');
    const c = await ev(`(() => { const h = document.querySelector('#view .wktitle h2'), t = document.querySelector('#top h1 .ht'); return {h2: h.textContent, top: t ? t.textContent : null}; })()`);
    check(/Color Management/.test(c.h2) && c.top !== 'Color Management', 'computer: the title stays in the page head ' + JSON.stringify(c));
    await shot('p21108a-desktop.png');
  }, true);

  console.log(`p21108_a_wkhead_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
