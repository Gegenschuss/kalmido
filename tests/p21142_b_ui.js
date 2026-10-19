// 2.114.2 B (#2264): a number scheme with an error keeps its width, the message sits UNDER the field, and a button
// "Reset" puts the last saved valid scheme back (saved by the autosave, the message gone).
// freelancer-matrix: office -- once as a person without an organisation (own private office), once as the org admin.
// Firefox: 1000 px and 375 px.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21142_b_ui', check, shots: 'P21142B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21142B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const FEAT = 'cal,comments,collab,clients,office';
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const ACK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']}, ACK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, ACK);
  const FID = (await call('POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123'}, ACK)).id;  // no orgs = a freelancer
  check(!!FID, 'setup: fiona without an organisation');
  const FCK = await login('fiona');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, FCK);

  const run = (user, ck, width) => firefox(async o => {
    const {cmd, ev, ctx, nav} = o, tag = `${user} ${width}: `;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`) === 200, tag + 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height: 800}});
    const good = `ZZ${width}-{yyyy}-{seq:03}`;
    check((await call('PUT', '/api/office/settings', {invoice_scheme: good}, ck)).status === 200, tag + 'a valid scheme is saved first');
    await nav(B + '#office/settings');
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#os-inv-scheme')`).catch(() => false)); i++) await sleep(300);
    await sleep(800);
    const geo = () => ev(`(() => { const i = document.querySelector('#os-inv-scheme').getBoundingClientRect(), p = document.querySelector('#os-inv-scheme-pv'), pr = p.getBoundingClientRect(), b = document.querySelector('#os-inv-scheme-rs') || {hidden: true, getBoundingClientRect: () => ({top: 0, height: 0})}; return {w: Math.round(i.width), bottom: i.bottom, ptop: pr.top, err: p.classList.contains('err'), text: p.textContent, rs: !b.hidden && b.getBoundingClientRect().height > 0, rtop: b.getBoundingClientRect().top, over: document.documentElement.scrollWidth > window.innerWidth + 1, val: document.querySelector('#os-inv-scheme').value}; })()`);
    const before = await geo();
    check(before.val === good && !before.err && !before.rs, tag + 'valid: no message, no reset button ' + JSON.stringify(before));
    await ev(`(() => { const i = document.querySelector('#os-inv-scheme'); i.value = 'RE-{initial}-{seq}'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    let g; for (let i = 0; i < 30; i++) { g = await geo(); if (g.err) break; await sleep(200); }
    check(g.err && /Unknown building block/.test(g.text), tag + 'the error shows ' + g.text);
    check(g.w === before.w && g.w >= (width < 500 ? 150 : 250), tag + 'field keeps its width ' + before.w + ' -> ' + g.w);
    check(g.ptop >= g.bottom - 1 && g.rs && g.rtop >= g.ptop, tag + 'message under the field, reset button below ' + JSON.stringify(g));
    check(!g.over, tag + 'no horizontal overflow');
    // the field in view; without the reset button (an export without #2264) the shots are the old layout
    if (o.shot) { await ev(`document.querySelector('#os-inv-scheme').scrollIntoView({block: 'center'})`); await sleep(300); await o.shot(`2264-${(await ev(`!!document.querySelector('#os-inv-scheme-rs')`)) ? 'nachher' : 'vorher'}-${user}-${width}.png`); }
    await ev(`document.querySelector('#os-inv-scheme-rs').click()`);
    for (let i = 0; i < 30; i++) { g = await geo(); if (!g.err && g.val === good) break; await sleep(200); }
    check(g.val === good && !g.err && !g.rs, tag + 'reset: last saved scheme back, message gone ' + JSON.stringify(g));
    await sleep(1500);
    check((await call('GET', '/api/office/settings', null, ck)).settings?.invoice_scheme === good, tag + 'server still holds the valid scheme');
  }, width < 500);

  await run('fiona', FCK, 1000);
  await run('fiona', FCK, 375);
  await run('alice', ACK, 1000);
  await run('alice', ACK, 375);
  console.log(`p21142_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
