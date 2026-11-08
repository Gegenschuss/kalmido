// p2725_c_sechold_ui -- 2.725.0 C (#5177): a held section head (phone, Firefox with touch) runs one mechanism, not two
// kalmido-suite: fresh
// A section head of a list carried two holds: dnd.js's touch hold (450 ms, lifts the section to drag it; let go unmoved = the
// head's menu) and the row menu's long press of multisel.js cm_bind (500 ms, the section menu). Both fired: held still, two
// menus opened one after the other; held and dragged, the section menu opened under the finger while the section moved.
// Now the drag's hold takes the press (ms_lpTake, as the file store rows):
// - held without moving, let go: exactly one menu, no section is dragged
// - held, then moved past the threshold: the section is dragged (its ghost shows), no menu at all
// Invented data only.
const {B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2725_c_sechold_ui', check, shots: 'P2725C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', whatsnew_on: '0'});
  const P = (await call('POST', '/api/lists', {name: 'Hold project'})).id;
  const SEC = [];
  for (const n of ['Alpha', 'Beta', 'Gamma']) SEC.push((await call('POST', '/api/sections', {list_id: P, name: n})).id);
  for (const [i, s] of SEC.entries()) await call('POST', '/api/tasks', {title: 'Task ' + i, list_id: P, section_id: s});

  await firefox(async ({cmd, ev, nav, ctx, until, shot}) => {
    // one finger: down on (x, y), hold `hold` ms, then (optionally) move by dy; up = let go (false: the finger stays down)
    const press = (x, y, hold, dy = 0, up = true) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: 'touch'},
      actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: hold},
        ...(dy ? [{type: 'pointerMove', x: Math.round(x), y: Math.round(y + dy / 2), duration: 120}, {type: 'pointerMove', x: Math.round(x), y: Math.round(y + dy), duration: 120}] : []),
        ...(up ? [{type: 'pointerUp', button: 0}] : [])]}]});
    const lift = () => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerUp', button: 0}]}]})
      .then(() => cmd('input.releaseActions', {context: ctx}));
    // every menu() call is counted (one #pop: a second menu would replace the first and stay unseen otherwise)
    const COUNT = `(() => { if (!window.__mn) { window.__mn = []; const m0 = window.menu; window.menu = function (a, items) { window.__mn.push((items || []).map(i => i && i.label).filter(Boolean).join('|')); return m0.apply(this, arguments); }; } window.__mn.length = 0; return 1; })()`;
    const menus = () => ev(`window.__mn.slice()`);
    const MENU = `!!document.querySelector('#pop:not(.hidden) [role="menu"]')`;
    const head = sid => ev(`(() => { const h = document.querySelector('#view .ghead[data-section="${sid}"]'); if (!h) return null; h.scrollIntoView({block: 'center'}); const r = h.getBoundingClientRect(); return {x: r.left + Math.min(120, r.width / 2), y: r.top + r.height / 2}; })()`);
    const closeMenu = () => ev(`(() => { if (typeof closePop === 'function') closePop(); else document.querySelector('#pop')?.classList.add('hidden'); return 1; })()`);

    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: ${JSON.stringify(H)}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#l/' + P);
    check(await until(`typeof sb_secHoldStart === 'function' && typeof LM_SECHEAD === 'object' && !!document.querySelector('#view .ghead[data-section="${SEC[2]}"]')`, {timeout: 20000}), 'phone: the list shows its section heads');
    check(await ev(`isTouch() && matchMedia('(pointer: coarse)').matches`), 'phone: a finger device (touch: true)');

    // ---- held without moving, let go: one menu, no drag
    await ev(COUNT);
    let p = await head(SEC[1]);
    check(!!p, 'the head of Beta is there');
    if (p) {
      await press(p.x, p.y, 700); await cmd('input.releaseActions', {context: ctx});
      check(await until(MENU), 'held still: a menu opens ' + JSON.stringify(await menus()));
      await until(`!document.querySelector('.sb-secghost')`);
      const m = await menus();
      check(m.length === 1, 'held still: exactly one menu, not the drag\'s and the long press\'s both ' + JSON.stringify(m));
      check(await ev(`!document.querySelector('.sb-secghost') && !document.querySelector('#view .dragging')`), 'held still: no section is dragged');
      await shot('p2725c-held-menu.png');
      await closeMenu();
      await until(`!(${MENU})`);
    }

    // ---- held, then moved: the section is dragged, no menu
    await ev(COUNT);
    p = await head(SEC[0]);
    if (p) {
      await press(p.x, p.y, 700, 90, false);
      check(await until(`!!document.querySelector('.sb-secghost')`), 'held and moved: the section is lifted and dragged (ghost)');
      check((await menus()).length === 0 && !(await ev(MENU)), 'held and moved: no menu while dragging ' + JSON.stringify(await menus()));
      await lift();
      check(await until(`!document.querySelector('.sb-secghost')`), 'held and moved: the drag ends on release');
      await until(`!document.querySelector('#view .dragging')`);
      check((await menus()).length === 0 && !(await ev(MENU)), 'held and moved: no menu after letting go ' + JSON.stringify(await menus()));
    } else check(false, 'the head of Alpha is there');
  }, true);

  console.log(`p2725_c_sechold_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
