// 2.168.0 part A UI test (#2665; 2.435.0 #3606: the button + project picker), own container (start.sh): a document's project. The editor of a FINALISED quotation shows
// the row "Project" outside the locked fieldset (usable), the client's projects in their own group on top; picking one saves
// it, "Open project" links to it; "Create new project" shows a name field preset with "Client – project title" and creates
// it. The project page shows "Quotations & invoices" with number, status and amount (a click opens the document); a member
// without the office module sees no such section. Desktop and the phone width. Invented names only. P2168AUI_NOSTART=1 =
// the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2168AUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const FEAT = 'clients,office,collab';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments', 'collab']});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  await call('PUT', '/api/office/settings', {company_fields: {name: 'Studio Example GmbH', street: 'Hafenweg 1', zip: '20457', city: 'Hamburg', country: 'de', tax_number: '12/345/67890', vat_id: 'DE999999999', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Example Bank'}, lang: 'en'});
  const C = await call('POST', '/api/clients', {name: 'Example Client AG', street: 'Marktstrasse 5', zip: '50667', city: 'Koeln', country: 'DE', org_id: ORG});
  const L = (await call('POST', '/api/lists', {name: 'Film project', kind: 'project', org_id: ORG})).id, L2 = (await call('POST', '/api/lists', {name: 'Other work', kind: 'project', org_id: ORG})).id;
  await call('PATCH', '/api/lists/' + L, {client_id: C.id});
  for (let i = 1; i <= 9; i++) await call('POST', '/api/lists', {name: 'Extra ' + i, kind: 'project', org_id: ORG});  // 2.435.0 (#3606): a long list gets a search
  const mk = async title => {
    const q = await call('POST', '/api/office/docs', {kind: 'offer', project_title: title, client_id: C.id});
    await call('PUT', '/api/office/docs/' + q.id + '/items', {items: [{title: 'Shoot', qty: 1, rate: 1200}]});
    const f = await call('POST', '/api/office/docs/' + q.id + '/finalize');
    check(f.locked === true, 'finalised ' + title);
    return f;
  };
  const Q1 = await mk('Film'), Q2 = await mk('Spot');
  const lidOf = async id => (await call('GET', '/api/office/docs/' + id)).list_id;

  for (const [q, mobile, who] of [[Q1, false, 'desktop'], [Q2, true, 'phone']]) {
    const w = await boot({user: 'alice', hash: 'office/offers/' + q.id, mobile}), d = w.document;
    const sel = await until(() => d.querySelector('#view #dpj-sel'));
    check(!!sel, `${who}: the editor has the project row`);
    check(sel && !sel.disabled && !sel.closest('fieldset[disabled]') && !sel.closest('.ofdfs'), `${who}: usable on a finalised quotation (outside the locked fieldset)`);
    // 2.435.0 (#3606): a button with the project's icon + name opens the project picker (no native select any more)
    check(sel?.tagName === 'BUTTON' && sel.getAttribute('aria-haspopup') === 'menu' && /No project/.test(sel.textContent), `${who}: a button "No project" ` + sel?.tagName);
    sel.click();
    const pop = await until(() => { const p = d.querySelector('#pop:not(.hidden) .menu-list'); return p && p.querySelector('[role="menuitem"]') ? p : null; });
    const heads = [...(pop?.querySelectorAll('.mgh') || [])].map(g => g.textContent);
    const items = [...(pop?.querySelectorAll('[role="menuitem"]') || [])];
    check(/No project/.test(items[0]?.textContent || '') && items[0]?.classList.contains('on'), `${who}: "No project" on top, checked`);
    check(heads[0] === 'Projects of the client' && heads[1] === 'Other projects', `${who}: the client's projects on top ` + heads.join(' | '));
    const film = items.find(b => /Film project/.test(b.textContent)), other = items.find(b => /Other work/.test(b.textContent));
    check(film && other && film.closest('.mgrp')?.querySelector('.mgh')?.textContent === 'Projects of the client' && items.indexOf(film) < items.indexOf(other), `${who}: both projects to pick, the client's first`);
    check(film?.querySelector('.lic'), `${who}: the project's icon in the picker`);
    check(!mobile || d.querySelector('#pop .tch-sh'), `${who}: a sheet with a head on the phone`);
    const sq = d.querySelector('#pop #mq-q');
    check(!!sq, `${who}: a search field from 10 entries`);
    if (sq) {
      sq.value = 'extra 3'; sq.dispatchEvent(new w.Event('input', {bubbles: true}));
      const shown = [...pop.querySelectorAll('[role="menuitem"]')].filter(b => !b.closest('[hidden]'));
      check(shown.length === 1 && /Extra 3/.test(shown[0].textContent), `${who}: the search leaves one entry ` + shown.map(b => b.textContent).join(' | '));
      sq.value = ''; sq.dispatchEvent(new w.Event('input', {bubbles: true}));
    }
    film?.click();
    check(await until(async () => (await lidOf(q.id)) === L), `${who}: picking saves the project`);
    check(await until(() => d.querySelector(`#view a[href="#l/${L}"]`)), `${who}: "Open project" links to it`);
    const box = d.querySelector('#view #dpj-new');
    check(box && !box.checked, `${who}: "Create new project" is off by default`);
    box.checked = true; box.dispatchEvent(new w.Event('change', {bubbles: true}));
    const name = await until(() => d.querySelector('#view #dpj-name'));
    check(name?.value === 'Example Client AG – ' + (who === 'desktop' ? 'Film' : 'Spot'), `${who}: the name preset "Client – title" ` + name?.value);
    name.value = name.value + ' ' + who;
    d.querySelector('#view [data-dpj="make"]')?.click();
    const nl = await until(async () => { const v = await lidOf(q.id); return v && v !== L ? v : 0; });
    check(nl, `${who}: a new project created and set`);
    const lists = (await call('GET', '/api/state')).lists || [];
    check(lists.some(l => l.id === nl && /Example Client AG – .* (desktop|phone)$/.test(l.name) && l.client_id === C.id), `${who}: the new project with name and client`);
    check(await until(() => d.querySelector('#view #dpj-sel')?.dataset.lid === String(nl) && /Example Client AG/.test(d.querySelector('#view #dpj-sel').textContent)), `${who}: the editor shows the new project`);  // 2.435.0 (#3606): the button
    w.close();
  }
  await call('POST', `/api/office/docs/${Q1.id}/project`, {list_id: L});

  // ---- the project page
  for (const [mobile, who] of [[false, 'desktop'], [true, 'phone']]) {
    const w = await boot({user: 'alice', hash: 'l/' + L, mobile}), d = w.document;
    w.eval(`povSet(listById(${L}), true); renderView();`);
    const sec = await until(() => d.querySelector('#pov-officedocs'));
    check(!!sec, `${who}: the project page shows "Quotations & invoices"`);
    const txt = sec?.textContent.replace(/\s+/g, ' ') || '';
    check(/Quotations/.test(txt) && txt.includes(Q1.number)  /* 2.380.0 (#3409): the group Quotations */ && /1,?428/.test(txt.replace(/\./g, ',')), `${who}: number and amount ` + txt.slice(0, 200));
    check(sec?.querySelector(`a[href="#office/offers/${Q1.id}"]`), `${who}: a row opens the quotation`);
    w.close();
  }
  // a member without the office module: no section
  const carl = await call('POST', '/api/users', {orgs: [{id: ORG, role: 'member'}], username: 'carl', display_name: 'Carl', password: 'password123', email: 'carl@example.com'});
  check((await call('PUT', `/api/lists/${L}/members`, {user_id: carl.id, role: 'edit'})).status < 300, 'carl a member of the project');
  const CC = await login('carl');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'clients,collab', workspace: 'org:' + ORG}, CC);
  const w = await boot({user: 'carl', hash: 'l/' + L}), d = w.document;
  w.eval(`povSet(listById(${L}), true); renderView();`);
  await sleep(1200);
  check(d.querySelector('.pov') && !d.querySelector('#pov-officedocs'), 'carl (no office): no documents on the project page');
  w.close();

  console.log(`p2168_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
