/* Kalmido web client: photo metadata on upload (2.61.0, #1819). The server removes GPS, camera and capture time from
   uploaded photos (kalmido/files/photometa.py); this file draws the organisation's switch in Settings > Workspaces (its
   admins decide, every member sees it) and the capture date of a photo document. The own switch for private files is a
   plain setting (settings.js SETS 's-pmeta').
   Classic script sharing the global scope with the others (load order: index.html; after wscolor.js). */
'use strict';

// the switch of each organisation in the workspaces pane (after wsPaneDraw; box._j = GET /api/orgs)
function pmeta_paneDraw(box) {
  if (!box?.isConnected) return;
  const orgs = (box._j || {}).orgs || [];
  for (const det of box.querySelectorAll('details.wsorg[data-oid]')) {
    const o = orgs.find(x => x.id === +det.dataset.oid); if (!o || det.querySelector('.pmeta-row')) continue;
    const adm = o.role === 'admin' && box._j.manage, id = `pmeta-o${o.id}`;
    const row = document.createElement('div');
    row.className = 'row pmeta-row';
    row.innerHTML = `<label class="chkl"><input type="checkbox" id="${id}" ${o.photo_meta_strip !== false ? 'checked' : ''} ${adm ? '' : 'disabled'}> ${tr('Remove location data from photos')}</label>`;
    const hint = document.createElement('div');
    hint.className = 'shint keep';
    hint.textContent = tr('Also removes camera details and capture time from the stored file.') + (adm ? '' : ' ' + tr('Only an admin of this organisation can change it.'));
    (det.querySelector('.wscpick + .shint') || det.querySelector('summary')).after(row); row.after(hint);
    if (!adm) continue;
    const cb = $('#' + id, row);
    cb.addEventListener('change', async () => {
      const on = cb.checked, put = v => async () => {
        await api('PATCH', `/api/orgs/${o.id}`, {photo_meta_strip: v});
        o.photo_meta_strip = v; if (cb.isConnected) cb.checked = v; return {};
      };
      try { await put(on)(); } catch { cb.checked = !on; return; }
      const label = tr('Photo metadata of {0}', qn(o.name));
      offerUndo(label, histAdd({label, undo: put(!on), redo: put(on)}));
    });
  }
}

// "Taken on …" in a document's detail (documents of photos: the EXIF capture date, kept when the metadata went)
function pmeta_takenHtml(d) {
  const t = d?.taken_at; if (!t || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(t)) return '';
  return `<div class="row dc-f pmeta-taken"><span></span><span class="muted">${ic('camera', 's')} ${esc(tr('Taken on {0} at {1}', dayLabel(t.slice(0, 10), true), fmtTimeLoc(t.slice(11, 16))))}</span></div>`;
}
