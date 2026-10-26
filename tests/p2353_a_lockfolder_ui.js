// kalmido-suite: fresh
// 2.353.0 A (#2758): locked folders of the file store -- the browser side (static/js/fslock.js + hooks in ablage.js), own
// container (start.sh), Firefox (real WebCrypto). A person without an organisation (her private space, freelancer-matrix: files):
// - locks a folder holding a plain file: the server keeps cipher names and KENC files only, the folder view shows the plain
//   names and the bar of the locked folder, the menu offers "Locked folder…"
// - uploads a picture: encrypted here, opened here (the viewer shows it from memory, a data: URL)
// - the name search runs in the browser
// - unlocks it with her password: plain names and files on the server again
// - 2.353.0 F (review): no scan / server search there, the reference palette skips it, a waiting person gets the key only by the
//   banner's button with the name (fslInfo / fslRelease stubbed: frida is alone)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2353_a_lockfolder_ui', check, shots: 'P2353A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2353A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const PASS = 'a long passphrase for frida';
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st = (await call('GET', '/api/state')).j;
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files'])].filter(Boolean).join(',')});
  check(((await call('GET', '/api/state')).j.me.workspaces || []).length === 0, 'frida has no organisation');
  const BOX = (await call('POST', '/api/files/folders', {name: 'Strongbox', space: 'private'})).j.id;
  const fd = new FormData(); fd.append('parent_id', String(BOX)); fd.append('file', new Blob(['ZQWmark plain words'], {type: 'text/plain'}), 'hello.txt');
  const up = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  check(up.status === 201, 'setup: a plain file in the folder');
  const names = async () => ((await call('GET', `/api/files?parent=${BOX}`)).j.items || []).map(x => x.name);

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash); await waitFor('!!(window.S && S.booted)'); };
    await nav(B + 'static/icon.svg');
    await ev('(() => { localStorage.clear(); return 1; })()');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#ablage');
    check(await ev(`(async () => { await e2eLoad(true); return !!(await e2eCreate(${JSON.stringify(PASS)})) && e2eUnlocked(); })()`), 'frida sets up her encryption');

    // ---- lock the folder (the dialog's confirm is the browser's own; the switch itself as the dialog runs it)
    await boot(`#ablage/${BOX}`);
    check(await ev(`(async () => { await e2eLoad(true); if (!e2eUnlocked()) await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS)})); return e2eUnlocked(); })()`), 'unlocked again after the page load');
    check(await waitFor(`typeof fsl_menuItem === 'function' && (ab_menuItems(AB.data?.node || {}) || []).some(x => x && x.label === tr('Lock folder…'))`), 'the folder menu offers "Lock folder…" (fslock.js loaded on demand)');
    const r = await ev(`(async () => { const p = []; const r = await fslStart(${BOX}, (d, t) => p.push([d, t])); return {r, p}; })().catch(e => ({err: e.message}))`);
    check(r && r.r === true, 'fslStart: the folder is locked ' + JSON.stringify(r).slice(0, 200));
    const n1 = await names();
    check(n1.length === 1 && n1[0].startsWith('e2e1:'), 'the server keeps a cipher name only ' + n1.join(','));
    const raw = await fetch(B + `api/files/nodes/${(await call('GET', `/api/files?parent=${BOX}`)).j.items[0].id}/content`, {headers: {Cookie: CK, 'X-Requested-With': 'kalmido'}});
    const head = Buffer.from(await raw.arrayBuffer());
    check(head.subarray(0, 4).toString() === 'KENC' && !head.includes(Buffer.from('ZQWmark')), 'the server keeps the file encrypted (KENC, no plain word)');

    // ---- the view: plain names, the bar, the menu of the locked folder
    await ev('ab_reload(), 1');
    check(await waitFor(`[...document.querySelectorAll('.abrow .abname')].map(x => x.textContent).includes('hello.txt')`), 'the folder view shows the plain name');
    check(await waitFor(`!!document.querySelector('.fslbar')`), 'the bar of the locked folder');
    check(await ev(`(ab_menuItems(AB.data.node) || []).some(x => x && x.label === tr('Locked folder…'))`), 'the menu: "Locked folder…"');
    await shot('p2353a-locked.png');

    // ---- upload a picture: encrypted here, opened here from memory
    check(await ev(`(async () => { const b = Uint8Array.from(atob(${JSON.stringify(PNG)}), c => c.charCodeAt(0)); await fsl_upload([new File([b], 'pic.png', {type: 'image/png'})], ${BOX}); return 1; })()`), 'encrypted upload');
    check(await waitFor(`[...document.querySelectorAll('.abrow .abname')].map(x => x.textContent).includes('pic.png')`), 'the picture shows with its plain name');
    check((await names()).every(n => n.startsWith('e2e1:')), 'the server has cipher names only');
    await ev(`(() => { const n = AB.data.items.find(x => x.name === 'pic.png'); ab_openFile(n); return 1; })()`);
    check(await waitFor(`(document.querySelector('.lightbox img')?.getAttribute('src') || '').startsWith('data:image/png')`), 'the picture opens decrypted in the viewer (from memory)');
    await ev(`(document.querySelector('.lightbox')?.remove(), 1)`);

    // ---- the name search runs in the browser
    await ev(`(() => { const q = document.querySelector('#fsl-q'); q.value = 'pic'; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await waitFor(`(() => { const n = [...document.querySelectorAll('.abrow .abname')].map(x => x.textContent); return n.length === 1 && n[0] === 'pic.png'; })()`), 'the name search filters in the browser');
    await ev(`(() => { const q = document.querySelector('#fsl-q'); q.value = ''; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);

    // ---- 2.353.0 F (#2758, review): no scan, no server search, no decrypted names in the reference palette, keys only by the named button
    check(await ev(`!document.querySelector('[data-ab="scan"]') && !!document.querySelector('[data-ab="upload"]')`), 'F M6: no camera scan in a locked folder (upload stays)');
    check(await ev(`(typeof ftxtBox !== 'function' || !document.querySelector('#ftxt-q')) && !!document.querySelector('#fsl-q')`), 'F N9: no server search box, the name search of the folder stays');
    check(await ev(`(typeof rf_palItems !== 'function' || !rf_palItems('pic').some(x => x.id.startsWith('rf:f:'))) ? 1 : 0`) === 1, 'F M7: the reference palette offers no file of the locked folder');
    const m1 = await ev(`(async () => {
      const keep = {info: fslInfo, rel: fslRelease}; window.__rel = null;
      fslInfo = async () => ({can_manage: true, mode: 'on', gen: 1, members: [], keys: [], pending: [{user_id: 77, name: 'Ida Example', has_keys: true}]});
      fslRelease = async (lid, uids) => { window.__rel = uids; return {ok: true, released: uids}; };
      try { FSL.auto = {}; await fsl_auto(AB.data); return {silent: window.__rel === null, wait: (FSL.wait[${BOX}] || []).map(p => p.name)}; }
      finally { window.__keep = keep; }
    })()`);
    check(m1 && m1.silent && (m1.wait || []).join() === 'Ida Example', 'F M1: opening hands no key over, the waiting person is noted ' + JSON.stringify(m1));
    check(await waitFor(`(document.querySelector('[data-fsl="release"]')?.textContent || '').includes('Ida Example')`), 'F M1: the banner names who waits, with a button');
    await ev(`(document.querySelector('[data-fsl="release"]').click(), 1)`);
    check(await waitFor(`(window.__rel || []).join() === '77' && document.body.textContent.includes(tr('Key handed over to {0}', 'Ida Example'))`), 'F M1: the button hands it over, the toast names the person');
    await ev(`(() => { fslInfo = window.__keep.info; fslRelease = window.__keep.rel; FSL.wait = {}; return 1; })()`);

    // ---- unlock with the password
    const s = await ev(`fslStop(${BOX}, 'password123').then(x => ({x}), e => ({err: e.message}))`);
    check(s && s.x === true, 'fslStop: unlocked ' + JSON.stringify(s));
    const n2 = await names();
    check(n2.sort().join(',') === 'hello.txt,pic.png', 'plain names on the server again ' + n2.join(','));
    check((await call('GET', `/api/files/lock/${BOX}`)).j.mode === null, 'the folder is open');
  }, false);

  console.log(`p2353_a_lockfolder_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
