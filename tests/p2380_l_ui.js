// 2.380.0 UI tests, leader part (#3420), own container (start.sh), Firefox. freelancer-matrix: office
// - the film pack offers "share by amount" (Producing): a new quotation with the pack takes it (switch off by default)
// - a quotation made before the pack was on (producing_on 0, producing_mode NULL): the editor shows the switch
//   "Calculate Producing" and the position marks once the pack is on; switching it on sets share by amount with the
//   pack's title and adds the line to the sums
// - an older quotation computing by quantities keeps its calculation; a quotation of an organisation the same as one of
//   a person without an organisation (this test: the person without an organisation, the API part also the organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2380_l_ui', check, shots: 'P2380L_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2380L_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const line = (d, k) => (d.totals?.lines || []).find(x => x.kind === k);

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

  // ================= API: the organisation
  await call(CA, 'PUT', '/api/office/settings', {industry_packs: ['film']});
  const film = ((await call(CA, 'GET', '/api/office/settings')).industry || []).find(x => x.code === 'film');
  await call(CA, 'PUT', '/api/office/settings', {industry_packs: []});
  check(film?.calc?.share?.label?.de === 'Producing' && film.calc.share.rate > 0 && film.calc.share.factor > 0, '#3420: the film pack offers share by amount ' + JSON.stringify(film?.calc?.share));
  const SV = (await call(CA, 'POST', '/api/office/services', {name_de: 'Dreh', name_en: 'Shoot', daily_rate: 1000, producing: 1})).id;
  const its = [{kind: 'service', service_id: SV, qty: 6}];
  const qa = await call(CA, 'POST', '/api/office/docs', {project_title: 'Vor dem Paket'});
  check(qa.producing_on === 0 && qa.producing_mode == null, '#3420: a quotation without a pack has no producing');
  await call(CA, 'PUT', `/api/office/docs/${qa.id}/items`, {items: its});
  const qb = await call(CA, 'POST', '/api/office/docs', {project_title: 'Vor dem Paket 2'});
  const qq = await call(CA, 'POST', '/api/office/docs', {project_title: 'Nach Mengen'});
  await call(CA, 'PATCH', `/api/office/docs/${qq.id}`, {producing_on: 1, prod_quotient: 3, producing_rate: 600});
  await call(CA, 'PUT', `/api/office/docs/${qq.id}/items`, {items: its});
  check((await call(CA, 'PUT', '/api/office/settings', {industry_packs: ['film'], lang: 'de'})).http === 200, 'film on');
  const qn = await call(CA, 'POST', '/api/office/docs', {project_title: 'Mit Paket'});
  check(qn.producing_mode === 'amount' && qn.producing_on === 0 && qn.share_label?.de === 'Producing', '#3420: a new quotation with the film pack: share by amount, switch off ' + JSON.stringify([qn.producing_mode, qn.producing_on]));
  const ja = await call(CA, 'PATCH', `/api/office/docs/${qa.id}`, {producing_on: 1});
  const pl = line(ja, 'producing');
  check(ja.producing_mode === 'amount' && ja.share_label?.de === 'Producing' && pl && pl.total > 0 && ja.totals.net === 6000 + pl.total,
    '#3420: switched on in the older quotation: share by amount with the pack title, the line in the sums ' + JSON.stringify([ja.producing_mode, pl, ja.totals?.net]));
  // review: a quotient sent along (valid for the old calculation, 3) does not become a share of 300 %
  const jb = await call(CA, 'PATCH', `/api/office/docs/${qb.id}`, {producing_on: 1, prod_quotient: 3});
  check(jb.producing_mode === 'amount' && jb.prod_quotient === film.calc.share.factor, '#3420: switched on with a quotient: the pack factor ' + JSON.stringify([jb.producing_mode, jb.prod_quotient]));
  const jq = await call(CA, 'PUT', `/api/office/docs/${qq.id}/items`, {items: its});
  check(jq.producing_mode == null && line(jq, 'producing')?.qty === 2, '#3420: a quotation computing by quantities keeps its calculation (6 / 3 = 2 days)');

  // ================= the person without an organisation: API + editor
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: FEAT});
  await call(CF, 'PUT', '/api/office/settings', {company: {name: 'Beispiel Film'}, lang: 'de'});
  const SVF = (await call(CF, 'POST', '/api/office/services', {name_de: 'Schnitt', name_en: 'Edit', daily_rate: 800, producing: 1})).id;
  const qf = await call(CF, 'POST', '/api/office/docs', {project_title: 'Alt ohne Paket'});
  await call(CF, 'PUT', `/api/office/docs/${qf.id}/items`, {items: [{kind: 'service', service_id: SVF, qty: 5}]});
  check(qf.producing_on === 0 && qf.producing_mode == null, 'freelancer: the quotation starts without producing');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const open = async (nav, id) => { await nav(B + 'static/icon.svg'); await nav(B + `#office/offers/${id}`); };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    await open(nav, qf.id);
    check(await ready(ev, `document.querySelectorAll('.ofdeditor .ofdits .ofdit').length >= 1`, 80), 'the quotation editor');
    check(await ev(`!document.querySelector('#ofd-producing_on') && !document.querySelector('.ofdeditor [data-k="producing"]')`), '#3420: without the pack no producing switch');
    check((await call(CF, 'PUT', '/api/office/settings', {industry_packs: ['film']})).http === 200, 'freelancer: film on in the own office');
    await open(nav, qf.id);
    check(await ready(ev, `!!document.querySelector('#ofd-producing_on')`, 80) && await ev(`!document.querySelector('#ofd-producing_on').checked && !!document.querySelector('.ofdeditor [data-k="producing"]')`),
      '#3420: with the pack on the older quotation shows the switch (off) and the position marks');
    await ev(`(() => { document.getElementById('ofd-producing_on').click(); return 1; })()`);
    const autos = `[...document.querySelectorAll('.ofdautos .ofdauto')].map(x => x.textContent).join(' | ')`;
    check(await ready(ev, `/Producing/.test(${autos}) && /4\\.000,00 €/.test(${autos}) && !!document.querySelector('#ofd-prod_quotient')`, 60), '#3420: switched on: the Producing line by amount ' + await ev(autos));
    await shot('p2380-l-producing.png');
  });
  const sf = await call(CF, 'GET', `/api/office/docs/${qf.id}`);
  check(sf.producing_on === 1 && sf.producing_mode === 'amount' && line(sf, 'producing')?.total > 0, 'freelancer: saved on the server ' + JSON.stringify([sf.producing_on, sf.producing_mode]));
  check((await call(CA, 'GET', `/api/office/docs/${qf.id}`)).http >= 403, 'freelancer: the organisation admin does not see the quotation');
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
