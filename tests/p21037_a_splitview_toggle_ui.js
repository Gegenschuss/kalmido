// 2.1037.0 A UI test (#5803 the split view one click away: a button next to the bell, Shift+V), own container (start.sh, isolated test database), Firefox with a mouse and real keys.
// kalmido-suite: fresh
// Invented data only. alice has no organisation (freelancer-matrix: Geteilte Ansicht).
// - a narrow window (1200 px): no button in the bar, no gap; Shift+V does nothing
// - a wide window: the button sits next to the bell, not pressed; a mouse click: the right half comes with Today (nothing shown there
//   before), the button is pressed (aria-pressed), the switch in Settings > Appearance shows "on"; a click again: the right half goes
// - switching on again shows the right half's last page (splR): the project's title there
// - Shift+V switches on and off; Shift+V while typing in a field types a V and switches nothing; Shift+V with the focus in the right half
//   switches off (the right half hands the key to the window around it)
// - "Open on the right" stands in the menu while the split view is off and switches it on; "Split view on / off" in the command search
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21037_a_splitview_toggle', check, shots: 'P21037A_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Lighthouse survey', kind: 'project'})).id;
  await call('POST', '/api/tasks', {title: 'Measure the lantern room', list_id: L});

  await firefox(async o => {
    const {cmd, ev, ctx, nav, until, shot} = o;
    const {realClick} = require('./ff');
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    let nn = 0; const load = h => nav(B + '?n=' + (++nn) + h);
    const booted = () => until(`typeof S !== 'undefined' && S.booted && !!document.querySelector('#view')`, {timeout: 30000});
    const FR = `document.querySelector('#splitpane iframe.splitfr')`;
    const FW = `(() => { try { return ${FR}.contentWindow; } catch { return null; } })()`;
    const untilFr = (x, opt = {timeout: 30000}) => until(`(() => { const w = ${FW}, d = w && w.document; if (!w || !d) return null; try { return (${x}); } catch { return null; } })()`, opt);
    // the page title a person sees in the right half (its header, laid out, not hidden)
    const frTitle = re => untilFr(`[...d.querySelectorAll('#top h1 .ht')].some(e => ${re}.test(e.textContent || '') && e.getBoundingClientRect().width > 2 && (!e.checkVisibility || e.checkVisibility({visibilityProperty: true})))`);
    const gone = () => until(`!document.querySelector('#splitpane') && !document.documentElement.classList.contains('split-on')`);
    const BTN = '.splbtn';
    const btn = () => ev(`(() => { const b = [...document.querySelectorAll('${BTN}')].find(x => x.offsetParent !== null); if (!b) return null; const r = b.getBoundingClientRect();
      return {pressed: b.getAttribute('aria-pressed'), on: b.classList.contains('on'), title: b.title, w: Math.round(r.width), bell: !!b.nextElementSibling && b.nextElementSibling.classList.contains('bell')}; })()`);
    // a real key press (Shift held for the letter); the browser sends it to whatever has the focus
    const shiftV = async () => {
      await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k', actions: [{type: 'keyDown', value: ''}, {type: 'keyDown', value: 'V'}, {type: 'keyUp', value: 'V'}, {type: 'keyUp', value: ''}]}]});
      await cmd('input.releaseActions', {context: ctx});
    };
    const focusLeft = () => ev(`(document.activeElement && document.activeElement !== document.body && document.activeElement.blur(), window.focus(), 1)`);

    // ---- 1200 px: the split view is not offered: no button (no gap next to the bell), Shift+V does nothing, no menu entry
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1200, height: 1000}});
    await ev(`localStorage.removeItem('tasks.split'), localStorage.removeItem('tasks.splR'), 1`);
    await load('#today'); await booted();
    await until(`!!document.querySelector('.bell')`);
    check(await ev(`!document.querySelector('${BTN}') && spl_offer() === false`), '1200 px: no split view button in the bar');
    await focusLeft(); await shiftV();
    check(await ev(`new Promise(r => requestAnimationFrame(() => r(!document.querySelector('#splitpane') && LS.get('split', false) !== true)))`), '1200 px: Shift+V switches nothing on');
    check(await ev(`!listMenuItems(${L}, document.body).some(x => x && x.cls === 'msplit')`), '1200 px: no "Open on the right" in the menu');

    // ---- 2800 px: the button next to the bell, off
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 2800, height: 1100}});
    await load('#today'); await booted();
    const b0 = await until(() => btn());
    check(b0 && b0.pressed === 'false' && !b0.on && b0.w > 10, 'wide: the split view button shows, not pressed ' + JSON.stringify(b0));
    check(b0 && b0.bell, 'wide: the button sits right before the bell ' + JSON.stringify(b0));
    check(b0 && /Split view/.test(b0.title) && /V/.test(b0.title), 'wide: its tooltip names the split view and the key ' + JSON.stringify(b0 && b0.title));
    check(await ev(`!document.querySelector('#splitpane')`), 'wide, off: no right half');

    // ---- a click with the mouse: on, the right half shows Today (no page remembered yet)
    const c1 = await realClick(o, BTN);
    check(c1.ok, 'the button takes a mouse click ' + c1.on);
    check(await frTitle(/^Today$/), 'on: the right half shows Today');
    const b1 = await btn();
    check(b1 && b1.pressed === 'true' && b1.on, 'on: the button is pressed ' + JSON.stringify(b1));
    await ev(`loadModule('settings').then(() => { settingsModal('look'); return 1; })`);
    check(await until(`!!document.querySelector('.smodal #s-split') && document.querySelector('.smodal #s-split').checked`), 'on: the switch in Settings > Appearance shows on');
    await ev(`document.querySelectorAll('.smodal').forEach(m => m.remove()), 1`);
    await shot('p21037a-on-today.png');

    // the right half goes to the project (its own navigation); remembered as its last page
    await untilFr(`w.S && w.S.booted`);
    await ev(`(${FW}.location.hash = '#l/${L}', 1)`);
    check(await frTitle(/Lighthouse survey/), 'the right half shows the project');
    check(await until(`LS.get('splR', '') === '#l/${L}'`), 'the right half\'s page is remembered (splR)');

    // ---- a click again: off, the whole width for the app
    const c2 = await realClick(o, BTN);
    check(c2.ok, 'the pressed button takes a mouse click ' + c2.on);
    check(await gone(), 'off: the right half goes');
    const b2 = await btn();
    check(b2 && b2.pressed === 'false' && !b2.on, 'off: the button is not pressed ' + JSON.stringify(b2));

    // ---- Shift+V: on again with the last page, then off
    await focusLeft(); await shiftV();
    check(await frTitle(/Lighthouse survey/), 'Shift+V: on, the right half shows its last page (the project)');
    check(await until(`document.querySelector('${BTN}')?.getAttribute('aria-pressed') === 'true'`), 'Shift+V: the button follows (pressed)');
    await focusLeft(); await shiftV();
    check(await gone(), 'Shift+V again: off');

    // ---- Shift+V while typing in a field: the letter goes into the field, nothing switches
    await ev(`(() => { const q = currentQuickInput(); if (q) q.focus(); return !!q; })()`);
    const typing = await until(`document.activeElement && /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)`);
    check(typing, 'a text field has the focus');
    await shiftV();
    check(await until(`document.activeElement && /V$/.test(document.activeElement.value || '')`), 'Shift+V in a field types a V');
    check(await ev(`!document.querySelector('#splitpane') && LS.get('split', false) !== true`), 'Shift+V in a field switches nothing');
    await ev(`(() => { const a = document.activeElement; if (a && 'value' in a) { a.value = ''; a.dispatchEvent(new Event('input', {bubbles: true})); } a && a.blur(); return 1; })()`);

    // ---- the focus in the right half: Shift+V there switches off (the right half hands the key to the window around it)
    await focusLeft(); await shiftV();
    check(await frTitle(/Lighthouse survey/), 'on again for the right half\'s turn');
    await untilFr(`w.S && w.S.booted && typeof w.kb_on === 'function'`);
    await ev(`(() => { const f = ${FR}; f.focus(); const w = f.contentWindow; w.focus(); const v = w.document.querySelector('#view'); if (v) { v.tabIndex = -1; v.focus(); } return 1; })()`);
    check(await until(`document.activeElement === ${FR}`), 'the focus is in the right half');
    await shiftV();
    check(await gone(), 'Shift+V with the focus in the right half: off');
    check(await until(`document.querySelector('${BTN}')?.getAttribute('aria-pressed') === 'false'`), 'after Shift+V in the right half the button is not pressed');

    // ---- "Open on the right" while it is off: in the menu, and it switches it on
    const it = await ev(`(() => { const x = listMenuItems(${L}, document.body).find(x => x && x.cls === 'msplit'); if (!x) return ''; x.fn(); return x.label; })()`);
    check(it === 'Open on the right', 'off: the project menu has "Open on the right" ' + it);
    check(await frTitle(/Lighthouse survey/), '"Open on the right" switches the split view on and shows the project');
    check(await until(`document.querySelector('${BTN}')?.getAttribute('aria-pressed') === 'true'`), 'after "Open on the right" the button is pressed');

    // ---- the command search: "Split view on / off" (with its key)
    await ev(`(openPalette(), 1)`);
    await until(`!!document.querySelector('#palette input, .palette input')`);
    await ev(`(() => { const i = document.querySelector('#palette input, .palette input'); i.value = 'split view'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    const row = await until(`[...document.querySelectorAll('#palette [role=option], .palette [role=option]')].find(e => /Split view on \\/ off/.test(e.textContent)) ? 1 : 0`);
    check(row, 'the command search has "Split view on / off"');
    if (row) {
      await ev(`[...document.querySelectorAll('#palette [role=option], .palette [role=option]')].find(e => /Split view on \\/ off/.test(e.textContent)).click(), 1`);
      check(await gone(), 'the command switches the split view off');
    }
    await shot('p21037a-off.png');
  }, false);

  console.log(`p21037_a_splitview_toggle: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
