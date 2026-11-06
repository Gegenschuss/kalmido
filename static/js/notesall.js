/* Kalmido web client: the notes of all lists and projects in one place (2.45.0, #1516).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- #1516: #notes (no list id) = every note I may read: pinned first, then the newest change; the list's name on each card;
// a filter by list / project and a search in title and text (the server's GET /api/notes, the same rights as a list's notes);
// "New note" opens a quick note (2.477.0, #3881: in the filtered list, else in the private list "Notes"). #notes/<id> stays the
// notes of one list.
S.sbn = {q: '', lid: 0, hits: null, ex: {}, exLoaded: false, qT: null};
// 2.398.0 (#3405): Notes are in every workspace and show that workspace's notes: the notes of its projects plus my private list
// "Notes" (only I see it; sharing = moving a note into a project, with the warning that names who sees it then). The server
// keeps who may read a note (the list's people); this only decides what the view shows
const nt_inWs = n => { const l = n && listById(n.list_id); return !!l && (inWs(l) || qn_isList(l.id)); };  // a list not loaded: not shown (inWs(undefined) is true)
const nt_wsNotes = () => (S.notes || []).filter(nt_inWs);
const sb_noteCount = () => nt_wsNotes().length;
const sb_noteWritable = () => S.lists.filter(l => !l.archived && notesOn(l) && canEditList(l.id));
const sb_notesShown = () => S.lists.some(l => !l.archived && notesOn(l)) || sb_noteCount() > 0;
function sb_noteExcerpts() {  // the first lines of the newest notes (S.notes has no text)
  if (S.sbn.exLoaded) return;
  S.sbn.exLoaded = true;
  rawFetch('GET', '/api/notes').then(j => { for (const n of j.notes || []) S.sbn.ex[n.id] = n.excerpt; if (S.route.mod === 'notes' && !S.nt.lid) sb_notesPatch(); }).catch(() => { S.sbn.exLoaded = false; });
}
function sb_notesItems() {
  const f = S.sbn.lid;
  if (S.sbn.q.trim()) return S.sbn.hits && S.sbn.hits.filter(nt_inWs);  // null = the server is still asked; 2.398.0 (#3405): this workspace's
  return nt_wsNotes().filter(n => !f || n.list_id === f).sort((a, b) => (b.pinned - a.pinned) || String(b.updated_at).localeCompare(String(a.updated_at)));
}
function sb_noteCardsHtml() {
  const vis = sb_notesItems(), q = S.sbn.q.trim();
  if (vis === null) return `<div class="muted mhint">${tr('Loading…')}</div>`;
  if (!vis.length) return q || S.sbn.lid ? `<div class="empty">${tr('No notes match.')}</div>` : symEmpty('note', tr('No notes yet.'), sb_noteWritable().length ? tr('Meeting notes, briefings, decisions: write them next to the tasks.') : '');
  return `<ul class="ntcards" aria-label="${esc(tr('Notes'))}">${vis.map(n => {
    const l = listById(n.list_id), ex = n.excerpt ?? S.sbn.ex[n.id] ?? '';
    return `<li><a href="#note/${n.id}" class="ntcard sbncard">
      <span class="ntt">${n.pinned ? `<span class="ntpin" title="${esc(tr('Pinned'))}">${ic('pin', 's')}</span>` : ''}${esc(n.title)}</span>
      ${ex ? `<span class="ntx">${esc(ex.slice(0, 140))}</span>` : ''}
      <span class="ntm"><span class="sbnl">${l ? licMark(l, 'sm', true) : ''}${esc(l ? lname(l) : '?')}</span>${(n.tags || []).map(t => `<span class="tag">#${esc(t)}</span>`).join('')}<time title="${esc(fmtWhen(n.updated_at))}">${esc(relTime(n.updated_at))}</time></span></a></li>`;
  }).join('')}</ul>`;
}
function sb_notesView() { return `<div class="ntwrap"><div class="ntview sbnall">${sb_notesListHtml()}</div></div>`; }
// 2.602.0 (#4817): the list alone - the page's on a phone, the panel's on a computer (chat.js nt_panelHtml)
function sb_notesListHtml() {
  sb_noteExcerpts();
  const ids = new Set(nt_wsNotes().map(n => n.list_id)), ls = S.lists.filter(l => ids.has(l.id) || l.id === S.sbn.lid);  // 2.398.0 (#3405)
  const opt = l => `<option value="${l.id}" ${l.id === S.sbn.lid ? 'selected' : ''}>${esc(lname(l))}</option>`;
  const prj = ls.filter(l => !l.is_inbox), oth = ls.filter(l => l.is_inbox);  // 2.352.0 B (#2752)
  const sel = ls.length > 1 || S.sbn.lid ? `<select id="sbn-l" class="sbnsel" aria-label="${esc(tr('Project'))}"><option value="0">${tr('All projects')}</option>${prj.length && oth.length ? `<optgroup label="${esc(tr('Projects'))}">${prj.map(opt).join('')}</optgroup><optgroup label="${esc(tr('Other projects'))}">${oth.map(opt).join('')}</optgroup>` : ls.map(opt).join('')}</select>` : '';
  return `<div class="ntlist sbnlist">
    <div class="ntbar sbnbar"><div class="ssearch">${ic('search', 's')}<input id="sbn-q" type="search" value="${esc(S.sbn.q)}" placeholder="${esc(tr('Search notes'))}" aria-label="${esc(tr('Search notes'))}" autocomplete="off"></div>${sel}
      ${S.me?.kid ? '' : `<button type="button" class="btn sm pri" data-sb="note-new">${ic('plus', 's')}${tr('New note')}</button>` /* 2.477.0 (#3881): always (the list Notes comes with it) */}</div>
    ${o3a_orgView() && !S.me?.kid && (!S.sbn.lid || qn_isList(S.sbn.lid)) ? `<p class="muted shint sbnpriv">${ic('lock', 's')} ${esc(tr('New notes stay private: only you see them. To share one, move it into a project.'))}</p>` : '' /* 2.398.0 (#3405) */}
    <div id="sbn-res">${sb_noteCardsHtml()}</div></div>`;
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
document.addEventListener('input', e => {
  if (e.target.id !== 'sbn-q') return;
  S.sbn.q = e.target.value; if (S.sbn.q.trim()) S.sbn.hits = null; sb_notesSearch();
});
document.addEventListener('change', e => {
  if (e.target.id !== 'sbn-l') return;
  S.sbn.lid = +e.target.value || 0; S.sbn.hits = null;
  if (S.sbn.q.trim()) sb_notesSearch();
  if (o3a_orgView()) renderView(); else sb_notesPatch();  // 2.398.0 (#3405): the privacy line follows the filter
});
// 2.551.0 (#4607): a right click (computer) or a long press (phone) on a note card opens that note's menu (chat.js noteMenu,
// on the phone the sheet with its title); the click ending the press does not open the note. Cards of the trash are no links.
const nt_cardMenu = r => { const id = +(r.getAttribute('href') || '').replace('#note/', ''); if (!id) return false; noteMenu(r, id); return true; };
cm_bind('#view a.ntcard[href^="#note/"], #side a.ntcard[href^="#note/"]', nt_cardMenu);  // 2.602.0 (#4817): + the panel's list
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-sb="note-new"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  // 2.477.0 (#3881): no question any more: a list filtered here takes it, else the private list "Notes"
  const f = sb_noteWritable().find(l => l.id === S.sbn.lid);
  qn_new(f ? f.id : 0);
}, true);

// ---- 2.477.0 (#3881): the quick note, like Apple Notes. One grip (holding the phone's Plus button, the key m, "New note" in
// the command field and in the notes) opens an empty note with the cursor in its text: no question for the list, no title
// field. The first line is the title, it saves by itself; a note left empty goes for good (never into the trash). Its home is
// the private list "Notes" (lists.quicknote, made by the server on the first grip, POST /api/notes/quick-list): a flat
// list, newest first, a fixed entry in the sidebar; it can never be shared (the server refuses, core/access.py qn_private).
// A note of that list may move into a shared list only after a warning that names who sees it then.
// The note being written is a draft (id QN_DRAFT, S.nt.draft) until its first character: then it is made (online, or in the
// outbox like any note: offline as before), so an empty one never reaches the server.
const QN_DRAFT = -1;
const qn_isList = lid => !!listById(lid)?.quicknote;
const qn_list = () => S.lists.find(l => l.quicknote && !l.archived && l.owner_id === S.me?.id);
const QN_MADE = new Set();  // the notes made as a quick note in this tab: they keep the one text field (also in another list)
const qn_plain = n => !!n && (n.id === QN_DRAFT || qn_isList(n.list_id) || QN_MADE.has(n.id));
// the title of a quick note: its first line with text, a heading's # left out (the server's qn_title, collab/notes.py)
function qn_titleOf(text) {
  for (const ln of String(text || '').split(/\r?\n/)) { const t = ln.replace(/^\s*#{1,6}\s+/, '').replace(/\s+/g, ' ').trim(); if (t) return t.slice(0, 300); }
  return '';
}
async function qn_listId() {
  const l = qn_list(); if (l) return l.id;
  let j; try { j = await rawFetch('POST', '/api/notes/quick-list'); } catch (e) { toast(e instanceof Offline ? tr('The list Notes is made with the first quick note: that needs a connection once.') : e.message); return 0; }
  await load();
  return j.list_id;
}
/** @param {number} [lid] the list (default: the private list "Notes") */
async function qn_new(lid) {
  if (S.me?.kid || S.qnBusy) return;
  S.qnBusy = true;
  try {
    const id = lid || await qn_listId(); if (!id) return;
    if (S.nt.id === QN_DRAFT && S.nt.draft?.list_id === id) { qn_focus(); return; }
    const now = new Date().toISOString();
    S.nt.draft = {id: QN_DRAFT, list_id: id, title: '', body: '', text: '', tags: [], pinned: false, created_by: S.me?.id, updated_by: S.me?.id, created_at: now, updated_at: now, updated_by_name: ''};
    if (location.hash !== '#notes/' + id && !/^#note\//.test(location.hash)) history.pushState(null, '', '#notes/' + id);  // Back from the note = its list
    go('note/' + QN_DRAFT);
    qn_focus();
  } finally { S.qnBusy = false; }
}
function qn_focus(n = 0) {
  const b = $('#nt-body');
  if (b && S.nt.id === QN_DRAFT) { b.focus(); b.setSelectionRange(b.value.length, b.value.length); return; }
  if (n < 30) requestAnimationFrame(() => qn_focus(n + 1));
}
// the editor: one text field, nothing in front of it
function qn_editHtml(n) {
  const dr = n.id === QN_DRAFT;
  return `<div class="nthead ntqhead">${isMobile() ? `<button type="button" class="iconbtn" data-act="nt-close" aria-label="${esc(tr('Back'))}">${ic('back')}</button>` : ''}<span class="spacer"></span>
    ${dr ? '' : `<button type="button" class="iconbtn" data-act="nt-menu" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots')}</button>`}
    ${isMobile() ? '' : `<button type="button" class="iconbtn" data-act="nt-close" title="${esc(tr('Close'))}" aria-label="${esc(tr('Close'))}">${ic('x')}</button>`}</div>
    <textarea id="nt-body" class="ntbody ntplain" aria-label="${esc(tr('Note'))}" placeholder="${esc(tr('Note … (#123 links a task)'))}">${esc(dr ? n.text : n.body)}</textarea>
    <div class="ntfoot muted"><span id="nt-saved" role="status" aria-live="polite"></span><span class="spacer"></span>${dr ? '' : `<span>${esc(tr('Changed {0}', fmtWhen(n.updated_at)))}</span>`}</div>`;
}
// the first character: the note is made (the text typed meanwhile follows as a change; left empty meanwhile: gone again)
function qn_create() {
  const d = S.nt.draft, b = $('#nt-body'); if (!d) return;
  if (b && S.nt.id === QN_DRAFT) d.text = b.value;
  S.nt.dirty = false; clearTimeout(S.nt.saveT);
  if (S.nt.creating || !d.text.trim()) return;
  const sent = d.text, url = `/api/lists/${d.list_id}/notes`, body = {title: qn_titleOf(sent), body: sent, client_ref: outKey()};
  S.nt.creating = (async () => {
    let r = null;
    if (ntLocked(d.list_id)) try { r = await rawFetch('POST', url, body); } catch (e) { toast(e instanceof Offline ? tr('Offline: only works again with a connection') : e.message); return; }  // 2.536.0 (#4567): else the outbox, online too
    if (S.nt.lid === d.list_id && !S.nt.notes) S.nt.notes = [];
    if (!r) r = enqueue('POST', url, body);  // offline: the outbox (ntLocal draws it)
    else {
      if (S.nt.lid === d.list_id) S.nt.notes = [r, ...S.nt.notes.filter(x => x.id !== r.id)];
      S.notes = [{id: r.id, list_id: d.list_id, title: r.title, tags: [], pinned: false, updated_at: r.updated_at}, ...(S.notes || []).filter(x => x.id !== r.id)];
    }
    QN_MADE.add(r.id);
    const on = S.nt.id === QN_DRAFT && S.nt.draft === d;
    if (S.nt.draft === d) S.nt.draft = null;
    if (on) { S.nt.id = r.id; if (S.route.mod === 'notes') history.replaceState(null, '', '#note/' + r.id); }
    const n = (S.nt.notes || []).find(x => x.id === r.id) || r;
    if (!d.text.trim()) qn_purge(n);
    else if (d.text !== sent) { if (on) { S.nt.dirty = true; noteFlush(); } else ntWrite(n, {body: d.text, title: qn_titleOf(d.text)}).catch(() => {}); }
    else if (on) { const s = $('#nt-saved'); if (s) s.textContent = (r.queued || r.id < 0) && !OUT.online ? tr('You are offline: the note is saved as soon as the server is reachable') : tr('Saved'); }
    if (!on && S.route.mod === 'notes') renderView();  // left already: the list shows it
  })().finally(() => { S.nt.creating = null; });
}
// leaving a quick note (another note, its list, another view): left empty = gone for good. true = handled (no save)
function qn_leave() {
  const n = noteCur(); if (!n || !qn_plain(n)) return false;
  const b = $('#nt-body'), text = b ? b.value : n.id === QN_DRAFT ? n.text : n.body;
  if (n.id === QN_DRAFT) n.text = text;
  if (text.trim()) return false;
  clearTimeout(S.nt.saveT); S.nt.dirty = false;
  if (n.id === QN_DRAFT) S.nt.draft = null;  // never made (or still being made: qn_create takes it back)
  else qn_purge(n);
  return true;
}
// an empty quick note goes for good: DELETE ?empty=1 (the server checks that it is empty); one made offline and not sent yet
// leaves the outbox with its changes
async function qn_purge(n, empty = false) {
  S.nt.notes = (S.nt.notes || []).filter(x => x.id !== n.id); S.notes = (S.notes || []).filter(x => x.id !== n.id);
  const url = `/api/notes/${n.id}`, del = url + '?empty=1';
  if (n.id < 0) {
    const mine = OUT.q.filter(x => x.tmp === n.id || x.url === url);
    if (mine.length && !mine.some(x => x.sending)) { outSave(() => { OUT.q = OUT.q.filter(x => !mine.includes(x)); }); renderTop(); return; }
  }
  try {
    if (!empty && (await ntWrite(n, {body: ''})).queued) { enqueue('DELETE', del); return; }
    if (n.id < 0 || OUT.q.some(x => x.url === url)) { enqueue('DELETE', del); return; }
    await rawFetch('DELETE', del);
  } catch (e) { if (e instanceof Offline) enqueue('DELETE', del); }
}
// the notes of the list "Notes" loaded: an empty one of mine left behind (the tab closed while it was empty) goes too
function qn_heal(lid) {
  if (!qn_isList(lid)) return;
  for (const n of (S.nt.notes || []).filter(x => x.id > 0 && x.id !== S.nt.id && x.created_by === S.me?.id && !String(x.body || '').trim())) qn_purge(n, true);
}
// moving a note out of the list "Notes" to other people: the server answers 409 quicknote_share with their names; only after
// a yes it goes (share_ok)
async function qn_shareAsk(people, l) {
  return askDialog({title: tr('Move the note to {0}?', lname(l)), html: `<p><b>${esc(tr('After the move these people see this note:'))}</b></p><ul class="qnwho">${people.map(p => `<li><b>${esc(p)}</b></li>`).join('')}</ul><p class="muted">${esc(tr('The list Notes itself stays private.'))}</p>`, ok: tr('Move'), cancel: tr('Cancel')});
}
// the phone: holding the Plus button = a quick note (a tap stays a new task)
const QN_FAB = ms_longPress('#fab', () => false, () => qn_new());
