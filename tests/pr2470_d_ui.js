// kalmido-suite: fresh
// 2.470.0 UI tests of part D (#3596, points 3 and 5): the page office/settings became a jump into Settings > Company & office
// (own container, start.sh, jsdom, invented data only). freelancer-matrix: office
// - an old link opens the dialog with one form #ofc-set, the address is replaced (no page in the history, no way back into a circle)
// - the same for a person without an organisation and for a member (reads only, fields locked)
// - a person without the settings lands on "My rights" at office/rights
// - office/import and office/rights stay pages; both lead back into Settings; services and text blocks too
// - Texts & templates: one row per catalogue, the rows open their pages; the settings search finds them
// - Settings as the last point of the office does not bring the dialog up again when the office is opened
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until: untilB} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); let j = null; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...(j || {})}; };
const until = fn => untilB(fn, {timeout: 15000, step: 120}).catch(() => null);
const FEAT = 'cal,comments,collab,files,docs,office,clients';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const ORG = (await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id})).id;
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  await call(CA, 'POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  await call(CA, 'POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  const CB = await login('bob'), CF = await login('frida');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});

  // ================= an old link, for the admin of an organisation and a person without one
  for (const who of ['alice', 'frida']) {
    const w = await boot({user: who, hash: 'office/settings'}), d = w.document;
    check(!!(await until(() => d.querySelector('.smodal #s-biz #ofc-set'))), `${who}: an old link opens Settings > Company & office`);
    check(d.querySelector('.snav [data-sec="biz"]')?.getAttribute('aria-selected') === 'true', `${who}: on the right area`);
    check(!!(await until(() => w.location.hash === '#office/start')), `${who}: the address is replaced ` + w.location.hash);
    check(d.querySelectorAll('#ofc-set').length === 1, `${who}: one form on the screen`);
    check(!d.querySelector('#ofc-set .ostsub') && !d.querySelector('#ofc-set [data-ostp][hidden]'), `${who}: no tab row, nothing hidden`);
    check(!d.querySelector('#ofc-set input:not([type=file])')?.disabled, `${who}: the fields can be changed`);
    const rows = [...d.querySelectorAll('#s-biz-tpl ~ [data-ostp="tpl"] [data-osttpl]')].map(a => a.dataset.osttpl).join();
    check(rows === 'services,texts,gendocs', `${who}: Texts & templates has its three rows ` + rows);
    await sleep(300);
    check(d.querySelectorAll('.smodal').length === 1 && w.location.hash === '#office/start', `${who}: no second jump`);
    // the way into a catalogue and back
    d.querySelector('[data-osttpl="services"]').click();
    check(!!(await until(() => w.location.hash === '#office/services' && !d.querySelector('.smodal') && d.querySelector('.office [data-setgo="biz-tpl"]'))), `${who}: the row leads to the services, Settings close`);
    d.querySelector('.office [data-setgo="biz-tpl"]').click();
    check(!!(await until(() => d.querySelector('.smodal #s-biz #ofc-set'))), `${who}: and back into Settings`);
    check(w.location.hash === '#office/services', `${who}: the page stays below the dialog`);
    // Settings kept as the last point: the office opens on a page, never on the dialog
    w.eval(`LS.set('ofmLast', 'settings')`);
    check(w.eval(`ofm_entry().key`) !== 'settings', `${who}: the office does not open on Settings`);
    w.close();
    for (const [hash, sel] of [['office/import', '.oim'], ['office/rights', '.orr']]) {
      const x = await boot({user: who, hash}), e = x.document;
      check(!!(await until(() => e.querySelector(sel))), `${who}: ${hash} stays a page`);
      check(x.location.hash === '#' + hash && !e.querySelector('.smodal'), `${who}: ${hash} does not jump`);
      check(!!(await until(() => e.querySelector('.office [data-setgo="biz"]'))), `${who}: ${hash} leads back`);
      e.querySelector('.office [data-setgo="biz"]').click();
      check(!!(await until(() => e.querySelector('.smodal #s-biz #ofc-set'))), `${who}: back from ${hash} opens Settings`);
      x.close();
    }
  }

  // ================= a member reads
  {
    const w = await boot({user: 'bob', hash: 'office/settings'}), d = w.document;
    check(!!(await until(() => d.querySelector('.smodal #s-biz #ofc-set'))), 'member: the old link opens Settings');
    check(d.querySelector('#os-name')?.disabled && !!d.querySelector('#ofc-set .ofclockhint'), 'member: fields locked, with the hint');
    w.close();
    check((await call(CB, 'PUT', '/api/office/settings', {payment_days: 3})).http === 403, 'member: the server refuses a change');
  }

  // ================= a person without the settings: "My rights", at its own address
  {
    const bob = (await call(CB, 'GET', '/api/state')).me.id;
    const pa = await call(CA, 'PUT', `/api/office/rights/people/${bob}`, {groups: ['tpl:staff']});
    const lv = (await call(CB, 'GET', '/api/office/settings')).rights?.levels?.settings;
    check(pa.http === 200 && (lv || 'none') === 'none', 'Bob in a group without the settings ' + pa.http + ' ' + lv);
    const w = await boot({user: 'bob', hash: 'office/settings'}), d = w.document;
    check(!!(await until(() => w.location.hash === '#office/rights' && d.querySelector('.orr'))), 'no right: the old link ends on My rights ' + w.location.hash);
    check(!d.querySelector('.smodal') && !d.querySelector('.office [data-setgo]'), 'no right: no dialog, no way into Settings');
    w.close();
  }

  // ================= the settings search
  {
    const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
    w.eval(`settingsModal('biz')`);
    await until(() => d.querySelector('.smodal #s-biz #ofc-set'));
    const sq = d.querySelector('#s-search');
    for (const [q, lab] of [['textbausteine', 'Text blocks'], ['leistungen', 'Services'], ['dokumentvorlagen', 'Document templates']]) {
      sq.dispatchEvent(new w.FocusEvent('focus')); sq.value = q; sq.dispatchEvent(new w.Event('input', {bubbles: true}));
      const hs = await until(() => { const x = [...d.querySelectorAll('#s-sres [data-hit]')].map(b => b.textContent); return x.length ? x : null; });
      check((hs || []).some(t => t.includes(lab)), `search "${q}" finds ${lab} ` + JSON.stringify(hs));
    }
    w.close();
  }
  console.log(F.length ? `FAILED ${F.length} (${ok} ok)` : `all ${ok} checks passed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
