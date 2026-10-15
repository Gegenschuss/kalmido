// ------------------------------------------------------------------ 2.43.0 (#1346) the project page as a pin board
// A colour per block for everyone in the project (lists.page_style) and notepads (Markdown, own title, block "np<id>"),
// changed by everyone who may write in the list (accounts/layouts.py). Clicking a notepad edits it right there; it saves
// when the field is left (a live update waits while it is focused; someone else's save in between is asked about).
const WG_COLORS = [['yellow', N_('Yellow')], ['green', N_('Green')], ['blue', N_('Blue')], ['red', N_('Red')], ['purple', N_('Purple')], ['grey', N_('Grey')]];
const wgPov = () => { const l = routeList(); return l && S.povD[l.id]?.j ? {l, d: S.povD[l.id], y: S.povD[l.id].j.layout || {}} : null; };
const wgPadBlocks = () => (wgPov()?.y.pads || []).map(p => ['np' + p.id, p.title || N_('Notepad'), 'edit', 'half']);
const wgPadColor = k => wgPov()?.y.style?.[k] || '';
const wgPovSet = (P, r) => { if (P.d.j && r) { P.d.j.layout = r; renderView(); } };
async function wgColorSet(k, c) {
  const P = wgPov(); if (!P) return;
  const old = P.y.style?.[k] || '';
  const put = async x => { wgPovSet(P, await api('PUT', `/api/lists/${P.l.id}/page-style`, {block: k, color: x})); return {}; };
  try { await put(c); } catch { return; }
  histToast(tr('Colour changed'), histAdd({label: tr('Colour changed'), undo: () => put(old), redo: () => put(c)}));
}
function wgColorItems(k) {
  const P = wgPov(); if (!P?.y.can_style || P.l.archived) return [];
  const cur = P.y.style?.[k] || '';
  return [{label: tr('No colour'), title: tr('No colour'), cls: 'wgsw wgsw-none', on: !cur, fn: () => wgColorSet(k, '')},
    ...WG_COLORS.map(([c, n]) => ({label: tr(n), title: tr(n), cls: `wgsw wgsw-${c}`, on: cur === c, fn: () => wgColorSet(k, c)}))];
}
function wgPadAddItems() {
  const P = wgPov(); if (!P?.y.can_style || P.l.archived || (P.y.pads || []).length >= 20) return [];
  return [{label: tr('Notepad'), icon: 'edit', sub: tr('Text right on the page (Markdown)'), fn: () => wgPadNew()}];
}
async function wgPadNew(title, body) {
  const P = wgPov(); if (!P) return;
  let r; try { r = await api('POST', `/api/lists/${P.l.id}/notepads`, {title: title ?? tr('Notepad'), body: body || ''}); } catch { return; }
  wgPovSet(P, r);
  let id = r.id;
  if (title === undefined) { const p = r.pads.find(x => x.id === id); if (p) wgPadEdit(p); }
  histToast(tr('Notepad added'), histAdd({label: tr('Notepad added'),
    undo: async () => { wgPovSet(P, await api('DELETE', `/api/notepads/${id}`)); return {}; },
    redo: async () => { const p = await api('POST', `/api/lists/${P.l.id}/notepads`, {title: title ?? tr('Notepad'), body: body || ''}); id = p.id; wgPovSet(P, p); return {}; }}));
}
function wgPadItems(k) {
  const P = wgPov(), id = +String(k).replace(/^np/, ''), p = /^np\d+$/.test(k) && (P?.y.pads || []).find(x => x.id === id);
  if (!p || !P.y.can_style || P.l.archived) return [];
  return [{label: tr('Edit'), icon: 'edit', fn: () => wgPadEdit(p)},
    {label: tr('Rename…'), icon: 'tag', fn: async () => {
      const t = await askDialog({title: tr('Name of the notepad'), ok: tr('Save'), input: {value: p.title, max: 200}}); if (t == null || t === false) return;
      const put = async x => { wgPovSet(P, await api('PATCH', `/api/notepads/${p.id}`, {title: x})); return {}; }, old = p.title;
      try { await put(String(t).trim()); } catch { return; }
      histToast(tr('Renamed'), histAdd({label: tr('Renamed'), undo: () => put(old), redo: () => put(String(t).trim())}));
    }},
    {label: tr('Delete notepad'), icon: 'trash', cls: 'danger', fn: async () => {
      if (p.body && !await askConfirm(tr('Delete this notepad?'), tr('Everyone in the project loses its text.'), {ok: tr('Delete'), danger: true})) return;
      const col = P.y.style?.[k] || '';
      try { wgPovSet(P, await api('DELETE', `/api/notepads/${p.id}`)); } catch { return; }
      let nid = null;
      histToast(tr('Notepad deleted'), histAdd({label: tr('Notepad deleted'),
        undo: async () => { const r = await api('POST', `/api/lists/${P.l.id}/notepads`, {title: p.title, body: p.body}); nid = r.id; wgPovSet(P, col ? await api('PUT', `/api/lists/${P.l.id}/page-style`, {block: 'np' + nid, color: col}) : r); return {}; },
        redo: async () => { if (nid) wgPovSet(P, await api('DELETE', `/api/notepads/${nid}`)); return {}; }}));
    }}];
}
function wgPadHtml(l, p, can) {
  const ed = WG.pad?.id === p.id, nm = p.title || tr('Notepad');
  const edit = can ? `data-wgpadedit="${p.id}" tabindex="0" role="button" aria-label="${esc(tr('Edit {0}', nm))}"` : '';
  const body = ed ? `<textarea class="wgpadin" data-wgpad="${p.id}" rows="8" maxlength="20000" aria-label="${esc(nm)}" placeholder="${esc(tr('Write in Markdown: lists, links, **bold**…'))}">${esc(WG.pad.body)}</textarea><p class="muted wgpadh">${tr('Saved when you leave the field.')}</p>`
    : p.body ? `<div class="md povmd wgpadmd" ${edit}>${renderMd(p.body, false, {lid: l.id}).replace(/<input type="checkbox"/g, '<input type="checkbox" disabled')}</div>`
      : `<div class="muted povempty wgpadmd" ${edit}>${can ? tr('Empty. Tap to write (Markdown).') : tr('Empty.')}</div>`;
  return `<section class="povs wgpad" id="pov-np${p.id}"><div class="povh"><h3>${esc(nm)}</h3><span class="spacer"></span></div>${body}</section>`;
}
function wgPadEdit(p) {
  WG.pad = {id: p.id, body: S.drafts['np:' + p.id] ?? p.body, orig: p.body, base: p.updated_at};
  renderView();
  setTimeout(() => { const t = $(`#view [data-wgpad="${p.id}"]`); if (t) { t.focus(); t.setSelectionRange(t.value.length, t.value.length); autosize(t); } }, 20);
}
async function wgPadSave(force) {
  const st = WG.pad, P = wgPov(); if (!st || !P) return;
  if (st.body === st.orig) { WG.pad = null; delete S.drafts['np:' + st.id]; renderView(); return; }
  try {
    const r = await rawFetch('PATCH', `/api/notepads/${st.id}`, {body: st.body, ...(force ? {} : {base: st.base})});
    if (WG.pad === st) WG.pad = null;
    delete S.drafts['np:' + st.id]; wgPovSet(P, r);
  } catch (e) {
    if (e.status === 409 && e.data?.pad) {  // someone else saved in between: keep the text, ask
      const ok = await askConfirm(tr('Someone else changed this notepad in the meantime'), tr('Save your text over it? Otherwise their version stays and your text is dropped.'), {ok: tr('Save mine'), cancel: tr('Keep theirs')});
      if (ok) { st.base = e.data.pad.updated_at; return wgPadSave(true); }
      if (WG.pad === st) WG.pad = null; delete S.drafts['np:' + st.id]; povLoad(P.l.id, true); return;
    }
    toast(e instanceof Offline ? tr('Offline: only works again with a connection') : e.message);  // the text stays in the draft
  }
}
document.addEventListener('click', e => {
  const m = e.target.closest?.('[data-wgpadedit]'); if (!m || e.target.closest('a,button,input')) return;
  const p = (wgPov()?.y.pads || []).find(x => x.id === +m.dataset.wgpadedit); if (p) { e.preventDefault(); wgPadEdit(p); }
});
document.addEventListener('keydown', e => {
  const m = e.target.closest?.('[data-wgpadedit]'); if (!m || e.target !== m || (e.key !== 'Enter' && e.key !== ' ')) return;
  e.preventDefault(); m.click();
});
document.addEventListener('input', e => { const t = e.target; if (t.dataset?.wgpad && WG.pad?.id === +t.dataset.wgpad) { WG.pad.body = t.value; S.drafts['np:' + WG.pad.id] = t.value; autosize(t); } });
document.addEventListener('focusout', e => { const t = e.target; if (t.dataset?.wgpad && WG.pad?.id === +t.dataset.wgpad) setTimeout(() => { if (document.activeElement !== t) wgPadSave(); }, 0); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && e.target.dataset?.wgpad) { e.preventDefault(); e.stopPropagation(); e.target.blur(); } }, true);
LY.project.colorItems = wgColorItems;
LY.project.blockItems = wgPadItems;
