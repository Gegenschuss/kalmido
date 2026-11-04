// kalmido-suite: fresh
// 2.365.2 B UI tests (#2789), jsdom, own container (start.sh). freelancer-matrix: Oberflaeche (frida has no organisation)
// - Settings > Documents: sorting automatically (a level per feature, undo), archive numbers, rules; no inbox / mail there;
//   the gear of the documents opens it; the lists and custom fields keep a dialog in the module (no levels in it)
// - Settings > Integrations has ONE block "Documents: inboxes": the file store folder (switch, undo), folder watcher, mail address
// - Karakeep, the newsletter service, the bookmark button, the address books for birthdays (CardDAV) and the booking page are in
//   Integrations; the module entries (kkModal, the bookmarks menu, contactsModal, the Calendars dialog) open them there
// - Data > Import links the consent import of the newsletter
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, histAdded} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P23652B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el && el.dispatchEvent(new w.Event('change', {bubbles: true}));
const shown = (d, k) => { const p = d.querySelector(`.smodal [data-pane="${k}"]`); return !!p && !p.classList.contains('hidden'); };
const closeAll = d => d.querySelectorAll('.modal').forEach(m => m.remove());

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'events', 'contacts', 'family', 'reading']});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: [...new Set([...(st.settings?.features || '').split(','), 'cal', 'files', 'docs', 'events', 'contacts', 'family', 'reading'])].filter(Boolean).join(',')});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  const s0 = await call('GET', '/api/docs/settings?ws=private');
  check(s0.http === 200 && s0.can_manage, 'frida manages her own documents (her own admin)');

  const w = await boot({user: 'frida', hash: 'docs'}), d = w.document;
  await until(() => w.eval('S.booted && typeof dcs_paneHtml === "function" && typeof intB_draw === "function"'), 60);

  // ---- the gear of the documents opens Settings > Documents
  click(w, await until(() => d.querySelector('#view [data-dc="settings"]')));
  const pane = await until(() => d.querySelectorAll('#s-dcs [data-dcl]').length && d.querySelector('#s-dcs'));
  check(pane && shown(d, 'docs'), 'the gear opens Settings > Documents');
  check(!d.querySelector('.modal.dc-smd'), 'no documents dialog besides the settings');
  check(d.querySelectorAll('#s-dcs [data-dcl]').length === (s0.levels ? Object.keys(s0.levels).length : 4) && d.querySelector('#s-dcs #dcs-asn') && d.querySelector('#s-dcs-rules-h') && /Your own documents/.test(pane?.textContent || ''),
    'Settings > Documents: levels, archive number prefix, rules, the own workspace named');
  check(!d.querySelector('#s-dcs [data-dsc="inbox"]') && !d.querySelector('#s-dcs [data-dcs="inbox"]') && !d.querySelector('#s-dcs .dc-mail') && !d.querySelector('#s-dcs [data-dsc]'), 'Settings > Documents: no inboxes (they are in Integrations)');
  check(!!d.querySelector('#s-dcs [data-dcs="lists"]') && !!d.querySelector('#s-dcs [data-dcs="go-integr"]'), 'Settings > Documents: links to the lists and to the inboxes');
  // a level: saved at once, one undo step
  const sel = d.querySelector('#s-dcs [data-dcl]'), f = sel.dataset.dcl, from = s0.levels[f];
  const to = [...sel.options].map(o => o.value).find(v => v !== from);
  const h1 = w.eval('HIST.undo.length');
  sel.value = to; change(w, sel);
  check(await until(async () => (await call('GET', '/api/docs/settings?ws=private')).levels[f] === to), `the level of ${f} is saved at once (${from} -> ${to})`);
  check(await histAdded(w, h1), 'the level is one undo step');  // 2.504.0 (#4085): recorded after the answer, the server is faster
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', '/api/docs/settings?ws=private')).levels[f] === from), 'undo: the old level');
  check(await until(() => d.querySelector(`#s-dcs [data-dcl="${f}"]`)?.value === from), 'undo: the pane shows the old level');
  // the archive number prefix
  const asn = d.querySelector('#s-dcs #dcs-asn'); asn.value = 'AR'; change(w, asn);
  check(await until(async () => (await call('GET', '/api/docs/settings?ws=private')).asn_prefix === 'AR'), 'the prefix of the archive numbers is saved');

  // ---- the lists keep a dialog in the module
  click(w, d.querySelector('#s-dcs [data-dcs="lists"]'));
  const lm = await until(() => d.querySelector('.modal.dc-smd .dc-fadd') && d.querySelector('.modal.dc-smd'));
  check(lm && !d.querySelector('.smodal') && /Custom fields/.test(lm.textContent) && /Senders, types and tags/.test(lm.textContent), 'the lists dialog: senders, types, tags and custom fields');
  check(lm && !lm.querySelector('[data-dcl]') && !lm.querySelector('#dcs-asn') && !lm.querySelector('[data-dsc]'), 'the lists dialog: no second copy of the settings');
  click(w, lm?.querySelector('[data-dcs="go-set"]'));
  check(await until(() => !d.querySelector('.modal.dc-smd') && shown(d, 'docs')), 'the lists dialog links back to Settings > Documents');
  closeAll(d);
  check(!!d.querySelector('#view [data-dc="lists"]'), 'the documents bar has a button for the lists');

  // ---- Integrations: one block "Documents: inboxes"
  w.eval(`settingsModal('scans')`);
  const box = await until(() => d.querySelector('#s-scan [data-dsc="inbox"]') && d.querySelector('#s-scan'));
  check(box && shown(d, 'integr') && /Documents: inboxes/.test(d.querySelector('#s-scan-h')?.textContent || ''), 'Integrations: the block "Documents: inboxes"');
  check(box && /Folder watcher/.test(box.textContent), '… with the folder watcher');
  const ib = d.querySelector('#s-scan [data-dsc="inbox"]'), was = !!s0.inbox;
  const h2 = w.eval('HIST.undo.length');
  ib.checked = !was; change(w, ib);
  check(await until(async () => !!(await call('GET', '/api/docs/settings?ws=private')).inbox === !was), 'the file store folder switch saves at once');
  check(await histAdded(w, h2), 'the switch is one undo step');  // 2.504.0 (#4085)
  await w.eval(`histStep('undo')`);
  check(await until(async () => !!(await call('GET', '/api/docs/settings?ws=private')).inbox === was), 'undo: the switch as before');
  if (s0.mail?.enabled) {
    click(w, d.querySelector('#s-scan [data-dsc="mailnew"]'));
    check(await until(() => (d.querySelector('#s-scan .dc-mail code')?.textContent || '').includes('@')), 'the mail address is made in Integrations');
    check(!!(await call('GET', '/api/docs/settings?ws=private')).mail?.address, '… and stored on the server');
  } else check(!d.querySelector('#s-scan [data-dsc="mailnew"]'), 'mail off on this server: no mail buttons');
  check(d.querySelector('.icard[data-jump="#s-scan-h"]') && /Documents: inboxes/.test(d.querySelector('.icard[data-jump="#s-scan-h"]').textContent), 'the card of Integrations names the inboxes');

  // ---- Integrations: Karakeep, newsletter, bookmark button, address books, booking page
  for (const [h, what] of [['#s-kk-h', 'Karakeep'], ['#s-nwl-h', 'the newsletter service'], ['#s-bmlet-h', 'the bookmark button'], ['#s-carddav-h', 'the address books for birthdays'], ['#s-apb-h', 'the booking page']])
    check(!!d.querySelector(`.smodal [data-pane="integr"] ${h}`), `Integrations has ${what} (${h})`);
  check(await until(() => d.querySelector('#s-kk #kk-url')) && d.querySelector('#s-kk #kk-tok').type === 'password', 'Karakeep: address and API key (password field)');
  // the form needs the server key (KALMIDO_SECRET_KEY, p255_e_ui sets it); without it the block says so
  check(await until(() => d.querySelector('.nwl-set #nwl-url') || /server key is missing/.test(d.querySelector('.nwl-set')?.textContent || ''), 60) && /sends no newsletters/.test(d.querySelector('.nwl-set')?.textContent || ''), 'the newsletter service: drawn in Integrations (form or the missing server key)');
  check(!d.querySelector('.nwl-set [data-nwl="seg-new"]'), '… without the segments (they stay with the newsletter)');
  check(/^javascript:/.test(d.querySelector('#s-bmlet-h + .caprow .capbm')?.getAttribute('href') || '') && /bm=1/.test(d.querySelector('.capbm').getAttribute('href')), 'the bookmark button: a javascript link to /share?bm=1');
  check(await until(() => d.querySelector('#s-carddav #ct-url')), 'the address books: the form to connect one');
  closeAll(d);

  // ---- the modules open the places in the settings
  for (const [js, h, what] of [['kkModal()', '#s-kk-h', 'Karakeep (Read later / Home & life)'], ['bm_bookmarkletHelp()', '#s-bmlet-h', 'the bookmark button (bookmarks menu)'], ['contactsModal()', '#s-carddav-h', 'the address books (Family)']]) {
    w.eval(js);
    check(await until(() => shown(d, 'integr') && d.querySelector(`.smodal ${h}`)), `${what}: opens Settings > Integrations`);
    closeAll(d);
  }
  w.location.hash = '#cal';
  click(w, await until(() => d.querySelector('#view [data-act="ev-cals"]'), 60));
  const ph = await until(() => d.querySelector('.evcmodal [data-evc="phone"]'));
  check(!!ph && !!d.querySelector('.evcmodal [data-evc="booking"]'), 'the Calendars dialog keeps "On the phone…" and "Booking page…"');
  click(w, ph);
  check(await until(() => shown(d, 'integr') && !d.querySelector('.dgmodal')), 'Calendar "On the phone…" opens Settings > Integrations (no second guide)');
  closeAll(d);
  w.eval(`settingsModal('booking')`);
  click(w, await until(() => d.querySelector('.smodal [data-intb="apb"]')));
  check(await until(() => !d.querySelector('.smodal') && d.querySelector('.apb-dlg, .modal .apb-body'), 60), 'Integrations > Booking page opens its dialog');
  closeAll(d);

  // ---- Data > Import: the way to the consent import
  w.eval(`settingsModal('data')`);
  const nb = await until(() => d.querySelector('.smodal [data-pane="data"] [data-intb="nwl"]'));
  check(!!nb, 'Data > Import links the newsletter consent import');
  click(w, nb);
  check(await until(() => d.querySelector('.modal.nwl-md #nwl-imp-file'), 60), '… which opens the newsletter with its import');
  check(!!d.querySelector('.modal.nwl-md [data-nwl="go-set"]') && !d.querySelector('.modal.nwl-md #nwl-url'), 'the newsletter without a service: the way to the settings, no form');
  w.close();

  // ---- documents off: no section Documents
  await call('PATCH', '/api/settings', {features: 'files,events,contacts,family,reading'});
  const v = await boot({user: 'frida', hash: 'today'}), e = v.document;
  await until(() => v.eval('S.booted && typeof settingsModal === "function"'), 60);
  v.eval(`settingsModal('integr')`);
  await until(() => e.querySelector('.smodal'));
  check(!e.querySelector('.smodal .snav [data-sec="docs"]') && !e.querySelector('#s-dcs') && !e.querySelector('#s-scan'), 'documents off: no section Documents, no inboxes block');
  v.close();

  console.log(`p2365_2_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
