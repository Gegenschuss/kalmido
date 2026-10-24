// 2.298.0 C (#3187) UI tests: less text in knowledge, agents, settings and account. Own container (start.sh). Invented names only.
// - status codes in words: a failed request without a server text says "File too large" (413), "Too many requests, wait a
//   moment" (429), "Server error, please try again later" (5xx), else "Error 404"; a bare 404 of the server says
//   "Not found. Maybe deleted or no longer shared with you." (also for a person without an organisation)
// - the chat's "Ctrl+Enter sends" shows until the first message sent on this device, then stays away (the button's title keeps it)
// - encryption: the loss warning stays word for word and visible, "Protects against ..." sits in the fold-out "What it
//   protects, and what not" (project dialog and knowledge space)
// - Settings > Share from your phone: the Android steps are folded, one token hint (kept visible)
// - the agent dots name their state (title)
// freelancer-matrix: settings
// P2298C_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2298C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 60, ms = 150) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(ms); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,wiki,files';
const NF = 'Not found. Maybe deleted or no longer shared with you.';
const WARN = 'Passphrase and recovery code lost = the contents are lost. Nobody can restore them, not even the operator.';
const WARN_WIKI = 'The keys hang on your passphrase and your recovery code. Without both the pages are lost; nobody can restore them, not even the operator.';

async function statusWords(user) {
  const w = await boot({user}), d = w.document;
  check(w.eval(`httpErrText(413)`) === 'File too large', `${user}: 413 in words`);
  check(w.eval(`httpErrText(429)`) === 'Too many requests, wait a moment', `${user}: 429 in words`);
  check(w.eval(`httpErrText(500)`) === 'Server error, please try again later' && w.eval(`httpErrText(503)`) === 'Server error, please try again later', `${user}: 5xx in words`);
  check(w.eval(`httpErrText(404)`) === 'Error 404', `${user}: any other code stays "Error 404"`);
  // a bare 404 of the server reaches the toast with its words (core.js api() -> e.message)
  const msg = await w.eval(`api('GET', '/api/wiki/pages/999999').then(() => 'ok', e => e.message)`);
  check(msg === NF, `${user}: a missing page says what happened: ${msg}`);
  // Share from your phone: Android steps folded, one token hint that stays visible
  w.eval(`settingsModal('share')`);
  const sec = await until(() => d.querySelector('#s-share-h') && d.querySelector('#s-hszip')?.closest('.spane, [data-pane], .smodal'));
  const det = d.querySelector('#s-hszip')?.parentElement?.nextElementSibling;
  check(det?.tagName === 'DETAILS' && !det.open && /HTTP Shortcuts/.test(det.textContent) && /How to set it up/.test(det.querySelector('summary')?.textContent || ''),
    `${user}: the Android steps are folded ` + (det?.tagName || 'none'));
  const tok = [...(sec || d).querySelectorAll('.shint.keep')].find(x => /upload token is like a password/.test(x.textContent));
  check(tok && /A new one makes old shortcuts invalid/.test(tok.textContent), `${user}: one token hint, kept visible`);
  check(!/Each download contains a new upload token|After a new token: paste it/.test(sec?.textContent || ''), `${user}: the two other token hints are gone`);
  w.close();
}

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  check(bob.http < 300, 'bob ' + bob.http);
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');

  await statusWords('alice');
  await statusWords('frida');

  // ---- the key hint until the first message sent on this device
  const bobId = bob.id || bob.user?.id;
  const dm = await call(CA, 'POST', '/api/team/dm', {user_id: bobId}), rid = dm.id || dm.room?.id;
  check(!!rid, 'a direct conversation ' + JSON.stringify(dm).slice(0, 120));
  let w = await boot({user: 'alice', hash: 'team/' + rid}), d = w.document;
  await until(() => d.querySelector('#tc-in') && d.querySelector('.tccomp .chkh'));
  check(/^(Ctrl|Cmd)\+Enter sends$/.test(d.querySelector('.tccomp .chkh')?.textContent || ''), 'before the first message: the visible hint ' + d.querySelector('.tccomp .chkh')?.textContent);
  d.querySelector('#tc-in').value = 'Hallo Bob';
  click(w, d.querySelector('[data-act="tc-send"]'));
  const sent = await until(async () => ((await call(CB, 'GET', `/api/team/rooms/${rid}/messages`)).messages || []).some(m => /Hallo Bob/.test(m.body || m.text || '')));
  check(sent, 'the message arrived');
  check(await until(() => (d.querySelector('.tccomp .chkh')?.textContent ?? '') === ''), 'after the first message: the hint is gone ' + JSON.stringify(d.querySelector('.tccomp .chkh')?.textContent));
  check(w.eval(`chatKeyHintVis()`) === '' && /Enter sends/.test(w.eval(`chatKeyHint()`)), 'the button title keeps it, the visible line stays away');
  check(w.eval(`localStorage.getItem('tasks.chatSent')`) === '1', 'remembered on this device');
  // the agent dots name their state
  check(/title="waiting for you"/.test(w.eval(`hdot('waiting')`)) && /title="offline"/.test(w.eval(`hdot('offline')`)), 'a status dot names its state');
  w.close();
  // another device (fresh storage): the hint is there again
  w = await boot({user: 'alice', hash: 'team/' + rid}); d = w.document;
  await until(() => d.querySelector('.tccomp .chkh'));
  check(/Enter sends/.test(d.querySelector('.tccomp .chkh')?.textContent || ''), 'a device that never sent: the hint shows');

  // ---- encryption notices: the warning word for word and visible, the protection details in the fold-out
  const box = d.createElement('div'); box.innerHTML = w.eval('wkeNoteHtml()'); d.body.appendChild(box);
  const li = [...box.querySelectorAll('ol.le2unote > li')].map(x => x.textContent);
  check(li.includes(WARN_WIKI), 'knowledge space: the loss warning stays word for word in the visible list');
  const wd = box.querySelector('details.le2uwhat');
  check(wd && !wd.open && /What it protects, and what not/.test(wd.querySelector('summary').textContent) && /Protects against a database leak/.test(wd.textContent)
    && !li.some(x => /Protects against a database leak/.test(x)), 'knowledge space: "Protects against" in the fold-out');
  box.remove();
  w.eval(`e2eEnsure = async () => true; le2u_info = async () => ({blockers: [], members: [{user_id: S.me.id, name: 'Alice', has_keys: true}, {user_id: 99, name: 'Carol', has_keys: false}]}); le2u_startDlg(1); 1`);
  const dlg = await until(() => d.querySelector('.cdlg .le2unote') && d.querySelector('.cdlg'));
  const vis = [...(dlg?.querySelectorAll('ol.le2unote > li') || [])].map(x => x.textContent);
  check(vis[0] === WARN, 'project: the loss warning first and word for word ' + vis[0]);
  check(vis.some(x => /no agents, no tasks by e-mail/.test(x)) && /Carol: not set up yet/.test(dlg?.textContent || ''), 'project: the consequences and who lacks a key stay visible');
  const pd = dlg?.querySelector('details.le2uwhat');
  check(pd && !pd.open && /Protects against a database leak/.test(pd.textContent) && /Encrypted: titles/.test(pd.textContent) && /recovery code is enough/.test(pd.textContent)
    && !vis.some(x => /Protects against/.test(x)), 'project: protection, field list and recovery code in the fold-out');
  w.close();

  console.log(`p2298_c_lesstext_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
