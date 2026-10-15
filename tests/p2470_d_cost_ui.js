// 2.47.0 UI tests, part D (quotation editor), own container (start.sh, mode workspaces), Firefox (desktop + phone width):
// - #1645: the switch "Calculate producing" and the raw data choice are always in the quotation (default off), the flags of
//   a position are always there; switching producing on adds the producing line
// - #1649: the admin sees the purchase and the surplus per position plus the sum; a percent position shows its rate in %
//   and the external base instead of quantity x unit; a member sees neither purchase nor surplus; on a phone the surplus
//   stays inside its row
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2470_d_cost_ui', check, shots: 'P2470D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH'}, lang: 'en'});
  const SVE = (await call(CA, 'POST', '/api/office/services', {name_de: 'Schnitt', name_en: 'Editing', daily_rate: 500, intext: 'extern', producing: 1})).id;
  const SVI = (await call(CA, 'POST', '/api/office/services', {name_de: 'Regie', name_en: 'Direction', daily_rate: 100, intext: 'intern'})).id;
  const SVK = await call(CA, 'POST', '/api/office/services', {name_de: 'Künstlersozialkasse', name_en: 'Artists social insurance', unit: 'percent', daily_rate: 5});
  check(SVK.http === 201, '#1649: a service of unit percent ' + SVK.http);
  const offer = await call(CA, 'POST', '/api/office/docs', {project_title: 'Imagefilm', lang: 'en'});
  const put = await call(CA, 'PUT', `/api/office/docs/${offer.id}/items`, {items: [{kind: 'service', service_id: SVE, qty: 2, cost: 300}, {kind: 'service', service_id: SVI, qty: 3}, {kind: 'service', service_id: SVK.id, qty: 1}]});
  check(put.http === 200 && put.totals.net === 1350 && offer.producing_on === 0, 'the quotation: 1000 + 300 + 5 % of 1000 ' + put.totals?.net);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + `#office/offers/${offer.id}`);
    check(await ready(ev, `document.querySelectorAll('.ofdeditor .ofdits .ofdit').length >= 3`, 80), 'the quotation editor (admin)');
    // ================= #1645
    check(await ev(`!!document.querySelector('#ofd-producing_on') && !document.querySelector('#ofd-producing_on').checked && !!document.querySelector('#ofd-raw_mode') && document.querySelectorAll('.ofdeditor [data-k="producing"]').length === 3`),
      '#1645: the producing switch (off), the raw data choice and the flags are there although the default is off');
    await ev(`(() => { document.getElementById('ofd-producing_on').click(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('.ofdautos .ofdauto')].some(x => /Producing/.test(x.textContent)) && document.getElementById('ofd-producing_on').checked && !!document.querySelector('#ofd-prod_quotient')`),
      '#1645: switched on in the quotation, the producing line appears');
    // ================= #1649 admin
    const rows = `[...document.querySelectorAll('.ofdeditor .ofdits:not(.ofdautos) > .ofdit')]`;
    check(await ready(ev, `${rows}.filter(li => li.querySelector('.ofdmargin')).length === 3`), '#1649: a surplus at every position (admin)');
    check(await ev(`/400\\.00/.test(${rows}[0].querySelector('.ofdmargin').textContent) && ${rows}[0].querySelector('[data-k="cost"]').value.startsWith('300')`),
      '#1649: purchase 300 per day, surplus 1000 - 600 ' + await ev(`${rows}[0].querySelector('.ofdmargin')?.textContent`));
    check(await ev(`!!document.querySelector('.ofdtotals .ofdmsum') && /750\\.00/.test(document.querySelector('.ofdtotals .ofdmsum').textContent)`),
      '#1649: the sum of the surpluses ' + await ev(`document.querySelector('.ofdtotals .ofdmsum')?.textContent`));
    check(await ev(`(() => { const li = ${rows}[2]; return !li.querySelector('[data-k="qty"]') && li.querySelector('[data-k="rate"]').value === '5' && /%/.test(li.querySelector('.ofdnums').textContent) && /1,000\\.00/.test(li.querySelector('.ofdpctof').textContent) && /50\\.00/.test(li.querySelector('.ofdlt').textContent); })()`),
      '#1649: the percent position: 5 % of 1,000.00 external = 50.00, no quantity');
    await shot('p2470-d-admin.png');
    // phone width: the surplus stays inside its row
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(`${rows}.every(li => { const m = li.querySelector('.ofdmargin'); if (!m) return true; const a = m.getBoundingClientRect(), b = li.getBoundingClientRect(); return a.width > 0 && a.right <= b.right + 1 && a.left >= b.left - 1; })`),
      '#1649: on a phone the surplus stays inside its row');
    await shot('p2470-d-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ================= #1649 member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + `#office/offers/${offer.id}`);
    check(await ready(ev, `document.querySelectorAll('.ofdeditor .ofdits .ofdit').length >= 3`, 80), 'the quotation editor (member)');
    check(await ev(`!document.querySelector('.ofdeditor .ofdmargin') && !document.querySelector('.ofdeditor [data-k="cost"]') && !document.querySelector('.ofdtotals .ofdmsum') && !document.querySelector('.ofdtotals .ofdint')`),
      '#1649: a member sees no purchase and no surplus');
    check(await ev(`(OFD.doc.items || []).every(i => !('cost' in i) && !('margin' in i)) && !('items_margin' in OFD.doc)`), '#1649: the member\'s client has no purchase data at all');
  }, false);

  console.log(`p2470_d_cost_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
