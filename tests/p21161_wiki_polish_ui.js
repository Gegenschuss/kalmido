// Package 2.1161.0 (#6086, #6088, #6090) UI tests: the knowledge pages polished - the phone's layout, the states of loading,
// failing and nothing-here, the page's content read like text.
// kalmido-suite: fresh
// Own container (start.sh), Firefox (a mouse, then a finger); invented pages only. Screenshots: P21161_SHOTS.
// #6086 360 px: the trash's page name keeps a line of its own (was one letter per line next to the buttons); Select: the page
//   names keep their room, the date leaves the row; a table in the editor: no header breaks inside a word; with a finger the
//   editor's boxes >= 19 px and the row "…" 44 px
// #6088 a page that fails to load: the shared error block with "Try again" (it loads then) and a way back; a page that is not
//   there: the no-access block with a way back; a failed save: "Not saved" stays in the footer (also after a redraw) until a
//   save works ("Try again" there); a failed text search says so; an empty folder = the shared empty block
// #6090 the front matter as fields (Tags, As of, the date written as the app writes dates), folded in the editor; a link shows the
//   page's name (the path as its tooltip), "Linked from" the name with its folders beside it; a daily note is titled with its
//   date and its folder "journal" reads "Daily notes"; a page from a template drops its empty points and its own front matter
//   (its tags stay); a snippet does not repeat the page's title
// freelancer-matrix: Wissen (alice has no organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21161_wiki_polish_ui', check, shots: 'P21161_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21161_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  check(!(st0.me.workspaces || []).length, 'setup: alice has no organisation (a person on her own)');
  const CHECK = '---\ntags: [shoot]\nas_of: 2026-11-10\n---\n# Checklist\n\nPlan B: [[Processes/Shoot day/Weather plan B]].\n\n'
    + '| Equipment | Quantity | Daily rate | Responsible | Remark | Location |\n|---|---|---|---|---|---|\n| Camera | 2 | 120 | Anna | with battery | Store |\n\n- [ ] Charge the batteries\n';
  const P = {};
  for (const [k, p, b] of [['check', 'Processes/Shoot day/Checklist', CHECK], ['plan', 'Processes/Shoot day/Weather plan B', 'Rain: the hall.'],
    ['cat', 'Processes/Shoot day/Catering', 'Lunch at one.'], ['exp', 'Processes/Editing/Export', 'ProRes.'], ['contacts', 'Contacts', 'Anna, Bert.'],
    ['day', 'journal/2026-11-14', 'Shot the first scene.'], ['old', 'Old price list for the summer shoot days 2025', 'Gone.'],
    ['tpl', 'Templates/Minutes', '---\ntype: minutes\ntags: [minutes]\n---\n# {{title}}\n\n- \n- [ ] \n* [ ]\n\nNotes here']]) P[k] = (await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: b})).id;
  check(Object.values(P).every(Boolean), 'setup: the pages ' + JSON.stringify(P));
  check((await call('DELETE', '/api/wiki/pages/' + P.old)).http < 300, 'setup: a page in the trash');
  check((await call('POST', '/api/wiki/folders', {space: 'private', name: 'Archive'})).http < 300, 'setup: an empty folder Archive');

  const login2 = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  // one fetch answer replaced in the page (a failing server for one URL), FAILX() takes it back
  const FAIL = (rx, status = 500, method = '') => `(() => { window.__f0 = window.__f0 || window.fetch; const f0 = window.__f0, rx = new RegExp(${JSON.stringify(rx)});
    window.fetch = (u, o) => rx.test(String(u && u.url || u)) && (!${JSON.stringify(method)} || (o && o.method || 'GET') === ${JSON.stringify(method)}) ? Promise.resolve(new Response(JSON.stringify({error: 'Test failure'}), {status: ${status}, headers: {'Content-Type': 'application/json'}})) : f0(u, o); return 1; })()`;
  const FAILX = `(() => { if (window.__f0) window.fetch = window.__f0; return 1; })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot, until, idle}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await login2(ev) === 200, 'ff: login');
    const size = (w, h) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});

    // ================= #6086 the phone (360 px)
    await size(360, 740);
    await nav(B + '?w=360#wiki');
    check(await until(`!!document.querySelector('#view .wktree') && typeof wk_trashDlg === 'function'`, {timeout: 20000}), '360: the knowledge pages');
    await ev(`(() => { wk_trashDlg('private'); return 1; })()`);
    const tn = await until(`(() => { const b = document.querySelector('.wktrashdlg .wktrow .n b'); if (!b) return null; const lh = parseFloat(getComputedStyle(b).lineHeight) || 20, r = b.getBoundingClientRect();
      return {w: Math.round(r.width), lines: Math.round(r.height / lh), txt: b.textContent}; })()`);
    check(tn && /Old price list/.test(tn.txt) && tn.w >= 150 && tn.lines <= 3, `#6086 360 the trash: the name keeps a line of its own (was one letter per line) ${JSON.stringify(tn)}`);
    const tb = await ev(`(() => { const n = document.querySelector('.wktrashdlg .wktrow .n').getBoundingClientRect(), b = document.querySelector('.wktrashdlg .wktrow [data-wkt="restore"]').getBoundingClientRect(); return {n: Math.round(n.bottom), b: Math.round(b.top), sw: document.querySelector('.wktrashdlg').scrollWidth <= document.querySelector('.wktrashdlg').clientWidth + 1}; })()`);
    check(tb && tb.b >= tb.n - 2 && tb.sw, `#6086 360 the trash: Restore / Delete below the name, nothing runs over ${JSON.stringify(tb)}`);
    await shot('p21161-trash-360.png');
    await ev(`(() => { document.querySelector('.wktrashdlg [data-wkt="close"]').click(); return 1; })()`);
    // Select: the leaves two folders deep keep their names
    await nav(B + '?w=360#wiki');
    await until(`!!document.querySelector('#view .wktree [data-wksel="mode"], #view [data-wksel="mode"]')`, {timeout: 20000});
    await ev(`(() => { document.querySelectorAll('#view details').forEach(x => x.open = true); document.querySelector('#view [data-wksel="mode"]').click(); return 1; })()`);
    const sel = await until(`(() => { const rs = [...document.querySelectorAll('#view .wkselrow')]; if (rs.length < 5) return null; document.querySelectorAll('#view details').forEach(x => x.open = true);
      const cut = [...document.querySelectorAll('#view .wkselrow a.wkitem > span')].filter(s => s.offsetWidth && s.scrollWidth > s.clientWidth + 1 && s.clientWidth < 100).map(s => [s.textContent, s.clientWidth]);
      return {n: rs.length, cut, dates: [...document.querySelectorAll('#view .wkselrow .wkwhen')].filter(x => x.offsetWidth).length, sw: document.documentElement.scrollWidth, vw: innerWidth}; })()`);
    check(sel && !sel.cut.length && sel.dates === 0 && sel.sw <= sel.vw, `#6086 360 Select: every page name keeps its room, no date in the row, nothing runs over ${JSON.stringify(sel)}`);
    await shot('p21161-select-360.png');
    await ev(`(() => { wk_selEnd(); renderView(); return 1; })()`);
    // a table in the editor: no header broken inside a word
    await nav(B + '?w=360#wiki/' + P.check);
    if (await until(`!!document.querySelector('#view [data-wk="pen"]')`, {timeout: 20000})) await ev(`(() => { const b = document.querySelector('#view [data-wk="pen"]'); if (b.getAttribute('aria-pressed') !== 'true') b.click(); return 1; })()`);  // a phone reads first
    const th = await until(`(() => { const ts = [...document.querySelectorAll('#wk-cm .cm-wktbl th')]; if (ts.length < 6) return null;
      return ts.map(t => { const r = document.createRange(); r.selectNodeContents(t); return [t.textContent.trim(), new Set([...r.getClientRects()].map(x => Math.round(x.top))).size]; }); })()`, {timeout: 20000});
    check(th && th.every(([t, n]) => n <= t.split(/\s+/).length), `#6086 360 the editor's table: each header on one line (was "Equipm ent") ${JSON.stringify(th)}`);
    if (!th) console.log('table state:', await ev(`JSON.stringify({cm: !!document.querySelector('#wk-cm'), edit: WK.edit, pg: WK.pg?.id, mob: isMobile(), tch: isTouch(), lines: [...document.querySelectorAll('#wk-cm .cm-line')].map(l => l.textContent).slice(0, 14), view: (document.querySelector('#view')?.textContent || '').slice(0, 300)})`));
    const tw = await ev(`(() => { const t = document.querySelector('#wk-cm .cm-wktbl'); return t ? {sw: t.scrollWidth, cw: t.clientWidth, page: document.documentElement.scrollWidth <= innerWidth} : null; })()`);
    check(tw && tw.sw > tw.cw && tw.page, `#6086 360 the editor's table scrolls sideways in its box, the page does not ${JSON.stringify(tw)}`);
    await shot('p21161-table-360.png');

    // ================= #6090 the content read like text (computer)
    await size(1280, 860);
    await nav(B + '?w=1280#wiki/' + P.check);
    const fm = await until(`(() => { const w = document.querySelector('#wk-cm .cm-wkfmw .wkattrs'); if (!w) return null; return {dt: [...w.querySelectorAll('dt')].map(x => x.textContent), dd: [...w.querySelectorAll('dd')].map(x => x.textContent),
      raw: [...document.querySelectorAll('#wk-cm .cm-line')].some(l => /^---$|^as_of:/.test(l.textContent)), want: fmtDay('year', new Date('2026-11-10T00:00:00'))}; })()`, {timeout: 20000});
    check(fm && fm.dt.join('|') === 'Tags|As of' && fm.dd[1] === fm.want && !fm.raw, `#6090 the editor: the front matter folded to fields, the date written out ${JSON.stringify(fm)}`);
    const ln = await ev(`(() => { const a = document.querySelector('#wk-cm .cm-wkwl'); return a ? {t: a.textContent, ti: a.getAttribute('title')} : null; })()`);
    check(ln && ln.t === 'Weather plan B' && ln.ti === 'Processes/Shoot day/Weather plan B', `#6090 the editor: a link shows the page's name, the path as its tooltip ${JSON.stringify(ln)}`);
    await shot('p21161-editor-1280.png');
    // a click on the folded line opens the lines
    await ev(`(() => { WKCM.view.focus(); WKCM.view.dispatch({selection: {anchor: 5}}); return 1; })()`);  // the cursor in the front matter (focus first: a headless window sends no focus event, the update sees it)
    check(await until(`!document.querySelector('#wk-cm .cm-wkfmw') && [...document.querySelectorAll('#wk-cm .cm-line')].some(l => /^as_of: 2026-11-10/.test(l.textContent))`), '#6090 the editor: the cursor in the fields shows the front matter to edit') || console.log('fm lines:', await ev(`JSON.stringify([...document.querySelectorAll('#wk-cm .cm-line')].slice(0, 6).map(l => l.textContent))`));
    // the read view (the lock "Read-only")
    await ev(`(() => { LS.set('wkRo', '1'); WK.edit = false; renderView(); return 1; })()`);
    const rd = await until(`(() => { const a = document.querySelector('#wk-md a.wklink'), dl = document.querySelector('#view .wkpage > .wkattrs, #view .wkpage .wkattrs'); if (!a || !dl) return null;
      const as = [...dl.querySelectorAll('div')].find(x => x.querySelector('dt')?.textContent === 'As of');
      return {t: a.textContent, ti: a.getAttribute('title'), dt: [...dl.querySelectorAll('dt')].map(x => x.textContent).sort().join('|'), dd: as?.querySelector('dd')?.textContent, want: fmtDay('year', new Date('2026-11-10T00:00:00'))}; })()`, {timeout: 20000});
    check(rd && rd.t === 'Weather plan B' && rd.ti === 'Processes/Shoot day/Weather plan B', `#6090 read: the link shows the page's name ${JSON.stringify(rd)}`);
    check(rd && rd.dt === 'As of|Tags' && rd.dd === rd.want, `#6090 read: the front matter's keys as words, the date written out (was "as_of 2026-11-10") ${JSON.stringify(rd)}`);
    await nav(B + '?w=1280#wiki/' + P.plan);
    const bl = await until(`(() => { const a = document.querySelector('#view .wkback a'); return a ? {name: a.querySelector('span')?.firstChild?.textContent.trim(), dir: a.querySelector('.wkpdir')?.textContent} : null; })()`, {timeout: 20000});
    check(bl && bl.name === 'Checklist' && bl.dir === 'Processes / Shoot day', `#6090 "Linked from": the name, its folders quietly beside it ${JSON.stringify(bl)}`);
    // the daily note: its date as the title, its folder in words
    await nav(B + '?w=1280#wiki/' + P.day);
    const dn = await until(`(() => { const h = document.querySelector('#view .wkpage h2'); return h && h.textContent.trim() ? {h: h.textContent.trim(), want: fmtDay('year', new Date('2026-11-14T00:00:00')), crumbs: document.querySelector('#view .wkpage .wkcrumbs')?.textContent} : null; })()`, {timeout: 20000});
    check(dn && dn.h === dn.want && /Daily notes/.test(dn.crumbs || '') && !/journal/.test(dn.crumbs || ''), `#6090 the daily note: titled with its date, the folder "Daily notes" (was 2026-11-14 in "journal") ${JSON.stringify(dn)}`);
    await shot('p21161-daynote-1280.png');
    // a page from a template
    const mk = await ev(`wk_mk('private', 'Minutes/Monday', ${P.tpl}).then(r => r.id)`);
    const mb = mk && (await call('GET', '/api/wiki/pages/' + mk)).body;
    check(typeof mb === 'string' && !/^\s*[-*]\s*(\[ \])?\s*$/m.test(mb) && !/type: minutes/.test(mb) && /tags: \[minutes\]/.test(mb) && /# Monday/.test(mb) && /Notes here/.test(mb),
      `#6090 a page from a template: no empty points, the template's own front matter left out, its tags kept ${JSON.stringify(mb)}`);
    // a snippet that starts with the title
    const sn = await ev(`wks_snipHtml({path: 'Processes/Shoot day/Checklist', snippet: 'Checklist This list holds every shoot day', marks: [[20, 25]]}, 'holds')`);
    check(/^<small class="wksnip">This list <b>holds<\/b> every shoot day<\/small>$/.test(sn || ''), `#6090 a snippet does not repeat the page's title ${sn}`);
    await ev(`(() => { LS.set('wkRo', ''); return 1; })()`);

    // ================= #6088 loading, failing, nothing here
    await ev(FAIL(`/api/wiki/pages/${P.exp}$`));
    await nav(B + '?w=1280#wiki/' + P.exp);
    await ev(FAIL(`/api/wiki/pages/${P.exp}$`));
    const er = await until(`(() => { const e = document.querySelector('#view .wkpage .eerr'); return e ? {t: e.textContent, retry: !!e.querySelector('[data-esretry]'), back: e.querySelector('a[data-navup]')?.getAttribute('href')} : null; })()`, {timeout: 20000});
    check(er && /The page could not be loaded/.test(er.t) && er.retry && er.back, `#6088 a page that fails to load: what failed, Try again and a way back ${JSON.stringify(er)}`);
    await shot('p21161-loaderror-1280.png');
    await ev(FAILX);
    await ev(`(() => { document.querySelector('#view .wkpage [data-esretry]').click(); return 1; })()`);
    check(await until(`/ProRes/.test(document.querySelector('#view .wkpage #wk-cm')?.textContent || '')`, {timeout: 20000}), '#6088 Try again: the page loads');
    await nav(B + '?w=1280#wiki/999999');
    const na = await until(`(() => { const e = document.querySelector('#view .wkpage .enoacc'); return e ? {t: e.textContent, back: !!e.querySelector('a[data-navup]')} : null; })()`, {timeout: 20000});
    check(na && /does not exist/.test(na.t) && na.back, `#6088 a page that is not there: the no-access block with a way back ${JSON.stringify(na)}`);
    await size(360, 740);
    await nav(B + '?w=360#wiki/999998');
    check(await until(`!!document.querySelector('#view .wkpage .enoacc a[data-navup]')`, {timeout: 20000}), '#6088 360: the phone gets the way back too');
    await size(1280, 860);
    // a failed save
    await nav(B + '?w=1280#wiki/' + P.cat);
    check(await until(`/Lunch at one/.test(document.querySelector('#wk-cm')?.textContent || '') && !!WKCM.view`, {timeout: 20000}), 'the page Catering in the editor');
    await ev(FAIL(`/api/wiki/pages/${P.cat}$`, 500, 'PATCH'));
    await ev(`(() => { const v = WKCM.view; v.dispatch({changes: {from: v.state.doc.length, insert: ' And coffee.'}, userEvent: 'input'}); WK.dirty = true; wk_flush(); return 1; })()`);
    check(await until(`/Not saved/.test(document.querySelector('#wk-saved.wkunsaved')?.textContent || '')`), '#6088 a failed save: "Not saved" in the footer');
    await ev(`(() => { renderView(); return 1; })()`);
    check(await until(`/Not saved/.test(document.querySelector('#wk-saved.wkunsaved')?.textContent || '') && !!document.querySelector('#wk-saved [data-wk="resave"]')`), '#6088 it stays after the page is drawn again, with Try again');
    await shot('p21161-notsaved-1280.png');
    await ev(FAILX);
    await ev(`(() => { document.querySelector('#wk-saved [data-wk="resave"]').click(); return 1; })()`);
    check(await until(`!document.querySelector('#wk-saved.wkunsaved')`), '#6088 Try again saved: the note goes');
    check(await until(async () => /And coffee/.test((await call('GET', '/api/wiki/pages/' + P.cat)).body || '')), '#6088 the text is on the server');
    // an empty folder; a failed text search
    await nav(B + '?w=1280#wiki/d/Archive');
    check(await until(`/This folder is empty/.test(document.querySelector('#view .wkfolder .nempty')?.textContent || '')`, {timeout: 20000}), '#6088 an empty folder: the shared empty block');
    await ev(FAIL('/api/search'));
    await ev(`(() => { const q = document.querySelector('#wk-q'); q.value = 'zebra'; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    const se = await until(`(() => { const e = document.querySelector('#wks .eerr'); return e ? e.textContent : null; })()`);
    check(se && /search in the texts did not work/.test(se), `#6088 a failed text search says so (was "No page matches.") ${se}`);
    await ev(FAILX);
  });

  // ================= #6086 with a finger: the editor's boxes and the row "…"
  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await login2(ev) === 200, 'ff touch: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await nav(B + '?w=360#wiki');
    const more = await until(`(() => { document.querySelectorAll('#view details').forEach(x => x.open = true); const b = [...document.querySelectorAll('#view .wkrow .wkmore')].find(x => x.offsetWidth); if (!b) return null; const r = b.getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height)}; })()`, {timeout: 20000});
    check(more && more.w >= 43 && more.h >= 43, `#6086 finger: the row "…" 44 px ${JSON.stringify(more)}`);
    await nav(B + '?w=360#wiki/' + P.check);
    await until(`!!document.querySelector('#view [data-wk="pen"]')`, {timeout: 20000});
    await ev(`(() => { document.querySelector('#view [data-wk="pen"]').click(); return 1; })()`);
    const cb = await until(`(() => { const b = document.querySelector('#wk-cm .cm-wkcb input'); if (!b) return null; const r = b.getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height)}; })()`, {timeout: 20000});
    check(cb && cb.w >= 19 && cb.h >= 19, `#6086 finger: the editor's box as big as the read view's (was 14 px) ${JSON.stringify(cb)}`);
    await shot('p21161-finger-360.png');
  }, true);

  console.log(`p21161_wiki_polish_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
