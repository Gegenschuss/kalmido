// kalmido-suite: fresh
// #4300 (2.507.0): a locked folder of the file store after an account move, own container (start.sh), Firefox (real WebCrypto).
// frida (no organisation, freelancer-matrix: files) locks a folder holding a file, a subfolder and a file in it; her account
// export goes into gina (no keys). gina unlocks with frida's passphrase and reads the names and the bytes: all of them are bound
// to frida's ids. Without the old ids nothing opens (the guard of the test). gina adds a file and unlocks the folder: plain again.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2507_a_lockmove_ui', check, shots: 'P2507A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no JSON */ } return {status: r.status, j}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 250 : 100000, step: 250});
const PASS = 'a long passphrase of frida for the move';
const TXT = 'Rental contract, invented words';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, CA);
  const ck = {};
  for (const u of ['frida', 'gina']) {
    check((await call('POST', '/api/users', {username: u, display_name: u, password: 'password123', email: `${u}@example.com`, orgs: []}, CA)).status < 300, u);
    ck[u] = await login(u);
    const st = (await call('GET', '/api/state', null, ck[u])).j;
    await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files'])].filter(Boolean).join(',')}, ck[u]);
  }
  const BOX = (await call('POST', '/api/files/folders', {name: 'Strongbox', space: 'private'}, ck.frida)).j.id;
  const SUB = (await call('POST', '/api/files/folders', {name: 'Inner', parent_id: BOX}, ck.frida)).j.id;
  for (const [parent, name] of [[BOX, 'contract.txt'], [SUB, 'inner.txt']]) {
    const fd = new FormData(); fd.append('parent_id', String(parent)); fd.append('file', new Blob([`${TXT} ${name}`], {type: 'text/plain'}), name);
    check((await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck.frida}, body: fd})).status === 201, 'a plain file ' + name);
  }

  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash); await waitFor('!!(window.S && S.booted)'); };
    const signIn = user => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
    await nav(B + 'static/icon.svg');
    await ev('(() => { localStorage.clear(); return 1; })()');
    check(await signIn('frida') === 200, 'Firefox: frida');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#ablage');
    check(await ev(`(async () => { await e2eLoad(true); return !!(await e2eCreate(${JSON.stringify(PASS)})) && e2eUnlocked(); })()`), 'frida sets up her encryption');
    const locked = await ev(`fslStart(${BOX}).catch(e => e.message)`);
    check(locked === true, 'frida locks the folder ' + JSON.stringify(locked));

    // the move: her account export into gina (the API, like the settings page)
    check((await call('POST', '/api/account/export', null, ck.frida)).status === 202, 'export started');
    check(await until(async () => (await call('GET', '/api/account/export', null, ck.frida)).j.state === 'done'), 'export done');
    const t = (await (await fetch(B + 'api/account/export/file', {method: 'POST', headers: {...H, Cookie: ck.frida}, body: JSON.stringify({password: 'password123'})})).json()).ticket;
    const zip = Buffer.from(await (await fetch(B + 'api/account/export/file?t=' + encodeURIComponent(t || ''), {headers: {...H, Cookie: ck.frida}})).arrayBuffer());
    const iid = (await call('POST', '/api/account/import', {size: zip.length, name: 'frida.zip'}, ck.gina)).j.id;
    check((await fetch(B + `api/account/import/${iid}?offset=0`, {method: 'PUT', headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/octet-stream', Cookie: ck.gina}, body: zip})).ok, 'upload into gina');
    const pv = await until(async () => { const j = (await call('GET', `/api/account/import/${iid}`, null, ck.gina)).j; return j.state === 'preview' ? j : null; });
    check(pv?.preview?.encrypted?.locked_folders === 1, 'preview: the locked folder comes along ' + JSON.stringify(pv?.preview?.encrypted));
    await call('POST', `/api/account/import/${iid}/run`, {target: 'private', people: {}}, ck.gina);
    check(await until(async () => (await call('GET', `/api/account/import/${iid}`, null, ck.gina)).j.state === 'done'), 'import into gina done');
    const tops = (await call('GET', '/api/files?space=private', null, ck.gina)).j.items || [];
    const G = tops.find(x => x.name === 'Strongbox')?.id;
    check(G && G !== BOX, 'gina has the folder under a new id');

    // gina: frida's passphrase, then her folder opens
    await ev('(() => { localStorage.clear(); return 1; })()');
    check(await signIn('gina') === 200, 'Firefox: gina');
    await boot('#ablage');
    check(await ev(`(async () => { await e2eLoad(true); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS)})); return e2eUnlocked(); })()`), 'gina unlocks with the passphrase from before');
    const read = `(async () => { const out = {}; const walk = async p => { for (const n of (await rawFetch('GET', '/api/files?parent=' + p)).items) {
        const name = await fslNameDec(${G}, n.name, true);
        if (n.kind === 'folder') await walk(n.id);
        else { const f = await fslFileDec(${G}, await (await fetch('/api/files/lock/${G}/raw/' + n.id, {headers: {'X-Requested-With': 'kalmido'}})).arrayBuffer()); out[name] = new TextDecoder().decode(f.data); }
        if (n.kind === 'folder') out[name] = 'folder'; } }; await walk(${G}); return JSON.stringify(out); })().catch(e => 'ERR ' + (e.code || e.message))`;
    const got = await ev(read);
    check(got === JSON.stringify({'contract.txt': `${TXT} contract.txt`, 'inner.txt': `${TXT} inner.txt`, Inner: 'folder'}) ||
          (got.startsWith('{') && JSON.parse(got)['contract.txt'] === `${TXT} contract.txt` && JSON.parse(got)['inner.txt'] === `${TXT} inner.txt` && JSON.parse(got).Inner === 'folder'),
          '#4300: names and files open after the move ' + got);
    // the guard: bound to the new id nothing opens (this is the data loss of before)
    const guard = await ev(`(async () => { const n = (await rawFetch('GET', '/api/files?parent=${G}')).items.find(x => x.kind === 'file'); const a = FSL.aad[${G}]; FSL.memo.clear(); FSL.aad[${G}] = ${G};
      let r = 'opened'; try { await fslNameDec(${G}, n.name, false); } catch { r = 'refused'; } FSL.aad[${G}] = a; FSL.memo.clear(); return r; })()`);
    check(guard === 'refused', '#4300: the ciphertexts are bound to the old id: ' + guard);
    await boot(`#ablage/${G}`);
    await ev(`(async () => { await e2eLoad(true); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS)})); ab_reload(); return 1; })()`);
    check(await waitFor(`[...document.querySelectorAll('.abrow .abname')].map(x => x.textContent).includes('contract.txt')`), '#4300: the folder view shows the plain name');
    await shot('p2507a-moved.png');

    // working there: a new file, read back after the keys are fetched anew
    check(await ev(`(async () => { await fsl_upload([new File([new TextEncoder().encode('Added after the move')], 'added.txt', {type: 'text/plain'})], ${G}); delete FSL.info[${G}]; delete FSL.keys[${G}]; FSL.memo.clear(); return 1; })()`), 'gina adds a file');
    const again = await ev(read);
    check(again.startsWith('{') && JSON.parse(again)['added.txt'] === 'Added after the move', '#4300: the new file opens ' + again);

    // unlocking: everything plain again on the server
    const off = await ev(`(async () => await fslStop(${G}, 'password123'))().catch(e => 'ERR ' + (e.code || e.message))`);
    check(off === true || off === undefined || (off && !String(off).startsWith('ERR')), '#4300: gina unlocks the folder ' + JSON.stringify(off));
    const names = ((await call('GET', `/api/files?parent=${G}`, null, ck.gina)).j.items || []).map(x => x.name).sort();
    check(names.join() === 'Inner,added.txt,contract.txt', '#4300: plain names again ' + names.join());
  }, false);

  console.log(`p2507_a_lockmove_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
