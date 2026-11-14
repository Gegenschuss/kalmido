// @ts-check
/* Kalmido web client: 2.1151.0 D (#5524) a knowledge page of a space WITH the lock as a file, made in the browser (the server
   only holds its ciphertext; GET /api/wiki/pages/<id>/export answers 409 there, like the space's export). Loaded on demand
   (lazyload.js module 'wkdoc', from the page's "…" menu, wiki.js wk_docItems).
   - .docx: the page as the app shows it (wk_render), walked into WordprocessingML (headings, paragraphs, bold / italic /
     struck / code, web and mail links, lists with ticks, quotes, code blocks, rules, tables); pictures as their text (a space
     with the lock has no files). Packed with the ZIP writer of the space's export (wikie2e.js wkeZip).
   - PDF: the browser's print function on the page alone (its reading style), "Save as PDF" there -- no PDF writer here.
   The look follows the reading style the page is shown in (wklive.js wkst_of), the same choices as the server's file
   (kalmido/wiki/wkdoc.py WKD_LOOK). Classic script sharing the global scope. */
'use strict';

const WDX_LOOK = {'': {fs: 10.5, lh: 1.45, side: 22, gap: 0.6, font: 'Arial'}, book: {fs: 11, lh: 1.65, side: 32, gap: 0.75, font: 'Georgia'},
  compact: {fs: 9, lh: 1.3, side: 16, gap: 0.35, font: 'Arial'}, notepad: {fs: 10.5, lh: 1.6, side: 24, gap: 0.6, font: 'Arial'}};
const WDX_HEAD = [1.9, 1.5, 1.28, 1.14, 1.05, 1.0];
const WDX_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';
const WDX_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const WDX_HEAD_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
const wdxX = s => String(s ?? '').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f￾￿]/g, '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const wdxStyle = sp => (typeof wkst_of === 'function' ? wkst_of(sp) : '') || '';
function wdxName(p, ext) { return (String(p.path || '').split('/').pop().replace(/[\\/:*?"<>|\u0000-\u001f]+/g, ' ').trim().replace(/^\.+|\.+$/g, '') || 'page').slice(0, 80) + '.' + ext; }
// the page as the app draws it, as a detached element (DOMParser: nothing runs, nothing is put into the page)
// the drawn text starts with a heading that only repeats the page's name: no extra title then (as the server's file)
function wdxDupTitle(dom, title) {
  const h = dom.querySelector('h1, h2, h3, h4, h5, h6'), t = String(title).trim().toLowerCase();
  return !!h && (h.textContent || '').trim().toLowerCase() === t && (dom.textContent || '').trim().toLowerCase().startsWith(t);
}
function wdxDom(p) {
  const html = typeof wk_render === 'function' ? wk_render(p) : '';
  return /** @type {HTMLElement} */ (new DOMParser().parseFromString('<div>' + html + '</div>', 'text/html').body.firstElementChild);
}

// ---- .docx --------------------------------------------------------------------------------------------------------
function wdxDocx(p) {
  const lk = WDX_LOOK[wdxStyle(p.space)] || WDX_LOOK[''], rels = [], nums = [], title = String(p.path || '').split('/').pop();
  const rel = href => { const id = 'rId' + (rels.length + 10); rels.push([id, href]); return id; };
  const run = (/** @type {string} */ t, /** @type {any} */ s) => {
    let pr = (s.b ? '<w:b/>' : '') + (s.i ? '<w:i/>' : '') + (s.s ? '<w:strike/>' : '');
    if (s.c) pr = '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>' + pr + '<w:shd w:val="clear" w:color="auto" w:fill="F1F3F6"/>';
    if (s.a) pr = '<w:rStyle w:val="Hyperlink"/>' + pr;
    return '<w:r>' + (pr ? '<w:rPr>' + pr + '</w:rPr>' : '') + String(t).split('\n').map(x => '<w:t xml:space="preserve">' + wdxX(x) + '</w:t>').join('<w:br/>') + '</w:r>';
  };
  // the inline content of an element -> runs (nested lists stay out: they are blocks of their own)
  const inl = (/** @type {Element} */ el, /** @type {any} */ s = {}) => {
    let out = '';
    for (const n of el.childNodes) {
      if (n.nodeType === 3) { const t = (n.textContent || '').replace(/\s+/g, ' '); if (t) out += run(t, s); continue; }
      if (n.nodeType !== 1) continue;
      const e = /** @type {HTMLElement} */ (n), tg = e.tagName;
      if (tg === 'UL' || tg === 'OL' || tg === 'SCRIPT' || tg === 'STYLE' || tg === 'BUTTON' || e.classList.contains('sr')) continue;
      if (tg === 'BR') out += '<w:r><w:br/></w:r>';
      else if (tg === 'INPUT' && /** @type {HTMLInputElement} */ (e).type === 'checkbox') out += run(/** @type {HTMLInputElement} */ (e).checked || e.hasAttribute('checked') ? '☒ ' : '☐ ', s);
      else if (tg === 'IMG') out += run(e.getAttribute('alt') || '', {...s, i: true});
      else if (tg === 'A' && /^(https?:|mailto:)/i.test(e.getAttribute('href') || '')) out += '<w:hyperlink r:id="' + rel(e.getAttribute('href')) + '">' + inl(e, {...s, a: true}) + '</w:hyperlink>';
      else out += inl(e, {...s, b: s.b || tg === 'STRONG' || tg === 'B' || tg === 'TH', i: s.i || tg === 'EM' || tg === 'I', s: s.s || tg === 'DEL' || tg === 'S', c: s.c || tg === 'CODE'});
    }
    return out;
  };
  const para = (inner, st, ppr = '') => '<w:p>' + (st || ppr ? '<w:pPr>' + (st ? '<w:pStyle w:val="' + st + '"/>' : '') + ppr + '</w:pPr>' : '') + inner + '</w:p>';
  const body = [];
  const list = (el, depth) => {
    const ordered = el.tagName === 'OL';
    if (ordered) nums.push(+(el.getAttribute('start') || 1) || 1);
    const nid = ordered ? 1 + nums.length : 1;
    for (const li of el.children) {
      if (li.tagName !== 'LI') continue;
      body.push(para(inl(li), 'ListParagraph', '<w:numPr><w:ilvl w:val="' + Math.min(3, depth) + '"/><w:numId w:val="' + nid + '"/></w:numPr>'));
      for (const sub of li.children) if (sub.tagName === 'UL' || sub.tagName === 'OL') list(sub, depth + 1);
    }
  };
  const blocks = (el, quote = false) => {
    for (const n of el.childNodes) {
      if (n.nodeType === 3) { if ((n.textContent || '').trim()) body.push(para(run(n.textContent.trim(), {}), quote ? 'Quote' : '')); continue; }
      if (n.nodeType !== 1) continue;
      const e = /** @type {HTMLElement} */ (n), tg = e.tagName;
      if (/^H[1-6]$/.test(tg)) body.push(para(inl(e), 'Heading' + Math.min(6, Math.max(1, +tg[1] - top + 1))));  // the app draws "#" as h4: the page's highest level is Heading1
      else if (tg === 'P') body.push(para(inl(e), quote ? 'Quote' : ''));
      else if (tg === 'UL' || tg === 'OL') list(e, 0);
      else if (tg === 'BLOCKQUOTE') blocks(e, true);
      else if (tg === 'PRE') body.push(para(run((e.textContent || '').replace(/\n$/, ''), {}), 'Code'));
      else if (tg === 'HR') body.push(para('', '', '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="C9CED6"/></w:pBdr>'));
      else if (tg === 'TABLE') {
        const rows = [...e.querySelectorAll('tr')], n = Math.max(1, ...rows.map(r => r.children.length)), tw = Math.round((210 - 2 * lk.side) * 56.7), cw = Math.floor(tw / n);
        const bd = ['top', 'left', 'bottom', 'right', 'insideH', 'insideV'].map(s => '<w:' + s + ' w:val="single" w:sz="4" w:space="0" w:color="C9CED6"/>').join('');
        body.push('<w:tbl><w:tblPr><w:tblW w:w="' + tw + '" w:type="dxa"/><w:tblBorders>' + bd + '</w:tblBorders></w:tblPr><w:tblGrid>' + '<w:gridCol w:w="' + cw + '"/>'.repeat(n) + '</w:tblGrid>'
          + rows.map(r => { const head = [...r.children].some(c => c.tagName === 'TH'); return '<w:tr>' + (head ? '<w:trPr><w:tblHeader/></w:trPr>' : '') + [...r.children].map(c => '<w:tc><w:tcPr><w:tcW w:w="' + cw + '" w:type="dxa"/>' + (head ? '<w:shd w:val="clear" w:color="auto" w:fill="F1F3F6"/>' : '') + '</w:tcPr>' + para(inl(c, {b: head}), '') + '</w:tc>').join('') + '</w:tr>'; }).join('') + '</w:tbl>');
        body.push(para('', ''));
      } else if (tg === 'IMG') body.push(para(run(e.getAttribute('alt') || '', {i: true}), ''));
      else if (tg === 'SCRIPT' || tg === 'STYLE' || tg === 'BUTTON') continue;
      else if ([...e.children].some(c => /^(P|H[1-6]|UL|OL|PRE|TABLE|BLOCKQUOTE|HR|DIV|SECTION|FIGURE)$/.test(c.tagName))) blocks(e, quote);
      else { const t = inl(e); if (t) body.push(para(t, quote ? 'Quote' : '')); }
    }
  };
  const dom = wdxDom(p), top = Math.min(6, ...[...dom.querySelectorAll('h1, h2, h3, h4, h5, h6')].map(h => +h.tagName[1]));
  if (!wdxDupTitle(dom, title)) body.push(para(run(title, {}), 'Title'));
  blocks(dom);
  const hs = Math.round(lk.fs * 2), ln = Math.round(240 * lk.lh / 1.15), after = Math.round(lk.fs * lk.gap * 20), side = Math.round(lk.side * 56.7), f = lk.font;
  const doc = WDX_HEAD_XML + '<w:document ' + WDX_NS + '><w:body>' + body.join('') + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1247" w:right="' + side + '" w:bottom="1134" w:left="' + side + '" w:header="709" w:footer="709" w:gutter="0"/></w:sectPr></w:body></w:document>';
  const head = [1, 2, 3, 4, 5, 6].map(n => '<w:style w:type="paragraph" w:styleId="Heading' + n + '"><w:name w:val="heading ' + n + '"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="' + Math.round(hs * WDX_HEAD[n - 1] * 6) + '" w:after="' + after + '"/><w:outlineLvl w:val="' + (n - 1) + '"/></w:pPr><w:rPr><w:b/><w:sz w:val="' + Math.round(hs * WDX_HEAD[n - 1]) + '"/></w:rPr></w:style>').join('');
  const styles = WDX_HEAD_XML + '<w:styles ' + WDX_NS + '><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="' + f + '" w:hAnsi="' + f + '" w:cs="' + f + '" w:eastAsia="' + f + '"/><w:sz w:val="' + hs + '"/><w:szCs w:val="' + hs + '"/></w:rPr></w:rPrDefault>'
    + '<w:pPrDefault><w:pPr><w:spacing w:after="' + after + '" w:line="' + ln + '" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
    + '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
    + '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="' + after * 2 + '"/></w:pPr><w:rPr><w:b/><w:sz w:val="' + Math.round(hs * WDX_HEAD[0]) + '"/></w:rPr></w:style>' + head
    + '<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:pBdr><w:left w:val="single" w:sz="12" w:space="8" w:color="C9CED6"/></w:pBdr><w:ind w:left="340"/></w:pPr><w:rPr><w:color w:val="4B515C"/></w:rPr></w:style>'
    + '<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:pPr><w:shd w:val="clear" w:color="auto" w:fill="F1F3F6"/><w:spacing w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/><w:sz w:val="' + Math.max(14, hs - 2) + '"/></w:rPr></w:style>'
    + '<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="' + Math.round(after / 3) + '"/><w:contextualSpacing/></w:pPr></w:style>'
    + '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr><w:color w:val="1D4ED8"/><w:u w:val="single"/></w:rPr></w:style></w:styles>';
  const lvls = fmt => [0, 1, 2, 3].map(n => '<w:lvl w:ilvl="' + n + '"><w:start w:val="1"/><w:numFmt w:val="' + fmt + '"/><w:lvlText w:val="' + (fmt === 'bullet' ? '•' : '%' + (n + 1) + '.') + '"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="' + 360 * (n + 1) + '" w:hanging="360"/></w:pPr></w:lvl>').join('');
  const numbering = WDX_HEAD_XML + '<w:numbering ' + WDX_NS + '><w:abstractNum w:abstractNumId="0">' + lvls('bullet') + '</w:abstractNum><w:abstractNum w:abstractNumId="1">' + lvls('decimal') + '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
    + nums.map((s, k) => '<w:num w:numId="' + (k + 2) + '"><w:abstractNumId w:val="1"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="' + s + '"/></w:lvlOverride></w:num>').join('') + '</w:numbering>';
  const docRels = WDX_HEAD_XML + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="' + WDX_R + '/styles" Target="styles.xml"/><Relationship Id="rId2" Type="' + WDX_R + '/numbering" Target="numbering.xml"/>'
    + rels.map(([id, h]) => '<Relationship Id="' + id + '" Type="' + WDX_R + '/hyperlink" Target="' + wdxX(h) + '" TargetMode="External"/>').join('') + '</Relationships>';
  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  const core = WDX_HEAD_XML + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>' + wdxX(title) + '</dc:title><dcterms:created xsi:type="dcterms:W3CDTF">' + now + '</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">' + now + '</dcterms:modified></cp:coreProperties>';
  const types = WDX_HEAD_XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
    + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    + '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>';
  const pkg = WDX_HEAD_XML + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="' + WDX_R + '/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>';
  const te = new TextEncoder();
  const zip = wkeZip([['[Content_Types].xml', types], ['_rels/.rels', pkg], ['docProps/core.xml', core], ['word/document.xml', doc], ['word/styles.xml', styles],
    ['word/numbering.xml', numbering], ['word/_rels/document.xml.rels', docRels]].map(([name, s]) => ({name, data: te.encode(s)})));
  return new Blob([zip], {type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});
}

// ---- PDF: the browser's print of the page alone ---------------------------------------------------------------------
function wdxPrint(p) {
  document.querySelector('.wdxprint')?.remove();
  const box = document.createElement('div'), st = wdxStyle(p.space), title = String(p.path || '').split('/').pop();
  box.className = 'wdxprint' + (st ? ' wkst-' + st : '');
  const h = document.createElement('h1'); h.textContent = title;
  const md = wdxDom(p); md.className = 'md ntmd wkmd';
  if (!wdxDupTitle(md, title)) box.append(h);
  box.append(document.importNode(md, true));
  document.body.append(box); document.body.classList.add('wdxprinting');
  const done = () => { document.body.classList.remove('wdxprinting'); box.remove(); window.removeEventListener('afterprint', done); };
  window.addEventListener('afterprint', done);
  setTimeout(() => { window.print(); setTimeout(() => { if (!matchMedia('print').matches) done(); }, 60000); }, 50);  // Safari (iPhone) returns before the sheet closes: afterprint or a minute
}

// the page's "…": PDF / Word of a page in a space with the lock (wiki.js wk_docItems)
async function wdx_local(p, fmt) {
  const sp = p.space;
  if (typeof wkeReady === 'function' && !wkeReady(sp)) { if (!await e2eEnsure()) return; await wkeKeys(sp, true); }
  if (typeof wkeReady === 'function' && !wkeReady(sp)) throw wkeErrLocked();
  if (fmt === 'pdf') { wdxPrint(p); return; }
  wkeSave(wdxDocx(p), wdxName(p, 'docx'));
}
