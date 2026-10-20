// 2.40.0 UI tests, part E (office settings), own container (start.sh), Firefox (desktop, mouse):
// - #1378: the logo upload and the settings import of the page go through with the CSRF header (no "header missing")
// - #1371: typed but unsaved input of the settings form stays over a change of the view and back, over live events
//   (a comment from another session, ofcInfo(true), render()) while typing (focus + caret kept), beforeunload asks while
//   unsaved; a dialog with changes asks before Cancel throws them away. 2.113.0 (#2247): the settings save each field
//   when it is left (no bar "Unsaved changes", no Save / Discard)
// - #1379: producing / raw data off (new organisation): no rule fields, no flags in the service dialog, no automatic lines
//   and raw data fields in the quotation editor; the switch shows the fields at once
// - #1377: the choice of the word before the management's names in the company data
// - #1382: building block buttons insert at the caret, the preview of every scheme (plain error, counter restart), the
//   (i) buttons of the terms (settings, company data, client card), also after a redraw
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2400_e_ui', check, shots: 'P2400E_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  // 2.46.0 (#1592): no organisation from the start any more: the setup creates the one these tests use (id 1), new people join it
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const st = await call(CA, 'GET', '/api/office/settings');
  check(st.http === 200 && st.settings.producing_on === 0 && st.settings.raw_on === 0, '#1379: a new organisation starts with producing / raw data off');
  await call(CA, 'PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH'}, lang: 'en', company_fields: {name: 'Studio Nordlicht GmbH', city: 'Köln'}});
  const SV = (await call(CA, 'POST', '/api/office/services', {name_de: 'Dreh', name_en: 'Shoot', daily_rate: 1000, producing: 1, raw_fee: 1})).id;
  const offer = await call(CA, 'POST', '/api/office/docs', {project_title: 'Imagefilm'});
  await call(CA, 'PUT', `/api/office/docs/${offer.id}/items`, {items: [{kind: 'service', service_id: SV, qty: 6}]});
  const task = await call(CA, 'POST', '/api/tasks', {title: 'Drehplan abstimmen'});
  const CA2 = await login('alice');  // a second session of the same person: its comment is a live event for the page

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#ofc-set #osc-street')`, 80), 'the settings page');
    await ev(`(() => { window.__t = []; const o = toast; toast = (m, ...a) => { __t.push(String(m)); return o(m, ...a); }; return 1; })()`);

    // ================= #1378 logo + import through the page's own functions (the header comes from the helper)
    const PNG = '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360606060000000050001a5f645400000000049454e44ae426082';
    await ev(`(async () => { const b = new Uint8Array('${PNG}'.match(/../g).map(h => parseInt(h, 16))); await ofcLogoUpload(new File([b], 'logo.png', {type: 'image/png'})); return 1; })()`);
    check(await ready(ev, `!!OFC.info?.settings?.logo && __t.includes(tr('Logo saved'))`), '#1378: the logo upload of the page works ' + JSON.stringify(await ev('__t')));
    // 2.87.9 (#1940): the import first names the office it goes into (confirmed here)
    await ev(`(async () => { const t = await (await fetch('/api/office/export')).text(); ofcImport(new File([t], 'office.json', {type: 'application/json'}), false); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.itc-dlg [data-cd="yes"]')`), '#1940: the import names its target first');
    await ev(`(() => { document.querySelector('.itc-dlg [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `__t.some(x => /^Imported/.test(x))`), '#1378: the settings import of the page works ' + JSON.stringify(await ev('__t')));
    check(!(await ev(`__t.some(x => /X-Requested-With/.test(x))`)), '#1378: no "header missing"');

    // ================= #1371 unsaved input; 2.113.0 (#2247): the settings save each field themselves (no bar, no Save / Discard)
    await ready(ev, `!!document.querySelector('#ofc-set #osc-street')`);
    const typ = (id, v) => ev(`(() => { const el = document.getElementById('${id}'); el.focus(); el.value = ${JSON.stringify(v)}; el.dispatchEvent(new Event('input', {bubbles: true})); return el.value; })()`);
    const srv = async (f, n = 40) => { for (let i = 0; i < n; i++) { const j = await call(CA, 'GET', '/api/office/settings'); if (f(j)) return j; await sleep(250); } return null; };
    const leave = id => ev(`(() => { document.getElementById('${id}').dispatchEvent(new FocusEvent('focusout', {bubbles: true})); return 1; })()`);  // (a background window gets no focus events: leaving a field by hand)
    await typ('osc-street', 'Hafenstraße 12'); await leave('osc-street'); await typ('os-valid', '21');
    check(!(await ev(`!!document.querySelector('#ofc-set .fgbar')`)), '#2247: no bar "Unsaved changes" on the settings');
    check(!!(await srv(j => j.company_fields?.street === 'Hafenstraße 12')), '#2247: leaving a field saves it');
    const unload = `(() => { const e = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented; })()`;
    check(await ev(unload), '#1371: closing the page asks while the field being typed in is unsaved');
    await shot('p2400-e-unsaved.png');
    // leave the view (another module) and come back
    await ev(`(() => { location.hash = '#inbox'; return 1; })()`);
    check(await ready(ev, `!document.querySelector('#ofc-set') && S.route.mod !== 'office'`), '#1371: left the settings');
    await ev(`(() => { location.hash = '#office/settings'; return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#ofc-set #osc-street')`, 60), '#1371: back on the settings');
    check(await ev(`document.getElementById('osc-street').value === 'Hafenstraße 12' && document.getElementById('os-valid').value === '21' && !document.querySelector('#ofc-set .fgbar')`),
      '#1371: the typed values are back after the view change ' + await ev(`document.getElementById('osc-street').value + ' / ' + document.getElementById('os-valid').value`));
    await leave('os-valid');  // 2.113.0 (#2247): the restored draft saves when left
    // live events while typing in a field: a comment from another session, ofcInfo(true), render()
    await ev(`(() => { const el = document.getElementById('osc-city'); el.focus(); el.value = 'Ham'; el.setSelectionRange(3, 3); el.dispatchEvent(new Event('input', {bubbles: true})); window.__rv = 0; const o = renderView; renderView = (...a) => { __rv++; return o(...a); }; return 1; })()`);
    await call(CA2, 'POST', `/api/tasks/${task.id}/comments`, {body: 'Passt der Dienstag?'});
    const live = await ready(ev, `__rv > 0`, 40);
    await ev(`(async () => { await ofcInfo(true); render(); ofcDraw(); return 1; })()`);
    await sleep(400);
    const after = await ev(`(() => { const c = document.getElementById('osc-city'); return {city: c.value, focus: document.activeElement === c, caret: c.selectionStart, street: document.getElementById('osc-street').value, valid: document.getElementById('os-valid').value}; })()`);
    check(after.city === 'Ham' && after.focus && after.caret === 3 && after.street === 'Hafenstraße 12' && after.valid === '21',
      `#1371: live events (comment ${live ? 'arrived' : 'not seen'}, ofcInfo(true), render) keep the input, the focus and the caret ` + JSON.stringify(after));
    // leaving the field stores it; nothing is left to ask about
    await typ('osc-city', 'Hamburg');
    await leave('osc-city');
    const saved = await srv(j => j.company_fields?.city === 'Hamburg');
    check(saved && saved.company_fields.street === 'Hafenstraße 12' && saved.settings.offer_valid_days === 21, '#2247: every field stored by itself ' + JSON.stringify(saved?.company_fields || {}).slice(0, 120));
    check(await ready(ev, `!document.querySelector('#ofc-set .fgbar') && !Object.keys(FG.d['ofc-set:' + OFC.info.org_id]?.f || {}).length`) && !(await ev(unload)), '#2247: saved: no bar, no question on closing');
    // a dialog with changes asks before Cancel throws them away
    await ev(`(() => { ofcModal('services', null); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal.ofcdlg #of-name_de')`);
    await ev(`(() => { const el = document.querySelector('.modal.ofcdlg #of-name_de'); el.value = 'Ton'; el.dispatchEvent(new Event('input', {bubbles: true})); document.querySelector('.modal.ofcdlg [data-m="close"]').click(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('.modal')].some(m => /Discard changes/.test(m.textContent))`), '#1371: Cancel in a changed dialog asks first');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);

    // ================= #1379 producing / raw data off
    const hid = sel => `getComputedStyle(document.querySelector('${sel}')).display === 'none'`;
    // 2.113.1 (#2251): producing is an option of an industry pack now: without one the settings have no producing rule at all
    check(await ev(`!document.querySelector('.ofcrule[data-rule="prod"]') && ${hid('.ofcrule[data-rule="raw"]')} && !document.getElementById('os-prod-on')`), '#1379/#2251 off: no producing rule without a pack, the raw data fields are hidden');
    await ev(`(() => { const c = document.getElementById('os-raw-on'); c.click(); return 1; })()`);
    check(await ev(`!(${hid('.ofcrule[data-rule="raw"]')})`), '#1379: switching on shows its fields at once');
    await ev(`(() => { document.getElementById('os-raw-on').click(); return 1; })()`);  // 2.113.0 (#2247): off again (each click saves)
    await ev(`(() => { ofcModal('services', {...(ofcRow('services', ${SV}) || {id: ${SV}, name_de: 'Dreh'}), producing: 0, raw_fee: 0}); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal.ofcdlg #of-name_de')`);
    check(await ev(`(() => { const p = document.querySelector('.modal.ofcdlg #of-producing'); const q = document.querySelector('.modal.ofcdlg #of-raw_fee'); return !!p && !p.closest('.row').hidden && !!q && !q.closest('.row').hidden; })()`), '#1645: the service dialog always shows the producing / raw data flags');  // 2.47.0 (#1645): was hidden while off
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    await ev(`(() => { location.hash = '#office/offers/${offer.id}'; return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.ofdeditor .ofdits')`, 60), 'the quotation editor');
    // 2.47.0 (#1645): the switches of the quotation and the flags are always shown; off = no automatic line
    // 2.113.1 (#2251): the producing switch and flag only with a pack option (or a quotation computing producing already)
    check(await ev(`!!document.querySelector('#ofd-raw_mode') && !document.querySelector('#ofd-producing_on') && !document.querySelector('#ofd-prod_quotient') && !document.querySelector('.ofdautos .ofdauto') && !document.querySelector('.ofdeditor [data-k="producing"]') && !!document.querySelector('.ofdeditor [data-k="raw_fee"]')`),
      '#1645 off: no producing / raw data line, the switches and flags are there');
    await shot('p2400-e-editor-off.png');

    // ================= #1377 + #1382 on the settings page
    await ev(`(() => { location.hash = '#office/settings'; return 1; })()`);
    await ready(ev, `!!document.querySelector('#ofc-set #osc-street')`, 60);
    // 2.138.0 (#2242): 7 options now (Gesellschafter (GbR) added)
    check(await ev(`document.querySelectorAll('#osc-md_label option').length === 7 && document.getElementById('osc-md_label').value === ''`), '#1377: the word before the names, default Geschäftsführung');
    await ev(`(() => { const s = document.getElementById('osc-md_label'); s.value = 'owner_f'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);  // 2.113.0 (#2247): the choice saves itself
    let md = '';
    for (let i = 0; i < 40 && md !== 'owner_f'; i++) { md = (await call(CA, 'GET', '/api/office/settings')).company_fields?.md_label; if (md !== 'owner_f') await sleep(250); }
    check(md === 'owner_f', '#1377: the choice is saved ' + md);
    await sleep(1200);  // 2.113.0 (#2247): the live redraw after the save settles before typing on
    await ready(ev, `!document.querySelector('#ofc-set > .fgbar')`);
    // building blocks at the caret, the preview with a plain error, then a valid one
    await ev(`(() => { ost_show('docs', true); return 1; })()`);  // 2.113.0 (#2247): the schemes are in the area Documents (a hidden field takes no focus)
    await ev(`(() => { const el = document.getElementById('os-inv-scheme'); el.focus(); el.value = 'RE-'; el.setSelectionRange(3, 3); el.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await ev(`(() => { document.querySelector('[data-ofc="bb"][data-for="os-inv-scheme"][data-bb="{yyyy}"]').click(); return 1; })()`);
    check(await ev(`document.getElementById('os-inv-scheme').value === 'RE-{yyyy}' && document.activeElement.id === 'os-inv-scheme' && document.activeElement.selectionStart === 9`), '#1382: a building block goes in at the caret ' + await ev(`document.getElementById('os-inv-scheme').value + ' / ' + document.activeElement.id + ' / ' + document.activeElement.selectionStart`));
    check(await ready(ev, `/running number is missing/.test(document.getElementById('os-inv-scheme-pv').textContent)`), '#1382: the preview says in plain words what is missing ' + await ev(`document.getElementById('os-inv-scheme-pv').textContent`));
    await ev(`(() => { document.querySelector('[data-ofc="bb"][data-for="os-inv-scheme"][data-bb="{seq:03}"]').click(); return 1; })()`);
    const Y = new Date().getFullYear();
    check(await ready(ev, `document.getElementById('os-inv-scheme-pv').textContent.includes('next: RE-${Y}001') && /every year/.test(document.getElementById('os-inv-scheme-pv').textContent)`),
      '#1382: the invoice preview with the counter restart ' + await ev(`document.getElementById('os-inv-scheme-pv').textContent`));
    check(await ready(ev, `/^next: /.test(document.getElementById('os-cr-scheme-pv').textContent) && /^next: /.test(document.getElementById('os-rm-scheme-pv').textContent) && /^next: KVA-/.test(document.getElementById('os-preview').textContent)`),
      '#1382: every scheme shows its next number');
    const ii = `(() => ['os-inv-scheme', 'os-cr-scheme', 'os-einv', 'os-datev', 'osc-register_court', 'osc-vat_id', 'osc-md_label'].filter(id => !document.querySelector('label[for="' + id + '"] .ib')))()`;
    check((await ev(ii)).length === 0, '#1382: (i) at the scheme and term rows, missing: ' + JSON.stringify(await ev(ii)));
    check(await ev(`(() => { const b = document.querySelector('label[for="os-inv-scheme"] .ib'); const src = document.getElementById(b.dataset.ii); return /\\{seq:03\\}/.test(src.textContent) && /finalised/.test(src.textContent) && /RE-2026-001/.test(src.textContent); })()`), '#1382: the scheme (i) has the building blocks, examples and the invoice rule');
    await ev(`(() => { document.getElementById('os-inv-scheme').value = document.getElementById('os-inv-scheme').defaultValue; document.getElementById('os-inv-scheme').dispatchEvent(new Event('input', {bubbles: true})); document.querySelector('#ofc-set > .fgbar [data-fgb="discard"]')?.click(); document.getElementById('os-pack').focus(); return 1; })()`);
    await ev(`(async () => { await ofcInfo(true); ofcDraw(); return 1; })()`); await sleep(300);
    check((await ev(ii)).length === 0, '#1382: the (i) buttons stay after a redraw, missing: ' + JSON.stringify(await ev(ii)));
    await shot('p2400-e-schemes.png');
    // the client card
    await ev(`(() => { clientModal(null); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal.cldlg .clbill')`);
    check(await ev(`(() => { const d = document.querySelector('.modal.cldlg .clbill'); d.open = true; return ['clb-buyer_reference', 'clb-email_invoice', 'clb-payment_terms_days'].every(id => !!d.querySelector('label[for="' + id + '"] .ib')); })()`), '#1382: (i) at buyer reference, invoice e-mail and payment terms of the client card');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); FG.d = {}; return 1; })()`);
  }, false);

  console.log(`p2400_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
