// @ts-check
// 2.635.0 (#4807 d): notes on a document -- several, each with its author and time (docs/notes.py). Loaded with the documents
// (lazyload.js LD_MODS.docs). docs.js draws the sheet with an empty .dc-notes box; dn_draw fills it from d.notes (doc_json):
// the list, oldest first, "Delete" on a note its author or someone who may change the document may remove, and a field for
// a new note (only with the right to change the document). A draft survives the sheet's redraws (DN.draft per document).
/** @type {{draft: Object<number, string>}} */
const DN = {draft: {}};

function dn_html(d) {
  const notes = d.notes || [], w = d.role !== 'view';
  const li = notes.map(n => `<li class="dc-note" data-dnid="${+n.id}"><div class="dc-note-h"><b>${esc(n.author?.name || tr('Unknown'))}</b> <span class="muted">${esc(fmtWhen(n.created_at))}${n.source === 'paperless' ? ` · ${esc(tr('from Paperless-ngx'))}` : ''}</span>${n.can_delete ? `<button type="button" class="iconbtn dc-note-x" data-dn="del" data-dnid="${+n.id}" aria-label="${esc(tr('Delete note'))}" title="${esc(tr('Delete note'))}">${ic('trash', 's')}</button>` : ''}</div><p class="dc-note-t">${esc(n.text)}</p></li>`).join('');
  const add = w ? `<div class="dc-note-new"><label class="sr" for="dc-note-in">${esc(tr('New note'))}</label><textarea id="dc-note-in" rows="2" maxlength="5000" placeholder="${esc(tr('Add a note…'))}">${esc(DN.draft[d.id] || '')}</textarea><button type="button" class="btn sm pri" data-dn="add">${esc(tr('Add note'))}</button></div>` : '';
  if (!notes.length && !w) return '';
  return `<details class="dc-text dc-notesd"${notes.length ? ' open' : ''}><summary><h4>${esc(tr('Notes'))}${notes.length ? ` (${notes.length})` : ''}</h4>${ic('chev', 's dc-chev')}</summary>${li ? `<ul class="dc-notel">${li}</ul>` : ''}${add}</details>`;
}

function dn_draw(md, d) {
  const box = md.querySelector('.dc-notes'); if (!box || !d) return;
  const key = `${d.id}:${d.role}:${(d.notes || []).map(n => n.id).join(',')}`;
  if (box._k === key && box.firstChild) return;  // kept through the sheet's redraws (data-fl-fill): a focused field stays
  box._k = key;
  const open = box.querySelector('details')?.open;
  box.innerHTML = dn_html(d);
  const det = box.querySelector('details'); if (det && open !== undefined) det.open = open || !!(d.notes || []).length;
  if (box._on) return;
  box._on = true;
  box.addEventListener('input', e => {
    const t = /** @type {HTMLTextAreaElement} */ (e.target);
    if (t.id === 'dc-note-in' && DC.doc) DN.draft[DC.doc.id] = t.value;
  });
  box.addEventListener('click', async e => {
    const b = /** @type {HTMLElement} */ (e.target).closest('[data-dn]'); const doc = DC.doc;
    if (!b || !doc) return;
    if (b.dataset.dn === 'add') {
      const t = /** @type {HTMLTextAreaElement|null} */ (box.querySelector('#dc-note-in')); const text = (t?.value || '').trim();
      if (!text) { t?.focus(); return; }
      let j; try { j = await api('POST', `/api/docs/${doc.id}/notes`, {text}); } catch { return; }
      delete DN.draft[doc.id];
      doc.notes = j.notes; dn_draw(md, doc);
      /** @type {HTMLElement|null} */ (box.querySelector('#dc-note-in'))?.focus();
      const id = j.note?.id;
      histToast(tr('Note added'), histAdd({label: tr('Note added'),
        undo: async () => { const r = await api('DELETE', `/api/docs/${doc.id}/notes/${id}`); dn_set(doc, r.notes); return {}; },
        redo: async () => { const r = await api('POST', `/api/docs/${doc.id}/notes`, {text}); dn_set(doc, r.notes); return {}; }}));
      return;
    }
    if (b.dataset.dn === 'del') {
      const n = (doc.notes || []).find(x => x.id === +(b.dataset.dnid || 0)); if (!n) return;
      let j; try { j = await api('DELETE', `/api/docs/${doc.id}/notes/${n.id}`); } catch { return; }
      doc.notes = j.notes; dn_draw(md, doc);
      // the undo writes the text again as a new note of the signed-in person: only offered for an own note
      if (n.author?.id === S.me?.id) {
        histToast(tr('Note deleted'), histAdd({label: tr('Note deleted'),
          undo: async () => { const r = await api('POST', `/api/docs/${doc.id}/notes`, {text: n.text}); dn_set(doc, r.notes); return {}; },
          redo: async () => { const x = (doc.notes || []).find(y => y.text === n.text && y.author?.id === S.me?.id); if (x) { const r = await api('DELETE', `/api/docs/${doc.id}/notes/${x.id}`); dn_set(doc, r.notes); } return {}; }}));
      } else toast(tr('Note deleted'));
    }
  });
}

function dn_set(doc, notes) {  // after an undo / redo: the open sheet of that document shows the new list
  doc.notes = notes;
  const md = document.querySelector('.dc-md'); if (md && DC.doc && DC.doc.id === doc.id) dn_draw(md, DC.doc);
}
