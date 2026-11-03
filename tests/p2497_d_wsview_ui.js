// kalmido-suite: fresh
// 2.497.0 (#4048) in a real browser: a workspace switch keeps the scroll position of a view per workspace (viewmem.js) and does not
// reopen a task kept for the view it enters: only a task already open stays. Computer and phone width.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2497_d_wsview_ui', check, shots: 'P2497D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,collab'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id, OW = 'org:' + ORG;
  const P = (await call('POST', '/api/lists', {name: 'Long', org_id: null})).id;
  const O = (await call('POST', '/api/lists', {name: 'Website', org_id: ORG})).id;
  const OT = (await call('POST', '/api/tasks', {title: 'Deploy', list_id: O})).id;
  for (let i = 0; i < 70; i++) await call('POST', '/api/tasks', {title: 'Row ' + i, list_id: P});
  for (const [wd, ht] of [[1200, 800], [390, 844]]) await firefox(async o => {
    const {cmd, ev, ctx} = o, tag = wd + ': ';
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(x => x.status)`) === 200, tag + 'login');
    await call('PATCH', '/api/settings', {workspace: 'private'});
    await o.nav(B + '#l/' + P);
    check(await o.until(`!!document.querySelector('#view .trow') && wsCur() === 'private'`, {timeout: 20000}), tag + 'the private list is there');
    // ---- the scroll position of the view stays with its workspace (the list goes -> the inbox and back: same page twice)
    const sw = ws => ev(`wsSet(${JSON.stringify(ws)}).then(() => 1)`);
    await o.nav(B + '#today'); await o.until(`S.route.key === 'today'`, {timeout: 10000});
    await o.nav(B + '#l/' + P); await o.until(`S.route.key === 'l:${P}' && !!document.querySelector('#view .trow')`, {timeout: 10000});
    const top = await ev(`(() => { const v = document.querySelector('#view'); v.scrollTop = 400; v.dispatchEvent(new Event('scroll')); return v.scrollTop; })()`);
    check(top > 100, tag + 'the list scrolls ' + top);
    await sw('all');  // "All" shows the list too: the page stays, the key changes
    await o.until(`wsCur() === 'all' && S.route.key === 'l:${P}'`, {timeout: 10000});
    await sw('private');
    check(await o.until(`wsCur() === 'private' && S.route.key === 'l:${P}' && Math.abs(document.querySelector('#view').scrollTop - ${top}) <= 2`, {timeout: 10000}), tag + 'back in the workspace: the view at its scroll position ' + await ev(`document.querySelector('#view').scrollTop`));
    // ---- a task kept for a view of the organisation does not open by the switch
    await sw(OW);
    await o.nav(B + '#inbox'); await o.until(`S.route.key === 'inbox'`, {timeout: 10000});
    await ev(`openDetail(${OT})`); await o.until(`S.sel === ${OT}`, {timeout: 10000});
    await o.nav(B + '#cal'); await o.until(`S.route.mod === 'cal'`, {timeout: 15000});  // the inbox keeps its open task (leaving a view)
    await ev(`closeDetail(true); 1`);
    await sw('private');
    await o.nav(B + '#inbox'); await o.until(`S.route.key === 'inbox' && wsCur() === 'private'`, {timeout: 10000});
    await sw(OW);
    await o.until(`S.route.key === 'inbox' && wsCur() === ${JSON.stringify(OW)} && VM.key.startsWith(${JSON.stringify(OW)})`, {timeout: 10000});
    check(await ev(`S.sel === null`), tag + 'the switch opens no task kept for the view: ' + await ev(`S.sel`));
    // leaving and coming back inside the workspace still brings the task back (#3439 unchanged)
    await o.nav(B + '#cal'); await o.until(`S.route.mod === 'cal'`, {timeout: 15000});
    await ev(`(() => { const a = (LS.get(VM_LS, {}) || {}), k = ${JSON.stringify(OW)} + '|t:inbox'; a[k] = {...(a[k] || {}), sel: ${OT}}; LS.set(VM_LS, a); return 1; })()`);
    await o.nav(B + '#inbox');
    check(await o.until(`S.route.key === 'inbox' && S.sel === ${OT}`, {timeout: 10000}), tag + 'inside the workspace the kept task still comes back');
    await ev(`closeDetail(true); 1`);
  }, false);
  console.log(`p2497_d_wsview_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
