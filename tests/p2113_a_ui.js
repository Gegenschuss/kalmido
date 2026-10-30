// 2.113.0 UI tests, part A (office settings), own container (start.sh), Firefox:
// - #2247: the settings in five areas (Company, Documents, Packs, Data, Access) like Settings > Administration: one area
//   shown, switching without a reload, the choice remembered per device (after a reload too); opening saves nothing and
//   shows no bar "Unsaved changes"; a field saves itself when it is left ("Saved" at the field, one undo step), a wrong
//   value stays in the field with its error; no Save button; a member sees every field locked
// - #2246: an industry pack's card says Switched on / Off and switches the pack at once (the box of the calculation rules
//   follows)
// - 390 px: the strip of the areas scrolls sideways, the chosen area is scrolled into view
// tenant-matrix: office (the member); the person without an organisation: p2113_a_api_test.py (freelancer-matrix: office)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2113_a_ui', check, shots: 'P2113A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2113A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CA, 'PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH'}, lang: 'en', company_fields: {name: 'Studio Nordlicht GmbH', city: 'Köln'}, payment_days: 21});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  await call(CA, 'PUT', '/api/orgs/1/members', {email: 'bob@example.com', role: 'member'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:1'});
  const srv = async (f, n = 40) => { for (let i = 0; i < n; i++) { const j = await call(CA, 'GET', '/api/office/settings'); if (f(j)) return j; await sleep(250); } return null; };
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // which areas are shown (every part of an area), is an element on screen
  const shown = `[...new Set([...document.querySelectorAll('#ofc-set [data-ostp]')].filter(p => !p.hidden).map(p => p.dataset.ostp))].join(',')`;
  const vis = id => `(() => { const e = document.getElementById('${id}'); return !!e && !!e.getClientRects().length; })()`;
  const tab = k => `(() => { document.querySelector('#ofc-set [data-ostsub="${k}"]').click(); return 1; })()`;
  const typ = (id, v) => `(() => { const el = document.getElementById('${id}'); el.focus(); el.value = ${JSON.stringify(v)}; el.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`;
  const leave = id => `(() => { document.getElementById('${id}').dispatchEvent(new FocusEvent('focusout', {bubbles: true})); return 1; })()`;  // (a background window gets no focus events)
  const row = id => `document.getElementById('${id}')?.closest('.row')?.querySelector('.ostok')`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    const as = u => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
    await as('alice');
    await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');  // (a real reload)
    check(await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub]') && !!document.getElementById('os-name')`, 80), 'the settings page');

    // ================= #2247 the areas
    check(await ev(`[...document.querySelectorAll('#ofc-set [data-ostsub]')].map(b => b.dataset.ostsub).join(',')`) === 'company,docs,packs,functions,data,access', '#2247: the areas (2.147.0 #2460: + Functions)');  // 2.147.0 (#2460): six areas
    check(await ev(`!!document.querySelector('#ofc-set .seg.aisub[role="tablist"] [data-ostsub="company"][aria-selected="true"] svg')`), '#2247: the strip of Settings > Administration (icon, tab roles), Company first');
    check(await ev(shown) === 'company' && await ev(vis('os-name')) && !(await ev(vis('os-pack'))) && !(await ev(vis('os-paydays'))), '#2247: only the area Company is shown ' + await ev(shown));
    check(await ev(`!document.querySelector('[data-ofc="save-settings"]')`), '#2247: no Save button');
    // opening saves nothing and shows no bar
    await sleep(1500);
    check(await ev(`!document.querySelector('#ofc-set .fgbar') && !document.querySelector('#ofc-set .ostok') && HIST.undo.length === 0`), '#2247: opening: no bar, nothing saved');
    const areas = {docs: 'os-paydays', packs: 'os-pack', data: 'os-datev', access: 'os-agents-read', company: 'osc-street'};
    for (const [k, id] of Object.entries(areas)) {
      await ev(tab(k));
      check(await ev(shown) === k && await ev(vis(id)) && await ev(`document.querySelector('[data-ostsub="${k}"]').getAttribute('aria-selected') === 'true'`), `#2247: the area ${k} shows ${id} only ` + await ev(shown));
    }
    check(await ev(`!!document.getElementById('osc-street') && !!document.querySelector('#ofc-set [data-ostp="company"] a[href="/api/office/export"]')`), '#2247: the master data file in Company');
    check(await ev(`!!document.querySelector('#ofc-set [data-ostp="data"] a[href="#office/import"]') && !!document.querySelector('#ofc-set [data-ostp="data"] .dxset')`), '#2247: legacy import and DATEV in Data');
    check(await ev(`!!document.querySelector('#ofc-set [data-ostp="docs"] #os-parts-inv') && !!document.querySelector('#ofc-set [data-ostp="docs"] #os-intro-de') && !!document.querySelector('#ofc-set [data-ostp="docs"] #os-raw-on')`), '#2247: templates, default texts and calculation rules in Documents');
    check(await ev(`!!document.querySelector('#ofc-set [data-ostp="packs"] #pkc') && !!document.querySelector('#ofc-set [data-ostp="access"] [data-ofc="log"]')`), '#2247: the packs in Packs, the access log in Access');
    // remembered per device, also after a reload
    await ev(tab('packs'));
    await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');  // (a real reload)
    check(await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub]')`, 80) && await ev(shown) === 'packs', '#2247: the area is remembered after a reload ' + await ev(shown));

    // ================= #2247 a field saves itself
    await ev(tab('docs'));
    await ev(typ('os-paydays', '28'));
    check(!(await ev(`!!document.querySelector('#ofc-set .fgbar')`)), '#2247: typing shows no bar');
    await ev(leave('os-paydays'));
    const s1 = await srv(j => j.settings?.payment_days === 28);
    check(!!s1 && s1.settings.company.name === 'Studio Nordlicht GmbH' && s1.company_fields.city === 'Köln' && s1.settings.lang === 'en', '#2247: leaving the field saved it, nothing else changed');
    check(await ready(ev, `(() => { const m = ${row('os-paydays')}; return !!m && m.classList.contains('on') && /Saved/.test(m.textContent) && !!m.querySelector('[data-ost-undo]'); })()`), '#2247: "Saved" with Undo at the field');
    await shot('p2113-a-saved.png');
    // a wrong value stays in the field with the error
    await ev(typ('os-paydays', 'many'));
    await ev(leave('os-paydays'));
    check(await ready(ev, `(() => { const m = ${row('os-paydays')}; return !!m && m.classList.contains('err') && document.getElementById('os-paydays').hasAttribute('aria-invalid'); })()`), '#2247: a wrong value: the field is marked with the error');
    check(await ev(`document.getElementById('os-paydays').value === 'many'`) && (await call(CA, 'GET', '/api/office/settings')).settings.payment_days === 28, '#2247: the wrong value stays in the field, nothing saved');
    check(await ev(`(() => { const e = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented; })()`), '#2247: closing the page asks while a value could not be saved');
    await ev(typ('os-paydays', '14'));
    await ev(leave('os-paydays'));
    check(!!(await srv(j => j.settings?.payment_days === 14)) && await ready(ev, `!document.getElementById('os-paydays').hasAttribute('aria-invalid') && !${row('os-paydays')}.classList.contains('err')`), '#2247: corrected: saved, the error gone');
    // one undo step per field
    await ev(`(() => { ${row('os-paydays')}.querySelector('[data-ost-undo]').click(); return 1; })()`);
    check(!!(await srv(j => j.settings?.payment_days === 28)), '#2247: Undo at the field puts the value before back');
    check(await ready(ev, `document.getElementById('os-paydays')?.value === '28'`), '#2247: the field shows it');
    // a choice saves at once; the shown area survives the redraw
    await ev(`(() => { const s = document.getElementById('os-currency'); s.value = 'USD'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    const cs = !!(await srv(j => j.settings?.currency === 'USD'));  // 2.424.0 (#3572): the message names what failed (the save or the area)
    check(cs && await ready(ev, `${shown} === 'docs'`), '#2247: a choice saves at once, the area stays ' + JSON.stringify([cs, await ev(shown), await ev(`location.hash + ' ' + !!document.querySelector('#ofc-set')`)]));
    await call(CA, 'PUT', '/api/office/settings', {currency: 'EUR'});

    // ================= #2246 the pack card
    await ev(tab('packs'));
    check(await ready(ev, `!!document.querySelector('#pkc [data-pkc-item="industry/film"] [data-pkc-on="film"]')`, 60), '#2246: the film card has its switch');
    const card = `document.querySelector('#pkc [data-pkc-item="industry/film"]')`;
    check(await ev(`(() => { const c = ${card}, i = c.querySelector('[data-pkc-on]'); return !i.checked && i.getAttribute('role') === 'switch' && c.querySelector('.pkc-onst').textContent.trim() === 'Off'; })()`), '#2246: the card says Off');
    check(!(await ev(`!!document.querySelector('#pkc [data-pkc-item^="country/"] [data-pkc-on]')`)), '#2246: no switch on a country pack');
    await ev(`(() => { ${card}.querySelector('[data-pkc-on]').click(); return 1; })()`);
    check(!!(await srv(j => (j.settings?.industry_packs || []).includes('film'))), '#2246: the switch turns the pack on at once');
    check(await ready(ev, `(() => { const c = ${card}; return !!c && c.querySelector('[data-pkc-on]').checked && c.querySelector('.pkc-onst').textContent.trim() === 'Switched on' && document.getElementById('os-ind-film').checked; })()`), '#2246: the card says Switched on, the box of the rules follows');
    check(await ev(`${shown} === 'packs'`), '#2246: the area stays after the redraw');
    await shot('p2113-a-pack-on.png');
    await ev(`(() => { ${card}.querySelector('[data-pkc-on]').click(); return 1; })()`);
    check(!!(await srv(j => !(j.settings?.industry_packs || []).includes('film'))) && await ready(ev, `${card}.querySelector('.pkc-onst').textContent.trim() === 'Off'`), '#2246: and off again');

    // ================= 390 px: the strip scrolls sideways
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');  // (a real reload)
    await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub]')`, 80);
    await ev(tab('company')); await sleep(300);
    const st = await ev(`(() => { const s = document.querySelector('#ofc-set .ostsub'); return {sw: s.scrollWidth, cw: s.clientWidth, ox: getComputedStyle(s).overflowX, h: Math.round(s.querySelector('button').getBoundingClientRect().height), pw: document.documentElement.scrollWidth}; })()`);
    check(st.sw > st.cw && st.ox === 'auto' && st.pw <= 391, '#2247 390 px: the strip scrolls sideways, the page not ' + JSON.stringify(st));
    await ev(tab('access')); await sleep(700);
    check(await ev(`(() => { const s = document.querySelector('#ofc-set .ostsub'), b = s.querySelector('[data-ostsub="access"]').getBoundingClientRect(), r = s.getBoundingClientRect(); return s.scrollLeft > 0 && b.right <= r.right + 1; })()`), '#2247 390 px: the chosen area is scrolled into view');
    await shot('p2113-a-390.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});

    // ================= a member: every field locked, nothing saved (tenant-matrix: office)
    await as('bob');
    await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');  // (a real reload)
    check(await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub]') && !!document.getElementById('os-currency')`, 80), 'member: the settings page');
    check(await ev(`document.getElementById('os-currency').matches(':disabled') && document.getElementById('os-raw-on').matches(':disabled') && document.getElementById('os-name').disabled`), 'member: fields locked (choices and boxes too)');
    await ev(tab('packs'));
    check(await ready(ev, `!!document.querySelector('#pkc [data-pkc-on="film"]')`, 60) && await ev(`document.querySelector('#pkc [data-pkc-on="film"]').disabled`), 'member: the pack switch locked');
    await ev(`(() => { const s = document.getElementById('os-currency'); s.value = 'USD'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await sleep(800);
    check((await call(CA, 'GET', '/api/office/settings')).settings.currency === 'EUR' && await ev(`!document.querySelector('#ofc-set .ostok')`), 'member: nothing is saved');
  }, false);

  console.log(`p2113_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
