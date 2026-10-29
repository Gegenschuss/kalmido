// kalmido-suite: fresh
// 2.365.2 A (#2789) UI tests: the office's settings moved into Settings > Company & office. Own container (start.sh), jsdom,
// invented data only. freelancer-matrix: office
// - Settings has the area "Company & office" while the office module is on (not with the module off)
// - it shows the office's settings form (#ofc-set) of the current workspace, the areas one below the other with a heading
//   each (no tab row, no hidden part), "Applies to" with the workspace
// - a field saves itself there (autosave, the same PUT as the office page)
// - the office menu's point Settings opens Settings > Company & office (the page office/settings stays for old links)
// - the workspace's mailbox (IMAP / SMTP) with Set up / Change in Company & office
// - the same for a person without an organisation (their private office, they are its admin)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); let j = null; try { j = await r.json(); } catch { j = null; } return {http: r.status, ...(j || {})}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,files,docs,office,clients';

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

  for (const [who, ck] of [['alice', CK], ['frida', FCK]]) {
    let w = await boot({user: who, hash: 'today'}), d = w.document;
    await until(() => d.querySelector('#side, main'));
    w.eval(`settingsModal('biz')`);
    const md = await until(() => d.querySelector('.smodal'));
    check(md?.querySelector('.snav [data-sec="biz"]')?.getAttribute('aria-selected') === 'true', `${who}: settingsModal('biz') opens Company & office`);
    const form = await until(() => d.querySelector('.smodal #s-biz #ofc-set'), 100);
    check(!!form, `${who}: the office settings form sits in Settings`);
    if (form) {
      check(!form.querySelector('.ostsub') && !form.querySelector('[data-ostp][hidden]'), `${who}: no tab row, no hidden area`);
      const hs = [...form.querySelectorAll(':scope > h4')].map(h => h.id);
      check(hs[0] === 's-biz-company' && hs.includes('s-biz-docs') && hs.length >= 4, `${who}: one heading per area, Company first ` + hs.join());
      check(/Applies to/.test(d.querySelector('#s-biz .sbizws')?.textContent || ''), `${who}: "Applies to" names the workspace`);
      check(!form.querySelector('#os-paydays')?.disabled, `${who}: the own office is editable`);
      // a field saves itself (autosave): change + focus out, the server has it
      const f = form.querySelector('#os-paydays');
      if (f) {
        f.value = '21'; f.dispatchEvent(new w.Event('change', {bubbles: true}));
        const got = await until(async () => (await call('GET', '/api/office/settings', null, ck)).settings?.payment_days === 21, 60);
        check(got, `${who}: payment terms saved from Settings`);
      }
    }
    // the workspace's mailbox (IMAP / SMTP) sits in Company & office too, as far as the person may set it up
    await until(() => w.eval(`typeof HMB !== 'undefined' && !!HMB.j`), 60);
    const sp = JSON.parse(w.eval(`JSON.stringify((HMB.j?.spaces || []).find(x => x.ws === ofcWs()) || null)`) || 'null');
    if (sp?.manage) check(!!(await until(() => d.querySelector('#s-bizmail-h') && d.querySelector(`#s-bizmail [data-hmba="edit"]`), 40)), `${who}: E-mail with Set up / Change in Company & office`);
    else check(!d.querySelector('#s-bizmail [data-hmba="edit"]'), `${who}: no mailbox button without the right`);
    // Company & office goes away with the office module
    d.querySelector('.smodal [data-m="close"]')?.click();
    await until(() => !d.querySelector('.smodal'));
    w.close();

    // the office menu's Settings open Settings > Company & office
    w = await boot({user: who, hash: 'office/offers'}); d = w.document;
    const pt = await until(() => d.querySelector('#side [data-ofm="settings"]'), 100);
    check(!!pt, `${who}: the office menu has Settings`);
    if (pt) {
      click(w, pt);
      check(!!(await until(() => d.querySelector('.smodal #s-biz #ofc-set'), 100)), `${who}: the menu point opens Settings > Company & office`);
      check(w.location.hash !== '#office/settings', `${who}: no page change to office/settings ` + w.location.hash);
      check(d.querySelectorAll('#ofc-set').length === 1, `${who}: one settings form on the screen`);
    }
    w.close();
  }

  // office off: no area Company & office
  await call('PATCH', '/api/settings', {features: 'cal,comments,collab,files'}, FCK);
  const w = await boot({user: 'frida', hash: 'today'}), d = w.document;
  await until(() => d.querySelector('#side, main'));
  w.eval(`settingsModal()`);
  const md = await until(() => d.querySelector('.smodal'));
  check(md && !md.querySelector('.snav [data-sec="biz"]'), 'office off: no area Company & office');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
