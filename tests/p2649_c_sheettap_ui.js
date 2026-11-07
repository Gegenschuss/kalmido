// 2.649.0 C (#5062) UI test (Firefox, phone with touch), fresh DB: a dialog sheet scrolled down keeps its place when a finger
// kalmido-suite: fresh
// touches it - a tap on a row toggles that row (sheetdrag.js measured the content height on every touch with height auto,
// the card jumped to its top and the tap hit another row; p2150_ui went red), and a drag at the grip keeps the scroll too
const {B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2649_c_sheettap_ui', check, shots: 'P2649C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CK}, body: JSON.stringify({lang: 'en', tour: 'done', whatsnew_on: '0'})});

  await firefox(async ({cmd, ev, nav, ctx, shot, drag, until}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#today');
    check(await until(`typeof modal === 'function' && !!document.querySelector('#view')`), 'the app is up');
    // a dialog with 40 tick rows (taller than the phone), scrolled down
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); const m = modal('<h3>Rows</h3>' + Array.from({length: 40}, (_, i) => '<label class="chkl"><input type="checkbox" data-row="' + i + '"><span>Row ' + i + '</span></label>').join('')); m.classList.add('p2649c'); return 1; })()`);
    check(await until(`(() => { const c = document.querySelector('.p2649c > .card'); return !!c && c.getAnimations().length === 0 && c.scrollHeight > c.clientHeight + 300; })()`), 'setup: the dialog scrolls');
    const SCROLL = `(() => { const c = document.querySelector('.p2649c > .card'); c.scrollTop = 300; return c.scrollTop; })()`;
    const st0 = await ev(SCROLL);
    check(st0 >= 250, 'setup: scrolled down ' + st0);
    // the row in the middle of the screen, its point taken once it stands still
    const PT = `(() => { const c = document.querySelector('.p2649c > .card'), h = innerHeight / 2; const l = [...c.querySelectorAll('label.chkl')].find(x => { const r = x.getBoundingClientRect(); return r.top <= h && r.bottom >= h; }); if (!l) return null; const r = l.getBoundingClientRect(), p = {x: Math.round(r.left + r.width * .7), y: Math.round(r.top + r.height / 2), row: l.querySelector('input').dataset.row}; const same = window.__p2649 === JSON.stringify(p); window.__p2649 = JSON.stringify(p); return same ? p : null; })()`;
    const p = await until(() => ev(PT).catch(() => null));
    check(!!p, 'setup: a row under the middle of the screen');
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: p.x, y: p.y}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
    const tapped = `[...document.querySelectorAll('.p2649c input:checked')].map(x => x.dataset.row).join(',')`;
    await until(`${tapped} !== ''`);
    check(await ev(tapped) === p.row, `a tap toggles the row under the finger (row ${p.row}, ticked: ${await ev(tapped)})`);
    check(await ev(`document.querySelector('.p2649c > .card').scrollTop`) === st0, 'the tap keeps the scroll ' + await ev(`document.querySelector('.p2649c > .card').scrollTop`));
    await shot('p2649c-tap.png');
    // a short drag down at the grip (the head; the card may start above the screen) resizes the sheet and keeps the scroll
    const top = await ev(`document.querySelector('.p2649c > .card').getBoundingClientRect().top`);
    await drag(195, Math.max(4, top + 12), 0, 60, 'touch');
    await until(`!document.querySelector('.p2649c > .card').classList.contains('sd-drag')`);
    check(await ev(`!!document.querySelector('.p2649c')`), 'drag: the dialog stays open');
    const st1 = await ev(`document.querySelector('.p2649c > .card').scrollTop`);
    check(st1 >= st0 - 2, `a drag at the grip keeps the scroll (${st1} >= ${st0})`);
  }, true);

  console.log(`p2649_c_sheettap_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p2649_c_sheettap_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
