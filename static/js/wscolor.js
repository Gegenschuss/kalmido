/* Kalmido web client: workspace colours (2.53.0, #1474): Private stays neutral, an organisation has a colour (its admins
   choose, every member sees the same) -- a stripe in the list header and the sidebar, the frame of the input fields, the
   sign / switch of the workspace, the hint when something moves from Private into an organisation.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md; after listcolor.js). */
'use strict';

// the organisations' own palette (8 tones, [dark-theme value, light-theme value]): a workspace is only
// a stripe / frame / the sign in the header, never a dot or an accent, so it needs no ink; the tones sit between the list
// tones (deeper, calmer) so the two signals do not read as one. Text in the tone (the sign) passes 4.5:1 on the backgrounds.
const WSC_TONES = [
  ['#8b9cf7', '#4252c7'], ['#4cc3d9', '#0e6f82'], ['#6fcf8f', '#2b7444'], ['#e0b05c', '#85600f'],
  ['#ef8a6b', '#b0472a'], ['#d38ad8', '#8c3b91'], ['#f080a0', '#b03a5d'], ['#a8b0bd', '#545c69'],
];
// the colour of a workspace. Private has none (neutral); an organisation has the one its admins chose
// (orgs.color, nearest tone of WSC_TONES) or, before that, a default tone from its id -- coloured always means "others see it"
const wsc_ix = (color, orgId) => { const i = color ? lp_nearIx(color, WSC_TONES, [0, 1]) : -1; return i >= 0 ? i : Math.abs(+orgId - 1) % WSC_TONES.length; };
const wsc_tone = orgId => orgId ? WSC_TONES[wsc_ix(wsOrg(orgId)?.color, orgId)] : null;
const wsc_vars = orgId => { const t = wsOn() && wsc_tone(orgId); return t ? `--wsd:${t[0]};--wsl:${t[1]}` : ''; };
// the attributes for an element in a workspace's colour: data-wsc + style="--wsd/--wsl" (app.css picks the theme's tone)
const wsc_attr = orgId => { const v = wsc_vars(orgId); return v ? ` data-wsc="1" style="${v}"` : ''; };
const wsc_ofWs = ws => String(ws || '').startsWith('org:') ? +ws.slice(4) : 0;
// the sidebar row of an organisation's list: a stripe on its left edge
const wsc_rowAttr = l => l && !l.is_inbox && l.org_id ? wsc_attr(l.org_id) : '';
// moved from Private into an organisation -> the toast says who sees it now (the move keeps its Undo)
function wsc_moveMsg(fromList, toList, msg) {
  const a = lp_listOf(fromList), b = lp_listOf(toList);
  if (!wsOn() || !a || !b || (a.org_id && !a.is_inbox) || !b.org_id || b.is_inbox) return msg;
  return tr('Will be visible to everyone in {0}', wsLabel(b.org_id));
}
// a list moved into an organisation (list dialog): the hint with its own Undo (back to Private)
function wsc_listMoved(id, was, now) {
  if (!wsOn() || was || !now) return;
  const put = org => async () => { await api('PATCH', '/api/lists/' + id, {org_id: org}); await load(); render(); return {}; };
  const msg = tr('Will be visible to everyone in {0}', wsLabel(now));
  offerUndo(msg, histAdd({label: tr('Workspace of {0}', qn(lname(listById(id)) || '')), undo: put(null), redo: put(now)}));
}

// ---- after every render: the open list's workspace colour on the list view (header stripe, quick add frame) and the
// detail's comment field (the task's workspace)
const WSC_VARS = ['--wsd', '--wsl'];
const wsc_listVars = l => l && !l.is_inbox && l.org_id ? wsc_vars(l.org_id) : '';
function wsc_sync() {
  const k = S.route?.mod === 'tasks' ? String(S.route.key || '') : '';
  lp_put($('#main'), 'wsc-on', wsc_listVars(k.startsWith('l:') ? listById(+k.slice(2)) : null), WSC_VARS);
  wsc_detail();
}
function wsc_detail() {
  const t = S.sel ? taskById(S.sel) : null;
  lp_put($('#detail'), 'wsc-on', wsc_listVars(t ? listById(t.list_id) : null), WSC_VARS);
}

// ---- Settings > Workspaces: an organisation's colour (its admins choose, every member sees the same)
function wsc_paneDraw(box) {
  if (!box?.isConnected) return;  // the dialog closed while /api/orgs loaded
  const orgs = (box._j || {}).orgs || [];
  for (const det of box.querySelectorAll('details.wsorg[data-oid]')) {
    const o = orgs.find(x => x.id === +det.dataset.oid); if (!o || det.querySelector('.wscpick')) continue;
    const adm = o.role === 'admin', cur = WSC_TONES[wsc_ix(o.color, o.id)][0];
    const row = document.createElement('div');
    row.className = 'row wscpick';
    row.innerHTML = `<label>${tr('Colour of the workspace')}</label><div class="colors" role="group" aria-label="${esc(tr('Colour of the workspace'))}">${WSC_TONES.map((t, i) => `<button type="button" style="background:${t[0]}" class="${cur === t[0] ? 'on' : ''}" aria-pressed="${cur === t[0]}" aria-label="${esc(tr('Color {0}', i + 1))}" data-wscp="${t[0]}" ${adm ? '' : 'disabled'}></button>`).join('')}</div>`;
    const hint = document.createElement('div');
    hint.className = 'shint keep';
    hint.textContent = adm ? tr('Lists of the organisation show it as a stripe in the header and the sidebar, for every member. Private stays without colour.') : tr('Only an admin of this organisation can change it.');
    const sum = det.querySelector('summary');
    sum.after(row); row.after(hint);
    if (!adm) continue;
    row.addEventListener('click', async e => {
      const b = e.target.closest('[data-wscp]'); if (!b || b.classList.contains('on')) return;
      const prev = o.color || '', put = c => async () => {
        await api('PATCH', `/api/orgs/${o.id}`, {color: c});
        o.color = c; const w = wsOrg(o.id); if (w) w.color = c;
        const sel = WSC_TONES[wsc_ix(c, o.id)][0];
        $$('[data-wscp]', row).forEach(x => { x.classList.toggle('on', x.dataset.wscp === sel); x.setAttribute('aria-pressed', String(x.dataset.wscp === sel)); });
        render(); return {};
      };
      try { await put(b.dataset.wscp)(); } catch { return; }
      offerUndo(tr('Colour of {0}', qn(o.name)), histAdd({label: tr('Colour of {0}', qn(o.name)), undo: put(prev), redo: put(b.dataset.wscp)}));
    });
  }
}
