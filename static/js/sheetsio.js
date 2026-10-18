// 2.89.0 C (#1916): tables to and from files. "Import CSV or Excel…" in the tables overview (a new table in the space shown,
// or attached to the list of the overview) and "Export as CSV" / "Export as Excel (.xlsx)" in a table's menu. They hook into
// sheets.js (SHV_HOOKS); an import is one Undo step (the new table goes to the trash, Redo brings it back).
window.SHV_HOOKS = window.SHV_HOOKS || {menu: [], overview: []};
(SHV_HOOKS.menu = SHV_HOOKS.menu || []).push(sh => [
  {label: tr('Export as CSV'), icon: 'download', fn: () => shxUiExport(sh, 'csv')},
  {label: tr('Export as Excel (.xlsx)'), icon: 'download', fn: () => shxUiExport(sh, 'xlsx')}]);
(SHV_HOOKS.overview = SHV_HOOKS.overview || []).push((space, lid) => [
  {label: tr('Import CSV or Excel…'), icon: 'upload', fn: () => shxUiImport(space, lid)}]);

function shxUiExport(sh, fmt) {  // a download of the file the server makes (values evaluated for you)
  const a = document.createElement('a');
  a.href = `/api/sheets/${sh.id}/export.${fmt === 'xlsx' ? 'xlsx' : 'csv'}`; a.download = '';
  document.body.append(a); a.click(); a.remove();
}
function shxUiSpace(space, lid) {  // the space of an imported table: the list's, else the overview's, else where new tables go
  const l = lid && typeof listById === 'function' ? listById(lid) : null;
  if (l) return l.org_id ? 'org:' + l.org_id : 'private';
  if (space && space !== 'all') return space;
  return typeof shvNewSpace === 'function' ? shvNewSpace() : 'private';
}
function shxUiImport(space, lid) {
  const sp = shxUiSpace(space, lid), inp = document.createElement('input');
  inp.type = 'file'; inp.accept = '.csv,.tsv,.txt,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  inp.onchange = async () => {
    const f = inp.files?.[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f); fd.append('space', sp); if (lid) fd.append('list_id', String(lid));
    let r; try { r = await rawFetch('POST', '/api/sheets/import', fd); } catch (e) { toast(e.message); return; }
    const id = r.sheet.id, title = r.sheet.title || '';
    const after = gone => { if (typeof shvAfterIdx === 'function') shvAfterIdx(id, gone); };
    after(false);
    const e = histAdd({label: tr('Import of {0}', qn(title)), ids: [], snaps: [], lids: [],
      undo: async () => { await rawFetch('DELETE', '/api/sheets/' + id); after(true); return {skipped: []}; },
      redo: async () => { await rawFetch('POST', `/api/sheets/${id}/restore`); after(false); return {skipped: []}; }});
    histToast((r.messages || []).join(' · ') || tr('Import finished'), e);
    go('sheets/' + id);
  };
  inp.click();
}
