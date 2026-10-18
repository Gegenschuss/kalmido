// 2.98.0 part C UI tests, own container (start.sh), Firefox. Invented people and companies only.
// #2180 the office rail (variant A): on a computer a second column left of the page with the groups Sell, Money,
// Administration as small caps headings and their points below each other (15 rem at 1280 px, 12 rem at 1024 px, the
// page still wide enough), the active point with aria-current, up / down / Home / End inside the rail, the page's own
// heading .ofpt, the path on a detail page; Settings has the tabs General | Templates (services, text blocks, their old
// routes lead there); the small caps readable in the light theme (4.5:1). Phone 402 px: the start page lists the groups in
// one column, a sub page has the way back "< Office · group" first and the group's points as ONE row of tabs (no wrap,
// the active one in sight, left / right). A person without an organisation (her own admin, P4) is the main person here.
// P298C_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p298_c_ui', check, shots: 'P298C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P298C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const FEAT = 'cal,comments,collab,contacts,office,clients,sheets';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CC = await login('carol');
  for (const ck of [CA, CC]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CC, 'GET', '/api/state')).me.workspaces || []).length, 'P4: carol has no organisation');
  const os = await call(CC, 'GET', '/api/office/settings');
  check(os.http === 200 && os.role === 'admin' && os.personal, 'P4: carol is the admin of her own office');
  const cl = await call(CC, 'POST', '/api/clients', {name: 'Example Ltd'});
  check(cl.id > 0, 'a client of carol');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const click = (ev, sel) => ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return 0; b.click(); return 1; })()`);
  const key = (ev, k) => ev(`(() => { const a = document.activeElement; a.dispatchEvent(new KeyboardEvent('keydown', {key: '${k}', bubbles: true, cancelable: true})); return document.activeElement?.dataset?.ofm || ''; })()`);
  const noSide = `document.documentElement.scrollWidth <= window.innerWidth + 1`;
  const theme = (ev, t) => ev(`(() => { localStorage.setItem('tasks.theme', '"${t}"'); return 1; })()`);
  // the contrast of the small caps against the page (WCAG relative luminance)
  const contrast = `(() => { const rgb = s => (s.match(/[\\d.]+/g) || []).slice(0, 3).map(Number); const lum = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); return .2126 * r + .7152 * g + .0722 * b; };
    const h = document.querySelector('#view .ofrh'); let el = h, bg = 'rgba(0, 0, 0, 0)'; while (el && /rgba\\(0, 0, 0, 0\\)|transparent/.test(bg)) { bg = getComputedStyle(el).backgroundColor; el = el.parentElement; }
    if (/rgba\\(0, 0, 0, 0\\)|transparent/.test(bg)) bg = getComputedStyle(document.body).backgroundColor;
    const a = lum(rgb(getComputedStyle(h).color)), b = lum(rgb(bg)); return Math.round((Math.max(a, b) + .05) / (Math.min(a, b) + .05) * 100) / 100; })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`); await theme(ev, 'light');
    check(await signIn(ev, 'carol') === 200, 'carol signs in');
    // ================= #2180 computer 1280
    await nav(B + '#office/offers');
    check(await ready(ev, `!!document.querySelector('#view .ofwrap > .ofrail') && typeof OFC === 'object' && !!OFC.info`, 80), '#2180: the rail left of the page');
    const pts = await ev(`[...document.querySelectorAll('#view .ofrail .ofrg')].map(g => g.dataset.ofmg + ':' + [...g.querySelectorAll('.ofri')].map(b => b.dataset.ofm).join('+')).join(' ')`);
    check(pts === 'sell:pipeline+offers+clients+contacts+gendocs+contracts money:cashflow+kpi+bank+books+subs+travel admin:equipment+agreements+settings', '#2180: groups and points in order (P4: all of them) ' + pts);
    check(await ev(`[...document.querySelectorAll('#view .ofrail .ofrh')].map(h => h.textContent.trim()).join('|') === 'Sell|Money|Administration' && !document.querySelector('#view .ofrail .ofrh svg')`), '#2180: three small caps headings without icons');
    check(await ev(`(() => { const n = document.querySelector('#view .ofrail'); return n.tagName === 'NAV' && n.getAttribute('aria-label') === 'Office' && [...n.querySelectorAll('.ofri')].every(b => b.tagName === 'BUTTON' && !b.getAttribute('role')); })()`), '#2180: a nav "Office" of buttons, no tabs');
    check(await ev(`(() => { const on = [...document.querySelectorAll('#view .ofrail [aria-current="page"]')]; return on.length === 1 && on[0].dataset.ofm === 'offers' && on[0].classList.contains('on'); })()`), '#2180: the active point (aria-current)');
    check(await ev(`document.querySelector('#view .ofbody > .ofpt')?.textContent === 'Quotes & invoices' && !document.querySelector('#view .ofmcrumb')`), '#2180: the page heading, no path on a list page');
    const w1280 = await ev(`Math.round(document.querySelector('#view .ofrail').getBoundingClientRect().width)`);
    check(Math.abs(w1280 - 240) <= 2, '#2180: the rail is 15 rem at 1280 px ' + w1280);
    check(await ev(`getComputedStyle(document.querySelector('#view .ofrail')).position === 'sticky'`), '#2180: the rail stays (sticky)');
    check(await ev(noSide), '#2180 1280: nothing sticks out to the side');
    const cr = await ev(contrast);
    check(cr >= 4.5, '#2180: the small caps have 4.5:1 in the light theme ' + cr);
    console.log('p298_c_ui: contrast of the small caps (light) ' + cr);
    await shot('p298c-desktop-1280-light.png');
    // the keys inside the rail
    await ev(`(() => { document.querySelector('#view .ofrail .ofri').focus(); return 1; })()`);
    check(await key(ev, 'ArrowDown') === 'offers', '#2180: ArrowDown = the next point');
    check(await key(ev, 'ArrowUp') === 'pipeline', '#2180: ArrowUp = the point before');
    check(await key(ev, 'End') === 'settings', '#2180: End = the last point');
    check(await key(ev, 'Home') === 'pipeline', '#2180: Home = the first point');
    check(await ev(`location.hash === '#office/offers'`), '#2180: the keys only move the focus');
    // Settings: General | Templates (services and text blocks; their old routes lead there)
    await click(ev, '#view .ofrail [data-ofm="settings"]');
    check(await ready(ev, `location.hash === '#office/settings' && !!document.querySelector('.office .ofrseg [data-go="office/settings"][aria-selected="true"]') && !!document.querySelector('#ofc-set')`, 60), '#2180: Settings opens on General');
    check(await ev(`!document.querySelector('#view .ofrail [data-ofm="services"],#view .ofrail [data-ofm="texts"]')`), '#2180: services and text blocks are no points of the rail');
    await click(ev, '.office .ofrseg [aria-selected="false"]');
    check(await ready(ev, `location.hash === '#office/services' && !!document.querySelector('.office[data-ofctab="services"] .ofrseg2 [data-go="office/services"][aria-selected="true"]') && document.querySelector('#view .ofrail [aria-current="page"]')?.dataset.ofm === 'settings'`, 60), '#2180: the tab Templates = services, the rail stays on Settings');
    await click(ev, '.office .ofrseg2 [data-go="office/texts"]');
    check(await ready(ev, `location.hash === '#office/texts' && !!document.querySelector('.office[data-ofctab="texts"] .ofrseg [aria-selected="true"]') && document.querySelector('.office .ofrseg [aria-selected="true"]').dataset.go === 'office/texts'`, 60), '#2180: Templates > Text blocks');
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('.office .ofrseg [data-go="office/texts"]')`, 60), '#2180: Templates opens the one used last');
    await nav(B + '#office/services');
    check(await ready(ev, `!!document.querySelector('.office[data-ofctab="services"] .ofrseg2') && document.querySelector('#view .ofbody > .ofpt')?.textContent === 'Settings'`, 60), '#2180: the old route #office/services leads into the tab');
    // the path of a detail page instead of the heading
    await nav(B + '#client/' + cl.id);
    check(await ready(ev, `!!document.querySelector('#view .ofbody > .ofmcrumb')`, 60), '#2180: the path on a client, inside the page column');
    check(await ev(`!document.querySelector('#view .ofpt') && document.querySelector('#view .ofrail [aria-current="page"]')?.dataset.ofm === 'clients'`), '#2180: no heading on a detail page, the rail marks Clients');
    // dark theme
    await theme(ev, 'dark'); await nav(B + '#office/offers');
    await ready(ev, `!!document.querySelector('#view .ofrail') && !!OFC.info`, 60); await sleep(500);
    check(await ev(contrast) >= 4.5, '#2180: the small caps have 4.5:1 in the dark theme too');
    await shot('p298c-desktop-1280-dark.png');
    // ================= #2180 computer 1024: the rail is 12 rem, the page still wide enough
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1024, height: 800}});
    await theme(ev, 'light'); await nav(B + '#office/offers');
    await ready(ev, `!!document.querySelector('#view .ofrail') && !!OFC.info`, 60); await sleep(600);
    const m = JSON.parse(await ev(`JSON.stringify({rail: Math.round(document.querySelector('#view .ofrail').getBoundingClientRect().width), body: Math.round(document.querySelector('#view .ofbody').getBoundingClientRect().width), side: !!document.querySelector('#side') && document.querySelector('#side').getBoundingClientRect().width})`));
    console.log('p298_c_ui: 1024 px - rail / page / sidebar ' + JSON.stringify(m));
    check(Math.abs(m.rail - 192) <= 2, '#2180 1024: the rail is 12 rem ' + JSON.stringify(m));
    // with the main sidebar open (15 rem) 722 px are left for rail + page: a 12 rem rail leaves ~506 px (560 would need a
    // narrower rail); the quotations' search, filter and kinds still fit
    check(m.body >= 500, '#2180 1024: the page column is at least 500 px wide ' + JSON.stringify(m));
    check(await ev(noSide), '#2180 1024: no scrolling sideways');
    await shot('p298c-desktop-1024.png');
    // ================= #2180 phone 402
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 874}});
    await nav(B + 'static/icon.svg'); await nav(B + '#office');
    check(await ready(ev, `document.querySelectorAll('#view .ofmstart .ofl .oflg').length === 3`, 80), '#2180 phone: the start page lists three groups');
    check(await ev(`!document.querySelector('#view .ofrail') && !document.querySelector('#view .ofpb') && !document.querySelector('#view .ofmtiles')`), '#2180 phone: the list is the menu, no tiles');
    check(await ev(`(() => { const rs = [...document.querySelectorAll('#view .oflc .oflr')], l = new Set(rs.map(b => Math.round(b.getBoundingClientRect().left))), w = new Set(rs.map(b => Math.round(b.getBoundingClientRect().width))); return rs.length === 15 && l.size === 1 && w.size === 1 && rs.every(b => b.getBoundingClientRect().height >= 45); })()`), '#2180 phone: one column, 15 rows of at least 2.875 rem');
    check(await ev(`[...document.querySelectorAll('#view .oflg h3')].map(h => h.textContent.trim()).join('|') === 'Sell|Money|Administration'`), '#2180 phone: the group headings');
    check(await ev(noSide), '#2180 phone: nothing sticks out to the side (start)');
    await shot('p298c-phone-start.png');
    await click(ev, '#view .oflc [data-ofm="subs"]');
    check(await ready(ev, `location.hash === '#office/subs' && !!document.querySelector('#view .ofpb .ofpts')`, 60), '#2180 phone: a row opens its page with the bar');
    await sleep(500);
    const pb = JSON.parse(await ev(`(() => { const bar = document.querySelector('#view .ofpb'), row = bar.querySelector('.ofpts'), ts = [...row.querySelectorAll('.ofpt2')], rb = row.getBoundingClientRect(), on = row.querySelector('.ofpt2.on').getBoundingClientRect();
      const first = [...bar.querySelectorAll('button,a,[tabindex]')].find(x => x.tabIndex >= 0);
      return JSON.stringify({n: ts.length, rows: new Set(ts.map(t => Math.round(t.getBoundingClientRect().top))).size, wrap: getComputedStyle(row).flexWrap, ox: getComputedStyle(row).overflowX, onSeen: on.left >= rb.left - 1 && on.right <= rb.right + 1,
        back: first?.classList.contains('ofpback') && first.dataset.go === 'office/start', label: bar.querySelector('.ofpback').textContent.trim(), sticky: getComputedStyle(bar).position, th: Math.min(...ts.map(t => t.getBoundingClientRect().height))}); })()`));
    check(pb.n === 6 && pb.rows === 1 && pb.wrap === 'nowrap' && pb.ox === 'auto', '#2180 phone: the six points of Money in ONE row that scrolls ' + JSON.stringify(pb));
    check(pb.onSeen, '#2180 phone: the active tab is in sight ' + JSON.stringify(pb));
    check(pb.back && /^Office\s*·\s*Money$/.test(pb.label) && pb.sticky === 'sticky' && pb.th >= 43, '#2180 phone: the way back "Office · Money" first, sticky, large tabs ' + JSON.stringify(pb));
    check(await ev(noSide), '#2180 phone: nothing sticks out to the side (sub page)');
    await shot('p298c-phone-page.png');
    await ev(`(() => { document.querySelector('#view .ofpb .ofpt2.on').focus(); return 1; })()`);
    check(await key(ev, 'ArrowRight') === 'travel' && await key(ev, 'ArrowLeft') === 'subs' && await key(ev, 'Home') === 'cashflow', '#2180 phone: left / right / Home in the tab row');
    await click(ev, '#view .ofpb .ofpback');
    check(await ready(ev, `location.hash === '#office/start' && document.querySelectorAll('#view .oflg').length === 3`, 60), '#2180 phone: the way back leads to the start list');
  }, false);

  console.log(`p298_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
