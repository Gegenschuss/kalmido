// @ts-check
/* Kalmido web client: 2.353.0 D (#2759) file store and documents are ONE area "Ablage". Each folder shows as a list or as
   cards (the documents' tiles of docs.js, dc_card; the choice per folder and person: the setting ab_cards), recognition
   (text, sender, type, date) is switched per folder (subfolders inherit, like the rights) or started for one file
   ("Recognise"), and "All documents" / "To review" are saved filters below the folders (#ablage/docs, #ablage/review; ablage.js
   ab_panelHtml, on phones ab_docBtns; 2.752.0 #4887: a folder with recognition shows the documents' view, abd_foldHtml). A locked folder (part A: the node's field locked) never recognises, its cards show
   the names only. The rules live on the server (docs/recog.py); ablage.js calls in here only when this file is loaded.
   Loaded with the documents (lazyload.js, module docs). Classic script sharing the global scope with the others. */
'use strict';

const abd_on = () => feat('docs') && !S.me?.kid;
const abd_cardKeys = () => { try { const a = JSON.parse(S.settings?.ab_cards || '[]'); return Array.isArray(a) ? a : []; } catch { return []; } };
// asked for by ablage.js with typeof before this file may be loaded: function declarations (window properties), never const -
// a view drawn before the load kept seeing a const as missing (main red #3506: a new start showed the list, not the cards)
// 2.769.0 (#5340): a folder that recognises shows cards unless the person chose the list there ('!'+key in ab_cards); every
// other folder a list unless chosen as cards (key in ab_cards); the old values stay valid
function abd_cardsOn(key) { return abd_on() && (abd_recogHere(key) ? !abd_cardKeys().includes('!' + key) : abd_cardKeys().includes(key)); }
// 2.583.0 (#4832): a folder that recognises shows its content as document cards by default (2.769.0, #5340: with the switch,
// the list shows the documents' fields); known once the folder is loaded (its node), the cards load its documents' fields then
function abd_recogHere(key) { const n = AB.data?.node; return !!(n && AB.dkey === key && n.kind === 'folder' && n.recog_on && !abd_locked(n)); }
const abd_locked = n => !!n?.locked;  // part A (#2758): a locked folder and everything in it (a missing field = not locked)

// ---- list / cards per folder (all devices of the person: the setting ab_cards, changed by single entries)
async function abd_setCards(key, on) {
  const rec = abd_recogHere(key), k2 = rec ? '!' + key : key, add = rec ? !on : on;  // 2.769.0 (#5340): a recognising folder stores "list chosen"
  const ks = abd_cardKeys().filter(k => k !== k2);
  if (add) ks.push(k2);
  if (S.settings) S.settings.ab_cards = JSON.stringify(ks);
  ab_draw();  // 2.477.0 (#3936): the loaded entries drawn again at once (no new load; the cards fetch the documents' fields themselves when needed)
  try { await api('PATCH', '/api/settings', {set_delta: {ab_cards: add ? {add: [k2]} : {remove: [k2]}}}); } catch { /* shown; the local choice holds until the next load */ }
}
// the switch List | Cards (2.769.0, #5340: also above a recognising folder, ablage.js ab_foldTools)
const abd_viewSeg = c => `<div class="seg abviewseg" role="group" aria-label="${esc(tr('View'))}"><button type="button" data-abdv="list" aria-pressed="${!c}" class="${c ? '' : 'on'}" title="${esc(tr('List'))}">${ic('list', 's')}<span>${tr('List')}</span></button><button type="button" data-abdv="cards" aria-pressed="${c}" class="${c ? 'on' : ''}" title="${esc(tr('Cards'))}">${ic('grid', 's')}<span>${tr('Cards')}</span></button></div>`;
function abd_foldSeg(d) { return abd_on() && d?.node ? abd_viewSeg(abd_cardsOn('n:' + d.node.id)) : ''; }
function abd_toolsHtml(d, key) {
  if (!abd_on() || !d.items?.length) return '';
  const ts = abd_cardsOn(key) && typeof ts_barHtml === 'function' ? ts_barHtml() : '';  // 2.583.0 (#4812): the card size, the same as the documents'
  return ts + abd_viewSeg(abd_cardsOn(key));  // 2.769.0 (#5340): a recognising folder has its switch in ab_foldTools
}
// a card: a document = its tile of the documents (preview, sender, date, type, tags), other files and folders = name + picture
function abd_card(n) {
  const menuBtn = `<span class="abcmenu"><button data-rowmenu="dc-card" type="button" class="iconbtn" data-ab="menu" data-id="${n.id}" aria-label="${esc(tr('More actions for {0}', n.name))}" title="${esc(tr('More'))}">${ic('dots', 's')}</button></span>`;  // in a span: .dc-card>button is the tile
  const shc = typeof ab_shChip === 'function' ? ab_shChip(n, AB.data?.node?.owner_id) : '', sh = shc ? `<span class="abcshw">${shc}</span>` : '';  // 2.558.0 (#4693): the names, a click opens Share
  if (n.doc?.id && !abd_locked(n)) return dc_card(n.doc).replace(/<\/li>$/, menuBtn + sh + '</li>');
  const img = n.kind === 'file' && !abd_locked(n) && ab_isImg(n) && !upLocked(n) ? (typeof ts_img === 'function' ? ts_img(abd_thumbUrl(n), abd_thumbUrl(n) + '&size=l') /* 2.583.0 (#4812) */ : `<img src="${esc(abd_thumbUrl(n))}" alt="" loading="lazy">`) : '';
  const meta = abd_locked(n) ? '' : [n.kind === 'folder' ? '' : fmtSize(n.size || 0), ab_when(n.updated_at)].filter(Boolean).join(' · ');
  // 2.583.0 (#4832): the same card function as the documents (docs.js dc_card), a file opens the document view (ablage.js ab_openFile)
  return dc_card(n, {file: {thumb: img || `<span class="dc-ph">${ab_icon(n)}</span>`, meta, attrs: `data-ab="open" data-id="${n.id}"${n.kind === 'folder' ? ` data-abdrop="${n.id}"` : ''}`, after: menuBtn + sh}});
}
// 2.477.0 (#3936): a picture card shows the server's small preview, never the original (the version keeps the browser's copy fresh)
const abd_thumbUrl = n => `/api/files/nodes/${n.id}/thumb?v=${encodeURIComponent(n.version || 1)}`;
function abd_cardsHtml(d) {
  // loaded as a list: the cards draw at once, only documents among the entries need their fields (fetched behind, the cards stay)
  if (!AB.dq && !AB.loading && d.items.some(n => n.doc && !n.doc.id)) { AB.key = ''; setTimeout(ab_load, 0); }  // 2.477.0 (#3936)
  return abd_cardsHtml2(d);
}
const abd_cardsHtml2 = d => `<ul class="dc-grid abcards${AB.selOn ? ' dc-selon' : '' /* 2.768.0 (#4888) */}" aria-label="${esc(tr('Files'))}">${d.items.map(abd_card).join('')}</ul>`;

// ---- recognition: the line above a folder's list, the menu items, the switch
function abd_recogLine(d) {
  const n = d.node;
  if (!abd_on() || !n || abd_locked(n) || n.kind !== 'folder') return '';
  if (!n.recog_on && n.recog !== 'off') return '';  // nothing recognises here and nobody switched it off: no line
  const from = n.recog_on && n.recog !== 'on' ? (n.recog_from ? tr('as in “{0}”', n.recog_from) : n.recog_root ? tr('the documents folder') : '') : '';
  const txt = n.recog_on ? tr('Recognition on: text, sender, type and date of new files are recognised') : tr('Recognition off in this folder');
  return `<p class="muted abrecog">${ic('sparkle', 's')}<span>${esc(txt)}${from ? ` <small>(${esc(from)})</small>` : ''}</span>${ab_canWrite(n.role) ? `<button type="button" class="linkbtn" data-abdr="${n.id}">${tr('Change…')}</button>` : ''}</p>`;
}
// 2.683.0 (#5150): the documents of the folder in the order shown (its cards; in the list view its entries), the sheet leafs
// through them (docs.js dc_nav: "3 of 48", the arrows, the swipe); before, the sheet of the file store could not leaf at all
const abd_navIds = () => { const c = $$('.abview [data-dco]').map(x => +x.dataset.dco); return c.length ? c : (AB.data?.items || []).filter(n => n.doc && !abd_locked(n)).map(n => n.id); };  // 2.750.0 (#5228): the list's entries carry doc {state, review} without an id
function abd_menuItems(n) {
  if (!abd_on() || abd_locked(n) || !ab_canWrite(n.role)) return n.doc?.id && abd_on() ? [{label: tr('Open as document'), icon: 'file', fn: () => dc_open(n.id, {list: abd_navIds()})}] : [];
  if (n.kind === 'folder') return [{label: tr('Recognition…'), icon: 'sparkle', fn: () => setTimeout(() => abd_recogMenu(n), 0)}];  // after this menu closed
  if (n.kind !== 'file') return [];
  if (n.doc) return [{label: tr('Open as document'), icon: 'file', fn: () => dc_open(n.id, {list: abd_navIds()})}];
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
// ---- 2.752.0 (#4887): a folder with recognition = the documents' view of that folder (ablage.js viewAblage): the documents'
// bar (search, filter, sort, card size, Add / Scan into this folder), its subfolders as cards first, its documents (docs.js
// dc_bodyHtml: the server's list ?folder=, a search / filter ?under= takes the subfolders along, sorted and paged like all
// documents), then its files that are no documents (yet). The switch Files | Documents of phones (abd_navHtml) is gone: the
// bar of the spaces has "All documents" / "To review" (ablage.js ab_docBtns)
function abd_foldHtml(d) {
  const n = d.node, fresh = dc_ctxSet('f:' + n.id), open = !document.querySelector('.dc-infold');
  if (DC.ws != null && DC.ws !== dc_ws()) p61b_dcReset();
  if (!DC.loading && (fresh || (!DC.docs && !DC.err) || (open && Date.now() - (DC.at || 0) > 3000))) setTimeout(dc_load, 0);
  if (open && typeof dcv_restore === 'function') setTimeout(dcv_restore, 0);  // back from a document: the same place, its card in view
  const items = d.items || [], have = new Set((DC.docs || []).map(x => x.id));
  const kids = items.filter(x => x.kind === 'folder'), plain = items.filter(x => x.kind !== 'folder' && !(x.doc && !abd_locked(x)) && !have.has(x.id));
  const ul = xs => xs.length ? `<ul class="dc-grid abcards${AB.selOn ? ' dc-selon' : '' /* 2.768.0 (#4888) */}" aria-label="${esc(tr('Files'))}">${xs.map(abd_card).join('')}</ul>` : '';
  // 2.769.0 (#5340): the list chosen (the switch, ab_cards '!n:<id>'): the same documents, sort and filters as rows with their fields
  const list = !abd_cardsOn('n:' + n.id), li = xs => xs.map(abd_lRow).join('');
  const fold = {node: n, canAdd: ab_canWrite(n.role), before: list ? li(kids) : ul(kids), after: list ? li(plain) : ul(plain), card: abd_docCard, list: list ? abd_listHtml : null};
  return `<div class="dc-view dc-infold${list ? ' abdlon' : ''}" data-abfold="${n.id}">${dc_headHtml(fold)}${dc_bodyHtml(fold)}</div>`;
}
// ---- 2.769.0 (#5340): the list of a recognising folder: Name, Type, Sender, Date, Amount, To review (a header sorts like the
// documents' sort, docs.js dc_sortPick: the server sorts, the pages stay right); narrow screens: type, sender, date and amount as
// a second line below the name, the header gone (the bar's sort stays)
const ABD_COLS = [['title', N_('Name')], ['type', N_('Type')], ['sender', N_('Sender')], ['date', N_('Date')], ['amount', N_('Amount')], ['review', N_('To review')]];
function abd_listHtml(before, after) {
  const s = dc_sort();
  const head = ABD_COLS.map(([k, l]) => `<span role="columnheader" class="abdl-${k}" aria-sort="${s.k === k ? (s.d === 'asc' ? 'ascending' : 'descending') : 'none'}"><button type="button" class="abdlsort${s.k === k ? ' on' : ''}" data-abdls="${k}" title="${esc(tr('Sort by {0}', tr(l)))}">${esc(tr(l))}${s.k === k ? `<span aria-hidden="true">${s.d === 'asc' ? '↑' : '↓'}</span>` : ''}</button></span>`).join('');
  return `<div class="abdl${AB.selOn ? ' abdlsel' : ''}" role="table" aria-label="${esc(tr('Documents'))}"><div class="abdlrow abdlhead" role="row">${head}<span role="columnheader" class="abdl-act"></span></div>${before}${(DC.docs || []).map(abd_lDocRow).join('')}${after}</div>`;
}
const abd_lMenu = n => `<span role="cell" class="abdl-act"><button data-rowmenu="abrow" type="button" class="iconbtn" data-ab="menu" data-id="${n.id}" aria-label="${esc(tr('More actions for {0}', n.name))}" title="${esc(tr('More'))}">${ic('dots', 's')}</button></span>`;
const abd_lCells = c => ABD_COLS.slice(1).map(([k], i) => `<span role="cell" class="abdl-${k}">${c[i] || ''}</span>`).join('');  // c: html of Type .. To review
// a folder or a file that is no document (yet): its name (and the file's date) in the same columns
function abd_lRow(n) {
  const day = n.kind === 'folder' ? '' : ab_when(n.updated_at);
  const box = AB.selOn ? dc_selMark(n) : '', on = AB.selOn && AB.sel.has(n.id);  // 2.768.0 (#4888): the area's one selection
  return `<div class="abdlrow${on ? ' dc-on' : ''}" role="row" data-abid="${n.id}"><span role="cell" class="abdl-title">${box}<button type="button" class="abdlopen" data-ab="open" data-id="${n.id}"${n.kind === 'folder' ? ` data-abdrop="${n.id}"` : ''}>${ab_icon(n)}<span class="abtxt"><span class="abname">${esc(n.name)}</span>${day ? `<span class="abdlsub muted">${esc(day)}</span>` : ''}</span></button></span>${abd_lCells(['', '', day ? `<span class="muted">${esc(day)}</span>` : '', '', ''])}${abd_lMenu(n)}</div>`;
}
// a document: its recognised fields (a locked one: the name only, as its card)
function abd_lDocRow(doc) {
  const n = (AB.data?.items || []).find(x => x.id === doc.id), lk = !!n && abd_locked(n), on = AB.selOn && AB.sel.has(doc.id);
  const ty = lk ? '' : doc.type?.name || '', snd = lk ? '' : doc.sender?.name || '', day = lk ? '' : dc_day(doc.date), amt = lk || !doc.amount ? '' : dc_money(doc.amount, doc.currency);
  const st = lk ? '' : doc.review ? `<span class="abver abdoc rev">${tr('To review')}</span>` : doc.state === 'wait' || doc.state === 'run' ? `<span class="abver abdoc">${tr('Recognising…')}</span>` : '';
  const sub = [ty, snd, day, amt].filter(Boolean).map(esc).join(' · ');
  const box = AB.selOn ? dc_selMark(doc) : '';  // 2.768.0 (#4888): the area's one selection (ablage.js ab_selPick)
  return `<div class="abdlrow${doc.review ? ' rev' : ''}${on ? ' dc-on' : ''}${DC.lastId === doc.id ? ' dc-cur' : ''}" role="row" data-abid="${doc.id}"><span role="cell" class="abdl-title">${box}<button type="button" class="abdlopen" data-dco="${doc.id}">${ic(dc_isPdf(doc) ? 'pdf' : 'file')}<span class="abtxt"><span class="abname" title="${esc(doc.name)}">${esc(doc.name)}</span>${sub ? `<span class="abdlsub muted">${sub}</span>` : ''}</span></button></span>${abd_lCells([esc(ty), esc(snd), esc(day), esc(amt), st])}${n ? abd_lMenu(n) : '<span role="cell" class="abdl-act"></span>'}</div>`;
}
// a document of the folder: its card with the file store's menu and share names (an entry of the folder; one found in a
// subfolder by a search: the documents' card)
function abd_docCard(doc) {
  const n = (AB.data?.items || []).find(x => x.id === doc.id);
  if (!n || abd_locked(n)) return dc_card(doc);
  return abd_card({...n, doc});
}

// ---- events
document.addEventListener('click', e => {
  const t = /** @type {HTMLElement} */ (e.target);
  const v = /** @type {HTMLElement|null} */ (t.closest?.('.abview [data-abdv]'));
  if (v) { abd_setCards(AB.key || (S.route.nid ? 'n:' + S.route.nid : 's:' + ab_curSpace()), v.dataset.abdv === 'cards'); return; }
  const hs = /** @type {HTMLElement|null} */ (t.closest?.('.abview [data-abdls]'));  // 2.769.0 (#5340): a column header of the list sorts
  if (hs) { dc_sortPick(hs.dataset.abdls || 'date'); return; }
  const o = /** @type {HTMLElement|null} */ (t.closest?.('.abview [data-dco]'));  // a document's card: the document view (2.583.0, #4832/#4835; Back leads to the file store)
  if (o && !o.closest('.dc-infold')) { e.preventDefault(); dc_open(+o.dataset.dco, {list: abd_navIds()}); return; }  // 2.683.0 (#5150): + the folder's documents to leaf through; 2.752.0 (#4887): a folder with recognition: docs.js opens it
  const r = /** @type {HTMLElement|null} */ (t.closest?.('.abview [data-abdr]'));
  if (r) { const n = AB.data?.node; if (n && n.id === +r.dataset.abdr) abd_recogMenu(n, r); }
});
// 2.477.0 (#3936): a picture card whose small preview cannot be made (too big, unreadable) shows the picture icon, no broken image
document.addEventListener('error', e => {
  const img = /** @type {HTMLElement} */ (e.target);
  if (img?.tagName !== 'IMG' || !img.closest?.('.abcf .dc-th')) return;
  img.outerHTML = `<span class="dc-ph">${ic('picture')}</span>`;
}, true);
// 2.768.0 (#4888): a card's long press / right click is the area's one card menu (ablage.js ab_cardMenu, AB_CARDLP)
