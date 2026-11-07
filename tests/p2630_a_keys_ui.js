// 2.630.0 UI tests, part A (#4510): ONE key registry (static/js/keys.js) instead of a keydown listener per area, jsdom:
// kalmido-suite: fresh
// - Escape closes only the innermost open thing: a dialog over a menu over the task panel -> the dialog, then the menu, then
//   the panel, one per key; a menu opened inside a dialog closes before the dialog
// - a key registered with kb_on fires in its scope, not while typing in a field (a letter), and shows in the shortcut help
// - the old way: a key sent to the document still reaches the registry (it bubbles to window)
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
    const esc = (o = {}) => (d.activeElement || d.body).dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true, ...o}));
    const dlgs = () => d.querySelectorAll('.modal:not(.an-out)').length;
    const popOpen = () => !d.querySelector('#pop').classList.contains('hidden');
    await until(() => w.eval(`!!taskById(${t.id})`));

    // ---- a dialog over a menu over the task panel: one Escape = one closes, the innermost first
    w.eval(`openDetail(${t.id})`);
    await until(() => w.eval(`S.sel === ${t.id}`) && d.querySelector('#detail'));
    w.eval(`openPop(document.querySelector('#detail') || document.body, '<div class="p2630-menu"><button>One</button></div>')`);
    check(popOpen(), tag + 'the menu is open');
    w.eval(`modal('<h3>Check p2630</h3><p>Text</p>').classList.add('p2630-dlg')`);
    check(dlgs() === 1 && w.eval('kb_scopes()[0].scope') === 'dialog', tag + 'the dialog is the innermost scope');
    esc();
    check(await until(() => dlgs() === 0), tag + 'Escape 1: the dialog closed');
    check(popOpen() && w.eval(`S.sel === ${t.id}`), tag + 'Escape 1: the menu and the panel stay open');
    esc();
    check(await until(() => !popOpen()), tag + 'Escape 2: the menu closed');
    check(w.eval(`S.sel === ${t.id}`), tag + 'Escape 2: the panel stays open');
    if (/^(INPUT|TEXTAREA)$/.test(d.activeElement?.tagName || '')) d.activeElement.blur();  // a focused field would take the Escape first (it blurs)
    esc();
    check(await until(() => !w.eval('S.sel')), tag + 'Escape 3: the panel closed');

    // ---- a menu opened inside a dialog closes before the dialog
    w.eval(`(() => { const m = modal('<h3>Second p2630</h3><button class="p2630-in">Pick</button>'); openPop(m.querySelector('.p2630-in'), '<div><button>Two</button></div>'); })()`);
    check(dlgs() === 1 && popOpen() && d.querySelector('#pop').classList.contains('overmodal'), tag + 'a menu over the dialog');
    esc();
    check(await until(() => !popOpen()) && dlgs() === 1, tag + 'Escape: the menu over the dialog closed, the dialog stays');
    esc();
    check(await until(() => dlgs() === 0), tag + 'Escape: then the dialog closed');
    check(await until(() => w.eval('KBR.st.length') === 0), tag + 'nothing stays on the stack ' + w.eval('JSON.stringify(KBR.st.map(s => s.scope))'));

    // ---- the old way of a test: a key sent to the document (bubbles) still reaches the registry
    w.eval(`modal('<h3>Third p2630</h3>')`);
    w.eval(`document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))`);
    check(await until(() => dlgs() === 0), tag + 'Escape sent to the document closes the dialog');

    // ---- a key registered with kb_on: its scope, never while typing a letter, in the help
    w.eval(`window.__p2630 = 0; kb_on('global', 'Shift+Y', () => { window.__p2630++; }, {help: 'Check p2630 shortcut', group: 'General'})`);
    d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Y', shiftKey: true, bubbles: true, cancelable: true}));
    check(w.eval('window.__p2630') === 1, tag + 'kb_on: Shift+Y runs its handler');
    const inp = d.createElement('input'); d.body.appendChild(inp); inp.focus();
    inp.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Y', shiftKey: true, bubbles: true, cancelable: true}));
    check(w.eval('window.__p2630') === 1, tag + 'kb_on: not while typing in a field');
    inp.remove();
    w.eval(`modal('<h3>Fourth p2630</h3>')`);
    d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Y', shiftKey: true, bubbles: true, cancelable: true}));
    check(w.eval('window.__p2630') === 1, tag + 'kb_on: an open dialog keeps a global key from the view');
    esc(); await until(() => dlgs() === 0);
    check(w.eval(`SHORTCUTS().some(([g, rows]) => g === 'General' && rows.some(([k, n]) => k === 'Shift+Y' && n === 'Check p2630 shortcut'))`), tag + 'the help list has the registered key');
    check(w.eval(`SHORTCUTS().some(([g, rows]) => rows.some(([k]) => k === 'g t'))`), tag + 'the help list keeps its fixed keys');
    w.eval('shortcutsModal()');
    check(await until(() => d.querySelector('.kbmodal') && /Check p2630 shortcut/.test(d.querySelector('.kbmodal').textContent)), tag + 'the shortcut dialog shows the registered key');
    esc();
    check(await until(() => !d.querySelector('.kbmodal:not(.an-out)')), tag + 'Escape closes the shortcut dialog');
    w.close?.();
  }
  console.log(F.length ? 'FAILED ' + F.length : 'OK ' + ok); process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
