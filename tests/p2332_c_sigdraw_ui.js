// kalmido-suite: fresh
// 2.332.0 C (#3301) UI tests: draw the signature picture (Office > Correspondence > Signature) and use it when approving an
// entertainment receipt. Own container (start.sh), Firefox (desktop with the mouse, phone width with a finger).
// - "Draw" opens the one drawing field of 2.357 (canvas.lt-pad, touch-action none, drawn at a fixed 600 x 200 so a phone gets
//   enough pixels); Save without a stroke says what is missing; Clear (padclr) empties it
// - strokes with the mouse (WebDriver in Firefox has no pen pointer), Save: the profile has a PNG with transparent corners, cut to the strokes, below 300 KB
// - the approve dialog of a receipt offers "With my signature" (on) with the note that it is no electronic signature;
//   approving keeps the choice (sign_image 1)
// - on a phone a finger draws (touch pointer), the picture is saved through the same route
// Invented names only; the strokes are drawn by the test.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2332_c_sigdraw_ui', check, shots: 'P2332C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2332C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const y = String(new Date().getFullYear());
  const meal = await call(CA, 'POST', '/api/office/meals', {date: `${y}-01-10`, place_name: 'Bistro Beispiel', place_address: 'Hauptstraße 5, 12345 Musterstadt',
    occasion: 'Planning of the trade fair stand', host: {id: me.id}, guests: [{name: 'Otto Beispiel', extra: 'Example AG'}], amounts: [{kind: 'food', rate: 19, gross: 59.5}]});
  check(meal.http === 201, 'a draft receipt ' + meal.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const getJ = url => `fetch('${url}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  const clk = sel => `(() => { const x = document.querySelector('${sel}'); if (!x) return 0; x.click(); return 1; })()`;
  const pad = `(() => { const c = document.querySelector('.modal canvas.lt-pad'); if (!c) return null; const r = c.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height, iw: c.clientWidth, cw: c.width, ta: getComputedStyle(c).touchAction, dpr: window.devicePixelRatio}; })()`;
  // the saved picture: PNG, its size, the alpha of the corners and whether any pixel is drawn
  const pic = `${getJ('/api/office/letters/profile')}.then(p => new Promise(res => { if (!p.image) return res({has: false}); const im = new Image(); im.onload = () => {
      const c = document.createElement('canvas'); c.width = im.width; c.height = im.height; const x = c.getContext('2d'); x.drawImage(im, 0, 0); const d = x.getImageData(0, 0, im.width, im.height).data;
      let ink = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) ink++;
      res({has: p.has_image, png: p.image.startsWith('data:image/png;base64,'), bytes: Math.floor((p.image.length - 22) * 3 / 4), w: im.width, h: im.height, corner: d[3], ink}); };
    im.onerror = () => res({has: p.has_image, bad: true}); im.src = p.image; }))`;
  const openDraw = async ev => {
    await ev(clk('[data-lt="profile"]'));
    check(await ready(ev, `!!document.querySelector('.modal [data-m="draw"]')`), 'the signature dialog offers "Draw"');
    await ev(clk('.modal [data-m="draw"]'));
    check(await ready(ev, `!!document.querySelector('.modal canvas.lt-pad') && !document.querySelector('.modal [data-m="padclr"]').hidden`), 'Draw: a canvas and "Clear"');
    return ev(pad);
  };
  const saved = async (ev, what) => {
    await ev(clk('.modal [data-m="save"]'));
    check(await ready(ev, `!document.querySelector('.modal') && /Saved/.test(document.querySelector('#toast')?.textContent || '')`, 60), what + ': saved (toast)');
    return ready(ev, `${getJ('/api/office/letters/profile')}.then(p => p.has_image)`);
  };

  // ================= desktop: the mouse
  await firefox(async ({cmd, ev, ctx, nav, shot, drag}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/letters');
    check(await ready(ev, `!!document.querySelector('[data-lt="profile"]')`, 80), 'the correspondence with the signature button');
    let p = await openDraw(ev);
    check(p && p.ta === 'none', 'the canvas does not scroll on touch (touch-action none) ' + JSON.stringify(p));
    check(p && p.cw >= p.iw && p.cw === 600, 'the canvas has at least one pixel per CSS pixel ' + JSON.stringify(p));
    await ev(clk('.modal [data-m="save"]'));
    check(await ready(ev, `/Please draw your signature first/.test(document.querySelector('.modal .aerr')?.textContent || '')`), 'Save without a stroke: "Please draw your signature first."');
    await drag(p.x + 30, p.y + 40, 120, 30);
    await ev(clk('.modal [data-m="padclr"]'));
    await ev(clk('.modal [data-m="save"]'));
    check(await ready(ev, `!!document.querySelector('.modal') && /Please draw your signature first/.test(document.querySelector('.modal .aerr')?.textContent || '')`), 'Clear empties the field');
    await drag(p.x + 30, p.y + 50, 140, 25, 'mouse');
    await drag(p.x + 60, p.y + 30, 90, 50, 'mouse');  // Firefox's WebDriver has no pen pointer; pen = the same pointer events
    await shot('p2332-c-draw.png');
    check(await saved(ev, 'mouse'), 'the profile has the drawn picture');
    const s = await ev(pic);
    check(s.has && s.png && !s.bad, 'saved as PNG ' + JSON.stringify(s));
    check(s.corner === 0 && s.ink > 20, 'transparent background, the strokes drawn ' + JSON.stringify(s));
    check(s.w < p.cw && s.h < p.cw && s.w > 20, 'cut to the strokes (smaller than the canvas) ' + JSON.stringify(s));
    check(s.bytes < 300 * 1024, 'below 300 KB ' + s.bytes);
    // ================= the approve dialog of a receipt
    await nav(B + '#office/meals');
    check(await ready(ev, `typeof BW === 'object' && (BW.data || (BW.loading || bw_load(), false)) && BW.data.my_sig === 1`, 80), 'the receipts know the person has a picture (my_sig)');
    await ev(`(() => { bw_modal(BW.data.meals.find(m => m.id === ${meal.id})); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #bw-sig') && document.querySelector('.modal #bw-sig').checked`), 'the approve dialog: "With my signature", on');
    check(await ev(`/not an electronic signature/.test(document.querySelector('.modal').textContent)`), 'the note: no electronic signature, ask the tax adviser');
    await shot('p2332-c-approve.png');
    await ev(clk('.modal [data-bwm="approve"]'));
    check(await ready(ev, `${getJ('/api/office/meals/' + meal.id)}.then(m => m.status === 'approved' && m.sign_image === 1)`, 60), 'approved with the picture (sign_image 1)');
  });

  // ================= phone: a finger
  await call(CA, 'DELETE', '/api/office/letters/profile/image');
  await firefox(async ({cmd, ev, ctx, nav, shot, drag}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/letters');
    check(await ready(ev, `!!document.querySelector('[data-lt="profile"]')`, 80), 'phone: the signature button');
    const p = await openDraw(ev);
    check(p && p.w > 150 && p.x >= 0 && p.x + p.w <= 391, 'phone: the canvas fits the screen ' + JSON.stringify(p));
    await drag(p.x + 20, p.y + 40, Math.min(200, p.w - 40), 30, 'touch');
    await shot('p2332-c-touch.png');
    check(await saved(ev, 'finger'), 'phone: the finger-drawn picture saved');
    const s = await ev(pic);
    check(s.png && s.corner === 0 && s.ink > 10, 'phone: a transparent PNG with the stroke ' + JSON.stringify(s));
  }, true);

  console.log(`p2332_c_sigdraw_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
