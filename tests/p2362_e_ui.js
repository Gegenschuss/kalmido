// 2.36.2 UI tests, part E: the foundation of Office & finance (#1021) and #1146 (PDF button), own container (start.sh). jsdom:
// - settings: the company as single fields (street ... managing directors), the free lines folded away as the fallback,
//   "Quotation number: when created / when finalised"; saving stores the fields on the server; the access log loads
// - the editor: "Finalise" + the labelled PDF button (aria-label), period of service fields; Finalise asks, then the
//   document is locked: banner with "Duplicate", every field disabled, no add / move buttons, the server answers locked;
//   the history (admin) lists the entries; the list row shows the lock
// - the client dialog has the folded "Billing details"
// Firefox 390 x 844 touch: the finalised editor and the company fields on a phone -- tap targets >= 24 px, the PDF button
// shows its label and is >= 44 px high, no horizontal overflow, screenshots (P2362E_SHOTS)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2362_e_ui', check, shots: 'P2362E_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status, status: typeof j.status === 'string' ? j.status : r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,office,clients';
const fire = (w, el, type) => el.dispatchEvent(new w.Event(type, {bubbles: true}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const st = await call('GET', '/api/office/settings');
  check(st.http === 200 && st.role === 'admin' && st.company_fields, 'office settings with company fields, alice is the organisation admin ' + st.http);
  await call('PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH', lines: ['Hafenstraße 12', '20457 Hamburg']}, lang: 'de'});
  const S1 = (await call('POST', '/api/office/services', {name_de: 'Schnitt', name_en: 'Editing', category: 'Video', daily_rate: 1000})).id;
  const doc = await call('POST', '/api/office/docs', {project_title: 'Imagefilm', items: [{service_id: S1, qty: 2}]});
  check(doc.http === 201 && doc.number, 'a quotation ' + doc.http);

  // ================= jsdom: settings with the company fields
  let w = await boot({hash: 'office/settings'}); let d = w.document;
  await until(() => d.querySelector('#ofc-set #osc-street'), 60);
  check(!!d.querySelector('#osc-street') && !!d.querySelector('#osc-iban') && !!d.querySelector('#osc-vat_id') && !!d.querySelector('#osc-managing_directors'), 'settings: the company as single fields');
  check(!!d.querySelector('details.ofcfree #os-lines') && !d.querySelector('details.ofcfree').open, 'settings: the free lines are folded away as the fallback');
  check(d.querySelector('#os-numat')?.value === 'create' && d.querySelector('#os-numat').options.length === 2, 'settings: quotation number when created (default) / when finalised');
  const set = (id, v) => { const el = d.querySelector(id); el.value = v; fire(w, el, 'input'); };
  set('#osc-street', 'Hafenstraße 12'); set('#osc-zip', '20457'); set('#osc-city', 'Hamburg'); set('#osc-iban', 'DE02 1203 0000 0000 2020 51'); set('#osc-managing_directors', 'Jana Muster');
  d.querySelector('#ofc-set').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  const cf = await until(async () => { const j = await call('GET', '/api/office/settings'); return j.company_fields?.iban === 'DE02120300000000202051' && j.company_fields; }, 60);
  check(cf && cf.street === 'Hafenstraße 12' && cf.city === 'Hamburg' && cf.managing_directors === 'Jana Muster', 'settings: Save stores the company fields ' + JSON.stringify(cf));
  await until(() => d.querySelector('[data-ofc="log"]'), 40);
  d.querySelector('[data-ofc="log"]')?.click();
  await until(() => d.querySelector('#ofc-set .ofdlog li'), 60);
  check(/Company/.test(d.querySelector('#ofc-set .ofdlog')?.textContent || ''), 'settings: the access log lists the company change: ' + (d.querySelector('#ofc-set .ofdlog')?.textContent || '').slice(0, 160));
  w.close();

  // ================= jsdom: the editor, finalising
  w = await boot({hash: 'office/offers/' + doc.id}); d = w.document;
  await until(() => d.querySelector('.ofdeditor .ofdits .ofdit'), 60);
  const pdf = d.querySelector('a[data-ofd="pdf"]');
  check(pdf && pdf.getAttribute('aria-label') === 'Download PDF' && /PDF/.test(pdf.textContent) && pdf.getAttribute('href') === `/api/office/docs/${doc.id}/pdf`, '#1146: the PDF button has a label and an aria-label');
  check(!!d.querySelector('[data-ofd="finalize"]') && !!d.querySelector('#ofd-service_from') && !!d.querySelector('#ofd-service_to') && !d.querySelector('input[type="date"]'), 'editor: Finalise, period of service (date pickers, no native date input)');
  check(!d.querySelector('fieldset.ofdfs').disabled && !d.querySelector('.ofdlocked'), 'editor: open before finalising');
  d.querySelector('[data-ofd="finalize"]').click();
  await until(() => d.querySelector('[data-cd="yes"]'), 40);
  check(/Finalise this document/.test(d.querySelector('.modal')?.textContent || ''), 'Finalise asks first');
  const yes = d.querySelector('[data-cd="yes"]'); const fm = yes.closest('form');
  if (fm) fm.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); else yes.click();
  const srv = await until(async () => { const j = await call('GET', `/api/office/docs/${doc.id}`); return j.locked && j; }, 60);
  check(srv && srv.locked && srv.can_edit === false, 'the server has the document finalised');
  await until(() => d.querySelector('.ofdlocked'), 60);
  check(!!d.querySelector('.ofdlocked [data-ofd="dup"]') && /Finalised on/.test(d.querySelector('.ofdlocked')?.textContent || ''), 'editor: the banner says finalised and offers Duplicate');
  check(d.querySelector('fieldset.ofdfs')?.disabled === true && !d.querySelector('[data-ofd="finalize"]'), 'editor: every field disabled, no Finalise button any more');
  check(!!d.querySelector('#ofd-status') && !d.querySelector('#ofd-status').closest('fieldset'), 'editor: the status select stays usable');
  const det = d.querySelector('details.ofdsec[data-sec="log"]');
  check(!!det, 'editor: the admin sees the history section');
  if (det) { det.open = true; det.dispatchEvent(new w.Event('toggle')); }
  await until(() => d.querySelector('details[data-sec="log"] .ofdlog li'), 60);
  const lt = d.querySelector('details[data-sec="log"] .ofdlog')?.textContent || '';
  check(/finalised/.test(lt) && /created/.test(lt), 'history lists created and finalised: ' + lt.slice(0, 160));
  d.querySelector('[data-ofd="back"]').click();
  await until(() => d.querySelector('.ofdlist .ofdrow'), 60);
  check(!!d.querySelector('.ofdlist .ofdrow .ofdlk'), 'the list row shows the lock');
  // the client dialog has the billing details
  if (typeof w.clientModal === 'function') {
    w.clientModal(null);
    await until(() => d.querySelector('.modal details.clbill'), 20);
    check(!!d.querySelector('.modal details.clbill #clb-vat_id') && !!d.querySelector('#clb-buyer_reference') && !!d.querySelector('#clb-payment_terms_days'), 'the client dialog has the folded billing details');
  } else check(false, 'clientModal reachable');
  w.close();

  // ================= Firefox 390 touch
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, '390: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#office/offers/' + doc.id); await ready(ev, '.office .ofdlocked'); await sleep(800);
    const g = await ev(`(() => { const vis = e => { const b = e.getBoundingClientRect(); return b.width && b.height; }; const r = [...document.querySelectorAll('.ofdhead button, .ofdhead select, .ofdhead a, .ofdlocked button')].filter(vis).map(b => b.getBoundingClientRect()); const p = document.querySelector('.ofdhead .ofdpdf'), pb = p && p.getBoundingClientRect(), pt = p && p.querySelector('.ofdpdft'); return {n: r.length, small: r.filter(r => r.width < 24 || r.height < 24).length, wide: document.documentElement.scrollWidth > window.innerWidth + 1, pdfH: pb && Math.round(pb.height), pdfLabel: !!pt && getComputedStyle(pt).display !== 'none', banner: !!document.querySelector('.ofdlocked'), dis: document.querySelector('fieldset.ofdfs')?.disabled}; })()`);
    check(g && g.n >= 4 && g.small === 0 && !g.wide && g.pdfH >= 44 && g.pdfLabel && g.banner && g.dis, '390: finalised editor -- controls >= 24 px, PDF button labelled and >= 44 px, banner, no horizontal overflow ' + JSON.stringify(g));
    await shot('p2362e-390-finalised.png');
    await o.nav(B + '#office/settings'); await ready(ev, '#osc-street'); await sleep(600);
    const s = await ev(`(() => { const r = [...document.querySelectorAll('.ofcco input')].map(e => e.getBoundingClientRect()).filter(b => b.width); return {n: r.length, small: r.filter(b => b.height < 24).length, out: r.filter(b => b.right > window.innerWidth + 1).length, wide: document.documentElement.scrollWidth > window.innerWidth + 1}; })()`);
    check(s && s.n === 14 && s.small === 0 && s.out === 0 && !s.wide, '390: the company fields fit the phone ' + JSON.stringify(s));
    await ev(`(() => { document.querySelector('#osc-street').scrollIntoView({block: 'start'}); return 1; })()`); await sleep(400);
    await shot('p2362e-390-company.png');
  }, true);

  console.log(`p2362_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
