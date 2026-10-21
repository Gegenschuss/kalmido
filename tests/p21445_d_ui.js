// 2.144.5 UI tests, part D (phone), own container (start.sh), Firefox in a phone viewport (390x844), motion allowed:
// - #1560: the full-screen search leaves with an exit animation (class an-out, inert, then gone); opening it again while
//   it is leaving leaves exactly one search; with reduced motion it is removed at once (second Firefox)
// - #2011: the suggestions after "=" never cover the edited cell (below, or above when the keyboard leaves no room), the cell
//   editor ends at the visible edge, the side panel shows "Live again" right after "Freeze value" without a new tap
// freeze-free: no route; freelancer-matrix: sheets
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21445D_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Nordwind', lang: 'en', modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,sheets'});
  const sh = await call(CA, 'POST', '/api/sheets', {title: 'Phone sheet'});
  check(sh.http === 201, 'a table ' + sh.http);
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  const phone = async (cmd, ctx) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});

  // ---- #1560 with motion
  const mk = (tag, prefs) => require('./ff')({tag, check, shots: 'P21445D_SHOTS', prefs});
  await mk('p21445_d_a', [['ui.prefersReducedMotion', 0]])(async ({cmd, ev, ctx, nav}) => {
    await phone(cmd, ctx);
    await nav(B); await signIn(ev); await nav(B + '#sheets/' + sh.id);
    check(await ready(ev, `typeof SHV !== 'undefined' && SHV.sh?.id === ${sh.id} && isMobile() && an_on()`, 80), 'the table opens on the phone with motion');
    await ev(`(() => { openPalette(); return 1; })()`);
    check(await ev(`!!document.querySelector('.palette') && !document.querySelector('.palette.an-out')`), '#1560: the search is open');
    await ev(`(() => { closePalette(); return 1; })()`);
    const mid = await ev(`(() => { const p = document.querySelector('.palette'); return !!p && p.classList.contains('an-out') && p.hasAttribute('inert') && !f8d_open(); })()`);
    check(mid, '#1560: while closing the search is still there, marked as leaving and inert');
    check(await ready(ev, `!document.querySelector('.palette')`, 12), '#1560: after the exit the search is gone');
    await ev(`(() => { openPalette(); closePalette(); openPalette(); return 1; })()`);
    check(await ev(`document.querySelectorAll('.palette').length === 1 && !document.querySelector('.palette.an-out')`), '#1560: opening again while it is leaving leaves one open search');
    await sleep(450);
    check(await ev(`document.querySelectorAll('.palette').length === 1 && !document.querySelector('.palette.an-out')`), '#1560: the new search survives the old exit timer');
    await ev(`(() => { closePalette(true); return 1; })()`);
    check(await ev(`!document.querySelector('.palette')`), '#1560: closePalette(true) removes at once');
  }, true);

  // ---- #1560 reduced motion + #2011
  await mk('p21445_d_b', [['ui.prefersReducedMotion', 1]])(async ({cmd, ev, ctx, nav}) => {
    await phone(cmd, ctx);
    await nav(B); await signIn(ev); await nav(B + '#sheets/' + sh.id);
    check(await ready(ev, `typeof SHV !== 'undefined' && SHV.sh?.id === ${sh.id} && isMobile()`, 80), 'the table opens (reduced motion)');
    await ev(`(() => { openPalette(); closePalette(); return 1; })()`);
    check(await ev(`!document.querySelector('.palette')`), '#1560: with reduced motion the search is removed at once');

    // the editor of the last column ends at the visible edge
    const geo = await ev(`(async () => {
      const sh = SHV.sh, last = sh.columns[sh.columns.length - 1], row = sh.rows[sh.rows.length - 1] || sh.rows[0];
      await shvPut([{row_id: sh.rows[0].id, col_id: sh.columns[0].id, raw: '5'}, {row_id: row.id, col_id: sh.columns[0].id, raw: '=1+2'}]);
      const sc = document.getElementById('shv-scroll'); sc.scrollLeft = sc.scrollWidth;
      shvSelect(row.id, last.id); shvEditStart(null);
      await new Promise(r => setTimeout(r, 200));
      const i = document.getElementById('shv-ed'); if (!i) return null;
      const b = i.getBoundingClientRect(); return {right: b.right, vw: window.innerWidth, w: b.width, cols: sh.columns.length};
    })()`);
    check(geo && geo.right <= geo.vw + 1 && geo.w >= 80, '#2011: the cell editor ends inside the screen ' + JSON.stringify(geo));

    // suggestions: beside the field, below with room, above (not over the field) when the keyboard leaves none
    const sug = await ev(`(async () => {
      const inp = document.getElementById('shv-ed'); inp.value = '='; 
      const items = Array.from({length: 14}, (_, i) => ({token: 'var' + i, label: 'Variable ' + i, kind: 'variable'}));
      const place = () => { SHV.ac = {items, i: 0, from: 1, to: 1, inp}; shvAcDraw(); const b = document.getElementById('shv-ac').getBoundingClientRect(), f = inp.getBoundingClientRect(); return {bt: b.top, bb: b.bottom, ft: f.top, fb: f.bottom}; };
      const a = place();
      const real = Object.getOwnPropertyDescriptor(window, 'visualViewport');
      const f = inp.getBoundingClientRect();
      Object.defineProperty(window, 'visualViewport', {configurable: true, value: {offsetTop: 0, height: Math.round(f.bottom + 30), width: 390}});  // a keyboard right below the field
      const b = place();
      if (real) Object.defineProperty(window, 'visualViewport', real); else delete window.visualViewport;
      return {a, b};
    })()`);
    const noOver = x => x.bb <= x.ft + 0.5 || x.bt >= x.fb - 0.5;
    check(sug && noOver(sug.a) && noOver(sug.b), '#2011: the suggestions never cover the field ' + JSON.stringify(sug));
    check(sug && sug.b.bb <= sug.b.ft + 0.5, '#2011: no room below (keyboard): the list sits above the field ' + JSON.stringify(sug?.b));
    await ev(`(() => { shvAcClose(); shvEditEnd(false); return 1; })()`);

    // freeze: the panel changes the button at once
    const fr = await ev(`(async () => {
      const sh = SHV.sh, row = sh.rows[sh.rows.length - 1] || sh.rows[0];
      shvSelect(row.id, sh.columns[0].id);
      const side = document.getElementById('shv-side');
      const btn = () => side.querySelector('[data-shv="freeze"]');
      let b = btn(); if (!b) return {err: 'no freeze button'};
      const before = b.textContent.trim(); b.focus(); b.click();
      for (let i = 0; i < 40; i++) { await new Promise(r => setTimeout(r, 150)); if (/Live again/.test(btn()?.textContent || '')) break; }
      return {before, after: btn()?.textContent.trim()};
    })()`);
    check(fr && /Freeze/.test(fr.before || '') && /Live again/.test(fr.after || ''), '#2011: after "Freeze value" the panel offers "Live again" at once ' + JSON.stringify(fr));
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
