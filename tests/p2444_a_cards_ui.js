// kalmido-suite: fresh
// 2.444.0 (#3447) UI test: credit card statements in the office, own container (start.sh, mode workspaces), Firefox. An invented
// statement only. tenant-matrix: office
// - Money > Credit cards: the card, its statement, the positions read, "Confirm positions"; a suggestion is shown, nothing matched
//   until the press; "Private" shows what the holder pays back; on a phone the same sheet without a sideways scroll
// - a member who holds a card sees the point in the menu and only that card
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2444_a_cards_ui', check, shots: 'P2444_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const pdf = lines => {  // a PDF with a text layer, hand-written
  const stream = `BT /F1 10 Tf 12 TL 40 760 Td\n${lines.map(x => `(${x}) Tj T*`).join('\n')}\nET`;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('')}trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return out;
};
const upload = async (ck, url, field, name, text, extra = {}) => { const fd = new FormData(); fd.append(field, new Blob([text], {type: 'application/pdf'}), name); for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${org.id}`});
  const bob = (await call(CB, 'GET', '/api/state')).me;
  const card = await call(CA, 'POST', '/api/office/cards', {holder_id: bob.id, last4: '4711'});
  await call(CA, 'POST', '/api/office/cards', {holder_name: 'Fremde Person', last4: '9999'});
  const st = await upload(CA, `/api/office/cards/${card.id}/statements`, 'file', 'abrechnung.pdf', pdf(['Abrechnung vom 15.01.2025', 'Karte 5232 12XX XXXX 4711', '03.01. 04.01. Cafe Beispiel Berlin 12,50-', '05.01. 05.01. Cloud Beispiel Inc USD 20,00 18,40-', 'Auslandseinsatzentgelt 0,32-', 'Neuer Saldo 31,22-']));
  check(st.http === 201 && st.read, 'the statement read ' + st.http);
  const doc = await upload(CA, '/api/docs', 'files', 'cafe-beispiel.pdf', pdf(['Rechnung Cafe']), {ws: `org:${org.id}`});
  await sleep(1500);
  await call(CA, 'PATCH', `/api/docs/${doc.ids[0]}`, {amount: '12.50', date: '2025-01-03'});

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.ok)`);
  const click = sel => `(() => { const e = ${sel}; if (!e) return 0; e.click(); return 1; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/cards');
    check(await ready(ev, `document.querySelectorAll('.bnkrow .ccopen').length === 2`, 100), 'the two cards are listed');
    await shot('p2444-cards.png');
    await ev(click(`document.querySelector('[data-cc="card"]')`));
    check(await ready(ev, `!!document.querySelector('[data-cc="stmt"]')`), 'the card lists its statement');
    await ev(click(`document.querySelector('[data-cc="stmt"]')`));
    check(await ready(ev, `document.querySelectorAll('.ccl .bnkrow').length === 3 && !!document.querySelector('[data-cc="confirm"]')`), 'three positions, waiting for the confirmation');
    await ev(click(`document.querySelector('[data-cc="confirm"]')`));
    check(await ready(ev, `!!document.querySelector('.ccsug [data-cc="match"]')`), 'confirmed: the receipt is suggested');
    check(await ev(`!document.querySelector('.ccl .bnkm')`), 'nothing matched before the press');
    await shot('p2444-sheet.png');
    await ev(click(`document.querySelector('.ccsug [data-cc="match"]')`));
    check(await ready(ev, `!!document.querySelector('.ccl .bnkm')`), 'matched after the press');
    await ev(click(`document.querySelector('[data-cc="mark"][data-v="private"]')`));
    check(await ready(ev, `/Holder pays back/.test(document.querySelector('.ccfacts')?.textContent || '')`), 'the private sum shows');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 800}});
    await sleep(500);
    check(await ev(`document.documentElement.scrollWidth <= window.innerWidth + 1`), 'no sideways scroll on a phone ' + await ev(`document.documentElement.scrollWidth`));
    await shot('p2444-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.ok)`);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    await signIn(ev, 'bob');
    await nav(B + '#office/cards');
    check(await ready(ev, `document.querySelectorAll('.bnkrow .ccopen').length === 1`, 100), 'the holder sees their own card only');
    check(await ready(ev, `!!document.querySelector('[href="#office/cards"], [data-go="office/cards"]') || OFM_ITEMS.find(i => i.key === 'cards').adm === 0`), 'the menu point for the holder');
    check(await ev(`!document.querySelector('[data-cc="add"]')`), 'a holder adds no cards');
    await shot('p2444-holder.png');
  });
  console.log(`p2444_a_cards_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
