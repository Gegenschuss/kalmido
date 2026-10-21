/* Kalmido web client: workspace colours (2.53.0, #1474): Private stays neutral, an organisation has a colour (its admins
   choose, every member sees the same) -- the stripe on top of the sidebar (2.138.2 C, #2389), the frame of the input fields, the
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
// 2.57.0 B (#1807): my own choice wins (setting ws_colors, a tone of LP_TONES -> its dark / light value, "none" = neutral)
const wsc_tone = orgId => { if (!orgId) return null; const t = wsp_own('org:' + +orgId); return t === 'none' ? null : t ? [t[2], t[4]] : WSC_TONES[wsc_ix(wsOrg(orgId)?.color, orgId)]; };
const wsc_vars = orgId => { const t = wsOn() && wsc_tone(orgId); return t ? `--wsd:${t[0]};--wsl:${t[1]}` : ''; };
// the attributes for an element in a workspace's colour: data-wsc + style="--wsd/--wsl" (app.css picks the theme's tone)
const wsc_attr = orgId => { const v = wsc_vars(orgId); return v ? ` data-wsc="1" style="${v}"` : ''; };
// ---- 2.57.0 B (#1807): my own colour per workspace (setting ws_colors {"private" | "org:<id>": tone key | "none"}; only I
// see it). Without a choice: an organisation keeps its admins' colour, Private stays neutral.
const wsp_cols = () => { try { const o = JSON.parse(S.settings?.ws_colors || '{}'); return o && typeof o === 'object' && !Array.isArray(o) ? o : {}; } catch { return {}; } };
// my choice for a workspace: the LP_TONES row, 'none' or undefined (= the default)
const wsp_own = ws => { const v = wsp_cols()[ws]; return v === 'none' ? 'none' : LP_TONES.find(t => t[0] === v); };
// the tone [dark, light] of a workspace as shown to me ('all' and a neutral one: null)
const wsp_tone = ws => { if (!wsOn() || !ws || ws === 'all') return null; if (ws !== 'private') return wsc_tone(wsc_ofWs(ws)); const t = wsp_own('private'); return t && t !== 'none' ? [t[2], t[4]] : null; };
const wsp_vars = ws => { const t = wsp_tone(ws); return t ? `--wsd:${t[0]};--wsl:${t[1]}` : ''; };
// like wsc_attr for a workspace key (the switch, the chip, a list's sign): Private takes my colour too
const wsp_attr = ws => { const v = wsp_vars(ws); return v ? ` data-wsc="1" style="${v}"` : ''; };
// 2.138.2 C (#2389): the colour of the stripe on top of the sidebar (and the dot of the switch) -- my own choice, else the
// organisation's (its admins' colour), else Kalmido's accent for Private (also without an organisation, P4); "All" and a
// neutral choice: null (grey stripe, hollow dot)
const wsp_barTone = ws => {
  if (!ws || ws === 'all') return null;
  if (ws !== 'private') return wsOn() ? wsc_tone(wsc_ofWs(ws)) : null;
  const t = wsp_own('private');
  return t && t !== 'none' ? [t[2], t[4]] : ['var(--accent)', 'var(--accent)'];
};
const wsp_barVars = ws => { const t = wsp_barTone(ws); return t ? `--wsd:${t[0]};--wsl:${t[1]}` : ''; };
// the dot in front of a workspace's name (the switch and its menu); neutral = a hollow ring
const wsp_dot = ws => { const v = wsp_barVars(ws); return `<span class="wsp-dot" aria-hidden="true"${v ? ` data-wsc="1" style="${v}"` : ''}></span>`; };
// 2.138.2 C (#2389): no tint of the sidebar any more -- the shown workspace's colour goes onto #app (--wbd / --wbl) for the
// 4 px stripe on top of the sidebar and the 3 px stripe on top of the header while the sidebar is closed (phone, rail)
const WSB_VARS = ['--wbd', '--wbl'];
function wsp_side() {
  const t = wsp_barTone(wsOn() ? wsCur() : 'private');
  lp_put($('#app'), 'wsb-on', t ? `--wbd:${t[0]};--wbl:${t[1]}` : '', WSB_VARS);
}
async function wsp_set(ws, v) {
  const before = S.settings.ws_colors || '{}', o = wsp_cols();
  if ((o[ws] || '') === v) return;
  if (v) o[ws] = v; else delete o[ws];
  const after = JSON.stringify(o), lab = tr('Colour of {0}', qn(wsName(ws)));
  const put = x => async () => { S.settings.ws_colors = x; render(); wsp_paneMark(); await api('PATCH', '/api/settings', {ws_colors: x}); return {}; };
  try { await put(after)(); } catch { S.settings.ws_colors = before; render(); wsp_paneMark(); return; }
  offerUndo(lab, histAdd({label: lab, undo: put(before), redo: put(after)}));
}
// Settings > Workspaces: my colour per workspace -- Default (organisations: the admins' colour), No color, the 12 list tones
function wsp_paneHtml() {
  const row = ws => {
    const nm = wsName(ws), org = ws !== 'private', def = org ? WSC_TONES[wsc_ix(wsOrg(wsc_ofWs(ws))?.color, wsc_ofWs(ws))][0] : '';
    const b = (v, bg, lab) => `<button type="button" style="background:${bg}" aria-label="${esc(lab)}" title="${esc(lab)}" data-wspc="${v}" class="${v ? '' : 'wsp-def'}"></button>`;
    return `<div class="row wsp-row" data-wsp="${esc(ws)}"><span class="wsp-nm">${wsIcon(ws)}<span>${esc(nm)}</span></span><div class="colors" role="group" aria-label="${esc(tr('Colour of {0}', nm))}">${org ? b('', def, tr('Default (colour of the organisation)')) + b('none', 'var(--bg4)', tr('No color')) : b('', 'var(--accent)', tr('Default (Kalmido purple)')) /* 2.138.2 C (#2389) */}${LP_TONES.map(t => b(t[0], t[2], tr(t[1]))).join('')}</div></div>`;
  };
  // 2.138.2 C (#2389): "Workspace colour" -- the stripe on top of the sidebar; Private's default is the accent (no "No color")
  return `<div class="wsp-pane"><h5>${tr('Workspace colour')}</h5><div class="shint keep">${tr('Only you see it: a stripe on top of the sidebar and a dot in the workspace switch. Without a choice an organisation shows the colour its admins chose; Private shows Kalmido purple.')}</div>${(wsOn() ? wsOptions() : ['private']).filter(w => w !== 'all').map(row).join('')}</div>`;
}
// 2.138.2 C (#2389, P4): the swatches react (Settings > Workspaces, and the account page of a person without an organisation)
function wsp_paneWire(box) {
  const p = box?.querySelector('.wsp-pane'); if (!p || p._w) return;
  p._w = 1; wsp_paneMark();
  p.addEventListener('click', e => {
    const b = e.target.closest('[data-wspc]'); if (b && !b.classList.contains('on')) wsp_set(b.closest('[data-wsp]').dataset.wsp, b.dataset.wspc);
  });
}
// the pressed swatch of each row follows my setting (after a change, its Undo, another device)
function wsp_paneMark() {
  const cols = wsp_cols();
  for (const r of $$('.wsp-row[data-wsp]')) {
    const ws = r.dataset.wsp, v = LP_TONES.some(t => t[0] === cols[ws]) || (cols[ws] === 'none' && ws !== 'private') ? cols[ws] : '';
    $$('[data-wspc]', r).forEach(b => { const on = b.dataset.wspc === v; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
  }
}
const wsc_ofWs = ws => String(ws || '').startsWith('org:') ? +ws.slice(4) : 0;
// the sidebar row of an organisation's list: a stripe on its left edge
// 2.144.3 B (#2231): the colour of the workspace an agent (or a chat entry of one) belongs to, same data-wsc / --wsd / --wsl
// mechanism as lists: an organisation's tone; Private = my own chosen colour, else neutral (null org = private). A chat entry
// with agent_org_id / org_id (the job chats of 2.107) passes the entry: acw_of(entry). Without organisations (wsOn() false): none.
const acw_attr = orgId => { const v = wsOn() ? wsp_vars(orgId ? 'org:' + +orgId : 'private') : ''; return v ? ` data-wsc="1" style="${v}"` : ''; };
const acw_of = e => acw_attr(e ? (e.agent_org_id ?? e.org_id) : null);
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
  wsp_side();  // 2.57.0 B (#1807); 2.138.2 C (#2389): the stripe's colour
}
function wsc_detail() {
  const t = S.sel ? taskById(S.sel) : null;
  lp_put($('#detail'), 'wsc-on', wsc_listVars(t ? listById(t.list_id) : null), WSC_VARS);
}

// ---- Settings > Workspaces: an organisation's colour (its admins choose, every member sees the same)
function wsc_paneDraw(box) {
  if (!box?.isConnected) return;  // the dialog closed while /api/orgs loaded
  if (!box.querySelector('.wsp-pane')) {  // 2.57.0 B (#1807): my own colours, above the organisations
    box.insertAdjacentHTML('afterbegin', wsp_paneHtml()); wsp_paneWire(box);
  }
  const orgs = (box._j || {}).orgs || [];
  for (const det of box.querySelectorAll('details.wsorg[data-oid]')) {
    const o = orgs.find(x => x.id === +det.dataset.oid); if (!o || det.querySelector('.wscpick')) continue;
    const adm = o.role === 'admin', cur = WSC_TONES[wsc_ix(o.color, o.id)][0];
    const row = document.createElement('div');
    row.className = 'row wscpick';
    row.innerHTML = `<label>${tr('Colour of the workspace')}</label><div class="colors" role="group" aria-label="${esc(tr('Colour of the workspace'))}">${WSC_TONES.map((t, i) => `<button type="button" style="background:${t[0]}" class="${cur === t[0] ? 'on' : ''}" aria-pressed="${cur === t[0]}" aria-label="${esc(tr('Color {0}', i + 1))}" data-wscp="${t[0]}" ${adm ? '' : 'disabled'}></button>`).join('')}</div>`;
    const hint = document.createElement('div');
    hint.className = 'shint keep';
    hint.textContent = adm ? tr('Every member sees it as a stripe on top of the sidebar and a dot in the workspace switch, unless they choose their own colour.') : tr('Only an admin of this organisation can change it.');  // 2.138.2 C (#2389): new hint
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
