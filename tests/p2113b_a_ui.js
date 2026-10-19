// 2.113.1 UI tests, part A (#2251, #2252), own container (start.sh, mode workspaces), Firefox (desktop + phone width):
// - no pack option: a new quotation shows no producing switch / fields / marks; an older quotation that computes producing
//   still shows its line and its switch (so it can be switched off)
// - an own pack of the data folder with "share by amount" and the film pack switched on: the settings show factor / day
//   rate; a new quotation shows the switch, the factor with the new help text, the marks per position, the share line,
//   the handling costs line; the markup switched on in the quotation adds its line, a renamed title shows at once
// - on a phone the calculation fields stay inside the width
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2113b_a_ui', check, shots: 'P2113BA_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2113BA_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

// an own pack in the data folder: the shipped film pack with another code and the option "share by amount"
const film = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'kalmido', 'office', 'packs', 'industry', 'film.json'), 'utf8'));
const own = {...film, code: 'example_share', name: {de: 'Beispiel Anteil', en: 'Example share'}, version: 1,
  calc: {share: {label: {de: 'Organisation', en: 'Organisation'}, rate: 500, factor: 0.5}}};
fs.mkdirSync(path.join(DATA, 'packs', 'industry'), {recursive: true});
fs.writeFileSync(path.join(DATA, 'packs', 'industry', 'example_share.json'), JSON.stringify(own));

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
  await call(CA, 'PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH'}, lang: 'de', producing_on: 1});
  const SV = (await call(CA, 'POST', '/api/office/services', {name_de: 'Dreh', name_en: 'Shoot', daily_rate: 1000, producing: 1})).id;
  const its = [{kind: 'service', service_id: SV, qty: 10}];
  const q0 = await call(CA, 'POST', '/api/office/docs', {project_title: 'Ohne Paket'});
  await call(CA, 'PUT', `/api/office/docs/${q0.id}/items`, {items: its});
  const qOld = await call(CA, 'POST', '/api/office/docs', {project_title: 'Alter Beleg'});
  await call(CA, 'PATCH', `/api/office/docs/${qOld.id}`, {producing_on: 1, prod_quotient: 3, producing_rate: 600});  // computes like before 2.113.1
  const old = await call(CA, 'PUT', `/api/office/docs/${qOld.id}/items`, {items: its});
  check(old.http === 200 && old.producing_mode == null && old.totals?.producing_days === 3.5, 'an older quotation: 10 days / 3 = 3,5 producing days ' + old.totals?.producing_days);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const open = async (nav, id) => { await nav(B + 'static/icon.svg'); await nav(B + `#office/offers/${id}`); };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= no pack option
    await open(nav, q0.id);
    check(await ready(ev, `document.querySelectorAll('.ofdeditor .ofdits .ofdit').length >= 1`, 80), 'the quotation editor');
    check(await ev(`!document.querySelector('#ofd-producing_on') && !document.querySelector('#ofd-prod_quotient') && !document.querySelector('.ofdeditor [data-k="producing"]') && !document.querySelector('.ofdeditor [data-k="in_handling"]') && !document.querySelector('.ofdautos .ofdauto')`),
      '#2251: without a pack option no producing switch, fields or marks');
    await open(nav, qOld.id);
    check(await ready(ev, `[...document.querySelectorAll('.ofdautos .ofdauto')].some(x => /Producing/.test(x.textContent) && /3,5 Tage/.test(x.textContent))`, 80)
      && await ev(`!!document.querySelector('#ofd-producing_on')?.checked && !!document.querySelector('#ofd-prod_quotient') && !!document.querySelector('.ofdeditor [data-k="producing"]')`),
      '#2251: an older quotation shows its producing line, switch and quotient without a pack');
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#ofc-set #os-raw-on')`, 80) && await ev(`!document.querySelector('#os-prod-on') && !document.querySelector('#os-sf')`),
      '#2251: the settings have no producing rule without a pack');

    // ================= the own pack + film on
    const st = await call(CA, 'PUT', '/api/office/settings', {industry_packs: ['example_share', 'film'], producing_on: 1});
    check(st.http === 200 && (st.settings?.industry_packs || []).join() === 'example_share,film', '#2252: own pack + film switched on ' + st.http);
    const q1 = await call(CA, 'POST', '/api/office/docs', {project_title: 'Mit Paket'});
    await call(CA, 'PUT', `/api/office/docs/${q1.id}/items`, {items: [...its, {kind: 'service', title: 'Hotel', qty: 1, rate: 400, unit: 'flat', in_handling: 0, in_markup: 0}]});
    await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#ofc-set #os-sf')`, 80) && await ev(`!!document.querySelector('#os-prod-on')?.checked && document.querySelector('#os-sf').value.replace(',', '.') === '0.50' && document.querySelector('#os-sr').value.replace('.', '').startsWith('500')`),
      '#2251: the settings show switch, factor and day rate from the pack');
    await open(nav, q1.id);
    check(await ready(ev, `document.querySelectorAll('.ofdeditor .ofdits .ofdit').length >= 2`, 80), 'the quotation editor with a pack');
    check(await ev(`!!document.querySelector('#ofd-producing_on')?.checked && !!document.querySelector('#ofd-prod_quotient') && /÷ day rate × factor/.test(document.querySelector('#ofd-prod_quotient').closest('.row')?.textContent || '')`),
      '#2251: switch and factor with the new help text');
    check(await ev(`document.querySelectorAll('.ofdeditor [data-k="producing"]').length === 2 && document.querySelectorAll('.ofdeditor [data-k="in_handling"]').length === 2 && document.querySelectorAll('.ofdeditor [data-k="in_markup"]').length === 2 && !document.querySelectorAll('.ofdeditor [data-k="in_handling"]')[1].checked`),
      '#2251/#2252: the marks per position (the hotel left out of the handling costs)');
    const autos = `[...document.querySelectorAll('.ofdautos .ofdauto')].map(x => x.textContent).join(' | ')`;
    check(await ready(ev, `/Organisation.*10\\.000,00 € \\/ 500,00 € x 0,5 = 10 Tage/.test(${autos}) && /Handlungskosten.*400,00 €/.test(${autos})`),
      '#2251/#2252: the share line and the handling costs line: ' + await ev(autos));
    await shot('p2113b-a-editor.png');
    // the markup switched on and renamed in the quotation
    await ev(`(() => { document.getElementById('ofd-markup_on').click(); return 1; })()`);
    check(await ready(ev, `/Markup.*1\\.000,00 €/.test(${autos}) && !!document.querySelector('#ofd-markup_label')`, 60), '#2252: the markup switched on: 10 % of 10.000 = 1.000 ' + await ev(autos));
    await ev(`(() => { const s = document.getElementById('ofd-markup_stacked'); s.click(); return 1; })()`);
    check(await ready(ev, `/Markup.*1\\.040,00 €/.test(${autos})`, 60), '#2252: stacked: 10 % of 10.000 + 400 = 1.040');
    await ev(`(() => { const i = document.getElementById('ofd-markup_label'); i.value = 'Production Fee'; i.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `/Production Fee.*1\\.040,00 €/.test(${autos}) && [...document.querySelectorAll('.ofdeditor [data-k="in_markup"]')].some(x => /Production Fee/.test(x.closest('label')?.textContent || ''))`, 60),
      '#2252: the renamed title on the line and at the marks');
    const q1s = await call(CA, 'GET', `/api/office/docs/${q1.id}`);
    check(q1s.markup_pct === 10 && q1s.markup_stacked === 1 && q1s.markup_label?.de === 'Production Fee', '#2252: saved on the server');
    // ================= phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(`[...document.querySelectorAll('#ofd-prod_quotient, #ofd-markup_label, #ofd-handling_pct')].every(x => x.getBoundingClientRect().right <= innerWidth + 1)`),
      'phone: the calculation fields stay inside the width');
    await shot('p2113b-a-phone.png');
  }, false);

  console.log(`p2113b_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
