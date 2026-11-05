// 2.555.0 UI test, part A (#4470: the field forms of a document and a receipt follow one rule by their own width), own
// kalmido-suite:
// container (start.sh), Firefox. Invented data only. Alice has no organisation (private documents in her own office), so this
// is the freelancer case too.
// - computer, the pane beside the list (under 36rem): every label above its field, every field the full width of the form,
//   one right edge for all fields (also the ones marked "automatic", the mark stands at the right of the label line); the date
//   button as high as a text field, the same border and background
// - a wide form (a whole page of 760 px): the label column left of the fields, still one right edge
// - phone 390 px: labels above the fields, no sideways scrolling
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2555_a_formnarrow_ui', check, shots: 'P2555A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2555A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

function textPdf(lines) {  // a one-page PDF with a text layer, written by hand
  const stream = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${l}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return out;
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,docs'});
  const upload = async (name, lines) => {
    const fd = new FormData(); fd.append('ws', 'private'); fd.append('area', 'office'); fd.append('files', new Blob([textPdf(lines)], {type: 'application/pdf'}), name + '.pdf');
    const rr = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CA}, body: fd});
    const id = ((await rr.json()).ids || [])[0];
    for (let i = 0; i < 120; i++) { const d = await call(CA, 'GET', `/api/docs/${id}`); if (d.state === 'done' || d.state === 'failed') return d; await sleep(250); }
    return call(CA, 'GET', `/api/docs/${id}`);
  };
  const R = await upload('receipt-with-a-rather-long-name', ['Quittung', 'Datum 02.10.2026']);
  const pr = await call(CA, 'PUT', `/api/docs/${R.id}/receipt`, {project_id: null, category: 'Material', vat_pct: '19', keep: true});
  check(pr.receipt?.is_receipt === true, 'setup: a receipt ' + pr.http);

  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const open = async (nav, ev, doc) => { await nav(B + 'static/icon.svg'); await nav(B + `#docs/${doc.id}`); return ready(ev, `document.querySelector('.dc-form #dc-name')?.value === ${JSON.stringify(doc.name)} && !!document.querySelector('#rc-cat')`); };
  // two fields marked "automatic" (as a rule sets them), drawn by the page itself
  const mark = `(() => { DC.doc.auto = {...(DC.doc.auto || {}), type: 'rule', folder: 'rule'}; dc_mdDraw(document.querySelector('.dc-body').parentElement); return !!document.querySelector('.dc-f .dc-auto'); })()`;
  // each visible row with a label: label, field, row and the "automatic" mark
  const ROWS = `(() => { const vis = e => e.getClientRects().length > 0, b = e => { const r = e.getBoundingClientRect(); return {l: Math.round(r.left), r: Math.round(r.right), t: Math.round(r.top), b: Math.round(r.bottom), h: Math.round(r.height)}; };
    const rows = [...document.querySelectorAll('.rc-slot .dc-f, .dc-form .dc-f')].filter(vis).filter(r => r.children[0].tagName === 'LABEL');
    return JSON.stringify({w: Math.round(document.querySelector('.dc-props').clientWidth), rows: rows.map(r => { const a = r.querySelector('.dc-auto'); return {f: r.children[0].htmlFor, lab: b(r.children[0]), fld: b(r.children[1]), row: b(r), auto: a ? b(a) : null}; })}); })()`;
  const oneRight = rows => rows.length > 0 && rows.every(r => Math.abs(r.fld.r - rows[0].fld.r) <= 1);
  const above = rows => rows.every(r => r.lab.b <= r.fld.t + 1 && Math.abs(r.lab.l - r.fld.l) <= 1);
  const full = rows => rows.every(r => r.fld.r - r.fld.l >= r.row.r - r.row.l - 1);
  const autoInLabelLine = rows => rows.filter(r => r.auto).every(r => r.auto.b <= r.fld.t + 1 && Math.abs(r.auto.r - r.fld.r) <= 1 && r.auto.t < r.lab.b);
  // the date button against the title field: height, border colour, background
  const DATE = `(() => { const a = document.querySelector('#dc-date-w .dpbtn'), n = document.querySelector('#dc-name'), s = getComputedStyle(a), t = getComputedStyle(n);
    return JSON.stringify({h: [Math.round(a.getBoundingClientRect().height), Math.round(n.getBoundingClientRect().height)], bc: [s.borderTopColor, t.borderTopColor], bg: [s.backgroundColor, t.backgroundColor], bw: [s.borderTopWidth, t.borderTopWidth],
      r: [Math.round(a.getBoundingClientRect().right), Math.round(n.getBoundingClientRect().right)]}); })()`;
  const dateLikeField = o => Math.abs(o.h[0] - o.h[1]) <= 1 && o.bc[0] === o.bc[1] && o.bg[0] === o.bg[1] && o.bw[0] === o.bw[1] && Math.abs(o.r[0] - o.r[1]) <= 1;
  // the page and the sheet do not scroll sideways, no part of the form reaches past the right edge of the sheet
  const noSide = `(() => { const W = document.documentElement.clientWidth, b = document.querySelector('.dc-body'), card = b.closest('.card') || b.parentElement, f = b.querySelector('.dc-props'), fr = f.getBoundingClientRect().right;
    const out = [...f.querySelectorAll('*')].filter(e => e.getClientRects().length && e.getBoundingClientRect().right > fr + .5).map(e => e.tagName + '.' + String(e.className).slice(0, 30));
    return JSON.stringify({ok: document.documentElement.scrollWidth <= W && card.scrollWidth <= card.clientWidth && !out.length, W, sw: document.documentElement.scrollWidth, cs: card.scrollWidth, cc: card.clientWidth, out: out.slice(0, 8)}); })()`;

  // the theme of this run: the appearance synced from the server wins over a value put into localStorage before the load
  const theme_ = t => `(() => { if (typeof LS === 'undefined' || typeof applyLook !== 'function') return false; if (LS.get('theme', 'auto') !== '${'${t}'}') { LS.set('theme', '${'${t}'}'); applyLook(); } return document.documentElement.dataset.theme === '${'${t}'}'; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    for (const theme of ['light', 'dark']) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
      await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);

      // ---- computer: the pane beside the list
      check(await open(nav, ev, R), `${theme}: the receipt opens in the pane`);
      check(await ev(mark), `${theme}: two fields marked automatic`);
      let g = JSON.parse(await ev(ROWS));
      check(g.w < 576 && g.rows.length >= 8, `${theme}: the pane form is narrower than 36rem, receipt + document fields ` + JSON.stringify({w: g.w, n: g.rows.length}));
      check(above(g.rows), `${theme} pane: every label above its field ` + JSON.stringify(g.rows.filter(r => r.lab.b > r.fld.t + 1)));
      check(full(g.rows), `${theme} pane: every field the full width ` + JSON.stringify(g.rows.map(r => [r.f, r.fld.r - r.fld.l, r.row.r - r.row.l])));
      check(oneRight(g.rows), `${theme} pane: one right edge for all fields, also the automatic ones ` + JSON.stringify(g.rows.map(r => [r.f, r.fld.r])));
      check(g.rows.filter(r => r.auto).length === 2 && autoInLabelLine(g.rows), `${theme} pane: "automatic" at the right of the label line ` + JSON.stringify(g.rows.filter(r => r.auto)));
      const dt = JSON.parse(await ev(DATE));
      check(dateLikeField(dt), `${theme} pane: the date button looks like a text field ` + JSON.stringify(dt));
      await ev(`document.querySelector('.dc-form').scrollIntoView()`);
      await ready(ev, theme_(theme)); await shot(`p2555-a-pane-${theme}.png`);

      // ---- a wide form: the whole page at 760 px
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 760, height: 1000}});
      check(await open(nav, ev, R), `${theme}: the receipt opens as a page at 760 px`);
      check(await ev(mark), `${theme} 760: marked automatic`);
      check(await ready(ev, `document.querySelector('.dc-props').clientWidth >= 576`), `${theme} 760: the form is 36rem or wider`);
      g = JSON.parse(await ev(ROWS));
      check(g.rows.every(r => r.lab.r < r.fld.l && r.lab.t < r.fld.b), `${theme} wide: the label column left of the fields ` + JSON.stringify(g.rows.filter(r => r.lab.r >= r.fld.l)));
      check(oneRight(g.rows) && g.rows.every(r => Math.abs(r.fld.l - g.rows[0].fld.l) <= 1), `${theme} wide: one left and one right edge of the fields ` + JSON.stringify(g.rows.map(r => [r.f, r.fld.l, r.fld.r])));
      check(g.rows.filter(r => r.auto).every(r => r.auto.r <= r.fld.l), `${theme} wide: "automatic" in the label column, not beside the field ` + JSON.stringify(g.rows.filter(r => r.auto)));
      await ev(`document.querySelector('.dc-form').scrollIntoView()`);
      await ready(ev, theme_(theme)); await shot(`p2555-a-wide-${theme}.png`);

      // ---- phone 390 px
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
      check(await open(nav, ev, R), `${theme}: the receipt opens on a phone`);
      check(await ev(mark), `${theme} 390: marked automatic`);
      g = JSON.parse(await ev(ROWS));
      check(above(g.rows) && full(g.rows) && oneRight(g.rows) && autoInLabelLine(g.rows), `${theme} 390: labels above, full width, one right edge ` + JSON.stringify(g.rows.map(r => [r.f, r.lab.b, r.fld.t, r.fld.r])));
      check(dateLikeField(JSON.parse(await ev(DATE))), `${theme} 390: the date button looks like a text field`);
      { const o = JSON.parse(await ev(noSide)); check(o.ok, `${theme} 390: no sideways scrolling ` + JSON.stringify(o)); }
      await ev(`document.querySelector('.dc-form').scrollIntoView()`);
      await ready(ev, theme_(theme)); await shot(`p2555-a-phone-${theme}.png`);
    }
  }, false);

  console.log(`p2555_a_formnarrow_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
