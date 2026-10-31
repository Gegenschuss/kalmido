// 2.147.0 UI tests, part A (country pack functions), own container (start.sh), Firefox:
// - #2460: Office > Settings has the area Functions (sixth area) with one switch per function of the country pack; the
//   finalising rules are shown locked; a switch saves itself ("Saved", one undo step); DATEV off = the DATEV fields leave
//   the area Data and the saved DATEV address stays on the server; VAT return figures off = no VAT return section in
//   the bookkeeping, the export for the tax advisor is there
// - #2462: changing the country pack asks first (what is hidden, finalised documents keep their state); No = the old
//   pack stays (select and server); a new personal office (no organisation) shows the country question on top, Use sets it
// tenant-matrix: office (the member sees the switches locked); freelancer-matrix: office (the person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2147_a_ui', check, shots: 'P2147A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2147A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CA, 'PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH'}, lang: 'en', datev_email: 'inbox@example.com',
    company_fields: {name: 'Studio Nordlicht GmbH', city: 'Köln'}});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  await call(CA, 'PUT', '/api/orgs/1/members', {email: 'bob@example.com', role: 'member'});
  await call(CA, 'POST', '/api/users', {username: 'erin', display_name: 'Erin', password: 'password123', email: 'erin@example.com'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:1'});
  const CE = await login('erin');
  await call(CE, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  const srv = async (ck, f, n = 40) => { for (let i = 0; i < n; i++) { const j = await call(ck, 'GET', '/api/office/settings'); if (f(j)) return j; await sleep(250); } return null; };
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const shown = `[...new Set([...document.querySelectorAll('#ofc-set [data-ostp]')].filter(p => !p.hidden).map(p => p.dataset.ostp))].join(',')`;
  const tab = k => `(() => { document.querySelector('#ofc-set [data-ostsub="${k}"]').click(); return 1; })()`;
  const flip = k => `(() => { const el = document.querySelector('#ofc-set [data-feat="${k}"]'); el.click(); return 1; })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    const as = u => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
    await as('alice');
    await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub]') && !!document.getElementById('os-name')`, 80), 'the settings page');
    check(await ev(`!document.querySelector('.ocf-choose')`), '#2462: an office with saved settings is not asked for its country');

    // ================= #2460 the area Functions
    check(await ev(`[...document.querySelectorAll('#ofc-set [data-ostsub]')].map(b => b.dataset.ostsub).filter(k => k !== 'tax').join(',')`) === 'company,docs,packs,functions,data,access', '#2460: the areas, Functions after Packs (Bank & taxes of #2789 left out: main has it, the train not yet)');
    await ev(tab('functions'));
    check(await ev(shown) === 'functions', '#2460: the area Functions shown alone');
    const feats = await ev(`[...document.querySelectorAll('#ofc-set [data-feat]')].map(x => x.dataset.feat + ':' + (x.checked ? 1 : 0) + (x.disabled ? 'd' : '')).join(',')`);
    check(feats === 'books.datev:1,docs.delivery:1,docs.einvoice:1,books.vat_return:1,books.tax_dates:1,books.export_csv:1,books.gobd:1d', '#2460: DE offers every function, finalising rules locked ' + feats);  // 2.434.0 (#3608): + docs.delivery
    check(await ev(`document.querySelector('#ofc-set [data-feat="books.datev"]').getAttribute('role') === 'switch'`), '#2460: a switch (role switch)');
    await shot('p2147-a-functions.png');
    await ev(flip('books.datev'));
    const s1 = await srv(CA, j => (j.settings?.features_off || []).includes('books.datev'));
    check(!!s1 && s1.features['books.datev'] === false, '#2460: the switch saves itself');
    check(await ready(ev, `!!document.querySelector('#ocf-books-datev')?.closest('.row')?.querySelector('.ostok.on')`), '#2460: "Saved" at the switch');
    check(await ev(`HIST.undo.length === 1`), '#2460: one undo step');
    check(s1?.settings?.datev_email === 'inbox@example.com', '#2460: the DATEV address stays saved');
    await ev(tab('data'));
    check(await ready(ev, `!document.getElementById('os-datev') && !document.querySelector('#ofc-set .dxset')`), '#2460: DATEV off -> no DATEV fields in Data');
    await ev(tab('functions'));
    await ev(flip('books.vat_return'));
    check(!!(await srv(CA, j => (j.settings?.features_off || []).includes('books.vat_return'))), '#2460: VAT return figures off saved');
    await nav(B + '#office/books');
    check(await ready(ev, `!!document.getElementById('bk-euh')`, 80), 'the bookkeeping');
    check(await ev(`!document.getElementById('bk-ustva') && !!document.getElementById('bk-exh') && !!document.querySelector('a[href*="/api/office/books/export"][href*="zip=1"]')`),
      '#2460 #2461: no VAT return section, the export for the tax advisor (CSV + ZIP) is there');
    await call(CA, 'PUT', '/api/office/settings', {features_off: []});

    // ================= #2462 the change of the country asks first
    await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub]')`, 80), 'settings again');
    await ev(tab('packs'));
    check(await ready(ev, `!!document.querySelector('#os-pack option[value="XX"]')`, 60), '#2461: the base pack is in the country choice');
    // 2.209.0 B (#2569): on a phone the country select takes the row width (was ~45 px)
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 800}}); await sleep(400);
    const pw = await ev(`(() => { const s = document.getElementById('os-pack'), r = s.closest('.row'); return [s.getBoundingClientRect().width, r.getBoundingClientRect().width]; })()`);
    check(pw[0] > 200 && pw[0] >= pw[1] * 0.6, '#2569: the country select is wide on a phone ' + pw);
    await shot('p2209-b-pack-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}}); await sleep(300);
    await ev(`(() => { const s = document.getElementById('os-pack'); s.value = 'XX'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.cdlg [data-cd="yes"]')`, 40), '#2462: a confirmation before the change');
    const txt = await ev(`document.querySelector('.cdlg [data-cd="yes"]').closest('.cdlg-f').textContent`);
    check(/Hidden/.test(txt) && /DATEV/.test(txt) && /keep their state/.test(txt), '#2462: the warning names hidden functions and finalised invoices ' + txt.slice(0, 200));
    await shot('p2147-a-switch.png');
    await ev(`(() => { document.querySelector('.cdlg [data-cd="no"]').click(); return 1; })()`);
    await sleep(800);
    check((await call(CA, 'GET', '/api/office/settings')).settings.pack === 'DE' && await ev(`document.getElementById('os-pack').value`) === 'DE', '#2462: No = DE stays');

    // ================= a member: switches locked
    await as('bob');
    await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub="functions"]')`, 80), 'member: settings');
    await ev(tab('functions'));
    check(await ev(`[...document.querySelectorAll('#ofc-set [data-feat]')].every(x => x.matches(':disabled'))`), 'member: every switch locked');

    // ================= P4: a person without an organisation is asked for the country
    await as('erin');
    await nav(B + 'static/icon.svg'); await nav(B + '#office');  // 2.224.0 B (#2816): the card sits on the page the office opens with
    check(await ready(ev, `!!document.querySelector('.ocf-choose #ocf-ch option[value="XX"]')`, 80), 'P4 #2462: the country question on top of the new personal office');
    check(await ev(`document.getElementById('ocf-ch').value`) === 'XX', 'P4 #2462: English -> the base pack suggested');
    await shot('p2147-a-choose.png');
    await ev(`(() => { document.querySelector('[data-ocf="choose"]').click(); return 1; })()`);
    const se = await srv(CE, j => j.pack_choose === false);
    check(!!se && se.settings.pack === 'XX' && se.features['books.datev'] === false, 'P4 #2462: Use sets the base pack, DATEV is not part of it');
    check(await ready(ev, `!document.querySelector('.ocf-choose')`), 'P4 #2462: the question is gone ' + JSON.stringify(await ev(`({pc: OFC.info?.pack_choose, pack: OFC.info?.settings?.pack, tab: S.route.tab, mod: S.route.mod, il: OFC.infoLoading, pw: OFC.pbWait, n: document.querySelectorAll('.ocf-choose').length})`)));
  }, false);

  console.log(`p2147_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
