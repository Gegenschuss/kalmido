// 2.298.0 A1 UI tests (#3186, less text in the office), own container (start.sh, mode workspaces), Firefox at phone width
// (390 px) with screenshots (P2298A1_SHOTS). Invented company, client and figures only.
// - the office helpers (ofcRowF / ofdF / the free-lines textareas) write their help as .shint: it sits behind the (i) of the
//   label (hidden, the (i) button there); a keep line (the invoice number comes only when finalised, the test number) stays
//   visible; units ('%', the currency) stay visible next to the field
// - a field explained twice shows no visible line any more (payment terms: the (i) only)
// - the number scheme's building blocks show only while the scheme field has the focus (also reachable with Tab); a click on
//   a block keeps the focus in the field and inserts it
// - a field that saves itself confirms with the quiet tick (.svtick, "Saved" for screen readers), no toast; the toast with
//   Undo stays where it offers Undo
// - the one-way warning of the transfer keeps its sentence word for word
// freelancer-matrix: office  (alice's personal office without an organisation, then the office of her organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2298_a1_lesstext_ui', check, shots: 'P2298A1_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2298A1_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,time,workload';
const SH = !!process.env.P2298A1_SHOTS;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'de'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'de', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: FEAT, workspace: 'private'});
  await call(CA, 'PUT', '/api/office/settings', {company: {name: 'Studio Beispiel'}, lang: 'de'});
  const invP = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', lang: 'de', project_title: 'Imagefilm'});
  check(invP.http === 201, 'a draft invoice in the personal office ' + invP.http);
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  // visible = takes room on the page (a hidden .iisrc / a clipped block does not)
  const vis = sel => `(() => { const e = document.querySelector('${sel}'); if (!e) return false; const b = e.getBoundingClientRect(); return b.width > 2 && b.height > 2 && getComputedStyle(e).visibility !== 'hidden'; })()`;
  const sub = async (ev, k) => { await ev(`(() => { document.querySelector('#ofc-set [data-ostsub="${k}"]')?.click(); return 1; })()`); await sleep(300); };
  const toastSaved = `[...document.querySelectorAll('#toast, .toast')].some(t => t.offsetParent && /^\\s*Gespeichert\\s*$/.test(t.textContent))`;
  // headless Firefox without window focus fires no focus events (and matches no :focus-within): the page's own focusin /
  // focusout listeners get the event by hand, they read document.activeElement (a real focus change sets it)
  const fin = `(() => { document.activeElement?.dispatchEvent(new FocusEvent('focusin', {bubbles: true})); return 1; })()`;
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('#ofc-set *, .ofdeditor *')].filter(e => e.getClientRects().length && !e.closest('.ostsub')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    for (const [tag, ws, inv] of [['personal', 'private', invP], ['org', `org:${org.id}`, null]]) {
      const T = ` (${tag})`;
      await call(CA, 'PATCH', '/api/settings', {workspace: ws});
      if (tag === 'org') await call(CA, 'PUT', '/api/office/settings', {company: {name: 'Alpha GmbH'}, lang: 'de'});
      await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');
      check(await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub="company"]')`, 80), 'the office settings' + T);
      // ---- company: the help of the company name sits behind the (i) of its label
      await sub(ev, 'company');
      if (SH) await shot(`p2298a1-${tag}-settings-company.png`);
      // (the sections of the other office files have their own suites; here the rows of office.js)
      const OWN = ['os-name', 'os-lines', 'os-color', 'os-scheme', 'os-numat', 'os-valid', 'os-inv-scheme', 'os-paydays', 'os-skonto', 'os-rmdays', 'os-datev', 'os-portal-docs', 'os-sf', 'os-rf', 'os-einv', 'os-pack', 'osc-md_label'];
      const left = await ev(`${JSON.stringify(OWN)}.filter(id => document.getElementById(id)?.closest('.row')?.querySelector('.ofchint'))`);
      check(!left.length, 'no visible ofchint line left in the office.js rows of the settings' + T + ' ' + JSON.stringify(left));
      check(await ev(`(() => { const row = document.querySelector('#os-name')?.closest('.row'); const h = row?.querySelector(':scope > .shint'); return !!h && h.classList.contains('iisrc') && !!row.querySelector('label .ib'); })()`)
        && !await ev(vis('#os-name ~ .shint')), 'company name: the help behind the (i) of the label, not visible' + T);
      // ---- documents & numbers: the building blocks only while the scheme field has the focus
      await sub(ev, 'docs');
      if (SH) await shot(`p2298a1-${tag}-settings-docs.png`);
      check(await ev(`!!document.querySelector('#os-scheme')`) && !await ev(vis('.ofcbb')), 'number scheme: no building blocks without the focus' + T);
      check(await ev(`(() => { const row = document.querySelector('#os-inv-scheme')?.closest('.row'); const h = row?.querySelector(':scope > .shint.keep'); return !!h && !h.classList.contains('iisrc'); })()`)
        && await ev(vis('#ofc-set .row:has(#os-inv-scheme) > .shint.keep')), 'invoice numbers: the keep line (number when finalised) stays visible' + T);
      await ev(`(() => { const i = document.querySelector('#os-scheme'); i.focus(); i.setSelectionRange(i.value.length, i.value.length); return 1; })()`);
      await ev(fin);
      check(await ready(ev, vis('#ofc-set .row:has(#os-scheme) + .ofcbb')), 'number scheme: the building blocks show with the focus' + T);
      if (SH) await shot(`p2298a1-${tag}-settings-scheme-focus.png`);
      const before = await ev(`document.querySelector('#os-scheme').value`);
      // a real pointer click on a block (mousedown keeps the focus, the click inserts it)
      const bb = await ev(`(() => { const b = document.querySelector('#ofc-set .row:has(#os-scheme) + .ofcbb [data-bb="{yy}"]'); b.scrollIntoView({block: 'center'}); const r = b.getBoundingClientRect(); return [Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2)]; })()`);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: bb[0], y: bb[1]}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
      check(await ready(ev, `document.querySelector('#os-scheme').value !== ${JSON.stringify(before)} && document.querySelector('#os-scheme').value.includes('{yy}')`), 'number scheme: a click on a block inserts it' + T);
      check(await ev(`document.activeElement?.id === 'os-scheme'`) && await ev(vis('#ofc-set .row:has(#os-scheme) + .ofcbb')), 'number scheme: the focus stays in the field, the blocks stay' + T);
      // keyboard: Tab from the field reaches the first block (it shows while it has the focus)
      await ev(`(() => { document.querySelector('#os-scheme').value = ${JSON.stringify(before)}; return 1; })()`);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k', actions: [{type: 'keyDown', value: ''}, {type: 'keyUp', value: ''}]}]});
      const inBb = await ready(ev, `!!document.activeElement?.closest('.ofcbb')`); await ev(fin);
      check(inBb && await ev(vis('#ofc-set .row:has(#os-scheme) + .ofcbb')), 'number scheme: Tab reaches the building blocks' + T);
      await ev(`(() => { const a = document.activeElement; a?.blur(); a?.dispatchEvent(new FocusEvent('focusout', {bubbles: true})); return 1; })()`);
      check(await ready(ev, `!(${vis('.ofcbb')})`), 'number scheme: the blocks go again without the focus' + T);
      // ---- invoices: payment terms explained once (the (i)), the field saves itself with a quiet tick
      check(await ev(`(() => { const row = document.querySelector('#os-paydays')?.closest('.row'); return !!row && !row.querySelector(':scope > .shint:not(.iisrc)') && [...row.querySelectorAll('label .ib')].length === 1; })()`), 'payment terms: one (i), no visible line' + T);
      // Enter in a field (the form submit) saves all: no toast, the quiet mark at the field
      await ev(`(() => { const i = document.querySelector('#os-valid'); i.focus(); i.value = '21'; i.form.requestSubmit(); return 1; })()`);
      check(await ready(ev, `+((typeof OFC === 'object' ? OFC : {}).info?.settings?.offer_valid_days) === 21`), 'Enter: the settings are saved' + T);
      check(await ready(ev, `!!document.querySelector('#ofc-set .row:has(#os-valid) .ostok.on, #ofc-set .row:has(#os-valid) .svtick')`), 'Enter: the quiet mark at the field' + T);
      check(!await ev(toastSaved), 'Enter: no toast "Gespeichert"' + T);
      check(await ev(noSide), 'phone: nothing of the settings sticks out to the side' + T);
      // ---- the one-way warning keeps its sentence (personal office: transfer into an organisation)
      if (tag === 'personal') {
        await sub(ev, 'data');
        const tx = await ev(`document.querySelector('#ofc-set')?.textContent || ''`);
        check(!/organisation|Organisation/.test(tx) || !/übertragen|Übertragen/.test(tx) || /Das lässt sich nicht rückgängig machen\./.test(tx), 'transfer: the one-way sentence stays word for word' + T);
      }
      // ---- the invoice draft: the editor's help behind the (i), units visible
      if (inv) {
        await nav(B + 'static/icon.svg'); await nav(B + `#office/offers/${inv.id}`);
        check(await ready(ev, `!!document.querySelector('.ofdeditor #ofd-payment_days')`, 80), 'the invoice editor' + T);
        if (SH) await shot(`p2298a1-${tag}-invoice-top.png`);
        check(await ev(`!document.querySelector('.ofdeditor .ofchint')`), 'invoice editor: no visible ofchint line' + T);
        check(await ev(`(() => { const row = document.querySelector('#ofd-payment_days')?.closest('.row'); return !!row && !row.querySelector(':scope > .shint:not(.iisrc)') && row.querySelectorAll('label .ib').length === 1; })()`), 'invoice editor: payment terms with one (i), no visible line' + T);
        await ev(`(() => { document.querySelector('#ofd-discount_pct')?.scrollIntoView({block: 'center'}); return 1; })()`);
        await sleep(200);
        if (SH) await shot(`p2298a1-${tag}-invoice-calc.png`);
        check(!await ev(`!!document.querySelector('#ofd-discount_pct')`) || await ev(vis('.row:has(#ofd-discount_pct) > .shint.keep')), 'invoice editor: the unit % of the discount stays visible' + T);
        check(await ev(noSide), 'phone: nothing of the editor sticks out to the side' + T);
      }
    }
    // ---- a toggle that saves itself (vacation approval of the organisation): the quiet tick, no toast
    await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
    await nav(B + 'static/icon.svg'); await nav(B + '#workload');
    await ready(ev, `!!document.querySelector('#view .ab2tabs')`, 60);
    await ev(`(() => { WLV.tab = 'abs'; AB2.data = null; render(); return 1; })()`);
    if (await ready(ev, `typeof LV === 'object' && !!(LV.data && LV.data.people) && !!document.querySelector('#view details.lvbox')`, 60)) {
      await ev(`(() => { const b = document.querySelector('#view details.lvbox'); b.open = true; b.dispatchEvent(new Event('toggle')); return 1; })()`);
      await sleep(200);
      await ev(`(() => { const c = document.querySelector('#view #lv-approval'); c.click(); return 1; })()`);
      check(await ready(ev, `(() => { const t = document.querySelector('#view .svtick'); return !!t && t.previousElementSibling?.contains(document.querySelector('#lv-approval')); })()`), 'vacation approval: the quiet tick at the switch');
      check(await ev(`(() => { const t = document.querySelector('.svtick'); return !!t && /Gespeichert/.test(t.textContent) && !!t.querySelector('.sr'); })()`), 'vacation approval: "Gespeichert" for screen readers');
      check(!await ev(toastSaved), 'vacation approval: no toast "Gespeichert"');
    } else check(false, 'the vacation accounts of the organisation');
  });
  console.log(`p2298_a1_lesstext_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
