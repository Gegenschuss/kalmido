// 2.92.0 UI tests (part C, #1926), own container (start.sh), Firefox (desktop + phone width). Invented words only.
// - a task's .docx opens in the document preview (not a download): heading, bold text, list, table, built from the model
//   (an HTML tag in the file stays text); Close and Escape close it
// - a task's .xlsx: one tab per sheet, column letters and row numbers, a tap on the second tab shows its cells
// - "Summarize" only when an agent that sees the task can be asked: without one the hint how to connect / share; with the
//   agent in the list the button, the dialog names the agent, the comment mentions it; one undo step removes it again
// - an Ablage file (.docx) opens in the same preview
// - phone width: the preview fits the screen, large tap targets, screenshot
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p292_c_ui', check, shots: 'P292C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P292C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

// the test files: written with Python's zipfile (no zip library in node, nothing checked in)
const MAKE = String.raw`
import io, sys, zipfile
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
def z(parts):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as f:
        for k, v in parts.items():
            f.writestr(k, v)
    return b.getvalue()
p = lambda x, st="": '<w:p>' + ('<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % st if st else '') + x + '</w:p>'
r = lambda t, b=False: '<w:r>' + ('<w:rPr><w:b/></w:rPr>' if b else '') + '<w:t xml:space="preserve">%s</w:t></w:r>' % t
li = lambda t: '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>' + r(t) + '</w:p>'
body = (p(r("Projektplan Seestern"), "Heading1") + p(r("Wir liefern ") + r("Treibholz", True) + r(" am Montag."))
        + li("Punkt Anker") + li("Punkt Boje")
        + '<w:tbl><w:tr><w:tc>' + p(r("Posten")) + '</w:tc><w:tc>' + p(r("Menge")) + '</w:tc></w:tr><w:tr><w:tc>' + p(r("Seil")) + '</w:tc><w:tc>' + p(r("3")) + '</w:tc></w:tr></w:tbl>'
        + p(r("&lt;img src=x onerror=alert(1)&gt; bleibt Text")))
docx = z({"word/document.xml": '<w:document %s><w:body>%s</w:body></w:document>' % (W, body),
          "word/styles.xml": '<w:styles %s><w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style></w:styles>' % W,
          "word/numbering.xml": '<w:numbering %s><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>' % W})
wb = '<workbook %s %s><sheets><sheet name="Material" sheetId="1" r:id="rId1"/><sheet name="Termine" sheetId="2" r:id="rId2"/></sheets></workbook>' % (S, R)
rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="x" Target="worksheets/sheet2.xml"/></Relationships>')
cell = lambda ref, t: '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, t)
s1 = '<worksheet %s><sheetData><row r="1">%s%s</row><row r="2">%s<c r="B2"><v>42</v></c></row></sheetData></worksheet>' % (S, cell("A1", "Teil"), cell("B1", "Anzahl"), cell("A2", "Kompass"))
s2 = '<worksheet %s><sheetData><row r="3">%s</row></sheetData></worksheet>' % (S, cell("C3", "Leuchtfeuer Termin"))
xlsx = z({"xl/workbook.xml": wb, "xl/_rels/workbook.xml.rels": rels, "xl/worksheets/sheet1.xml": s1, "xl/worksheets/sheet2.xml": s2})
out = sys.argv[1]
open(out + "/plan.docx", "wb").write(docx)
open(out + "/liste.xlsx", "wb").write(xlsx)
`;
const TMP = path.join(DATA, 'p292c-files');
require('fs').mkdirSync(TMP, {recursive: true});
execFileSync('python3', ['-c', MAKE, TMP]);
const DOCX = require('fs').readFileSync(path.join(TMP, 'plan.docx')), XLSX = require('fs').readFileSync(path.join(TMP, 'liste.xlsx'));
const post = async (url, name, data, type, extra = {}) => {
  const fd = new FormData();
  fd.append('file', new Blob([data], {type}), name);
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return {status: r.status, ...(await r.json().catch(() => ({})))};
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const feats = ((await call('GET', '/api/state')).settings.features || '').split(',').filter(Boolean);
  await call('PATCH', '/api/settings', {features: [...new Set([...feats, 'files', 'comments', 'collab'])].join(',')});
  const L = (await call('POST', '/api/lists', {name: 'Harbour'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Lighthouse order', list_id: L})).id;
  const a1 = await post(`/api/tasks/${T}/attachments`, 'plan.docx', DOCX, DOCX_MIME);
  const a2 = await post(`/api/tasks/${T}/attachments`, 'liste.xlsx', XLSX, XLSX_MIME);
  check(a1.status < 300 && a2.status < 300, `setup: two task files ${a1.status} ${a2.status}`);
  const up = await post('/api/files/upload', 'brief.docx', DOCX, DOCX_MIME, {space: 'private', replace: '0'});
  const NID = up.items?.[0]?.id;
  check(up.status === 201 && NID, 'setup: an Ablage file ' + up.status);
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude', scopes: ['read', 'comments', 'attachments:read']});
  check(ag.id, 'setup: an agent ' + ag.status);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const click = (ev, sel) => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return 0; e.click(); return 1; })()`);
  const tile = name => `[...document.querySelectorAll('#detail a[data-dview]')].find(a => a.title === ${JSON.stringify(name)})`;
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await nav(B + '#t/' + T);
    check(await ready(ev, `!!(${tile('plan.docx')}) && !!(${tile('liste.xlsx')})`, 60), '#1926: the Word and Excel files carry the preview');
    // ---- docx
    await ev(`(() => { ${tile('plan.docx')}.click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.lightbox.dpview .dpvdoc')`, 60), '#1926: a tap on the .docx opens the preview (no download)');
    check(await ev(`(() => { const d = document.querySelector('.dpvdoc'); return /Projektplan Seestern/.test(d.querySelector('h2')?.textContent || '') && d.querySelector('strong')?.textContent === 'Treibholz'
      && d.querySelectorAll('ul li').length === 2 && d.querySelectorAll('table td').length === 4; })()`), '#1926: heading, bold, list and table');
    check(await ev(`(() => { const d = document.querySelector('.dpvdoc'); return !d.querySelector('img') && /<img src=x/.test(d.textContent); })()`), '#1926: markup in the file stays text');
    check(await ev(`!!document.querySelector('.dpview a[download]')`), '#1926: download in the bar');
    check(await ready(ev, `!!document.querySelector('.dpview .dpvfoot:not([hidden])') && !document.querySelector('.dpview .dpvsum')`) || await ev(`!document.querySelector('.dpview .dpvsum')`),
      '#1926: no agent in the list: no "Summarize" (a hint instead when agents are on)');
    await shot('p292c-docx.png');
    await ev(`(() => { document.querySelector('.dpview').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.lightbox')`), '#1926: Escape closes the preview');
    // ---- xlsx
    await ev(`(() => { ${tile('liste.xlsx')}.click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.dpview .dpvsheet')`, 60), '#1926: the .xlsx opens as a sheet');
    check(await ev(`(() => { const t = [...document.querySelectorAll('.dpvtab')].map(b => b.textContent); const h = [...document.querySelectorAll('.dpvsheet thead th')].map(x => x.textContent);
      return t.join('|') === 'Material|Termine' && h.join('|') === '|A|B' && document.querySelector('.dpvsheet tbody td.dpvnum')?.textContent === '42'; })()`), '#1926: sheet tabs, column letters, a number');
    await click(ev, '.dpvtab[data-i="1"]');
    check(await ready(ev, `document.querySelector('.dpvtab.on')?.textContent === 'Termine' && /Leuchtfeuer Termin/.test(document.querySelector('.dpvsheet')?.textContent || '') && document.querySelector('.dpvsheet tbody th')?.textContent === '3'`),
      '#1926: the second sheet with its row number');
    await shot('p292c-xlsx.png');
    await click(ev, '[data-dpv="x"]');
    check(await ready(ev, `!document.querySelector('.lightbox')`), '#1926: Close closes it');
    // ---- the agent in the list: "Summarize"
    const m = await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
    check(m.status < 300, 'setup: the agent in the list ' + m.status);
    await ev(`(() => { ${tile('plan.docx')}.click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.dpview .dpvsum')`, 60), '#1926: with an agent that sees the task: "Summarize"');
    await click(ev, '.dpview .dpvsum');
    check(await ready(ev, `!!document.querySelector('.modal.cdlg') && /plan\\.docx/.test(document.querySelector('.modal .dpvwho')?.textContent || '') && /Claude/.test(document.querySelector('.modal .dpvwho').textContent)`),
      '#1926: the dialog names the file and the agent');
    await shot('p292c-summarize.png');
    await click(ev, '.modal [data-cd="yes"]');
    const hasC = () => call('GET', `/api/tasks/${T}/timeline`).then(j => (j.items || j.comments || j.timeline || []).filter(x => (x.body || '').includes(`<@${ag.id}>`) && !x.deleted_at && (x.body || '').includes('plan.docx')).length);
    let n = 0; for (let i = 0; i < 40 && !n; i++) { n = await hasC(); if (!n) await sleep(250); }
    check(n === 1, '#1926: the comment mentions the agent and names the file');
    check(await ready(ev, `/Claude/.test(document.querySelector('#toast')?.textContent || '')`), '#1926: a toast with undo');
    await ev(`(() => { const b = [...document.querySelectorAll('#toast button')].find(x => /undo/i.test(x.textContent)); b?.click(); return !!b; })()`);
    let gone = false; for (let i = 0; i < 40 && !gone; i++) { gone = (await hasC()) === 0; if (!gone) await sleep(250); }
    check(gone, '#1926: undo removes the comment again');
    // ---- Ablage
    await nav(B + '#ablage');
    check(await ready(ev, `[...document.querySelectorAll('[data-ab="open"]')].some(b => /brief\\.docx/.test(b.textContent))`, 60), 'the Ablage lists the file');
    await ev(`(() => { [...document.querySelectorAll('[data-ab="open"]')].find(b => /brief\\.docx/.test(b.textContent)).click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.dpview .dpvdoc h2')`, 60), '#1926: an Ablage .docx opens in the preview');
    check(await ev(`!document.querySelector('.dpview .dpvsum')`), '#1926: no "Summarize" for an Ablage file (no comments there)');
    await click(ev, '[data-dpv="x"]');
    // ---- phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#t/' + T);
    await ready(ev, `!!(${tile('liste.xlsx')})`, 60);
    await ev(`(() => { ${tile('liste.xlsx')}.click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.dpview .dpvsheet')`, 60), '390: the sheet opens');
    const g = await ev(`(() => { const b = document.querySelector('.dpvbox').getBoundingClientRect(), x = document.querySelector('[data-dpv="x"]').getBoundingClientRect(), t = document.querySelector('.dpvtab').getBoundingClientRect();
      return {l: b.left, r: b.right, wide: document.documentElement.scrollWidth <= 390, x: x.height, t: t.height}; })()`);
    check(g && g.l >= 0 && g.r <= 390 && g.wide && g.x >= 36 && g.t >= 39, '390: the preview fits, large targets ' + JSON.stringify(g));
    await shot('p292c-390-xlsx.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
