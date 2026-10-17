// 2.61.0 (#1820): text recognition of stored files -- the mark at a file ("Text recognised" / "No text found"), the
// search in the file store (names + recognised text, also project files) and the "in file" note of a task search hit.
// The server recognises the text in the background (files/textscan.py); nothing here waits for it.

// ---- the mark at a file (up.text from the serializers; hooked into the marks of the upload checks, attachments.js)
function ftxtMark(up) {
  if (!up || !up.text || typeof scnMark !== 'function') return '';
  if (up.text === 'found') return scnMark('search', tr('Text recognised'), tr('The text of this file was recognised: the search finds it.'), 'ftxtmark');
  if (up.text === 'none') return scnMark('', tr('No text found'), tr('The text recognition found no text in this file.'), 'ftxtmark ftxtnone');
  if (up.text === 'wait') return scnMark('', tr('Recognising text…'), tr('The text of this file is being recognised in the background.'), 'ftxtmark ftxtnone');
  return '';
}
if (typeof scnMakers !== 'undefined') scnMakers.push(ftxtMark);

// ---- the note below a task search hit that only its file's text matched
const ftxtHitHtml = t => t?.file_hit ? `<div class="ftxthit muted">${ic('file', 's')}<span>${esc(tr('Found in the file {0}', t.file_hit))}</span></div>` : '';

// ---- the search in the file store (one field above the list; all spaces the person can see)
const FTXT = {q: '', res: null, seq: 0, timer: 0, busy: false};
const ftxtActive = () => !!FTXT.q.trim();
const ftxtItem = id => (FTXT.res?.items || []).find(x => x.id === +id) || null;
const ftxtBox = () => `<div class="ftxtbar" role="search">${ic('search', 's')}<input id="ftxt-q" type="search" value="${esc(FTXT.q)}" placeholder="${esc(tr('Search files: name or text'))}" aria-label="${esc(tr('Search files: name or text'))}" autocomplete="off" enterkeyhint="search"></div>`;

function ftxtResults() {
  const r = FTXT.res;
  if (!r) return `<p class="muted lempty">${tr('Searching…')}</p>`;
  const items = r.items || [], lfs = r.list_files || [];
  if (!items.length && !lfs.length) return `<div class="empty abempty">${ic('search')}<span>${tr('No results.')}</span></div>`;
  const why = h => h === 'text' ? tr('Found in the text') : '';
  const fsRows = items.map(n => {
    const meta = [why(n.hit), n.folder ? tr('in {0}', n.folder) : ''].filter(Boolean).join(' · ');
    return `<div class="abrow ftxtrow" role="listitem" data-abid="${n.id}"><button type="button" class="abopen" data-ab="open" data-id="${n.id}">${ab_icon(n)}<span class="abtxt"><span class="abname">${esc(n.name)}</span>${meta ? `<span class="abmeta2 muted">${esc(meta)}</span>` : ''}</span></button><span class="abmeta muted">${esc(meta)}</span><span class="abbadges"></span><button type="button" class="iconbtn" data-ab="menu" data-id="${n.id}" aria-label="${esc(tr('More actions for {0}', n.name))}" title="${esc(tr('More'))}">${ic('dots')}</button></div>`;
  }).join('');
  const lfRows = lfs.map(f => {
    const meta = [why(f.hit), tr('Project {0}', f.list_name)].filter(Boolean).join(' · ');
    return `<div class="abrow ftxtrow" role="listitem"><button type="button" class="abopen" data-ftxt-lf="${f.id}">${ic(f.mime === 'application/pdf' ? 'pdf' : /^image\//.test(f.mime || '') ? 'picture' : 'file')}<span class="abtxt"><span class="abname">${esc(f.name)}</span><span class="abmeta2 muted">${esc(meta)}</span></span></button><span class="abmeta muted">${esc(meta)}</span></div>`;
  }).join('');
  return `<div class="ablist" role="list" aria-label="${esc(tr('Search results'))}">${fsRows}${lfs.length ? `<h4 class="ftxth">${tr('Project files')}</h4>` : ''}${lfRows}</div>`;
}

async function ftxtRun() {
  const q = FTXT.q.trim(), seq = ++FTXT.seq;
  if (!q) { FTXT.res = null; ab_draw(); return; }
  try {
    const j = await api('GET', '/api/files/search?q=' + encodeURIComponent(q));
    if (seq !== FTXT.seq) return;
    FTXT.res = j;
  } catch { if (seq === FTXT.seq) FTXT.res = {items: [], list_files: []}; }
  ab_draw();
}
function ftxtSet(q) {
  FTXT.q = q; clearTimeout(FTXT.timer);
  if (!q.trim()) { FTXT.seq++; FTXT.res = null; ab_draw(); return; }
  FTXT.timer = setTimeout(ftxtRun, 250);
}
function ftxtOpenLf(f) {
  const url = `/api/list-files/${f.id}`;
  if (f.mime === 'application/pdf' && typeof pdfView === 'function') { pdfView({url, name: f.name, size: f.size, dlUrl: url + '?dl=1'}); return; }
  if (/^image\//.test(f.mime || '')) { window.open(url, '_blank', 'noopener'); return; }
  const a = document.createElement('a'); a.href = url + '?dl=1'; a.download = f.name; document.body.appendChild(a); a.click(); a.remove();
}
document.addEventListener('input', e => { if (e.target.id === 'ftxt-q') ftxtSet(e.target.value); });
document.addEventListener('keydown', e => { if (e.target.id === 'ftxt-q' && e.key === 'Escape' && FTXT.q) { e.preventDefault(); e.target.value = ''; ftxtSet(''); } });
document.addEventListener('click', e => {
  const lf = e.target.closest?.('[data-ftxt-lf]');
  if (lf) { const f = (FTXT.res?.list_files || []).find(x => x.id === +lf.dataset.ftxtLf); if (f) ftxtOpenLf(f); }
});
document.addEventListener('click', e => {  // capture: opening a folder or another space leaves the search before the view draws
  const b = e.target.closest?.('.abview [data-ab="space"], .abview [data-go^="ablage"]');
  const o = e.target.closest?.('.ftxtrow [data-ab="open"]');
  if ((b || (o && ftxtItem(o.dataset.id)?.kind === 'folder')) && FTXT.q) { FTXT.q = ''; FTXT.res = null; FTXT.seq++; if (!o) setTimeout(ab_draw, 0); }
}, true);
