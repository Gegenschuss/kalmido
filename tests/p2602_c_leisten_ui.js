// 2.602.0 C (#4817) UI test, own container (start.sh, isolated test database), Firefox with a mouse. Invented data only.
// kalmido-suite:
// The side lists, one way: on a computer the note list sits in the shared panel #side (like the folders of Knowledge), with
// its button "Hide the panel" (.sbbhide) and the panel's width; the page shows the open note alone. The lists that stay in
// the page (file store spaces, team chat conversations, contacts / clients, notes without the panel) share ONE width, the
// token --w-leiste (15rem, at least 14rem). A phone keeps list and note one after the other.
// freelancer-matrix: Seitenleisten (alice has no organisation; the panel does not depend on the workspace)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2602_c_leisten_ui', check, shots: 'P2602C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['contacts']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,contacts'});
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'alice: no organisation (person on her own)');
  const L = (await call('POST', '/api/lists', {name: 'Shoot plan', kind: 'project'})).id;
  const N1 = (await call('POST', `/api/lists/${L}/notes`, {title: 'Locations', body: 'harbour, old mill'})).id;
  const N2 = (await call('POST', `/api/lists/${L}/notes`, {title: 'Crew', body: 'camera, sound'})).id;
  check(L && N1 && N2, `setup: a project with two notes ${L} ${N1} ${N2}`);
  const bk = await call('POST', '/api/books', {name: 'Customers'});
  for (const [g, f] of [['Petra', 'Buyer'], ['Jonas', 'Light']]) await call('POST', '/api/contacts', {book_id: bk.id, given: g, family: f, emails: [{value: `${g.toLowerCase()}@example.com`, type: ['work']}]});

  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    const R = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e || !e.getClientRects().length) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), r: Math.round(b.right), w: Math.round(b.width)}; })()`;
    const REM = `parseFloat(getComputedStyle(document.documentElement).fontSize)`;

    // ================= a computer: the note list in the panel
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '?w=1440#notes/' + L);
    check(await until(`!!S.booted && document.querySelectorAll('#side .ntpan a.ntcard').length === 2`), '1440: the two notes are in the panel #side');
    check(await ev(`!document.querySelector('#view .ntlist') && !document.querySelector('#view a.ntcard') && !document.querySelector('#app').classList.contains('sbb-nopan')`), '1440: no list in the page, the panel is shown (Notes left SBB_NOPANEL)');
    check(await ev(`!!document.querySelector('#view .ntpick .nempty')`), '1440: no note open: the page shows the hint');
    check(await ev(`!!document.querySelector('#side #nt-q') && !!document.querySelector('#side [data-act="nt-new"]')`), '1440: search and "New note" in the panel');
    { const p = await ev(`(() => { const s = ${R('#side')}; return s ? {...s, rem: ${REM}, sw: getComputedStyle(document.documentElement).getPropertyValue('--sideW').trim()} : null; })()`);
      check(p && Math.abs(p.w - 15 * p.rem) <= 2, '1440: the list takes the panel width (15rem) ' + JSON.stringify(p)); }
    await ev(`(() => { document.querySelector('#side a.ntcard[href="#note/${N1}"]').click(); return 1; })()`);
    check(await until(`location.hash === '#note/${N1}' && !!document.querySelector('#view .ntedit #nt-title') && document.querySelector('#side a.ntcard.on')?.getAttribute('href') === '#note/${N1}'`), '1440: a card opens its note in the page, the card stays marked in the panel');
    { const x = await ev(`(() => { const v = ${R('#view .ntview')}, e = ${R('#view .ntedit')}; return v && e ? {v, e} : null; })()`);
      check(x && Math.abs((x.e.l - x.v.l) - (x.v.r - x.e.r)) <= 2, '1440: the open note stands alone in the page (centred in its reading width, no list column beside it) ' + JSON.stringify(x)); }
    // the search in the panel keeps its focus while typing
    await ev(`(() => { const q = document.querySelector('#side #nt-q'); q.focus(); q.value = 'crew'; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await until(`document.querySelectorAll('#side .ntpan a.ntcard').length === 1 && document.activeElement?.id === 'nt-q'`), '1440: the panel search filters the cards, the field keeps the focus');
    await ev(`(() => { const q = document.querySelector('#side #nt-q'); q.value = ''; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await shot('p2602c-notes-1440.png');
    // "Hide the panel": the list goes, the page takes the room; the open area's icon brings it back
    await ev(`(() => { document.querySelector('#side .sbbhide').click(); return 1; })()`);
    check(await until(`(() => { const v = document.querySelector('#view').getBoundingClientRect(), r = document.querySelector('#srail').getBoundingClientRect(); return !!LS.get('sideFold', false) && v.left <= r.right + 2; })()`), '1440: "Hide the panel" hides the note list, the page starts at the bar');
    await ev(`go('notes/${L}')`);
    check(await until(`!!document.querySelector('#view .ntpick [data-act="sbb-panel"]') && !!document.querySelector('#view .ntpick [data-act="nt-new"]')`), '1440: panel hidden, no note open: the hint offers the list back and "New note"');
    await ev(`(() => { document.querySelector('#srail .srb.on[data-sbb="notes"]').click(); return 1; })()`);
    check(await until(`!LS.get('sideFold', false) && document.querySelectorAll('#side .ntpan a.ntcard').length === 2 && !document.querySelector('#view .ntpick [data-act="sbb-panel"]')`), '1440: the area icon brings the panel with the list back');
    // the overview of all notes: its list (search, project filter) in the panel too
    await nav(B + '?w=1440#notes');
    check(await until(`!!document.querySelector('#side .ntpan .sbnlist #sbn-q') && document.querySelectorAll('#side .sbncard').length === 2 && !document.querySelector('#view .sbnall')`), '1440: #notes: the overview list in the panel');

    // ================= one width for the lists in the page: --w-leiste
    { const t = await ev(`getComputedStyle(document.documentElement).getPropertyValue('--w-leiste').trim() + '|' + getComputedStyle(document.documentElement).getPropertyValue('--w-leiste-min').trim()`);
      check(t === '15rem|14rem', '--w-leiste 15rem, --w-leiste-min 14rem ' + t); }
    // the grids of the lists that stay in the page, measured on a sample of each in the page (its first column)
    const col = cls => ev(`(() => { const v = document.querySelector('#view'), d = document.createElement('div'); d.className = ${JSON.stringify(cls)}; d.style.width = '60rem'; d.innerHTML = '<div></div><div></div>'; v.appendChild(d); const w = d.firstChild.getBoundingClientRect().width / ${REM}; d.remove(); return Math.round(w * 10) / 10; })()`);
    // 2.743.0 (#4930): contacts / clients take their columns from the building block .lsd2 (was .ctcols)
    for (const cls of ['abview', 'tcview', 'tcview inthread', 'ntview open', 'lsd2']) {
      const w = await col(cls);
      check(Math.abs(w - 15) <= .1, `--w-leiste: the list column of .${cls.replace(' ', '.')} is 15rem (${w})`);
    }
    await nav(B + '?w=1440#contacts');
    check(await until(`!!S.booted && !!document.querySelector('#view .ctrow[data-ctopen]')`), '1440: the contacts show');
    { const c = await ev(`(() => { const l = ${R('#view .ctlistw')}; return l ? {...l, rem: ${REM}} : null; })()`);
      check(c && Math.abs(c.w - 15 * c.rem) <= 2, '1440: the contact list is --w-leiste wide ' + JSON.stringify(c)); }

    // ================= a phone: unchanged, list and note one after the other in the page
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '?w=390#notes/' + L);
    check(await until(`!!S.booted && document.querySelectorAll('#view .ntlist a.ntcard').length === 2`), '390: the list of notes is in the page');
    check(await ev(`!document.querySelector('#side .ntpan')`), '390: no note list in the drawer');
    await ev(`(() => { document.querySelector('#view a.ntcard[href="#note/${N2}"]').click(); return 1; })()`);
    check(await until(`location.hash === '#note/${N2}' && !!document.querySelector('#view .ntedit #nt-title') && !document.querySelector('#view .ntlist')?.getClientRects().length`), '390: the note alone, the list hidden as before');
    await shot('p2602c-notes-390.png');
  }, false);

  console.log(`p2602_c_leisten_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
