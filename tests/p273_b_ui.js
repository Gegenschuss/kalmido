// 2.73.0 UI tests (part B, #1473), own container (start.sh). Invented names only. jsdom:
// Settings > Data > "Move and export everything": the section with the steps "Move to your own server"; "Export everything"
// starts the export, the state turns into a download link; an upload (made over the API: the pieces) shows its preview in the
// section after opening it again (the source person, the counts, the people with "found" and a tick that is off); with the
// tick the import starts, the result names the counts and offers undo; undo asks, then removes the imported list.
// Part 4: an uploaded organisation export asks for the recovery key in the section; a wrong key is named, the right one
// opens the preview (organisation export, the tick adds to the organisation, no private space as target).
// Firefox 390 touch: the section fits the phone, screenshot.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p273_b_ui', check, shots: 'P273B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const KEY = require('crypto').randomBytes(32).toString('base64');  // the organisation export needs the server key
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: `${process.env.EXTRA || ''} -e KALMIDO_SECRET_KEY=${KEY}`}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab';
async function dataPane(w) {
  w.eval(`settingsModal()`); await sleep(400);
  const md = w.document.querySelector('.smodal');
  click(w, md.querySelector('.snav [data-sec="data"]')); await sleep(500);
  return w.document.querySelector('.smodal');
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice Umzug', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call(CA, 'POST', '/api/users', {orgs: [1], username: 'bob', display_name: 'Bob Neu', password: 'password123', email: 'bob@example.com'});
  const carol = await call(CA, 'POST', '/api/users', {orgs: [1], username: 'carol', display_name: 'Carol Team', password: 'password123', email: 'carol@example.com'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Umzug UI Liste', org_id: null})).id;
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: carol.id, role: 'edit'});
  await call(CA, 'POST', '/api/tasks', {title: 'Kiste UI packen', list_id: L});

  // ================= the export in the section
  let w = await boot({user: 'alice'});
  let md = await dataPane(w);
  check(md.querySelector('#s-umz-h') && /Move and export everything/.test(md.querySelector('#s-umz-h').textContent), 'the section is there');
  check(md.querySelector('.umzhow summary') && /Move to your own server/.test(md.querySelector('.umzhow').textContent) && md.querySelectorAll('.umzsteps li').length === 4,
    'the steps "Move to your own server"');
  check(md.querySelector('a[href="/api/export.json"]'), 'the JSON export stays');
  const eb = await until(() => md.querySelector('#s-umz-exp [data-umz="exp"]'));
  check(eb && /Export everything/.test(eb.textContent), '"Export everything"');
  click(w, eb);
  const dl = await until(() => md.querySelector('#s-umz-exp a[href="/api/account/export/file"]'), 100);
  check(dl && /kalmido-account-/.test(md.querySelector('#s-umz-exp').textContent), 'the export is ready: download link');
  check(md.querySelector('#s-umz-exp [data-umz="exp-del"]'), '"Delete now"');
  w.close();

  // the file, uploaded by bob in pieces (the API; the app sends the same requests)
  const zr = await fetch(B + 'api/account/export/file', {headers: {Cookie: CA}});
  const zip = Buffer.from(await zr.arrayBuffer());
  check(zr.ok && zip.length > 100, 'download');
  const up = await call(CB, 'POST', '/api/account/import', {size: zip.length, name: 'alice.zip'});
  for (let off = 0; off < zip.length; off += up.chunk) {
    const pr = await fetch(B + `api/account/import/${up.id}?offset=${off}`, {method: 'PUT', headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/octet-stream', Cookie: CB}, body: zip.subarray(off, off + up.chunk)});
    check(pr.ok, `piece at ${off}`);
  }
  await until(async () => (await call(CB, 'GET', `/api/account/import/${up.id}`)).state === 'preview');

  // ================= bob: the preview in the section, the tick, the run, undo
  w = await boot({user: 'bob'});
  md = await dataPane(w);
  const box = () => md.querySelector('#s-umz-imp .umzbox');
  await until(() => box());
  check(box() && /Export of Alice Umzug/.test(box().textContent) && /\d+ lists?/.test(box().textContent), 'the preview: source person + counts');
  const ck = box()?.querySelector('[data-umzp][data-k="share"]');
  check(ck && !ck.checked && /found: Carol Team/.test(box().textContent), 'carol found, the tick is off');
  check(/Nothing is shared without a tick/.test(box().textContent), 'the hint on ticks');
  ck.checked = true;
  click(w, box().querySelector('[data-umz="go"]'));
  await until(() => md.querySelector('#s-umz-imp [data-umz="undo"]'), 100);
  check(/Import finished/.test(md.querySelector('#s-umz-imp').textContent) && /Shared/.test(md.querySelector('#s-umz-imp').textContent), 'the result with the shared person');
  const st = await call(CB, 'GET', '/api/state');
  const nl = (st.lists || []).find(x => x.name === 'Umzug UI Liste');
  check(nl && nl.id !== L, 'bob has the list (new id)');
  const CC = await login('carol');
  check(((await call(CC, 'GET', '/api/state')).lists || []).some(x => nl && x.id === nl.id), 'carol (ticked) got the list shared');
  click(w, md.querySelector('#s-umz-imp [data-umz="undo"]'));
  const yes = await until(() => w.document.querySelector('[data-cd="yes"]'));
  check(yes, 'undo asks first');
  click(w, yes);
  await until(async () => !((await call(CB, 'GET', '/api/state')).lists || []).some(x => x.name === 'Umzug UI Liste'), 60);
  check(!((await call(CB, 'GET', '/api/state')).lists || []).some(x => x.name === 'Umzug UI Liste'), 'undo removed the list');
  check(!md.querySelector('#s-umz-imp .umzbox'), 'the box is closed');
  w.close();
  void bob;

  // ================= part 4: an organisation export asks for the recovery key
  const up2 = async (ck, buf) => {
    const u = await call(ck, 'POST', '/api/account/import', {size: buf.length, name: 'org.kalmido-export'});
    for (let off = 0; off < buf.length; off += u.chunk) await fetch(B + `api/account/import/${u.id}?offset=${off}`, {method: 'PUT', headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/octet-stream', Cookie: ck}, body: buf.subarray(off, off + u.chunk)});
    return u.id;
  };
  await call(CA, 'POST', '/api/lists', {name: 'Org UI Liste', org_id: 1});
  await call(CA, 'POST', '/api/orgs/1/export');
  await until(async () => (await call(CA, 'GET', '/api/orgs/1/export')).state !== 'running', 100);
  const ox = Buffer.from(await (await fetch(B + 'api/orgs/1/export/file', {headers: {Cookie: CA}})).arrayBuffer());
  const rk = (await call(CA, 'POST', '/api/orgs/1/encryption/recovery', {password: 'password123'})).recovery_key;
  check(ox.length > 100 && rk, 'organisation export + recovery key');
  const oid = await up2(CA, ox);
  await until(async () => (await call(CA, 'GET', `/api/account/import/${oid}`)).state === 'key');
  w = await boot({user: 'alice'});
  md = await dataPane(w);
  await until(() => md.querySelector('#s-umz-key'));
  check(md.querySelector('#s-umz-key')?.type === 'password' && /Organisation export of Kalmido/.test(md.querySelector('#s-umz-imp').textContent), 'the key field of an organisation export');
  md.querySelector('#s-umz-key').value = Array(13).fill('ABCD').join('-');
  click(w, md.querySelector('[data-umz="key"]'));
  await until(() => /Attempts left/.test(md.querySelector('#s-umz-imp')?.textContent || ''), 100);
  check(/Attempts left: 9/.test(md.querySelector('#s-umz-imp').textContent), 'a wrong key is named');
  md.querySelector('#s-umz-key').value = rk;
  click(w, md.querySelector('[data-umz="key"]'));
  await until(() => md.querySelector('#s-umz-imp .umzbox [data-umz="go"]'), 100);
  const ob = md.querySelector('#s-umz-imp .umzbox');
  check(ob && /Organisation export of Kalmido/.test(ob.textContent) && !/Private/.test(md.querySelector('#s-umz-tgt')?.textContent || 'Private'), 'opened: preview, organisations only as target');
  check(!ob.querySelector('[data-k="share"]') || /Add to the organisation/.test(ob.textContent), 'the tick adds to the organisation');
  click(w, ob.querySelector('[data-umz="cancel"]')); await sleep(400);
  check(!md.querySelector('#s-umz-imp .umzbox'), 'cancel');
  w.close();

  // ================= Firefox: the phone (390, touch)
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .agview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { settingsModal('data'); return 1; })()`); await sleep(1200);
    await ev(`(() => { const h = document.querySelector('.smodal #s-umz-h'); h && h.scrollIntoView(); const d = document.querySelector('.smodal .umzhow'); if (d) d.open = true; return 1; })()`); await sleep(500);
    const g = await ev(`(() => { const s = document.querySelector('.smodal #s-umz-exp'); if (!s) return null; const r = s.getBoundingClientRect();
      const b = document.querySelector('.smodal #s-umz-exp .btn'); const q = b ? b.getBoundingClientRect() : null;
      return {left: r.left, right: r.right, btn: q ? q.right <= 390 : false, wide: document.documentElement.scrollWidth <= 390}; })()`);
    check(g && g.left >= 0 && g.right <= 390 && g.btn && g.wide, `${tag}: the section fits the phone ` + JSON.stringify(g));
    await shot('p273b-390-move.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
