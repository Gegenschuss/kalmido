// kalmido-suite: fresh
// 2.353.0 E (#2775) UI tests: the settings search finds the settings windows of the areas. Own container (start.sh), jsdom,
// invented data only. freelancer-matrix: settings
// - "Scanner" and "Download" find the folder watcher (Settings > Integrations > Scans from your computer, #2773); the jump
//   marks it (class sflash)
// - a hit from an area window ("Sorting automatically" of the documents, "Letterhead" of the office settings) names the area,
//   opens the area + its window and marks the section
// - only windows whose module is on: documents off = no hit from the documents window
// - a phone: the search field is in the head of the settings overview (not hidden), a hit works from there
// - the same for a person without an organisation
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); let j = null; try { j = await r.json(); } catch {} return {http: r.status, ...(j || {})}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,files,docs,office,clients';
const type = (w, d, q) => { const sq = d.querySelector('#s-search'); sq.dispatchEvent(new w.FocusEvent('focus')); sq.value = q; sq.dispatchEvent(new w.Event('input', {bubbles: true})); };
// the hit is the section heading or its card at the top of Integrations (a button that jumps to it): either is marked
const SCAN = '#s-scan-h.sflash, .icard[data-jump="#s-scan-h"].sflash';
const hits = d => [...d.querySelectorAll('#s-sres [data-hit]')];
const openSettings = async (w, d) => { w.eval(`settingsModal()`); return until(() => d.querySelector('#s-search')); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, CK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'}, CK);
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  check(fr.http < 300, 'a person without an organisation');
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'}, FCK);

  for (const who of ['alice', 'frida']) {
    let w = await boot({user: who, hash: 'today'}); let d = w.document;
    await until(() => d.querySelector('#side'));
    // ---- "Scanner" / "Download" find the folder watcher under Integrations
    for (const q of ['scanner', 'download', 'Scanner']) {
      check(await openSettings(w, d), `${who}: the settings open`);
      type(w, d, q);
      const hb = hits(d).find(b => /Integrations ›/.test(b.textContent) && /Scans from your computer/.test(b.textContent));
      check(!!hb, `${who}: "${q}" finds Integrations › Scans from your computer ` + JSON.stringify(hits(d).map(b => b.textContent)));
      if (hb) {
        click(w, hb);
        check(!!(await until(() => d.querySelector(SCAN))), `${who}: "${q}": the jump marks the folder watcher's section`);
        check(!d.querySelector('[data-pane="integr"]')?.classList.contains('hidden'), `${who}: "${q}": Integrations is the shown tab`);
      }
      d.querySelector('.smodal [data-m="close"]')?.click();
      await until(() => !d.querySelector('#s-search'));
    }
    // ---- a hit from the documents window: names the area, opens the window, marks the section
    await openSettings(w, d);
    type(w, d, 'sorting');
    let hb = hits(d).find(b => /Settings of the documents/.test(b.textContent));
    check(hb && /File store/.test(hb.textContent) && /Sorting automatically/.test(hb.textContent), `${who}: "sorting" offers File store › Settings of the documents › Sorting automatically ` + JSON.stringify(hits(d).map(b => b.textContent)));
    if (hb) {
      click(w, hb);
      check(!!(await until(() => !d.querySelector('#s-search') && d.querySelector('.dc-smd'))), `${who}: the settings close, the documents' settings window opens`);
      const fl = await until(() => d.querySelector('.dc-smd .sflash'));
      check(fl && /Sorting automatically/.test(fl.textContent), `${who}: the section "Sorting automatically" is marked ` + (fl && fl.outerHTML.slice(0, 80)));
      check(w.eval('S.route.mod') === 'docs', `${who}: the area of the window is open (docs) ` + w.eval('S.route.mod'));
      d.querySelector('.dc-smd [data-dcs="close"]')?.click(); d.querySelector('.dc-smd')?.remove();
    }
    // ---- a hit from the office settings: route office/settings, the pane switched, the section marked
    await openSettings(w, d);
    type(w, d, 'letterhead');
    hb = hits(d).find(b => /Office ›/.test(b.textContent) && /Letterhead/.test(b.textContent));
    check(!!hb, `${who}: "letterhead" offers Office › Settings › Letterhead ` + JSON.stringify(hits(d).map(b => b.textContent)));
    if (hb) {
      click(w, hb);
      check(!!(await until(() => d.querySelector('#ofc-set'))), `${who}: the office settings open`);
      const fl = await until(() => d.querySelector('#ofc-set .sflash'));
      check(!!fl && !fl.closest('[hidden]'), `${who}: the letterhead is marked and its pane is shown ` + (fl ? fl.outerHTML.slice(0, 80) : w.eval(`JSON.stringify({bp: !!$('#bp-h'), hid: !!$('#bp-h')?.closest('[hidden]'), panes: $$('#ofc-set [data-ostp]').map(p => p.dataset.ostp + (p.hidden ? '-' : '+')), dash: !!$('#ofc-set')?.closest('.modal, .card, .dash'), ost: typeof ost_show})`)));
      check(w.eval(`location.hash`) === '#office/settings', `${who}: the route is office/settings ` + w.eval('location.hash'));
    }
    await until(() => !d.querySelector('.sflash'));  // the ring is over (its observer stopped) before the window goes
    w.close();

    // ---- a phone: the search sits in the head of the settings overview and works from there
    w = await boot({user: who, hash: 'today', mobile: true}); d = w.document;
    await until(() => d.querySelector('#side, .tabbar, main'));
    check(await openSettings(w, d), `${who} phone: the settings open`);
    const md = d.querySelector('.smodal'), ss = d.querySelector('.smodal .shdr .ssearch');
    check(md && md.classList.contains('sidx'), `${who} phone: the overview of the settings is shown`);
    check(ss && w.getComputedStyle(ss).display !== 'none' && !ss.closest('[hidden], .hidden'), `${who} phone: the search field is visible in the head of the overview`);
    type(w, d, 'download');
    hb = hits(d).find(b => /Scans from your computer/.test(b.textContent) && /Integrations ›/.test(b.textContent));
    check(!!hb, `${who} phone: "download" finds the folder watcher`);
    if (hb) { click(w, hb); check(!!(await until(() => d.querySelector(SCAN))) && !md.classList.contains('sidx'), `${who} phone: the hit leaves the overview and marks the section`); }
    await until(() => !d.querySelector('.sflash'));  // the ring is over (its observer stopped) before the window goes
    w.close();
  }

  // ---- only windows whose module is on: documents and office off = no hit from their windows
  await call('PATCH', '/api/settings', {features: 'cal,comments,collab,files'}, FCK);
  const w = await boot({user: 'frida', hash: 'today'}); const d = w.document;
  await until(() => d.querySelector('#side'));
  await openSettings(w, d);
  for (const q of ['sorting', 'letterhead']) {
    type(w, d, q);
    check(!hits(d).some(b => /Settings of the documents|Office ›/.test(b.textContent)), `module off: "${q}" offers no window of a switched-off area ` + JSON.stringify(hits(d).map(b => b.textContent)));
  }
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
