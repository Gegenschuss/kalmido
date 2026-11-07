// kalmido-suite: fresh
// 2.620.0 A (#4616): a long press (phone) / a right click (computer) opens the row's "…" menu in the places that had no
// binding yet: the filing addresses of the mailbox (hubmail.js), repositories (gitrepo.js), inbound webhooks (hookin.js),
// file requests (filereq.js), the folder cards of the tables (sheetfold.js) and the file cards (abdocs.js).
// Own container (start.sh), jsdom. Each area: its module is loaded, a row with the area's selector and its "…" button is put
// into the page (the data of these areas needs outside services), the button is the probe: the right click and the long
// press must click it (the area's own handler then opens the menu); the browser's menu stays where there is no button, on a
// link inside a row (not the table cards) and with a selection. A source check keeps the real templates and the selectors together.
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2620A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const ctx = (w, el) => { const e = new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true, button: 2}); el.dispatchEvent(e); return e; };
const touch = (w, el, type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); for (const [k, v] of Object.entries({pointerType: 'touch', clientX: 5, clientY: 5})) Object.defineProperty(e, k, {value: v}); el.dispatchEvent(e); };
const src = f => fs.readFileSync(path.join(__dirname, '..', 'static', 'js', f), 'utf8');

// area: module to load, a function that exists once it is loaded, the row (selector = class, tag), the button's attribute,
// the file of the real template, what the template must contain, a link inside the row (keeps the browser menu) or not
const AREAS = [
  {name: 'mailbox addresses', mod: 'hubmail', fn: 'hbm_hubView', cls: 'hbmsp', btn: 'data-hbma="menu"', file: 'hubmail.js', link: true},
  {name: 'repositories', mod: 'gitrepo', fn: 'repoWire', cls: 'reporow', btn: 'data-rp="menu"', file: 'gitrepo.js', link: true},
  {name: 'inbound webhooks', mod: 'hookin', fn: 'whiMount', cls: 'whi-row', btn: 'data-whi-menu="1"', file: 'hookin.js', link: true},
  {name: 'file requests', mod: 'filereq', fn: 'frq_open', cls: 'frq-row', btn: 'data-frq="menu"', file: 'filereq.js', link: true},
  {name: 'table folder cards', mod: 'sheets', fn: 'shf_cardsHtml', cls: 'shfcard', btn: 'data-shf="fmenu"', file: 'sheetfold.js', link: false},
  {name: 'file cards', mod: 'docs', fn: 'abd_card', cls: 'dc-card', btn: 'data-ab="menu"', file: 'abdocs.js', link: true},
];

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await fetch(B + 'api/admin/setup', {method: 'POST', headers: {...H, Cookie: CK}, body: JSON.stringify({lang: 'en', collab_all: true})});
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CK}, body: JSON.stringify({lang: 'en', tour: 'done'})});

  const w = await boot({user: 'alice', hash: 'ablage'}); const d = w.document;
  await until(() => w.eval(`typeof cm_bind === 'function' && typeof loadModule === 'function'`));

  for (const A of AREAS) {
    // the real template carries the class and the button the binding looks for
    const s = src(A.file);
    check(s.includes(A.cls) && s.includes(A.btn.split('=')[0]), `${A.name}: the template has ${A.cls} and ${A.btn.split('=')[0]}`);
    check(new RegExp(`cm_bind\\('[^']*${A.cls.replace(/-/g, '\\-')}`).test(s), `${A.name}: ${A.file} binds ${A.cls}`);
    await w.eval(`loadModule('${A.mod}')`);
    check(await until(() => w.eval(`typeof ${A.fn} === 'function'`)), `${A.name}: module ${A.mod} loaded`);
    // a probe row inside the page: the row, its "…" button, the click counted
    const host = d.createElement('div'); host.id = 'probe-' + A.cls; host.className = 'abview';
    const tag = A.cls === 'hbmsp' ? 'li' : A.cls === 'dc-card' ? 'li' : 'div';
    host.innerHTML = (A.cls === 'hbmsp' ? '<ul class="hbmspaces">' : A.cls === 'dc-card' ? '<ul class="dc-grid abcards">' : '')
      + `<${tag} class="${A.cls}"><span class="t">${A.link ? '<a href="https://example.com/x">Link</a> ' : ''}Name</span>`
      + `<button type="button" class="iconbtn" ${A.btn}>...</button></${tag}>`
      + `<${tag} class="${A.cls}" id="nobtn-${A.cls}"><span class="t">Without button</span></${tag}>`
      + (A.cls === 'hbmsp' || A.cls === 'dc-card' ? '</ul>' : '');
    d.querySelector('#view').appendChild(host);
    const row = host.querySelector('.' + A.cls), btn = row.querySelector('button');
    let n = 0; btn.addEventListener('click', e => { n++; e.stopPropagation(); });

    // computer: the right click on the name text clicks the button, the browser's menu is held back
    let e = ctx(w, row.querySelector('.t'));
    check(e.defaultPrevented && n === 1, `${A.name}: a right click clicks the "…" button (${n})`);
    // phone: a long press does the same, the click that ends the press does nothing
    touch(w, row.querySelector('.t'), 'pointerdown');
    check(await until(() => n === 2, 20), `${A.name}: a long press clicks the "…" button (${n})`);
    touch(w, row.querySelector('.t'), 'pointerup');
    // the browser's menu stays: a row without a button (after the click guard of the press, 600 ms)
    await sleep(700);
    e = ctx(w, host.querySelector('#nobtn-' + A.cls + ' .t'));
    check(!e.defaultPrevented && n === 2, `${A.name}: a row without a button keeps the browser's menu`);
    // a link inside the row keeps the browser's menu (copy link); not in the table cards, where the whole card is a link
    if (A.link) {
      e = ctx(w, row.querySelector('a'));
      check(!e.defaultPrevented && n === 2, `${A.name}: a right click on a link keeps the browser's menu`);
    }
    host.remove();
  }

  // the table cards: the whole card is a link, so the right click on it opens the menu all the same
  {
    await sleep(700);  // lets the earlier long press settle (the click guard lasts 600 ms)
    const host = d.createElement('div'); host.className = 'abview';
    host.innerHTML = '<ul><li class="shvcard shfcard" data-fid="1"><a href="#sheets/f/1" class="shvcl"><b class="nm">Folder</b></a><button type="button" class="iconbtn" data-shf="fmenu" data-id="1">...</button></li></ul>';
    d.querySelector('#view').appendChild(host);
    let n = 0; host.querySelector('button').addEventListener('click', e => { n++; e.stopPropagation(); });
    const e = ctx(w, host.querySelector('.nm'));
    check(e.defaultPrevented && n === 1, 'table folder cards: a right click on the card (a link) opens the folder menu (' + n + ')');
    host.remove();
  }

  // the places left out stay as they are: page and dialog menus are no row menus
  for (const [f, why] of [['feeds.js', 'page menu'], ['budget.js', 'page menu'], ['office_letters.js', 'detail bar'], ['sprints.js', 'sprint bar'], ['widgets.js', 'start tiles drag']]) {
    check(!/cm_bind\(/.test(src(f)), `${f}: no row binding (${why})`);
  }

  w.close();
  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
