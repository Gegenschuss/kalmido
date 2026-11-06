// 2.207.0 A UI tests (#2763, own container, start.sh; P2207A_NOSTART=1: the container runs already). jsdom:
// - a person without an organisation: Documents > Settings shows "Scans from your computer" with the folder watcher (no
//   programs on this server: the honest hint) and the mail way
//   2.365.2 B (#2789): all of it is one block "Documents: inboxes" in Settings > Integrations
// - "Create inbox" shows the setup code once with a copy button and the three steps; the inbox is listed; the code is gone
//   when the dialog is opened again
// - the mail note is big until "Got it", then one quiet line (remembered on the server); the address has a copy button
// - revoking asks first and removes the inbox
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2207_a_scan_ui', check, shots: 'P2207A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const MAIL = '-e KALMIDO_MAIL_ADDRESS=tasks@example.test -e KALMIDO_IMAP_HOST=127.0.0.1 -e KALMIDO_IMAP_PORT=1143 -e KALMIDO_IMAP_USER=tasks';
if (!process.env.P2207A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: `${process.env.EXTRA || ''} ${MAIL}`.trim()}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files', 'docs'])].filter(Boolean).join(',')});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  await call('POST', '/api/docs/mail', {ws: 'private'});

  const w = await boot({user: 'frida', hash: 'docs'}), d = w.document;
  await until(() => w.eval('typeof dc_settings === "function" && typeof dsc_integrHtml === "function"'), 60);
  const copied = [];
  Object.defineProperty(w.navigator, 'clipboard', {value: {writeText: async t => { copied.push(t); }}, configurable: true});
  // 2.365.2 B (#2789): the gear opens Settings > Documents, which points to the one block "Documents: inboxes" in Integrations
  // (folder of the file store, folder watcher, scan inboxes, mail way); the module has no second copy
  (await until(() => d.querySelector('#view [data-dc="settings"]')))?.click();
  const gi = await until(() => d.querySelector('.smodal #s-dcs [data-dcs="go-integr"]'));
  check(gi && !d.querySelector('#s-dcs .dsc-way') && !d.querySelector('#s-dcs [data-dsc]'), 'Settings > Documents: only the pointer to Integrations');
  gi?.click();
  const sm = await until(() => d.querySelector('#s-scan .dc-mail code') && d.querySelector('#s-scan'));
  const txt = () => d.querySelector('#s-scan')?.textContent || '';
  check(sm && /Documents: inboxes/.test(d.querySelector('#s-scan-h')?.textContent || '') && /Folder watcher/.test(txt()) && /By e-mail/.test(txt()) && d.querySelector('#s-scan [data-dsc="inbox"]'), 'one block: file store folder, folder watcher, mail way');

  // ---- the mail way: copy button, the note big once
  check(d.querySelector('#s-scan .dc-mail code')?.textContent.includes('@'), 'the forwarding address is shown');
  d.querySelector('[data-dsc="mailcopy"]').click();
  check(await until(() => copied.some(x => x.includes('@'))), 'copy button: the address in the clipboard');
  check(d.querySelector('#s-scan .dsc-note') && /like a postcard/.test(txt()), 'the mail note is big the first time');
  d.querySelector('[data-dsc="notice"]').click();
  check(await until(() => !d.querySelector('#s-scan .dsc-note') && d.querySelector('#s-scan .dsc-hint')), 'after "Got it": one quiet line');
  check((await call('GET', '/api/docs/scan-keys?ws=private')).mail_notice === true, 'remembered on the server');

  // ---- Settings > Integrations: the download and a new inbox (the code once)
  const em = await until(() => d.querySelector('#s-scan .dsc-new'));
  const etxt = () => d.querySelector('#s-scan')?.textContent || '';
  check(!d.querySelector('[data-pane="integr"]')?.classList.contains('hidden') && /Folder watcher/.test(etxt()), 'the link opens Integrations at the section');
  // 2.207.0 (#2763): the image builds the programs (Dockerfile stage folderwatch) -> download buttons instead of the hint
  check((d.querySelector('#s-scan .dsc-dl')?.children.length || 0) >= 3 && !/Not available on this server/.test(etxt()), 'the programs of the image: download buttons, no hint');
  check(em?.open, 'no inbox yet: "New scan inbox" is open');
  check(d.querySelector('#dsc-name')?.value === 'Scanner', 'the name proposal "Scanner"');
  d.querySelector('#dsc-name').value = 'Flur';
  d.querySelector('[data-dsc="new"]').click();
  const code = await until(() => d.querySelector('#dsc-code')?.value);
  check(code && code.startsWith('kalmido-scan:1:') && /Only visible now/.test(etxt()), 'the setup code is shown once: ' + (code || '').slice(0, 20));
  check(d.querySelectorAll('#s-scan .dsc-steps li').length === 3 && /Open Anyway/.test(etxt()) && /in the scan software set up a profile/.test(etxt()) && !/ScanSnap/i.test(etxt()), 'the three steps (Mac / Windows, code, scanner without a device name)');  // 2.427.0 (#3577): no device name
  check([...d.querySelectorAll('#s-scan .dsc-key')].some(x => /Flur/.test(x.textContent) && /Private/.test(x.textContent)), 'the inbox is listed with its place');
  // 2.582.0 (#4831): the private space is called "Private" (like in the file store), in the Documents tree and the scan head
  check(w.eval(`dc_wsName('private')`) === 'Private' && w.eval(`ab_spaceName('private')`) === w.eval(`dc_wsName('private')`) && d.querySelector('#s-scan > p.muted')?.textContent === 'Private', 'private space: "Private", same name as the file store');
  d.querySelector('[data-dsc="copy"]').click();
  check(await until(() => copied.includes(code)), 'copy button: the code in the clipboard');
  w.eval(`document.querySelectorAll('.modal').forEach(m => modalClose(m))`);
  w.eval(`settingsModal('scans')`);
  await until(() => d.querySelector('#s-scan .dsc-key'));
  check(!d.querySelector('#dsc-code') && !etxt().includes(code), 'opened again: the code is gone');
  w.eval(`document.querySelectorAll('.modal').forEach(m => modalClose(m))`);
  w.eval(`settingsModal('scans')`);
  await until(() => d.querySelector('#s-scan .dsc-key'));
  check(!d.querySelector('#s-scan .dsc-note') && d.querySelector('#s-scan .dsc-hint'), 'opened again: the mail note stays small');

  // ---- revoke asks first
  const kid = (await call('GET', '/api/docs/scan-keys?ws=private')).keys[0]?.id;
  d.querySelector(`[data-dsc="del:${kid}"]`).click();
  const okb = await until(() => d.querySelector('.cdlg-f [data-cd="yes"]'));
  check(okb, 'revoking asks first');
  okb?.click();
  check(await until(async () => ((await call('GET', '/api/docs/scan-keys?ws=private')).keys || []).length === 0), 'the inbox is revoked');
  check(await until(() => !d.querySelector('#s-scan .dsc-key')), 'and gone from the list');
  w.close();

  // ---- the real layout (Firefox): desktop and a phone, the section with a fresh setup code, no horizontal overflow
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.ok)`);
    let nr = 0;
    for (const [vw, vh] of [[1280, 900], [390, 844]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B + '?v=' + (++nr) + '#docs');
      for (let i = 0; i < 40 && !(await ev(`typeof dsc_integrHtml === 'function' && typeof settingsModal === 'function'`).catch(() => false)); i++) await sleep(300);
      await ev(`(() => { settingsModal('scans'); return 1; })()`);
      for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#s-scan [data-dsc="new"]')`).catch(() => false)); i++) await sleep(200);
      await ev(`(() => { const d = document.querySelector('#s-scan .dsc-new'); if (d) d.open = true; document.querySelector('#dsc-name').value = 'Scanner ${vw}'; document.querySelector('#s-scan [data-dsc="new"]').click(); return 1; })()`);
      for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#dsc-code')`).catch(() => false)); i++) await sleep(200);
      await ev(`(() => { document.querySelector('#s-scan-h')?.scrollIntoView(); return 1; })()`);
      await sleep(500);
      const lay = await ev(`(() => { const m = document.querySelector('#s-scan').closest('.spanes') || document.querySelector('#s-scan'); const c = document.querySelector('#s-scan .dsc-code');
        return {code: !!(c && c.offsetWidth), sw: m.scrollWidth, cw: m.clientWidth, doc: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1}; })()`);
      check(lay.code && lay.sw <= lay.cw + 1 && lay.doc, `${vw}px: the section with the code, no horizontal overflow ${JSON.stringify(lay)}`);
      await shot(`p2207-scan-${vw}.png`);
    }
  });

  console.log(`p2207_a_scan_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
