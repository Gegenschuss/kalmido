// 2.577.0 C UI test (#4466): named document addresses in Settings > Integrations ("Documents: inboxes", by e-mail).
// kalmido-suite: after=p2577_c_docmail
// Runs in the container of p2577_c_docmail (the mail input on); a person without an organisation (frida), invented names only.
// - the block "Named addresses" under the general address; "New named address" with name, folder and tags makes one: listed with
//   its folder, its tags and its address; the copy button copies that address
// - the switch turns it off (the row is marked, the server says inactive) and on again; "Edit" saves a new name
// - deleting asks first and removes it
// - Firefox: 1280 px and 390 px, the section with a named address, no horizontal overflow (screenshot)
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2577_c_ui', check, shots: 'P2577C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  CK = await login('frida');
  await call('POST', '/api/docs/mail', {ws: 'private'});
  const set = await call('GET', '/api/docs/settings?ws=private');
  const fol = await call('POST', '/api/files/folders', {name: 'Kreditkarte', parent_id: set.root_id});
  check(fol.id && (await call('GET', '/api/docs/mail-addresses?ws=private')).addresses.filter(a => !a.general).length === 0, 'setup: a folder, no named address yet');

  const w = await boot({user: 'frida', hash: 'docs'}), d = w.document;
  await until(() => w.eval('typeof settingsModal === "function" && typeof dsc_namedHtml === "function"'), 60);
  const copied = [];
  Object.defineProperty(w.navigator, 'clipboard', {value: {writeText: async t => { copied.push(t); }}, configurable: true});
  w.eval(`settingsModal('scans')`);
  const nb = await until(() => d.querySelector('#s-scan .dsn-named'));
  check(nb && /Named addresses/.test(nb.textContent) && d.querySelector('#s-scan .dc-mail code'), 'the block "Named addresses" under the general address');
  const nn = d.querySelector('#s-scan .dsn-new'); if (nn) nn.open = true;
  d.querySelector('#dsn-name-new').value = 'Kreditkarte';
  d.querySelector('#dsn-folder-new').value = String(fol.id);
  d.querySelector('#dsn-tags-new').value = 'Karte, Ausgaben';
  d.querySelector('[data-dsc="nnew"]').click();
  const row = await until(() => d.querySelector('#s-scan .dsn-addr'));
  const srv = (await call('GET', '/api/docs/mail-addresses?ws=private')).addresses.filter(a => !a.general);
  const A1 = srv[0] || {};
  check(row && srv.length === 1 && A1.name === 'Kreditkarte' && A1.target_folder === fol.id && A1.tags.join(',') === 'Karte,Ausgaben', 'created with name, folder and tags ' + JSON.stringify(A1));
  check(row && /Kreditkarte/.test(row.textContent) && /Karte, Ausgaben/.test(row.textContent) && row.querySelector('.dsn-code')?.textContent === A1.address, 'listed with folder, tags and its address');
  d.querySelector(`[data-dsc="ncopy:${A1.id}"]`)?.click();
  check(await until(() => copied.includes(A1.address)), 'the copy button copies that address');

  // ---- off / on
  const sw = d.querySelector(`[data-dsc="non:${A1.id}"]`);
  sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/docs/mail-addresses?ws=private')).addresses.find(a => a.id === A1.id)?.active === false), 'the switch turns it off on the server');
  check(await until(() => d.querySelector('#s-scan .dsn-addr.off')), 'the row is marked off');
  const sw2 = d.querySelector(`[data-dsc="non:${A1.id}"]`);
  sw2.checked = true; sw2.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/docs/mail-addresses?ws=private')).addresses.find(a => a.id === A1.id)?.active === true), 'and on again');

  // ---- edit the name
  const ed = await until(() => d.querySelector('#s-scan .dsn-edit')); if (ed) ed.open = true;
  d.querySelector(`#dsn-name-${A1.id}`).value = 'Kreditkarte Firma';
  d.querySelector(`[data-dsc="nsave:${A1.id}"]`).click();
  check(await until(async () => (await call('GET', '/api/docs/mail-addresses?ws=private')).addresses.find(a => a.id === A1.id)?.name === 'Kreditkarte Firma'), 'Edit saves a new name');
  check(await until(() => /Kreditkarte Firma/.test(d.querySelector('#s-scan .dsn-addr')?.textContent || '')), 'shown at once');

  // ---- delete asks first
  d.querySelector(`[data-dsc="ndel:${A1.id}"]`).click();
  const okb = await until(() => d.querySelector('.cdlg-f [data-cd="yes"]'));
  check(okb, 'deleting asks first');
  okb?.click();
  check(await until(async () => (await call('GET', '/api/docs/mail-addresses?ws=private')).addresses.filter(a => !a.general).length === 0), 'deleted on the server');
  check(await until(() => !d.querySelector('#s-scan .dsn-addr')), 'and gone from the list');
  w.close();

  // ---- the real layout (Firefox): desktop and a phone, no horizontal overflow
  await call('POST', '/api/docs/mail-addresses', {ws: 'private', name: 'Kontoauszuege mit einem langen Namen', target_folder: fol.id, tags: ['Bank', 'Konto', 'Monatlich']});
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.ok)`);
    let nr = 0;
    for (const [vw, vh] of [[1280, 900], [390, 844]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B + '?v=' + (++nr) + '#docs');
      for (let i = 0; i < 40 && !(await ev(`typeof dsc_namedHtml === 'function' && typeof settingsModal === 'function'`).catch(() => false)); i++) await sleep(300);
      await ev(`(() => { settingsModal('scans'); return 1; })()`);
      for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#s-scan .dsn-addr')`).catch(() => false)); i++) await sleep(200);
      await ev(`(() => { const n = document.querySelector('#s-scan .dsn-new'); if (n) n.open = true; document.querySelector('#s-scan .dsn-named')?.scrollIntoView(); return 1; })()`);
      await sleep(500);
      const lay = await ev(`(() => { const m = document.querySelector('#s-scan').closest('.spanes') || document.querySelector('#s-scan'); const r = document.querySelector('#s-scan .dsn-addr');
        return {row: !!(r && r.offsetWidth), rw: r ? r.scrollWidth <= r.clientWidth + 1 : false, sw: m.scrollWidth, cw: m.clientWidth, doc: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1}; })()`);
      check(lay.row && lay.rw && lay.sw <= lay.cw + 1 && lay.doc, `${vw}px: the named address row, no horizontal overflow ${JSON.stringify(lay)}`);
      await shot(`p2577c-docmail-${vw}.png`);
    }
  });

  console.log(`p2577_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
