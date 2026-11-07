// 2.653.0 part B UI tests (#5087), Firefox, fresh DB: the finger switch isTouchUi() and the device line in Settings > Help.
// kalmido-suite: fresh
// Firefox with touch (ff.js touch=true: coarse pointer, no hover, touch events) at a phone (390x844), a tablet in portrait
// (840x1180) and turned (1180x840); Firefox with a mouse at 1280x800:
// - isTouchUi() is true on touch at every width, false with the mouse; isMobile() is true only at 390 (layout by space,
//   unchanged); isTouch() keeps its old answer (narrow or no hover)
// - Settings > Help > About shows one line "This device" with the window size and both switches; turning the device
//   (a new viewport while the settings are open) updates the size in the line
// Firefox headless: pointer:coarse and hover:none come from ui.primaryPointerCapabilities (as in the audit #3357 probe);
// navigator.maxTouchPoints stays 0 there, so the switch only reads the media queries (as on the devices).
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2653_b_touchui', check, shots: 'P2653B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const ENV = `JSON.stringify({ui: isTouchUi(), mob: isMobile(), touch: isTouch(), coarse: matchMedia('(pointer:coarse)').matches, hoverNone: matchMedia('(hover:none)').matches, w: innerWidth})`;
const LINE = `(() => { const e = document.getElementById('s-aboutdev'); if (!e) return ''; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 ? e.textContent : 'hidden:' + e.textContent; })()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Website'})).id;
  await call('POST', '/api/tasks', {title: 'Cut trailer', list_id: L});
  check(L, 'seed');

  const session = async (o, sizes, mouse) => {
    const {cmd, ev, ctx, nav, shot} = o;
    const until = async (expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(150); } return false; };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    for (const [wd, ht] of sizes) {
      const tag = `${mouse ? 'mouse' : 'touch'} ${wd}x${ht}`;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
      await nav(B + '#l/' + L);
      check(await until(`document.querySelectorAll('.trow').length >= 1 && innerWidth === ${wd}`), tag + ': the list shows the task');
      const e = JSON.parse(await ev(ENV));
      if (mouse) {
        check(e.ui === false && e.coarse === false && e.hoverNone === false, `${tag}: isTouchUi() false with the mouse ${JSON.stringify(e)}`);
        check(e.mob === false && e.touch === false, `${tag}: isMobile() and isTouch() false on the desktop ${JSON.stringify(e)}`);
      } else {
        check(e.ui === true, `${tag}: isTouchUi() true with a finger ${JSON.stringify(e)}`);
        check(e.mob === (wd <= 767), `${tag}: isMobile() is the width only (true only on the phone) ${JSON.stringify(e)}`);
        check(e.touch === true, `${tag}: isTouch() unchanged (narrow or no hover) ${JSON.stringify(e)}`);
      }
      await ev(`(() => { settingsModal('help'); return 1; })()`);
      check(await until(`!!document.getElementById('s-aboutdev')`), tag + ': Settings > Help has the device line');
      await ev(`(() => { document.getElementById('s-aboutdev')?.scrollIntoView({block: 'center'}); return 1; })()`);
      const txt = await ev(LINE);
      check(new RegExp(`^${wd} × ${ht} px · pixel ratio [\\d.]+ · pointer ${mouse ? 'fine' : 'coarse'} · hover ${mouse ? 'yes' : 'no'} · phone layout ${wd <= 767 ? 'yes' : 'no'} · finger operation ${mouse ? 'no' : 'yes'}$`).test(txt),
        `${tag}: the device line is visible and names size, pointer, hover and both switches: ${txt}`);
      await shot(`p2653-b-about-${mouse ? 'mouse' : 'touch'}-${wd}x${ht}.png`);
      if (!mouse && wd === 840) {
        // turning the tablet while the settings are open: the line follows (resize), the switch stays on fingers
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: ht, height: wd}});
        check(await until(`(document.getElementById('s-aboutdev')?.textContent || '').startsWith('${ht} × ${wd} px')`), `${tag}: turned, the device line shows ${ht} × ${wd}: ${await ev(LINE)}`);
        check(JSON.parse(await ev(ENV)).ui === true, `${tag}: turned, isTouchUi() still true`);
      }
      await ev(`(() => { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); document.querySelectorAll('.modal, .smodal').forEach(m => m.remove()); return 1; })()`);
    }
  };
  await firefox(async o => session(o, [[390, 844], [840, 1180], [1180, 840]], false), true);
  await firefox(async o => session(o, [[1280, 800]], true), false);

  console.log(`p2653_b_touchui_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
