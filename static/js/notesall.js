/* Kalmido web client: the notes of all lists and projects in one place (2.45.0, #1516).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- #1516: #notes (no list id) = every note I may read: pinned first, then the newest change; the list's name on each card;
// a filter by list / project and a search in title and text (the server's GET /api/notes, the same rights as a list's notes);
// "New note" asks for the list (only lists with notes that I may write in). #notes/<id> stays the notes of one list.
S.sbn = {q: '', lid: 0, hits: null, ex: {}, exLoaded: false, qT: null};
const sb_noteCount = () => (S.notes || []).length;
const sb_noteWritable = () => S.lists.filter(l => !l.archived && notesOn(l) && canEditList(l.id));
const sb_notesShown = () => S.lists.some(l => !l.archived && notesOn(l)) || sb_noteCount() > 0;
function sb_noteExcerpts() {  // the first lines of the newest notes (S.notes has no text)
  if (S.sbn.exLoaded) return;
  S.sbn.exLoaded = true;
  rawFetch('GET', '/api/notes').then(j => { for (const n of j.notes || []) S.sbn.ex[n.id] = n.excerpt; if (S.route.mod === 'notes' && !S.nt.lid) sb_notesPatch(); }).catch(() => { S.sbn.exLoaded = false; });
}
function sb_notesItems() {
  const f = S.sbn.lid;
  if (S.sbn.q.trim()) return S.sbn.hits;  // null = the server is still asked
  return (S.notes || []).filter(n => !f || n.list_id === f).sort((a, b) => (b.pinned - a.pinned) || String(b.updated_at).localeCompare(String(a.updated_at)));
}
function sb_noteCardsHtml() {
  const vis = sb_notesItems(), q = S.sbn.q.trim();
  if (vis === null) return `<div class="muted mhint">${tr('Loading…')}</div>`;
  if (!vis.length) return q || S.sbn.lid ? `<div class="empty">${tr('No notes match.')}</div>` : botEmpty('ruhig', tr('No notes yet.'), sb_noteWritable().length ? tr('Meeting notes, briefings, decisions: write them next to the tasks.') : '');
  return `<ul class="ntcards" aria-label="${esc(tr('Notes'))}">${vis.map(n => {
    const l = listById(n.list_id), ex = n.excerpt ?? S.sbn.ex[n.id] ?? '';
    return `<li><a href="#note/${n.id}" class="ntcard sbncard">
      <span class="ntt">${n.pinned ? `<span class="ntpin" title="${esc(tr('Pinned'))}">${ic('pin', 's')}</span>` : ''}${esc(n.title)}</span>
      ${ex ? `<span class="ntx">${esc(ex.slice(0, 140))}</span>` : ''}
      <span class="ntm"><span class="sbnl">${l ? licMark(l, 'sm', true) : ''}${esc(l ? lname(l) : '?')}</span>${(n.tags || []).map(t => `<span class="tag">#${esc(t)}</span>`).join('')}<time title="${esc(fmtWhen(n.updated_at))}">${esc(relTime(n.updated_at))}</time></span></a></li>`;
  }).join('')}</ul>`;
}
function sb_notesView() {
  sb_noteExcerpts();
  const ids = new Set((S.notes || []).map(n => n.list_id)), ls = S.lists.filter(l => ids.has(l.id) || l.id === S.sbn.lid);
  const opt = l => `<option value="${l.id}" ${l.id === S.sbn.lid ? 'selected' : ''}>${esc(lname(l))}</option>`;
  const prj = ls.filter(l => l.kind === 'project'), oth = ls.filter(l => l.kind !== 'project');
  const sel = ls.length > 1 || S.sbn.lid ? `<select id="sbn-l" class="sbnsel" aria-label="${esc(tr('Project'))}"><option value="0">${tr('All projects')}</option>${prj.length && oth.length ? `<optgroup label="${esc(tr('Projects'))}">${prj.map(opt).join('')}</optgroup><optgroup label="${esc(tr('Other projects'))}">${oth.map(opt).join('')}</optgroup>` : ls.map(opt).join('')}</select>` : '';
  return `<div class="ntwrap"><div class="ntview sbnall"><div class="ntlist">
    <div class="ntbar sbnbar"><div class="ssearch">${ic('search', 's')}<input id="sbn-q" type="search" value="${esc(S.sbn.q)}" placeholder="${esc(tr('Search notes'))}" aria-label="${esc(tr('Search notes'))}" autocomplete="off"></div>${sel}
      ${sb_noteWritable().length ? `<button type="button" class="btn sm pri" data-sb="note-new" aria-haspopup="menu">${ic('plus', 's')}${tr('New note')}</button>` : ''}</div>
    <div id="sbn-res">${sb_noteCardsHtml()}</div></div></div></div>`;
}
function sb_notesPatch() { const r = $('#sbn-res'); if (r) fl_set(r, sb_noteCardsHtml()); }  // 2.46.2 (#1718)
function sb_notesSearch() {
  clearTimeout(S.sbn.qT);
  const q = S.sbn.q.trim(); if (!q) { S.sbn.hits = null; sb_notesPatch(); return; }
  S.sbn.qT = setTimeout(async () => {
    const want = q + '|' + S.sbn.lid;
    let j; try { j = await rawFetch('GET', '/api/notes?q=' + encodeURIComponent(q) + (S.sbn.lid ? '&list_id=' + S.sbn.lid : '')); } catch (e) { toast(e instanceof Offline ? tr('Notes are only available online.') : e.message); return; }
    if (want !== S.sbn.q.trim() + '|' + S.sbn.lid) return;
    S.sbn.hits = j.notes || []; sb_notesPatch();
    announce(trn('{0} note', '{0} notes', S.sbn.hits.length));
  }, 250);
}
async function sb_noteNew(l) {
  let r; try { r = await rawFetch('POST', `/api/lists/${l.id}/notes`, {title: tr('New note')}); } catch (e) { toast(e.message); return; }
  S.notes = [{id: r.id, list_id: l.id, title: r.title, tags: [], pinned: false, updated_at: r.updated_at}, ...(S.notes || [])];
  S.nt.newId = r.id; go('note/' + r.id);
  setTimeout(() => { const t = $('#nt-title'); if (t) { t.focus(); t.select(); } }, 150);
}
document.addEventListener('input', e => {
  if (e.target.id !== 'sbn-q') return;
  S.sbn.q = e.target.value; if (S.sbn.q.trim()) S.sbn.hits = null; sb_notesSearch();
});
document.addEventListener('change', e => {
  if (e.target.id !== 'sbn-l') return;
  S.sbn.lid = +e.target.value || 0; S.sbn.hits = null;
  if (S.sbn.q.trim()) sb_notesSearch(); sb_notesPatch();
});
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-sb="note-new"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const ls = sb_noteWritable(), f = ls.find(l => l.id === S.sbn.lid);
  if (f) { sb_noteNew(f); return; }
  if (ls.length === 1) { sb_noteNew(ls[0]); return; }
  tch_listPicker(b, {filter: l => ls.includes(l), pick: l => sb_noteNew(l), title: tr('New note in…')});
}, true);
