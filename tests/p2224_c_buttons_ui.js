// 2.224.0 C (#2816, #2817): two button sizes on a computer, one switch style. Own container (start.sh), Firefox with a mouse.
// A person WITHOUT an organisation with an own office (the freelancer case). Invented data only.
// - the cash book: "Book" 28 px on a computer, the Income | Expense switch is a plain .seg with the same button height as the view switch, aria-pressed works
// - the document-kind tabs (Quotes & invoices) are a plain .seg: same button height as the cash book's switch
// - the header's "New task" (a probe button with its CSS) is a normal button (32 px, no pill)
// - on a phone width the quick entry keeps its large targets
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2224_c_ui', check, shots: 'P2224C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2224C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const FEAT = 'cal,comments,office,clients,docs';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.ok)`);
  const hgt = s => `(() => { const e = document.querySelector('${s}'); return e ? Math.round(e.getBoundingClientRect().height) : -1; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // no organisation: the own office
    await nav(B + '#office/cashbook');
    check(await ready(ev, `!!document.querySelector('#cb-quick')`, 80), 'the cash book of a person without an organisation');
    check(await ev(`!!document.querySelector('.seg.cb-dir') && document.querySelectorAll('.seg.cb-dir button').length === 2`), 'Income | Expense is a plain .seg');
    const segH = await ev(hgt('.cb-bar .seg button, .seg:not(.cb-dir) button'));
    const dirH = await ev(hgt('.cb-dir button'));
    check(dirH > 0 && dirH === segH, `the kind switch has the height of the other switches (${dirH} / ${segH})`);
    check(await ev(hgt('.cb-go')) === 28, 'Book: 28 px on a computer ' + await ev(hgt('.cb-go')));
    await ev(`(() => { document.querySelector('[data-cb="dir"][data-v="out"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('[data-cb="dir"][data-v="out"]').getAttribute('aria-pressed') === 'true' && document.querySelector('[data-cb="dir"][data-v="in"]').getAttribute('aria-pressed') === 'false'`), 'aria-pressed follows the click');
    await shot('p2224-c-cashbook.png');
    // the document-kind tabs
    await nav(B + '#office/invoices');  // #3409: quotations and invoices are two areas; the invoices' area has five kinds
    check(await ready(ev, `document.querySelectorAll('.ofdkinds [data-ofd="kind"]').length === 5`, 80), 'the five document kinds of the invoices');
    check(await ev(hgt('.ofdkinds button')) === segH, `the kind tabs have the standard switch height (${await ev(hgt('.ofdkinds button'))} / ${segH})`);
    check(await ev(`document.querySelector('.ofdkinds [aria-selected="true"]') && !!document.querySelector('.ofdkinds [role="tab"]')`), 'role=tab / aria-selected stay');
    await shot('p2224-c-offers.png');
    // the header's New task
    await nav(B + '#tasks');
    // the button is only drawn on a touch tablet's calendar: measure the real CSS on a probe button inside #top
    check(await ready(ev, `!!document.querySelector('#top')`, 80), 'the header');
    check(await ev(`(() => { const t = document.querySelector('#top'), e = document.createElement('button'); e.className = 'btn pri tnew'; e.innerHTML = '<span>New task</span>'; t.appendChild(e); const r = parseFloat(getComputedStyle(e).borderTopLeftRadius), h = Math.round(e.getBoundingClientRect().height); e.remove(); return h === 32 && r < 12; })()`), 'New task: a normal 32 px button, no pill');
    await shot('p2224-c-top.png');
    // phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#office/cashbook');
    check(await ready(ev, `!!document.querySelector('#cb-quick')`, 80), 'the cash book on a phone');
    check(await ev(`['.cb-go', '[data-cb="dir"]'].every(s => document.querySelector(s).getBoundingClientRect().height >= 43)`), 'large targets in the quick entry');
    await shot('p2224-c-cashbook-phone.png');
  }, false);

  console.log(`p2224_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
