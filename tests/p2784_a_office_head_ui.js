// 2.784.0 A UI test (#5402): the office head at 320, 460 and 840 px does not overlap. Own container (start.sh), Firefox, a finger.
// kalmido-suite: fresh
// Invented people only. freelancer-matrix: office (no new route) -- carol has no organisation (the admin of her own office, P4).
// - Office > Receipts (#office/receipts) with a real receipt: the bar of the points (.ofpb: the way back + .ofpts, one row that scrolls)
//   and every visible button / link / field of the page measured by getBoundingClientRect: no two of them cut into each other
//   (a box inside another one is no overlap), nothing sticks out of the window to the side, the page does not scroll sideways,
//   nothing of the page starts under the sticky bar
// - the bar is reachable: its last point comes into sight by scrolling the row; the texts "Receipts" and "Bank" are read
// - the same on the start list (#office, .oflg) and on Money > Bank
// - the receipt sheet (its "Apply" line, if the recognition proposes values) does not overlap either
// P2784A_NOSTART=1 = the server already runs. Screenshots: P2784A_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2784_a_ui', check, shots: 'P2784A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2784A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const FEAT = 'cal,comments,collab,contacts,office,clients,docs';
const today = TC.today();
function tinyPdf(lines) {  // a one-page PDF with a text layer
  const s = 'BT /F1 12 Tf 40 700 Td 16 TL ' + lines.map(t => `(${t}) Tj T*`).join(' ') + ' ET';
  const o = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${s.length} >>\nstream\n${s}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  o.forEach((x, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${x}\nendobj\n`; });
  const xr = out.length; out += `xref\n0 ${o.length + 1}\n0000000000 65535 f \n` + offs.map(n => String(n).padStart(10, '0') + ' 00000 n \n').join('');
  return out + `trailer\n<< /Size ${o.length + 1} /Root 1 0 R >>\nstartxref\n${xr}\n%%EOF\n`;
}
// run in the page: the boxes of the page's controls; returns the problems as strings
const MEASURE = `(() => {
  const W = window.innerWidth, out = [];
  const closed = e => { const d = e.closest('details:not([open])'); return !!d && !(e.closest('summary') && e.closest('summary').parentElement === d); };  // the content of a closed <details> has no box on the page
  const vis = e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && !e.closest('[hidden],[inert]') && !closed(e); };
  const bar = document.querySelector('#view .ofpb'), row = bar && bar.querySelector('.ofpts');
  const clip = e => { const sc = e.closest('.ofpts'); if (!sc) return true; const a = e.getBoundingClientRect(), b = sc.getBoundingClientRect(); return a.left >= b.left - 1 && a.right <= b.right + 1; };  // a point scrolled out of its row is not on the page
  const els = [...document.querySelectorAll('#view button, #view a[href], #view input:not([type=hidden]):not([type=file]), #view select, #view [role=tab], #view .ofpt2')].filter(vis).filter(clip);
  const box = e => { const r = e.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom}; };
  const nm = e => (e.className && String(e.className).split(' ')[0] || e.tagName.toLowerCase()) + ':' + (e.textContent || e.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 18) + '@' + [e.getBoundingClientRect().left, e.getBoundingClientRect().top, e.getBoundingClientRect().width, e.getBoundingClientRect().height].map(Math.round).join(',');
  for (let i = 0; i < els.length; i++) for (let j = i + 1; j < els.length; j++) {
    const a = els[i], c = els[j]; if (a.contains(c) || c.contains(a)) continue;
    const x = box(a), y = box(c), w = Math.min(x.r, y.r) - Math.max(x.l, y.l), h = Math.min(x.b, y.b) - Math.max(x.t, y.t);
    if (w > 1 && h > 1) out.push('overlap ' + nm(a) + ' x ' + nm(c));
  }
  for (const e of els) { const r = e.getBoundingClientRect(); if (r.right > W + 1 || r.left < -1) out.push('outside ' + nm(e) + ' ' + Math.round(r.left) + '..' + Math.round(r.right)); }
  if (document.documentElement.scrollWidth > W + 1) out.push('scrolls sideways ' + document.documentElement.scrollWidth);
  if (bar && getComputedStyle(bar).position === 'sticky') {  // the page's first content starts below the bar
    const bb = bar.getBoundingClientRect(), nx = bar.nextElementSibling;
    if (nx && vis(nx) && nx.getBoundingClientRect().top < bb.bottom - 1) out.push('content under the bar ' + nm(nx));
  }
  return JSON.stringify(out);
})()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CC = await login('carol');
  await call(CC, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CC, 'GET', '/api/state')).me.workspaces || []).length, 'P4: carol has no organisation');
  check((await call(CC, 'GET', '/api/office/settings')).role === 'admin', 'P4: carol is the admin of her own office');
  // two real receipts; the first one has a text layer with the values the recognition can propose
  const ids = [];
  for (const [name, lines, amount] of [['toner.pdf', ['Example Supplies Ltd', 'Invoice No. RE-2784-01', 'Net 100.00 EUR', 'VAT 19 % 19.00 EUR', 'Gross 119.00 EUR'], '119.00'], ['paper.pdf', ['Beleg paper'], '59.50']]) {
    const fd = new FormData(); fd.append('files', new Blob([tinyPdf(lines)], {type: 'application/pdf'}), name);
    const u = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CC}, body: fd}); const j = await u.json().catch(() => ({}));
    check(u.status === 201 && j.ids?.length === 1, 'upload ' + name + ' ' + u.status);
    const id = (j.ids || [])[0]; ids.push(id);
    check((await call(CC, 'PATCH', `/api/docs/${id}`, {amount, date: today})).http === 200, 'amount + date ' + name);
    check((await call(CC, 'PUT', `/api/docs/${id}/receipt`, {category: 'Material', vat_pct: '19', keep: true})).http === 200, 'receipt ' + name);
  }

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const probs = async (ev, what) => { const p = JSON.parse(await ev(MEASURE)); check(!p.length, what + ' ' + JSON.stringify(p)); return p; };

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.ofmAll', 'true'); localStorage.setItem('tasks.sbbUnfold', '["office:money"]'); return 1; })()`);
    check(await signIn(ev, 'carol') === 200, 'carol signs in');
    for (const w of [320, 460, 840]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: 800}});
      const at = `${w} px: `;
      // ---- Receipts: the bar, the list, the controls
      await nav(B + 'static/icon.svg'); await nav(B + '#office/receipts');
      const bar = w < 840;  // 840 px and wider: the points sit in the side panel, no bar in the page (2.152.2, #2617)
      check(await ready(ev, `${bar ? "!!document.querySelector('#view .ofpb .ofpts .ofpt2.on') && " : ''}document.querySelectorAll('#view .rcl-list > li').length === 2`, 100), at + 'Receipts open with the bar and both receipts');
      await sleep(400);
      if (bar) check(await ev(`(() => { const b = document.querySelector('#view .ofpb'); return /Receipts/.test(b.querySelector('.ofpt2.on').textContent) && [...b.querySelectorAll('.ofpt2')].some(t => t.textContent.trim() === 'Bank') && /Bank|Cash|Credit/.test(b.textContent); })()`), at + 'the points read "Receipts" and "Bank"');
      await probs(ev, at + 'Receipts: nothing overlaps or sticks out');
      // the last point comes into sight by scrolling the row, and then nothing overlaps either
      const seen = !bar || await ev(`(() => { const row = document.querySelector('#view .ofpts'), ts = [...row.querySelectorAll('.ofpt2')], last = ts[ts.length - 1]; last.scrollIntoView({inline: 'end', block: 'nearest'}); const a = last.getBoundingClientRect(), b = row.getBoundingClientRect(); return a.left >= b.left - 1 && a.right <= b.right + 1 && a.width > 20; })()`);
      if (bar) check(seen, at + 'the last point of the bar can be scrolled into sight');
      await sleep(200);
      await probs(ev, at + 'Receipts, bar scrolled to its end: nothing overlaps');
      await shot(`p2784a-receipts-${w}.png`);
      // ---- the receipt sheet (the "Apply" line when values are proposed)
      await ev(`(() => { const r = document.querySelector('#view .ofpts'); if (r) r.scrollLeft = 0; return 1; })()`);
      await ev(`(() => { const b = document.querySelector('#view .rcl-list [data-rcl="rc"][data-id="${ids[0]}"]'); b && b.click(); return 1; })()`);
      check(await ready(ev, `!!document.querySelector('.bk-sheet')`, 60), at + 'the receipt sheet opens');
      await sleep(500);
      const sheet = JSON.parse(await ev(`(() => { const s = document.querySelector('.bk-sheet'), W = window.innerWidth, out = [];
        const bs = [...s.querySelectorAll('button, input:not([type=hidden]):not([type=file]), select, a[href]')].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden' && !(e.closest('details:not([open])') && !e.closest('summary')); });
        const sr = s.getBoundingClientRect();
        for (let i = 0; i < bs.length; i++) for (let j = i + 1; j < bs.length; j++) { if (bs[i].contains(bs[j]) || bs[j].contains(bs[i])) continue; const x = bs[i].getBoundingClientRect(), y = bs[j].getBoundingClientRect();
          if (Math.min(x.right, y.right) - Math.max(x.left, y.left) > 1 && Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top) > 1) out.push('overlap ' + (bs[i].textContent || bs[i].id).trim().slice(0, 14) + '@' + [x.left, x.top, x.width, x.height].map(Math.round) + ' x ' + (bs[j].textContent || bs[j].id).trim().slice(0, 14) + '@' + [y.left, y.top, y.width, y.height].map(Math.round)); }
        for (const e of bs) { const r = e.getBoundingClientRect(); if (r.right > W + 1 || r.left < -1) out.push('outside ' + (e.textContent || e.id).trim().slice(0, 14)); }
        const ap = s.querySelector('[data-rx^="apply:"]');
        return JSON.stringify({out, n: bs.length, apply: ap ? ap.textContent.trim() : null}); })()`));
      check(!sheet.out.length && sheet.n > 3, at + 'the receipt sheet: nothing overlaps or sticks out ' + JSON.stringify(sheet));
      if (sheet.apply !== null) check(sheet.apply === 'Apply', at + 'the proposal line shows "Apply"');
      else console.log(`note: ${at}the recognition proposed no values, the sheet has no "Apply" line to measure`);
      await shot(`p2784a-sheet-${w}.png`);
      await ev(`(() => { const c = document.querySelector('.bk-sheet [data-m="close"]'); c && c.click(); return 1; })()`);
      check(await ready(ev, `!document.querySelector('.bk-sheet')`, 40), at + 'the sheet closes again');
      // ---- the start list of the office and Bank
      await nav(B + '#office');
      check(await ready(ev, `${bar ? "document.querySelectorAll('#view .ofmstart .oflg').length >= 3 && [...document.querySelectorAll('#view .oflr')].some(b => /Bank/.test(b.textContent))" : "document.querySelector('#view').textContent.trim().length > 80"}`, 100), at + 'the start list reads the groups and "Bank"');
      await sleep(300);
      await probs(ev, at + 'start list: nothing overlaps or sticks out');
      await nav(B + '#office/bank');
      check(await ready(ev, bar ? `!!document.querySelector('#view .ofpb .ofpt2.on') && /Bank/.test(document.querySelector('#view .ofpb .ofpt2.on').textContent)` : `document.querySelector('#view').textContent.trim().length > 80 && /bank/i.test(location.hash + document.querySelector('#view').textContent)`, 100), at + 'Bank opens' + (bar ? ' with its bar' : ''));
      await sleep(500);
      await probs(ev, at + 'Bank: nothing overlaps or sticks out');
      await shot(`p2784a-bank-${w}.png`);
    }
  }, true);

  console.log(F.length ? 'FAILED: ' + F.length : 'ok ' + ok);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
