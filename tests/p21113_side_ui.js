// kalmido-suite: fresh
// 2.1113.0 UI test (#5966): the lower part of the phone's drawer looks the same in every area (Firefox, touch, 412 x 915).
// freelancer-matrix: n/a (no new route; alice runs the instance without an organisation, the drawer is the same for her)
// - every area below the row of areas starts with ONE head: its name on the left, its actions on the right (Time: the pen of
//   the menu sits in that head, no row that holds the pen alone any more)
// - the rows are as high as the rows of Projects; the open entry carries the same mark everywhere (the tint and the accent):
//   a project view, a part of Time and a page of Knowledge
// - Start has one entry only: nothing below the row of areas repeats it
// - Knowledge leaves folders that start with "_" (_attachments) out of the drawer's tree, the other folders stay
// Screenshots into $P21113S_SHOTS. Invented names only.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21113_side_ui', check, shots: 'P21113S_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const MODS = 'cal,comments,wiki,time,pomo,collab';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'de', collab_all: true, time_all: true, modules: MODS.split(',')});
  await call(CA, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: MODS});
  for (const n of ['Garten', 'Steuer']) await call(CA, 'POST', '/api/lists', {name: n});
  const pg = await call(CA, 'POST', '/api/wiki/pages', {space: 'private', path: 'Rezepte/Kuchen', body: 'Mehl, Zucker, Eier'});
  const att = await call(CA, 'POST', '/api/wiki/pages', {space: 'private', path: '_attachments/Bildliste', body: 'nur Technik'});
  check(pg.id && att.id, 'two pages, one in a folder "_attachments" ' + pg.http + ' ' + att.http);

  await firefox(async ({cmd, ev, nav, ctx, shot, until}) => {
    const wait = (s, o) => until(() => ev(s), o);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height: 915}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.lookLocal', 'true'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await nav(B + '#today'); await wait(`!!S.booted`);
    const open = async () => { await ev(`(() => { if (!document.querySelector('#side.open')) document.querySelector('#top .menu')?.click(); return 1; })()`); return wait(`!!document.querySelector('#side.open .sbmr .srb[data-sbb]')`); };
    const area = async id => { await ev(`(() => { document.querySelector('#side .sbmr .srb[data-sbb="${id}"]').click(); return 1; })()`); await open(); };
    // the look of the open entry and of the rows, the head below the row of areas
    const LOOK = sel => `(() => { const vis = e => !!e && !!e.offsetParent; const on = [...document.querySelectorAll(${JSON.stringify(sel)})].find(vis);
      const cs = on && getComputedStyle(on), hd = document.querySelector('#side .sbah');
      return JSON.stringify({bg: cs ? cs.backgroundColor : null, fg: cs ? cs.color : null, h: on ? Math.round(on.getBoundingClientRect().height) : 0, text: getComputedStyle(document.body).color,
        head: vis(hd) ? hd.querySelector('.sbaht')?.textContent || '' : null, tools: vis(hd) ? [...hd.querySelectorAll('.sbtools button')].map(b => b.dataset.act + ':' + (b.dataset.area || '')).join() : '',
        pen: !!document.querySelector('#side .navpen'), rows: [...document.querySelectorAll('#side .sbbp .srow, #side .sbbp .sbbt')].filter(vis).map(r => r.textContent.trim()),
        hs: [...new Set([...document.querySelectorAll('#side .sbbp .srow, #side .sbbp .sbbt')].filter(vis).map(r => Math.round(r.getBoundingClientRect().height)))]}); })()`;
    const look = async sel => JSON.parse(await ev(LOOK(sel)) || 'null');
    const tint = c => !!c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent';

    // Projects: the open view (Today) - the mark every area shares, the row height of Projects
    check(await open(), 'the drawer opens');
    await wait(`!!document.querySelector('#side .srow.on[data-go="today"]')`);
    const pj = await look('#side .srow.on[data-go="today"]');
    const ph = JSON.parse(await ev(`JSON.stringify([...document.querySelectorAll('#side .srow[data-list]')].filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().height)))`));
    check(tint(pj.bg) && pj.fg !== pj.text && ph.length >= 2, '#5966: Projects marks the open view with the tint and the accent ' + JSON.stringify({pj, ph}));
    await shot('p21113-projects.png');

    // Time: one head with the name and the pen, no row with the pen alone; the open part with the same mark, rows as high
    await area('time');
    check(await wait(`!!document.querySelector('#side.open .sbah') && !!document.querySelector('#side .sbbp .srow.on')`), '#5966: the area Time in the drawer');
    const tm = await look('#side .sbbp .srow.on');
    const tname = await ev(`tr(sbb_def('time')[2])`);
    check(tm.head === tname && /nav-edit:time/.test(tm.tools) && !tm.pen, '#5966: Time starts with its head (name left, pen right), no row with the pen alone ' + JSON.stringify(tm) + ' ' + tname);
    check(tm.bg === pj.bg && tm.fg === pj.fg, '#5966: the open part of Time carries the same mark as Projects ' + JSON.stringify({tm, pj}));
    check(tm.hs.length === 1 && Math.abs(tm.hs[0] - ph[0]) <= 1, '#5966: the rows of Time as high as the rows of Projects ' + JSON.stringify({hs: tm.hs, ph}));
    const gap = await ev(`(() => { const h = document.querySelector('#side .sbah').getBoundingClientRect(), r = [...document.querySelectorAll('#side .sbbp .srow')].find(e => e.offsetParent).getBoundingClientRect(); return Math.round(r.top - h.bottom); })()`);
    check(gap >= 0 && gap <= 8, '#5966: the first row of Time right below its head (no big gap) ' + gap);
    await shot('p21113-time.png');

    // Start: one entry only - nothing below the row of areas repeats it
    await area('home');
    await wait(`location.hash.startsWith('#home') && !!document.querySelector('#side.open .sbmr .srb.on[data-sbb="home"]')`);
    await sleep(300);
    const hm = await look('#side .sbbp .srow.on');
    check(hm.head === null && !hm.rows.length, '#5966: Start shows nothing twice below the row of areas ' + JSON.stringify(hm));
    await shot('p21113-start.png');

    // Knowledge: its head, the folders without "_attachments", the open page with the same mark
    await ev(`(() => { closeSide?.(); location.hash = '#wiki/${pg.id}'; return 1; })()`);
    await wait(`S.route.mod === 'wiki' && S.route.wid === ${pg.id}`);
    await open();
    check(await wait(`!!document.querySelector('#side.open .sbah') && [...document.querySelectorAll('#side .sbbt')].some(r => /Kuchen/.test(r.textContent))`, {timeout: 15000}), '#5966: the tree of Knowledge in the drawer, open down to the page');
    const wk = await look('#side .sbbt.on');
    const wname = await ev(`tr(sbb_def('wiki')[2])`);
    check(wk.head === wname, '#5966: Knowledge starts with its head ' + JSON.stringify(wk) + ' ' + wname);
    check(wk.rows.some(t => /Rezepte/.test(t)) && !wk.rows.some(t => /_attachments/.test(t)), '#5966: the folder "_attachments" is left out of the tree, "Rezepte" stays ' + JSON.stringify(wk.rows));
    check(wk.bg === pj.bg && wk.fg === pj.fg, '#5966: the open page carries the same mark as Projects ' + JSON.stringify({wk, pj}));
    check(wk.hs.every(x => Math.abs(x - ph[0]) <= 1), '#5966: the rows of Knowledge as high as the rows of Projects ' + JSON.stringify({hs: wk.hs, ph}));
    await shot('p21113-wiki.png');
  }, true);
  console.log(F.length ? `p21113_side_ui: ${F.length} FAILED, ${ok} passed` : `p21113_side_ui: all ${ok} passed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
