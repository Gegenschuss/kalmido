/* Kalmido web client: Markdown in task titles (2.40.0, #1409). Classic script sharing the global scope with the others.
   Titles show inline Markdown (bold, italic, strikethrough, code, links) through the description's safe mdInline
   (attachments.js: everything is escaped first, links only http(s) / mailto); no blocks. The title field keeps the source.
   Places without HTML (tab title, notifications, aria-label / title attributes, export, sorting and search) use mdPlain:
   the same text without the Markdown marks (the server has the same rules in core/i18n.py md_plain). */
'use strict';

const MD_TITLE_RE = /[*~`\[\\]|https?:\/\/|mailto:/;
// the title as HTML (escaped; inline Markdown only when the title has any of its marks)
function mdTitle(s, nolink) { s = String(s ?? ''); if (!MD_TITLE_RE.test(s)) return esc(s); const h = mdInline(s); return nolink ? h.replace(/<a [^>]*>|<\/a>/g, '') : h; }
// inside a link / button / draggable chip (calendar, timeline, roadmap, dashboard): the formatting without nested links
const mdTitleNL = s => mdTitle(s, true);
// the title as plain text: [label](url) -> label, `code` -> code, **b** / *i* / ~~s~~ -> their text, \* -> *
function mdPlain(s) {
  s = String(s ?? '');
  if (!MD_TITLE_RE.test(s)) return s;
  s = s.replace(MD_PH_RE, '').replace(MD_ESC_RE, (_, c) => String.fromCharCode(0xE000 + c.charCodeAt(0)));  // \* = a literal * (attachments.js)
  return s.replace(/\[([^\[\]]+)\]\((?:https?:\/\/|mailto:)[^\s"'<>()\[\]`\\]+\)/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, '$1$2')
    .replace(/~~([^~]+)~~/g, '$1')
    .replace(MD_PH_RE, c => String.fromCharCode(c.charCodeAt(0) - 0xE000));
}
// a link in a title opens the link (a new tab; a task link of this app on top, chat.js trefOpen on the same node), never
// the task behind it: the row's own click handlers look for [data-act] further up, so the click stops at the document
document.addEventListener('click', e => { if (e.target.closest?.('.ttl a[href], .mdttl a[href]')) e.stopPropagation(); }, true);
// "Turn the open checklist items into subtasks" (detail.js mdToSubtasks): the history keeps the text before (server: activity
// md_subtasks with data.prev); "Restore the description" there puts it back (one undo step; the subtasks stay)
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-act="md-restore"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const t = taskById(S.sel), a = (S.tl?.activity || []).find(x => x.id === +b.dataset.aid);
  if (!t || !canEdit(t) || !a?.data?.prev || S.tl.id !== t.id) return;
  if (tlkIs(t)) { tlkToast(t); return; }
  flushSaves();
  await patchUndoable(t.id, {content: a.data.prev}, tr('Description restored'));
  S.editContent = false; renderDetail();
});
