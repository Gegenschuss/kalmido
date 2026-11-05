// 2.543.0 (#4473): office list rows on a phone (Firefox, real layout, 390 x 844 touch) and on a desktop (1200 x 800 mouse).
// kalmido-suite: fresh
// freelancer-matrix: office  (a person without an organisation)
// - phone: the amount and "net" / "gross" stand side by side on the right, the status label sits at the start of the meta line
//   under the title (not under the amount); a row is not taller than title + meta line (+ its padding)
// - desktop as before: "net" / "gross, net …" under the amount, the status under it on the right, no label in the meta line
// With P2543B_SHOTS: a picture of both lists.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2543_b_rows_ff_ui', check, shots: 'P2543B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const SH = !!process.env.P2543B_SHOTS;

// the geometry of the first row of the list: row, title, meta line, amount, its "net"/"gross" note, both status labels
const MEASURE = `(() => { const row = document.querySelector('.ofdlist .ofdrow[data-id]'); if (!row) return null;
  const R = e => { if (!e) return null; const b = e.getBoundingClientRect(); return b.width && b.height ? {t: b.top, b: b.bottom, l: b.left, r: b.right, h: b.height} : null; };
  return JSON.stringify({row: R(row), title: R(row.querySelector('.ofcn > b')), meta: R(row.querySelector('.ofcn > small.muted')),
    amt: R(row.querySelector('.ofdsum > b')), note: R(row.querySelector('.ofdsum .oil_amt')), noteTxt: row.querySelector('.ofdsum .oil_amt')?.innerText,
    st: R(row.querySelector('.ofcn .ofdst')), sr: R(row.querySelector('.ofdsum .ofdsr')), stTxt: row.querySelector('.ofcn .ofdst')?.innerText,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1}); })()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const u = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(u.http === 200 || u.http === 201, 'the freelancer ' + u.http);
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  await call('GET', '/api/office/settings');
  check(!((await call('GET', '/api/state')).orgs || []).length, 'a person without an organisation');
  const CL = (await call('POST', '/api/clients', {name: 'Example Client Ltd', street: 'Main Street 5', zip: '50667', city: 'Cologne', country: 'DE'})).id;
  const q = await call('POST', '/api/office/docs', {client_id: CL, project_title: 'Image film for the spring campaign'});
  await call('PUT', `/api/office/docs/${q.id}/items`, {items: [{kind: 'service', title: 'Camera', qty: 2, unit: 'day', rate: 800}]});
  const inv = await call('POST', `/api/office/docs/${q.id}/invoice`, {});
  check(inv.http === 201, 'an invoice from the quotation ' + inv.http);
  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
  };
  // the list is there and laid out: the amount of the first row has a size
  const listUp = ev => ready(ev, `(() => { const b = document.querySelector('.ofdlist .ofdrow[data-id] .ofdsum > b'); return !!b && b.getBoundingClientRect().width > 0 && document.fonts.status === 'loaded'; })()`);

  // ================= phone
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    check(await ffLogin(o) === 200, '390: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    for (const [hash, kind, word] of [['#office/offers', 'quotation', /^net$/], ['#office/invoices', 'invoice', /^gross$/]]) {
      await nav(B + 'static/icon.svg'); await nav(B + hash);
      check(await listUp(ev), `390 ${kind}: the list`);
      const g = JSON.parse(await ev(MEASURE) || 'null');
      check(g && g.amt && g.note && Math.abs(g.amt.b - g.note.b) < 4 && g.note.l >= g.amt.r - 1, `390 ${kind}: "${word.source}" small right behind the amount in the same line ` + JSON.stringify(g));
      check(g && word.test((g.noteTxt || '').trim()), `390 ${kind}: the short note ${word} ` + g?.noteTxt);
      check(g && g.st && !g.sr && /Draft/.test(g.stTxt || ''), `390 ${kind}: the status label in the meta line, none under the amount ` + JSON.stringify(g));
      check(g && g.st && g.meta && g.title && g.st.t >= g.title.b - 1 && g.st.b <= g.meta.b + 2, `390 ${kind}: the label stands in the line under the title`);
      check(g && g.row && g.title && g.meta && g.row.h <= g.title.h + g.meta.h + 16 && g.row.h >= 44, `390 ${kind}: the row is not taller than title + meta line (${g?.row?.h} px)`);
      check(g && !g.wide, `390 ${kind}: no horizontal overflow`);
      if (SH) await shot(`p2543b-390-${kind}.png`);
    }
  }, true);

  // ================= desktop: as before
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    check(await ffLogin(o) === 200, '1200: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1200, height: 800}});
    for (const [hash, kind, word] of [['#office/offers', 'quotation', /^net$/], ['#office/invoices', 'invoice', /^gross, net /]]) {
      await nav(B + 'static/icon.svg'); await nav(B + hash);
      check(await listUp(ev), `1200 ${kind}: the list`);
      const g = JSON.parse(await ev(MEASURE) || 'null');
      check(g && g.amt && g.note && g.note.t >= g.amt.b - 1, `1200 ${kind}: the note under the amount as before ` + JSON.stringify(g));
      check(g && word.test((g.noteTxt || '').trim()), `1200 ${kind}: the full note ${word} ` + g?.noteTxt);
      check(g && !g.st && g.sr && g.sr.t >= g.note.b - 1, `1200 ${kind}: the status under the amount, no label in the meta line ` + JSON.stringify(g));
      if (SH) await shot(`p2543b-1200-${kind}.png`);
    }
  }, false);

  console.log(`p2543_b_rows_ff_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
