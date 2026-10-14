/* Kalmido web client: copying a chat message with its formatting.
   2.41.0 (#1374): "Copy" in the menu of a chat message puts the rendered message on the clipboard as text/html (headings,
   bold / italic, lists, tables, links, code blocks) AND as readable text/plain; the program it goes into picks one (mail,
   Word, Pages, Google Docs take the formatting, a plain editor the text). The HTML is rebuilt from scratch: only plain
   tags with simple inline styles, no app classes, buttons, avatars or anchor links; dark text without a page background,
   so it never lands white on white (the app's dark mode does not travel along). "Copy as Markdown" keeps the raw text.
   Without ClipboardItem (an http address, an older browser): a hidden rendered copy is selected and execCommand('copy')
   takes it, the copy event carries both types; when that fails too, the plain text alone (clipCopy). */

// closing blocks and host notes an agent's answer may still carry (hosts normally strip the blocks before posting):
// ```suggest / ```approval (```freigabe) / ```approval-done at the end, the numbered "Next: 1) …" line of a host without
// answer buttons, the host's note about a missing approval card. None of it belongs into a copy.
const RCP_TAIL_KINDS = /^```(?:suggest|approval|freigabe|approval-done|freigabe-erledigt)(?:[ \t][^\n]*)?$/;
const RCP_NEXT = /(?:^|\n)[ \t]*(?:Next|Weiter mit):[ \t]+1\)?[ \t][^\n]*$/;
const RCP_NOTE = /(?:^|\n)[ \t]*_(?:Note from the launcher|Hinweis vom (?:Starter|Dienst)):[^\n]*_[ \t]*$/;
function rcpClean(text) {
  let t = String(text || '').replace(/\s+$/, '');
  for (let k = 0; k < 8; k++) {
    const before = t, lines = t.split('\n');
    if (lines.length >= 2 && lines[lines.length - 1].trim() === '```') {
      let j = lines.length - 2;
      while (j >= 0 && !lines[j].startsWith('```')) j--;
      if (j >= 0 && RCP_TAIL_KINDS.test(lines[j])) t = lines.slice(0, j).join('\n');
    }
    t = t.replace(RCP_NEXT, '').replace(RCP_NOTE, '').replace(/\s+$/, '');
    if (t === before) break;
  }
  return t;
}

const RCP_MONO = "font-family:Menlo,Consolas,'Courier New',monospace;font-size:13px;color:#1f2328";
const RCP_CELL = 'border:1px solid #d0d7de;padding:4px 8px;color:#1f2328;vertical-align:top';
const RCP_ROOT = "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1f2328";
// rendered tag -> [tag in the copy, inline style]; the app renders # as h4 .. ###+ as h6 (small in a bubble), the copy
// takes h2 .. h4
const RCP_TAGS = {
  H1: ['h2', 20], H2: ['h2', 20], H3: ['h2', 20], H4: ['h2', 20], H5: ['h3', 17], H6: ['h4', 15],
  P: ['p', 'margin:0 0 10px'], BR: ['br', ''], B: ['b', ''], STRONG: ['b', ''], I: ['i', ''], EM: ['i', ''], S: ['s', ''], DEL: ['s', ''],
  CODE: ['code', RCP_MONO + ';background:#f2f3f5;padding:1px 4px;border-radius:3px'],
  UL: ['ul', 'margin:0 0 10px;padding-left:24px'], OL: ['ol', 'margin:0 0 10px;padding-left:24px'], LI: ['li', 'margin:2px 0'],
  TABLE: ['table', 'border-collapse:collapse;margin:0 0 10px'], THEAD: ['thead', ''], TBODY: ['tbody', ''], TR: ['tr', ''],
  TH: ['th', RCP_CELL + ';background:#f6f8fa;font-weight:600;text-align:left'], TD: ['td', RCP_CELL],
  BLOCKQUOTE: ['blockquote', 'margin:0 0 10px;padding:0 0 0 12px;border-left:3px solid #d0d7de;color:#57606a'],
  HR: ['hr', 'border:0;border-top:1px solid #d0d7de;margin:12px 0'],
  A: ['a', 'color:#0b57d0;text-decoration:underline'],
};
const RCP_DROP = new Set(['BUTTON', 'SVG', 'svg', 'IMG', 'PICTURE', 'VIDEO', 'AUDIO', 'SCRIPT', 'STYLE', 'TEMPLATE', 'IFRAME', 'OBJECT', 'SELECT', 'TEXTAREA']);
function rcpWalk(from, to) {
  for (const n of from.childNodes) {
    if (n.nodeType === 3) { to.appendChild(document.createTextNode(n.nodeValue)); continue; }
    if (n.nodeType !== 1) continue;
    const tag = n.nodeName;
    if (tag === 'INPUT') { if (n.type === 'checkbox') to.appendChild(document.createTextNode(n.checked ? '[x] ' : '[ ] ')); continue; }
    if (RCP_DROP.has(tag)) continue;  // copy buttons of code blocks, pictures, controls
    if (tag === 'PRE') {  // a code block: its text only (no highlighting spans)
      const p = document.createElement('pre');
      p.setAttribute('style', RCP_MONO + ';line-height:1.45;background:#f6f8fa;border:1px solid #d0d7de;border-radius:6px;padding:10px 12px;margin:0 0 10px;white-space:pre-wrap');
      p.textContent = n.textContent; to.appendChild(p); continue;
    }
    const m = RCP_TAGS[tag];
    if (!m) { rcpWalk(n, to); continue; }  // div / span wrappers: only their content
    let st = m[1];
    if (typeof st === 'number') st = `font-size:${st}px;font-weight:600;line-height:1.3;margin:16px 0 8px;color:#1f2328`;
    if (tag === 'A') {
      const h = n.getAttribute('href') || '';
      if (!/^(https?:|mailto:)/i.test(h)) { rcpWalk(n, to); continue; }  // links inside the app (#t/12) stay text
    }
    const e = document.createElement(m[0]);
    if (tag === 'A') e.setAttribute('href', n.getAttribute('href'));
    if (tag === 'OL' && n.getAttribute('start')) e.setAttribute('start', n.getAttribute('start'));
    if ((tag === 'TD' || tag === 'TH') && /\bta-([cr])\b/.test(n.className)) st += n.className.includes('ta-c') ? ';text-align:center' : ';text-align:right';
    if ((tag === 'UL' || tag === 'OL') && to.nodeName === 'LI') st = 'margin:0;padding-left:24px';  // a nested list
    if (st) e.setAttribute('style', st);
    rcpWalk(n, e); to.appendChild(e);
  }
  return to;
}
// the Markdown text -> the cleaned element (root div with the base style)
function rcpRender(md) {
  const src = document.createElement('div'); src.innerHTML = renderMd(md, true);
  const out = document.createElement('div'); out.setAttribute('style', RCP_ROOT);
  return rcpWalk(src, out);
}
// the readable plain text of the cleaned element: no Markdown signs, lists with "- " / "1. ", table cells with tabs,
// a link's address in brackets after its text
function rcpPlain(root) {
  const inl = n => {
    if (n.nodeType === 3) return n.nodeValue;
    if (n.nodeType !== 1 || n.nodeName === 'UL' || n.nodeName === 'OL') return '';
    if (n.nodeName === 'BR') return '\n';
    const t = [...n.childNodes].map(inl).join('');
    if (n.nodeName === 'A') { const h = n.getAttribute('href') || ''; return h && h !== t && h.replace(/^mailto:/, '') !== t ? `${t} (${h})` : t; }
    return t;
  };
  const list = (l, d) => [...l.children].map((li, i) => '  '.repeat(d) + (l.nodeName === 'OL' ? `${(+l.getAttribute('start') || 1) + i}. ` : '- ')
    + inl(li).trim() + '\n' + [...li.children].filter(x => x.nodeName === 'UL' || x.nodeName === 'OL').map(x => list(x, d + 1)).join('')).join('');
  let out = '';
  for (const n of root.childNodes) {
    if (n.nodeType === 3) { out += n.nodeValue; continue; }
    const tag = n.nodeName;
    if (tag === 'PRE') out += n.textContent + '\n\n';
    else if (tag === 'UL' || tag === 'OL') out += list(n, 0) + '\n';
    else if (tag === 'TABLE') out += [...n.querySelectorAll('tr')].map(r => [...r.children].map(c => inl(c).trim()).join('\t')).join('\n') + '\n\n';
    else if (tag === 'BLOCKQUOTE') out += inl(n).split('\n').map(x => '> ' + x).join('\n') + '\n\n';
    else if (tag === 'HR') out += '----------\n\n';
    else out += inl(n).trim() + '\n\n';
  }
  return out.replace(/\n{3,}/g, '\n\n').trim();
}
// the formatted copy of a Markdown text: true = on the clipboard (with formatting or, as the last way, plain)
async function rcpCopy(md) {
  const box = rcpRender(md), html = box.outerHTML, text = rcpPlain(box);
  try {
    if (typeof ClipboardItem === 'function' && navigator.clipboard?.write) {
      await navigator.clipboard.write([new ClipboardItem({'text/html': new Blob([html], {type: 'text/html'}), 'text/plain': new Blob([text], {type: 'text/plain'})})]);
      return true;
    }
  } catch { /* blocked: the old way */ }
  const back = document.activeElement, sel = window.getSelection?.(), host = document.createElement('div');
  host.className = 'cliptmp rcptmp'; host.setAttribute('aria-hidden', 'true'); host.innerHTML = html;
  document.body.appendChild(host);
  const put = e => { if (!e.clipboardData) return; e.clipboardData.setData('text/html', html); e.clipboardData.setData('text/plain', text); e.preventDefault(); };
  document.addEventListener('copy', put, true);
  let ok = false;
  try { const r = document.createRange(); r.selectNodeContents(host); sel?.removeAllRanges(); sel?.addRange(r); ok = !!document.execCommand?.('copy'); } catch { ok = false; }
  document.removeEventListener('copy', put, true); sel?.removeAllRanges(); host.remove(); back?.focus?.({preventScroll: true});
  return ok || clipCopy(text);
}
