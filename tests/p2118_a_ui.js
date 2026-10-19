// 2.118.0 A (#2265): the office settings offer "Counter for quotations" (per organisation / client / project) next to the
// quotation scheme, a building block button {version} beside "Initials" (quotation scheme only), the preview shows the
// result (per client an example from 01, V1); saved with the form.
// freelancer-matrix: office -- once as a person without an organisation (own private office), once as the org admin.
// Firefox: 1000 px and 390 px.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2118_a_ui', check, shots: 'P2118A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2118A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const FEAT = 'cal,comments,collab,clients,office';
const KV = 'KV-{client}-{yyyy}-{seq:02}';
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const ACK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments']}, ACK);
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
    check((await call('PUT', '/api/office/settings', {offer_scheme: KV, offer_counter: 'org'}, ck)).status === 200, tag + 'scheme + org counter saved first');
    await nav(B + '#office/settings');
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#os-counter')`).catch(() => false)); i++) await sleep(300);
    await sleep(800);
    const sel = await ev(`(() => { const s = document.querySelector('#os-counter'); if (!s) return null; const r = s.getBoundingClientRect(); return {opts: [...s.options].map(x => x.value), val: s.value, label: document.querySelector('label[for=os-counter]')?.textContent || '', w: r.width, vis: r.height > 0}; })()`);
    check(sel && sel.vis && sel.val === 'org' && sel.opts.join() === 'org,client,project', tag + 'the counter choice is there ' + JSON.stringify(sel));
    check(sel && /Counter for quotations/.test(sel.label), tag + 'its label ' + JSON.stringify(sel));
    const btns = await ev(`(() => { const q = id => [...(document.querySelector('#' + id)?.closest('.row')?.parentElement?.querySelectorAll('[data-for="' + id + '"][data-bb="{version}"]') || [])].length; return {offer: q('os-scheme'), inv: q('os-inv-scheme')}; })()`);
    check(btns.offer === 1 && btns.inv === 0, tag + 'the {version} button only at the quotation scheme ' + JSON.stringify(btns));
    // per client: the preview shows the example from 01
    await ev(`(() => { const s = document.querySelector('#os-counter'); s.value = 'client'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    let pv = ''; for (let i = 0; i < 30; i++) { pv = await ev(`document.querySelector('#os-preview')?.textContent || ''`); if (/-01\b/.test(pv)) break; await sleep(200); }
    check(/KV-\S+-\d{4}-01/.test(pv), tag + 'preview per client from 01: ' + pv);
    // the {version} button inserts at the caret
    await ev(`(() => { const i = document.querySelector('#os-scheme'); i.value = '${KV}-V'; i.focus(); i.setSelectionRange(i.value.length, i.value.length); return 1; })()`);
    await ev(`document.querySelector('[data-for="os-scheme"][data-bb="{version}"]').click()`);
    const val = await ev(`document.querySelector('#os-scheme').value`);
    check(val === KV + '-V{version}', tag + 'the button inserted {version}: ' + val);
    for (let i = 0; i < 30; i++) { pv = await ev(`document.querySelector('#os-preview')?.textContent || ''`); if (/-V1\b/.test(pv)) break; await sleep(200); }
    check(/KV-\S+-\d{4}-01-V1/.test(pv), tag + 'preview with V1: ' + pv);
    const over = await ev(`document.documentElement.scrollWidth > window.innerWidth + 1`);
    check(!over, tag + 'no horizontal overflow');
    if (o.shot) { await ev(`document.querySelector('#os-counter').scrollIntoView({block: 'center'})`); await sleep(300); await o.shot(`2265-${user}-${width}.png`); }
    await ev(`(() => { const f = document.querySelector('#ofc-set'); if (f.requestSubmit) f.requestSubmit(); else f.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); return 1; })()`);
    let s; for (let i = 0; i < 30; i++) { s = (await call('GET', '/api/office/settings', null, ck)).settings || {}; if (s.offer_counter === 'client') break; await sleep(300); }
    check(s.offer_counter === 'client' && s.offer_scheme === KV + '-V{version}', tag + 'saved: per client + the scheme ' + JSON.stringify({c: s.offer_counter, sc: s.offer_scheme}));
  }, width < 500);

  await run('fiona', FCK, 1000);
  await run('fiona', FCK, 390);
  await run('alice', ACK, 1000);
  await run('alice', ACK, 390);
  console.log(`p2118_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
