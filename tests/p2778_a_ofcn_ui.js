// 2.778.0 A (#5382) UI test, own container (start.sh), Firefox (desktop + phone width). Invented data only.
// kalmido-suite: fresh
// - the shared .ofcn rule: in every office list the name stands on top and the small detail line below it, whatever the row class
//   (AGB rows with and without a file, recurring invoices, booking archive runs / files)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2778_a', check, shots: 'P2778A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CK}, body: JSON.stringify({lang: 'en', tour: 'done', features: 'cal,comments,office,clients'})});
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // rows as the app's own renderers build them; the rin / bka rows copy their markup (the real lists need server data)
  const BUILD = `(() => {
    const ul = document.createElement('ul'); ul.id = 'p2778'; ul.className = 'office ofclist'; ul.setAttribute('role', 'list');
    ul.style.cssText = 'position:relative;z-index:9;background:#fff';
    ul.innerHTML = [
      agbRowHtml('de', 'Deutsch', {name: 'terms_example_long.pdf', date: '2026-10-01', up: null}, true),
      agbRowHtml('en', 'English', null, true),
      '<li class="rin-it" data-sid="1"><span class="ofcn"><b>Monthly retainer · Beispiel GmbH</b><small class="muted">every month</small></span><button type="button" class="btn sm">Edit</button></li>',
      '<li class="bka-run"><span class="ofcn"><b>09.11.2026 · Alice</b><small class="muted">12 bookings imported</small></span><button type="button" class="btn sm">Undo</button></li>',
      '<li class="bka-pfile"><span class="ofcn"><b>bookings-2026.csv</b><small class="muted">CSV · 4 KB</small></span><button type="button" class="btn sm">Download</button></li>',
    ].join('');
    document.body.appendChild(ul); return ul.children.length;
  })()`;
  const CHECK = `(() => [...document.querySelectorAll('#p2778 > li')].map(li => {
    const n = li.querySelector('.ofcn'), b = n.querySelector('b').getBoundingClientRect(), s = n.querySelector('small').getBoundingClientRect();
    return {cls: li.className, name: n.querySelector('b').textContent, det: n.querySelector('small').textContent, below: s.top >= b.bottom - 1, w: li.getBoundingClientRect().width, right: li.getBoundingClientRect().right};
  }))()`;
  await firefox(async ({cmd, ev, ctx, nav}) => {
    for (const W of [1440, 390]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 900}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
      await nav(B + '#calendar');
      check(await ready(ev, `typeof loadModule === 'function'`), W + ': app loaded');
      await ev(`Promise.all([loadModule('office'), loadCss('office')]).then(() => 1)`);
      check(await ready(ev, `typeof agbRowHtml === 'function'`), W + ': office terms module loaded');
      await ev(`document.getElementById('p2778')?.remove(); 1`);
      check(await ev(BUILD) === 5, W + ': rows built');
      await sleep(300);
      const rows = await ev(CHECK);
      for (const x of rows) {
        check(x.below, `${W}: ${x.cls}: detail below name (${x.name})`);
        check(x.right <= W + 1, `${W}: ${x.cls}: nothing sticks out`);
      }
      const t = rows.map(x => x.name + '|' + x.det).join('\n');
      check(/Deutsch\|terms_example_long\.pdf/.test(t), W + ': AGB with file shows language and file name');
      check(/English\|No terms and conditions yet/.test(t), W + ': AGB without file shows "No terms and conditions yet"');
    }
  });
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
