// 2.144.5 UI test, part A, own container (start.sh), jsdom (English, checks by classes / data attributes):
// - #2001: an approval card in a task comment shows Yes / No only to an approver (choice_can): the list owner sees the
//   buttons, an editor sees the waiting line instead; plain answer buttons stay for the editor
// - #2387: the recovery key box says, while the organisation's key is renewed, that the search may miss documents (F9);
//   the step-up of an SSO account: without a fresh sign-in it asks first (cancelled = nothing sent), with one it goes on;
//   back from the provider with an error the app says why (#rck-stepup-error=...); 2.144.5 A2 (review R1): only after an own
//   step-up of the same organisation + purpose (sessionStorage), a bare #rck-stepup link does nothing
// - #2387 F8: the HTTP Shortcuts download is fetched: a refusal shows the server's reason instead of a silent failure
// P21445A_NOSTART=1 = the container is running.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21445A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments'});
  const ed = await call(CA, 'POST', '/api/users', {username: 'ed', display_name: 'Ed Editor', password: 'password123', email: 'ed@example.com'});
  const CE = await login('ed');
  await call(CE, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Release work'})).id;
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'robo', display_name: 'Robo'});
  const AGH = {Authorization: 'Bearer ' + ag.token};
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: ed.id, role: 'edit'});
  await call(CA, 'PATCH', `/api/lists/${L}`, {agent_members: true});
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Publish the cut', list_id: L})).id;
  const AP = (await call(null, 'POST', `/api/v1/tasks/${T}/comments`, {body: 'Ready.', approval: {title: 'Publish the cut'}}, AGH)).id;
  const T2 = (await call(CA, 'POST', '/api/tasks', {title: 'Pick one', list_id: L})).id;
  const Q = (await call(null, 'POST', `/api/v1/tasks/${T2}/comments`, {body: 'Which one?', choices: ['Short', 'Long']}, AGH)).id;
  check(AP && Q, 'setup: an approval card and plain buttons');

  const card = async (w, tid, cid) => {
    w.eval(`openDetail(${tid})`);
    return until(() => w.document.querySelector(`#d-tl-items .cm[data-cid="${cid}"] .cccard, #d-tl-items .cm[data-cid="${cid}"] .cchoices`));
  };
  // ---- #2001: the owner of the list sees Yes / No
  let w = await boot({user: 'alice'});
  let c = await card(w, T, AP);
  check(c && c.querySelectorAll('.apvbtns .cchb').length === 2, '#2001: the list owner sees Yes / No ' + (c ? c.innerHTML.slice(0, 200) : 'no card'));
  // ---- #2387 F9: the renewal hint (state from the server's fields)
  const h = w.eval(`ocStateHtml({enabled: true, active: true, rotating: true})`), h0 = w.eval(`ocStateHtml({enabled: true, active: true, rotating: false})`);
  check(/ocrotsearch/.test(h) && /search may not find/.test(h) && !/ocrotsearch/.test(h0), 'F9: the search hint only while the key is renewed');
  // ---- #2387: the step-up of an SSO account
  w.eval(`window._p = ocStepUp(5, 'fresh', 'Show recovery key', {stepup: 'oidc', fresh: false})`);
  const dl = await until(() => w.document.querySelector('.cdlg'));
  check(dl && /login provider/.test(dl.textContent) && dl.querySelector('[data-cd="yes"]')?.textContent === 'Sign in again', '#2387: without a fresh sign-in it asks first: ' + (dl ? dl.textContent.slice(0, 160) : 'no dialog'));
  dl?.querySelector('[data-cd="no"]').click();
  const r1 = await w.eval('window._p');
  check(r1 === null && w.location.pathname === '/', '#2387: cancelled = nothing sent, no navigation');
  const r2 = await w.eval(`ocStepUp(5, 'fresh', 'Show recovery key', {stepup: 'oidc', fresh: true})`);
  check(r2 && typeof r2 === 'object' && !w.document.querySelector('.cdlg'), '#2387: after the step-up sign-in it goes on without asking');
  // 2.144.5 A2 (#2387, review R1): the way back counts only with the own pending step-up (sessionStorage), never a bare link
  w.eval(`window._oc = []; window._ocs = ocShowRecovery; window.ocShowRecovery = (...a) => { window._oc.push(a); }; sessionStorage.removeItem('rck-stepup')`);
  w.eval(`history.replaceState(null, '', '/#rck-stepup/5/new'); ocStepUpBack()`);
  await sleep(300);
  check(w.eval('window._oc.length') === 0 && w.location.hash === '' && !w.document.querySelector('.cdlg'), 'R1: a link to #rck-stepup without an own step-up does nothing');
  w.eval(`sessionStorage.setItem('rck-stepup', '5:show'); history.replaceState(null, '', '/#rck-stepup/5/new'); ocStepUpBack()`);
  await sleep(300);
  check(w.eval('window._oc.length') === 0 && w.eval(`sessionStorage.getItem('rck-stepup')`) === null, 'R1: a step-up for showing does not open a new key, the pending one is used up');
  w.eval(`sessionStorage.setItem('rck-stepup', '5:new'); history.replaceState(null, '', '/#rck-stepup/5/new'); ocStepUpBack()`);
  await sleep(300);
  const oc = w.eval('JSON.stringify(window._oc)');
  check(oc === JSON.stringify([[5, {step: 'fresh', fresh: true, fresh_new: true}, true, true]]) && w.eval(`sessionStorage.getItem('rck-stepup')`) === null,
    'R1: the own step-up goes on to the key: ' + oc);
  w.eval('window.ocShowRecovery = window._ocs');
  w.eval(`sessionStorage.setItem('rck-stepup', '5:show'); history.replaceState(null, '', '/#rck-stepup-error=auth_time'); ocStepUpBack()`);
  const tt = await until(() => { const e = w.document.querySelector('#toast'); return e && /auth_time/.test(e.textContent) ? e.textContent : ''; });
  check(/did not say when you signed in/.test(tt) && w.location.hash === '', '#2387: back with an error the app says why: ' + tt);
  // ---- #2387 F8: a refused download shows the reason
  w.eval(`window._f = window.fetch; window.fetch = async () => ({ok: false, status: 403, json: async () => ({error: 'Refused for a test reason'})}); S.me.drop_token_set = false`);
  w.eval(`(() => { const a = document.createElement('a'); a.href = '/api/me/share/httpshortcuts.zip'; a.setAttribute('download', 'x.zip'); tkh_zipClick({preventDefault() {}}, a, document.body); })()`);
  const t8 = await until(() => { const e = w.document.querySelector('#toast'); return e && /test reason/.test(e.textContent) ? e.textContent : ''; });
  check(/Refused for a test reason/.test(t8), 'F8: the refusal of the download is shown: ' + t8);
  w.eval('window.fetch = window._f');
  check(errs.length === 0, 'no JS errors (alice): ' + errs.slice(0, 3).join(' | '));
  w.close();

  // ---- #2001: an editor who is no approver sees the waiting line, plain buttons stay
  w = await boot({user: 'ed'});
  c = await card(w, T, AP);
  c = c && c.closest('.cccard');
  check(c && !c.querySelector('.apvbtns') && c.querySelector('.cpermst') && w.eval(`tlComment(${AP})?.choice_can`) === false,
    '#2001: the editor sees no Yes / No: ' + (c ? c.textContent.slice(0, 160) : 'no card'));
  c = await card(w, T2, Q);
  check(c && c.querySelectorAll('.cchb').length === 2, '#2001: plain answer buttons stay for the editor');
  check(errs.length === 0, 'no JS errors (ed): ' + errs.slice(0, 3).join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
