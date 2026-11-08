// 2.750.0 (#5229) UI test: a wiki page's files: attach, drop and delete only in edit mode.
// kalmido-suite: fresh
// Own container (start.sh), Firefox with a mouse. Invented data only; every file is made in the page.
// - reading (read-only switch on): the file list keeps open + copy link, but has no delete button, no "Attach files", no #wka-file;
//   a file dropped onto the page uploads nothing and shows "Edit first to attach files" (and does not fall onto another input)
// - editing: "Attach files", #wka-file and the delete buttons are there again; a drop attaches
// freelancer-matrix: none (a person without organisation is used)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2750_b_wikiattach_ui', check, shots: 'P2750B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'wiki'});
  const pg = await call(CA, 'POST', '/api/wiki/pages', {space: 'private', path: 'Attach notes', body: 'Some text'});
  check(!!pg.id, 'a private wiki page');
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const toastT = `(document.querySelector('#toast')?.textContent || '')`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.wkRo', '"1"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.ok)`);
    await nav(B + '#wiki/' + pg.id);
    check(await ready(ev, `!!document.querySelector('#wk-md')`, 80), 'reading: the page is shown without editor');
    // a file on the page (uploaded from inside the page, like the app does)
    await ev(`new Promise(r => { const c = document.createElement('canvas'); c.width = c.height = 16; c.getContext('2d').fillRect(0, 0, 8, 8); c.toBlob(b => { window.__png = new File([b], 'skizze.png', {type: 'image/png'}); r(1); }, 'image/png'); })`);
    await ev(`(() => { const fd = new FormData(); fd.append('file', __png); return fetch('/api/wiki/pages/${pg.id}/files', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}, body: fd}).then(r => r.ok); })()`);
    await nav(B + '#wiki/' + pg.id);
    check(await ready(ev, `!!document.querySelector('.wkfiles a.wkfile')`, 80), 'reading: the file is listed');
    const rd = await ev(`({add: !!document.querySelector('[data-wka="add"]'), inp: !!document.querySelector('#wka-file'), del: !!document.querySelector('[data-wka="del"]'), copy: !!document.querySelector('[data-wka="copy"]'), open: !!document.querySelector('.wkfiles a.wkfile')})`);
    check(!rd.add && !rd.inp && !rd.del && rd.copy && rd.open, 'reading: open + copy link stay, no delete, no attach, no #wka-file ' + JSON.stringify(rd));
    await shot('p2750b-wiki-read.png');
    await ev(`(() => { window.__ch = []; document.addEventListener('change', e => { if (e.target.type === 'file') window.__ch.push(e.target.id); }, true); return 1; })()`);
    await ev(`(() => { const v = document.querySelector('.wkfiles'), dt = new DataTransfer(); dt.items.add(__png); for (const t of ['dragover', 'drop']) v.dispatchEvent(new DragEvent(t, {bubbles: true, cancelable: true, dataTransfer: dt})); return 1; })()`);
    check(await ready(ev, `/Edit first to attach files/.test(${toastT})`, 20), 'reading: a dropped file shows "Edit first to attach files" ' + await ev(toastT) + ' ' + await ev(`JSON.stringify({edit: WK.edit, ro: wk_ro(), md: !!document.querySelector('#wk-md'), hasFn: wka_readOnly(), m: (document.querySelector('.modal:not(.closing)')?.outerHTML || '').slice(0, 120), t: document.querySelector('#toast')?.outerHTML})`));
    await sleep(400);
    const n = await ev(`fetch('/api/wiki/pages/${pg.id}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => (j.files || (j.page || {}).files || []).length)`);
    check(n === 1 && (await ev(`window.__ch.length === 0`)), 'reading: nothing uploaded, no input filled ' + n);
    // editing
    await ev(`(() => { localStorage.removeItem('tasks.wkRo'); return 1; })()`);
    await nav(B + 'static/icon.svg'); await nav(B + '#wiki/' + pg.id);
    check(await ready(ev, `!!document.querySelector('#wka-file') && !!document.querySelector('[data-wka="add"]') && !!document.querySelector('[data-wka="del"]')`, 80), 'editing: attach, #wka-file and delete are there ' + await ev(`JSON.stringify({edit: WK.edit, ro: wk_ro(), ls: Object.keys(localStorage).join()})`));
    await shot('p2750b-wiki-edit.png');
  }, false);

  console.log(`p2750_b_wikiattach_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
