// 2.97.0 part D UI test (#2050), own container (start.sh), Firefox (real WebCrypto): a knowledge page of a space with the lock to
// another workspace. Alice locks her private space; the page menu offers "Move to another workspace…", the dialog warns that
// the pages are no longer end-to-end encrypted in the open organisation, a second question confirms it, the server then holds
// the plain page there; Undo encrypts it again for the private space (the old name, readable with the key). Lock -> lock:
// both pages of a folder re-encrypted for the organisation's key, the link between them follows. A person without an
// organisation: there is no other workspace (409). P297D_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p297_d_ui', check, shots: 'P297D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P297D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(250); } return fn(); };
const PASS = 'correct horse battery staple';
const M = 'QXZmark';  // every plain text of the moved pages carries it

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const feats = async ck => { const st = (await call('GET', '/api/state', null, ck)).j; await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: [...(st.settings?.features || '').split(',').filter(Boolean), 'wiki', 'collab'].join(',')}, ck); };
  await feats(CK);
  const ME = (await call('GET', '/api/state')).j.me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: ME})).j.id;
  const SP = 'org:' + ORG;
  const mk = async (p, body) => (await call('POST', '/api/wiki/pages', {space: 'private', path: p, body})).j.id;
  const P1 = await mk('Box/Plan', `${M} plan, see [[Box/Other]]`);
  const P2 = await mk('Box/Other', `${M} other`);
  check(P1 > 0 && P2 > 0, 'setup: two private pages in a folder');

  const session = (user, fn) => firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash); await waitFor('!!(window.S && S.booted)'); await sleep(500); };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.wkSpace', ${JSON.stringify(JSON.stringify('private'))}); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`) === 200, `Firefox: login ${user}`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#inbox');
    const unlock = () => ev(`(async () => { await e2eLoad(true); if (!E2E.st.set) return !!(await e2eCreate(${JSON.stringify(PASS)})); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS)})); return e2eUnlocked(); })()`);
    await fn({ev, waitFor, boot, unlock});
  }, false);

  await session('alice', async ({ev, waitFor, boot, unlock}) => {
    check(await unlock(), 'Alice sets up encryption');
    const st = await ev(`wkeStart('private').then(r => ({r, mode: wkeMode('private')})).catch(e => ({err: e.message}))`);
    check(st.r === true && st.mode === 'on', 'the private space is locked ' + JSON.stringify(st));
    let idx = (await call('GET', '/api/wiki?space=private&bodies=1')).j;
    check((idx.pages || []).length === 2 && idx.pages.every(x => x.path.startsWith('e2e1:')) && !JSON.stringify(idx).includes(M), 'the server keeps ciphers only');

    // ---- the page menu, the dialog with the warning, the second question, the move
    await boot('#wiki/' + P1);
    await ev(`(async () => { await wk_load('private', true); WK.pg = null; renderView(); return 1; })()`);
    check(await waitFor(`!!document.querySelector('#view [data-wk="pmenu"]')`), 'the page menu button');
    await ev(`(document.querySelector('#view [data-wk="pmenu"]')?.click(), 1)`);
    const sel = `[...document.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"]')]`;
    const labels = await waitFor(`${sel}.map(b => b.textContent.trim()).join('|') || ''`);
    check(/Move to another workspace…/.test(labels || ''), 'the page menu offers the move with the lock ' + labels);
    await ev(`(${sel}.find(b => b.textContent.trim() === 'Move to another workspace…')?.click(), 1)`);
    const notes = await waitFor(`(() => { const b = document.querySelector('.smv-dlg [data-smv="yes"]'); return b && !b.disabled && document.querySelector('.smv-dlg .smv-notes').textContent; })()`);
    check(/no longer end-to-end encrypted/.test(notes || ''), 'the dry run warns: no longer end-to-end encrypted ' + notes);
    await ev(`(document.querySelector('.smv-dlg [data-smv="yes"]').click(), 1)`);
    const ask = await waitFor(`document.querySelector('.cdlg')?.textContent || ''`);
    check(/no longer end-to-end encrypted/.test(ask || ''), 'a second question names the warning ' + (ask || '').slice(0, 120));
    await ev(`(document.querySelector('.cdlg [data-cd="yes"]')?.click(), 1)`);
    const moved = await until(async () => { const g = (await call('GET', '/api/wiki/pages/' + P1)).j; return g.space === SP && g; });
    check(moved && moved.path === 'Plan' && moved.body === `${M} plan, see [[Box/Other]]`, 'the page is plain and readable in the organisation ' + JSON.stringify(moved).slice(0, 200));

    // ---- Undo: encrypted again for the private space, the old name
    await ev(`histStep('undo')`);
    const back = await until(async () => { const g = (await call('GET', '/api/wiki/pages/' + P1)).j; return g.space === 'private' && g; });
    check(back && back.path.startsWith('e2e1:') && back.body.startsWith('e2e1:') && !JSON.stringify(back).includes(M), 'Undo: back in the private space as ciphers');
    const op = await ev(`(async () => { const p = await wkePage(await rawFetch('GET', '/api/wiki/pages/${P1}')); return {path: p.path, body: p.body, locked: !!p._wke}; })()`);
    check(op && op.path === 'Box/Plan' && op.body === `${M} plan, see [[Box/Other]]` && !op.locked, 'Undo: the old name and text open with the key ' + JSON.stringify(op));

    // ---- lock -> lock: the folder re-encrypted for the organisation, the link follows
    const so = await ev(`wkeStart(${JSON.stringify(SP)}).then(r => ({r, mode: wkeMode(${JSON.stringify(SP)})})).catch(e => ({err: e.message}))`);
    check(so.r === true && so.mode === 'on', 'the organisation space is locked too ' + JSON.stringify(so));
    const res = await ev(`(async () => { await wk_load('private', true); const r = await wkr_run('private', ${JSON.stringify(SP)}, [{id: ${P1}, path: 'Moved/Plan'}, {id: ${P2}, path: 'Moved/Other'}]);
      const p = await wkePage(await rawFetch('GET', '/api/wiki/pages/${P1}')); return {space: r.space, n: r.moved.length, path: p.path, body: p.body, locked: !!p._wke}; })().catch(e => ({err: e.message}))`);
    check(res && res.space === SP && res.n === 2, 'lock -> lock: both pages moved ' + JSON.stringify(res));
    check(res && res.path === 'Moved/Plan' && res.body === `${M} plan, see [[Moved/Other]]` && !res.locked, 'lock -> lock: readable with the organisation key, the link follows ' + JSON.stringify(res));
    idx = (await call('GET', '/api/wiki?space=' + SP + '&bodies=1')).j;
    check((idx.pages || []).length === 2 && !JSON.stringify(idx).includes(M), 'the organisation holds ciphers only');
  });

  // ---- a person without an organisation: no other workspace
  await call('POST', '/api/users', {username: 'dave', display_name: 'Dave', password: 'password123', email: 'dave@example.com', orgs: []});
  const DK = await login('dave');
  const DP = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Mine', body: 'x'}, DK)).j.id;
  check((await call('POST', '/api/wiki/move-space', {pages: [DP], space: 'private', to: SP, dry: 1}, DK)).status === 409, 'without an organisation: 409');

  console.log(`p297_d_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
