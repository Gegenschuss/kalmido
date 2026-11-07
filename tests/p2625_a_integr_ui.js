// 2.625.0 A UI test (#4489): Settings > Integrations shows every integration as one folded row. Own container (start.sh),
// kalmido-suite: fresh
// jsdom, invented data only. freelancer-matrix: settings (frida has no organisation; alice is an admin with an organisation)
// - every integration is a closed <details class="introw"> with an icon, its name and (where the pane loads one) its state;
//   no heading of an integration stands outside a row; opening a row shows the form as before
// - the cards at the top open the row of their target; a focus key (settingsModal('karakeep')) opens its row
// - the settings search finds a field inside a closed row and opens the row
// - the state follows the data: the calendar subscription "not connected" -> link created -> "connected"; Karakeep "not connected"
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); let j = null; try { j = await r.json(); } catch { /* no body */ } return {...(j || {}), http: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const type = (w, d, q) => { const sq = d.querySelector('#s-search'); sq.dispatchEvent(new w.FocusEvent('focus')); sq.value = q; sq.dispatchEvent(new w.Event('input', {bubbles: true})); };
const FEAT = 'cal,comments,collab,files,docs,events,contacts,family,reading';
const row = (d, k) => d.querySelector(`.smodal [data-pane="integr"] details.introw[data-intr="${k}"]`);
const closeAll = d => d.querySelectorAll('.modal').forEach(m => m.remove());

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'events', 'contacts', 'family', 'reading']}, CK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CK);
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  check(fr.http < 300, 'a person without an organisation');
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'}, FCK);

  for (const who of ['frida', 'alice']) {
    const w = await boot({user: who, hash: 'today'}), d = w.document;
    await until(() => w.eval('S.booted && typeof settingsModal === "function"'), 60);
    w.eval(`settingsModal('integr')`);
    const pane = await until(() => d.querySelector('.smodal [data-pane="integr"]'));
    check(pane && !pane.classList.contains('hidden'), `${who}: Integrations opens`);
    const rows = [...pane.querySelectorAll('details.introw')];
    check(rows.length >= 8, `${who}: the integrations are rows (${rows.length})`);
    check(rows.every(x => !x.open), `${who}: every row starts closed`);
    check(rows.every(x => x.querySelector(':scope > summary > svg') && (x.querySelector(':scope > summary > b')?.textContent || '').trim()), `${who}: every row has an icon and a name`);
    check(!pane.querySelector(':scope > h4'), `${who}: no heading of an integration outside its row`);
    for (const [k, h] of [['cals', '#s-cals-h'], ['ical', '#s-ical-h'], ['kk', '#s-kk-h'], ['nwl', '#s-nwl-h'], ['mail', '#s-mail-h'], ['share', '#s-share-h'], ['bmlet', '#s-bmlet-h'], ['carddav', '#s-carddav-h'], ['scan', '#s-scan-h']])
      check(row(d, k)?.querySelector(`.introw-b ${h}`), `${who}: the row ${k} holds the form (${h})`);
    check(/Calendar subscription/.test(row(d, 'ical')?.querySelector('summary')?.textContent || ''), `${who}: the row is named like its section`);

    // ---- the state from the data the pane loads
    check(await until(() => /^not connected$/.test(row(d, 'ical')?.querySelector('[data-intrst]')?.textContent || '')), `${who}: calendar subscription: "not connected"`);
    check(await until(() => /^not connected$/.test(row(d, 'kk')?.querySelector('[data-intrst]')?.textContent || '')), `${who}: Karakeep: "not connected"`);
    click(w, await until(() => row(d, 'ical').querySelector('[data-m="ical-create"]')));
    check(await until(() => /^connected$/.test(row(d, 'ical')?.querySelector('[data-intrst]')?.textContent || '')), `${who}: after creating the link: "connected"`);
    check(!(row(d, 'share')?.querySelector('[data-intrst]')?.textContent || ''), `${who}: a row without a state shows only its name`);

    // ---- the cards at the top open the row of their target
    const card = pane.querySelector('.icard[data-jump="#s-share-h"]');
    check(card && !row(d, 'share').open, `${who}: the card "Share from your phone", its row closed`);
    click(w, card);
    check(row(d, 'share').open, `${who}: the card opens its row`);
    const mc = pane.querySelector('.icard[data-jump="#s-mail-h"]');
    click(w, mc);
    check(row(d, 'mail').open, `${who}: the card "Send by e-mail" opens its row`);
    closeAll(d);

    // ---- a focus key lands on its open row
    w.eval(`settingsModal('karakeep')`);
    check(await until(() => row(d, 'kk')?.open), `${who}: settingsModal('karakeep') opens the row Karakeep`);
    check(!row(d, 'nwl').open, `${who}: … and leaves the others closed`);
    closeAll(d);

    // ---- the settings search finds a field in a closed row and opens the row
    w.eval(`settingsModal()`);
    await until(() => d.querySelector('#s-search'));
    check(row(d, 'ical') && !row(d, 'ical').open, `${who}: the subscription row closed again`);
    type(w, d, 'as calendar alarms');
    const hb = await until(() => [...d.querySelectorAll('#s-sres [data-hit]')].find(b => /calendar alarms/i.test(b.textContent)));
    check(!!hb, `${who}: the search finds a field inside a closed row`);
    click(w, hb);
    check(await until(() => row(d, 'ical')?.open && !d.querySelector('[data-pane="integr"]').classList.contains('hidden')), `${who}: the hit opens Integrations and the row`);
    type(w, d, 'Karakeep');
    const hk = await until(() => [...d.querySelectorAll('#s-sres [data-hit]')].find(b => /Integrations ›/.test(b.textContent) && /Karakeep/.test(b.textContent)));
    check(!!hk, `${who}: the search finds the row by its name`);
    click(w, hk);
    check(await until(() => row(d, 'kk')?.open), `${who}: a hit on the row's name opens the row`);
    await until(() => !d.querySelector('.sflash'));
    w.close();
  }

  console.log(`p2625_a_integr_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
