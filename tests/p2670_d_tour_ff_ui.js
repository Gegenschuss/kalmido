// 2.670.0 (#4576) UI test (Firefox, real layout): the short introductions of the areas, about seven steps each
// kalmido-suite: fresh
// freelancer-matrix: onboarding (frida has no organisation; alice is the admin of one, "All workspaces")
// For every area (incl. Notes and Chat), on a computer (1280 x 800, mouse) and a phone (390 x 844, touch), as it opens for the
// first time (empty): the introduction has 5-8 steps; each step with a target rings a visible element of the open area when the
// real tour shows it (tourStart / tourGo, the ring is on the screen and lies on the target); the phone gets its own targets and
// texts (no step points into the closed drawer); no text of the film industry without that industry. With P2670D_SHOTS: a
// picture of every step that has a target.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2670_d_tour_ff_ui', check, shots: 'P2670D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEATS = 'cal,comments,collab,office,clients,contacts,time,pomo,review,stats,home,contracts,care,health,travel,family,budget,reading,feeds,files,docs,wiki,sheets,habits,agents';
const AREAS = ['cal', 'office', 'time', 'review', 'life', 'reading', 'ablage', 'wiki', 'sheets', 'habits', 'agents', 'notes', 'team'];
const FILM = /\b(film|video|shoot|camera crew|dreh)/i;

// the step shown now: its target (the step's own selector), the ring, the card - all as the user sees them
const SHOWN = `(() => { const el = document.querySelector('.tour'); if (!el) return null; const st = TOUR.steps[TOUR.i];
  const ring = el.querySelector('.tring'), card = el.querySelector('.tcard'), rr = ring.getBoundingClientRect(), cr = card.getBoundingClientRect();
  const on = r => r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
  const tgt = st.sel ? tourModEl(st.sel) : null, tr0 = tgt && tgt.getBoundingClientRect();
  const inRing = !!tr0 && tr0.left >= rr.left - 1 && tr0.right <= rr.right + 1 && tr0.top >= rr.top - 1 && tr0.bottom <= rr.bottom + 1;
  return JSON.stringify({id: st.id, sel: st.sel || '', n: TOUR.steps.length, ring: !ring.classList.contains('none') && on(rr), tgt: !!tr0 && on(tr0), inRing,
    card: on(cr), h3: card.querySelector('h3')?.textContent || '', p: card.querySelector('p')?.textContent || '', step: el.dataset.step}); })()`;

async function walk({ev, nav, idle, shot}, who, w) {
  for (const id of AREAS) {
    await nav(B + 'static/icon.svg'); await nav(B + '#' + id);
    const up = await ev(`new Promise(res => { const t0 = Date.now(), f = () => { if (typeof sbb_area === 'function' && sbb_area() === ${JSON.stringify(id)} && document.querySelector('#view')?.children.length) res(true); else if (Date.now() - t0 > 15000) res(false); else setTimeout(f, 100); }; f(); })`);
    check(up, `${who} ${w} ${id}: the area opens`);
    await idle().catch(() => {});
    check(await ev(`loadModule('tourmods').then(() => true, () => false)`), `${who} ${w} ${id}: tourmods loads`);
    await ev(`(tourStart(${JSON.stringify(id)}), true)`);
    const first = await ev(`new Promise(res => { const t0 = Date.now(), f = () => { if (document.querySelector('.tour .tcard h3')) res(true); else if (Date.now() - t0 > 5000) res(false); else setTimeout(f, 50); }; f(); })`);
    check(first, `${who} ${w} ${id}: the introduction shows`);
    const n = await ev('TOUR.steps.length');
    check(n >= 5 && n <= 8, `${who} ${w} ${id}: 5-8 steps (${n}): ` + await ev('TOUR.steps.map(s => s.id).join(",")'));
    check(await ev('new Set(TOUR.steps.map(s => s.id)).size === TOUR.steps.length'), `${who} ${w} ${id}: each step once`);
    for (let i = 0; i < n; i++) {
      await ev(`(tourGo(${i}), true)`); await sleep(40);
      const s = JSON.parse(await ev(SHOWN) || 'null');
      if (!s) { check(false, `${who} ${w} ${id} step ${i}: no card`); break; }
      check(s.card && s.h3 && s.p && s.step === s.id, `${who} ${w} ${id} ${s.id}: the card with title and text on the screen`);
      check(!FILM.test(s.h3 + ' ' + s.p), `${who} ${w} ${id} ${s.id}: no film text without that industry: ${s.h3} / ${s.p}`);
      if (s.sel) {
        check(s.tgt && s.ring && s.inRing, `${who} ${w} ${id} ${s.id}: the ring lies on a visible target (${s.sel}) ` + JSON.stringify(s));
        if (/\.sbbtn|#side\b/.test(s.sel) && w < 600) check(false, `${who} ${w} ${id} ${s.id}: a phone step points into the drawer (${s.sel})`);
        await shot(`p2670d-${who}-${w}-${id}-${s.id}.png`);
      }
    }
    await ev('(tourEnd(true), true)'); await sleep(100);
  }
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  check((await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', tours_more: '0', features: FEATS})).http < 300, 'alice: all modules on');
  const u = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(u.http === 200 || u.http === 201, 'the freelancer ' + u.http);
  CK = await login('frida');
  check((await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', tours_more: '0', features: FEATS})).http < 300, 'frida: all modules on');
  check(!((await call('GET', '/api/state')).orgs || []).length, 'frida: a person without an organisation');
  for (const who of ['frida', 'alice']) {
    for (const [touch, w, h] of [[false, 1280, 800], [true, 390, 844]]) {
      await firefox(async o => {
        const {cmd, ev, ctx, nav} = o;
        await nav(B + 'static/icon.svg');
        await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
        check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${who}', password: 'password123'})}).then(r => r.status)`) === 200, `${who} ${w}: login`);
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
        await walk(o, who, w);
      }, touch);
    }
  }
  const fails = F.length; console.log(`p2670_d_tour_ff_ui: ${ok} ok, ${fails} failed`); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
