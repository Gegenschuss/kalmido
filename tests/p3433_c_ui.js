// 2.537.0 C UI test (#3433): tasks with a time budget from a quotation. Own container (start.sh). The editor of a quotation
// kalmido-suite: fresh
// shows "Create tasks" next to the project row; a click opens the preview with a tick per position (the text line is no row,
// the part is a section), the hours per row (16 for two days, none for a flat rate: typed by hand); one row unticked, a name
// for the new project, "Create tasks" -> the ticked rows are tasks with their budget, the button reads "Update budget from
// the quotation" and the preview shows them as unchanged. The phone width: the same button and preview. Invented names only.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P3433CUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const FEAT = 'clients,office,collab,fields,time';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments', 'collab']});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  await call('PUT', '/api/office/settings', {company_fields: {name: 'Studio Example GmbH', street: 'Hafenweg 1', zip: '20457', city: 'Hamburg', country: 'de', tax_number: '12/345/67890', vat_id: 'DE999999999', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Example Bank'}, lang: 'en'});
  const C = await call('POST', '/api/clients', {name: 'Example Client AG', street: 'Marktstrasse 5', zip: '50667', city: 'Koeln', country: 'DE', org_id: ORG});
  const mk = async title => {
    const q = await call('POST', '/api/office/docs', {kind: 'offer', project_title: title, client_id: C.id, items: [
      {kind: 'service', title: 'Concept', detail: 'Idea and treatment', qty: 2, unit: 'day', rate: 800},
      {kind: 'text', title: 'Prices are net'},
      {kind: 'service', title: 'Edit', qty: 6, unit: 'hour', rate: 95},
      {kind: 'service', title: 'Music licence', qty: 1, unit: 'flat', rate: 400}]});
    check(q.id && q.kind === 'offer', 'quotation ' + title);
    const p = await call('POST', `/api/office/docs/${q.id}/parts`, {title: 'Graphics'});
    await call('PUT', `/api/office/docs/${q.id}/parts/${p.part.id}/items`, {items: [{kind: 'service', title: 'Animation', qty: 1, unit: 'day', rate: 700}]});
    return q;
  };
  const Q1 = await mk('Film'), Q2 = await mk('Spot');

  for (const [q, mobile, who] of [[Q1, false, 'desktop'], [Q2, true, 'phone']]) {
    const w = await boot({user: 'alice', hash: 'office/offers/' + q.id, mobile}), d = w.document;
    const btn = await until(() => d.querySelector('#view [data-dpj="tasks"]'));
    check(btn && /Create tasks/.test(btn.textContent), `${who}: the button "Create tasks" ` + btn?.textContent);
    btn?.click();
    const md = await until(() => d.querySelector('.modal.otkdlg'));
    check(!!md, `${who}: the preview opens`);
    const rows = [...(md?.querySelectorAll('tbody tr:not(.otksec)') || [])];
    const byT = t => rows.find(r => r.textContent.includes(t));
    check(rows.length === 4 && !byT('Prices are net'), `${who}: four rows, no text line ` + rows.map(r => r.textContent.replace(/\s+/g, ' ').trim()).join(' | '));
    check(rows.every(r => r.querySelector('input[type="checkbox"][data-otk]')?.checked), `${who}: a tick per position, all ticked`);
    check([...(md?.querySelectorAll('.otksec th') || [])].map(x => x.textContent).join() === 'Graphics', `${who}: the part is a section`);
    const hv = t => byT(t)?.querySelector('[data-otkh]')?.value;
    check(hv('Concept') === '16' && hv('Edit') === '6' && hv('Music licence') === '' && hv('Animation') === '8', `${who}: the hours ${hv('Concept')} ${hv('Edit')} ${hv('Music licence')} ${hv('Animation')}`);
    check(!/800|1[.,]600|95,00|95\.00/.test(md?.querySelector('tbody')?.textContent || ''), `${who}: no prices in the rows`);
    check(/Example Client AG – /.test(md?.querySelector('#otk-name')?.value || ''), `${who}: the new project's name preset ` + md?.querySelector('#otk-name')?.value);
    byT('Edit').querySelector('[data-otk]').checked = false;
    byT('Music licence').querySelector('[data-otkh]').value = '3';
    md.querySelector('[data-m="ok"]')?.click();
    const lid = await until(async () => (await call('GET', '/api/office/docs/' + q.id)).list_id);
    check(lid, `${who}: the quotation got a project`);
    check(await until(() => !d.querySelector('.modal.otkdlg')), `${who}: the preview closes`);
    const st = await call('GET', '/api/state');
    const ts = (st.tasks || []).filter(t => t.list_id === lid);
    const fld = (st.fields || []).find(f => f.list_id === lid && f.name === 'Budget h');
    const val = t => fld ? (ts.find(x => x.title === t)?.fields || {})[fld.id] : undefined;
    check(ts.map(t => t.title).sort().join() === 'Animation,Concept,Music licence', `${who}: the ticked rows are tasks ` + ts.map(t => t.title).join());
    check(fld && +val('Concept') === 16 && +val('Music licence') === 3 && +val('Animation') === 8, `${who}: the budgets in "Budget h" ${val('Concept')} ${val('Music licence')} ${val('Animation')}`);
    const b2 = await until(() => { const b = d.querySelector('#view [data-dpj="tasks"]'); return b && /Update budget from the quotation/.test(b.textContent) ? b : null; });
    check(!!b2, `${who}: the button now reads "Update budget from the quotation"`);
    b2?.click();
    const md2 = await until(() => d.querySelector('.modal.otkdlg'));
    const sts = [...(md2?.querySelectorAll('.otkst') || [])].map(x => x.textContent);
    check(sts.filter(x => x === 'Unchanged').length === 3 && sts.filter(x => x === 'New').length === 1, `${who}: three unchanged, the unticked one new ` + sts.join());
    md2?.querySelector('[data-m="close"]')?.click();
    w.close();
  }

  console.log(`p3433_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
