// kalmido-suite: fresh
// 2.521.0 (#4400) Firefox (real layout), own container (start.sh): the file store's list row on hover: the select box replaces the
// symbol in the symbol's own column (the symbol is hidden, the box sits exactly there, the name does not move). Invented data only.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2521_a_ui', check, shots: 'P2521A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/files/folders', {space: 'private', name: 'Papers'});
  const fd = new FormData(); fd.append('space', 'private'); fd.append('files', new Blob(['hello']), 'note.txt');
  await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd}).catch(() => {});
  await firefox(async o => {
    const {cmd, ev, ctx} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.abSpace', '"private"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await o.nav(B + '#ablage');
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('.ablist .abrow .absel')`).catch(() => false)); i++) await sleep(250);
    const rect = `(() => { const r = document.querySelector('.ablist .abrow'), R = e => e.getBoundingClientRect(), ic = r.querySelector('.abopen > svg'), bx = r.querySelector('.absel input'), nm = r.querySelector('.abname');
      return {ic: R(ic), bx: R(bx), nm: R(nm).left, icVis: getComputedStyle(ic).visibility, y: R(r).top + R(r).height / 2, x: R(r).left + 200, op: +getComputedStyle(r.querySelector('.absel')).opacity}; })()`;
    const a = JSON.parse(await ev(`JSON.stringify(${rect})`));
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(a.x), y: Math.round(a.y)}]}]}); await sleep(400);
    const b = JSON.parse(await ev(`JSON.stringify(${rect})`));
    const cx = b.ic.left + b.ic.width / 2, cy = b.ic.top + b.ic.height / 2, bcx = b.bx.left + b.bx.width / 2, bcy = b.bx.top + b.bx.height / 2;
    check(b.op === 1 && b.icVis === 'hidden', '#4400: on hover the symbol is hidden and the box shown ' + JSON.stringify({a, b}));
    check(Math.abs(cx - bcx) <= 1.5 && Math.abs(cy - bcy) <= 1.5, '#4400: the box sits centred on the symbol\'s place ' + JSON.stringify({cx, cy, bcx, bcy}));
    check(await ev(`(() => { const e = document.elementFromPoint(${cx}, ${cy}); return !!e.closest('.absel'); })()`), '#4400: the point of the symbol hits the box');
    check(Math.abs(b.nm - a.nm) < .5, '#4400: the name does not move ' + a.nm + ' / ' + b.nm);
  }, true);
  console.log(`${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(1); });
