// kalmido-suite: fresh
// 2.555.0 B (#4664) UI tests: Settings > Company & office, the head and the findings 1-13 of the review of 05.11. Own
// container (start.sh), jsdom, invented data only. freelancer-matrix: office
// As the admin of an organisation's office (alice), as a person without an organisation (frida, her private office) and,
// for the lock hint, as a member (bob):
// - no "Applies to" with the workspace menu: no [data-act=ws-menu] in #s-biz, the area named once as plain text
// - heading levels: the groups h3 straight in the form, no h3 inside a part; "Company" and "Documents & numbers" each one
//   heading; no heading "Country pack" or "Functions" inside a part; the packs part is "Industry packs"; "Closing texts";
//   the test mode switch says "Test mode on"; a part that draws itself again gets its headings one level lower too
// - the paper size hint once (only in the letterhead part); the industry packs only on their cards (a link in the rules)
// - travel expenses / entertainment receipts under Bank & taxes, not Packs
// - every label[for] points to an element; no empty label (the agents switch); the locked home currency's label too
// - "Choose country" of a new office stays in Settings and leads to the country pack field
// - a member sees "Only admins and the bookkeeping change this." once
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
const FEAT = 'cal,comments,collab,files,docs,office,clients,travel';
const txt = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();

async function openBiz(who) {
  const w = await boot({user: who, hash: 'today'}), d = w.document;
  await until(() => d.querySelector('#side, main'));
  w.eval(`settingsModal('biz')`);
  const form = await until(() => d.querySelector('.smodal #s-biz #ofc-set #s-biz-company'), 100) && d.querySelector('.smodal #s-biz #ofc-set');
  return {w, d, form};
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, CK);
  const me = (await call('GET', '/api/state', null, CK)).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha Studio', admin_id: me}, CK)).id;
  check(!!ORG, 'an organisation');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${ORG}`}, CK);
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  check(fr.http < 300, 'a person without an organisation');
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'}, FCK);
  check(!((await call('GET', '/api/state', null, FCK)).me.workspaces || []).length, 'frida is in no organisation');
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'}, CK);
  await call('PUT', `/api/orgs/${ORG}/members`, {email: 'bob@example.com', role: 'member'}, CK);
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${ORG}`}, BK);

  for (const [who, area] of [['alice', 'Alpha Studio'], ['frida', 'Private']]) {
    const {w, d, form} = await openBiz(who);
    check(!!form, `${who}: the office settings in Settings > Company & office`);
    if (!form) { w.close(); continue; }
    const box = d.querySelector('#s-biz');
    // "Choose country" of the new office (first, before anything is saved): stays in Settings, to the country pack field
    const slim = await until(() => box.querySelector('.ocf-slim [data-ocf="to-pack"]'), 40);
    check(!!slim && !box.querySelector('.ocf-slim [data-go]'), `${who}: the new office's "Choose country" stays on the page`);
    if (slim) {
      click(w, slim);
      check(!!d.querySelector('.smodal') && !!(await until(() => d.querySelector('#s-biz #os-pack')?.closest('.row.sflash'), 20)) && w.location.hash !== '#office/pipeline' && w.location.hash !== '#office/offers', `${who}: "Choose country" marks the country pack field, Settings stay open`);
    }
    // the head: the area as text, no workspace menu
    check(!box.querySelector('[data-act="ws-menu"]'), `${who}: no workspace menu in Company & office`);
    check(txt(box.querySelector('.sbizws')) === `Workspace: ${area}` && box.querySelector('.sbizws')?.tagName === 'P', `${who}: the head names the area once as text: ` + txt(box.querySelector('.sbizws')));
    check(!/Applies to/.test(box.textContent), `${who}: no "Applies to"`);
    // heading levels
    const groups = [...form.querySelectorAll(':scope > h3')].map(h => h.id);
    check(groups[0] === 's-biz-company' && groups.includes('s-biz-docs') && groups.includes('s-biz-packs') && !form.querySelector(':scope > h4'), `${who}: the groups are h3 ` + groups.join());
    check(!form.querySelector('.ostp h3'), `${who}: no h3 inside a part ` + [...form.querySelectorAll('.ostp h3')].map(txt).join('|'));
    const heads = t => [...box.querySelectorAll('h3, h4, h5')].filter(h => txt(h) === t).length;
    check(heads('Company') === 1, `${who}: "Company" once ` + heads('Company'));
    check(heads('Documents & numbers') === 1, `${who}: "Documents & numbers" once`);
    check(heads('Functions') === 1 && heads('Packs') === 1 && !heads('Country pack'), `${who}: "Functions" and "Packs" once, no heading "Country pack"`);
    check(d.getElementById('pkc-h')?.tagName === 'H4' && txt(d.getElementById('pkc-h')) === 'Industry packs', `${who}: the packs part is h4 "Industry packs"`);
    check([...form.querySelectorAll('[data-ostp="docs"] h4')].some(h => txt(h) === 'Closing texts'), `${who}: the closing texts have their heading`);
    const tri = await until(() => d.getElementById('tri-mode'), 40);
    check(tri && txt(tri.closest('label')) === 'Test mode on' && d.getElementById('tri-h')?.tagName === 'H4', `${who}: the test mode: heading h4, the switch "Test mode on"`);
    // the paper size hint: once, in the letterhead part
    check(!d.getElementById('os-paper-hint') && !!(await until(() => d.getElementById('bp-paper-hint'), 40)), `${who}: one paper size hint place (letterhead)`);
    w.eval(`BPL.st = {...(BPL.st || {}), on: 1, paper: 'a4'}; bp_paperShow('letter')`);
    check([...box.querySelectorAll('.dtp-warn')].filter(x => !x.hidden && /US-Letter/.test(x.textContent)).length === 1, `${who}: a paper size mismatch is said once`);
    // the industry packs: switched on their cards only
    check(!form.querySelector('input[id^="os-ind-"]') && !!form.querySelector('[data-ostp="docs"] .ostind [data-ostgo="pkc"]'), `${who}: no pack boxes in the calculation rules, a link to the packs`);
    check(await until(() => d.querySelector('.smodal #ofc-set #pkc [data-pkc-on="film"]'), 60), `${who}: the film pack's card has its switch`);
    // a part that draws itself again: its h3 becomes h4, its h4 h5 (the observer of biz_paint); the form itself may be drawn
    // anew meanwhile (then the two are put in again)
    check(await until(() => {
      const x = d.getElementById('p2555-x'), y = d.getElementById('p2555-y');
      if (!x) { d.querySelector('.smodal #ofc-set [data-ostp="data"]')?.insertAdjacentHTML('beforeend', '<h3 id="p2555-x">X</h3><h4 id="p2555-y">Y</h4>'); return false; }
      return x.tagName === 'H4' && y?.tagName === 'H5' && x.dataset.hl === '1';
    }, 20), `${who}: a redrawn part's headings one level lower`);
    // travel expenses / entertainment receipts under Bank & taxes
    const lf = () => d.querySelector('.smodal #s-biz #ofc-set');
    const rk = await until(() => lf()?.querySelector('.rkpset'), 40);
    check(!rk || rk.closest('[data-ostp]')?.dataset.ostp === 'tax', `${who}: travel expenses under Bank & taxes`);
    const bw = lf()?.querySelector('.bwcset');
    check(!bw || bw.closest('[data-ostp]')?.dataset.ostp === 'tax', `${who}: entertainment receipts under Bank & taxes`);
    check(![...lf().querySelectorAll('[data-ostp="packs"]')].some(f => f.querySelector('.rkpset, .bwcset')), `${who}: nothing of travel / entertainment under Packs`);
    // labels
    const bad = [...box.querySelectorAll('label[for]')].filter(l => !d.getElementById(l.getAttribute('for'))).map(l => l.getAttribute('for'));
    check(!bad.length, `${who}: every label points to an element ` + bad.join());
    const empty = [...box.querySelectorAll('label')].filter(l => !txt(l) && !l.querySelector('input, select, textarea, img, svg'));
    check(!empty.length, `${who}: no empty label ` + empty.map(l => l.outerHTML.slice(0, 80)).join(' | '));
    check(!!d.getElementById('os-agents-read') && !d.getElementById('os-agents-read').closest('.row').querySelector('label:empty'), `${who}: the agents switch without an empty label`);
    // the locked home currency: the label points to the shown value
    const hh = w.eval(`(() => { const i = OFC.info, a = i.home_locked, p = i.pack; i.home_locked = 1; i.pack = {...p, currency_editable: 1}; const h = ost_homeHtml(i.settings || {}, ''); i.home_locked = a; i.pack = p; return h; })()`);
    check(/for="os-home-v"/.test(hh) && /id="os-home-v"/.test(hh), `${who}: the locked home currency's label points to its value`);
    w.close();
  }

  // a member: the lock hint once, no group made of it alone
  {
    const {w, d, form} = await openBiz('bob');
    check(!!form && !!d.querySelector('.ofclockhint'), 'bob: the settings with the lock hint');
    const n = (d.querySelector('#s-biz')?.textContent || '').split('Only admins and the bookkeeping change this.').length - 1;
    check(n === 1, 'bob: "Only admins and the bookkeeping change this." once: ' + n);
    check(!d.querySelector('#s-biz [data-act="ws-menu"]') && txt(d.querySelector('#s-biz .sbizws')) === 'Workspace: Alpha Studio', 'bob: the area as text');
    w.close();
  }

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
