// 2.46.6 UI tests, part D, own container (start.sh), Firefox (1440 x 900):
// - #1711: the pen next to "Yes" on an approval card (task comment): a tap writes "Yes, but: <card title>" into the comment
//   box (text already there stays), nothing is sent, the card stays open; the agent chat's card has the pen too, a
//   permission question (chatPerm) does not
// - #1713: the setup command carries the account language (--lang / -Lang)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2466_d_ui', check, shots: 'P2466D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Agent work'})).id;
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AGH = {Authorization: 'Bearer ' + ag.token};
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Release the draft', list_id: L})).id;
  const AP = (await call(null, 'POST', `/api/v1/tasks/${T}/comments`, {body: 'Ready to publish.', approval: {title: 'Publish the draft', what: 'it goes online'}}, AGH)).id;
  check(AP, 'the agent posts an approval card (setup)');

  await firefox(async o => {
    const {ev, nav, cmd, ctx} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(() => 1)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    check(await ready(`typeof ccCommentHtml === 'function'`), 'Firefox: the list');
    await ev(`(() => { openDetail(${T}); return 1; })()`);
    const sel = `#d-tl-items .cm[data-cid="${AP}"] .cccard.apvopen`;
    check(await ready(`!!document.querySelector('${sel} .cchw .cchpen')`), '#1711: the pen sits next to Yes on the open approval card');
    check(await ev(`document.querySelectorAll('${sel} .cchb').length === 2`), '#1711: Yes and No are still the two answer buttons');
    await ev(`(() => { const i = document.querySelector('#c-input'); i.value = 'Thanks'; i.dispatchEvent(new Event('input', {bubbles: true})); document.querySelector('${sel} .cchpen').click(); return 1; })()`);
    await sleep(300);
    check(await ev(`document.querySelector('#c-input').value === 'Thanks Yes, but: Publish the draft' && S.tl.comments.length === 1`), '#1711: the pen adds "Yes, but: <title>" after the text, nothing is sent');
    check(await ev(`!!document.querySelector('${sel}') && !document.querySelector('${sel} .cpermst')`), '#1711: the card stays open');
    // the agent chat: the approval card has the pen, a permission question does not
    check(await ev(`ccApvBtns({choices: [{id: 'yes', label: 'Yes'}, {id: 'no', label: 'No'}], approval: {title: 'X', std: 1}}, id => 'data-x="' + id + '"', 'data-chpen="5" data-cid="yes"').includes('cchpen')`), '#1711: the shared buttons render the pen when asked for');
    check(await ev(`!ccApvBtns({choices: [], approval: {title: 'X', std: 1}}, id => '').includes('cchpen')`), '#1711: no pen by default');
    check(await ev(`apvBtns({id: 7, choices: {choices: [{id: 'yes', label: 'Yes'}, {id: 'no', label: 'No'}], approval: {title: 'Deploy', std: 1}}}).includes('data-chpen="7"')`), '#1711: the chat approval card has the pen');
    check(await ev(`!chatPermHtml({id: 8, from: 'agent', body: 'May I?', choices: {choices: [{id: 'allow', label: 'Allow'}, {id: 'deny', label: 'Deny'}], permission: {tool: 'Bash'}}}, 'open').includes('cchpen')`), '#1711: a permission question has no pen');
    // #1713: the language goes into the command
    check(await ev(`(() => { S.settings.lang = 'de'; LS.set('lang', 'de'); return ains_command('mac', 'https://k.example.com', 'ks_x', '~/p').endsWith(" --lang de") && ains_command('windows', 'https://k.example.com', 'ks_x', '~\\\\p').endsWith(" -Lang de"); })()`), '#1713: de account -> --lang de / -Lang de');
    check(await ev(`(() => { S.settings.lang = 'fr'; LS.set('lang', 'fr'); return ains_command('mac', 'https://k.example.com', 'ks_x', '~/p').endsWith(" --lang en"); })()`), '#1713: another language -> en');
  }, false);

  console.log(`p2466_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
