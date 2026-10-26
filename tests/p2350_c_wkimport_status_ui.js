// kalmido-suite:
// 2.350.0 C (#2744) UI tests (own container, start.sh), jsdom: a running knowledge import stays findable.
// - a click next to the import window / Esc while it runs = "In the background" with a note that says where the status is
//   (it used to close silently)
// - while it runs: "Import running · 33 %" on top of the knowledge pages and the percent at Knowledge in the bar, also after
//   a redraw; a click on either opens the window again; gone once the import ended (its report comes as before)
// - after a reload (wki_resume) and for a locked space (the browser import) the same; computer and phone
// freelancer-matrix: wiki (the import runs in the private space of a person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2350C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
// a small ZIP made here: two pages
const ZIP = execFileSync('python3', ['-c', `
import io, sys, zipfile
b = io.BytesIO()
with zipfile.ZipFile(b, "w") as z:
    z.writestr("Import/Eins.md", "# Eins\\n")
    z.writestr("Import/Zwei.md", "# Zwei\\n")
sys.stdout.buffer.write(b.getvalue())`]);
const json = j => new Response(JSON.stringify(j), {status: 200, headers: {'Content-Type': 'application/json'}});
// the server's answers about the import held at "running" while hold.on (the unpacking of a large archive takes a while)
function holdServer(w, hold) {
  const f0 = w.fetch;
  w.fetch = async (u, o = {}) => {
    const url = String(u);
    if (hold.on && (o.method || 'GET') === 'GET' && /\/api\/wiki\/import\/upload\/[^/?]+$/.test(url)) return json({id: url.split('/').pop(), state: 'running', space: 'private', progress: hold.progress});
    if (hold.on && hold.current && (o.method || 'GET') === 'GET' && /\/api\/wiki\/import\/upload$/.test(url)) {
      const j = await (await f0(u, o)).json(); return json({...j, current: hold.current});
    }
    return f0(u, o);
  };
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  check(!(st0.me.workspaces || []).length, 'setup: frida has no organisation');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});

  // ================= a computer
  let w = await boot({user: 'frida', hash: 'wiki', ls: {'tasks.wkSpace': JSON.stringify('private')}}), d = w.document;
  check(await until(() => typeof w.wki_start === 'function'), 'the knowledge module is there');
  const hold = {on: true, progress: {done: 1, total: 3}};
  holdServer(w, hold);
  const box = () => d.querySelector('.modal .wki-box');
  const note = () => d.querySelector('#view .wki-st');
  const dot = () => d.querySelector('[data-sbb="wiki"] .wki-dot, [data-go="wiki"] .wki-dot');
  const toastHas = re => re.test(d.querySelector('#toast')?.textContent || '');
  await w.wki_start('private', new w.File([ZIP], 'wiki.zip', {type: 'application/zip'}));
  check(await until(() => /Unpacking: 1 of 3 files/.test(box()?.textContent || '')), 'the window shows the unpacking ' + (box()?.textContent || '-') + ' | ' + w.eval('JSON.stringify(WKI.cur) + " " + WKI.up') + ' | ' + (d.querySelector('#toast')?.textContent || ''));
  if (!box()) { console.log(`${ok} ok, ${F.length} failed`); process.exit(1); }
  // a click next to the window: like "In the background", with the note
  const md = box().closest('.modal');
  md.dispatchEvent(new w.MouseEvent('mousedown', {bubbles: true, cancelable: true}));
  check(await until(() => !box()), 'a click next to the window closes it');
  check(await until(() => toastHas(/goes on in the background/) && toastHas(/at Knowledge in the bar and on top of the knowledge pages/)), 'the note says where the status is: ' + (d.querySelector('#toast')?.textContent || '-'));
  check(await until(() => /Import running · 33 %/.test(note()?.textContent || '')), 'on top of the knowledge pages: Import running · 33 % ' + (note()?.textContent || '-'));
  check(await until(() => dot()?.textContent === '33 %'), 'at Knowledge in the bar: 33 % ' + (dot()?.textContent || '-'));
  hold.progress = {done: 2, total: 3};
  check(await until(() => /Import running · 66 %/.test(note()?.textContent || '') && dot()?.textContent === '66 %'), 'the note follows the progress');
  w.eval('render()');
  check(await until(() => note() && dot(), 10), 'after a redraw both are still there ' + !!note() + ' ' + !!dot() + ' ' + [...d.querySelectorAll('[data-sbb="wiki"], [data-go="wiki"]')].map(e => e.parentElement?.id + ':' + e.outerHTML.slice(0, 160)).join(' || '));
  // a click on the note opens the window again
  note().click();
  check(await until(() => /Unpacking: 2 of 3 files/.test(box()?.textContent || '')), 'a click on the note opens the window again');
  d.querySelector('.modal [data-wki="bg"]').click();
  check(await until(() => !box()), '"In the background" closes it');
  // a click on the percent at Knowledge in the bar too; Esc = in the background
  dot().click();
  check(await until(() => box()), 'a click on the percent in the bar opens the window again');
  check(/#wiki/.test(w.location.hash), '… and stays on the knowledge pages');
  d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  check(await until(() => !box()), 'Esc closes it');
  // the end: the report as before, the notes go
  hold.on = false;
  check(await until(() => /2 pages imported/.test(d.body.textContent)), 'the import ends with its report');
  check(await until(() => !note() && !dot()), 'the notes are gone after the end');
  // a locked space imports in the browser: the same note
  w.eval(`WKI.cur = {state: 'e2e', abort: false, done: 1, total: 4}; wki_mark()`);
  check(await until(() => /Import running · 25 %/.test(note()?.textContent || '')), 'a locked space: the note too');
  note().click();
  check(await until(() => /1 of 4 pages/.test(box()?.textContent || '')), 'a locked space: the click opens the window with the pages');
  w.eval(`WKI.cur = null; wki_mark(); modalClose(WKI.md)`);
  check(await until(() => !box() && !note()), 'a locked space: gone with the end');
  w.close();

  // ================= a phone, after a reload: the import found again (wki_resume)
  w = await boot({user: 'frida', mobile: true, hash: 'wiki', ls: {'tasks.wkSpace': JSON.stringify('private')}}); d = w.document;
  check(await until(() => typeof w.wki_resume === 'function'), 'phone: the knowledge module is there');
  const hold2 = {on: true, progress: {done: 2, total: 4}, current: {id: 'p2350c-gone', state: 'running', space: 'private', progress: {done: 2, total: 4}}};
  holdServer(w, hold2);
  w.eval('WKI.cur = null; wki_resume()');
  const note2 = () => d.querySelector('#view .wki-st');
  check(await until(() => /Import running · 50 %/.test(note2()?.textContent || '')), 'phone, after a reload: the note ' + (note2()?.textContent || '-'));
  note2().click();
  const box2 = () => d.querySelector('.modal .wki-box');
  check(await until(() => /Unpacking: 2 of 4 files/.test(box2()?.textContent || '')), 'phone: a click opens the window');
  box2().closest('.modal').dispatchEvent(new w.MouseEvent('mousedown', {bubbles: true, cancelable: true}));
  check(await until(() => !box2() && /at Knowledge in the bar/.test(d.querySelector('#toast')?.textContent || '')), 'phone: a click next to it = in the background with the note');
  hold2.on = false; hold2.current = null;  // the server knows no such import: the note goes
  check(await until(() => !note2()), 'phone: gone once the server knows it no more');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
