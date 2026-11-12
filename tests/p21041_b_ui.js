// kalmido-suite: fresh
// 2.1041.0 UI tests, part B (#5814 #5816 #5817): the quotation editor. Own container (start.sh), Firefox (1440 px, a mouse).
// Invented names and figures only. freelancer-matrix: office (a person without organisation, the personal office)
// - a position is made optional with its "Kind of position" field: the row carries the tag "Optional", its amount in brackets,
//   and the net total of the editor drops by its amount (the sum the person reads)
// - "Subtotal under every section" (ticked with the mouse): a subtotal row under each heading's positions with the section's
//   amount; the net total stays as it was
// - "Print as a flat price" (ticked with the mouse): the hint "The client sees only the total" shows, the editor still shows
//   every unit price; ticked off again the hint goes
// P21041BU_SHOTS=1: pictures of the editor.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return !!c; };
const firefox = require('./ff')({tag: 'p21041_b_ui', check, shots: 'P21041BU_SHOTS'});
const {realClick} = require('./ff');
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21041BU_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const svc = (title, qty, rate, opt = '') => ({kind: 'service', title, qty, rate, unit: 'day', tax: 'standard', opt});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,office,clients'});
  check((await call(CF, 'PUT', '/api/office/settings', {lang: 'en', currency: 'EUR'})).http === 200, 'the personal office');
  const Q = await call(CF, 'POST', '/api/office/docs', {project_title: 'Example film'});
  check(Q.http === 201, 'a quotation ' + Q.http);
  const its = await call(CF, 'PUT', `/api/office/docs/${Q.id}/items`, {items: [{kind: 'heading', title: 'Pre-production'}, svc('Concept', 2, 1000), svc('Mood film', 1, 400),
    {kind: 'heading', title: 'Shoot'}, svc('Camera', 3, 800)]});
  check(its.http === 200 && its.totals?.net === 4800, 'five lines, net 4.800 ' + its.totals?.net);

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    const press = async (sel, what) => { const c = await realClick({cmd, ev, ctx}, sel); check(c.ok, `${what}: pressed with the mouse (${c.on})`); return c.ok; };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const wait = async (js, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    const net = `(document.querySelector('#ofd-totals .tr-net dd')?.textContent || '')`;
    await nav(B + `#office/offers/${Q.id}`);
    check(await wait(`document.querySelectorAll('.ofdits .ofdit').length >= 5 && /4,800\\.00/.test(${net})`), 'the editor with the positions and the net total 4,800.00 ' + await ev(net).catch(() => '-'));
    // #5814: the kind of position
    const row = `[...document.querySelectorAll('.ofdits .ofdit')].find(li => li.querySelector('input[data-k="title"]')?.value === 'Mood film')`;
    check(await ev(`!!${row}?.querySelector('select[data-k="opt"]') && [...${row}.querySelector('select[data-k="opt"]').options].map(o => o.textContent).join('|') === 'Normal position|Optional position|Alternative position'`),
      '#5814: the row offers Normal / Optional / Alternative ' + await ev(`[...(${row}?.querySelector('select[data-k="opt"]')?.options || [])].map(o => o.textContent).join('|')`).catch(() => '-'));
    await ev(`(() => { const s = ${row}.querySelector('select[data-k="opt"]'); s.value = 'optional'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await wait(`/4,400\\.00/.test(${net})`), '#5814: the net total drops by its amount: 4,400.00 ' + await ev(net).catch(() => '-'));
    check(await ev(`${row}.classList.contains('ofdopt') && /Optional/.test(${row}.querySelector('.ofdopttag')?.textContent || '') && /^\\(.*400\\.00\\)$/.test(${row}.querySelector('.ofdlt')?.textContent.trim() || '')`),
      '#5814: the row says "Optional" and shows its amount in brackets ' + await ev(`${row}?.querySelector('.ofdlt')?.textContent || '-'`).catch(() => '-'));
    check(await wait(`/not included in the total/.test(document.querySelector('.ofdoptnote')?.textContent || '')`), '#5814: the note below the sums');
    if (process.env.P21041BU_SHOTS) await shot('p21041b-optional');
    // #5816: the subtotals
    await press('#ofd-subtotals', 'Subtotal under every section');
    check(await wait(`document.querySelectorAll('.ofdits .ofdsub').length === 2`), '#5816: two subtotal rows');
    const subs = await ev(`[...document.querySelectorAll('.ofdits .ofdsub')].map(x => x.textContent.replace(/\\s+/g, ' ').trim()).join(' / ')`);
    check(/Subtotal Pre-production\s*€?2,000\.00/.test(subs) && /Subtotal Shoot\s*€?2,400\.00/.test(subs), '#5816: each with its section and amount (the optional one not in it): ' + subs);
    check(await ev(`(() => { const l = [...document.querySelectorAll('.ofdits > li')]; const s = l.findIndex(x => x.classList.contains('ofdsub')); return s > 0 && l[s + 1]?.classList.contains('ofdhd'); })()`),
      '#5816: the first subtotal stands right before the next heading');
    check(/4,400\.00/.test(await ev(net)), '#5816: the net total stays 4,400.00');
    if (process.env.P21041BU_SHOTS) await shot('p21041b-subtotals');
    // #5817: the flat price
    await press('#ofd-flat_print', 'Print as a flat price');
    check(await wait(`/The client sees only the total/.test(document.querySelector('.ofdflathint')?.textContent || '')`), '#5817: the hint that the client sees only the total');
    check(await ev(`[...document.querySelectorAll('.ofdits input[data-k="rate"]')].some(x => /800/.test(x.value))`), '#5817: the editor keeps the unit prices');
    const sv = await call(await login('frida'), 'GET', `/api/office/docs/${Q.id}`);
    check(sv.flat_print === true && sv.subtotals === true, '#5816 / #5817: both switches saved ' + JSON.stringify([sv.flat_print, sv.subtotals]));
    await press('#ofd-flat_print', 'Print as a flat price off');
    check(await wait(`!document.querySelector('.ofdflathint')`), '#5817: off again, the hint goes');
  });

  console.log(`p21041_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
