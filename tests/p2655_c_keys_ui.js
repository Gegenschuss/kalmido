// 2.655.0 UI tests, part C (#4998): the remaining keydown listeners on document / window moved onto the key registry (keys.js), jsdom:
// kalmido-suite: fresh
// - 'first' (what was a capture listener on the document): asked before every field and area and not held by an open dialog:
//   the icon tooltip hides on Esc and the dialog under it stays; the timeline's pick mode ends on Esc and the dialog stays;
//   the link preview hides and lets the key go on (the dialog closes with the same Esc, as before)
// - the docs pane's Esc is the view's (view:docs): an open menu closes first, the next Esc closes the pane
// - the letters n and / of the shell are the registry's: they work, not while typing, not under an open dialog, and the
//   shortcut help lists n / q / m / a / / in the group General right after '?', from the registry, each once
// run as the admin of an organisation AND as a person without organisation (freelancer parity). Invented names only.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const DESK = {'(hover:hover) and (pointer:fine)': true};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const ACK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments']}, ACK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, ACK);
  const fu = await call('POST', '/api/users', {orgs: [], username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com'}, ACK);
  check(fu.status < 300, 'a person without organisation ' + fu.status);
  const FCK = await login('fiona');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, FCK);

  for (const [user, ck] of [['alice', ACK], ['fiona', FCK]]) {
    const tag = user + ': ';
    const t = await call('POST', '/api/tasks', {title: 'Order the paper ' + user}, ck);
    check(t.id > 0, tag + 'a task ' + t.status);
    const w = await boot({user, hash: 'inbox', media: DESK}), d = w.document;
    await until(() => w.eval('!!S.booted && typeof kb_on === "function"'));
    const kd = (k, o = {}, el) => (el || d.activeElement || d.body).dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
    const esc = el => kd('Escape', {}, el);
    const dlgs = () => d.querySelectorAll('.modal:not(.an-out)').length;
    const closeAll = async () => { for (let i = 0; i < 4 && dlgs(); i++) { const n = dlgs(); esc(d.body); await until(() => dlgs() < n); } return dlgs() === 0; };
    const popOpen = () => !d.querySelector('#pop').classList.contains('hidden');
    check(w.eval(`(KBR.on.get('first') || []).length`) >= 8, tag + "the former capture listeners are on the registry's 'first' " + w.eval(`(KBR.on.get('first') || []).length`));

    // ---- 'first': the icon tooltip over a dialog: Esc hides the tooltip only, the dialog stays; the next Esc closes the dialog
    w.eval(`modal('<h3>Check p2655</h3><p>Text</p>')`);
    w.eval(`(() => { const s = document.createElement('span'); s.id = 'p2655tip'; s.hidden = true; s.textContent = 'A hint p2655'; const b = document.createElement('button'); b.className = 'ib'; b.dataset.ii = 'p2655tip'; document.body.append(s, b); iiShow(b, true); })()`);
    check(!!d.querySelector('#iitip:not(.hidden)') && dlgs() === 1, tag + 'the tooltip shows over the dialog');
    if (/^(INPUT|TEXTAREA)$/.test(d.activeElement?.tagName || '')) d.activeElement.blur();
    esc();
    check(!d.querySelector('#iitip:not(.hidden)'), tag + 'Esc 1: the tooltip hid');
    await sleep(50);
    check(dlgs() === 1, tag + 'Esc 1: the dialog stays (the tooltip took the key before it)');
    esc();
    check(await until(() => dlgs() === 0), tag + 'Esc 2: the dialog closed');

    // ---- 'first': the timeline's pick mode is not held by an open dialog (as the capture listener before)
    check(w.eval('typeof tlPickEnd') === 'function', tag + 'the timeline module is loaded');
    w.eval(`modal('<h3>Second p2655</h3>')`);
    w.eval(`S.tlPick = {from: ${t.id}}`);
    esc(d.body);
    check(w.eval('S.tlPick') === null, tag + 'Esc ends picking a task of the timeline');
    await sleep(50);
    check(dlgs() === 1, tag + 'Esc that ended picking leaves the dialog open');
    check(await closeAll(), tag + 'then the dialog closes');

    // ---- 'first' watching: the link preview hides and the key goes on (the dialog under it closes with the same Esc)
    w.eval(`modal('<h3>Third p2655</h3>')`);
    w.eval(`(() => { const el = document.createElement('div'); el.className = 'rfpv on'; document.body.appendChild(el); RFH.el = el; })()`);
    esc(d.body);
    check(w.eval('RFH.el') === null, tag + 'Esc hides the link preview');
    check(await until(() => dlgs() === 0), tag + 'the same Esc closes the dialog too (the preview only watches)');

    // ---- view:docs: an open menu closes first, the next Esc closes the docs pane (route and pane set by hand, the module is loaded)
    check(w.eval('typeof dc_paneClose') === 'function', tag + 'the docs module is loaded');
    w.eval(`window.__p2655r = S.route; S.route = {...S.route, mod: 'docs'}; window.__p2655c = 0; window.__p2655s = 0; window.__p2655pc = dc_paneClose; window.__p2655ps = dc_step;
      dc_paneClose = () => { window.__p2655c++; DC.paneId = null; }; dc_step = d => { window.__p2655s += d; }; DC.paneId = 1;`);
    w.eval(`openPop(document.body, '<div class="p2655-menu"><button>One</button></div>')`);
    check(popOpen() && w.eval('kb_scopes().map(s => s.scope).join()').includes('view:docs'), tag + 'docs: a menu over the pane, view:docs among the scopes');
    esc(d.body);
    check(await until(() => !popOpen()) && w.eval('window.__p2655c') === 0, tag + 'docs: Esc 1 closes the menu, the pane stays');
    kd('ArrowDown', {}, d.body); kd('ArrowUp', {}, d.body); kd('ArrowUp', {}, d.body);
    check(w.eval('window.__p2655s') === -1, tag + 'docs: the arrows step through the pane ' + w.eval('window.__p2655s'));
    esc(d.body);
    check(w.eval('window.__p2655c') === 1, tag + 'docs: Esc 2 closes the pane');
    w.eval(`S.route = window.__p2655r; dc_paneClose = window.__p2655pc; dc_step = window.__p2655ps; DC.paneId = null;`);

    // ---- the letters of the shell: n focuses the add box, not while typing and not under a dialog; / opens the search
    if (d.activeElement && d.activeElement !== d.body) d.activeElement.blur();
    check(!!d.querySelector('#qinput'), tag + 'the add box is there');
    const inp = d.createElement('input'); d.body.appendChild(inp); inp.focus();
    kd('n', {}, inp);
    check(d.activeElement === inp, tag + 'n while typing in a field stays a letter');
    inp.remove();
    w.eval(`modal('<h3>Fourth p2655</h3>')`); if (d.activeElement && d.activeElement !== d.body) d.activeElement.blur();
    kd('n', {}, d.body);
    check(d.activeElement?.id !== 'qinput', tag + 'n under an open dialog does nothing (the dialog is modal)');
    check(await closeAll(), tag + 'the dialog closed');
    kd('n', {}, d.body);
    check(await until(() => d.activeElement?.id === 'qinput'), tag + 'n focuses the add box');
    d.activeElement.blur();
    kd('/', {}, d.body);
    check(await until(() => w.eval('S.route.key') === 'search'), tag + '/ opens the search ' + w.eval('S.route.key'));

    // ---- the help: n / q / m / a / / from the registry, in General right after '?', each once, no mark row left
    const gen = w.eval(`JSON.stringify((SHORTCUTS().find(([g]) => g === 'General') || [, []])[1].map(([k]) => k))`);
    const ks = JSON.parse(gen), at = ks.indexOf('?');
    check(JSON.stringify(ks.slice(at + 1, at + 6)) === JSON.stringify(['n', 'q', 'm', 'a', '/']), tag + 'the help lists n q m a / after ? ' + gen);
    check(!ks.includes('@kb') && ks.filter(k => k === 'n').length === 1, tag + 'no mark row, n once');
    check(w.eval(`kb_helpRows().some(([g, rows]) => g === 'General' && rows.some(([k, n]) => k === '/' && n === 'Search'))`), tag + 'the help row of / comes from the registry');
    w.eval('shortcutsModal()');
    check(await until(() => d.querySelector('.kbmodal') && /New note/.test(d.querySelector('.kbmodal').textContent) && /Quick capture to the basket/.test(d.querySelector('.kbmodal').textContent)), tag + 'the shortcut dialog shows the registered letters');
    esc(d.body);
    check(await until(() => !d.querySelector('.kbmodal:not(.an-out)')), tag + 'Esc closes the shortcut dialog');
    w.close?.();
  }
  console.log(F.length ? 'FAILED ' + F.length : 'OK ' + ok); process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
