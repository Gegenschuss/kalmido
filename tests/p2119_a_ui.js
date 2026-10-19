// 2.119.0 UI tests, part A (#2288): entertainment receipts in the office, own container (start.sh), Firefox (desktop + phone
// width), an organisation's admin and a person without an organisation. Invented companies, people and figures only.
// - the menu point under Money, the empty list; the mask: a new place (name + address), the host = me, a new guest with
//   company, two amount lines, the tip, the live total, saved as a draft; approving locks it (the list tag, the mask read-only
//   with the confirmation), the new place and guest are in the choices of the next mask
// - the row menu: PDF, duplicate, undo the approval with a reason (one undo step re-approves), delete a draft with undo
// - the filters (year, person, occasion) for the list and the evaluation (70 / 30, CSV / PDF links with the filters)
// - the office settings: the choice lists (rename in place, remove + undo)
// - the phone (390 px): the mask fits, targets >= 44 px; a person without an organisation has the module -- freelancer-matrix: office
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2119_a_ui', check, shots: 'P2119A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2119A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.http < 300, 'a person without an organisation');
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const y = String(new Date().getFullYear());
  const old = await call(CA, 'POST', '/api/office/meals', {date: `${y}-01-10`, place_name: 'Bistro Beispiel', place_address: 'Hauptstraße 5, 12345 Musterstadt',
    occasion: 'Planning of the trade fair stand', host: {id: me.id}, guests: [{name: 'Otto Beispiel', extra: 'Example AG'}], amounts: [{kind: 'food', rate: 19, gross: 59.5}]});
  check(old.http === 201 && (await call(CA, 'POST', `/api/office/meals/${old.id}/approve`)).http === 200, 'one approved receipt of this year');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const getJ = url => `fetch('${url}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  const noSide = sel => `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('${sel} *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const setv = (sel, v) => `(() => { const x = document.querySelector('${sel}'); x.value = ${JSON.stringify(v)}; x.dispatchEvent(new Event('input', {bubbles: true})); x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`;
  const clk = sel => `(() => { const x = document.querySelector('${sel}'); if (!x) return 0; x.click(); return 1; })()`;
  const menuClick = label => `(() => { const b = [...document.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim().startsWith(${JSON.stringify(label)})); if (!b) return 0; b.click(); return 1; })()`;
  const rowMore = txt => `(() => { const l = [...document.querySelectorAll('.bwlist li')].find(l => l.textContent.includes(${JSON.stringify(txt)})); if (!l) return 0; l.querySelector('[data-bw="rowmore"]').click(); return 1; })()`;
  const meals = async ev => (await ev(`${getJ('/api/office/meals?year=' + y)}.then(j => j.meals)`));
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/meals');
    check(await ready(ev, `!!document.querySelector('#bw-year')`, 80), 'the tab Entertainment receipts');
    check(await ev(`[...document.querySelectorAll('[data-ofm="meals"]')].some(b => /Entertainment receipts/.test(b.textContent))`), 'a menu point of the office');
    check(await ready(ev, `document.querySelectorAll('.bwlist .ofcrow').length === 1 && !!document.querySelector('.bwlist .bwok')`), 'the approved receipt in the list, tagged');

    // ---- the mask
    await ev(clk('[data-bw="new"]'));
    check(await ready(ev, `!!document.querySelector('.modal #bw-place')`), 'the mask');
    check(await ev(`document.querySelector('.modal #bw-host').value === 'u${me.id}'`), 'the host is me');
    check(await ev(`[...document.querySelector('.modal #bw-place').options].some(o => o.textContent === 'Bistro Beispiel') && [...document.querySelectorAll('.modal [data-bwg]')].some(x => /Otto Beispiel/.test(x.closest('label').textContent))`),
      'the place and the guest of the approved receipt are in the choices');
    await ev(setv('.modal #bw-place', '__new'));
    check(await ready(ev, `!document.querySelector('.modal .bwpnew').hidden`), 'New place… opens name and address');
    await ev(setv('.modal #bw-pname', 'Osteria Muster'));
    await ev(setv('.modal #bw-paddr', 'Marktplatz 7\n12345 Musterstadt'));
    await ev(setv('.modal #bw-occ', 'Kick-off of the image film for Example AG'));
    await ev(setv('.modal #bw-gname', 'Rita Rot'));
    await ev(setv('.modal #bw-gextra', 'Example AG, marketing'));
    await ev(clk('.modal [data-bwm="addguest"]'));
    check(await ready(ev, `[...document.querySelectorAll('.modal [data-bwg]')].some(x => x.checked && /Rita Rot/.test(x.closest('label').textContent))`), 'a new guest, chosen');
    await ev(`(() => { const g = document.querySelectorAll('.modal [data-bwl="gross"]'); g[0].value = '238'; g[1].value = '32,10'; g[1].dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await ev(`(() => { const r = document.querySelectorAll('.modal [data-bwl="rate"]'); r[1].value = '7'; r[1].dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await ev(setv('.modal #bw-tip', '20'));
    check(await ready(ev, `/290[.,]10/.test(document.querySelector('.modal .bwsum').textContent)`), 'the live total ' + await ev(`document.querySelector('.modal .bwsum')?.textContent`));
    check(await ev(`!document.querySelector('.modal .bw250').hidden`), 'from 250 € the hint about the company bill');
    await shot('p2119-a-mask.png');
    await ev(clk('.modal [data-bwm="save"]'));
    check(await ready(ev, `${getJ('/api/office/meals?year=' + y)}.then(j => j.meals.some(m => m.place_name === 'Osteria Muster' && m.status === 'draft' && m.calc.gross === '290.10' && m.guests.some(g => g.name === 'Rita Rot' && g.extra === 'Example AG, marketing')))`),
      'saved as a draft with its data');
    check(await ready(ev, `!document.querySelector('.modal') && [...document.querySelectorAll('.bwlist li')].some(l => /Osteria Muster/.test(l.textContent) && l.querySelector('.bwdraft'))`), 'the list: the draft');
    const nid = (await meals(ev)).find(m => m.place_name === 'Osteria Muster').id;

    // ---- approve from the mask
    await ev(`(() => { [...document.querySelectorAll('.bwlist .ofcrow')].find(b => /Osteria Muster/.test(b.textContent)).click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('.modal #bw-pname')?.value === 'Osteria Muster'`), 'the draft opens in the mask');
    await ev(clk('.modal [data-bwm="approve"]'));
    check(await ready(ev, `${getJ('/api/office/meals/' + nid)}.then(m => m.status === 'approved')`), 'approved');
    check(await ready(ev, `[...document.querySelectorAll('.bwlist li')].some(l => /Osteria Muster/.test(l.textContent) && l.querySelector('.bwok'))`), 'the list: approved');
    check(await ev(`${getJ('/api/office/meals/choices')}.then(j => j.places.some(p => p.name === 'Osteria Muster') && j.persons.some(p => p.name === 'Rita Rot'))`), 'the new place and guest joined the choices');
    await ev(`(() => { [...document.querySelectorAll('.bwlist .ofcrow')].find(b => /Osteria Muster/.test(b.textContent)).click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal .bwlocked') && document.querySelector('.modal .bwfs').disabled && !document.querySelector('.modal [data-bwm="save"]')`), 'the mask is read-only with the confirmation');
    check(await ev(`!!document.querySelector('.modal [data-bwm="unlock"]') && !!document.querySelector('.modal .bwlog li')`), 'undo the approval + the log');
    await shot('p2119-a-locked.png');
    await ev(clk('.modal [data-bwm="close"]'));

    // ---- the row menu
    await ready(ev, `!document.querySelector('.modal')`);
    await ev(rowMore('Osteria Muster'));
    check(await ready(ev, `[...document.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim()).join('|') === 'Open|PDF|Duplicate|Undo approval…'`),
      'the menu of an approved receipt ' + await ev(`[...document.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim()).join('|')`));
    await ev(menuClick('Undo approval'));
    check(await ready(ev, `!!document.querySelector('#cdlg-in')`), 'it asks for a reason');
    await ev(`(() => { const x = document.querySelector('#cdlg-in'); x.value = 'Wrong tip'; document.querySelector('[data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `${getJ('/api/office/meals/' + nid)}.then(m => m.status === 'draft' && m.log.at(-1).reason === 'Wrong tip')`), 'undone and logged with the reason');
    await ev(clk('#toast button'));
    check(await ready(ev, `${getJ('/api/office/meals/' + nid)}.then(m => m.status === 'approved' && m.log.length === 3)`), 'one undo step approves it again (logged)');
    await ready(ev, `[...document.querySelectorAll('.bwlist li')].some(l => /Osteria Muster/.test(l.textContent) && l.querySelector('.bwok'))`);
    await ev(rowMore('Osteria Muster'));
    await ready(ev, `!!document.querySelector('#pop .menu-list button')`);
    await ev(menuClick('Duplicate'));
    check(await ready(ev, `${getJ('/api/office/meals?year=' + y)}.then(j => j.meals.filter(m => m.place_name === 'Osteria Muster').length === 2)`), 'Duplicate: a copy');
    await ready(ev, `!!document.querySelector('.modal #bw-pname')`);
    await ev(`(() => { document.querySelector('.modal').remove(); return 1; })()`);
    await ready(ev, `document.querySelectorAll('.bwlist .bwdraft').length === 1`);
    await ev(`(() => { [...document.querySelectorAll('.bwlist li')].find(l => l.querySelector('.bwdraft')).querySelector('[data-bw="rowmore"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('#pop .menu-list button.danger')`);
    await ev(clk('#pop .menu-list button.danger'));
    await ready(ev, `!!document.querySelector('[data-cd="yes"]')`);
    await ev(clk('[data-cd="yes"]'));
    check(await ready(ev, `${getJ('/api/office/meals?year=' + y)}.then(j => j.meals.length === 2)`), 'the draft deleted');
    await ev(clk('#toast button'));
    check(await ready(ev, `${getJ('/api/office/meals?year=' + y)}.then(j => j.meals.length === 3)`), 'one undo step brings it back');

    // ---- the filters + the evaluation
    await ev(setv('#bw-occf', 'trade fair'));
    check(await ready(ev, `document.querySelectorAll('.bwlist .ofcrow').length === 1`), 'the occasion filter');
    await ev(setv('#bw-occf', ''));
    check(await ready(ev, `document.querySelectorAll('.bwlist .ofcrow').length === 3 && !!document.querySelector('#bw-person')`), 'all again, a person choice');
    await ev(setv('#bw-person', 'n:otto beispiel'));
    check(await ready(ev, `document.querySelectorAll('.bwlist .ofcrow').length === 1`), 'the person filter (a guest)');
    await ev(clk('[data-bw="view"][data-v="report"]'));
    check(await ready(ev, `!!document.querySelector('.bwcards') && document.querySelector('#bw-person').value === 'n:otto beispiel'`, 60), 'the evaluation keeps the filter');
    check(await ev(`/35[.,]00/.test(document.querySelector('.bwmain').textContent) && [...document.querySelectorAll('.ofcbar a[href*="/meals/report"]')].every(a => /person=n%3Aotto/.test(a.getAttribute('href')))`),
      '70 % of the filtered net, CSV / PDF with the filter ' + await ev(`document.querySelector('.bwmain')?.textContent`));
    await ev(setv('#bw-person', ''));
    check(await ready(ev, `/1 draft|approve it first/.test(document.querySelector('.office').textContent) || document.querySelectorAll('.bwcards').length === 1`), 'all people');
    await shot('p2119-a-report.png');

    // ---- the phone
    await ev(clk('[data-bw="view"][data-v="list"]'));
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(500);
    check(await ready(ev, `document.querySelectorAll('.bwlist [data-bw="rowmore"]').length === 3`), 'the list on a phone');
    check(await ev(`[...document.querySelectorAll('.bwlist [data-bw="rowmore"]')].every(b => { const r = b.getBoundingClientRect(); return r.width >= 43 && r.height >= 43; })`), 'the arrow is a 44 px target');
    await ev(clk('[data-bw="new"]'));
    check(await ready(ev, `!!document.querySelector('.modal #bw-place')`), 'the mask on a phone');
    check(await ev(noSide('.modal')), 'nothing sticks out to the side');
    check(await ev(`[...document.querySelectorAll('.modal .bwln select, .modal .bwln input, .modal .bwg, .modal [data-bwm="approve"]')].every(e => e.getBoundingClientRect().height >= 43)`), 'the fields are 44 px targets');
    await shot('p2119-a-phone.png');
    await ev(`(() => { document.querySelector('.modal').remove(); return 1; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});

    // ---- the office settings
    await nav(B + '#office/settings');
    check(await ready(ev, `document.querySelectorAll('.bwcset input[data-bwc="name"]').length === 4`, 80), 'the settings list the places and people');
    await ev(`(() => { const x = [...document.querySelectorAll('.bwcset input[data-bwc="name"]')].find(i => i.value === 'Rita Rot'); x.value = 'Rita Roth'; x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `${getJ('/api/office/meals/choices')}.then(j => j.persons.some(p => p.name === 'Rita Roth'))`), 'renamed in place');
    check(await ev(`${getJ('/api/office/meals/' + nid)}.then(m => m.guests.some(g => g.name === 'Rita Rot'))`), 'the receipt keeps its text');
    await ev(clk('.bwcset [data-bwc="del"]'));
    check(await ready(ev, `${getJ('/api/office/meals/choices')}.then(j => j.places.length + j.persons.length === 3)`), 'removed');
    await ev(clk('#toast button'));
    check(await ready(ev, `${getJ('/api/office/meals/choices')}.then(j => j.places.length + j.persons.length === 4)`), 'one undo step brings it back');
    check(await ev(`location.hash === '#office/settings'`), 'still the settings');
    await shot('p2119-a-settings.png');

    // ---- a person without an organisation
    await signIn(ev, 'frida');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/meals');
    check(await ready(ev, `!!document.querySelector('#bw-year')`, 80), 'freelancer: the tab in the personal office');
    check(await ev(`!document.querySelector('.bwlist') && !document.querySelector('#bw-person')`), 'freelancer: an empty list, no person choice');
    await ev(clk('[data-bw="new"]'));
    check(await ready(ev, `document.querySelector('.modal #bw-host')?.value === 'u${fr.id}'`), 'freelancer: she is the host');
    check(await ev(`!document.querySelector('.modal [data-bwg]') || ![...document.querySelectorAll('.modal [data-bwg]')].some(x => /Rita|Otto/.test(x.closest('label').textContent))`), 'freelancer: none of the organisation\'s choices');
    await ev(`(() => { document.querySelector('.modal').remove(); return 1; })()`);
  }, false);

  console.log(`p2119_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
