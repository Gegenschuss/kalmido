// Release 2.783.0 part A (#5375, #5376) UI tests: the knowledge views on a computer use the full width, a page does not jump.
// kalmido-suite: fresh
// Own container (start.sh), Firefox with a mouse; invented pages only. Screenshots: P2783A_SHOTS.
// #5375 every knowledge view of the stack .wkdesk (a folder, the space's top, a tag's pages, search hits, "All workspaces")
//   starts at the left edge of the bar (Find a page, New page, ...) and takes >= 80 % of the main area - before it stood as a
//   narrow column in the middle (start-breite.css margin-inline:auto in a flex column); 768 / 1280 / 1920, panel open and
//   hidden; Completed (.hview) as well; 320 / 460 (the phone's list) nothing runs over the side
// #5376 a page open: #top's title stands where the list has it (+-4 px), the card takes >= 80 % of the main area from the list's
//   left edge; the width switch: Read = the text column --w-lesen in the card's middle, Full = the card's width; 768 / 1280 / 1920 / 2560
//   2.1163.0 (#6089): no area bar above the page (its head is the only one) and the page scrolls as a whole (no inner box; before:
//   the card ended at the window's edge and the text scrolled inside it)
// freelancer-matrix: Wissen (alice has no organisation until the last part, "All workspaces" needs a second space)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2783_a_wiki_layout_ui', check, shots: 'P2783A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2783A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

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
  const long = Array.from({length: 90}, (_, i) => `Step ${i + 1}: check the light, the sound and the props of the scene.`).join('\n\n');
  const P = {};
  for (const [k, p, b] of [['pack', 'Handbook/Packing list', 'Camera, lenses, batteries. #shoot'], ['train', 'Handbook/Travel/Train times', 'The early train at seven. #shoot'],
    ['day', 'Handbook/Shoot day', long], ['top', 'Top page', 'A page at the top.']]) P[k] = (await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: b})).id;
  check(Object.values(P).every(Boolean), 'setup: four knowledge pages in folders');

  await firefox(async ({cmd, ev, ctx, nav, shot, until, idle}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    const size = (w, h) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
    // the main area (#view without its padding), the bar, an element of the view and #top's title (px)
    const M = sel => `(() => { const v = document.querySelector('#view'), vs = getComputedStyle(v), vr = v.getBoundingClientRect(), e = document.querySelector(${JSON.stringify(sel)});
      if (!e || !e.offsetWidth) return null;
      const b = e.getBoundingClientRect(), bar = document.querySelector('#view .wkbar')?.getBoundingClientRect(), t = document.querySelector('#top h1, #top .ttl, #top .title, #top h2')?.getBoundingClientRect();
      return {l: Math.round(b.left), w: Math.round(b.width), bot: Math.round(b.bottom), area: Math.round(v.clientWidth - parseFloat(vs.paddingLeft) - parseFloat(vs.paddingRight)), l0: Math.round(vr.left + parseFloat(vs.paddingLeft)),
        barL: bar ? Math.round(bar.left) : null, barT: bar ? Math.round(bar.top) : null, topL: t ? Math.round(t.left) : null, sw: document.documentElement.scrollWidth, vw: innerWidth, ih: innerHeight,
        vsc: v.scrollHeight - v.clientHeight, side: !LS.get('sideFold', false) && !!document.querySelector('#side')?.offsetWidth}; })()`;
    const panel = async open => {  // "Hide the panel" / the area's icon brings it back (areas.js sbb_panel)
      if (!!(await ev(`!LS.get('sideFold', false)`)) !== open) await ev(`(() => { sbb_panel(); return 1; })()`);
      return until(`!LS.get('sideFold', false) === ${open}`, {timeout: 5000});
    };
    const wide = (m, what) => {
      check(m && Math.abs(m.l - m.barL) <= 8 && Math.abs(m.l - m.l0) <= 8, `${what}: starts at the left edge of the bar ${JSON.stringify(m)}`);
      check(m && m.w >= 0.8 * m.area, `${what}: takes >= 80 % of the main area ${JSON.stringify(m)}`);
      check(m && m.sw <= m.vw, `${what}: nothing runs over the side ${JSON.stringify(m)}`);
    };
    const rows = () => ev(`[...document.querySelectorAll('#view .wkfolder .wkitem span, #view .wkfolder .wkitem')].map(x => x.textContent.trim()).join('|')`);

    // ================= #5375: the views of the stack, wide screens, panel open and hidden
    for (const [W, Ht] of [[768, 900], [1280, 860], [1920, 1080]]) {
      await size(W, Ht);
      for (const open of [true, false]) {
        const tag = `${W} panel ${open ? 'open' : 'hidden'}`;
        await nav(B + '?w=' + W + '#wiki/d/Handbook');
        check(await until(`!!document.querySelector('#view .wkdesk .wkfolder .wkdlist')`, {timeout: 20000}), `${tag}: the folder Handbook shows its list`);
        check(await panel(open), `${tag}: the panel ${open ? 'open' : 'hidden'}`);
        await idle();
        check(await until(`document.querySelector('#view .wkfolder h2')?.textContent.trim() === 'Handbook'`), `${tag}: the folder's heading`);
        const r = await rows();
        check(/Travel/.test(r) && /Packing list/.test(r) && /Shoot day/.test(r), `${tag}: the subfolder and the pages are rows (${r})`);
        wide(await until(M('#view .wkfolder')), `#5375 ${tag} folder`);
        await shot(`p2783a-folder-${W}-${open ? 'open' : 'hidden'}.png`);
        if (!open) continue;
        // the space's top, a tag's pages, search hits (the same stack)
        await nav(B + '?w=' + W + '#wiki');
        check(await until(`/Top page/.test(document.querySelector('#view .wkfolder')?.textContent || '')`, {timeout: 20000}), `${tag}: the space's top lists its pages`);
        wide(await until(M('#view .wkfolder')), `#5375 ${tag} the space's top`);
        await nav(B + '?w=' + W + '#wiki/t/shoot');
        check(await until(`(() => { const t = document.querySelector('#view .wkfolder.wktagview')?.textContent || ''; return /Packing list/.test(t) && /Train times/.test(t); })()`, {timeout: 20000}), `${tag}: the tag shoot lists its two pages`);
        wide(await until(M('#view .wkfolder.wktagview')), `#5375 ${tag} a tag's pages`);
        await nav(B + '?w=' + W + '#wiki/d/Handbook');
        await until(`!!document.querySelector('#wk-q')`, {timeout: 20000});
        await ev(`(() => { const q = document.querySelector('#wk-q'); q.value = 'train'; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
        check(await until(`/Train times/.test(document.querySelector('#view .wkfolder #wk-res')?.textContent || '')`), `${tag}: the search finds Train times`);
        wide(await until(M('#view .wkfolder')), `#5375 ${tag} search hits`);
        await ev(`(() => { const q = document.querySelector('#wk-q'); q.value = ''; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);  // the search is kept (WK.q): empty again
        check(await until(`!document.querySelector('#view .wkfolder #wk-res.wkdlist') && !!document.querySelector('#view .wkfolder h2')`), `${tag}: the search emptied, the folder again`);
      }
    }
    // Completed (.hview, the same rule in start-breite.css)
    await size(1280, 860);
    await nav(B + '?w=1280#done');
    wide(await until(`(() => { const m = ${M('#view .hview')}; return m && document.querySelector('#view .wkbar') === null ? {...m, barL: m.l0} : null; })()`, {timeout: 20000}), '#5375 1280 Completed (.hview)');
    // the phone: the list as before, nothing runs over the side
    for (const [W, Ht] of [[460, 860], [320, 700]]) {
      await size(W, Ht);
      await nav(B + '?w=' + W + '#wiki/d/Handbook');
      check(await until(`/Packing list/.test(document.querySelector('#view')?.textContent || '')`, {timeout: 20000}), `${W}: the folder's pages on the phone`);
      const m = await ev(`({sw: document.documentElement.scrollWidth, vw: innerWidth})`);
      check(m.sw <= m.vw, `${W}: nothing runs over the side ${JSON.stringify(m)}`);
      await shot(`p2783a-folder-${W}.png`);
    }

    // ================= #5376: a page open - no jump against the list, the card full width and inside the window
    for (const [W, Ht] of [[768, 900], [1280, 860], [1920, 1080], [2560, 1440]]) {
      await size(W, Ht);
      for (const open of [true, false]) {
        const tag = `${W} panel ${open ? 'open' : 'hidden'}`;
        await nav(B + '?w=' + W + '#wiki/d/Handbook');
        check(await until(`!!document.querySelector('#view .wkfolder .wkdlist')`, {timeout: 20000}), `${tag}: the list`);
        check(await panel(open), `${tag}: the panel`);
        await idle();
        const L = await until(M('#view .wkfolder'));
        await ev(`(() => { [...document.querySelectorAll('#view .wkdlist a.wkitem')].find(a => /Shoot day/.test(a.textContent)).click(); return 1; })()`);
        check(await until(`!!document.querySelector('#view .wkdesk.wkpgo article.wkpage #wk-cm .cm-content') && /Step 1:/.test(document.querySelector('#wk-cm')?.textContent || '')`, {timeout: 20000}), `${tag}: the page opens with its text in the editor`);
        await idle();
        const pg = await until(`(() => { const m = ${M('#view article.wkpage')}; if (!m) return null; const a = document.querySelector('[data-wka="add"]')?.getBoundingClientRect(), f = document.querySelector('#view article.wkpage .ntfoot')?.getBoundingClientRect(),
          c = document.querySelector('#wk-cm'), h2 = document.querySelector('#view article.wkpage h2')?.textContent.trim();
          return {...m, dsc: document.scrollingElement.scrollHeight - innerHeight, add: a ? [Math.round(a.top), Math.round(a.bottom)] : null, foot: f ? Math.round(f.bottom) : null, inner: c ? [c.scrollHeight, c.clientHeight] : null, h2}; })()`);
        check(pg && pg.h2 === 'Shoot day', `${tag}: the page's title ${pg?.h2}`);
        // 2.1163.0 (#6089): the bar (Find a page, New page, ...) belongs to the list, the page has only its own head
        check(pg && pg.barL == null, `#6089 ${tag}: no area bar above the open page ${JSON.stringify(pg)}`);
        check(pg && L && pg.topL != null && Math.abs(pg.topL - L.topL) <= 4, `#5376 ${tag}: #top's title stands where the list has it ${JSON.stringify([L?.topL, pg?.topL])}`);
        check(pg && L && pg.w >= 0.8 * pg.area && Math.abs(pg.l - L.l) <= 8, `#5376 ${tag}: the card takes the full width from the list's left edge ${JSON.stringify(pg)}`);
        // 2.1163.0 (#6089): the page scrolls as a whole: the text has no box of its own, the footer comes after the text
        check(pg && pg.inner && pg.inner[0] <= pg.inner[1] + 1, `#6089 ${tag}: the long text does not scroll inside the card ${JSON.stringify(pg?.inner)}`);
        check(pg && (pg.vsc > 100 || pg.dsc > 100) && pg.foot > pg.ih, `#6089 ${tag}: the page is longer than the window and scrolls as a whole ${JSON.stringify(pg)}`);
        if (open && (W === 1280 || W === 2560)) await shot(`p2783a-page-${W}.png`);
      }
    }
    // the width switch at 2560: Read = the text column --w-lesen in the card's middle, Full = the card's width
    const COL = `(() => { const c = document.querySelector('#wk-cm'), a = document.querySelector('#view article.wkpage'); if (!c || !a) return null; const s = getComputedStyle(c), cr = c.getBoundingClientRect(), ar = a.getBoundingClientRect(), rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
      return {col: Math.round(c.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight)), cl: Math.round(cr.left + parseFloat(s.paddingLeft) - ar.left), cr: Math.round(ar.right - (cr.right - parseFloat(s.paddingRight))), card: Math.round(ar.width), rem, cls: document.querySelector('#view .ntwrap').className}; })()`;  // 2.1163.0 (#6089): the column is the editor's margin now (no padding of a scroll box), the measure stays
    const rd = await until(`(() => { const x = ${COL}; return x && /pgw-lesen/.test(x.cls) ? x : null; })()`);
    check(rd && rd.col <= 46 * rd.rem + 2 && rd.col >= 45 * rd.rem - 2 && Math.abs(rd.cl - rd.cr) <= 4, `#5376 2560 Read: the text column --w-lesen in the card's middle ${JSON.stringify(rd)}`);
    await ev(`(() => { const o = LS.get('pgW', {}) || {}; o['w${P.day}'] = 'voll'; LS.set('pgW', o); renderView(); return 1; })()`);
    const fu = await until(`(() => { const x = ${COL}; return x && /pgw-voll/.test(x.cls) ? x : null; })()`);
    check(fu && fu.col >= 0.9 * fu.card, `#5376 2560 Full: the text takes the card's width ${JSON.stringify(fu)}`);
    await ev(`(() => { const o = LS.get('pgW', {}) || {}; delete o['w${P.day}']; LS.set('pgW', o); return 1; })()`);

    // ================= "All workspaces" (a second space: alice founds an organisation now)
    const og = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: st0.me.id});
    check(og.http < 300, 'the organisation Alpha ' + og.http);
    await call('PATCH', '/api/settings', {workspace: 'all'});
    await size(1920, 1080);
    await nav(B + '?w=1920#wiki');
    check(await until(`document.querySelector('#view .wkfolder h2')?.textContent.trim() === 'All workspaces'`, {timeout: 20000}), '1920: the overview All workspaces');
    check(await panel(true), '1920: the panel open');
    wide(await until(M('#view .wkfolder')), '#5375 1920 All workspaces');
    await shot('p2783a-all-1920.png');
  });

  console.log(`p2783_a_wiki_layout_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
