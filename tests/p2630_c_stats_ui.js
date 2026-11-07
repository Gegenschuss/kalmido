// kalmido-suite: fresh
// 2.630.0 (#4617) Firefox, own container (start.sh): the statistics show the blocks contracts (by provider), health (per
// person) and travel (the next trip) while their modules are on; a module switched off = its block is gone. Invented data only.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2630_c_stats_ui', check, shots: 'P2630C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const FEAT = 'stats,contracts,health,travel';
(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {...await r.json().catch(() => ({})), http: r.status}; };
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const T = (await call('GET', '/api/stats')).today, D = n => { const d = new Date(T + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  check((await call('POST', '/api/life/contracts', {name: 'Strom', provider: 'Stadtwerke', cost: 60, ends: D(40), notice: 1, notice_unit: 'm'})).http === 201, 'setup: a contract');
  check((await call('POST', '/api/life/contracts', {name: 'Zeitung', cost: 120, per: 'year', ends: D(150)})).http === 201, 'setup: a contract without a provider');
  check((await call('POST', '/api/life/health', {type: 'checkup', title: 'Zahnarzt', who: 'Anna', date: D(5)})).http === 201, 'setup: a check-up');
  check((await call('POST', '/api/life/trips', {name: 'Rom', from: D(20), to: D(24), packing: ''})).http === 201, 'setup: a trip');
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const txt = sel => `(document.querySelector('${sel}')?.textContent || '')`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 1000}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#stats');
    check(await ready(ev, `!!document.querySelector('.stats .stl-contracts') && !!document.querySelector('.stats .stl-health') && !!document.querySelector('.stats .stl-travel')`),
      '#4617: the three blocks contracts, health and travel appear');
    check(await ev(`/Stadtwerke \\(1\\)/.test(${txt('.stl-contracts')}) && /No provider \\(1\\)/.test(${txt('.stl-contracts')}) && /Strom/.test(${txt('.stl-contracts')})`),
      '#4617: contracts: by provider (with "No provider") and the deadline to cancel ' + await ev(txt('.stl-contracts')));
    check(await ev(`/Anna/.test(${txt('.stl-health .stlrows')}) && /Zahnarzt/.test(${txt('.stl-health .stlrows')})`), '#4617: health: the person with the next check-up');
    check(await ev(`/Rom/.test(${txt('.stl-travel')})`), '#4617: travel: the next trip');
    check(await ev(`(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.stl-contracts, .stl-health, .stl-travel')].every(e => e.getBoundingClientRect().right <= W + 1); })()`),
      'the blocks stay inside the screen');
    if (shot) await shot('blocks');
    await ev(`fetch('/api/settings', {method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({features: 'stats,contracts,travel'})}).then(r => r.status)`);
    await nav(B + 'static/icon.svg');
    await nav(B + '#stats');
    check(await ready(ev, `!!document.querySelector('.stats .stl-contracts') && !document.querySelector('.stats .stl-health')`), '#4617: health switched off: its block is gone, contracts stay');
  }, false);
  console.log(`${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(1); });
