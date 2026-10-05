/* Kalmido web client: Attachments, Paperless documents and the share target.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ attachments
// 2.13.0: versioned by its size, so a repaired / replaced file gets a new address (no stale cached broken answer)
// 2.13.1 (#465): chat files bring their own address (a.url, /api/chat-files/<id>)
const attUrl = (a, dl) => `${a.url || '/api/attachments/' + encodeURIComponent(a.id)}?v=${encodeURIComponent(a.size ?? 0)}${dl ? '&dl=1' : ''}`;
const fmtSize = b => b < 1024 ? b + ' B' : b < 1048576 ? Math.round(b / 1024) + ' KB' : (b / 1048576).toFixed(1).replace('.', ',') + ' MB';
const isImg = a => /^image\/(png|jpeg|gif|webp|avif|bmp)$/.test(a.mime);
// 2.13.0: an image that cannot be loaded (the file is missing / empty on the server) becomes a file tile that says so,
// not a broken-image icon
document.addEventListener('error', e => {
  const img = e.target; if (img?.tagName !== 'IMG' || !img.closest?.('.att.img')) return;
  const box = img.closest('.att.img'), a = img.closest('a');
  box.classList.replace('img', 'file'); box.classList.add('broken');
  if (a) a.innerHTML = `${ic('file')}<span class="an">${esc(img.alt || '')}</span><span class="as">${esc(tr('File damaged or missing'))}</span>`;
}, true);
function attHtml(a) {
  const t = taskById(S.sel), sending = (t?.paperless || []).some(p => p.status === 'pending' && p.att_id === a.id);
  const del = !canEdit(t) ? '' : `<button class="attdel" data-act="att-del" data-att="${a.id}" title="${tr('Remove')}">${ic('x', 's')}</button>` +
    (plOn() ? `<button class="attpl ${sending ? 'busy' : ''}" data-act="att-pl" data-att="${a.id}" title="${sending ? tr('being sent to Paperless') : tr('File in Paperless')}">${ic('archive', 's')}</button>` : '');
  if (isImg(a)) return `<div class="att img"><a href="${attUrl(a)}" data-act="att-view" data-att="${a.id}" title="${esc(a.name)}"><img src="${attUrl(a)}" loading="lazy" alt="${esc(a.name)}"></a>${del}</div>`;
  const pdf = a.mime === 'application/pdf';
  if (a.size === 0) return `<div class="att file broken"><span class="attx">${ic('file')}<span class="an">${esc(a.name)}</span><span class="as">${esc(tr('File damaged or missing'))}</span></span>${del}</div>`;  // 2.13.2 (#478 N6): an old 0-byte file says so
  return `<div class="att file"><a href="${attUrl(a, !pdf)}" ${pdf ? 'target="_blank" rel="noopener"' : 'download'} title="${esc(a.name)}">${ic(pdf ? 'pdf' : 'file')}<span class="an">${esc(a.name)}</span><span class="as">${fmtSize(a.size)}</span></a>${del}</div>`;
}
// 2.1.0 (#180): several Paperless connections (S.paperless.conns: id 0 = the server's legacy one, server ones with my own
// token, my personal ones); only usable ones (my token set) can search / link / show thumbnails
const plConns = () => (S.paperless?.conns || []).filter(c => c.usable);
const plConn = id => (S.paperless?.conns || []).find(c => c.id === (id || 0));
const plQ = id => `?conn=${encodeURIComponent(id || 0)}`;
function plHtml(p) {
  // a document of a connection I cannot use: I only see that there is one
  const cn = !p.hidden && plConn(p.conn);
  if (p.hidden || !plOn() || !cn?.usable) return `<div class="plink">${ic('archive')}<div class="pt"><b>${tr('Paperless document')}</b><span>${tr('Linked through a Paperless connection you cannot use')}</span></div></div>`;
  const x = !canEdit(taskById(S.sel)) ? '' : `<button class="attdel" data-act="pl-del" data-pl="${esc(p.id)}" title="${tr('Remove link')}">${ic('x', 's')}</button>`;
  if (p.status === 'pending') return `<div class="plink pending"><span class="spin"></span><div class="pt"><b>${esc(p.title)}</b><span>${tr('Paperless is processing the document…')}</span></div></div>`;
  if (p.status === 'error') return `<div class="plink err">${ic('archive')}<div class="pt"><b>${esc(p.title)}</b><span>${esc(p.message || tr('Error'))}</span></div>${x}</div>`;
  const sub = [plConns().length > 1 ? cn.name : '', p.correspondent, p.created ? fmtDate(p.created) : '', p.message].filter(Boolean).join(' · ');
  const doc = encodeURIComponent(p.doc_id);
  return `<div class="plink"><a href="${esc(cn.url)}/documents/${doc}/details" target="_blank" rel="noopener"><img src="/api/paperless/thumb/${doc}${plQ(cn.id)}" loading="lazy" alt=""><div class="pt"><b>${esc(p.title)}</b><span>${esc(sub)}</span></div></a>${x}</div>`;
}
// pick a connection when more than one is usable (menu at the anchor); resolves the id or null
function plPick(anchor) {
  const cs = plConns();
  if (cs.length < 2) return Promise.resolve(cs[0]?.id ?? null);
  return new Promise(res => {
    let done = false;
    menu(anchor, cs.map(c => ({label: c.name, icon: 'archive', fn: () => { done = true; res(c.id); }})));
    popOnClose = () => setTimeout(() => { if (!done) res(null); }, 0);  // closed without a pick
  });
}
function plSearchModal(taskId, o = {}) {  // 2.7.1 (#410): o.pick(doc, conn) + o.linked ('conn:doc') = the list's documents
  const cs = plConns();
  let conn = cs.some(c => c.id === +LS.get('plConn', -1)) ? +LS.get('plConn', -1) : cs[0]?.id ?? 0;
  const md = modal(`<h3>${tr('Link Paperless document')}</h3>
    ${cs.length > 1 ? `<div class="row plconn"><label for="pl-conn">${tr('Connection')}</label><select id="pl-conn">${cs.map(c => `<option value="${c.id}" ${c.id === conn ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></div>` : ''}
    <input id="pl-q" placeholder="${tr('Search: title, content, correspondent')}" autocomplete="off" enterkeyhint="search" style="width:100%">
    <div class="muted" id="pl-info" style="font-size:var(--fs-s);margin:.5rem 2px">${tr('Recently added')}</div>
    <div class="plres" id="pl-res"><div class="muted" style="padding:.75rem">${tr('Loading…')}</div></div>
    <div class="foot"><a class="btn" id="pl-open" href="${esc(plConn(conn)?.url || '')}" target="_blank" rel="noopener">${ic('archive', 's')} ${tr('Open Paperless')}</a><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('plmodal');
  const linked = () => o.linked ? new Set([...o.linked].filter(k => k.startsWith(conn + ':')).map(k => +k.split(':')[1])) : new Set((taskById(taskId)?.paperless || []).filter(p => (p.conn || 0) === conn).map(p => p.doc_id));
  let timer, seq = 0;
  const run = async q => {
    const my = ++seq, ln = linked();
    try {
      const j = await api('GET', `/api/paperless/search${plQ(conn)}&q=${encodeURIComponent(q)}`);
      if (my !== seq) return;
      $('#pl-info', md).textContent = q ? trn('{0} result', '{0} results', j.count) : tr('Recently added');
      $('#pl-res', md).innerHTML = j.items.map(d => `<button class="plitem ${ln.has(d.id) ? 'on' : ''}" data-doc="${d.id}"><img src="/api/paperless/thumb/${d.id}${plQ(conn)}" loading="lazy" alt=""><div class="pt"><b>${esc(d.title)}</b><span>${esc([d.correspondent, d.created ? fmtDate(d.created) : '', d.pages ? trn('{0} page', '{0} pages', d.pages) : ''].filter(Boolean).join(' · '))}</span>${d.snippet ? `<small>${esc(d.snippet)}</small>` : ''}</div>${ln.has(d.id) ? ic('check', 's') : ''}</button>`).join('') || `<div class="muted" style="padding:.75rem">${tr('Nothing found.')}</div>`;
    } catch (e) { if (my === seq) $('#pl-res', md).innerHTML = `<div class="muted" style="padding:.75rem">${esc(e.message)}</div>`; }
  };
  run('');
  $('#pl-q', md).addEventListener('input', e => { clearTimeout(timer); timer = setTimeout(() => run(e.target.value.trim()), 250); });
  $('#pl-conn', md)?.addEventListener('change', e => { conn = +e.target.value; LS.set('plConn', conn); $('#pl-open', md).href = plConn(conn)?.url || ''; run($('#pl-q', md).value.trim()); });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-doc]'); if (!b) return;
    if (b.classList.contains('on')) { toast(tr('Already linked')); return; }
    if (o.pick) { try { await o.pick(+b.dataset.doc, conn); } catch { return; } md.remove(); toast(tr('Linked')); return; }
    const t = await api('POST', `/api/tasks/${taskId}/paperless`, {doc_id: +b.dataset.doc, conn});
    putTask(t); md.remove(); render(); if (S.sel === taskId) renderDetail(); toast(tr('Linked'));
  });
  if (!isMobile()) setTimeout(() => $('#pl-q', md).focus(), 50);
}
// 2.13.2 (#478 N6): a 0-byte file is never sent (the server refuses it too): a clear message instead of a broken tile
function noEmpty(files) {
  files = [...files].filter(Boolean);
  const e = files.find(f => f.size === 0);
  if (e) toast(tr('{0}: the file is empty and was not uploaded', e.name || tr('Image')));
  return files.filter(f => f.size !== 0);
}
async function uploadFiles(taskId, files) {
  files = noEmpty(files);
  if (!files.length) return;
  if (taskId < 0) { toast(tr('Task is still syncing, try again in a moment')); return; }
  if (!canEdit(taskById(taskId))) { roToast(); return; }
  const max = 50 * 1024 * 1024, big = files.find(f => f.size > max);
  if (big) { toast(tr('{0} is larger than 50 MB', big.name)); return; }
  const fd = new FormData();
  files.forEach((f, i) => fd.append('file', f, f.name || `bild-${Date.now()}-${i}.png`));
  toast(files.length === 1 ? tr('Uploading…') : tr('Uploading {0} files…', files.length));
  try {
    const t = await api('POST', `/api/tasks/${taskId}/attachments`, fd);
    putTask(t); render(); if (S.sel === taskId) renderDetail();
    toast(files.length === 1 ? tr('Attached') : tr('{0} files attached', files.length));
  } catch (e) { /* api() already showed the error / offline notice */ }
}
function attLightbox(id, list) {
  const t = taskById(S.sel), imgs = list || (t?.attachments || []).filter(isImg);
  let i = Math.max(0, imgs.findIndex(a => a.id === id));
  const m = document.createElement('div');
  m.className = 'lightbox';
  const draw = () => { const a = imgs[i]; m.innerHTML = `<img src="${attUrl(a)}" alt="${esc(a.name)}"><div class="lbbar"><span>${esc(a.name)} · ${fmtSize(a.size)}</span><span class="spacer"></span>${imgs.length > 1 ? `<button data-lb="-1">${ic('left')}</button><button data-lb="1">${ic('right')}</button>` : ''}<a href="${attUrl(a, true)}" download title="${tr('Download')}">${ic('download')}</a><button data-lb="x" title="${tr('Close')}">${ic('x')}</button></div>`; };
  draw();
  m.addEventListener('click', e => {
    const b = e.target.closest('[data-lb]');
    if (b && b.dataset.lb !== 'x') { i = (i + +b.dataset.lb + imgs.length) % imgs.length; draw(); return; }
    if (b || e.target === m || e.target.tagName === 'IMG') m.remove();
  });
  document.body.appendChild(m);
}
function depthOf(t) { let n = 0, p = t; while (p && p.parent_id && n < 5) { p = S.tasks.get(p.parent_id); n++; } return n; }
// small, safe markdown: everything is escaped first, only whitelisted inline / block syntax is turned into html
// Tokenized: code spans, [label](url) links and bare links are cut out of the RAW text first, so no later
// rule can ever run inside an href (the old regex chain let a bare link inside a markdown link's URL
// break out of the attribute). URLs: http(s) / mailto only, no quotes, brackets, parentheses or spaces.
const MD_URL = String.raw`(?:https?:\/\/|mailto:)[^\s"'<>()\[\]\x60\\]+`;
const MD_TOK = new RegExp(String.raw`\x60([^\x60]+)\x60|\[([^\[\]]+)\]\((${MD_URL})\)|(^|[\s(])(https?:\/\/[^\s"'<>()\[\]\x60\\]+)`, 'g');
const mdSafeUrl = u => /^(https?:\/\/[^\s"'<>()\[\]`\\]+|mailto:[^\s"'<>()\[\]`\\]+)$/i.test(u) ? u : null;
const mdLink = (url, label) => `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
function mdFmt(t) {  // escaped text only (no attributes are produced here)
  return esc(t)
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, '$1<i>$2</i>')
    .replace(/~~([^~]+)~~/g, '<s>$1</s>');
}
// 2.18.0 review (R6): backslash escapes as in standard Markdown ("\*" = a literal *, e.g. in error-report tickets): the
// escaped character becomes a private-use placeholder before any rule runs and is put back (escaped) at the end; inside
// code spans the backslash stays, as in standard Markdown
const MD_ESC_RE = /\\([!-\/:-@\[-`{-~])/g, MD_PH_RE = /[\uE000-\uE07F]/g;
const mdPhBack = s => s.replace(MD_PH_RE, c => '\\' + String.fromCharCode(c.charCodeAt(0) - 0xE000));
function mdInline(s) {
  s = String(s ?? '').replace(MD_PH_RE, '').replace(MD_ESC_RE, (_, c) => String.fromCharCode(0xE000 + c.charCodeAt(0)));
  return mdInline1(s).replace(MD_PH_RE, c => esc(String.fromCharCode(c.charCodeAt(0) - 0xE000)));
}
function mdInline1(s) {
  let out = '', last = 0, m;
  const fmt = MD_REPO ? mdFileLinks : mdFmt;  // 2.18.0 (#408 G): src/app.py:42 -> the file in the list's repository
  MD_TOK.lastIndex = 0;
  while ((m = MD_TOK.exec(s))) {
    let rep;
    if (m[1] !== undefined) { m[1] = mdPhBack(m[1]); const fu = MD_REPO && mdFileUrl(m[1].trim()); rep = fu ? mdLink(fu, `<code>${esc(m[1])}</code>`) : `<code>${esc(m[1])}</code>`; }
    else if (m[2] !== undefined) { const u = mdSafeUrl(m[3]); rep = u ? mdLink(u, mdFmt(m[2])) : mdFmt(m[0]); }
    else {
      let u = m[5], tail = '';
      const tp = u.match(/[.,;:!?]+$/);  // sentence punctuation after a bare link is not part of it
      if (tp) { tail = tp[0]; u = u.slice(0, -tail.length); }
      rep = esc(m[4]) + (mdSafeUrl(u) ? mdLink(u, esc(u)) : esc(u)) + esc(tail);
    }
    out += fmt(s.slice(last, m.index)) + rep;
    last = MD_TOK.lastIndex;
    if (m[0] === '') MD_TOK.lastIndex++;
  }
  return out + fmt(s.slice(last));
}
// ---- 2.18.0 (#408 G): file:line references -> links into the list's repository (its first one, default branch).
// Conservative: a path of word characters with a known source file extension, optionally :line or :from-to, never right
// after a letter / slash / colon (so no URLs, no absolute paths, no times like 12:30, no "e.g.").
let MD_REPO = null;  // set by renderMd while it renders the text of a list that has a repository
const MD_FILE_EXT = 'py|pyi|js|mjs|cjs|jsx|ts|tsx|go|rs|java|kt|kts|c|h|cc|cpp|cxx|hpp|cs|rb|php|swift|scala|sh|bash|zsh|ps1|sql|html|htm|css|scss|sass|less|vue|svelte|json|jsonc|yaml|yml|toml|ini|cfg|conf|xml|md|txt|rst|lock|gradle|proto|graphql|tf|lua|pl|r|dart|ex|exs|erl|hs|ml|clj|el|vim|env|mk|cmake|dockerfile';
const MD_FILE_PATH = String.raw`((?:\.\/)?(?:[\w.-]+\/)*[\w-][\w.-]*\.(?:${MD_FILE_EXT}))(?::(\d{1,6})(?:-(\d{1,6}))?)?`;
const MD_FILE_RE = new RegExp(String.raw`(^|[\s(\[{,;"'])${MD_FILE_PATH}(?=$|[\s)\]},;:.!?"'])`, 'gi');
const MD_FILE_ONE = new RegExp(`^${MD_FILE_PATH}$`, 'i');
function mdFileUrl(ref) {  // "src/app.py:42" (the whole string, e.g. inline code) -> the URL in MD_REPO, or null
  const m = MD_FILE_ONE.exec(ref);
  return m ? mdRepoFileUrl(MD_REPO, m[1], m[2], m[3]) : null;
}
function mdRepoFileUrl(r, path, a, b) {
  const web = httpUrl(r?.web_url).replace(/\/+$/, ''); if (!web || path.split('/').includes('..')) return null;
  const br = (r.default_branch || 'main').split('/').map(encodeURIComponent).join('/');
  const p = path.replace(/^\.\//, '').split('/').map(encodeURIComponent).join('/');
  const pv = String(r.provider || 'github').toLowerCase();
  const ln = !a ? '' : pv === 'bitbucket' ? `#lines-${a}${b ? ':' + b : ''}` : pv === 'gitlab' ? `#L${a}${b ? '-' + b : ''}` : `#L${a}${b ? '-L' + b : ''}`;
  return pv === 'gitlab' ? `${web}/-/blob/${br}/${p}${ln}` : pv === 'bitbucket' ? `${web}/src/${br}/${p}${ln}`
    : pv === 'gitea' || pv === 'forgejo' ? `${web}/src/branch/${br}/${p}${ln}` : `${web}/blob/${br}/${p}${ln}`;
}
function mdFileLinks(t) {  // like mdFmt, with the file references as links (every part escaped)
  let out = '', last = 0, m;
  MD_FILE_RE.lastIndex = 0;
  while ((m = MD_FILE_RE.exec(t))) {
    // plain text: a bare file name only with a line (app.js:10, not "Node.js"); never a domain-like first part (site.com/a.html)
    if ((!m[2].includes('/') && !m[3]) || /^[\w-]+\.[a-z]{2,}\//i.test(m[2])) continue;
    const u = mdRepoFileUrl(MD_REPO, m[2], m[3], m[4]), at = m.index + m[1].length;
    if (!u) continue;
    out += mdFmt(t.slice(last, at)) + mdLink(u, esc(t.slice(at, MD_FILE_RE.lastIndex)));
    last = MD_FILE_RE.lastIndex;
  }
  return out + mdFmt(t.slice(last));
}
// ---- 2.18.0 (#408 G): syntax highlighting of fenced code blocks: a small tokenizer per language family (comments,
// strings, numbers, keywords; diff lines). Safe: every token is escaped, only fixed <span class> wrappers are added.
const HL_JS = 'async await break case catch class const continue debugger default delete do else export extends finally for from function get if import in instanceof let new of return set static super switch this throw try typeof var void while with yield true false null undefined';
const HL_KW = {
  js: HL_JS, ts: HL_JS + ' interface type enum implements private public protected readonly declare namespace abstract as keyof never unknown any string number boolean',
  py: 'and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case True False None self',
  sh: 'if then else elif fi for while until do done case esac function in return local export exit set unset readonly source echo cd',
  go: 'break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var true false nil',
  rust: 'as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while',
  java: 'abstract boolean break byte case catch char class const continue default do double else enum extends final finally float for fun if implements import instanceof int interface long new null package private protected public return short static super switch this throw throws try val var void volatile when while true false',
  c: 'auto bool break case char class const constexpr continue default delete do double else enum extern false float for goto if inline int long namespace new nullptr NULL private protected public register return short signed sizeof static struct switch template this true typedef typename union unsigned using virtual void volatile while',
  sql: 'select from where and or not insert into values update set delete create table alter drop index view join left right inner outer full cross on as group by order having limit offset null is in like between distinct union all primary key foreign references default exists case when then else end returning with asc desc count sum avg min max',
  yaml: 'true false null yes no on off', json: 'true false null', css: 'important',
};
const HL_ALIAS = {javascript: 'js', jsx: 'js', mjs: 'js', cjs: 'js', node: 'js', typescript: 'ts', tsx: 'ts', python: 'py', py3: 'py',
  bash: 'sh', shell: 'sh', zsh: 'sh', console: 'sh', shellsession: 'sh', golang: 'go', rs: 'rust', kotlin: 'java', kt: 'java',
  cpp: 'c', 'c++': 'c', h: 'c', hpp: 'c', cc: 'c', cs: 'c', csharp: 'c', objc: 'c', yml: 'yaml', toml: 'yaml', ini: 'yaml',
  xml: 'html', svg: 'html', htm: 'html', vue: 'html', scss: 'css', less: 'css', patch: 'diff', postgres: 'sql', sqlite: 'sql', mysql: 'sql', jsonc: 'json'};
const HL_MAX = 20000;  // longer blocks stay plain (fast on phones)
const HL_RE = {};
function hlRe(k) {
  if (HL_RE[k]) return HL_RE[k];
  const cm = ['js', 'ts', 'go', 'rust', 'java', 'c'].includes(k) ? String.raw`\/\/[^\n]*|\/\*[\s\S]*?\*\/` : k === 'css' ? String.raw`\/\*[\s\S]*?\*\/`
    : k === 'sql' ? String.raw`--[^\n]*|\/\*[\s\S]*?\*\/` : ['py', 'sh', 'yaml'].includes(k) ? String.raw`#[^\n]*` : '(?!)';
  const st = (k === 'py' ? String.raw`"""[\s\S]*?"""|'''[\s\S]*?'''|` : '') + (['js', 'ts', 'go'].includes(k) ? String.raw`\x60(?:\\[\s\S]|[^\x60\\])*\x60|` : '')
    + String.raw`"(?:\\.|[^"\\\n])*"` + (['json', 'rust'].includes(k) ? '' : String.raw`|'(?:\\.|[^'\\\n])*'`);
  const num = String.raw`\b(?:0[xX][\da-fA-F_]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\b`;
  return (HL_RE[k] = new RegExp(`(${cm})|(${st})|(${num})|([A-Za-z_$][\\w$]*)`, 'g'));
}
const hlSpan = (c, t) => `<span class="hl-${c}">${esc(t)}</span>`;
function hlCode(code, lang) {
  const k = HL_ALIAS[lang] || lang;
  if (!k || code.length > HL_MAX) return esc(code);
  if (k === 'diff') return code.split('\n').map(l => /^(\+\+\+|---) /.test(l) || /^@@/.test(l) ? hlSpan('m', l) : l[0] === '+' ? hlSpan('add', l) : l[0] === '-' ? hlSpan('del', l) : esc(l)).join('\n');
  if (k === 'html') {
    return code.replace(/(<!--[\s\S]*?-->)|(<\/?[A-Za-z][\w:.-]*|\/?>)|("[^"\n]*"|'[^'\n]*')|([\w:-]+)(?==)|([^<"'\w]+|[\s\S])/g,
      (m, c, t, s2, a) => c ? hlSpan('c', c) : t ? hlSpan('t', t) : s2 ? hlSpan('s', s2) : a ? hlSpan('a', a) : esc(m));
  }
  if (!HL_KW[k]) return esc(code);
  const kw = new Set(HL_KW[k].split(' ')), ci = k === 'sql', re = hlRe(k);
  let out = '', last = 0, m;
  re.lastIndex = 0;
  while ((m = re.exec(code))) {
    if (m[0] === '') { re.lastIndex++; continue; }
    const cls = m[1] ? 'c' : m[2] ? 's' : m[3] ? 'n' : kw.has(ci ? m[4].toLowerCase() : m[4]) ? 'k' : '';
    out += esc(code.slice(last, m.index)) + (cls ? hlSpan(cls, m[0]) : esc(m[0]));
    last = re.lastIndex;
  }
  return out + esc(code.slice(last));
}
function mdCodeBlock(lines, lang) {
  const l = String(lang || '').toLowerCase().replace(/[^\w+#.-]/g, '').slice(0, 20);
  return `<div class="mdcode"><pre class="mdpre"${l ? ` data-lang="${esc(l)}"` : ''}><code>${hlCode(lines.join('\n'), l)}</code></pre><button type="button" class="iconbtn mdcopy" data-mdcopy aria-label="${esc(tr('Copy code'))}" title="${esc(tr('Copy code'))}">${ic('copy', 's')}</button></div>`;
}
function renderMd(src, ro, o = {}) {
  // 2.18.0 (#408 G): o.lid = the list the text belongs to (file:line links into its repository)
  const keep = MD_REPO;
  MD_REPO = o.lid ? listRepos(o.lid).find(r => httpUrl(r.web_url)) || null : null;
  try { return renderMd0(src, ro); } finally { MD_REPO = keep; }
}
function renderMd0(src, ro) {
  // 2.13.4: nested lists (indented items go into the item above) and numbered lists keep counting across nested bullets;
  // a numbered list that starts at n (after a paragraph, "2.") shows n (<ol start>)
  const lines = String(src || '').split('\n');
  let h = '', para = [];
  const stack = [];  // open lists: {tag, ind}; the last <li> of each stays open for nested lists
  const flushPara = () => { if (para.length) { h += `<p>${para.join('<br>')}</p>`; para = []; } };
  const closeList = () => { while (stack.length) h += `</li></${stack.pop().tag}>`; };
  const item = (tag, ln, html, cls = '', num = 1) => {
    const ind = ln.replace(/\t/g, '    ').match(/^ */)[0].length;
    while (stack.length && stack[stack.length - 1].ind > ind) h += `</li></${stack.pop().tag}>`;
    const top = stack[stack.length - 1];
    if (top && top.ind === ind && top.tag !== tag) { h += `</li></${stack.pop().tag}>`; }
    const cur = stack[stack.length - 1];
    if (cur && cur.ind === ind) h += '</li>';
    else { h += `<${tag}${tag === 'ol' && num > 1 ? ` start="${num}"` : ''}>`; stack.push({tag, ind}); }
    h += `<li${cls ? ` class="${cls}"` : ''}>${html}`;
  };
  let code = null, lang = '';  // 2.13.4: ``` fenced code blocks (agents send them): kept as they are, in mono, scrolling
  // sideways; 2.18.0 (#408 G): highlighted by their language (```js), with a Copy button
  lines.forEach((ln, i) => {
    let m;
    if (code !== null) { if (/^\s*```\s*$/.test(ln)) { h += mdCodeBlock(code, lang); code = null; } else code.push(ln); return; }
    if ((m = ln.match(/^\s*```\s*([^\s`]*)/))) { flushPara(); closeList(); code = []; lang = m[1]; return; }
    if ((m = ln.match(/^(#{1,3})\s+(.*)/))) { flushPara(); closeList(); h += `<h${m[1].length + 3}>${mdInline(m[2])}</h${m[1].length + 3}>`; }
    else if ((m = ln.match(/^\s*[-*]\s+\[( |x|X)\]\s*(.*)/))) { flushPara(); item('ul', ln, `<input type="checkbox" ${ro ? 'disabled' : `data-mdline="${i}"`} ${m[1] !== ' ' ? 'checked' : ''}><span>${mdInline(m[2])}</span>`, `cb ${m[1] !== ' ' ? 'on' : ''}`); }
    else if ((m = ln.match(/^\s*[-*•]\s+(.*)/))) { flushPara(); item('ul', ln, mdInline(m[1])); }
    else if ((m = ln.match(/^\s*(\d+)[.)]\s+(.*)/))) { flushPara(); item('ol', ln, mdInline(m[2]), '', +m[1]); }
    else if (!ln.trim()) { flushPara(); closeList(); }
    else { closeList(); para.push(mdInline(ln)); }
  });
  if (code !== null) h += mdCodeBlock(code, lang);
  flushPara(); closeList();
  return h;
}
function autosize(el) { if (!el) return; el.style.height = 'auto'; if (el.scrollHeight) el.style.height = el.scrollHeight + 'px'; }
// base: the value before the edit when the caller already changed the local copy (markdown checkbox)
// 2.13.0 (#453, flaky phone network): typed text (title, description) is saved when the field is left, plus every 5 s
// while typing (and when the app goes to the background), not every 600 ms. Every value this device sent is remembered
// per field (S.sentVals): when the server reports a "conflict" whose current value is one of OUR earlier saves (a save
// that arrived although its answer got lost, a queued replay), it is no conflict: the newest text is sent again on top of
// it. A real conflict (someone else changed the field) never takes the field away while it has the focus: the draft
// stays, an inline bar offers "Keep mine" / "Show the other" / "Merge".
const TEXT_SAVE_MS = 5000;
S.sentVals = {};
const ownVal = (key, v) => (S.sentVals[key] || []).some(x => x === v);
function queueSave(id, field, value, base0) {
  const key = id + ':' + field;
  const old = saveTimers[key], t = taskById(id);
  clearTimeout(old?.t);
  const base = old ? old.base : base0 !== undefined ? base0 : (t ? t[field] : undefined);  // value before this round of typing
  saveTimers[key] = {t: setTimeout(() => doSave(key), field === 'title' || field === 'content' ? TEXT_SAVE_MS : 600), id, field, value, base, sess: HIST.sess};
}
addEventListener('pagehide', () => { flushSaves(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) flushSaves(); });
async function doSave(key, retry) {
  const s = saveTimers[key]; if (!s) return;
  delete saveTimers[key];
  if (s.field === 'title' && !s.value.trim()) return;
  const body = {[s.field]: s.value};
  if (s.base !== undefined && s.id > 0) body._prev = {[s.field]: s.base};
  (S.sentVals[key] ||= []).push(s.value); if (S.sentVals[key].length > 30) S.sentVals[key].shift();
  const lt = S.tasks.get(s.id); if (lt) lt[s.field] = s.value;  // the next round of typing builds on what was just sent
  const t = await api('PATCH', '/api/tasks/' + s.id, body);
  if (t.conflicts?.length) {
    const own = t.conflicts.filter(c => c.field === s.field && ownVal(key, c.server));
    if (own.length === t.conflicts.length && !retry) {  // only our own earlier text: send the newest on top of it
      if (saveTimers[key]) { saveTimers[key].base = own[0].server; return; }  // newer text is waiting: it goes on top of that
      saveTimers[key] = {...s, base: own[0].server, t: 0};
      return doSave(key, true);
    }
    addConflicts(s.id, t.conflicts, t.title);
    const field = $(s.field === 'title' ? '#d-title' : s.field === 'content' ? '#d-content' : null);
    const focused = S.sel === s.id && field && document.activeElement === field;
    const keep = {...t}; if (focused) keep[s.field] = s.value;  // the draft stays where it is typed
    putTask(keep);
    if (focused || (S.sel === s.id && field && field.value === s.value)) cfInline(s.id, s.field, t.conflicts.find(c => c.field === s.field), s.value);
    else if (S.sel === s.id) renderDetail();
    return;
  }
  putTask(t);
  const row = $$(`#view .trow[data-id="${s.id}"] .ttl`); row.forEach(r => { r.textContent = t.title; });
  if (s.base !== undefined) histText(s, t);
}
// typing in the title / description: one history step per field and editing session (focus to blur), not per save
function histText(s, t) {
  const key = s.id + ':' + s.field, top = HIST.undo[HIST.undo.length - 1];
  if (top && top.text === key && top.sess === s.sess && !HIST.redo.length && !t?._q && !(top.q && !top.q.done)) {  // queued saves: own steps (the outbox can cancel them)
    top.pairs[0][1][s.field] = s.value; top.after = [snapTask(S.tasks.get(s.id) || t)]; top.q = t?._q || null;
    top.label = s.field === 'title' ? tr('Renamed {0}', qn(String(s.value).slice(0, 40))) : tr('Description of {0}', qn(String(t.title || '').slice(0, 40)));
    if (!reverseOf(top.pairs[0][0], top.pairs[0][1], [s.field])) { HIST.undo.pop(); }  // typed back to the start: nothing to undo
    renderHist(); return;
  }
  const cur = snapTask(S.tasks.get(s.id) || t); if (!cur) return;
  const before = {...cur, [s.field]: s.base}, after = {...cur, [s.field]: s.value};
  histFields(s.field === 'title' ? tr('Renamed {0}', qn(String(s.value).slice(0, 40))) : tr('Description of {0}', qn(String(cur.title || '').slice(0, 40))),
    [[before, after, [s.field]]], {res: t, text: key, sess: s.sess});
}
document.addEventListener('focusin', e => { if (e.target.id === 'd-title' || e.target.id === 'd-content') HIST.sess++; });
function flushSaves() { return Promise.all(Object.keys(saveTimers).map(k => { clearTimeout(saveTimers[k].t); return doSave(k).catch(() => {}); })); }

// quiet: the caller records the step itself (see shiftUndo, patchUndoable); otherwise the change goes into the history
// (no toast), and tasks moved along with this one (list setting "Move dependent tasks along") get a toast with one undo
// for the whole chain
async function patchTask(id, body, quiet) {
  const before = snapTask(taskById(id));
  const t = await api('PATCH', '/api/tasks/' + id, body);
  putTask(t); render(); if (S.sel === id) renderDetail();
  if (!quiet && before) {
    if (t?.shifted?.length) shiftUndo(before, t, '');
    else histFields(histLabel(before, S.tasks.get(id) || t), [[before, snapTask(S.tasks.get(id) || t)]], {res: t});
  }
  return t;
}
// one step for a date change and the dependent tasks the server moved along with it (t.shifted: [{id, start, due,
// prev_start, prev_due}]); msg = what the change itself was ('' = only the "moved along" part)
function shiftUndo(before, t, msg) {
  const sh = t?.shifted || [];
  if (sh.length) load().then(() => render()).catch(() => {});
  const after = t && snapTask(S.tasks.get(t.id) || t), rev = before && after && reverseOf(before, after, HIST_FIELDS);
  const m = [msg, sh.length ? trn('{0} dependent task moved', '{0} dependent tasks moved', sh.length) : ''].filter(Boolean).join(' · ');
  if (!rev && !sh.length) { if (msg) toast(msg); return; }
  const pairs = [...(rev ? [[before, after, HIST_FIELDS]] : []), ...sh.map(x => [{id: x.id, start: x.prev_start, due: x.prev_due}, {id: x.id, start: x.start, due: x.due}, ['start', 'due']])];
  const e = histFields([before && after ? histLabel(before, after) : '', sh.length ? trn('{0} dependent task moved', '{0} dependent tasks moved', sh.length) : ''].filter(Boolean).join(' · '), pairs, {res: t});
  if (e) histToast(m, e);
}
