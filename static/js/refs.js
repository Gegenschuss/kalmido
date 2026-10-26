/* Kalmido web client: references between things (2.53.0, #1449 #1440). Classic script sharing the global scope with the others.
   - Drag a list / folder (sidebar), a task (list, calendar), a file (Ablage), a contact or an event onto the comment field or
     the description: a reference is put in at the drop point (a task as "#123", the rest as a Markdown link to this app).
   - A link to this app (#l/, #folder/, #t/, #contacts/, #ev/, #ablage/) is drawn as a small card with the kind's icon and the
     name the READER sees (client state or the read routes, which check the access); the label the author typed is never
     shown, a target the reader cannot see (or a deleted one) is a grey "No access" card without a name.
   - Phone / touch: a button "Insert reference" at the comment box and the description opens the search (palette mode 'ref').
   - 2.147.1 A (#2523): the same drop and button in the chat boxes (team chat, thread, agent chat, also a parked window of the
     split panel); several selected tasks dragged at once go in as several references.
   - Mouse only: resting on a task number or a card for 0.4 s shows a preview card next to the pointer. */
'use strict';

const RF_MIME = 'application/x-kalmido-ref';
const RF_KEY_RE = /^(?:[ltcef]:\d{1,9}|d:[^\n]{1,300})$/;
const RF_ICON = {l: 'list', d: 'folder', t: 'check', c: 'user', e: 'cal', f: 'file'};
const RF = {cache: new Map(), wait: new Map(), ta: null, tael: null, at: null, ct: null, ctq: null, ev: null};
const RF_TTL = 5 * 60e3;  // a fetched name is used for five minutes (renames show after that or a reload)

// ---- keys: "l:80" list, "d:<path>" folder, "t:5" task, "c:3" contact, "e:7" event, "f:12" file / folder in the Ablage
function rf_keyOfHash(h) {  // "#l/80" -> "l:80" (only the routes a reference card stands for), else null
  const m = /^#(l|t|ev|contacts|ablage|folder)\/(.+)$/.exec(h || ''); if (!m) return null;
  if (m[1] === 'folder') { let p; try { p = decodeURIComponent(m[2]); } catch { return null; } return p && p.length <= 300 && !p.includes('\n') ? 'd:' + p : null; }
  if (!/^\d{1,9}$/.test(m[2])) return null;
  return ({l: 'l', t: 't', ev: 'e', contacts: 'c', ablage: 'f'})[m[1]] + ':' + m[2];
}
const rf_enc = s => encodeURIComponent(s).replace(/[!'()*]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase());
function rf_hashOf(k) {
  const v = k.slice(2);
  return {l: 'l/', t: 't/', e: 'ev/', c: 'contacts/', f: 'ablage/', d: 'folder/'}[k[0]] + (k[0] === 'd' ? rf_enc(v) : v);
}
// the text that goes into the field: a task as "#123", the rest as [name](link); brackets in the name would end the label
function rf_text(k, name) {
  if (k[0] === 't') return '#' + k.slice(2);
  const n = String(name || '').replace(/[\[\]]/g, m => (m === '[' ? '(' : ')')).replace(/\s+/g, ' ').trim().slice(0, 80) || tr(rf_kindName(k));
  return `[${n}](${location.origin}/#${rf_hashOf(k)})`;
}
const rf_kindName = k => ({l: N_('Project'), d: N_('Folder'), t: N_('Task'), c: N_('Contact'), e: N_('Appointment'), f: N_('Document')})[k[0]];

// ---- what the reader sees: undefined = not known yet (asked), null = no access / gone, else the object
function rf_get(k) {
  const id = +k.slice(2);
  if (k[0] === 'l') { const l = listById(id); return l ? {name: lname(l), l} : null; }
  if (k[0] === 'd') { const p = k.slice(2); return folderNames().includes(p) ? {name: fName(p), path: p} : null; }
  if (k[0] === 't') { const t = taskById(id); if (t && !t.deleted_at) return {name: mdPlain(t.title), t}; }  // 2.280.0 F (#3108): the card from the local task; only the preview loads a long note (rf_pvShow)
  const c = RF.cache.get(k);
  if (c && Date.now() - c.at < RF_TTL) return c.v;
  rf_fetch(k);
  return c ? c.v : undefined;
}
const RF_URL = {t: id => `/api/tasks/${id}`, c: id => `/api/contacts/${id}`, e: id => `/api/events/${id}`, f: id => `/api/files/nodes/${id}`};
function rf_fetch(k) {
  if (RF.wait.has(k) || !RF_URL[k[0]]) return RF.wait.get(k);
  const p = rawFetch('GET', RF_URL[k[0]](+k.slice(2))).then(j => rf_norm(k, j), e => (e instanceof Offline || !e.status || e.status >= 500 ? undefined : null))
    .then(v => { RF.wait.delete(k); RF.cache.set(k, {v, at: v === undefined ? Date.now() - RF_TTL + 30e3 : Date.now()}); rf_paint(k); return v; });  // offline: asked again in 30 s
  RF.wait.set(k, p);
  return p;
}
function rf_norm(k, j) {  // the read route's answer -> {name, …}; a deleted / trashed target counts as gone
  if (!j || j.deleted_at || j.in_trash) return null;
  if (k[0] === 't') return {name: mdPlain(j.title), t: j};
  if (k[0] === 'c') return {name: j.fn || j.org || '', c: j};
  if (k[0] === 'e') return {name: j.title || '', e: j};
  if (k[0] === 'f') return {name: j.name || '', f: j};
  return null;
}
// ---- the card in rendered text (attachments.js mdLink asks for it for every link to this app)
function rf_card(hash) { const k = rf_keyOfHash(hash); return k ? rf_cardHtml(k) : null; }
function rf_cardHtml(k) {
  const v = rf_get(k), icn = ic(RF_ICON[k[0]], 's'), a = esc(k);
  if (v === null) return `<span class="rfcard rfno" data-rf="${a}" title="${esc(tr(rf_kindName(k)))}">${icn}<span class="rfn">${esc(tr('No access'))}</span></span>`;
  const tid = k[0] === 't' ? ` data-tref="${k.slice(2)}"` : '', done = k[0] === 't' && v?.t?.status ? ' rfdone' : '';
  if (v === undefined) return `<a href="#${esc(rf_hashOf(k))}" class="rfcard rfwait" data-rf="${a}"${tid}>${icn}<span class="rfn">…</span></a>`;
  return `<a href="#${esc(rf_hashOf(k))}" class="rfcard${done}" data-rf="${a}"${tid}>${icn}<span class="rfn">${esc(String(v.name || tr(rf_kindName(k))).slice(0, 80))}</span></a>`;
}
function rf_paint(k) {
  for (const el of document.querySelectorAll(`[data-rf="${CSS.escape(k)}"]`)) if (el.classList.contains('rfcard')) el.outerHTML = rf_cardHtml(k);
}

// ---- drag sources: an own format next to what the old drags set (nothing of theirs is changed)
function rf_srcKey(el) {
  if (!el?.closest) return null;
  let r;
  if ((r = el.closest('#side .srow[data-list]'))) return {k: 'l:' + +r.dataset.list};
  if ((r = el.closest('#side .fhead[data-folder]'))) return {k: 'd:' + r.dataset.folder};
  if ((r = el.closest('.trow[data-id], .cal .ev[data-id], .week .ev[data-id], .wev[data-id]')) && +r.dataset.id > 0) return {k: 't:' + +r.dataset.id};
  if ((r = el.closest('.abrow[data-abid]'))) return {k: 'f:' + +r.dataset.abid, n: r.querySelector('.abname')?.textContent || ''};
  if ((r = el.closest('.ctrow[data-ctopen]'))) return {k: 'c:' + +r.dataset.ctopen, n: r.querySelector('.ctn b, b')?.textContent || ''};
  if ((r = el.closest('[data-cev]')) && /^\d+$/.test(r.dataset.cev)) return {k: 'e:' + +r.dataset.cev, n: r.querySelector('.cevn')?.textContent || r.getAttribute('title') || ''};
  return null;
}
// 2.147.1 A (#2523): the chat boxes (the live ids and a parked window's data-cwid, chatwins.js) and the team chat's inline edit
const RF_CHAT = ['tc-in', 'tth-in', 'chat-in'];
const RF_TA_SEL = '#c-input, #d-content, .c-edit-input, .tc-edit, ' + RF_CHAT.map(i => `#${i}, [data-cwid="${i}"]`).join(', ');
// contacts and calendar entries are no drag sources of their own: while a comment box / description is on screen they
// become draggable under the mouse (not an event the calendar moves by pointer, .cgok)
const RF_DYN = '.ctrow[data-ctopen], .cevrow[data-cev], .cev[data-cev]:not(.cgok)';
document.addEventListener('pointerover', e => {
  if (e.pointerType !== 'mouse') return;
  const r = e.target.closest?.(RF_DYN);
  if (r && !r.hasAttribute('draggable') && document.querySelector(RF_TA_SEL)) r.setAttribute('draggable', 'true');  // 2.147.1 A (#2523): + the chat boxes
});
document.addEventListener('dragstart', e => {
  const s = rf_srcKey(e.target); if (!s || !RF_KEY_RE.test(s.k) || !e.dataTransfer) return;
  // 2.147.1 A (#2523): a drag that takes the whole selection (dragmulti.js) carries all selected tasks, in the order seen
  const id = s.k[0] === 't' ? +s.k.slice(2) : 0;
  if (id && e.target.closest?.('#view .trow') && S.multi?.size >= 2 && S.multi.has(id)) {
    const ids = typeof dgOrder === 'function' ? dgOrder([...S.multi]) : [...S.multi];
    s.ks = ids.filter(i => i > 0 && S.tasks.has(i)).slice(0, 50).map(i => 't:' + i);
  }
  try { e.dataTransfer.setData(RF_MIME, JSON.stringify(s)); } catch { return; }
  if (e.target.closest?.(RF_DYN)) { e.dataTransfer.effectAllowed = 'copy'; e.dataTransfer.setData('text/plain', rf_text(s.k, s.n)); }
}, true);
const rf_has = e => !!e.dataTransfer && [...(e.dataTransfer.types || [])].includes(RF_MIME);
function rf_dropTa(el) {  // the field a reference may be dropped into (only these; everything else keeps its old drop)
  const ta = el?.closest?.(RF_TA_SEL);  // 2.147.1 A (#2523): + the chat boxes
  if (ta) return ta.readOnly || ta.disabled ? null : ta;
  if (el?.closest?.('#detail #d-md')) { const d = document.getElementById('d-content'); return d && !d.readOnly ? d : null; }
  return null;
}
// window, capture: before every drop handler of the page (dnd.js, sidebar.js, ablage.js), only over the text fields
window.addEventListener('dragover', e => {
  if (!rf_has(e) || !rf_dropTa(e.target)) return;
  e.preventDefault(); e.stopPropagation();
}, true);
window.addEventListener('drop', e => {
  if (!rf_has(e)) return;
  const ta = rf_dropTa(e.target); if (!ta) return;
  e.preventDefault(); e.stopPropagation();
  let s; try { s = JSON.parse(e.dataTransfer.getData(RF_MIME)); } catch { return; }
  if (!s || typeof s.k !== 'string' || !RF_KEY_RE.test(s.k)) return;
  const v = rf_get(s.k), name = v?.name || s.n || '';
  // 2.147.1 A (#2523): several tasks = several references, one space apart
  const ks = Array.isArray(s.ks) ? s.ks.filter(k => typeof k === 'string' && /^t:\d{1,9}$/.test(k)).slice(0, 50) : [];
  const txt = ks.length > 1 ? ks.map(k => rf_text(k)).join(' ') : rf_text(s.k, name);
  if (ta.classList.contains('hidden')) { editContent(); rf_insert(ta, txt); return; }  // the rendered description
  // a parked chat window (data-cwid) becomes the live one by the focus in rf_insert (chatwins.js), ids swap in place
  rf_insert(ta, txt, rf_caretAt(ta, e.clientX, e.clientY));
}, true);
function rf_caretAt(ta, x, y) {
  try { const p = document.caretPositionFromPoint?.(x, y); if (p && p.offsetNode === ta) return p.offset; } catch { /* old browser */ }
  return document.activeElement === ta ? ta.selectionStart : ta.value.length;
}
// one step for the field's own undo (insertText), the field's input handler saves it like typing
function rf_insert(ta, txt, at) {
  const v = ta.value; at = Math.max(0, Math.min(at ?? v.length, v.length));
  const s = (at && !/\s/.test(v[at - 1]) ? ' ' : '') + txt + (at < v.length && /\s/.test(v[at]) ? '' : ' ');
  ta.focus(); ta.setSelectionRange(at, at);
  let ok = false; try { ok = document.execCommand('insertText', false, s); } catch { /* not supported */ }
  if (!ok || ta.value === v) { ta.setRangeText(s, at, at, 'end'); ta.dispatchEvent(new Event('input', {bubbles: true})); }
  if (typeof autosize === 'function') autosize(ta);
}

// ---- touch: "Insert reference" opens the search; a pick goes in at the cursor of that field
function rf_btnHtml(where, off) {
  if (off || !isTouch()) return '';
  const l = esc(tr('Insert reference'));
  // 2.147.1 A (#2523): the chat boxes ('tc-in', 'tth-in', 'chat-in') get the same quiet button in their row
  return where === 'c' || RF_CHAT.includes(where) ? `<button type="button" class="iconbtn rfins" data-rfins="${where}" title="${l}" aria-label="${l}">${ic('link', 's')}</button>`
    // the description's button as a quiet link row like "Lock note" (a .btn there widened the narrow panel, p252_ui)
    : `<div class="lnbar rfinsbar"><button type="button" class="linkbtn lnlock rfins" data-rfins="d">${ic('link', 's')}<span>${l}</span></button></div>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-rfins]'); if (!b) return;
  e.preventDefault();
  const w = b.dataset.rfins, ci = RF_CHAT.includes(w);
  // 2.147.1 A (#2523): a chat button takes the box of its own row (a parked window's box carries data-cwid)
  const ta = ci ? b.closest('.chcomp')?.querySelector(`#${w}, [data-cwid="${w}"]`) : document.getElementById(w === 'c' ? 'c-input' : 'd-content');
  if (!ta || ta.readOnly || ta.disabled) return;
  RF.ta = ta.id || w; RF.tael = ci ? ta : null; RF.at = document.activeElement === ta ? ta.selectionStart : null;
  rf_palReset(); openPalette('ref');
});
function rf_pick(k, name) {
  const ta = RF.tael?.isConnected ? RF.tael : document.getElementById(RF.ta); if (!ta || ta.disabled) return;  // 2.147.1 A (#2523): the chat box itself (redrawn: by its id)
  if (ta.classList.contains('hidden')) editContent();
  rf_insert(ta, rf_text(k, name), RF.at);
}
// palette.js palItems asks this in mode 'ref': lists, folders, tasks (client state), contacts (asked per text), the
// events of the coming months and the open Ablage folder's files; nothing that only the server could see without access
function rf_palItems(q) {
  q = String(q || '').trim();
  const it = [], add = (k, kind, label, icon, extra = {}) => it.push({id: 'rf:' + k, kind, label, icon, fn: () => rf_pick(k, label), ...extra});
  for (const l of S.lists.filter(x => !x.archived && !x.is_inbox)) add('l:' + l.id, 'list', lname(l), 'list', {lic: l, sw: cssColor(l.color), ...(l.folder ? {sub: fDisp(l.folder)} : {})});
  for (const f of folderNames()) add('d:' + f, 'folder', fDisp(f), 'folder');
  for (const t of S.tasks.values()) if (t.id > 0 && !t.status && !archivedTask(t)) add('t:' + t.id, 'tasks', mdPlain(t.title), 'check', {sub: '#' + t.id + (t.list_id ? '  ·  ' + lname(listById(t.list_id)) : '')});
  for (const c of RF.ct || []) add('c:' + c.id, 'Contact', c.fn || c.org || '', 'user', {sub: c.org || ''});
  for (const e of RF.ev || []) add('e:' + e.id, 'Appointment', e.title || '', 'cal', {sub: e.start ? dayLabel(String(e.start).slice(0, 10)) : ''});
  for (const n of (typeof AB !== 'undefined' && AB.data?.items) || []) if (n.kind !== 'link' && !(n.locked && n.lock_id !== n.id)) add('f:' + n.id, 'Document', n.name, n.kind === 'folder' ? 'folder' : 'file');  // 2.353.0 F (#2758, review M7): no decrypted name of a locked folder into a text
  rf_palAsk(q);
  if (!q) return it.filter(x => x.kind === 'list').slice(0, 12).concat(it.filter(x => x.kind === 'tasks').slice(0, 8));
  const nm = q.match(/^#?(\d{1,9})$/), hit = nm && taskById(+nm[1]);
  const hits = it.map(x => ({...x, score: Math.max(fuzzy(q, x.label), x.sub ? fuzzy(q, x.sub) * 0.3 : 0)})).filter(x => x.score > 0).sort((a, b) => b.score - a.score).slice(0, 60);
  return hit ? [{id: 'rf:t:' + hit.id, kind: 'tasks', label: `#${hit.id} ${mdPlain(hit.title)}`, icon: 'hash', fn: () => rf_pick('t:' + hit.id)}, ...hits] : hits;
}
function rf_palAsk(q) {  // contacts per text (debounced), the events once per opening
  const redraw = () => { if (typeof PAL !== 'undefined' && PAL.mode === 'ref' && document.querySelector('.palette')) palDraw(); };
  if (RF.ev === null && feat('cal')) {
    RF.ev = [];
    rawFetch('GET', `/api/events?from=${ds(new Date(Date.now() - 30 * 864e5))}&to=${ds(new Date(Date.now() + 120 * 864e5))}`)
      .then(j => { RF.ev = (j.items || []).filter((x, i, a) => a.findIndex(y => y.id === x.id) === i).slice(0, 300); redraw(); }).catch(() => {});
  }
  if (q.length < 2 || q === RF.ctq) return;
  RF.ctq = q; clearTimeout(rf_palAsk.t);
  rf_palAsk.t = setTimeout(() => rawFetch('GET', `/api/contacts?limit=8&q=${encodeURIComponent(q)}`).then(j => { if (RF.ctq === q) { RF.ct = j.items || []; redraw(); } }).catch(() => {}), 250);
}
function rf_palReset() { RF.ct = null; RF.ctq = null; RF.ev = null; }

// ---- #1440 the preview card (mouse only)
const RFH = {t: 0, hide: 0, a: null, el: null, x: 0, y: 0};
const RF_HOV = 'a[data-tref], a.rfcard[data-rf]';
// only a real mouse (a tap on a phone / tablet is pointerType "touch" / "pen" and keeps opening the target at once)
document.addEventListener('pointerover', e => {
  if (e.pointerType !== 'mouse') return;
  if (e.target.closest?.('.rfpv')) { clearTimeout(RFH.hide); return; }
  const a = e.target.closest?.(RF_HOV); if (!a || a.closest('.rfpv')) return;
  clearTimeout(RFH.hide);
  if (a === RFH.a) return;
  if (a.title) { a.dataset.rftitle = a.title; a.removeAttribute('title'); }  // no browser tooltip on top of the card
  RFH.x = e.clientX; RFH.y = e.clientY;
  clearTimeout(RFH.t); RFH.t = setTimeout(() => rf_pvShow(a), 400);
  RFH.wait = a;
});
document.addEventListener('pointermove', e => { if (RFH.wait && !RFH.a && e.pointerType === 'mouse') { RFH.x = e.clientX; RFH.y = e.clientY; } }, {passive: true});
document.addEventListener('pointerout', e => {
  const a = e.target.closest?.(`${RF_HOV}, .rfpv`); if (!a || (e.relatedTarget && a.contains(e.relatedTarget))) return;
  if (a === RFH.wait && !RFH.a) { clearTimeout(RFH.t); RFH.wait = null; rf_title(a); return; }
  if (RFH.a || RFH.el) { clearTimeout(RFH.hide); RFH.hide = setTimeout(rf_pvHide, 200); }
});
const rf_title = a => { if (a?.dataset.rftitle) { a.title = a.dataset.rftitle; delete a.dataset.rftitle; } };
for (const ev of ['scroll', 'wheel']) window.addEventListener(ev, () => { if (RFH.el || RFH.wait) rf_pvHide(); }, {capture: true, passive: true});
document.addEventListener('keydown', e => { if (e.key === 'Escape' && RFH.el) rf_pvHide(); });
document.addEventListener('pointerdown', e => { if (RFH.el && !e.target.closest?.('.rfpv')) rf_pvHide(); }, true);
function rf_pvHide() {
  clearTimeout(RFH.t); clearTimeout(RFH.hide);
  rf_title(RFH.a); rf_title(RFH.wait);
  const el = RFH.el; RFH.el = RFH.a = RFH.wait = null;
  if (el) { el.classList.remove('on'); setTimeout(() => el.remove(), reducedMotion() ? 0 : 160); }
}
function rf_keyOfEl(a) { return a.dataset.rf || (a.dataset.tref ? 't:' + a.dataset.tref : null); }
function rf_pvShow(a) {
  if (!a.isConnected) return;
  const k = rf_keyOfEl(a); if (!k || !RF_KEY_RE.test(k)) return;
  $$('.rfpv').forEach(x => x.remove());
  const el = document.createElement('div');
  el.className = 'rfpv'; el.setAttribute('role', 'tooltip');
  document.body.appendChild(el);
  RFH.a = a; RFH.el = el; RFH.wait = null;
  el.addEventListener('click', () => { const x = RFH.a; rf_pvHide(); x?.click(); });
  const draw = () => { if (RFH.el !== el) return; el.innerHTML = rf_pvHtml(k); rf_pvPlace(el, RFH.x, RFH.y); };
  draw();
  requestAnimationFrame(() => el.classList.add('on'));
  if (rf_get(k) === undefined) rf_fetch(k)?.then(draw);
  else if (k[0] === 't' && typeof tkNoteMissing === 'function' && tkNoteMissing(taskById(+k.slice(2)))) tkNoteLoad(+k.slice(2)).then(draw, () => {});  // 2.280.0 F (#3108): a long note not in the state
}
function rf_pvPlace(el, x, y) {  // next to the pointer, to the other side at the screen's edge, always inside it
  const w = el.offsetWidth, h = el.offsetHeight, vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
  let l = x + 14, t = y + 18;
  if (l + w > vw - 8) l = x - 14 - w;
  if (t + h > vh - 8) t = y - 12 - h;
  el.style.left = Math.round(Math.max(8, Math.min(l, vw - w - 8))) + 'px';
  el.style.top = Math.round(Math.max(8, Math.min(t, vh - h - 8))) + 'px';
}
function rf_pvHtml(k) {
  const v = rf_get(k), head = (icn, title, cls = '') => `<div class="rfpvh ${cls}">${ic(icn, 's')}<b>${esc(title)}</b></div>`;
  if (v === undefined) return head(RF_ICON[k[0]], tr('Loading…'));
  if (v === null) return head(RF_ICON[k[0]], tr('No access'), 'rfno');
  const rows = [], line = (i, txt) => txt && rows.push(`<div class="rfpvr">${ic(i, 's')}<span>${esc(txt)}</span></div>`);
  if (k[0] === 't') {
    const t = v.t, kids = S.tasks.has(t.id) ? children(t.id) : [], l = listById(t.list_id);
    line('list', l ? lname(l) : '');
    if (t.priority && PRIO_NAMES[t.priority]) line('flag', tr('Priority') + ': ' + tr(PRIO_NAMES[t.priority]));
    if (t.due) line('cal', dayLabel(t.due) + (t.due_time ? ' ' + t.due_time : ''));
    if (t.assignee_id) line('user', personNameAny(t.assignee_id));
    if (t.tags?.length) line('tag', t.tags.map(g => '#' + g).join(' '));
    if (kids.length) line('sub', tr('{0} of {1} subtasks done', kids.filter(x => x.status).length, kids.length));
    const n = [t.comment_count ? trn('{0} comment', '{0} comments', t.comment_count) : '', t.attachments?.length ? trn('{0} attachment', '{0} attachments', t.attachments.length) : ''].filter(Boolean).join('  ·  ');
    line('comment', n);
    const d = mdPlain(String(t.content || '')).replace(/\s+/g, ' ').trim().slice(0, 300);
    return head(t.status ? 'done' : 'check', `#${t.id} ${v.name}`, t.status ? 'rfdone' : '') + rows.join('') + (d ? `<div class="rfpvd">${esc(d)}</div>` : '');
  }
  if (k[0] === 'l') {
    const n = [...S.tasks.values()].filter(t => t.list_id === v.l.id && !t.status).length;
    line('folder', v.l.folder ? fDisp(v.l.folder) : '');
    line('check', trn('{0} open task', '{0} open tasks', n));
    return head('list', v.name) + rows.join('');
  }
  if (k[0] === 'd') {
    const ls = S.lists.filter(l => !l.archived && l.folder && fUnder(l.folder, v.path)), ids = new Set(ls.map(l => l.id));
    line('list', trn('{0} project', '{0} projects', ls.length));
    line('check', trn('{0} open task', '{0} open tasks', [...S.tasks.values()].filter(t => ids.has(t.list_id) && !t.status).length));
    return head('folder', fDisp(v.path)) + rows.join('');
  }
  if (k[0] === 'c') {
    const c = v.c;
    line('building', [c.org, c.title].filter(Boolean).join(', '));
    line('phone', (c.phones || [])[0]?.value || '');
    line('mail', (c.emails || [])[0]?.value || '');
    return head('user', v.name) + rows.join('');
  }
  if (k[0] === 'e') {
    const e = v.e, s = String(e.start || ''), en = String(e.end || '');
    line('clock', s ? dayLabel(s.slice(0, 10)) + (e.all_day ? '' : ' ' + s.slice(11, 16) + (en.length > 15 ? '–' + en.slice(11, 16) : '')) : '');
    line('mappin', e.location || '');
    return head('cal', v.name) + rows.join('');
  }
  const f = v.f;
  line('info', [f.kind === 'file' && f.size != null ? fmtSize(f.size) : '', f.updated_at ? fmtDate(String(f.updated_at).slice(0, 10)) : ''].filter(Boolean).join('  ·  '));
  return head(f.kind === 'folder' ? 'folder' : 'file', v.name) + rows.join('');
}
