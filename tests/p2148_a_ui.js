// 2.148.0 UI tests, part A (#2471, office: locking accounting periods + the export for the tax auditor), own container
// (start.sh), Firefox at phone width. A person without organisation (personal office, its own admin). freelancer-matrix: office
// - the bookkeeping shows the section "Lock periods (GoBD)" with the twelve months of the year
// - "Lock…" opens a dialog that asks to type the month: without it nothing is locked (the reason in the dialog), with it
//   the month is locked and shows its lock; nothing is left to lock, so the button is gone
// - "Export for the tax auditor" opens its dialog with the period
// - nothing of the section sticks out at the side on a phone
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2148_a_ui', check, shots: 'P2148A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2148A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const TODAY = TC.today();
const prev = (() => { const y = +TODAY.slice(0, 4), m = +TODAY.slice(5, 7); return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, '0')}`; })();
const LAB = `${prev.slice(5, 7)}/${prev.slice(0, 4)}`;
const SAME_YEAR = prev.slice(0, 4) === TODAY.slice(0, 4);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  // the person without organisation (tests/freelancer_fixture.py does the same in Python)
  const fu = await call(CA, 'POST', '/api/users', {username: 'erin', display_name: 'Erin', password: 'password123', email: 'erin@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CE = await login('erin');
  await call(CE, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CE, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'erin is in no organisation');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const clk = sel => `(() => { const x = document.querySelector('${sel}'); if (!x) return 0; x.click(); return 1; })()`;
  const per = cond => `fetch('/api/office/periods', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => ${cond})`;
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('#pl-sec, #pl-sec *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1 && e.getBoundingClientRect().left >= -1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});  // a phone
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'erin');
    await nav(B + '#office/books');
    check(await ready(ev, `document.querySelectorAll('#pl-sec .plmonths li').length === 12`, 100), 'the bookkeeping shows the section with 12 months '
      + await ev(`JSON.stringify({hash: location.hash, bar: !!document.querySelector('.bk-bar'), sec: (document.querySelector('#pl-sec')?.outerHTML || '').slice(0, 300), pl: typeof PL === 'object' ? PL.data : 'no PL', admin: typeof ofcAdmin === 'function' ? ofcAdmin() : 'no fn'})`).catch(e => String(e)));
    check(await ev(`document.querySelectorAll('#pl-sec .plm.on').length === 0 && /Nothing is locked yet/.test(document.querySelector('#pl-sec').textContent)`), 'nothing locked yet');
    check(await ev(`document.querySelector('#pl-to')?.value === '${prev}'`), `"Lock up to" offers the month before (${prev})`);
    await ev(`(() => { document.querySelector('#pl-sec').scrollIntoView({block: 'start'}); return 1; })()`); await sleep(300);
    check(await ev(noSide), 'phone: nothing of the section sticks out at the side');
    await shot('p2148-a-section.png');
    // the dialog asks to type the month
    await ev(clk('#pl-sec [data-pl="lock"]'));
    check(await ready(ev, `!!document.querySelector('.modal #pl-confirm')`, 40), 'the lock dialog opens with the field to type the month');
    check(await ev(`new RegExp('${LAB.replace('/', '\\/')}').test(document.querySelector('.modal').textContent) && /cannot be undone/.test(document.querySelector('.modal').textContent)`),
      'the dialog names the month and that there is no way back');
    await ev(clk('.modal [data-m="ok"]'));
    check(await ready(ev, `/confirm/.test(document.querySelector('.modal .aerr')?.textContent || '')`, 20), 'without typing: the reason in the dialog');
    check(await ready(ev, per('j.through === null')), 'without typing: nothing locked');
    await shot('p2148-a-dialog.png');
    await ev(`(() => { const i = document.querySelector('.modal #pl-confirm'); i.value = '${LAB}'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await ev(clk('.modal [data-m="ok"]'));
    check(await ready(ev, per(`j.through === '${prev}'`), 40), 'typed: the month is locked');
    check(await ready(ev, `!document.querySelector('.modal #pl-confirm')`, 20), 'the dialog closes');
    if (SAME_YEAR) check(await ready(ev, `document.querySelectorAll('#pl-sec .plm.on').length === ${+prev.slice(5, 7)} && !!document.querySelector('#pl-sec .plm.on svg, #pl-sec .plm.on .ic, #pl-sec .plm.on i')`, 40),
      'the locked months show their lock ' + await ev(`document.querySelectorAll('#pl-sec .plm.on').length`));
    check(await ready(ev, `new RegExp('Locked up to and including ${LAB.replace('/', '\\/')}').test(document.querySelector('#pl-sec')?.textContent || '')`, 40), 'the section says up to which month');
    check(await ev(`!document.querySelector('#pl-sec [data-pl="lock"]')`), 'nothing left to lock: no lock button');
    await shot('p2148-a-locked.png');
    // the auditor's export dialog
    await ev(clk('#pl-sec [data-pl="export"]'));
    check(await ready(ev, `!!document.querySelector('.modal #pl-from') && !!document.querySelector('.modal #pl-tot')`, 40), 'the export dialog opens with the period');
    check(await ev(noSide), 'phone: still nothing sticks out');
    await shot('p2148-a-export.png');
    await ev(clk('.modal [data-m="close"]'));
  }, false);

  console.log(`p2148_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
