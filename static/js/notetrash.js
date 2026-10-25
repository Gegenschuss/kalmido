// @ts-check
/* Kalmido web client: the notes of a project in the trash (2.272.0 E1, #3038). Classic script sharing the global scope with
   the others; loaded on demand (lazyload.js LD_MODS notetrash): chat.js draws the trash button next to "New note" and calls
   ntTrashHtml (a stand-in until this file is loaded). A deleted note lies in the trash (GET /api/lists/<id>/notes?trash=1)
   until the trash period ends (trash_days), Restore brings back the same note (POST /api/notes/<id>/restore). */
'use strict';

function ntTrashHtml() {
  const t = S.nt.trash;
  if (!t.notes) {
    if (!t.busy) {
      t.busy = true;
      rawFetch('GET', `/api/lists/${S.nt.lid}/notes?trash=1`).then(j => { if (S.nt.trash === t) { t.notes = j.notes || []; t.days = j.trash_days; renderView(); } })
        .catch(e => toast(e.message));
    }
    return `<div class="muted mhint">${tr('Loading…')}</div>`;
  }
  const hint = t.days ? `<p class="muted mscltrdays">${esc(trashNote(trn('Notes in the trash are deleted for good after {0} day.', 'Notes in the trash are deleted for good after {0} days.', t.days)))}</p>` : '';
  if (!t.notes.length) return `<div class="empty">${ic('trash')}${tr('The trash is empty')}</div>${hint}`;
  return `<ul class="ntcards" aria-label="${esc(tr('Trash'))}">${t.notes.map(n => `<li><div class="ntcard"><span class="ntt">${esc(n.title)}</span><span class="ntm"><span class="muted">${esc(tr('In the trash since {0}', fmtDate((n.deleted_at || '').slice(0, 10))))}</span><span class="spacer"></span><button type="button" class="btn sm" data-ntrest="${n.id}">${ic('undo', 's')} ${tr('Restore')}</button></span></div></li>`).join('')}</ul>${hint}`;
}
document.addEventListener('click', async e => {
  const b = /** @type {HTMLElement} */ (e.target).closest?.('[data-ntrest]'); if (!(b instanceof HTMLElement)) return;
  let x; try { x = await rawFetch('POST', `/api/notes/${b.dataset.ntrest}/restore`); } catch (err) { toast(err.message); return; }
  if (S.nt.lid === x.list_id) { S.nt.notes = [x, ...(S.nt.notes || []).filter(n => n.id !== x.id)]; if (S.nt.trash) S.nt.trash = {}; }
  await load(); toast(tr('Restored')); renderView();
});
