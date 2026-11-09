// 2.780.0 UI test, part A (#5389 head of the document view, #5391 no "Not a folder" at a file address): own container (start.sh),
// kalmido-suite: fresh
// jsdom + Firefox (1440 px and phone 390 px). Invented data only. P2780A_NOSTART=1 = the container runs.
// - #5391: the address #ablage/<document id> opened anew draws the document view with its content, no toast "Not a folder"
// - #5389: the arrows with "n of m" stand in the middle of the head and keep their x when a document with a very long name
//   follows a short one (tolerance 1 px) and when the counter gets longer ("9 of 171" -> "10 of 171"); the title is cut with
//   an ellipsis, one line, the full name in its tooltip; phone: the arrows in a row of their own, as before
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2780_a_ui', check, shots: 'P2780A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2780A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };

function pdf(lines) {  // a one-page PDF with a text layer, written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c);
  const st = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${st.length} >>\nstream\n${st}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
async function upload(name, lines) {
  const fd = new FormData();
  fd.append('files', new Blob([pdf(lines)], {type: 'application/pdf'}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = (await r.json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 150);
  return id;
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const LONG = 'Handbuch fuer die Elternarbeit im Kindergarten Sonnenschein Musterstadt Jahrgang 2026 Fassung vom ersten September mit allen Anlagen und Formularen.pdf';
  const D1 = await upload('kurz.pdf', ['Kurz Beispiel', 'Datum 01.09.2026']);
  const D2 = await upload(LONG, ['Lang Beispiel', 'Datum 02.09.2026']);
  const D3 = await upload('mittel-beispiel.pdf', ['Mittel Beispiel', 'Datum 03.09.2026']);
  check([D1, D2, D3].every(Boolean), 'three documents uploaded');

  // ================= #5391 (jsdom): the address of a document opened anew
  // every text the one toast element (#toast, not a class) shows, recorded from the first parse on: a toast that was already
  // hidden again still counts (leader job/3681: the first version looked for .toast, which never exists, and was green without the fix)
  const rec = w => { w.__toasts = []; new w.MutationObserver(() => { const t = w.document.getElementById('toast'), x = t?.textContent.trim(); if (x && w.__toasts[w.__toasts.length - 1] !== x) w.__toasts.push(x); }).observe(w.document, {subtree: true, childList: true, characterData: true}); };
  const w = await boot({user: 'alice', hash: `ablage/${D1}`, setup: rec}), d = w.document;
  check(await until(() => d.querySelector('.dv-view .dc-body')?.dataset.id === String(D1)), '#5391: #ablage/<document> draws the document view');
  check(await until(() => d.querySelector('.dv-view #dc-h')?.textContent.trim().length > 0 && d.querySelector('.dv-view .dv-pv')), '... with its title and the preview box');
  // the old way toasted with the folder query's answer, before the document view was drawn: nothing to wait for here
  const toasts = w.__toasts.slice();
  check(!toasts.some(t => /Not a folder/i.test(t)), '... no toast "Not a folder" ' + JSON.stringify(toasts));
  check(w.location.hash.startsWith('#ablage/') || w.location.hash.startsWith('#docs/'), '... the address stays a document address ' + w.location.hash);
  // a real failure of a folder load still says its message (a folder id that does not exist)
  w.location.hash = '#ablage/99999999';
  check(await until(() => w.__toasts.length > toasts.length || /not found|denied|No access|error/i.test(d.querySelector('#view')?.textContent || '')), '... a folder that does not exist still says its message');
  w.close();

  // ================= #5389 (Firefox): the head of the document view
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#docs');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    check(await wait(`document.querySelectorAll('.dc-card').length === 3`), 'Firefox: three cards');
    const HEAD = `(() => { const q = s => document.querySelector('.dv-view ' + s), r = e => e.getBoundingClientRect(), h = r(q('.dv-head')), n = r(q('.dc-nav')), b = [...document.querySelectorAll('.dv-view .dc-navb')].map(r), t = q('.dv-title');
      return {hl: h.left, hw: h.width, nl: n.left, nw: n.width, b0: b[0].left, b1: b[1].left, nt: r(q('.dc-navn')).left, title: t.textContent.trim(), tip: t.title, cut: t.scrollWidth > t.clientWidth, th: r(t).height, lh: parseFloat(getComputedStyle(t).lineHeight) || 0, ws: getComputedStyle(t).whiteSpace, ov: q('.dv-head').scrollWidth - q('.dv-head').clientWidth}; })()`;
    const open = async id => { await ev(`(document.querySelector('.dc-view [data-dco="${id}"]').click(), 1)`); return wait(`!!document.querySelector('.dv-view #dc-sender') && location.hash === '#ablage/${id}'`); };
    check(await open(D1), 'Firefox: the short document opens');
    await wait(`document.querySelectorAll('.dv-view .dc-navb').length === 2`);
    const a = await ev(HEAD);
    check(Math.abs((a.nl + a.nw / 2) - (a.hl + a.hw / 2)) <= 1.5, 'Firefox: the arrows sit in the middle of the head ' + JSON.stringify(a));
    await shot('p2780-head-short-1440.png');
    // leaf to the document with the very long name (the list: newest first -> D3, D2, D1; D1 is the last: arrow back twice)
    const step = async (dir, id) => { await ev(`(document.querySelector('.dv-view [data-dc="step:${dir}"]').click(), 1)`); return wait(`location.hash === '#ablage/${id}' && document.querySelector('.dv-view .dc-body')?.dataset.id === '${id}'`, 80); };
    check(await step(-1, D2), 'Firefox: the arrow leafs on to the document with the long name');
    await wait(`/${LONG.slice(0, 12)}/.test(document.querySelector('.dv-view #dc-h').textContent)`);
    const b = await ev(HEAD);
    check(Math.abs(b.b0 - a.b0) <= 1 && Math.abs(b.b1 - a.b1) <= 1, 'Firefox: long name -> the arrows keep their x (1 px) ' + JSON.stringify([a.b0, b.b0, a.b1, b.b1]));
    check(Math.abs((b.nl + b.nw / 2) - (b.hl + b.hw / 2)) <= 1.5, '... and stay in the middle of the head ' + JSON.stringify(b));
    check(b.cut && b.ws === 'nowrap' && b.th < 60 && b.tip.length > 100, 'Firefox: the long title is cut on one line, the full name in its tooltip ' + JSON.stringify({cut: b.cut, th: b.th, ws: b.ws, tip: b.tip.slice(0, 40)}));
    check(b.ov <= 1, 'Firefox: nothing sideways in the head ' + b.ov);
    check(await ev(`(() => { const hr = document.querySelector('.dv-hr').getBoundingClientRect(), h = document.querySelector('.dv-head').getBoundingClientRect(); return hr.right <= h.right + 1 && !!document.querySelector('.dv-hr [data-dc="del"]') && document.querySelector('.dv-hr [data-dc="del"]').getBoundingClientRect().right <= h.right + 1; })()`), 'Firefox: the actions stay at the right edge, Delete reachable');
    check(await ev(`(() => { const bk = document.querySelector('.dv-back').getBoundingClientRect(), h = document.querySelector('.dv-head').getBoundingClientRect(); return bk.left <= h.left + 2; })()`), 'Firefox: Back stays at the left edge');
    await shot('p2780-head-long-1440.png');
    check(await step(1, D1), 'Firefox: back to the short one');
    const c = await ev(HEAD);
    check(Math.abs(c.b0 - a.b0) <= 1, 'Firefox: and the arrows are where they were ' + JSON.stringify([a.b0, c.b0]));
    // the counter gets longer: "9 of 171" -> "10 of 171" moves nothing (the counter has a fixed width)
    const x9 = await ev(`(() => { const n = document.querySelector('.dv-view .dc-navn'); n.textContent = '9 of 171'; const r = [...document.querySelectorAll('.dv-view .dc-navb')].map(e => e.getBoundingClientRect().left); n.textContent = '10 of 171'; const s = [...document.querySelectorAll('.dv-view .dc-navb')].map(e => e.getBoundingClientRect().left); n.textContent = '1000 of 10000'; const t = [...document.querySelectorAll('.dv-view .dc-navb')].map(e => e.getBoundingClientRect().left); return {r, s, t}; })()`);
    check(Math.abs(x9.r[0] - x9.s[0]) <= 1 && Math.abs(x9.r[1] - x9.s[1]) <= 1 && Math.abs(x9.r[1] - x9.t[1]) <= 1, 'Firefox: "9 of 171" -> "10 of 171" -> "1000 of 10000": the arrows do not move ' + JSON.stringify(x9));
    // phone: as before -- the arrows in a row of their own, centered, nothing sideways
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + `#docs/${D2}`);
    check(await wait(`!!document.querySelector('.dv-view #dc-sender')`, 80), 'Firefox phone: the view opens');
    await wait(`document.querySelectorAll('.dv-view .dc-navb').length === 2`);
    const p = await ev(`(() => { const r = e => e.getBoundingClientRect(), h = r(document.querySelector('.dv-head')), n = r(document.querySelector('.dc-nav')), t = r(document.querySelector('.dv-title')), v = document.querySelector('.dv-view');
      return {nTop: n.top, tBot: t.bottom, nc: n.left + n.width / 2, hc: h.left + h.width / 2, sw: v.scrollWidth, cw: v.clientWidth}; })()`);
    check(p && p.nTop >= p.tBot - 1 && Math.abs(p.nc - p.hc) <= 2 && p.sw <= p.cw + 1, 'Firefox phone: the arrows in their own row, centered, nothing sideways ' + JSON.stringify(p));
    await shot('p2780-head-phone.png');
  });

  console.log(`p2780_a_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
