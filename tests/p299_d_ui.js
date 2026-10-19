// 2.99.0 UI tests, part D (office documents), own container (start.sh), Firefox on a touch screen at phone width:
// - #2025: every field of the document editor (head selects, text block selects, the position row with detail, unit and
//   VAT, the text areas) is at least 44 px high with a 16 px font, so iOS does not zoom and nothing is smaller to hit
// - #2188: the client form has the field "Name addition" under the name; the own company name in the office settings is a
//   text area of up to three lines, the extra address line follows the street
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p299_d_ui', check, shots: 'P299D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P299D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  await call(CA, 'PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH'}, lang: 'en'});
  const SV = (await call(CA, 'POST', '/api/office/services', {name_de: 'Schnitt', name_en: 'Editing', daily_rate: 500})).id;
  const offer = await call(CA, 'POST', '/api/office/docs', {project_title: 'Imagefilm', lang: 'en'});
  const put = await call(CA, 'PUT', `/api/office/docs/${offer.id}/items`, {items: [{kind: 'service', service_id: SV, qty: 2, detail: 'Two days'}, {kind: 'text', detail: 'Note'}]});
  check(put.http === 200, 'the quotation with a position and a text ' + put.http + ' ' + (put.error || ''));

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + `#office/offers/${offer.id}`);
    check(await ready(ev, `!!document.querySelector('.ofdeditor .ofdit [data-k="unit"]')`, 60), '#2025: the editor with its positions');
    check(await ev(`matchMedia('(pointer:coarse)').matches`), '#2025: the browser is a touch screen');
    await ev(`(() => { document.querySelectorAll('.ofdeditor details').forEach(x => { x.open = true; }); return 1; })()`);
    await sleep(300);
    // every visible field of the head and the editor: height and font size
    const bad = await ev(`(() => {
      const els = [...document.querySelectorAll('.ofdhead select, .ofdeditor input, .ofdeditor select, .ofdeditor textarea')]
        .filter(e => !/^(checkbox|radio|hidden|file|range|color)$/.test(e.type) && e.getClientRects().length);
      const out = els.filter(e => e.getBoundingClientRect().height < 43.5 || parseFloat(getComputedStyle(e).fontSize) < 15.9)
        .map(e => (e.id || e.dataset.k || e.dataset.f || e.className || e.tagName) + ':' + Math.round(e.getBoundingClientRect().height) + '/' + getComputedStyle(e).fontSize);
      return els.length + '|' + out.join(',');
    })()`);
    const [n, list] = String(bad).split('|');
    check(+n > 15 && !list, `#2025: all ${n} fields of the document editor are at least 44 px high with 16 px: ${list}`);
    for (const [sel, what] of [['#ofd-status', 'status'], ['#ofd-intro_pick', 'introduction text block'], ['#ofd-closing_pick', 'closing text block'], ['.ofdit [data-k="unit"]', 'unit'], ['.ofdit [data-k="tax"]', 'VAT'], ['.ofdit [data-k="detail"].ofddt', 'position detail'], ['#ofd-lang', 'language'], ['#ofd-currency', 'currency']]) {
      const h = await ev(`(() => { const e = document.querySelector('${sel.replace(/'/g, "\\'")}'); return e ? Math.round(e.getBoundingClientRect().height) + '/' + getComputedStyle(e).fontSize : 'missing'; })()`);
      check(/^(4[4-9]|[5-9]\d)\/(1[6-9]|2\d)/.test(h), `#2025: ${what} is 44 px / 16 px: ${h}`);
    }
    await shot('p299d-390-editor.png');
    // #2188: the company name is a text area (up to three lines) with the extra address line among the fields
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#os-name')`, 60), '#2188: the office settings');
    check(await ev(`document.querySelector('#os-name').tagName === 'TEXTAREA' && document.querySelector('#os-name').value === 'Studio Nordlicht GmbH'`),
      '#2188: the company name is a text area');
    check(await ev(`(() => { const rows = [...document.querySelectorAll('.ofcco .row')], at = id => rows.findIndex(r => r.querySelector('#' + id)); return at('osc-address_extra') > 0 && at('osc-address_extra') === at('osc-street') + 1; })()`),
      '#2188: the extra address line right under the street');
    // #2188: the client form has the name addition right under the name
    const nx = await ev(`(() => { if (typeof clientModal !== 'function') return 'no clientModal'; clientModal(null); const n = document.querySelector('#cl-name'), x = document.querySelector('#cl-nx');
      const r = !!(n && x && n.closest('.row').nextElementSibling === x.closest('.row')) && Math.round(x.getBoundingClientRect().height) >= 44; document.querySelector('.modal [data-m="close"]')?.click(); return String(r); })()`);
    check(nx === 'true', '#2188: the client form: the name addition under the name, 44 px: ' + nx);
  }, true);

  console.log(`p299_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
