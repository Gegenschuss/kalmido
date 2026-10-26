// @ts-check
/* Kalmido web client: 2.353.0 D (#2759) file store and documents are ONE area "Ablage". Each folder shows as a list or as
   cards (the documents' tiles of docs.js, dc_card; the choice per folder and person: the setting ab_cards), recognition
   (text, sender, type, date) is switched per folder (subfolders inherit, like the rights) or started for one file
   ("Recognise"), and "Documents" / "To review" are saved filters below the folders (#docs, #docs/review; ablage.js
   ab_panelHtml, on phones abd_navHtml). A locked folder (part A: the node's field locked) never recognises, its cards show
   the names only. The rules live on the server (docs/recog.py); ablage.js calls in here only when this file is loaded.
   Loaded with the documents (lazyload.js, module docs). Classic script sharing the global scope with the others. */
'use strict';

const abd_on = () => feat('docs') && !S.me?.kid;
const abd_cardKeys = () => { try { const a = JSON.parse(S.settings?.ab_cards || '[]'); return Array.isArray(a) ? a : []; } catch { return []; } };
const abd_cardsOn = key => abd_on() && abd_cardKeys().includes(key);
const abd_locked = n => !!n?.locked;  // part A (#2758): a locked folder and everything in it (a missing field = not locked)

// ---- list / cards per folder (all devices of the person: the setting ab_cards, changed by single entries)
async function abd_setCards(key, on) {
  const ks = abd_cardKeys().filter(k => k !== key);
  if (on) ks.push(key);
  if (S.settings) S.settings.ab_cards = JSON.stringify(ks);
  AB.key = ''; ab_load();
  try { await api('PATCH', '/api/settings', {set_delta: {ab_cards: on ? {add: [key]} : {remove: [key]}}}); } catch { /* shown; the local choice holds until the next load */ }
}
function abd_toolsHtml(d, key) {
  if (!abd_on() || !d.items?.length) return '';
  const c = abd_cardsOn(key);
  return `<div class="seg abviewseg" role="group" aria-label="${esc(tr('View'))}"><button type="button" data-abdv="list" aria-pressed="${!c}" class="${c ? '' : 'on'}" title="${esc(tr('List'))}">${ic('list', 's')}<span>${tr('List')}</span></button><button type="button" data-abdv="cards" aria-pressed="${c}" class="${c ? 'on' : ''}" title="${esc(tr('Cards'))}">${ic('grid', 's')}<span>${tr('Cards')}</span></button></div>`;
}
// a card: a document = its tile of the documents (preview, sender, date, type, tags), other files and folders = name + picture
function abd_card(n) {
  const menuBtn = `<span class="abcmenu"><button type="button" class="iconbtn" data-ab="menu" data-id="${n.id}" aria-label="${esc(tr('More actions for {0}', n.name))}" title="${esc(tr('More'))}">${ic('dots', 's')}</button></span>`;  // in a span: .dc-card>button is the tile
  if (n.doc?.id && !abd_locked(n) && typeof dc_card === 'function') return dc_card(n.doc).replace(/<\/li>$/, menuBtn + '</li>');
  const img = n.kind === 'file' && !abd_locked(n) && ab_isImg(n) && !upLocked(n) ? `<img src="${esc(ab_url(n))}" alt="" loading="lazy">` : '';
  const meta = abd_locked(n) ? '' : [n.kind === 'folder' ? '' : fmtSize(n.size || 0), ab_when(n.updated_at)].filter(Boolean).join(' · ');
  return `<li class="dc-card abcf"><button type="button" data-ab="open" data-id="${n.id}" ${n.kind === 'folder' ? `data-abdrop="${n.id}"` : ''} aria-label="${esc(n.name)}"><span class="dc-th">${img || `<span class="dc-ph">${ab_icon(n)}</span>`}</span><span class="dc-ct"><b class="dc-nm">${esc(n.name)}</b>${meta ? `<span class="dc-mt">${esc(meta)}</span>` : ''}</span></button>${menuBtn}</li>`;
}
const abd_cardsHtml = d => {
  if (!AB.dq && !AB.loading) { AB.key = ''; setTimeout(ab_load, 0); }  // loaded as a list before this file was there: again with the documents' fields
  return abd_cardsHtml2(d);
};
const abd_cardsHtml2 = d => `<ul class="dc-grid abcards" aria-label="${esc(tr('Files'))}">${d.items.map(abd_card).join('')}</ul>`;

// ---- recognition: the line above a folder's list, the menu items, the switch
function abd_recogLine(d) {
  const n = d.node;
  if (!abd_on() || !n || abd_locked(n) || n.kind !== 'folder') return '';
  if (!n.recog_on && n.recog !== 'off') return '';  // nothing recognises here and nobody switched it off: no line
  const from = n.recog_on && n.recog !== 'on' ? (n.recog_from ? tr('as in “{0}”', n.recog_from) : n.recog_root ? tr('the documents folder') : '') : '';
  const txt = n.recog_on ? tr('Recognition on: text, sender, type and date of new files are recognised') : tr('Recognition off in this folder');
  return `<p class="muted abrecog">${ic('sparkle', 's')}<span>${esc(txt)}${from ? ` <small>(${esc(from)})</small>` : ''}</span>${ab_canWrite(n.role) ? `<button type="button" class="linkbtn" data-abdr="${n.id}">${tr('Change…')}</button>` : ''}</p>`;
}
function abd_menuItems(n) {
  if (!abd_on() || abd_locked(n) || !ab_canWrite(n.role)) return n.doc?.id && abd_on() ? [{label: tr('Open as document'), icon: 'file', fn: () => dc_open(n.id, {keep: true})}] : [];
  if (n.kind === 'folder') return [{label: tr('Recognition…'), icon: 'sparkle', fn: () => setTimeout(() => abd_recogMenu(n), 0)}];  // after this menu closed
  if (n.kind !== 'file') return [];
  if (n.doc) return [{label: tr('Open as document'), icon: 'file', fn: () => dc_open(n.id, {keep: true})}];
  return [{label: tr('Recognise'), icon: 'sparkle', fn: () => abd_recognise(n)}];  // a file outside a recognising folder
}
function abd_recogMenu(n, anchor) {
  const own = n.recog || '', set = m => () => abd_recogSet(n, m);
  anchor = anchor || $(`[data-abid="${n.id}"] [data-ab="menu"]`) || $(`[data-abdr="${n.id}"]`) || $('[data-ab="menu"]') || document.body;
  menu(anchor, [{head: tr('Recognition')},
    {label: tr('As the folder above'), sub: tr('Subfolders follow their folder, like the rights'), on: !own, fn: set('inherit')},
    {label: tr('On'), sub: tr('Files in it and in its subfolders become documents'), on: own === 'on', fn: set('on')},
    {label: tr('Off'), sub: tr('New files stay plain files; documents stay documents'), on: own === 'off', fn: set('off')}], null, null, tr('Recognition'));
}
async function abd_recogSet(n, mode) {
  const was = n.recog || 'inherit';
  if (mode === was) return;
  let r; try { r = await api('PUT', `/api/files/nodes/${n.id}/recognition`, {mode}); } catch { return; }
  ab_reload();
  const msg = r.recog?.on ? (r.added ? trn('Recognition on: {0} file is being recognised', 'Recognition on: {0} files are being recognised', r.added) : tr('Recognition on for “{0}”', n.name)) : tr('Recognition off for “{0}”', n.name);
  offerUndo(msg, histAdd({label: tr('Recognition of “{0}”', n.name), undo: () => ab_req('PUT', `/api/files/nodes/${n.id}/recognition`, {mode: was}), redo: () => ab_req('PUT', `/api/files/nodes/${n.id}/recognition`, {mode})}));
}
async function abd_recognise(n) {
  try { await api('PUT', `/api/files/nodes/${n.id}/recognition`, {mode: 'on'}); } catch { return; }
  ab_reload(); toast(tr('“{0}” is being recognised', n.name));
}
// the mark of a document in the list: being recognised / to review / recognised
function abd_badge(n) {
  if (!n.doc || !abd_on()) return '';
  if (n.doc.review) return `<span class="abver abdoc rev" title="${esc(tr('Recognised values wait for your check'))}">${tr('To review')}</span>`;
  if (n.doc.state === 'wait' || n.doc.state === 'run') return `<span class="abver abdoc">${tr('Recognising…')}</span>`;
  return `<span class="abbadge abdoc" title="${esc(tr('Document: recognised'))}" aria-label="${esc(tr('Document: recognised'))}">${ic('sparkle', 's')}</span>`;
}
// ---- the saved filters on phones (a computer: the panel, ablage.js): below the spaces of the file store; in the documents'
// view the way back to the file store
function abd_navHtml(inAb) {
  if (!abd_on() || (typeof sbb_on === 'function' && sbb_on())) return '';
  const r = S.route, rv = DC.review ? ` <span class="dc-count">${DC.review}</span>` : '';
  const b = (go, icon, name, on, after = '') => `<button type="button" class="abspace abfilt ${on ? 'on' : ''}" data-go="${go}" ${on ? 'aria-current="page"' : ''}>${ic(icon, 's')}<span>${esc(name)}</span>${after}</button>`;
  const fs = b('docs', 'file', tr('Documents'), r.mod === 'docs' && !r.review) + b('docs/review', 'check', tr('To review'), r.mod === 'docs' && !!r.review, rv);
  return inAb ? fs : `<nav class="abspaces abdnav" aria-label="${esc(tr('File store'))}">${b('ablage', 'folder', tr('Files'), false)}${fs}</nav>`;
}

// ---- events
document.addEventListener('click', e => {
  const t = /** @type {HTMLElement} */ (e.target);
  const v = /** @type {HTMLElement|null} */ (t.closest?.('.abview [data-abdv]'));
  if (v) { abd_setCards(AB.key || (S.route.nid ? 'n:' + S.route.nid : 's:' + ab_curSpace()), v.dataset.abdv === 'cards'); return; }
  const o = /** @type {HTMLElement|null} */ (t.closest?.('.abview [data-dco]'));  // a document's card: its sheet over the file store (the route stays)
  if (o) { e.preventDefault(); dc_open(+o.dataset.dco, {keep: true}); return; }
  const r = /** @type {HTMLElement|null} */ (t.closest?.('.abview [data-abdr]'));
  if (r) { const n = AB.data?.node; if (n && n.id === +r.dataset.abdr) abd_recogMenu(n, r); }
});
