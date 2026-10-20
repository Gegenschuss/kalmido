// 2.87.9 UI tests, part E (polish), own container (start.sh). jsdom:
// - #1914 the list column "Date" is called "Due"
// - #1920 a document row has its own dots button (not a nested chevron); it and a right click open the shared More menu
// - #1933 the sidebar: search and workspace switch in one line (.sbsrch), the switch a round icon button with the dot
// - #1937 every dialog with a header is movable: a header inside a wrapper counts when it is the card's first header
// - #1963 the approval thumbs are app icons (no emoji)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  const offer = await call('POST', '/api/office/docs', {project_title: 'Imagefilm'});
  check(offer.http === 201, 'a quotation ' + offer.http);

  let w = await boot({hash: 'office/offers'}), d = w.document;
  await until(() => d.querySelector('.ofdlist .ofdrow'), 60);
  // ================= #1920
  const row = d.querySelector('.ofdlist .ofdrow'), more = d.querySelector('.ofdlist .ofdrmore');
  check(row && more && row.parentElement === more.parentElement && !row.querySelector('button, .ofdrmore') && more.getAttribute('aria-label') === 'More', '#1920: the row and its dots button are siblings, no button inside a button');
  click(w, more);
  const items = await until(() => { const x = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim()); return x.length && x; });
  check(items && ['Open', 'Duplicate', 'Preview (PDF)', 'Delete'].every(t => items.includes(t)), '#1920: the menu offers Open, Duplicate, Preview, Delete: ' + items);
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  row.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  check(await until(() => d.querySelector('#pop [role="menuitem"]')), '#1920: a right click on the row opens the same menu');
  w.close();

  // ================= #1914, #1933, #1937, #1963
  w = await boot({hash: 'inbox'}); d = w.document;
  await until(() => d.querySelector('#side .scmd'), 60);
  check(await w.eval(`tr(COLS.find(c => c[0] === 'due')[1])`) === 'Due', '#1914: the column is called Due');
  const bar = d.querySelector('#side .sbhead .wsbar');  // 2.138.1 (#2392): the button is the sidebar's heading
  check(d.querySelector('#side .sbdock .scmd') && bar && bar.querySelector('.wsn')?.textContent, '#1933: workspace button with its name in the row; 2.104.0 (#2161): search sits in the bottom dock' );
  const ok1 = await w.eval(`(() => {
    const md = modal('<div class="wrapx"><div class="lhdr"><h3>First</h3></div><div class="lhdr"><h3>Second</h3></div></div>');
    const h = md.querySelectorAll('.lhdr'), a = dw_card(h[0].querySelector('h3')), b = dw_card(h[1]);
    const r = [!!a, !b]; md.remove(); return r.join();
  })()`);
  check(ok1 === 'true,true', '#1937: the first header inside a wrapper moves the dialog, a second one does not: ' + ok1);
  const th = await w.eval(`thumbIc(true) + thumbIc(false)`);
  check(/svg/.test(th) && !/[\u{1F44D}\u{1F44E}]/u.test(th), '#1963: the approval thumbs are icons');
  w.close();

  // 2.87.9 (#1933, P4): a person without an organisation keeps the button; it names the private space, its menu has only that
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.http < 300, '#1933: a person without an organisation ' + fr.http);
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, FCK);
  w = await boot({user: 'frida', hash: 'inbox'}); d = w.document;
  const fbar = await until(() => d.querySelector('#side .sbhead .wsbar'), 60);  // 2.138.1 (#2392)
  check(fbar && /Private/.test(fbar.querySelector('.wsn')?.textContent || ''), '#1933: without an organisation the button stays and shows the private space');
  if (fbar) click(w, fbar);
  const fitems = await until(() => { const x = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim()); return x.length && x; });
  check(fitems && fitems.length === 1 && /Private/.test(fitems[0]), '#1933: its menu offers only the private space: ' + fitems);
  w.close();

  console.log(`p287b_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
