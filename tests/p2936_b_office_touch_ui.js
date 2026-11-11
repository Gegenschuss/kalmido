// 2.936.0 UI test, part B (#5457, office.css tidy-up): the office with a finger. Own container (start.sh, mode workspaces),
// kalmido-suite: fresh
// Firefox with touch. Invented companies and figures only. Template: job/3930 (p2894_b_office_touch_ui.js), on today's main.
// - phone 360 px: the office shows its content (a quotation by its title), opens it and goes back; no sideways overflow
// - on touch the area chip of the office head and "All figures" have a 44 px hit area (elementFromPoint 21.5 px above, below,
//   left and right of the middle: the ::after area counts, the looks stay small)
// - "Change number": on a phone it waits in "…" (#5448) with a full-size menu row; on a touch tablet (768 px) the pen in the
//   head has the 44 px hit area
// - the receipts' tool row (#5453) keeps its 44 px buttons on a phone
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2936_b_office_touch_ui', check, shots: 'P2936B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2936B_NOSTART !== '1' && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';

(async () => {
  for (let i = 0; i < 120 && !(await fetch(B + 'sw.js').catch(() => null))?.ok; i++) await sleep(250);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Gegenlicht Muster GbR', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  check((await call(CA, 'PUT', '/api/office/settings', {pack: 'DE'})).http === 200, 'the office country (no country card on top)');
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Example Ltd'});
  const d1 = await call(CA, 'POST', '/api/office/docs', {kind: 'offer', client_id: cl.id, project_title: 'Harbour film', items: [{title: 'Day 1', qty: 1, rate: 100}]});
  check(d1.id, 'setup: a quotation ' + JSON.stringify(d1).slice(0, 200));

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  // the element answers 21.5 px above, below, left and right of its middle (= a 43+ px hit area both ways), its look may stay smaller
  const reach = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return 'missing'; e.scrollIntoView({block: 'center'});
    const r = e.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    const hit = (dx, dy) => { const t = document.elementFromPoint(x + dx, y + dy); return !!t && (t === e || e.contains(t)); };
    const miss = [[0, -21.5], [0, 21.5], [-21.5, 0], [21.5, 0]].filter(([dx, dy]) => !hit(dx, dy)).map(([dx, dy]) => dx + '/' + dy);
    return miss.length ? 'small ' + Math.round(r.width) + 'x' + Math.round(r.height) + 'px, misses at ' + miss.join(' ') : 'ok'; })()`;
  const noOverflow = `document.scrollingElement.scrollWidth <= innerWidth`;
  const offerRow = `[...document.querySelectorAll('.office .ofcrow, .office .ofdrow')].find(r => r.textContent.includes('Harbour film'))`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev, 'alice') === 200, 'sign in');

    // the office list: the quotation by its title, the area chip in the head (alice has an organisation: two offices)
    await nav(B + '#office/offers');
    check(await ready(ev, `!!${offerRow}`, 80), '#5457: the office lists the quotation with its title');
    check(await ready(ev, `!!document.querySelector('.office .ofchead button.ofcws')`, 40), '#5457: the office head has the area chip as a button');
    check(await ev(noOverflow), '#5457: office list: no sideways overflow');
    const chip = await ev(reach('.office .ofchead button.ofcws'));
    check(chip === 'ok', '#5457: touch: the area chip has a 44 px hit area (' + chip + ')');
    await shot('p2936b-touch-office-list.png');

    // in: the quotation opens; "Change number" in "…" is a full menu row; back: the list again
    await ev(`(() => { ${offerRow}.click(); return 1; })()`);
    check(await ready(ev, `/^#office\\/offers\\/\\d+/.test(location.hash) && !!document.querySelector('.ofdhead [data-ofd="more"]')`, 60), '#5457: a tap opens the quotation ' + await ev('location.hash'));
    check(await ready(ev, `[...document.querySelectorAll('textarea, input')].some(i => i.value === 'Harbour film')`, 20), '#5457: the open quotation shows its title');
    check(await ev(noOverflow), '#5457: quotation: no sideways overflow');
    await ev(`(() => { document.querySelector('.ofdhead [data-ofd="more"]').click(); return 1; })()`);
    check(await ready(ev, `(() => { const b = [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Change number/.test(b.textContent)); return !!b && b.getBoundingClientRect().height >= 43; })()`, 40), '#5457 phone: "Change number" is a 44 px row in "…"');
    await ev(`(() => { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`);
    await shot('p2936b-touch-office-offer.png');
    await ev(`(() => { history.back(); return 1; })()`);
    check(await ready(ev, `/^#office\\/offers$/.test(location.hash) && !!${offerRow}`, 60), '#5457: back: the list is there again ' + await ev('location.hash'));

    // the receipts: the buttons of the tool row keep the toolbar height (44 px on a phone)
    await nav(B + '#office/receipts');
    if (await ready(ev, `!!document.querySelector('.rcl-tools .btn')`, 60)) {
      const hs = await ev(`[...document.querySelectorAll('.rcl-tools .btn')].map(b => b.getBoundingClientRect()).filter(r => r.width > 0).map(r => Math.round(r.height))`);
      check(hs.length && hs.every(h => h >= 43), '#5457: receipts: the tool row buttons stay 44 px tall (' + JSON.stringify(hs) + ')');
    }
    check(await ev(noOverflow), '#5457: receipts: no sideways overflow');

    // home: "All figures" under the figures card
    await nav(B + '#home');
    check(await ready(ev, `!!document.querySelector('.kptl+.linkbtn')`, 80), '#5457: home: the figures block shows "All figures"');
    const all = await ev(reach('.kptl+.linkbtn'));
    check(all === 'ok', '#5457: touch: "All figures" has a 44 px hit area (' + all + ')');
    check(await ev(noOverflow), '#5457: home: no sideways overflow');

    // a touch tablet: the head keeps the "Change number" pen, its hit area is 44 px
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 768, height: 1024}});
    await nav(B + '#office/offers/' + d1.id);
    check(await ready(ev, `(() => { const e = document.querySelector('.ofdhead .onumpen'); return !!e && e.getBoundingClientRect().width > 0; })()`, 60), '#5457 tablet: the quotation head shows the number pen');
    const pen = await ev(reach('.ofdhead .onumpen'));
    check(pen === 'ok', '#5457: touch: the "Change number" pen has a 44 px hit area (' + pen + ')');
    await shot('p2936b-touch-tablet-offer.png');
  }, true);

  console.log(`p2936_b_office_touch_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
