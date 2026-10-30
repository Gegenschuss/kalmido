// kalmido-suite: fresh
// 2.425.0 C UI tests (#3453), jsdom, own container (start.sh). freelancer-matrix: files (frida has no organisation, her own office)
// - Settings > Integrations has a card and a section "Receipt fetcher" below the folder watcher (only with the office)
// - "Create setup code" shows the code once (kalmido-fetch:1:...); the helper's report draws its portals with state and error
// - the portal's switch turns it off for the helper; disconnecting asks first and removes it
// - the error notice in News names the portal and its error
// - an account without the office has neither card nor section
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2425C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const DESK = {'(hover:hover) and (pointer:fine)': true};
const keyOf = code => JSON.parse(Buffer.from(code.slice('kalmido-fetch:1:'.length), 'base64url').toString()).key;
const report = (key, portals) => fetch(B + 'api/v1/fetcher/status', {method: 'PUT', headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + key}, body: JSON.stringify({portals})});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  for (const u of ['frida', 'gina']) await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`, orgs: []});
  const CF = await login('frida'), CG = await login('gina');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'files,docs,comments,collab,office'}, CF);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'files,docs,comments,collab'}, CG);
  check(((await call('GET', '/api/state', null, CF)).me.workspaces || []).length === 0, 'frida has no organisation');

  // ---- frida: the section, the setup code, the portals
  const w = await boot({user: 'frida', media: DESK}), d = w.document;
  // 2.425.0 (#3453 review): the notification row is there before the documents' code is loaded (docfetch.js comes lazily)
  check(w.eval("NOTIF_ROWS.some(r => r[0] === 'fetcher')"), 'the notification row "Receipt fetcher" is there right after the start (lazy docfetch.js loaded: ' + w.eval("typeof fx_html === 'function'") + ')');
  await until(() => w.eval('S.booted && typeof dsc_integrDraw === "function" && typeof fx_draw === "function"'), 60);
  w.eval(`settingsModal('integr')`);
  check(!!await until(() => d.querySelector('.icard[data-jump="#s-fetch-h"]')), 'Integrations: a card "Receipt fetcher"');
  check(!!await until(() => d.querySelector('#s-fetch .fx-new')), 'Integrations: the section is drawn with "Connect a receipt fetcher"');
  const hs = [...d.querySelectorAll('h4')].map(h => h.id);
  check(hs.indexOf('s-fetch-h') === hs.indexOf('s-scan-h') + 1, 'right below "Scans from your computer" ' + JSON.stringify(hs));
  check(/never stores passwords, cookies or logins/.test(d.querySelector('#s-fetch').textContent), 'it says that Kalmido stores no logins');
  d.querySelector('#fx-name').value = 'Mac Studio';
  click(w, d.querySelector('#s-fetch [data-fx="new"]'));
  const codeEl = await until(() => d.querySelector('#fx-code'));
  const code = codeEl?.value || '';
  check(code.startsWith('kalmido-fetch:1:') && d.activeElement === codeEl, 'the setup code is shown once and focused');
  const key = code ? keyOf(code) : '';
  check(key.startsWith('kbh_'), 'the code carries the key');
  check(/Mac Studio/.test(d.querySelector('#s-fetch .fx-one')?.textContent || '') && /appear here after the first report/.test(d.querySelector('#s-fetch').textContent),
    'the fetcher is listed, its portals follow after the first report');
  check((await report(key, [{key: 'amazon', name: 'Amazon', last_run: new Date().toISOString(), new: 3, error: 'Amazon: please sign in again'}])).ok, 'the helper reports');
  await w.eval(`fx_draw(document)`);
  const row = await until(() => d.querySelector('#s-fetch .fx-portal'));
  check(row && /Amazon/.test(row.textContent) && /3 new receipts/.test(row.textContent) && row.classList.contains('fx-err')
    && /please sign in again/.test(row.querySelector('.fx-errtxt')?.textContent || ''), 'the portal with its new receipts and its error ' + (row?.textContent || '').replace(/\s+/g, ' '));
  check(!d.querySelector('#fx-code') || d.querySelector('#fx-code').value === code, 'the code stays while the dialog is open');
  // the switch
  const cb = row.querySelector('input[type="checkbox"]');
  check(cb && cb.checked, 'the portal is on');
  cb.checked = false; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await (await fetch(B + 'api/v1/fetcher', {headers: {Authorization: 'Bearer ' + key}})).json()).portals?.[0]?.enabled === false),
    'switched off: the helper reads enabled false');
  check(d.querySelector('#s-fetch .fx-portal').classList.contains('off'), 'the row shows it is off');
  // the News text
  const items = (await call('GET', '/api/news', null, CF)).items || [];
  const it = items.find(x => x.kind === 'fetcherr');
  if (it) await until(() => w.eval(`typeof newsText === 'function'`) || (w.eval(`typeof loadModule === 'function' && loadModule('collab')`), false), 20);
  const nt = it ? w.eval(`typeof newsText === 'function' ? newsText(${JSON.stringify(it)}, {}) : ''`) : '';
  check(it && /Receipt fetcher .*Amazon.*please sign in again/.test(String(nt).replace(/<[^>]+>/g, '')), 'the News item names the portal and the error: ' + nt);
  // disconnect
  click(w, d.querySelector('#s-fetch [data-fx^="del:"]'));
  const yes = await until(() => d.querySelector('.cdlg-f [data-cd="yes"]'));
  check(yes && /Disconnect the receipt fetcher/.test(d.querySelector('#cdlg-t')?.textContent || ''), 'disconnecting asks first');
  if (yes) click(w, yes);
  check(await until(() => !d.querySelector('#s-fetch .fx-one') && d.querySelector('#s-fetch .fx-new')), 'disconnected: the fetcher is gone from the list');
  check((await fetch(B + 'api/v1/fetcher', {headers: {Authorization: 'Bearer ' + key}})).status === 401, 'and its key stops (401)');
  w.close();

  // ---- gina without the office: nothing
  const w2 = await boot({user: 'gina', media: DESK}), d2 = w2.document;
  await until(() => w2.eval('S.booted && typeof dsc_integrDraw === "function"'), 60);
  w2.eval(`settingsModal('integr')`);
  await until(() => d2.querySelector('#s-scan .dsc-way'));
  check(!d2.querySelector('.icard[data-jump="#s-fetch-h"]') && !d2.querySelector('#s-fetch'), 'gina (no office): neither card nor section');
  w2.close();

  console.log(`p2425_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
