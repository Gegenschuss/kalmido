/* Kalmido web client: Toasts, quick add wiring and the global event handlers.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ toast
let toastTimer;
// 2.6.0 (K18): the toast sits above whatever is docked at the bottom (the composer "Add task…", the tab bar, the + button),
// never on top of it; measured each time it shows
function toastPlace(el) {
  let top = innerHeight;
  for (const s of ['#view .qdock .qadd', '#tabs', '#fab:not(.gone)', '.mbar:not(.hidden)']) {
    const e = $(s); if (!e || !e.offsetWidth) continue;
    const r = e.getBoundingClientRect(); if (r.top > innerHeight * .5 && r.top < top && r.bottom > innerHeight - 160) top = r.top;
  }
  // 2.13.0 (#453 A12): an open bottom sheet (snooze, date, menus) is never covered: the toast sits above its top edge,
  // or at the top of the screen when the sheet is that tall
  // 2.25.0 (UX-31): the phone's quick-add sheet too: the message sits above it, never over the field
  const sh = $('#pop.sheet:not(.hidden)') || $('.qadd.sheet'), sr = sh && sh.offsetHeight ? sh.getBoundingClientRect() : null;
  el.classList.toggle('totop', !!sr && sr.top < innerHeight * .3);
  if (sr && sr.top >= innerHeight * .3) top = Math.min(top, sr.top);
  el.style.bottom = el.classList.contains('totop') ? '' : top < innerHeight ? Math.round(innerHeight - top + 12) + 'px' : '';
}
// 2.16.0 (#473): status messages for screen readers (WCAG 4.1.3): one polite live region (#srlive in index.html); the
// text is set a moment after clearing it, so the same message twice is read twice
let announceT;
// 2.16.0 (#473, WCAG 3.3.1): an error line of a form / dialog (.calerr, .aerr; role="alert" = read out when it appears) marks
// its field: the focused one, else the first text field of the same form / dialog: aria-invalid + aria-describedby
new MutationObserver(ms => {
  const seen = new Set();
  for (const m of ms) { const t = m.target.nodeType === 3 ? m.target.parentElement : m.target; const e = t?.closest?.('.calerr,.aerr'); if (e) seen.add(e); }
  for (const e of seen) {
    if (!e.id) continue;
    const box = e.closest('form,.card,.modal,.authscreen') || e.parentElement; if (!box) continue;
    const on = !!e.textContent.trim() && !e.hidden;
    const a = document.activeElement;
    const f = on ? (a && box.contains(a) && /INPUT|TEXTAREA|SELECT/.test(a.tagName) ? a : $('input:not([type=hidden]):not([type=checkbox]):not([type=radio]),textarea,select', box)) : null;
    for (const x of $$(`[aria-errormessage="${e.id}"]`, box)) if (x !== f) { x.removeAttribute('aria-invalid'); x.removeAttribute('aria-errormessage'); x.setAttribute('aria-describedby', (x.getAttribute('aria-describedby') || '').split(' ').filter(i => i && i !== e.id).join(' ')); if (!x.getAttribute('aria-describedby')) x.removeAttribute('aria-describedby'); }
    if (f) { f.setAttribute('aria-invalid', 'true'); f.setAttribute('aria-errormessage', e.id); const d = (f.getAttribute('aria-describedby') || '').split(' ').filter(Boolean); if (!d.includes(e.id)) f.setAttribute('aria-describedby', [...d, e.id].join(' ')); }
  }
}).observe(document.documentElement, {subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['hidden']});
// 2.16.0 (#473, WCAG 3.3.1): a required field left empty says so in words (next to the field, read out, aria-invalid)
// instead of only getting the focus
function need(el, msg) {
  if (!el) return;
  const lab = (selLabel(el) || el.getAttribute('placeholder') || '').replace(/[:*]\s*$/, '');
  const text = msg || (lab ? tr('Please fill in “{0}”', lab) : tr('Please fill in this field'));
  let e = el.nextElementSibling?.classList.contains('ferr') ? el.nextElementSibling : null;
  if (!e) { e = document.createElement('div'); e.className = 'ferr'; e.id = 'fe' + Math.random().toString(36).slice(2, 8); e.setAttribute('role', 'alert'); el.insertAdjacentElement('afterend', e); }
  e.textContent = text;
  const d = (el.getAttribute('aria-describedby') || '').split(' ').filter(Boolean);
  el.setAttribute('aria-invalid', 'true'); if (!d.includes(e.id)) el.setAttribute('aria-describedby', [...d, e.id].join(' '));
  el.addEventListener('input', () => { e.remove(); el.removeAttribute('aria-invalid'); const r = (el.getAttribute('aria-describedby') || '').split(' ').filter(x => x && x !== e.id).join(' '); r ? el.setAttribute('aria-describedby', r) : el.removeAttribute('aria-describedby'); }, {once: true});
  el.focus();
}
function announce(msg) {
  let r = $('#srlive');
  if (!r) { r = document.createElement('div'); r.id = 'srlive'; r.className = 'sr'; r.setAttribute('role', 'status'); r.setAttribute('aria-live', 'polite'); r.setAttribute('aria-atomic', 'true'); document.body.appendChild(r); }
  r.textContent = ''; clearTimeout(announceT);
  announceT = setTimeout(() => { r.textContent = String(msg || ''); }, 60);
}
function toast(msg, undo, ms, label) {  // label: the button's text instead of "Undo" (2.13.0: "Open")
  const el = $('#toast');
  announce(msg + (undo ? ' · ' + (label || tr('Undo')) + (isTouch() ? '' : ' (' + kbText('Mod+Z') + ')') : ''));
  if (!undo || label) HIST.toastE = null;  // any other message ends the toast's shortcut (the history keeps the step)
  el.innerHTML = `<span>${esc(msg)}</span>${undo ? `<button>${esc(label || tr('Undo'))}</button>${isMobile() || isTouch() || label ? '' : kb('Mod+Z')}` : ''}`;
  el.classList.remove('hidden');
  toastPlace(el);
  if (undo) el.querySelector('button').onclick = () => { el.classList.add('hidden'); undo(); };
  clearTimeout(toastTimer);
  const hide = () => { el.classList.add('hidden'); if (undo) HIST.toastE = null; };
  const wait = ms || (undo ? 6000 : 2500);
  toastTimer = setTimeout(hide, wait);
  // 2.16.0 (#473, WCAG 2.2.1): the toast stays while the pointer or the keyboard focus is on it
  el.onmouseenter = el.onfocusin = () => clearTimeout(toastTimer);
  el.onmouseleave = el.onfocusout = e => { if (e.type === 'focusout' && el.contains(e.relatedTarget)) return; if (el.matches(':hover') && e.type === 'focusout') return; clearTimeout(toastTimer); toastTimer = setTimeout(hide, Math.max(2500, wait / 2)); };
}

// ------------------------------------------------------------------ quick add wiring
function currentQuickInput() { return $('#qinput'); }
function updateChips(input) {
  if (input.id === 'qinput') qdockChips();
  input.closest('.qadd.dock')?.classList.toggle('has-text', !!input.value.trim());  // 2.24.0 (UX-30)
  const chips = input.closest('.qadd').querySelector('.chips');
  if (!chips) return;
  const r = parseQuick(input.value, S.quick.ignore);
  chips.innerHTML = r.chips.map(c => `<button class="qchip ${c.off ? 'off' : ''}" data-qtype="${esc(c.type)}" title="${c.off ? tr('recognize again') : tr("don't recognize")}">${esc(c.label)}</button>`).join('') + qMismatch(r);
}
// U21: a date that is not on the repeat's own days ("tomorrow … every monday"): say what happens
function qMismatch(r) {
  if (!r.due || !r.repeat) return '';
  const p = rrParts(r.repeat), d = pd(r.due);
  const off = (p.FREQ === 'WEEKLY' && p.BYDAY && !/\d/.test(p.BYDAY) && !p.BYDAY.split(',').includes(RR_WD[d.getDay()]))
    || (p.FREQ === 'MONTHLY' && p.BYMONTHDAY && !p.BYMONTHDAY.split(',').map(Number).includes(d.getDate()));
  return off ? `<span class="qnote" role="note">${ic('alert', 's')}${esc(tr('first on {0}, then {1}', dayLabel(r.due), repeatLabelBase(rrBase(r.repeat))))}</span>` : '';
}
async function submitQuick(input, extra = {}) {
  const cap = input.id === 'qsheet' && S.quickPreset.capture;  // 2.4.0 (#187): a capture ignores the view (inbox unless ~list)
  const d = {...(cap ? {} : quickDefaults()), ...(input.id === 'qsheet' ? S.quickPreset : {}), ...extra};
  const pasted = S.qfiles?.[input.id] || [];  // 2.22.0 (#678): images pasted into the box
  if (pasted.length) d.files = [...(d.files || []), ...pasted];
  const txt = input.value.trim(); if (!txt && !d.files?.length) return;
  const r = parseQuick(txt, S.quick.ignore);
  const url = r.url || d.url || null;
  if (!r.title && url) r.title = urlTitle(url);  // only a link typed / shared: domain + path as title
  if (!r.title && d.files?.length) r.title = d.files[0].name.replace(/\.[^.]+$/, '');  // shared file without a title
  if (!r.title) return;
  const o = input.id === 'qinput' && S.qov?.key === S.route.key ? S.qov : {};  // chips of the docked composer
  const body = {title: r.title, list_id: o.list_id || r.list_id || d.list_id, due: 'due' in o ? o.due : r.due || d.due, due_time: r.due_time || d.due_time, priority: 'priority' in o ? o.priority : r.priority ?? d.priority ?? 0,
    tags: [...(d.tags || []), ...(r.tags || [])], repeat: r.repeat || '', section_id: d.section_id, content: d.content || ''};
  if (url) body.url = url;
  if (r.ttype) body.ttype = r.ttype;  // 2.4.0 (#340): !bug / !feature / !task
  if (r.ms || d.ms) body.ms = 1;  // 2.18.0 (#430): !milestone
  if (d.assignee_id && !r.list_id) body.assignee_id = d.assignee_id;
  if (body.due_time && S.settings.default_reminder !== '') body.reminders = S.settings.default_reminder;
  input.value = ''; S.quick.ignore = new Set(); updateChips(input);
  if (pasted.length) { S.qfiles[input.id] = []; qFilesDraw(input); }
  if (input.id === 'qsheet' && (cap || S.quickPreset.content || S.quickPreset.url || S.quickPreset.due_time || S.quickPreset.files?.length)) { S.quickPreset = {}; closePop(); }
  if (d.open && input.id === 'qsheet') closePop();  // 2.14.0 (#484): the details take the screen
  const created = await createTask(body);
  if (r.wait && created?.id) { try { putTask(await api('PUT', `/api/tasks/${created.id}/waiting`, {note: r.wait, until: addDays(today(), 7)})); render(); } catch { /* api() said it */ } }  // 2.22.0 (#686)
  if (cap) { captureDone(created, body); return; }
  if (d.open && created?.id) { openDetail(created.id); return; }  // 2.14.0 (#484): "Add and open"
  if (d.files?.length && input.id === 'qsheet') closePop();
  if (created?.id && input.id === 'qinput') hintDone('qsyntax');
  // 2.13.0 (#453 P8): a task that does not show up in the open view (e.g. "… tomorrow 10:00" typed in Today lands in the
  // Inbox) says where it went, with "Open"
  if (created?.id && !d.files?.length && !d.open) setTimeout(() => {
    if ($(`#view .trow[data-id="${created.id}"]`)) return;
    const t = taskById(created.id) || created, l = listById(t.list_id);
    const tt = t.title || '', tq = tr('“{0}”|quoted', tt.length > 40 ? tt.slice(0, 39) + '…' : tt);  // 2.25.0 (UX-31): which task, where it went
    toast([tt ? tq : '', l ? lname(l) : '', t.due ? dayLabel(t.due) + (t.due_time ? ' ' + t.due_time : '') : ''].filter(Boolean).join(' · ') || tr('Added'), () => openDetail(created.id), 5000, tr('Open'));
  }, 350);
  if (d.files?.length && created?.id) { await uploadFiles(created.id, d.files); openDetail(created.id); return; }
  const again = document.body.contains(input) ? input : $('#' + input.id); if (again) again.focus();
}
function openQuickSheet(prefill = '', preset = {}) {
  S.quickPreset = preset;
  let q = $('.qadd.sheet');
  if (!q) {
    q = document.createElement('div');
    q.className = 'qadd sheet';
    q.innerHTML = `<div class="box">${ic('plus')}<input id="qsheet" name="kalmido-quick-add-sheet" type="text" data-form-type="other" data-lpignore="true" placeholder="${tr("What's next?")}" autocomplete="off" enterkeyhint="send">${tplBtn()}${qExtraBtns('qsheet')}<button class="iconbtn" data-act="qsheet-send" aria-label="${tr('Add')}">${ic('arrow')}</button></div><div class="chips"></div><div class="qhint">${tr('tomorrow 3pm · !high · #tag · ~list · every monday')}</div>`;  // 2.25.0 (UX-34); 2.30.0 (#1033): the clip/square hint is gone, both buttons carry title + aria-label
    document.body.appendChild(q);
  }
  $('#scrim').classList.remove('hidden');
  document.body.classList.add('qsheet-open');  // 2.13.0 (#453 P8): the + button does not peek out behind the sheet
  popOnClose = () => { q.remove(); S.quickPreset = {}; S.qMoved = false; document.body.classList.remove('qsheet-open'); };
  const nf = preset.files?.length || 0;
  const hint = [preset.due ? dayLabel(preset.due) + (preset.due_time ? ' ' + preset.due_time : '') : '', preset.content ? tr('Link as description') : '', preset.url ? tr('Link: {0}', urlHost(preset.url)) : '',
    nf ? (nf === 1 ? tr('Attachment: {0}', preset.files[0].name) : tr('{0} attachments', nf)) : ''].filter(Boolean).join(' · ');
  $('.qhint', q).textContent = hint || tr('tomorrow 3pm · !high · #tag · ~list · every monday');
  const inp = $('#qsheet'); inp.value = prefill; updateChips(inp);
  q.classList.toggle('capture', !!preset.capture);
  const i0 = $('.box > svg', q); if (i0) i0.outerHTML = ic(preset.capture ? 'zap' : 'plus');
  inp.placeholder = preset.capture ? tr('Capture to the inbox…') : preset.section_name ? tr('Add a task to {0}', preset.section_name) : tr("What's next?");
  if (preset.capture && !hint) $('.qhint', q).textContent = tr('Goes to the inbox · ~list · tomorrow · !high · #tag');
  // 2.26.x (#952): the focus in the same tap (no timer first): iOS opens the keyboard only for a focus inside the user's
  // gesture, so the sheet and the keyboard come up together; a second try a moment later if something took it back
  inp.focus();
  setTimeout(() => { if (document.activeElement !== inp && inp.isConnected) inp.focus(); }, 30);
}
// ---- 2.4.0 (#187): quick capture. A small box from anywhere: q / Ctrl+Space, the command palette, the app shortcut
// "Quick add" (/?action=capture) and the bookmarklet page /capture (a popup with ?title&url of the page you are on). The
// quick add syntax applies; without ~list / "in list …" it goes to the inbox, whatever view is open.
// 2.4.0 (#187): signing in on the capture page keeps the page (title + link of the bookmarklet)
const afterLogin = () => location.pathname === '/capture' ? '/capture' + location.search : '/';
function quickCapture(prefill = '', preset = {}) {
  if (typeof closePalette === 'function') closePalette();
  closePop();
  openQuickSheet(prefill, {list_id: inbox()?.id, ...preset, capture: true});
}
function captureDone(created, body) {
  if (!created) return;
  const l = listById(created.list_id || body.list_id);
  toast(tr('Captured to {0}', l ? lname(l) : tr('Inbox')));
  if (S.capturePage) {  // the bookmarklet popup: say it and close (a tab the script did not open stays, with a link to the app)
    const el = $('#view'); if (el) el.innerHTML = `<div class="empty capdone">${ic('done')}${esc(tr('Captured to {0}', l ? lname(l) : tr('Inbox')))}<br><a href="/#inbox" class="btn sm">${tr('Open Kalmido')}</a></div>`;
    if (window.opener) setTimeout(() => window.close(), 900);
  }
}
const bookmarklet = () => `javascript:(()=>{window.open(${JSON.stringify(location.origin + '/capture')}+'?title='+encodeURIComponent(document.title)+'&url='+encodeURIComponent(location.href),'kalmido_capture','popup,width=560,height=420')})()`;
function captureHelp() {  // /capture without a page: the bookmarklet + the keyboard shortcuts
  const md = modal(`<div class="lhdr"><h3>${ic('zap', 's')} ${tr('Capture to the inbox')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}">${ic('x')}</button></div>
    <p class="muted">${tr('Capture a thought or the page you are reading into the inbox, from anywhere. The quick add syntax works: tomorrow, !high, #tag, ~list.')}</p>
    <h4>${tr('Bookmarklet')}</h4>
    <div class="row caprow"><a class="btn pri capbm" href="${esc(bookmarklet())}" data-act="bm-hint" draggable="true">${ic('zap', 's')} ${tr('Add to Kalmido')}</a></div>
    <div class="shint keep">${tr('Drag the button to your bookmarks bar. On any page, click it: a small window opens with the page title and address, Enter saves it to your inbox. It runs no code of ours on that page and uses your normal sign-in.')}</div>
    <h4>${tr('Keyboard')}</h4>
    <div class="kbrow"><span>${tr('In the app')}</span>${kb('q')} ${kb('Ctrl+Space')}</div>
    <div class="shint keep">${tr('Installed app: its icon menu (right-click in the taskbar or dock, long-press on phones) has “Quick add”. A system-wide key: Windows: Start menu > right-click Kalmido > More > Open file location > Properties > Shortcut key; macOS: Shortcuts app > New shortcut “Open URL” with {0} > Add keyboard shortcut; Linux (GNOME / KDE): a custom shortcut that opens {0} in your browser.', location.origin + '/capture')}</div>
    <div class="foot"><span class="spacer"></span><a class="btn" href="/#inbox">${tr('Open Kalmido')}</a><button class="btn pri" data-m="cap">${ic('plus', 's')} ${tr('Capture now')}</button></div>`);
  md.classList.add('capmodal');
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-m], [data-act="bm-hint"]'); if (!b) return;
    if (b.dataset.act === 'bm-hint') { e.preventDefault(); toast(tr('Drag the button to your bookmarks bar')); return; }
    if (b.dataset.m === 'close') md.remove();
    if (b.dataset.m === 'cap') { md.remove(); quickCapture(); }
  });
}

// ------------------------------------------------------------------ events
document.addEventListener('click', async e => {
  if (e.target.closest('a.lnk, a.linkchip')) return;  // website link: the browser opens it (new tab)
  if (e.target.closest('#view .ttlin, #view .secadd')) return;  // 2.0.2: typing a title / a new task in a section
  const lm = e.target.closest('[data-lmove]');
  if (lm) { e.preventDefault(); moveList(+lm.dataset.id, +lm.dataset.lmove); return; }
  const fm = e.target.closest('[data-fmove]');
  if (fm) {
    e.preventDefault(); e.stopPropagation();
    const f = fm.dataset.folder, sib = folderNames().filter(x => fParent(x) === fParent(f)), i = sib.indexOf(f), j = i + +fm.dataset.fmove;
    if (j >= 0 && j < sib.length) { [sib[i], sib[j]] = [sib[j], sib[i]]; saveFolders(fParent(f) ? folderNames().filter(x => fParent(x) !== fParent(f)).concat(sib) : sib.flatMap(t => [t, ...folderSubs(t)])); }
    return;
  }
  // 2.25.0 (UX-02): the "…" of a list / folder in sort mode: up, down, folder
  const ls = e.target.closest('[data-lsort]');
  if (ls) {
    e.preventDefault(); e.stopPropagation();
    const id = +ls.dataset.lsort;
    menu(ls, [...listMoveItems(id), {label: tr('Move to folder…'), icon: 'folder', fn: () => folderPick(ls, id)}]);  // 2.27.0 (#991): + top / bottom
    return;
  }
  const fs = e.target.closest('[data-fsort]');
  if (fs) {
    e.preventDefault(); e.stopPropagation();
    const f = fs.dataset.fsort, sib = folderNames().filter(x => fParent(x) === fParent(f)), i = sib.indexOf(f);
    const mv = d => () => { const s2 = [...sib]; [s2[i], s2[i + d]] = [s2[i + d], s2[i]]; saveFolders(fParent(f) ? folderNames().filter(x => fParent(x) !== fParent(f)).concat(s2) : s2.flatMap(t => [t, ...folderSubs(t)])); };
    menu(fs, [{label: tr('Move up'), icon: 'chev', cls: 'mup', dis: i <= 0, fn: mv(-1)}, {label: tr('Move down'), icon: 'chev', dis: i < 0 || i >= sib.length - 1, fn: mv(1)}]);
    return;
  }
  const lf = e.target.closest('[data-lfolder]');
  if (lf) {
    e.preventDefault(); e.stopPropagation();
    folderPick(lf, +lf.dataset.lfolder);
    return;
  }
  const g = e.target.closest('[data-go]');
  if (g) {
    e.preventDefault(); if (S.sel && isMobile()) closeDetail();
    // 2.26.x (#953): left from the open drawer: the entry remembers it, so Back to it shows the drawer open again (Android's
    // back preview already shows it; route() used to close it right away = a short flash)
    if ($('#side.open') && g.closest('#side') && !history.state?.detail) try { history.replaceState({...(history.state || {}), side: 1}, '', location.href); } catch { /* old browser */ }
    go(g.dataset.go); return;
  }
  const qc = e.target.closest('.qchip');
  if (qc) { const t = qc.dataset.qtype; S.quick.ignore.has(t) ? S.quick.ignore.delete(t) : S.quick.ignore.add(t); const inp = qc.closest('.qadd').querySelector('input'); updateChips(inp); inp.focus(); return; }
  const cb = e.target.closest('.md input[data-mdline]');
  if (cb) { e.stopPropagation(); if (canEdit(taskById(S.sel))) toggleMdCheckbox(+cb.dataset.mdline); else { e.preventDefault(); roToast(); } return; }
  const mcd = e.target.closest('[data-mcard]');  // 2.4.2 (#389): a mention opens its card (also inside the description)
  if (mcd) { e.preventDefault(); e.stopPropagation(); mentionCard(mcd); return; }
  const mcp = e.target.closest('.md [data-mdcopy]');  // 2.18.0 (#408 G): "Copy" of a code block (never opens the editor)
  if (mcp) { e.preventDefault(); e.stopPropagation(); copyText(mcp.closest('.mdcode')?.querySelector('pre')?.textContent || ''); return; }
  if (e.target.closest('#d-md') && !e.target.closest('a')) { if (canEdit(taskById(S.sel))) editContent(); return; }
  const cev = e.target.closest('#view [data-cev]');
  if (cev) { const v = cev.dataset.cev; cevPop(cev, /^\d+$/.test(v) ? +v : v); return; }  // 2.21.0: own events have ids k<n>
  const rg = e.target.closest('#tl-deps [data-rmdep]');
  if (rg) { rmDepPop(rg); return; }
  const sb = e.target.closest('.rm-sum');
  if (sb) { if (!rmDragged) rmSumMenu(sb); return; }
  const dg = e.target.closest('#tl-deps [data-dep]');
  if (dg) { tlDepPop(dg); return; }
  const bar = e.target.closest('.tl-bar');
  if (bar) { if (S.tlPick) tlPickDo(+bar.dataset.id); else if (!tlDragged) openDetail(+bar.dataset.id); return; }
  const wev = e.target.closest('.wev');
  if (wev) { openDetail(+wev.dataset.id); return; }
  const wc = e.target.closest('.wcol');
  if (wc) { const y = e.clientY - wc.getBoundingClientRect().top, m = Math.max(0, Math.min(23 * 60 + 30, Math.floor(y / weekH() * 2) * 30)), pre = {due: wc.dataset.day, due_time: `${pad(Math.floor(m / 60))}:${pad(m % 60)}`}; openQuickSheet('', pre); evSheetBtn(pre); return; }
  const wh = e.target.closest('.wh, .wad');
  if (wh && !e.target.closest('.ev')) { S.calSel = wh.dataset.day; S.calMode = 'day'; LS.set('calMode', 'day'); renderView(); return; }
  // multi-select: ctrl/cmd/shift-click, or tap while in select mode
  // 2.26.0 (#936): Shift-click selects the range from the anchor (the last clicked / selected row, else the open or the
  // keyboard-focused task) in the visible order; Ctrl/Cmd-click toggles one task, starting from the open task (it joins
  // the selection). A plain click opens the task and ends the selection (openDetail -> meEnd).
  const mrow = e.target.closest('#view .trow');
  const anchor0 = S.multi.size ? S.multiLast : S.sel || S.kf;
  if (mrow && !e.target.closest('.caret') && (S.multiMode || e.ctrlKey || e.metaKey || (e.shiftKey && anchor0))) {
    e.preventDefault(); e.stopPropagation();
    const id = +mrow.dataset.id, ids = $$('#view .trow').map(r => +r.dataset.id);
    if (e.shiftKey && !e.ctrlKey && !e.metaKey && anchor0 && ids.includes(anchor0)) {
      const a = ids.indexOf(anchor0), b = ids.indexOf(id);
      if (a >= 0 && b >= 0) ids.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(x => S.multi.add(x));
      if (!S.multiLast || !S.multi.has(S.multiLast)) S.multiLast = anchor0;
    } else {
      if (!S.multi.size && !S.multiMode && S.sel && S.sel !== id && ids.includes(S.sel)) S.multi.add(S.sel);
      S.multi.has(id) ? S.multi.delete(id) : S.multi.add(id);
      S.multiLast = id;
    }
    $$('#view .trow').forEach(r => r.classList.toggle('msel', S.multi.has(+r.dataset.id)));
    renderMultiBar();
    return;
  }
  const cell = e.target.closest('.cal .cell');
  if (cell && !e.target.closest('.ev')) { S.calSel = cell.dataset.day; if (!cell.classList.contains('out')) { renderView(); } else { S.calMonth = S.calSel.slice(0, 7); renderView(); } return; }
  const ev = e.target.closest('.cal .ev, .week .ev');
  if (ev) { if (!swiped) openDetail(+ev.dataset.id); return; }
  const a = e.target.closest('[data-act]');
  // 2.31.0 (#1051): the gaps of a task row (between the circle and the title, its padding) open the task like its title
  if (!a) { const r = e.target.classList?.contains('trow') && e.target.closest('#view') ? e.target : null; if (r && r.querySelector(':scope > .tmain[data-act="open"]') && !swiped) openDetail(+r.dataset.id); return; }
  const act = a.dataset.act;
  const row = a.closest('.trow');
  const id = +(a.dataset.id || (row && row.dataset.id) || 0);
  switch (act) {
    case 'agent-chip': agentChipMenu(a); break;
    case 'st-chip': stChipMenu(a); break;
    case 'share-list': shareModal(+a.dataset.id); break;
    case 'dm': dmOpen(+a.dataset.uid, personNameAny(+a.dataset.uid)); break;  // 2.24.0 (#906)
    case 'ws-set': wsSet(a.dataset.ws); break;  // 2.28.0 (#935)
    case 'ws-menu': wsMenu(a); break;
    case 'chat-choice': chatChoice(+a.dataset.mid, a.dataset.cid); break;  // 2.28.0 (#1005)
    case 'chat-choice-send': chatChoice(+a.dataset.mid, null, true); break;
    case 'agents-go': settingsModal('agents'); break;  // 2.28.0 (#1011)
    case 'news-tab': LS.set('newsTab', a.dataset.tab); renderView(); break;  // 2.28.0 (#987)
    case 'chat-open': chatOpen(+a.dataset.aid); break;
    case 'chat-close': chatClose(); break;
    case 'chat-mode': chatModeMenu(a); break;  // 2.29.0 (#1029)
    case 'chat-pop': chatPop(); break;  // 2.29.0 (#363)
    case 'chat-dock': chatDock(a.dataset.fl === '1'); break;
    case 'chat-min': chatFloatMin(!$('#achat')?.classList.contains('min')); break;
    case 'chat-send': chatSend(); break;
    case 'chat-older': chatOlder(); break;  // 2.12.2 (#451)
    case 'chat-attach': $('#chat-file')?.click(); break;  // 2.13.1 (#465)
    case 'chat-stage-rm': { const arr = S.chatFiles[S.chat.aid] || []; arr.splice(+a.dataset.i, 1); const b = $('#chat-files'); if (b) b.innerHTML = chatFilesHtml(S.chat.aid); $('#chat-in')?.focus(); break; }
    case 'chat-file-rm': e.preventDefault(); e.stopPropagation(); chatFileRm(+a.dataset.fid); break;
    case 'chat-att-view': { e.preventDefault(); const m = S.chat.msgs.find(x => x.id === +a.dataset.mid); attLightbox(+a.dataset.fid, (m?.attachments || []).filter(isImg)); break; }
    case 'chat-bottom': chatBottom(); break;
    case 'job-do': jobDo(+a.dataset.jid, a.dataset.a); break;
    case 'prop-open': propOpen(+a.dataset.jid); break;  // 2.3.0
    case 'aiu-more': settingsModal('usage'); break;
    case 'ag-setup': LS.set('aiSub', 'setup'); settingsModal('agents'); break;  // 2.22.0 (#739); 2.27.0 (#955): at "Set up"
    case 'jobs-f': S.jobs.f = a.dataset.f; LS.set('jobsFilter', a.dataset.f); S.jobs.items = null; renderView(); break;
    case 'c-react': e.stopPropagation(); commentReact(+a.dataset.cid, a.dataset.e); break;
    case 'c-react-who': e.stopPropagation(); commentReactWho(+a.dataset.cid, a.dataset.e); break;
    case 'c-react-more': e.stopPropagation(); reactPicker(a, +a.dataset.cid); break;
    case 'c-apply': commentApply(+a.dataset.cid); break;
    case 'mr-ok': commentReact(+a.dataset.cid, 'up'); break;  // 2.2.0 (#339)
    case 'gate-ok': gateDecide(+a.dataset.cid, false); break;  // 2.26.0 (#949)
    case 'gate-skip': gateDecide(+a.dataset.cid, true); break;
    case 'mr-no': commentReact(+a.dataset.cid, 'down'); break;
    case 'git-undo': gitUndo(+a.dataset.id); break;
    case 'git-refresh': gitRefresh(+a.dataset.lid); break;
    case 'git-branch': { const t = taskById(+a.dataset.id); if (t) gitCopyBranch(t); break; }
    case 'git-ref': { const t = taskById(+a.dataset.id); if (t) copyText(gitRef(t)); break; }
    case 'ltag-rm': { const t = taskById(S.sel); patchTask(t.id, {ltags: (t.ltags || []).filter(g => g !== a.dataset.tag)}); break; }
    case 'tag-promote': tagPromote(taskById(S.sel), a.dataset.tag); break;
    case 'open': if (!swiped) openDetail(id); break;
    case 'open-id': openDetail(id); break;
    case 'dup-x': { DUP_OFF ||= new Set(LS.get('dupOff', [])); DUP_OFF.add(id); LS.set('dupOff', [...DUP_OFF].slice(-100)); a.closest('.ddup')?.remove(); $('#d-title')?.focus(); break; }
    case 'crumb': crumbGo(a.dataset.k, a.dataset.id); break;  // 2.7.2 (#424)
    case 'crumb-menu': crumbMenu(a, a.dataset.k, a.dataset.id); break;  // 2.25.0 (UX-44)
    case 'chat-react': e.stopPropagation(); chatReact(+a.dataset.mid, a.dataset.e); break;  // 2.7.2 (#421)
    case 'tv-stop': timerStop(); break;
    case 'news-open': newsOpen(+a.dataset.i); break;
    case 'bell-pop': bellPop(a); break;
    case 'news-kind': newsKindSet(a.dataset.nk); renderView(); break;
    case 'news-dismiss': newsDismiss(+a.dataset.i); break;
    case 'news-settings': settingsModal('newskinds'); break;
    case 'news-unread': S.nf.unread = !S.nf.unread; LS.set('newsUnread', S.nf.unread); renderView(); break;
    case 'news-readall': newsReadAll().then(() => { if (S.route.mod === 'news') renderView(); }); break;  // 2.13.0: with undo
    case 'news-filter': if (a.dataset.nk === '') newsKindSet(''); S.nf.filter = 'fme' in a.dataset && S.nf.filter === 'me' && a.getAttribute('aria-pressed') === 'true' ? '' : a.dataset.f; LS.set('newsFilter', S.nf.filter);  /* 2.13.0: the chip toggles */ S.nf.items = null; renderView(); break;
    case 'toggle': e.stopPropagation(); toggleTask(id); break;
    case 'flow-why': e.stopPropagation(); e.preventDefault(); toast(tr(FLOW_WHY), null, 6000); break;
    case 'assign': e.stopPropagation(); assignMenu(a, id); break;
    case 'take': e.stopPropagation(); takeTask(id || S.sel); break;  // 2.10.0 (#441)
    case 'dayplan': dayplanModal(a.dataset.mode || 'day', a.dataset.day || today()); break;  // 2.10.0 (#440)
    case 'unplan': patchUndoable(+a.dataset.id, {plan_start: null}, tr('Unplanned {0}', qn(String(taskById(+a.dataset.id)?.title || '').slice(0, 40)))); break;  // 2.11.0: the day plan's slot only
    case 'review-fold': { const open = a.getAttribute('aria-expanded') === 'true'; LS.set('reviewOpen', open ? '' : today()); if (open) S.review.route = null; renderView(); break; }  // 2.31.0 (#1052)
    case 'review-hide': LS.set('reviewHidden', today()); if (S.route.review) go('today'); else renderView(); break;
    case 'ck-uncheck': case 'ck-clear': {
      e.stopPropagation();
      const dn = [...S.tasks.values()].filter(t => t.list_id === id && t.status !== 0 && !t.parent_id).map(t => t.id), snaps = dn.flatMap(withKids);
      let r;
      try { r = await api('POST', `/api/lists/${id}/checklist`, {action: act === 'ck-clear' ? 'clear_done' : 'uncheck_all'}); } catch { break; }
      await load(); render();
      if (act === 'ck-clear' && dn.length) offerUndo(tr('Done items moved to the trash'), histTrash(trn('{0} done item moved to the trash', '{0} done items moved to the trash', dn.length), dn, snaps, r));
      else toast(act === 'ck-clear' ? tr('Done items moved to the trash') : tr('Everything is back on the list'));
      break;
    }
    case 'close-detail': closeDetail(); break;
    case 'collapse': {
      if (e.target.closest('.gact, .shandle') || secHeld) break;
      const k = a.dataset.key; S.collapsed.has(k) ? S.collapsed.delete(k) : S.collapsed.add(k); LS.set('collapsed', [...S.collapsed]); renderView(); break;
    }
    case 'palette': closeSide(); openPalette(); break;
    case 'new-task': { const q = currentQuickInput(); if (q && (!isMobile() || tabletDock())) q.focus(); else openQuickSheet(); break; }
    case 'side': $('#side').classList.add('open'); $('#scrim').classList.remove('hidden'); popOnClose = closeSide; sideRet = a; if (a.closest('#tabs') || S.sideToLists) { S.sideToLists = false; sideToLists(); } setTimeout(() => { if (document && $('#side.open') && !$('#side').contains(document.activeElement)) { sideRove(); const f = sideItems().find(x => x.tabIndex === 0) || sideItems()[0]; f?.focus({preventScroll: true}); } }, 60); break;  // 2.16.0 (#473): the drawer takes the focus
    case 'settings': closeSide(); settingsModal(); break;
    // 2.16.0 (#641): the account sits as the picture at the right of the Kalmido row (sidebar + drawer): Account, Settings,
    // Log out (the account rows at the top of the drawer / the bottom of the sidebar are gone)
    case 'user-menu': { const n = netState(); menu(a, [{label: S.me ? `${S.me.display_name} · ${S.me.username}` : '', icon: 'user', dis: true, cls: 'mwho'},
      // 2.31.0 (#378): the connection as the first line (online = "All saved" from 2.25), offline / waiting: try again now
      {label: n.k === 'on' ? tr('Online') + ' · ' + tr('All saved') : n.label, icon: n.k === 'on' ? 'check' : n.k === 'off' ? 'cloudoff' : 'sync', dis: true, cls: 'mnet n-' + n.k},
      ...(n.k !== 'on' ? [{label: tr('Try again'), icon: 'sync', fn: () => { if (OUT.q.length) flush(); refreshNow().then(staleDraw).catch(() => {}); }}] : []), '-',
      {label: tr('Account'), icon: 'user', fn: () => { closeSide(); settingsModal('account'); }},
      {label: tr('Settings'), icon: 'gear', keys: 'g s', fn: () => { closeSide(); settingsModal(); }},
      ...(S.me?.auth === 'session' ? ['-', {label: tr('Log out'), icon: 'logout', fn: logout}] : [])]); break; }
    case 'tabs-more': tabsMore(a); break;
    case 'list-chat': listChat(+a.dataset.id); break;  // 2.17.0 (#419)
    case 'rows-more': rowsMore(); break;  // 2.17.0 (#649)
    case 'rx-tog': {  // 2.16.0 (#643): open / close the quick reactions of a chat message or a comment
      const host = a.closest('.cmsg, .cm'); if (!host) break;
      const on = !host.classList.contains('rxshow');
      $$('.rxshow').forEach(x => { x.classList.remove('rxshow'); x.querySelector('.rxtog')?.setAttribute('aria-expanded', 'false'); });
      host.classList.toggle('rxshow', on); a.setAttribute('aria-expanded', String(on)); S.rxOpen = on ? rxKey(host) : null;
      if (on) setTimeout(() => { const q = host.querySelector('.chrxq, .cmrxq, .rxrow'); (q?.querySelector('.rxq') || q?.querySelector('.rx'))?.focus({preventScroll: true}); try { q?.scrollIntoView({block: 'nearest'}); } catch { /* old browsers */ } }, 0);  // 2.17.2: the last message's bar is not hidden behind the box
      break;
    }
    case 'list-new': menu(a, [{label: tr('New list'), icon: 'list', fn: () => { closeSide(); listModal(); }}, {label: tr('New project…'), icon: 'brief', fn: () => { closeSide(); listModal(null, '', {kind: 'project'}); }}, {label: tr('New folder…'), icon: 'folder', fn: () => { closeSide(); newFolder(); }}, ...(tplOf('list').length ? [{label: tr('New list from template'), icon: 'copy', fn: () => { closeSide(); templateMenu($('#top h1'), 'list'); }}] : []), ...(propOn() ? [{label: tr('New project from briefing…'), icon: 'bot', fn: () => { closeSide(); propRequest('project'); }}] : [])]); break;
    case 'tpl-use': if (a.closest('.qadd.sheet')) { closePop(); templateMenu($('#fab'), 'task'); } else templateMenu(a, 'task'); break;
    case 'stats-mode': S.st.mode = a.dataset.k; LS.set('statsMode', S.st.mode); renderView(); break;
    case 'status': statusModal(id); break;
    case 'ov-only': S.ov.only = !!a.dataset.k; LS.set('ovOnly', S.ov.only); renderView(); break;
    case 'cols': colModal(id); break;  // 2.14.0 (#425)
    case 'dep-add': depPicker(id, a.dataset.dir); break;
    case 'wait-on': waitOnMenu(a, id); break;  // 2.25.0 (UX-43)
    case 'dab-on': hintDone('dab'); setDab(id, true); break;  // 2.25.0 (UX-28)
    case 'dep-rm': {
      const b = +a.dataset.b;
      try { await api('DELETE', `/api/deps/${id}/${b}`); } catch { break; }
      await load(); render(); loadDeps(S.sel); break;
    }
    case 'open-dep': openTaskById(id); break;
    case 'folder-toggle': { const f = a.dataset.folder; foldSet(f, !foldClosed(f)); renderSide(); break; }
    case 'folder-menu': e.stopPropagation(); folderMenu(a, a.dataset.folder); break;
    case 'arch-restore': listArchive(+a.dataset.id, false); break;
    case 'arch-del': listDeleteForGood(+a.dataset.id); break;
    case 'refresh': refreshNow(); break;
    case 'chat-unyield': closeDetail(); setTimeout(() => $('#chat-in')?.focus(), 30); break;  // 2.13.2 (#478 N1)
    case 'agband': LS.set('agband', LS.get('agband', true) === false); renderView(); break;
    case 'side-group': sideGroupToggle(a.dataset.g); break;
    case 'copy-id': copyTaskLink(+a.dataset.id); break;  // 2.13.0
    case 'ids-toggle': { const lid = +a.dataset.id; LS.set('ids.' + lid, !idsOn(lid)); render(); break; }
    case 'side-fold': sideFold(!LS.get('sideFold', false)); break;  // 2.13.0 (#453 A15)
    case 'side-timeline': closeSide(); S.rmScrollReset = true; if (S.route.mod === 'tasks' && S.route.key === 'all') rmSet({v: 'timeline'}, 'all'); else { rmSet({v: 'timeline'}, 'none'); go('all'); } break;
    case 'team-agent': { closeSide(); const ag = agentById(a.dataset.aid); if (ag && ag.enabled) chatOpen(ag.id); else go('agents'); break; }
    case 'side-tags': S.collapsed.has('side:tags-open') ? S.collapsed.delete('side:tags-open') : S.collapsed.add('side:tags-open'); LS.set('collapsed', [...S.collapsed]); renderSide(); break;
    case 'lists-reorder': S.listReorder = !S.listReorder; renderSide(); break;
    case 'side-more': closeSide(); settingsModal('sidebar'); break;  // 2.25.0 (UX-03 / UX-26)
    case 'list-menu': listMenu(a, id); break;
    case 'top-more': menu(a, topMoreItems()); break;
    case 'fview': if (a.classList.contains('on')) break; if (a.dataset.k === 'matrix') { mxSet({scope: 'folder:' + a.dataset.f}); go('matrix'); } else go('folder/' + encodeURIComponent(a.dataset.f)); break;  // 2.4.2 (#390)
    case 'prog-hide': setProgHidden(id, true); break;
    case 'view-list': case 'view-kanban': case 'view-timeline': case 'view-overview': {
      const l = routeList();
      // phones: only the current view is shown (room for ← / →), a tap on it offers the others
      if (isTouch() && a.classList.contains('on') && a.closest('.vseg')) {
        menu(a, $$('.vseg button', a.closest('.vseg')).map(b => ({label: b.title, icon: b.dataset.ico, on: b === a,
          fn: async () => { if (b === a) return; await setListView(l, b.dataset.act.slice(5)); }})));
        break;
      }
      await setListView(l, act.slice(5)); break;
    }
    case 'pin': { const t = taskById(id); patchTask(id, {pinned: t.pinned ? 0 : 1}); break; }
    case 'conflicts': conflictModal(); break;
    case 'att-view': e.preventDefault(); attLightbox(+a.dataset.att); break;
    case 'catt-view': {
      e.preventDefault();
      const c = (S.tl.comments || []).find(x => x.id === +a.dataset.cid);
      attLightbox(+a.dataset.att, (c?.attachments || []).filter(isImg)); break;
    }
    case 'catt-del': {
      e.preventDefault(); e.stopPropagation();
      const c = (S.tl.comments || []).find(x => (x.attachments || []).some(f => f.id === +a.dataset.att)), f = c?.attachments.find(x => x.id === +a.dataset.att);
      if (!f || !await askConfirm(tr('Remove “{0}”?', f.name), tr('The file is deleted.'), {ok: tr('Remove'), danger: true})) break;
      try { await capi('DELETE', `/api/attachments/${f.id}`); } catch { break; }
      c.attachments = c.attachments.filter(x => x.id !== f.id); drawTimeline(); break;
    }
    case 'link-edit': S.editLink = true; renderDetail(); setTimeout(() => { const i = $('#d-url'); if (i) { i.focus(); i.select(); } }, 0); break;
    case 'link-rm': { const t = taskById(S.sel); if (t) patchUndoable(t.id, {url: null}, tr('Link removed')); break; }
    case 'tl-order': cmtOrderToggle(); break;  // 2.4.2 (#386)
    case 'tl-act': tlActToggle(); break;
    case 'tl-menu': e.stopPropagation(); tlMenu(a); break;  // 2.31.0 (#1054)
    case 'cm-fold': dsFoldToggle(); break;  // 2.31.0 (#344)
    case 'md-subtasks': mdToSubtasks(); break;
    case 'ms-open': openDetail(+a.dataset.id); break;  // 2.18.0 (#430): a task of the milestone
    case 'ms-copy': { const md = S.msr?.j?.release_notes; if (!md) break; try { await navigator.clipboard.writeText(md); toast(tr('Copied')); } catch { toast(tr('Copy failed')); } break; }
    case 'md-more': { (S.mdMore ||= new Set()); S.mdMore.has(S.sel) ? S.mdMore.delete(S.sel) : S.mdMore.add(S.sel); const m = $('#d-md'), open = S.mdMore.has(S.sel); if (m) m.classList.toggle('clamp', !open); a.textContent = open ? tr('Show less') : tr('Show more'); a.setAttribute('aria-expanded', open); break; }
    case 'd-jump-cm': { const tl = $('#d-tl'); if (tl) { tl.style.scrollMarginTop = ($('#detail .dtop')?.offsetHeight || 0) + 'px'; tl.scrollIntoView({block: 'start', behavior: reducedMotion() ? 'auto' : 'smooth'}); } break; }  // 2.31.0 (#1054): replaces the Details | Comments tabs; 2.31.1: the heading stays below the sticky panel header
    case 'sec-add': e.stopPropagation(); secAddOpen(+a.dataset.sec || 0); break;
    case 'c-send': sendComment(); break;
    case 'c-file-rm': { const arr = S.cfiles[S.sel] || []; arr.splice(+a.dataset.i, 1); $('#c-files').innerHTML = composerFiles(S.sel); break; }
    case 'mention-pick': mentionPick(+a.dataset.i); break;
    case 'c-edit': S.cedit = +a.dataset.cid; drawTimeline(); setTimeout(() => { const i = $(`.c-edit-input[data-cid="${a.dataset.cid}"]`); if (i) { autosize(i); i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }, 0); break;
    case 'c-edit-cancel': S.cedit = null; mentionClose(); drawTimeline(); break;
    case 'c-edit-save': {
      const cid = +a.dataset.cid, ta = $(`.c-edit-input[data-cid="${cid}"]`); if (!ta) break;
      try { await capi('PATCH', `/api/comments/${cid}`, {body: encodeMentions(ta.value.trim(), S.tl.people)}); } catch { break; }
      S.cedit = null; mentionClose(); await loadTimeline(S.sel); break;
    }
    case 'c-del': {
      const cid = +a.dataset.cid;
      if (!await askConfirm(tr('Delete this comment?'), tr('Everyone in the list sees it disappear.'), {ok: tr('Delete'), danger: true})) break;
      try { await capi('DELETE', `/api/comments/${cid}`); } catch { break; }
      if (S.cedit === cid) S.cedit = null;
      await loadTimeline(S.sel); break;
    }
    case 'pl-search': plSearchModal(S.sel); break;
    case 'wait-edit': waitDialog(+a.dataset.id); break;
    case 'wait-clear': waitClear(+a.dataset.id); break;
    case 'pl-del': {
      const t = taskById(S.sel), p = t?.paperless?.find(x => x.id === +a.dataset.pl);
      if (!p || !await askConfirm(tr('Remove the link to “{0}”?', p.title), tr('The document stays in Paperless.'), {ok: tr('Remove')})) break;
      putTask(await api('DELETE', `/api/paperless-links/${p.id}`)); render(); renderDetail(); break;
    }
    case 'att-pl': {
      e.preventDefault(); e.stopPropagation();
      const t = taskById(S.sel), at = t?.attachments?.find(x => x.id === +a.dataset.att);
      if (!at || a.classList.contains('busy')) break;
      const conn = await plPick(a); if (conn === null) break;  // 2.1.0: which connection, if there are several
      if (!await askConfirm(tr('File “{0}” in Paperless?', at.name), S.settings.paperless_keep === '1' ? tr('The attachment also stays here.') : tr('Once consumed, the link replaces the attachment.'), {ok: plConns().length > 1 ? tr('Send to {0}', plConn(conn)?.name || 'Paperless') : tr('Send to Paperless')})) break;
      putTask(await api('POST', `/api/attachments/${at.id}/to-paperless`, {conn})); render(); renderDetail();
      toast(tr('Sent to Paperless, processing')); break;
    }
    case 'att-del': {
      const t = taskById(S.sel), at = t?.attachments?.find(x => x.id === +a.dataset.att);
      if (!at || !await askConfirm(tr('Remove “{0}”?', at.name), tr('The file is deleted.'), {ok: tr('Remove'), danger: true})) break;
      putTask(await api('DELETE', `/api/attachments/${at.id}`)); render(); renderDetail(); break;
    }
    case 'multi': S.multiMode = !S.multiMode; if (!S.multiMode) S.multi.clear(); render(); break;
    case 'filter-new': closeSide(); filterModal(); break;
    case 'filter-edit': filterModal(id); break;
    case 'cal-done': setShowDone(!showDoneCal(), 'cal'); break;
    case 'cal-mode': S.calMode = a.dataset.k; LS.set('calMode', S.calMode); if (S.calMode === 'month') S.calMonth = S.calSel.slice(0, 7); renderView(); break;
    case 'tl-pick-cancel': tlPickEnd(); break;
    case 'rm-view': if (a.dataset.k !== (isRoadmap() ? 'timeline' : 'list')) { S.rmScrollReset = true; rmSet({v: a.dataset.k}, 'all'); } break;
    case 'rm-zoom': if (a.dataset.k !== rmZoom()) { S.rmScrollReset = true; rmSet({z: a.dataset.k}); } break;
    case 'rm-prev': rmNav(-1); break;
    case 'rm-next': rmNav(1); break;
    case 'rm-today': rmNav(0); break;
    case 'rm-jump': rmJump(a.dataset.d); break;
    case 'rm-toggle': rmToggle(a.dataset.key); break;
    case 'rm-collapse': rmAll(false); break;
    case 'rm-expand': rmAll(true); break;
    case 'rm-po': rmSet({po: !rmPO()}); break;
    case 'rm-hd': rmSet({hd: !rmHD()}); break;
    case 'rm-nd': rmSet({nd: !rmNdOn()}); break;
    case 'rm-ndfold': { const k = a.dataset.key; S.collapsed.has(k) ? S.collapsed.delete(k) : S.collapsed.add(k); LS.set('collapsed', [...S.collapsed]); renderView(); break; }
    case 'rm-who': rmWhoMenu(a); break;
    case 'rm-lists': rmListsPop(a); break;
    case 'tl-pick-list': { const f = S.tlPick?.from; S.tlPick = null; renderView(); if (f) depPicker(f, 'blocking'); break; }
    case 'tl-nd': { const lid = routeList()?.id || null, o = LS.get('tlnd', {}) || {}; o[tlNdKey(lid)] = !tlNdOn(lid); LS.set('tlnd', o); renderView(); break; }
    // 2.18.0 (#462 / #431): section folds of the timeline / roadmap, "+" (new task in that row), the inline field's buttons
    case 'tl-secfold': { const k = a.dataset.key; S.collapsed.has(k) ? S.collapsed.delete(k) : S.collapsed.add(k); LS.set('collapsed', [...S.collapsed]); renderView(); $(`.tl-secb[data-key="${rmEsc(k)}"]`)?.focus({preventScroll: true}); break; }
    case 'tl-add': tlAddAt(a); break;
    case 'tl-new-ok': tlNewSave(); break;
    case 'tl-new-x': tlNewEnd(true); break;
    case 'collapse-tl': { const k = a.dataset.key; S.collapsed.has(k) ? S.collapsed.delete(k) : S.collapsed.add(k); LS.set('collapsed', [...S.collapsed]); renderView(); break; }
    case 'tl-prev': case 'tl-next': S.tlStart = addDays(S.tlStart, act === 'tl-next' ? 14 : -14); renderView(); break;
    case 'tl-today': S.tlStart = addDays(weekStartOf(today()), -7); { const tl = $('#tlscroll'); renderView(); const n = $('#tlscroll'); if (n) n.scrollLeft = 5 * tlDW(); } break;
    case 'sort': sortMenu(a); break;
    case 'sort-shared': LS.del('sort2.' + S.route.key); render(); break;  // 2.27.0 (#988)
    case 'od-move': overdueAct(a); break;
    case 'od-other': overdueOther(a); break;  // 2.24.0 (UX-35)
    case 'od-hide': LS.set('odHide', today()); renderView(); break;
    case 'section-new': {
      const n = await askPrompt(tr('Name of the section / column'), '', {ok: tr('Add')}); if (!n || !n.trim()) break;
      const lid = S.route.key === 'inbox' ? inbox().id : +S.route.key.slice(2);
      await sectionCreate(lid, n.trim()); break;
    }
    case 'section-menu': e.stopPropagation(); sectionMenu(a, id); break;
    case 'hist-undo': case 'hist-redo': if (!histHeld()) histStep(act.slice(5)); break;
    case 'date': datePop(a, id); break;
    case 'due-q': quickDue(id, +a.dataset.d); break;
    case 'prio': prioMenu(a, id); break;
    case 'task-menu': taskMenu(a, id); break;
    case 'delete': deleteTask(id); break;
    case 'restore': await api('POST', `/api/tasks/${id}/restore`); await load(); render(); toast(tr('Restored')); break;
    case 'purge': if (await askConfirm(tr('Delete permanently?'), tr('This cannot be undone.'), {ok: tr('Delete permanently'), danger: true})) { await api('DELETE', `/api/tasks/${id}?hard=1`); await load(); render(); } break;
    case 'done-clean': doneCleanup(); break;
    case 'qd-date': {
      const inp = $('#qinput'), cur = 'due' in (S.qov || {}) ? S.qov.due : parseQuick(inp?.value || '', S.quick.ignore).due || quickDefaults().due || '';
      dpOpen(a, {kind: 'date', value: cur || today(), clear: true, label: tr('Date'), onPick: v => { S.qov.due = v || null; qdockChips(); $('#qinput')?.focus(); }});
      break;
    }
    case 'qd-list': menu(a, S.lists.filter(l => !l.archived && canAddTo(l.id)).map(l => ({label: lname(l), icon: 'list', fn: () => { S.qov.list_id = l.id; qdockChips(); $('#qinput')?.focus(); }}))); break;
    case 'qd-prio': menu(a, [[5, N_('High')], [3, N_('Medium')], [1, N_('Low')], [0, N_('None')]].map(([p, n]) => ({label: tr(n), icon: 'flag', cls: p ? 'flag-' + p : '', fn: () => { S.qov.priority = p; qdockChips(); $('#qinput')?.focus(); }}))); break;
    case 'mx-scope': mxScopeMenu(a); break;
    case 'mx-mine': mxSet({mine: !mxGet().mine}); break;
    case 'mx-due': mxSet({due: a.dataset.k}); break;
    case 'mx-reset': LS.del('mx'); render(); break;
    case 'mx-fold': { const p = +a.dataset.p, f = new Set(LS.get('mxFold', [])); f.has(p) ? f.delete(p) : f.add(p); LS.set('mxFold', [...f]); renderView(); $(`.quad[data-quad="${p}"] .qfold`)?.scrollIntoView?.({block: 'nearest'}); break; }
    case 'hint-x': hintDone(a.dataset.k); a.closest('[data-hint]')?.remove(); break;
    case 'trash-empty': if (await askConfirm(tr('Empty the trash permanently?'), trn('{0} task is deleted for good. This cannot be undone.', '{0} tasks are deleted for good. This cannot be undone.', (S.extra || []).filter(t => !t.keep).length), {ok: tr('Empty'), danger: true})) {
      const j = await api('DELETE', '/api/trash'); await load(); render();
      if (j.kept) toast(trn('{0} item stays: it is in a list of another owner', '{0} items stay: they are in lists of other owners', j.kept), null, 6000);  // 2.0.5 (#310)
    } break;
    case 'tag-rm': { const t = taskById(S.sel); patchTask(t.id, {tags: t.tags.filter(g => g !== a.dataset.tag)}); break; }
    case 'cal-prev': case 'cal-next': {
      const dir = act === 'cal-next' ? 1 : -1;
      if (S.calMode === 'week') S.calSel = addDays(S.calSel, 7 * dir);
      else if (S.calMode === 'day') S.calSel = addDays(S.calSel, dir);
      else if (S.calMode === 'agenda') S.calSel = addDays(S.calSel, 14 * dir);  // 2.21.0 (#659)
      else if (S.calMode === 'timeline') S.tlStart = addDays(S.tlStart, 14 * dir);
      else { const [y, m] = S.calMonth.split('-').map(Number); S.calMonth = ds(new Date(y, m - 1 + dir, 1)).slice(0, 7); }
      renderView(); break;
    }
    case 'cal-today': S.calMonth = today().slice(0, 7); S.calSel = today(); S.tlStart = addDays(weekStartOf(today()), -7); renderView(); break;
    case 'habit-new': habitModal(); break;
    case 'habit-open': habitModal(id); break;
    case 'habit-tick': {
      const h = S.habits.find(x => x.id === id), d = a.dataset.day, c = h.logs[d] || 0;
      const n = c >= h.goal ? 0 : c + 1;
      if (n) h.logs[d] = n; else delete h.logs[d];
      renderView();
      await api('POST', `/api/habits/${id}/log`, {day: d, count: n});
      break;
    }
    case 'pomo-kind': pomoKind = a.dataset.k; LS.set('pomoKind', pomoKind); renderView(); break;
    case 'pomo-start': pomoStart(); break;
    case 'pomo-task': pomoStart(id); closeDetail(); go('pomo'); break;
    case 'mb-date': multiDateMenu(a); break;
    case 'mb-today': batch('patch', {due: today()}); break;
    case 'mb-tomorrow': batch('patch', {due: addDays(today(), 1)}); break;
    case 'mb-prio': menu(a, [[5, N_('High')], [3, N_('Medium')], [1, N_('Low')], [0, N_('None')]].map(([p, n]) => ({label: tr(n), icon: 'flag', cls: p ? 'flag-' + p : '', fn: () => batch('patch', {priority: p})}))); break;
    case 'mb-list': menu(a, S.lists.filter(l => !l.archived && canEditList(l.id)).map(l => ({label: lname(l), fn: () => batch('patch', {list_id: l.id, section_id: null})}))); break;
    case 'mb-ms': {  // 2.18.0 (#430): the selected tasks (one list) into one of its open milestones, or out
      const lid = msBulkList(); if (!lid) break;
      menu(a, [...msOfList(lid).filter(m => m.status === 0).map(m => ({label: m.title + (m.due ? ' · ' + fmtDateLoc(m.due) : ''), icon: 'flag', fn: () => batch('patch', {milestone_id: m.id}, false, undefined, tr('Milestone: {0}', m.title))})),
        '-', {label: tr('No milestone'), icon: 'x', fn: () => batch('patch', {milestone_id: null}, false, undefined, tr('Milestone removed'))}]);
      break;
    }
    case 'mb-tag': { const g = await askPrompt(tr('Add tag'), '', {ok: tr('Add')}); if (g && g.trim()) batch('patch', {add_tags: [g.trim().replace(/^#/, '')]}); break; }
    case 'mb-pin': batch('patch', {pinned: [...S.multi].every(i => S.tasks.get(i)?.pinned) ? 0 : 1}); break;
    case 'mb-wait': { const wid = [...S.multi][0]; if (wid) { const tt = taskById(wid); if (tt?.waiting_at) waitClear(wid); else waitDialog(wid); } break; }  // 2.22.0 (#686)
    case 'mb-done': {
      const nb = [...S.multi].filter(i => S.tasks.get(i)?.blocked && S.tasks.get(i).status === 0 && dFor(S.tasks.get(i))).length;
      if (nb && !await askConfirm(trn('{0} of the selected tasks is still blocked by another task. Complete anyway?', '{0} of the selected tasks are still waiting on other tasks. Complete anyway?', nb), '', {ok: tr('Complete anyway')})) break;
      batch('complete', {}, true); break;
    }
    case 'mb-del': batch('delete', {}, true); break;
    case 'mb-sort': propRequest('triage', {ids: [...S.multi]}); break;  // 2.3.0 (#262)
    case 'mb-all': $$('#view .trow').forEach(r => S.multi.add(+r.dataset.id)); render(); break;
    case 'mb-close': S.multi.clear(); S.multiMode = false; render(); break;
    case 'mb-more': menu(a, $$('#mbar .mbh').map(h => ({label: h.getAttribute('aria-label'), icon: h.dataset.ico, cls: h.classList.contains('danger') ? 'flag-5' : '', fn: () => h.click()}))); break;  // 2.13.0 (#453 A14)
    case 'pomo-pause': case 'pomo-resume': case 'pomo-stop': {
      const swStop = act === 'pomo-stop' && S.pomo?.kind === 'stopwatch' ? Math.round(pomoElapsed(S.pomo) / 60) : null;
      const j = await api('POST', `/api/pomo/${S.pomo.id}/${act.slice(5)}`);
      if (swStop !== null) setTimeout(() => toast(tr('Stopped: {0} logged', fmtH(swStop))), 50);
      S.pomo = j.pomo; S.pomoToday = j.today; document.title = APP_NAME; render(); break;
    }
    case 'qsheet-send': submitQuick($('#qsheet')); break;
    case 'q-open': { const i = $('#' + a.dataset.q); if (i && i.value.trim()) submitQuick(i, {open: true}); else { i?.focus(); toast(tr('Type a title first')); } break; }  // 2.14.0 (#484)
    case 'q-clip': quickFiles($('#' + a.dataset.q)); break;
    case 'timer-pill': timerMenu(a); break;
    case 'run-pop': runPop(a); break;
    case 'timer-toggle': timerToggle(id); break;
    case 'te-add': entryModal(null, id ? {task_id: id} : {}); break;
    case 'te-edit': { const en = findEntry(+a.dataset.eid); if (en) entryModal(en); break; }
    case 'te-del': teDelete(+a.dataset.eid); break;
    case 'te-resume': { const en = findEntry(+a.dataset.eid); if (en) timerStart(en.task_id ? {task_id: en.task_id} : {list_id: en.list_id}, en.note); break; }
    case 'te-more': S.te.all = true; drawTaskTime(); break;
    case 'te-open': if (id) openTaskById(id); break;
    case 'tv-period': S.tv.period = a.dataset.k; LS.set('timePeriod', S.tv.period); if (S.tv.period === 'custom' && !S.tv.from) { [S.tv.from, S.tv.to] = [addDays(today(), -29), today()]; LS.set('timeFrom', S.tv.from); LS.set('timeTo', S.tv.to); } renderView(); break;
    case 'tv-scope': S.tv.scope = a.dataset.k; LS.set('timeScope', S.tv.scope); renderView(); break;
    case 'tv-lists': tvListsMenu(a); break;
    case 'tv-toggle': { const k = a.dataset.key; S.collapsed.has(k) ? S.collapsed.delete(k) : S.collapsed.add(k); LS.set('collapsed', [...S.collapsed]); renderView(); break; }
    case 'tv-entries': S.tv.entries = !S.tv.entries; LS.set('timeEntries', S.tv.entries); renderView(); break;
    case 'tv-sheet': timesheet(); break;
  }
});
let sideRet = null;
// 2.26.x (#953): the drawer opened again by Back (no focus move, no button to return to)
function sideDrawerOpen() { $('#side').classList.add('open'); $('#scrim').classList.remove('hidden'); popOnClose = closeSide; sideRet = null; }
function closeSide() {
  // 2.16.0 (#473): the focus goes back to the menu button when it was in the drawer
  if ($('#side.open') && sideRet && sideRet.isConnected && ($('#side').contains(document.activeElement) || document.activeElement === document.body)) { const r = sideRet; setTimeout(() => { if (!document) return; if (!$('#side.open') && (document.activeElement === document.body || !document.activeElement || $('#side').contains(document.activeElement)) && r.isConnected && r.offsetParent) r.focus({preventScroll: true}); }, 0); }
  sideRet = null;
  $('#side').classList.remove('open'); if (!$('.qadd.sheet') && $('#pop').classList.contains('hidden')) $('#scrim').classList.add('hidden'); }
$('#scrim').addEventListener('click', () => { closeSide(); closePop(); });
$('#fab').addEventListener('click', () => openQuickSheet());

document.addEventListener('input', e => {
  const t = e.target;
  if (t.id === 'qinput' || t.id === 'qsheet') updateChips(t);
  if (t.id === 'd-title') { autosize(t); queueSave(S.sel, 'title', t.value.replace(/\n/g, ' ')); }
  if (t.id === 'c-input' && t.value) commentTyping();  // 2.22.0 (#693)
  if (t.id === 'c-input') { autosize(t); S.drafts[S.sel] = t.value; mentionUpdate(t); t.closest('.ccomp')?.classList.toggle('used', !!t.value || !!(S.cfiles[S.sel] || []).length); }
  if (t.classList?.contains('c-edit-input')) { autosize(t); mentionUpdate(t); }
  if (t.id === 'd-content') { autosize(t); queueSave(S.sel, 'content', t.value); }
  if (t.id === 'searchq') doSearch(t.value);
});
document.addEventListener('change', async e => {
  const t = e.target;
  if (t.id === 'd-file') { uploadFiles(S.sel, t.files); t.value = ''; return; }
  if (t.id === 'c-file') { addCommentFiles(t.files); t.value = ''; return; }
  if (t.id === 'd-url') { saveLink(t.value); return; }
  if (t.id === 'd-list') patchUndoable(S.sel, {list_id: +t.value}, tr('Moved to {0}', lname(listById(+t.value))));
  if (t.id === 'd-sec') patchTask(S.sel, {section_id: t.value ? +t.value : null});
  if (t.id === 'd-ms') { msToggle(S.sel, t.checked); return; }  // 2.18.0 (#430)
  if (t.id === 'd-msel') { const m = t.value ? S.tasks.get(+t.value) : null; patchUndoable(S.sel, {milestone_id: m ? m.id : null}, m ? tr('Milestone: {0}', m.title) : tr('Milestone removed')); return; }
  if (t.id === 'd-ttype') patchUndoable(S.sel, {ttype: t.value}, t.value ? tr('Type: {0}', ttName(t.value)) : tr('Type removed'));  // 2.4.0 (#340)
  if (t.dataset?.cf !== undefined && t.closest('#detail')) saveField(t);
  if (t.id === 'pomo-task') { pomoTask = t.value; LS.set('pomoTask', t.value); }
  if ((t.id === 'tv-from' || t.id === 'tv-to') && t.value) { S.tv[t.id.slice(3)] = t.value; LS.set(t.id === 'tv-from' ? 'timeFrom' : 'timeTo', t.value); renderView(); }
});
document.addEventListener('keydown', async e => {
  const t = e.target;
  if (e.key === 'Enter' && !e.isComposing) {
    if (t.id === 'qinput' || t.id === 'qsheet') { e.preventDefault(); submitQuick(t); return; }
    if (t.id === 'd-title') { e.preventDefault(); t.blur(); return; }
    if (t.id === 'd-url') { e.preventDefault(); t.blur(); return; }
    if (t.dataset?.cf !== undefined && t.tagName === 'INPUT') { e.preventDefault(); t.blur(); return; }
    if (t.classList?.contains('nitem')) { e.preventDefault(); newsOpen(+t.dataset.i); return; }
    if (t.id === 'd-sub' && t.value.trim()) {
      const p = taskById(S.sel);
      const r = parseQuick(t.value.trim(), new Set());
      const v = t.value; t.value = '';
      const nt = await api('POST', '/api/tasks', {title: r.title || v, parent_id: p.id, list_id: p.list_id, due: r.due, due_time: r.due_time, priority: r.priority || 0});
      await load(); renderDetail(); render(); $('#d-sub').focus();
      if (nt?.id) histCreate(tr('Subtask {0} added', qn(String(nt.title || r.title || v).slice(0, 40))), nt);
      return;
    }
    if (t.id === 'd-tag' && t.value.trim()) {
      const p = taskById(S.sel); const v = t.value.trim().replace(/^#/, ''); t.value = '';
      await tagAdd(p, v); $('#d-tag')?.focus(); return;
    }
    if (t.dataset.kadd !== undefined && t.value.trim()) {
      const lid = S.route.key === 'inbox' ? inbox().id : +S.route.key.slice(2);
      const r = parseQuick(t.value.trim()); t.value = '';
      await createTask({title: r.title, list_id: lid, section_id: t.dataset.kadd ? +t.dataset.kadd : null, due: r.due, due_time: r.due_time, priority: r.priority || 0, tags: r.tags || [], repeat: r.repeat || ''});
      $(`[data-kadd="${t.dataset.kadd}"]`)?.focus(); return;
    }
    if (t.dataset.qadd !== undefined && t.value.trim()) {
      const r = parseQuick(t.value.trim()); t.value = '';
      await createTask({title: r.title, priority: +t.dataset.qadd, due: r.due, due_time: r.due_time, tags: r.tags || [], list_id: r.list_id || mxList(), repeat: r.repeat || ''});
      $(`[data-qadd="${t.dataset.qadd}"]`)?.focus(); return;
    }
  }
  if (e.key === 'Escape') {
    const lb = $('.lightbox'); if (lb) { lb.remove(); return; }
    const ts = $('.tsheet'); if (ts && !$('.modal')) { $('[data-ts="close"]', ts).click(); return; }
    if (!$('#pop').classList.contains('hidden') || $('.qadd.sheet')) { closePop(); return; }
    if (S.multi.size || S.multiMode) { S.multi.clear(); S.multiMode = false; render(); return; }
    const m = $$('.modal:not(.authscreen)').pop(); if (m) { m.remove(); return; }
    if ($('#side.open')) { closeSide(); return; }  // 2.16.0 (#473): Esc closes the drawer
    if (/INPUT|TEXTAREA/.test(t.tagName)) { t.blur(); return; }
    if (S.sel) closeDetail();
    return;
  }
  // 2.4.0 (#187): Ctrl+Space = quick capture from anywhere (also while typing somewhere else)
  if (e.ctrlKey && !e.altKey && !e.metaKey && (e.code === 'Space' || e.key === ' ') && t.id !== 'qsheet' && !$('.authscreen')) { e.preventDefault(); quickCapture(); return; }
  if (/INPUT|TEXTAREA|SELECT/.test(t.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === 'n') { e.preventDefault(); const q = currentQuickInput(); if (q && (!isMobile() || tabletDock())) q.focus(); else openQuickSheet(); }
  if (e.key === 'q' && !$('.modal')) { e.preventDefault(); quickCapture(); }
  if (e.key === 'a' && !$('.modal') && !chatFull() && feat('agents') && chatFabAgent()) { e.preventDefault(); chatPop(); }  // 2.29.0 (#363)
  if (e.key === '/') { e.preventDefault(); go('search'); }
});
document.addEventListener('focusout', e => {
  if (e.target.id === 'c-input' || e.target.classList?.contains('c-edit-input')) setTimeout(() => { if (S.mp && document.activeElement !== S.mp.ta) mentionClose(); }, 150);
  if (e.target.id === 'd-title' || e.target.id === 'd-content') flushSaves();
  if (e.target.id === 'd-content' && e.target.value.trim()) {  // back to the rendered markdown
    const t = taskById(S.sel); if (t) t.content = e.target.value;
    S.editContent = false;
    const md = $('#d-md'); if (md) { md.innerHTML = mdMentions(renderMd(e.target.value, false, {lid: taskById(S.sel)?.list_id}), taskById(S.sel)); md.classList.remove('hidden'); e.target.classList.add('hidden'); }
  }
});
function editContent() {
  S.editContent = true;
  const ta = $('#d-content'), md = $('#d-md'); if (!ta) return;
  md.classList.add('hidden'); ta.classList.remove('hidden'); autosize(ta); ta.focus();
}
function toggleMdCheckbox(i) {
  const t = taskById(S.sel); if (!t) return;
  const lines = t.content.split('\n');
  lines[i] = lines[i].replace(/\[( |x|X)\]/, m => m === '[ ]' ? '[x]' : '[ ]');
  const was = t.content;
  t.content = lines.join('\n');
  $('#d-content').value = t.content; $('#d-md').innerHTML = mdMentions(renderMd(t.content, false, {lid: t.list_id}), t);
  HIST.sess++;
  queueSave(t.id, 'content', t.content, was);
}

// ---- 2.22.0 (#678): the quick add box (docked composer, inline box, the sheet) gets the @ picker of the comment box
// (the people and agents of the list the task goes to) and takes pasted images / files: they become the new task's files
S.qfiles = {};  // input id -> [File]
function qTargetList(input) {
  const r = parseQuick(input.value, S.quick.ignore), o = input.id === 'qinput' && S.qov?.key === S.route.key ? S.qov : {};
  const d = input.id === 'qsheet' && S.quickPreset.capture ? {} : {...quickDefaults(), ...(input.id === 'qsheet' ? S.quickPreset : {})};
  return listById(o.list_id || r.list_id || d.list_id || inbox()?.id);
}
function qPeople(input) {
  const l = qTargetList(input);
  if (!l || !collab() || !l.shared) return [];
  return listPeople(l).filter(p => !S.me || p.user_id !== S.me.id).map(p => ({id: p.user_id, user_id: p.user_id, name: p.name}));
}
function qMentionUpdate(input) {
  const box = input.closest('.qadd'); if (!box) return;
  let pick = box.querySelector('.mpick.qmpick');
  const pre = input.value.slice(0, input.selectionStart ?? input.value.length), m = pre.match(/(?:^|\s)@([^\s@<>~#!]{0,30})$/u);
  const people = m ? qPeople(input) : [];
  const q = m ? m[1].toLowerCase() : '';
  const items = people.filter(p => { const n = p.name.toLowerCase(); return n.startsWith(q) || n.split(/\s+/).some(w => w.startsWith(q)); }).slice(0, 6);
  if (!items.length) { if (pick) pick.classList.add('hidden'); if (S.qmp) { input.removeAttribute('aria-activedescendant'); S.qmp = null; } return; }
  if (!pick) { pick = document.createElement('div'); pick.className = 'mpick qmpick'; pick.id = 'qmp-' + input.id; pick.setAttribute('role', 'listbox'); pick.setAttribute('aria-label', tr('Mention someone')); box.appendChild(pick); }
  S.qmp = {input, items, i: 0, start: pre.length - m[1].length - 1, pick};
  pick.classList.remove('hidden');
  pick.innerHTML = items.map((p, i) => `<button type="button" role="option" id="${pick.id}-o${i}" tabindex="-1" aria-selected="${i === 0}" class="${i === 0 ? 'on' : ''}" data-act="qmention-pick" data-i="${i}">${av(p.user_id, p.name)}${esc(p.name)}</button>`).join('');
  input.setAttribute('aria-controls', pick.id); input.setAttribute('aria-activedescendant', pick.id + '-o0');
}
function qMentionPick(i) {
  const mp = S.qmp; if (!mp) return;
  const p = mp.items[i], inp = mp.input, caret = inp.selectionStart ?? inp.value.length;
  inp.value = inp.value.slice(0, mp.start) + '@' + p.name + ' ' + inp.value.slice(caret);
  const pos = mp.start + p.name.length + 2;
  inp.focus(); inp.setSelectionRange(pos, pos);
  mp.pick.classList.add('hidden'); inp.removeAttribute('aria-activedescendant'); S.qmp = null;
  updateChips(inp);
}
function qMentionClose() { if (S.qmp) { S.qmp.pick.classList.add('hidden'); S.qmp.input.removeAttribute('aria-activedescendant'); S.qmp = null; } }
document.addEventListener('input', e => { if (e.target.id === 'qinput' || e.target.id === 'qsheet') qMentionUpdate(e.target); });
document.addEventListener('focusout', e => { if ((e.target.id === 'qinput' || e.target.id === 'qsheet') && S.qmp?.input === e.target) setTimeout(qMentionClose, 150); });
document.addEventListener('keydown', e => {
  const t = e.target; if (!S.qmp || S.qmp.input !== t) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault(); e.stopImmediatePropagation(); S.qmp.i = (S.qmp.i + (e.key === 'ArrowDown' ? 1 : -1) + S.qmp.items.length) % S.qmp.items.length;
    $$('button', S.qmp.pick).forEach((b, i) => { b.classList.toggle('on', i === S.qmp.i); b.setAttribute('aria-selected', i === S.qmp.i); });
    t.setAttribute('aria-activedescendant', S.qmp.pick.id + '-o' + S.qmp.i); return;
  }
  if ((e.key === 'Enter' || e.key === 'Tab') && !e.isComposing) { e.preventDefault(); e.stopImmediatePropagation(); qMentionPick(S.qmp.i); return; }
  if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); qMentionClose(); }
}, true);
document.addEventListener('click', e => { const b = e.target.closest('[data-act="qmention-pick"]'); if (b) { e.preventDefault(); e.stopPropagation(); qMentionPick(+b.dataset.i); } }, true);
// pasted files: chips under the box, uploaded after the task was created (then its panel opens)
function qFilesDraw(input) {
  const box = input.closest('.qadd'); if (!box) return;
  let el = box.querySelector('.qfiles');
  const fs = S.qfiles[input.id] || [];
  if (!fs.length) { el?.remove(); return; }
  if (!el) { el = document.createElement('div'); el.className = 'qfiles'; box.appendChild(el); }
  el.innerHTML = fs.map((f, i) => `<span class="qfile">${ic('clip', 's')}<span class="qfn">${esc(f.name || tr('Image'))}</span><button type="button" class="iconbtn" data-act="qfile-x" data-in="${input.id}" data-i="${i}" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove {0}', f.name || tr('Image')))}">${ic('x', 's')}</button></span>`).join('');
}
document.addEventListener('paste', e => {
  const t = document.activeElement; if (!t || (t.id !== 'qinput' && t.id !== 'qsheet')) return;
  const files = [...(e.clipboardData?.files || [])].filter(f => f.size > 0);
  if (!files.length) return;  // plain text paste stays normal
  e.preventDefault(); e.stopImmediatePropagation();
  const named = files.map((f, i) => f.name && f.name !== 'image.png' ? f : new File([f], `${tr('Image')} ${new Date().toISOString().slice(0, 16).replace('T', ' ').replace(':', '-')}${files.length > 1 ? ' ' + (i + 1) : ''}.${(f.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`, {type: f.type}));
  (S.qfiles[t.id] ||= []).push(...named);
  qFilesDraw(t);
  toast(trn('{0} file added: it is attached when you add the task', '{0} files added: they are attached when you add the task', named.length));
}, true);
document.addEventListener('click', e => {
  const b = e.target.closest('[data-act="qfile-x"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const fs = S.qfiles[b.dataset.in] || []; fs.splice(+b.dataset.i, 1);
  const inp = document.getElementById(b.dataset.in); if (inp) { qFilesDraw(inp); inp.focus(); }
}, true);
