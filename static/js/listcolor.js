/* Kalmido web client: list colours (2.53.0, #1426): the palette, the accent of an open list, the card edges, folder colours.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- 2.53.0 (#1426): a fixed palette of 12 tones for lists (and folders). A tone = [key, name, dark-theme value, ink on it,
// light-theme value, ink on it]; the dark value is the one stored (lists.color). Every pair passes WCAG AA (4.5:1) as text on
// the theme's backgrounds and with its ink on it (tests/appearance_ui.js). Decided 14.10.2026: no one-way step -- an older
// free colour stays stored as it is, the app SHOWS the nearest tone (lp_near), a new choice only comes from the palette.
const LP_TONES = [
  ['red', N_('Red'), '#f87171', '#1f0a0a', '#c4302b', '#ffffff'],
  ['orange', N_('Orange'), '#fb923c', '#1f0e04', '#ad4c07', '#ffffff'],
  ['yellow', N_('Yellow'), '#f5b041', '#1f1404', '#8a5806', '#ffffff'],
  ['lime', N_('Lime'), '#a3d94a', '#121a04', '#4a7110', '#ffffff'],
  ['green', N_('Green'), '#4ade80', '#05200f', '#1d7a3e', '#ffffff'],
  ['teal', N_('Teal'), '#2dd4bf', '#04201c', '#0f766e', '#ffffff'],
  ['sky', N_('Sky'), '#38bdf8', '#041a26', '#0369a1', '#ffffff'],
  ['blue', N_('Blue'), '#6d8cff', '#0a1033', '#3b5bdb', '#ffffff'],
  ['violet', N_('Violet'), '#a78bfa', '#1a1033', '#6d4bd8', '#ffffff'],
  ['purple', N_('Purple'), '#d07cf0', '#22082c', '#9333b8', '#ffffff'],
  ['pink', N_('Pink'), '#f472b6', '#2a0a1a', '#be2d78', '#ffffff'],
  ['grey', N_('Grey'), '#94a3b8', '#0f1420', '#56627a', '#ffffff'],
];
const lp_rgb = hex => {
  let h = String(hex || '').trim().replace('#', '');
  if (h.length === 3 || h.length === 4) h = h.slice(0, 3).split('').map(x => x + x).join('');
  if (!/^[0-9a-f]{6}([0-9a-f]{2})?$/i.test(h)) return null;
  return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
};
// "redmean" distance: close enough to how far apart two colours look, without a colour space conversion
const lp_dist = (a, b) => { const r = (a[0] + b[0]) / 2, d = a.map((v, i) => v - b[i]); return (2 + r / 256) * d[0] ** 2 + 4 * d[1] ** 2 + (2 + (255 - r) / 256) * d[2] ** 2; };
const lp_nearCache = new Map();
// the index of the nearest tone of pal (values at columns cols) for a stored colour, -1 = none / not a colour
function lp_nearIx(hex, pal, cols) {
  const k = cols.join() + '|' + hex;
  if (lp_nearCache.has(k)) return lp_nearCache.get(k);
  const c = lp_rgb(hex); let best = -1, bd = Infinity;
  if (c) pal.forEach((t, i) => { for (const j of cols) { const d = lp_dist(c, lp_rgb(t[j])); if (d < bd) { bd = d; best = i; } } });
  lp_nearCache.set(k, best);
  return best;
}
const lp_near = hex => { const i = hex ? lp_nearIx(hex, LP_TONES, [2, 4]) : -1; return i < 0 ? null : LP_TONES[i]; };
const lp_listOf = x => x && typeof x === 'object' ? x : listById(+x);
// the tone a list shows (null = no colour), its stored value ('' = none)
const lp_tone = x => { const l = lp_listOf(x); return l && !l.is_inbox && l.color ? lp_near(l.color) : null; };
const lp_col = x => lp_tone(x)?.[2] || '';
// what a form sends back: the stored (maybe free) colour as long as the shown tone was not changed -> never rewritten
const lp_keep = (l, c) => l && c && c === lp_col(l) ? l.color || '' : c;
const lp_dotOnly = () => S.settings?.list_color_dot === '1';
const lp_vars = t => t ? `--lpd:${t[2]};--lpid:${t[3]};--lpl:${t[4]};--lpil:${t[5]}` : '';
// the card edge of a task (Kanban, calendar, the collected views): a class + the tone as variables (theme picks, see app.css)
const lp_cls = t => !lp_dotOnly() && lp_tone(t?.list_id) ? ' lpc lpv' : '';
const lp_sty = t => lp_dotOnly() ? '' : lp_vars(lp_tone(t?.list_id));
const lp_attr = t => { const v = lp_sty(t); return v ? ` style="${v}"` : ''; };

// ---- folders: a colour per folder of mine (setting folder_colors {path: colour}); a new list in it takes it (the server
// does that for lists created without a colour, the list dialog preselects it); the lists already in it keep theirs
const lp_folderCols = () => { try { const o = JSON.parse(S.settings?.folder_colors || '{}'); return o && typeof o === 'object' ? o : {}; } catch { return {}; } };
function lp_folderColor(path) {
  const cols = lp_folderCols(), parts = String(path || '').split(FSEP).filter(Boolean);
  for (let i = parts.length; i > 0; i--) { const v = cols[parts.slice(0, i).join(FSEP)]; if (v) return lp_near(v)?.[2] || ''; }
  return '';
}
const lp_folderSty = f => { const c = lp_near(lp_folderCols()[f])?.[2]; return c ? ` style="color:${c}"` : ''; };
async function lp_folderSet(f, c) {
  const before = S.settings.folder_colors || '{}', o = lp_folderCols();
  if ((o[f] || '') === c) return;
  if (c) o[f] = c; else delete o[f];
  const after = JSON.stringify(o);
  const put = v => async () => { S.settings.folder_colors = v; render(); await api('PATCH', '/api/settings', {folder_colors: v}); return {}; };
  try { await put(after)(); } catch { S.settings.folder_colors = before; render(); return; }
  offerUndo(tr('Colour of {0}', qn(fName(f))), histAdd({label: tr('Colour of {0}', qn(fName(f))), undo: put(before), redo: put(after)}));
}
// the swatch row of a menu (list / folder): none + the 12 tones
const lp_menuRow = (cur, fn) => ({rcls: 'mcols', rlab: tr('Color'), row: ['', ...LP_TONES.map(t => t[2])].map((c, i) => ({label: c ? tr(LP_TONES[i - 1][1]) : tr('No color'), cls: 'mcol', swc: c, on: (cur || '') === c, fn: () => fn(c)}))});
const lp_folderMenuRow = f => [lp_menuRow(lp_near(lp_folderCols()[f])?.[2] || '', c => lp_folderSet(f, c)), '-'];
// the swatches of the list dialog (#l-col): none + the 12 tones, the shown tone pressed
const lp_dlgBtns = (cur, dis = '') => ['', ...LP_TONES.map(t => t[2])].map((c, i) => `<button type="button" style="background:${c || 'var(--bg4)'}" class="${(cur || '') === c ? 'on' : ''}" aria-pressed="${(cur || '') === c}" aria-label="${esc(c ? tr(LP_TONES[i - 1][1]) : tr('No color'))}" title="${esc(c ? tr(LP_TONES[i - 1][1]) : tr('No color'))}" data-c="${c}" ${dis}></button>`).join('');
// a new list: the folder's colour follows the folder field until a colour is picked by hand
document.addEventListener('click', e => { const b = e.target.closest?.('#l-col button'); if (b) b.closest('.modal')?.setAttribute('data-lptouch', '1'); });
document.addEventListener('input', e => {
  if (e.target.id !== 'l-folder') return;
  const md = e.target.closest('.modal'); if (!md || $('.lhdr', md) || md.dataset.lptouch) return;  // a new list only
  const c = lp_folderColor(fNorm(e.target.value));
  $$('#l-col button', md).forEach(b => { const on = b.dataset.c === c; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
});

// ---- after every render: the open list's colour as the accent of the list view; "Only as a dot" switches accent and card
// edges off
const LP_VARS = ['--lpd', '--lpid', '--lpl', '--lpil'];
// an element carrying a colour: the class on and the variables set ('a:b;c:d'), or both off ('')
function lp_put(el, cls, vars, names) {
  if (!el) return;
  el.classList.toggle(cls, !!vars);
  for (const n of names) el.style.removeProperty(n);
  if (vars) for (const p of vars.split(';')) { const [n, v] = p.split(':'); el.style.setProperty(n, v); }
}
function lp_sync() {
  document.body.classList.toggle('lp-dot', lp_dotOnly());
  const k = S.route?.mod === 'tasks' ? String(S.route.key || '') : '';
  const l = k.startsWith('l:') ? listById(+k.slice(2)) : null;
  const tone = !lp_dotOnly() && lp_tone(l);
  for (const el of [$('#main'), $('#fab')]) lp_put(el, 'lp-acc', tone ? lp_vars(tone) : '', LP_VARS);
  $('#main')?.classList.toggle('lp-one', !!l);  // one list open: its rows need no edge (the accent says it)
}
