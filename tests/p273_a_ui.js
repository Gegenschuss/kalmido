// 2.73.0 UI tests (part A, #661), own container (start.sh with the app's own address allowed + a server key). jsdom:
// Settings > Account > Servers: this server's row (badge, name), "Add server" with a connection code (the test server
// connects to itself as "the other server"), the new row with badge + "Connected", the event msv:changed and msvLinks();
// Edit (short name, colour, quick-add default) as one undo step; Remove with the confirmation, one undo step brings it
// back; "Create a connection code" shows the code once with a copy button; a broken code shows the reason in the dialog.
// No token in the page.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const EXTRA = (process.env.EXTRA || '') + ' -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1 -e KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), _status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const recode = (code, u) => { const j = JSON.parse(Buffer.from(code.slice('kalmido-link:'.length), 'base64url').toString()); return {t: j.t, code: 'kalmido-link:' + Buffer.from(JSON.stringify({u, t: j.t})).toString('base64url')}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  const bc = await call('POST', '/api/servers/code', {name: 'Alice'}, CB);
  check(bc._status === 201 && bc.code, 'bob makes a connection code');
  const {code, t: TOK} = recode(bc.code, 'http://127.0.0.1:3040');

  const w = await boot({user: 'alice'}), d = w.document;
  let changed = 0; d.addEventListener('msv:changed', () => { changed++; });
  w.eval(`settingsModal('account')`);
  const box = () => d.querySelector('.smodal #s-msv');
  await until(() => box()?.querySelector('[data-msvid="self"]'));
  check(box()?.querySelector('[data-msvid="self"] .msvb')?.textContent.length >= 1, 'this server has a badge');
  check(/This server/.test(box()?.querySelector('[data-msvid="self"]')?.textContent || ''), 'this server is named');
  check(d.querySelector('#s-msv-h') && d.querySelector('.smodal details.sdev')?.previousElementSibling?.classList.contains('msvsec'),
    'the section stands above "Advanced · for developers"');
  check(/No other server connected yet/.test(box().textContent), 'the empty state');

  // ---- a broken code: the reason in the dialog
  click(w, d.querySelector('.smodal [data-msva="add"]')); await until(() => d.querySelector('.msvmodal'));
  let md = d.querySelector('.msvmodal');
  md.querySelector('#msv-code').value = 'kalmido-link:nonsense';
  click(w, md.querySelector('[data-m="ok"]'));
  await until(() => !md.querySelector('#msv-err').hidden);
  check(/not valid/.test(md.querySelector('#msv-err').textContent), 'a broken code: the reason in the dialog ' + md.querySelector('#msv-err').textContent);
  // ---- the right code
  md.querySelector('#msv-code').value = code; md.querySelector('#msv-name').value = 'Home';
  click(w, md.querySelector('[data-m="ok"]'));
  await until(() => !d.querySelector('.msvmodal') && box()?.querySelector('.msvrow:not([data-msvid="self"])'));
  const row = () => box()?.querySelector('.msvrow:not([data-msvid="self"])');
  check(row() && row().querySelector('.msvb')?.textContent === 'HO' && row().textContent.includes("Home") && /Connected/.test(row().textContent),
    'the new account: badge, name, connected ' + (row()?.textContent || ''));
  check(changed >= 1, 'msv:changed after adding');
  const links = await w.eval('msvLinks()');
  check(links.length === 1 && links[0].name === 'Home' && links[0].remote_me.name === 'Bob', 'msvLinks() for the combined views');
  check(!d.body.innerHTML.includes(TOK), 'no token in the page');
  const SID = links[0].id;

  // ---- edit: short name, colour, quick add default; one undo step
  click(w, row().querySelector('[data-msva="edit"]')); await until(() => d.querySelector('.msvmodal'));
  md = d.querySelector('.msvmodal');
  check(md.querySelector('#msv-en').value === 'Home' && md.querySelectorAll('[data-msvcol]').length === 12, 'the edit dialog: name, 12 colours');
  const es = md.querySelector('#msv-es'); es.value = 'h2x'; es.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(es.value === 'H2X' && md.querySelector('.msvprev').textContent === 'H2X', 'the short name in capitals, the preview follows');
  const col = [...md.querySelectorAll('[data-msvcol]')].find(b => b.getAttribute('aria-pressed') !== 'true');
  click(w, col);
  md.querySelector('#msv-ei').checked = true;
  const topE = w.eval('HIST.undo[HIST.undo.length - 1]');  // 2.284.0 A (#3120): undo only once the edit's step is there
  click(w, md.querySelector('[data-m="ok"]'));
  await until(() => !d.querySelector('.msvmodal') && row()?.querySelector('.msvb')?.textContent === 'H2X');
  let st = await call('GET', '/api/servers');
  check(st.links[0].short === 'H2X' && st.links[0].color === col.dataset.msvcol && st.links[0].default_inbox === true, 'saved: short name, colour, quick add here');
  check(/Quick add lands here/.test(row().textContent) && !/Quick add lands here/.test(box().querySelector('[data-msvid="self"]').textContent),
    'the row says quick add lands there (not on this server any more)');
  await until(() => !w.eval('HIST.busy') && w.eval('HIST.undo[HIST.undo.length - 1]') !== topE);
  w.eval(`histStep('undo')`);
  await until(async () => (await call('GET', '/api/servers')).links[0].short === 'HO');
  st = await call('GET', '/api/servers');
  check(st.links[0].short === 'HO' && st.links[0].default_inbox === false, 'one undo step brings the old values back');

  // ---- remove with the confirmation, undo
  await until(() => row());
  // 2.284.0 A (#3120): Mac red 2x - the undo came before the removal's step (or while the undo above still ran: histStep
  // ignores a call during HIST.busy); wait for a new top step and no undo running
  const top0 = w.eval('HIST.undo[HIST.undo.length - 1]');
  click(w, row().querySelector('[data-msva="del"]')); await until(() => d.querySelector('.cdlg'));
  check(/revoke/.test(d.querySelector('.cdlg').textContent), 'the confirmation names revoking the token over there');
  d.querySelector('.cdlg [data-cd="yes"]').click();
  await until(async () => (await call('GET', '/api/servers')).links.length === 0);
  await until(() => !row());
  check(!row(), 'removed');
  await until(() => !w.eval('HIST.busy') && w.eval('HIST.undo[HIST.undo.length - 1]') !== top0);
  w.eval(`histStep('undo')`);
  await until(async () => (await call('GET', '/api/servers')).links.length === 1);
  check((await call('GET', '/api/servers')).links[0]?.id === SID, 'undo brings the same account back');

  // ---- a connection code for another server
  click(w, d.querySelector('.smodal [data-msva="code"]')); await until(() => d.querySelector('.msvmodal'));
  md = d.querySelector('.msvmodal');
  check(md.querySelector('.msvout').hidden && md.querySelector('[data-m="copy"]').hidden, 'before: no code, no copy button');
  md.querySelector('#msv-cn').value = 'Phone';
  click(w, md.querySelector('[data-m="ok"]'));
  await until(() => !md.querySelector('.msvout').hidden);
  check(/^kalmido-link:/.test(md.querySelector('#msv-cv').value) && !md.querySelector('[data-m="copy"]').hidden && md.querySelector('[data-m="ok"]').hidden,
    'the code shown once, with a copy button');
  const toks = await call('GET', '/api/me/tokens');
  check(toks.tokens.some(t => t.name === 'Kalmido-App: Phone'), 'the token is in Settings > Account > API tokens');
  click(w, md.querySelector('[data-m="close"]'));

  check(!errs.length, 'no script errors ' + errs.slice(0, 3).join(' | '));
  console.log(`p273_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
