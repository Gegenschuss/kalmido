// 2.769.0 UI tests of part D (#5352): "Recently edited" instead of the doubled list of the workspaces. Own container (start.sh),
// kalmido-suite: fresh
// jsdom + Firefox (real layout at 320 / 460 / 840 / 1280 px). Invented data only.
// - the overview "All workspaces" of Knowledge, Files and Reading: the main area shows "Recently edited" (newest first, the chip of
//   the workspace, who, when, a tap opens the item); on a computer with the panel NO second list of the workspaces (the panel has
//   it), with the panel hidden / on a phone the workspaces as compact chips on top; Reading (its panel lists none) keeps the chips
// - pinned: a favourite page shows above the list
// - empty: one sentence and "New page"
// - Start: the block "Recently edited", on by default, 8 entries, "More" leads to the overview; hidden like every block; in one
//   workspace only its own items, without chips
// - Firefox: full width, one line per row, no row wider than the screen, the placeholder as high as the list (no jump)
// - a person without an organisation: the block with her own items (freelancer-matrix: wiki)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2769_d_recent_ui', check, shots: 'P2769D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const upload = async (ck, name, space) => {
  const fd = new FormData(); fd.append('file', new Blob(['text of ' + name]), name); fd.append('space', space);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).items[0].id;
};
const FEAT = 'cal,comments,collab,files,docs,reading,feeds,wiki';
const rowsOf = (d, sel = '#view') => [...d.querySelectorAll(sel + ' .zler')];
const titles = (d, sel) => rowsOf(d, sel).map(a => a.querySelector('.zlen')?.textContent || '');
const spaceRows = d => [...d.querySelectorAll('#view .spov [data-spov], #view .wkspaces [data-wksp]')];

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, CA);
  const me = (await call('GET', '/api/state', null, CA)).me;
  const og = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id}, CA);
  const SP = 'org:' + og.id;
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'all'}, CA);
  const pg = async (space, p) => (await call('POST', '/api/wiki/pages', {space, path: p, body: 'Text of ' + p}, CA)).id;
  const P1 = await pg('private', 'Diary/Monday');
  await upload(CA, 'mine.txt', 'private');
  check((await call('POST', '/api/reading', {url: 'https://example.com/team', title: 'Team article', space: SP}, CA)).status < 300, 'a read-later entry of the organisation');
  const P2 = await pg(SP, 'Team/Process');

  // ================= Knowledge on a computer, "All workspaces": the list, no second list of the workspaces
  let w = await boot({user: 'alice', hash: 'wiki'}), d = w.document;
  check(await until(() => rowsOf(d).length >= 4), '#5352: Knowledge: "Recently edited" in the main area ' + titles(d));
  check(!spaceRows(d).length, '#5352: no second list of the workspaces next to the panel');
  check(d.querySelector('#side [data-wksp]'), '#5352: the panel keeps the workspaces');
  check(titles(d)[0] === 'Process' && rowsOf(d)[0].getAttribute('href') === '#wiki/' + P2, '#5352: newest first, a tap opens the page ' + titles(d));
  check(/Alpha/.test(rowsOf(d)[0].querySelector('.zlec')?.textContent || '') && /Alice/.test(rowsOf(d)[0].querySelector('.zlew')?.textContent || ''), '#5352: the chip of the workspace, who');
  check(rowsOf(d).some(a => a.getAttribute('href') === '#wiki/' + P1 && /Private/.test(a.textContent)), '#5352: the private page with its chip');
  check(rowsOf(d).some(a => /mine\.txt/.test(a.textContent) && /^#ablage\/\d+$/.test(a.getAttribute('href'))), '#5352: the file opens in the file store');
  check(rowsOf(d).some(a => /Team article/.test(a.textContent) && a.getAttribute('href') === '#reading/s/' + SP), '#5352: the read-later entry opens its workspace\'s list');
  check(!d.querySelector('#view .zlepin'), '#5352: no favourites: no "Pinned"');
  w.close();
  // pinned: a favourite page
  await call('PATCH', '/api/settings', {fav_items: JSON.stringify(['r:wiki:' + P1])}, CA);
  w = await boot({user: 'alice', hash: 'wiki'}); d = w.document;
  check(await until(() => d.querySelector('#view .zlepin .fv2-tile')), '#5352: a favourite page under "Pinned" above the list');
  w.close();
  await call('PATCH', '/api/settings', {fav_items: '[]'}, CA);
  // the panel hidden: the workspaces as chips on top
  w = await boot({user: 'alice', hash: 'wiki', ls: {'tasks.sideFold': 'true'}}); d = w.document;
  check(await until(() => rowsOf(d).length >= 4 && d.querySelectorAll('#view .zlechips [data-wksp]').length === 2), '#5352: panel hidden: chips of the workspaces on top');
  w.close();
  // a phone
  w = await boot({user: 'alice', hash: 'wiki', mobile: true}); d = w.document;
  check(await until(() => rowsOf(d).length >= 4 && d.querySelectorAll('#view .zlechips [data-wksp]').length === 2), '#5352: the phone: chips on top, the list below');
  w.close();

  // ================= Files and Reading
  w = await boot({user: 'alice', hash: 'ablage'}); d = w.document;
  check(await until(() => rowsOf(d).length >= 4) && !spaceRows(d).length, '#5352: Files: the list, no second list of the workspaces');
  w.close();
  w = await boot({user: 'alice', hash: 'ablage', mobile: true}); d = w.document;
  check(await until(() => rowsOf(d).length >= 4 && d.querySelectorAll('#view .zlechips [data-spov]').length === 4), '#5352: Files on a phone: the workspaces as chips');
  w.close();
  w = await boot({user: 'alice', hash: 'reading'}); d = w.document;
  check(await until(() => rowsOf(d).length >= 4 && d.querySelectorAll('#view .zlechips [data-spov]').length === 2), '#5352: Reading: its panel lists no workspaces, so the chips stay');
  w.close();

  // ================= Start: the block, 8 entries, "More"
  for (let i = 1; i <= 8; i++) await pg(SP, 'Many/Page ' + i);
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  check(await until(() => rowsOf(d, '#view .dc-recent').length === 8), '#5352: Start: the block "Recently edited" is on, 8 entries ' + rowsOf(d, '#view .dc-recent').length);
  check(titles(d, '#view .dc-recent')[0] === 'Page 8' && rowsOf(d, '#view .dc-recent')[0].querySelector('.zlec'), '#5352: Start: newest first, with the chip under "All"');
  check(d.querySelector('#view .dc-recent a.hpall')?.getAttribute('href') === '#wiki', '#5352: Start: "More" leads to the overview');
  w.close();
  await call('PATCH', '/api/settings', {workspace: 'private'}, CA);
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  check(await until(() => rowsOf(d, '#view .dc-recent').length === 2), '#5352: Start in Private: its two items (page, file)');
  check(!titles(d, '#view .dc-recent').some(t => /Page|Process/.test(t)) && !d.querySelector('#view .dc-recent .zlec'), '#5352: only Private, no chip ' + titles(d, '#view .dc-recent'));
  w.close();
  await call('PATCH', '/api/settings', {workspace: 'all', dashboard: JSON.stringify({hidden: ['recent']})}, CA);
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  check(await until(() => d.querySelector('#view .dc-today')) && !d.querySelector('#view .dc-recent'), '#5352: Start: hidden like every block');
  w.close();
  await call('PATCH', '/api/settings', {dashboard: '{}'}, CA);

  // ================= empty: an organisation without content
  const og2 = await call('POST', '/api/admin/orgs', {name: 'Beta', admin_id: me.id}, CA);
  const us = await call('POST', '/api/users', {username: 'erin', display_name: 'Erin', password: 'password123', email: 'erin@example.com', orgs: [og2.id]}, CA);
  check(us.status < 300, 'erin in Beta');
  const CE = await login('erin');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'all'}, CE);
  w = await boot({user: 'erin', hash: 'wiki'}); d = w.document;
  check(await until(() => d.querySelector('#view .zleempty [data-wk="new"]')), '#5352: empty: one sentence and "New page"');
  w.close();
  w = await boot({user: 'erin', hash: 'home'}); d = w.document;
  check(await until(() => /Recently edited: nothing/.test(d.querySelector('#view .dc-recent')?.textContent || '')), '#5352: Start empty: one slim line');
  w.close();

  // ================= a person without an organisation (freelancer-matrix: wiki)
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CA);
  check(fu.status < 300, 'frida');
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CF);
  await call('POST', '/api/wiki/pages', {space: 'private', path: 'Ideas', body: 'x'}, CF);
  w = await boot({user: 'frida', hash: 'home'}); d = w.document;
  check(await until(() => titles(d, '#view .dc-recent').includes('Ideas')) && !d.querySelector('#view .dc-recent .zlec'), 'P4: Start: her page, no chip');
  w.close();

  // ================= Firefox: the real layout at 320 / 460 / 840 / 1280 px
  const LAY = `(() => { const v = document.querySelector('#view'), o = document.querySelector('#view .zleov'), rs = [...document.querySelectorAll('#view .zler')];
    return {vw: innerWidth, view: v ? v.clientWidth : 0, ov: o ? Math.round(o.getBoundingClientRect().width) : 0, n: rs.length,
      hs: [...new Set(rs.map(a => Math.round(a.getBoundingClientRect().height)))], wide: rs.filter(a => a.getBoundingClientRect().right > innerWidth + 1 || a.scrollWidth > a.clientWidth + 1).length,
      chips: document.querySelectorAll('#view .zlechips [data-wksp], #view .zlechips [data-spov]').length}; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    const ready = async (expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    for (const vw of [320, 460, 840, 1280]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: 900}});
      await nav(B + '#wiki');
      check(await ready(`document.querySelectorAll('#view .zler').length >= 8`), `ff ${vw}: Knowledge: the list is up ` + await ev(`location.hash + ' ' + (document.querySelector('#view')?.innerHTML || '').replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ').slice(0, 300)`));
      await shot(`p2769d-wiki-${vw}.png`);
      const a = await ev(LAY);
      check(a.ov >= a.view - 64,  // the page margin only (was a narrow middle column, #5352)
        `ff ${vw}: the overview takes the width ${JSON.stringify(a)}`);
      check(a.hs.length === 1 && a.wide === 0, `ff ${vw}: one height per row, nothing wider than the screen ${JSON.stringify(a)}`);
      if (vw !== 840) check(vw > 840 ? a.chips === 0 : a.chips === 3,  // Private, Alpha, Beta
        `ff ${vw}: the workspaces as chips only without the panel ${JSON.stringify(a)}`);  // 840: panel or drawer, both right
      const ph = await ev(`(() => { const p = document.createElement('div'); p.className = 'zleph'; p.style.setProperty('--zlen', '3'); (document.querySelector('#view .zlesec') || document.body).appendChild(p); const h = p.getBoundingClientRect().height; p.remove(); return Math.round(h); })()`);
      check(Math.abs(ph - 3 * a.hs[0]) <= 2, `ff ${vw}: the placeholder is as high as its rows (no jump) ${ph} vs 3 x ${a.hs[0]}`);
      await nav(B + '#home');
      check(await ready(`document.querySelectorAll('#view .dc-recent .zler').length === 8`), `ff ${vw}: Start: the block with 8 entries`);
      const s = await ev(`(() => { const rs = [...document.querySelectorAll('#view .dc-recent .zler')]; return {hs: [...new Set(rs.map(a => Math.round(a.getBoundingClientRect().height)))], wide: rs.filter(a => a.getBoundingClientRect().right > innerWidth + 1).length}; })()`);
      check(s.hs.length === 1 && s.wide === 0, `ff ${vw}: Start: one height, nothing wider than the screen ${JSON.stringify(s)}`);
      await shot(`p2769d-start-${vw}.png`);
    }
  });

  console.log(`p2769_d_recent_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
