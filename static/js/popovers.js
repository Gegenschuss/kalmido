/* Kalmido web client: Popovers (date, priority, list, tags, reminders, repeat ...).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ popovers
let popRet = null;  // 2.16.0 (#473): where the focus goes back to when a popover / menu closes
function closePop() { popFocusBack(); document.body.classList.remove('pop-open'); /* 2.28.0 (#976) */ const t = $('#toast'); if (t && !t.classList.contains('hidden') && $('#pop.sheet:not(.hidden)')) requestAnimationFrame(() => toastPlace(t)); $('#pop').classList.add('hidden'); $('#pop').classList.remove('sheet', 'overmodal'); $('#scrim').classList.add('hidden'); $('#scrim').classList.remove('clear', 'overmodal'); popOnClose && popOnClose(); popOnClose = null; }
let popOnClose = null;
function openPop(anchor, html, onClose) {
  const p = $('#pop');
  p.onclick = null;  // a click handler of the previous popover (menu, calendar event) never carries over
  p.onpointerdown = null; p.ondblclick = null; p.classList.remove('bellpop', 'bpfull'); p.style.width = '';  // 2.7.0: nothing of the bell's dropdown carries over
  if (p.classList.contains('hidden')) { const ae = document.activeElement; popRet = anchor?.focus && anchor.isConnected && !anchor.closest?.('#pop') ? anchor : ae && ae !== document.body && !ae.closest?.('#pop') ? ae : null; }
  p.innerHTML = html; p.classList.remove('hidden'); document.body.classList.add('pop-open');  // 2.28.0 (#976): the grips step aside
  $('#scrim').classList.remove('hidden');
  // #318: a menu opened from inside a dialog (e.g. Settings > Agents > "Share a list with an agent…") goes above it
  const om = !!anchor?.closest?.('.modal'); p.classList.toggle('overmodal', om); $('#scrim').classList.toggle('overmodal', om);
  popOnClose = onClose || null;
  if (isMobile()) { p.classList.add('sheet'); const t = $('#toast'); if (t && !t.classList.contains('hidden')) requestAnimationFrame(() => toastPlace(t)); return p; }  // 2.13.0 (#453 A12)
  $('#scrim').classList.add('clear');
  const r = anchor.getBoundingClientRect();
  const w = p.offsetWidth, h = p.offsetHeight;
  let x = Math.min(r.left, innerWidth - w - 12), y = r.bottom + 6;
  if (y + h > innerHeight - 12) y = Math.max(12, r.top - h - 6);
  p.style.left = Math.max(12, x) + 'px'; p.style.top = y + 'px';
  return p;
}
function menu(anchor, items) {
  items = items.filter(Boolean).filter((x, i, a) => x !== '-' || (i > 0 && i < a.length - 1 && a[i - 1] !== '-'));  // 2.27.0: no doubled / edge separators
  const btn = (it, i, j) => `<button role="menuitem" data-i="${i}" ${j != null ? `data-j="${j}"` : ''} class="${it.on ? 'on' : ''} ${it.cls || ''}" ${it.dis ? 'disabled aria-disabled="true"' : ''} ${it.title ? `title="${esc(it.title)}"` : ''}>${it.dot ? `<span class="mdot">${hdot(it.dot)}</span>` : it.icon ? ic(it.icon, 's') : ''}<span class="ml">${esc(it.label)}${it.sub ? `<small class="msub">${esc(it.sub)}</small>` : ''}</span>${it.keys && !isMobile() ? kb(it.keys) : ''}${it.on ? `<span class="mchk" aria-hidden="true">${ic('check', 's')}</span>` : ''}</button>`;
  // {row: [item, item]} = one line of equal buttons (1.5.1: "Today" / "Tomorrow" on top of the task menu)
  const p = openPop(anchor, `<div class="menu-list" role="menu">${items.map((it, i) => it === '-' ? '<hr>' : it.row ? `<div class="mquick" role="group">${it.row.map((x, j) => btn(x, i, j)).join('')}</div>` : btn(it, i)).join('')}</div>`);
  p.onclick = e => { const b = e.target.closest('[data-i]'); if (!b || b.disabled) return; let it = items[+b.dataset.i]; if (it.row) it = it.row[+b.dataset.j]; closePop(); it.fn(); };
  // 2.16.0 (#473): the menu gets the focus (first item); ↑ ↓ Home End move in it, Esc / Tab out close it (keydown below)
  setTimeout(() => { if (document && !p.classList.contains('hidden') && !p.contains(document.activeElement)) p.querySelector('[role="menuitem"]:not([disabled])')?.focus({preventScroll: true}); }, 0);
  return p;
}
function popFocusBack() {
  const r = popRet; popRet = null;
  if ($('#pop').classList.contains('hidden') || !r || !r.isConnected) return;
  const a = document.activeElement;
  if (a && a !== document.body && !$('#pop').contains(a)) return;  // the focus went somewhere on purpose
  if (isTouch() && typing(r)) return;  // no phone keyboard popping up
  setTimeout(() => { if (!document) return; const b = document.activeElement; if ((!b || b === document.body || $('#pop').contains(b)) && r.isConnected) { try { r.focus({preventScroll: true}); } catch { /* gone */ } } }, 0);
}
document.addEventListener('keydown', e => {
  const m = e.target.closest?.('#pop [role="menu"]'); if (!m || e.altKey || e.ctrlKey || e.metaKey) return;
  const it = $$('[role="menuitem"]:not([disabled])', m), i = it.indexOf(e.target.closest('[role="menuitem"]'));
  const to = {ArrowDown: i + 1, ArrowUp: i - 1, ArrowRight: e.target.closest('.mquick') ? i + 1 : null, ArrowLeft: e.target.closest('.mquick') ? i - 1 : null, Home: 0, End: it.length - 1}[e.key];
  if (to != null && it.length) { e.preventDefault(); e.stopPropagation(); it[(to + it.length) % it.length].focus(); }
  else if (e.key === 'Tab') closePop();
});
// ---- 2.0.8 (#323): on a phone every <select> opens an app-style bottom sheet (like the menus) instead of the system
// picker: the field's label on top, the options with their icon / emoji / avatar, a check on the current value, a search
// field above 10 options, keyboard (↑ ↓ Home End, Enter, Esc). One enhancer for the whole app (task panel, dialogs,
// settings), no per-select code; picking sets the value and fires input + change, so every existing handler just works.
// Stays native (the rule): desktop (wider than 899 px), multiple / size > 1, disabled, fewer than 2 options, a select
// inside a popover or sheet itself (#pop, e.g. the date picker's repeat / duration: a sheet cannot open over a sheet),
// and any select marked data-native. Hints for the look: data-sheet-ico="<icon>" on the select = that icon for options
// without an emoji; data-sheet-av = options are users (avatar by value); data-ico on an option overrides.
const selSheetOk = el => el && el.tagName === 'SELECT' && isMobile() && !el.multiple && !(el.size > 1) && !el.disabled
  && el.options.length >= 2 && !el.closest('#pop') && !el.hasAttribute('data-native');
function selLabel(el) {
  const l = (el.id && document.querySelector(`label[for="${window.CSS?.escape ? CSS.escape(el.id) : el.id.replace(/["\\]/g, '\\$&')}"]`)) || (el.previousElementSibling?.tagName === 'LABEL' ? el.previousElementSibling : null) || el.closest('label');
  return (el.getAttribute('aria-label') || (l && l.textContent) || '').trim();
}
function selSheet(el) {
  const opts = [...el.options], search = opts.length > 10, lab = selLabel(el);
  const icoFor = o => {
    const tx = o.textContent.trim(), m = tx.match(EMO_RE);
    if (el.hasAttribute('data-sheet-av')) return [o.value ? av(+o.value, tx.replace(/\s*\([^)]*\)$/, ''), 'avatar sm') : ic('user', 's'), tx];  // "Alice (me)" -> initials of Alice
    if (m) return [`<span class="ssemo" aria-hidden="true">${esc(m[1])}</span>`, tx.slice(m[0].length)];
    const n = o.dataset.ico || el.dataset.sheetIco;
    return [n ? ic(n, 's') : '', tx];
  };
  const item = (o, i) => { const [i0, tx] = icoFor(o), on = o.selected;
    return `<button type="button" role="option" data-si="${i}" aria-selected="${on}" class="${on ? 'on' : ''}" ${o.disabled ? 'disabled aria-disabled="true"' : ''} data-q="${esc(tx.toLowerCase())}">${i0}<span class="ml">${esc(tx)}</span>${on ? `<span class="sschk">${ic('check', 's')}</span>` : ''}</button>`; };
  let body = '', grp = null;
  opts.forEach((o, i) => {
    const g = o.parentElement.tagName === 'OPTGROUP' ? o.parentElement : null;
    if (g !== grp) { grp = g; if (g) body += `<div class="ssgrp" role="presentation">${esc(g.label)}</div>`; }
    body += item(o, i);
  });
  const p = openPop(el, `<div class="selsheet">${lab ? `<div class="sshead" id="ss-h">${esc(lab)}</div>` : ''}${search ? `<div class="sssearch">${ic('search', 's')}<input id="ss-q" type="search" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search'))}" autocomplete="off" enterkeyhint="search"></div>` : ''}<div class="menu-list" role="listbox" ${lab ? 'aria-labelledby="ss-h"' : `aria-label="${esc(tr('Choose'))}"`}>${body}</div></div>`, () => { if (el.isConnected) try { el.focus({preventScroll: true}); } catch { /* ignore */ } });
  p.classList.add('selpop');
  const btns = () => [...p.querySelectorAll('[data-si]')].filter(b => !b.hidden && !b.disabled);
  p.onclick = e => {
    const b = e.target.closest('[data-si]'); if (!b || b.disabled) return;
    const o = opts[+b.dataset.si], was = el.value;
    closePop();
    if (o && o.value !== was) { el.value = o.value; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }
  };
  p.addEventListener('keydown', e => {
    const list = btns(), i = list.indexOf(document.activeElement);
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) {
      e.preventDefault(); e.stopPropagation();
      const n = e.key === 'Home' ? 0 : e.key === 'End' ? list.length - 1 : e.key === 'ArrowDown' ? Math.min(list.length - 1, i + 1) : Math.max(0, i - 1);
      list[n]?.focus();
    } else if (e.key === 'Enter' && e.target.id === 'ss-q') { e.preventDefault(); list[0]?.click(); }
  });
  const q = p.querySelector('#ss-q');
  if (q) q.addEventListener('input', () => { const v = q.value.trim().toLowerCase(); p.querySelectorAll('[data-si]').forEach(b => { b.hidden = !!v && !b.dataset.q.includes(v); }); p.querySelectorAll('.ssgrp').forEach(g => { g.hidden = !!v; }); });
  const cur = p.querySelector('[data-si].on');
  setTimeout(() => { cur?.scrollIntoView?.({block: 'center'}); if (!q || !isTouch()) (cur || btns()[0])?.focus({preventScroll: true}); }, 0);
  return p;
}
(() => {
  let t0 = null;
  document.addEventListener('touchstart', e => { const el = e.target.closest?.('select'); t0 = el && e.touches[0] ? {el, x: e.touches[0].clientX, y: e.touches[0].clientY} : null; }, {capture: true, passive: true});
  document.addEventListener('touchend', e => {
    const el = e.target.closest?.('select'); if (!selSheetOk(el) || !t0 || t0.el !== el) return;
    const c = e.changedTouches[0]; if (c && Math.hypot(c.clientX - t0.x, c.clientY - t0.y) > 10) return;  // a scroll, not a tap
    e.preventDefault(); t0 = null; selSheet(el);
  }, {capture: true, passive: false});
  // mouse / pen / a tap without touch events: the system picker opens on mousedown
  document.addEventListener('mousedown', e => { const el = e.target.closest?.('select'); if (!selSheetOk(el)) return; e.preventDefault(); selSheet(el); }, true);
  document.addEventListener('keydown', e => {
    const el = e.target; if (!selSheetOk(el)) return;
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'F4' || (e.altKey && ['ArrowDown', 'ArrowUp'].includes(e.key))) { e.preventDefault(); e.stopPropagation(); selSheet(el); }
  }, true);
})();
function prioMenu(anchor, id) {
  const t = taskById(id);
  if (!canEdit(t)) { roToast(); return; }
  menu(anchor, [[5, N_('High')], [3, N_('Medium')], [1, N_('Low')], [0, N_('None')]].map(([p, n]) => ({label: tr(n), icon: 'flag', on: t.priority === p, cls: p ? 'flag-' + p : '', fn: () => patchTask(id, {priority: p})})));
}
// 2.6.1 (#401): by default every change in the date popover (day, time, start, duration, reminders, repeat) is saved at
// once (a short pause bundles quick taps); the popover stays open for more, "Saved" shows in its foot, and closing it
// leaves ONE undo step for the whole visit with a toast "Date: … · Undo". "Undo" in the foot puts everything back and
// closes. Settings > General > "Confirm changes with OK" (date_confirm) brings back Cancel / OK.
const dateInstant = () => S.settings?.date_confirm !== '1';
function datePop(anchor, id) {
  const t = taskById(id);
  if (!canEdit(t)) { roToast(); return; }
  const st = {due: t.due, due_time: t.due_time, reminders: t.reminders, repeat: t.repeat, repeat_from: t.repeat_from, start: t.start, duration: t.duration, month: (t.due || today()).slice(0, 7),
    deadline: t.deadline || 0, nag: t.nag || ''};
  const instant = dateInstant(), before = snapTask(t);
  const body = () => ({due: st.due, due_time: st.due ? st.due_time : null, reminders: st.due ? st.reminders : '', repeat: st.due ? st.repeat : '', repeat_from: st.repeat_from,
    start: st.due && st.start && st.start < st.due ? st.start : null, duration: st.due_time ? (st.duration || 30) : null,
    ...(st.due ? {deadline: st.deadline, nag: st.nag} : {deadline: 0, nag: ''})});
  const msgOf = () => st.due ? tr('Date: {0}', dayLabel(st.due)) : tr('Date removed');
  // instant mode: what was sent last, the running request chain, the dependent tasks the server moved along (first prev)
  const I = {sig: JSON.stringify(body()), timer: null, chain: Promise.resolve(), saved: false, shifted: new Map(), done: false, last: null};
  const send = () => {
    clearTimeout(I.timer); I.timer = null;
    const b = body(), sig = JSON.stringify(b);
    if (sig === I.sig) return I.chain;
    I.sig = sig;
    I.chain = I.chain.then(async () => {
      const r = await patchTask(id, b, true);
      I.saved = true; I.last = r;
      for (const x of r?.shifted || []) { const o = I.shifted.get(x.id); I.shifted.set(x.id, o ? {...x, prev_start: o.prev_start, prev_due: o.prev_due} : x); }
      const f = $('#pop .psaved'); if (f && !I.done) { f.innerHTML = `${ic('check', 's')}<span>${tr('Saved')}</span>`; f.classList.add('on'); }
      const u = $('#pop [data-q="revert"]'); if (u && !I.done) u.hidden = false;
    }).catch(() => { /* api() showed the error; the popover shows the state it has */ });
    return I.chain;
  };
  const changed = () => { if (!instant || I.done) return; clearTimeout(I.timer); I.timer = setTimeout(send, 350); };
  // closing (Done, the scrim, Esc, another popover): send what is left, then one history step + the toast
  const finish = async () => {
    if (I.done) return; I.done = true;
    await send();
    if (!I.saved) return;
    const cur = S.tasks.get(id) || I.last;
    shiftUndo(before, cur ? {...cur, id, shifted: [...I.shifted.values()]} : null, msgOf());
  };
  const revert = async () => {
    I.done = true; clearTimeout(I.timer);
    await I.chain;
    if (!I.saved) return;
    const back = {}; for (const k of ['due', 'due_time', 'reminders', 'repeat', 'repeat_from', 'start', 'duration', 'deadline', 'nag']) back[k] = before[k] ?? (k === 'reminders' || k === 'repeat' || k === 'nag' ? '' : k === 'deadline' ? 0 : null);
    try { await patchTask(id, back, true); } catch { return; }
    // dependent tasks the server moved along: back to where they were
    const items = {}; for (const x of I.shifted.values()) items[x.id] = {start: x.prev_start, due: x.prev_due};
    if (Object.keys(items).length) { try { await histBatch('patch_each', Object.keys(items).map(Number), {items}); await load(); render(); } catch { /* shown */ } }
    toast(tr('Changes undone'));
  };
  const draw = () => {
    const [y, m] = st.month.split('-').map(Number);
    const start = weekStartOf(`${st.month}-01`);
    let g = wdOrder().map(i => `<div class="wd" aria-label="${esc(WDL[i])}">${WD[i]}</div>`).join('');
    for (let i = 0; i < 42; i++) { const d = addDays(start, i); if (i === 35 && pd(d).getMonth() !== m - 1) break; g += `<button class="d ${pd(d).getMonth() !== m - 1 ? 'out' : ''} ${d === today() ? 'today' : ''} ${d === st.due ? 'sel' : ''}" data-d="${d}">${pd(d).getDate()}</button>`; }
    const rems = new Set((st.reminders || '').split(',').filter(Boolean));
    const wd = st.due ? RR_WD[pd(st.due).getDay()] : 'MO', md = st.due ? pd(st.due).getDate() : 1;
    const presets = [['', tr('None')], ['FREQ=DAILY', tr('Daily')], ['FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR', tr('Weekdays')], [`FREQ=WEEKLY;BYDAY=${wd}`, tr('Weekly ({0})', WD[RR_WD.indexOf(wd)])], [`FREQ=WEEKLY;INTERVAL=2;BYDAY=${wd}`, tr('Every 2 weeks ({0})', WD[RR_WD.indexOf(wd)])], [`FREQ=MONTHLY;BYMONTHDAY=${md}`, tr('Monthly (on day {0})', md)], ['FREQ=YEARLY', tr('Yearly')]];
    const cur = rrBase(st.repeat), end = rrEnd(st.repeat);
    const custom = cur && !presets.some(p => p[0] === cur);
    const cu = st.cust ? rrForm(cur) : null;
    return `<div class="quick">
        <button data-q="0">${ic('sun')}${tr('Today')}</button><button data-q="1">${ic('sunrise')}${tr('Tomorrow')}</button><button data-q="w">${ic('week')}${tr('Next week')}</button><button data-q="x">${ic('ban')}${tr('No date|clear')}</button></div>
      <div class="mcal"><div class="mh"><button class="iconbtn" data-mm="-1">${ic('left')}</button>${MON[m - 1]} ${y}<button class="iconbtn" data-mm="1">${ic('right')}</button></div><div class="grid">${g}</div></div>
      <div class="prow">${ic('clock', 's')}${timeIn('p-time', st.due_time || '', {label: tr('Time'), empty: tr('all day')})}${st.due_time ? `<button class="iconbtn" data-q="notime" title="${tr('All day')}" aria-label="${tr('All day')}">${ic('x', 's')}</button>` : ''}</div>
      ${st.due_time ? `<div class="prow">${ic('timer', 's')}<select id="p-dur" aria-label="${esc(tr('Duration'))}">${[15, 30, 45, 60, 90, 120, 180, 240].map(v => `<option value="${v}" ${(st.duration || 30) === v ? 'selected' : ''}>${tr('Duration {0}', v < 60 ? v + ' min' : fmtNum(v / 60) + ' h')}</option>`).join('')}</select></div>` : ''}
      <div class="prow">${ic('timeline', 's')}<span class="muted" style="font-size:var(--fs-s)">${tr('Start|date')}</span>${dateIn('p-start', st.start || '', {max: st.due || '', label: tr('Start|date'), empty: tr('none')})}${st.start ? `<button class="iconbtn" data-q="nostart" title="${tr('No date range')}" aria-label="${tr('No date range')}">${ic('x', 's')}</button>` : ''}</div>
      <div class="prow">${ic('bell', 's')}<span class="muted plab">${tr('Reminder')}</span><div class="remchips" role="group" aria-label="${esc(tr('Reminder'))}">${[...REM_CHIPS, ...[...rems].filter(v => !REM_CHIPS.includes(v)).sort((a, b) => a - b)].map(v => `<button class="${rems.has(v) ? 'on' : ''}" data-rem="${v}" aria-pressed="${rems.has(v)}" title="${esc(fmtRem(v))}">${esc(remChip(v))}</button>`).join('')}<button class="${st.remc ? 'on' : ''}" data-q="remc" aria-expanded="${!!st.remc}">${tr('Other…|reminder')}</button></div></div>
      ${st.remc ? `<div class="prow remcust" role="group" aria-label="${esc(tr('Own reminder'))}"><input type="number" id="p-remn" min="1" max="999" inputmode="numeric" value="${esc(String(st.remn || 3))}" aria-label="${esc(tr('How many'))}"><select id="p-remu" aria-label="${esc(tr('Unit'))}">${REM_UNITS.map(([v, n]) => `<option value="${v}" ${String(st.remu || '1440') === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select><span class="muted">${tr('before|reminder')}</span><button class="btn sm" data-q="remadd">${tr('Add')}</button></div>` : ''}
      ${st.due ? `<div class="prow pdl"><label class="chkl"><input type="checkbox" id="p-dl" ${st.deadline ? 'checked' : ''}> ${ic('flag', 's')}${tr('Deadline')}</label>${st.deadline ? `<label class="chkl"><input type="checkbox" id="p-dlt" ${st.deadline === 2 ? 'checked' : ''}> ${tr('On Today from the first reminder')}</label>` : ''}</div>
      <div class="prow">${ic('repeat', 's')}<label class="muted pnagl" for="p-nag">${tr('Repeat reminder')}</label><select id="p-nag">${[['', tr('as the list ({0})', listById(t.list_id)?.nag ? nagLabel(listById(t.list_id).nag) : tr('Off|nag'))], ...NAG_OPTS.map(([v, n]) => [v, tr(n)])].map(([v, n]) => `<option value="${v}" ${st.nag === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>` : ''}
      <div class="prow">${ic('repeat', 's')}<select id="p-rep" aria-label="${esc(tr('Repeat'))}">${presets.map(([v, n]) => `<option value="${v}" ${cur === v ? 'selected' : ''}>${n}</option>`).join('')}${custom ? `<option value="${esc(cur)}" selected>${esc(repeatLabelBase(cur))}</option>` : ''}<option value="__custom">${tr('Custom…')}</option></select>${custom && !cu ? `<button class="iconbtn" data-q="cust" title="${tr('Edit')}" aria-label="${tr('Edit repeat')}">${ic('edit', 's')}</button>` : ''}</div>
      ${cu ? `<div class="rrcust" role="group" aria-label="${tr('Custom repeat')}">
        <div class="prow"><span class="muted">${tr('Every|repeat')}</span><input type="number" id="p-rn" min="1" max="99" value="${cu.n}" inputmode="numeric" aria-label="${tr('Interval')}"><select id="p-rf" aria-label="${tr('Unit')}">${[['DAILY', trn('day', 'days', cu.n)], ['WEEKLY', trn('week', 'weeks', cu.n)], ['MONTHLY', trn('month', 'months', cu.n)], ['YEARLY', trn('year', 'years', cu.n)]].map(([v, n]) => `<option value="${v}" ${cu.f === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>
        ${cu.f === 'WEEKLY' ? `<div class="prow rrwd" role="group" aria-label="${tr('On')}">${wdOrder().map(i => `<button class="${cu.days.has(RR_WD[i]) ? 'on' : ''}" data-rwd="${RR_WD[i]}" aria-pressed="${cu.days.has(RR_WD[i])}" aria-label="${esc(WDL[i])}">${esc(WD[i])}</button>`).join('')}</div>` : ''}
        ${cu.extra ? `<div class="shint keep">${tr('This rule has more parts than the form shows; edit it below.')}</div>` : ''}
        <details class="rrx" ${cu.extra ? 'open' : ''}><summary>${tr('Advanced · rule text (RRULE)')}</summary><input id="p-rrule" value="${esc(cur)}" spellcheck="false" autocapitalize="off" aria-label="RRULE" placeholder="FREQ=WEEKLY;INTERVAL=3;BYDAY=MO,TH"></details></div>` : ''}
      ${st.repeat ? `<div class="prow" style="padding-left:1.375rem"><span class="muted" style="font-size:var(--fs-s)">${tr('Ends')}</span><select id="p-end" style="max-width:8.125rem" aria-label="${esc(tr('Ends'))}"><option value="never" ${end.type === 'never' ? 'selected' : ''}>${tr('never')}</option><option value="count" ${end.type === 'count' ? 'selected' : ''}>${tr('after count')}</option><option value="until" ${end.type === 'until' ? 'selected' : ''}>${tr('on date')}</option></select>${end.type === 'count' ? `<input type="number" id="p-endn" min="1" max="999" value="${esc(end.val)}" style="max-width:4.625rem"><span class="muted" style="font-size:var(--fs-s)">${trn('time', 'times', end.val)}</span>` : end.type === 'until' ? dateIn('p-endd', end.val, {label: tr('on date'), clear: false, min: st.due || ''}) : ''}</div>` : ''}
      ${st.repeat ? `<div class="prow" style="padding-left:1.375rem"><label style="display:flex;gap:.5rem;align-items:center;font-size:var(--fs-m)"><input type="checkbox" id="p-from" ${st.repeat_from === 'done' ? 'checked' : ''} style="flex:none"> ${tr('repeat from completion date')}</label></div>` : ''}
      ${instant ? `<div class="popfoot pinst"><span class="psaved ${I.saved ? 'on' : ''}" role="status" aria-live="polite">${I.saved ? `${ic('check', 's')}<span>${tr('Saved')}</span>` : esc(tr('Changes apply at once'))}</span><button class="btn" data-q="revert" ${I.saved ? '' : 'hidden'}>${tr('Undo')}</button><button class="btn pri" data-q="done">${tr('Done')}</button></div>`
    : `<div class="popfoot"><button class="btn" data-q="cancel">${tr('Cancel')}</button><button class="btn pri" data-q="ok">${tr('OK')}</button></div>`}`;
  };
  const p = openPop(anchor, draw(), instant ? () => { finish(); } : null);
  const redraw = () => { p.innerHTML = draw(); };
  p.onclick = async e => {
    await dateClick(e);
    changed();
  };
  const dateClick = async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.d) { st.due = b.dataset.d; redraw(); }
    if (b.dataset.mm) { const [y, m] = st.month.split('-').map(Number); st.month = ds(new Date(y, m - 1 + +b.dataset.mm, 1)).slice(0, 7); redraw(); }
    if (b.dataset.rem !== undefined) { const s = new Set((st.reminders || '').split(',').filter(Boolean)); s.has(b.dataset.rem) ? s.delete(b.dataset.rem) : s.add(b.dataset.rem); st.reminders = [...s].join(','); if (!st.due) st.due = today(); redraw(); }
    if (b.dataset.q === 'remc') { st.remc = !st.remc; redraw(); if (st.remc) $('#p-remn')?.focus(); return; }
    if (b.dataset.q === 'remadd') {  // 2.7.0 (#412): an own reminder, e.g. 3 weeks before
      const n = Math.round(+$('#p-remn')?.value || 0), u = +($('#p-remu')?.value || 1440), m = n * u;
      if (!(n >= 1) || m > REM_MAX) { toast(tr('A reminder can be at most a year before the date')); return; }
      const s = new Set((st.reminders || '').split(',').filter(Boolean));
      if (s.size >= 10) { toast(tr('At most {0} reminders', 10)); return; }
      s.add(String(m)); st.reminders = [...s].join(','); st.remc = false; st.remn = n; st.remu = String(u); if (!st.due) st.due = today(); redraw(); return;
    }
    const q = b.dataset.q;
    if (q === '0' || q === '1') { st.due = addDays(today(), +q); st.month = st.due.slice(0, 7); redraw(); }
    if (q === 'w') { st.due = nextWeekday(1); st.month = st.due.slice(0, 7); redraw(); }
    // 2.13.3: "No date" removes the date with its time, start, reminders, repeat and repeat reminder in one step and closes
    // the popover (undo in the toast)
    if (q === 'x') {
      st.due = null; st.due_time = null; st.reminders = ''; st.repeat = ''; st.start = null; st.nag = ''; st.deadline = 0;
      closePop(); if (!instant) await patchUndoable(id, body(), msgOf());
      return;
    }
    if (q === 'nostart') { st.start = null; redraw(); }
    if (q === 'notime') { st.due_time = null; redraw(); }
    if (q === 'cust') { st.cust = true; redraw(); }
    if (b.dataset.rwd) {  // custom weekly repeat: weekday toggles
      const cu = rrForm(rrBase(st.repeat)); cu.days.has(b.dataset.rwd) ? cu.days.delete(b.dataset.rwd) : cu.days.add(b.dataset.rwd);
      if (!cu.days.size) cu.days.add(b.dataset.rwd);
      st.repeat = rrSetEnd(rrBuild(cu), rrEnd(st.repeat)); redraw(); $(`#pop [data-rwd="${b.dataset.rwd}"]`)?.focus();
    }
    if (q === 'cancel') closePop();
    if (q === 'done') closePop();  // instant: popOnClose -> finish()
    if (q === 'revert') { popOnClose = null; closePop(); await revert(); }
    if (q === 'ok') {
      closePop();
      await patchUndoable(id, body(), msgOf());
    }
  };
  p.onchange = e => {
    dateChange(e);
    changed();
  };
  const dateChange = e => {
    if (e.target.id === 'p-remn' || e.target.id === 'p-remu') { st.remn = +$('#p-remn').value || 1; st.remu = $('#p-remu').value; return; }
    if (e.target.id === 'p-dl') { st.deadline = e.target.checked ? 1 : 0; redraw(); }
    if (e.target.id === 'p-dlt') { st.deadline = e.target.checked ? 2 : 1; redraw(); }
    if (e.target.id === 'p-nag') { st.nag = e.target.value; redraw(); }
    if (e.target.id === 'p-time') {
      st.due_time = e.target.value || null; if (!st.due) st.due = today();
      if (st.due_time && !st.reminders && S.settings.default_reminder !== '') st.reminders = S.settings.default_reminder;
      redraw();
    }
    if (e.target.id === 'p-rep') {
      let v = e.target.value;
      if (v === '__custom') { st.cust = true; v = rrBase(st.repeat) || `FREQ=WEEKLY;BYDAY=${st.due ? RR_WD[pd(st.due).getDay()] : 'MO'}`; } else st.cust = false;
      st.repeat = !v ? '' : /COUNT=|UNTIL=/.test(v) ? v : rrSetEnd(v, rrEnd(st.repeat)); if (v && !st.due) st.due = today(); redraw();
    }
    if (e.target.id === 'p-end') {
      const ty = e.target.value;
      st.repeat = rrSetEnd(st.repeat, ty === 'count' ? {type: 'count', val: 5} : ty === 'until' ? {type: 'until', val: addDays(st.due || today(), 30)} : {type: 'never'});
      redraw();
    }
    if (e.target.id === 'p-rn' || e.target.id === 'p-rf') {
      const cu = rrForm(rrBase(st.repeat)); cu.n = Math.max(1, Math.min(99, +$('#p-rn').value || 1)); cu.f = $('#p-rf').value;
      if (cu.f === 'WEEKLY' && !cu.days.size) cu.days.add(st.due ? RR_WD[pd(st.due).getDay()] : 'MO');
      st.repeat = rrSetEnd(rrBuild(cu), rrEnd(st.repeat)); redraw();
    }
    if (e.target.id === 'p-rrule') {
      const v = e.target.value.trim().replace(/^RRULE:/i, '').toUpperCase();
      if (v && !/^FREQ=(DAILY|WEEKLY|MONTHLY|YEARLY)(;[A-Z]+=[A-Z0-9,+-]+)*$/.test(v)) { toast(tr('Not a valid rule, e.g. FREQ=WEEKLY;INTERVAL=3;BYDAY=MO,TH')); return; }
      st.repeat = !v ? '' : /COUNT=|UNTIL=/.test(v) ? v : rrSetEnd(v, rrEnd(st.repeat)); redraw();
    }
    if (e.target.id === 'p-endn') st.repeat = rrSetEnd(st.repeat, {type: 'count', val: +e.target.value});
    if (e.target.id === 'p-endd') st.repeat = rrSetEnd(st.repeat, {type: 'until', val: e.target.value});
    if (e.target.id === 'p-from') st.repeat_from = e.target.checked ? 'done' : 'due';
    if (e.target.id === 'p-dur') st.duration = +e.target.value;
    if (e.target.id === 'p-start') { st.start = e.target.value || null; if (st.start && !st.due) st.due = st.start; redraw(); }
  };
}
// ---- UX1 (U23, owner decision 8): own date and time pickers in the app language and design (the browser's fields
// follow the browser language: "09:00 AM", "mm/dd/yyyy" in a German interface). The value lives in a hidden input with
// the old id (YYYY-MM-DD / HH:MM as before, so every reader stays the same); a button shows it in the app language and
// opens a small popover: a month grid (arrow keys, PageUp/PageDown, Home/End, Enter, Esc; the week starts on the
// locale's first day) or hours and minutes plus a text field ("930", "9:30 pm", "21 Uhr"). A pick fires input + change.
const DP_SUNDAY = new Set(['AG', 'AS', 'BD', 'BR', 'BS', 'BT', 'BW', 'BZ', 'CA', 'CN', 'CO', 'DM', 'DO', 'ET', 'GT', 'GU', 'HK', 'HN', 'ID', 'IL', 'IN', 'JM', 'JP', 'KE', 'KH', 'KR', 'LA', 'MH', 'MM', 'MO', 'MT', 'MX', 'MZ', 'NI', 'NP', 'PA', 'PE', 'PH', 'PK', 'PR', 'PT', 'PY', 'SA', 'SG', 'SV', 'TH', 'TT', 'TW', 'UM', 'US', 'VE', 'VI', 'WS', 'YE', 'ZA', 'ZW']);
// the app language, with the browser's region when it is the same language (en + en-US browser -> en-US)
function dpLocale() {
  const app = LOCALE(), nav = (typeof navigator !== 'undefined' && navigator.language) || '';
  return nav.includes('-') && nav.split('-')[0].toLowerCase() === app.split('-')[0].toLowerCase() ? nav : app;
}
function weekStart() {  // 0 = Sunday, 1 = Monday, 6 = Saturday
  try {
    const L = new Intl.Locale(dpLocale()), wi = typeof L.getWeekInfo === 'function' ? L.getWeekInfo() : L.weekInfo;
    if (wi && wi.firstDay) return wi.firstDay % 7;
    return DP_SUNDAY.has(L.maximize().region) ? 0 : 1;
  } catch { return 1; }
}
const hour12 = () => { try { return /h1[12]/.test(new Intl.DateTimeFormat(dpLocale(), {hour: 'numeric'}).resolvedOptions().hourCycle || ''); } catch { return false; } };
const fmtTimeLoc = hm => { if (!/^\d\d:\d\d$/.test(hm || '')) return ''; const [h, m] = hm.split(':').map(Number); try { return new Date(2000, 0, 1, h, m).toLocaleTimeString(dpLocale(), {hour: hour12() ? 'numeric' : '2-digit', minute: '2-digit'}); } catch { return hm; } };
const fmtDateLoc = s => !/^\d{4}-\d\d-\d\d$/.test(s || '') ? '' : fmtDay(pd(s).getFullYear() !== new Date().getFullYear() ? 'year' : 'short', pd(s));
const wdOrder = () => { const f = weekStart(); return [0, 1, 2, 3, 4, 5, 6].map(i => (i + f) % 7); };
const weekStartOf = s => { const d = pd(s), k = (d.getDay() - weekStart() + 7) % 7; d.setDate(d.getDate() - k); return ds(d); };
// a time typed by hand: "9", "930", "09:30", "9.30", "9:30 pm", "21 uhr" -> "HH:MM" or null
function parseHM(v) {
  let s = String(v || '').trim().toLowerCase().replace(/\s*(uhr|h)$/, '');
  if (!s) return '';
  const pm = /p\.?m\.?$/.test(s), am = /a\.?m\.?$/.test(s);
  s = s.replace(/\s*[ap]\.?m\.?$/, '');
  let m = s.match(/^(\d{1,2})(?:[:.h ](\d{1,2}))?$/) || s.match(/^(\d{1,2})(\d{2})$/);
  if (!m) return null;
  let h = +m[1], mi = m[2] === undefined ? 0 : +m[2];
  if (pm && h < 12) h += 12;
  if (am && h === 12) h = 0;
  return h > 23 || mi > 59 ? null : `${pad(h)}:${pad(mi)}`;
}
function dpInner(kind, v, o) {
  const txt = kind === 'date' ? fmtDateLoc(v) : fmtTimeLoc(v);
  return `${ic(kind === 'date' ? 'cal' : 'clock', 's')}<span class="dpv ${txt ? '' : 'muted'}">${esc(txt || o.empty || (kind === 'date' ? tr('No date|clear') : tr('No time')))}</span>`;
}
function dpField(kind, id, v, o = {}) {
  v = v || '';
  const lab = o.label || '';
  return `<span class="dpw" id="${id}-w" ${o.hidden ? 'hidden' : ''}><input type="hidden" id="${id}" value="${esc(v)}" data-dp="${kind}" ${o.min ? `data-min="${esc(o.min)}"` : ''} ${o.max ? `data-max="${esc(o.max)}"` : ''} ${o.clear === false ? 'data-noclear="1"' : ''} data-label="${esc(lab)}" data-empty="${esc(o.empty || '')}" ${o.ro ? 'disabled' : ''} ${o.attrs || ''}><button type="button" class="dpbtn" data-dpfor="${id}" aria-haspopup="dialog" aria-expanded="false" aria-label="${esc(lab ? `${lab}: ${(kind === 'date' ? fmtDateLoc(v) : fmtTimeLoc(v)) || o.empty || tr('none')}` : '')}" ${o.ro ? 'disabled' : ''}>${dpInner(kind, v, o)}</button></span>`;
}
const dateIn = (id, v, o) => dpField('date', id, v, o);
const timeIn = (id, v, o) => dpField('time', id, v, o);
function dpSync(inp) {  // the button shows the hidden input's value
  const b = inp && $$('[data-dpfor]').find(x => x.dataset.dpfor === inp.id); if (!b) return;
  const kind = inp.dataset.dp, o = {empty: inp.dataset.empty}, v = inp.value;
  b.innerHTML = dpInner(kind, v, o);
  const lab = inp.dataset.label; if (lab) b.setAttribute('aria-label', `${lab}: ${(kind === 'date' ? fmtDateLoc(v) : fmtTimeLoc(v)) || o.empty || tr('none')}`);
}
function dpSet(inp, v) {
  inp.value = v || '';
  dpSync(inp);
  inp.dispatchEvent(new Event('input', {bubbles: true}));
  inp.dispatchEvent(new Event('change', {bubbles: true}));
}
const DP = {el: null, anchor: null, st: null};
function dpClose(focusBack = true) {
  if (!DP.el) return;
  const a = DP.anchor; DP.el.remove(); DP.el = null; DP.st = null; DP.anchor = null;
  if (a) { a.setAttribute?.('aria-expanded', 'false'); if (focusBack && a.isConnected) a.focus?.({preventScroll: true}); }
}
// open a picker: from a field button, or directly (dpOpen(anchor, {kind, value, min, max, label, onPick}))
function dpOpen(anchor, o) {
  dpClose(false);
  const el = document.createElement('div');
  el.id = 'dpop'; el.className = 'dpop ' + o.kind; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', o.label || (o.kind === 'date' ? tr('Choose a date') : tr('Choose a time')));
  document.body.appendChild(el);
  DP.el = el; DP.anchor = anchor; anchor?.setAttribute?.('aria-expanded', 'true');
  const v = o.value || '';
  DP.st = {...o, cur: o.kind === 'date' ? (v || (o.min && o.min > today() ? o.min : today())) : v, sel: v};
  o.kind === 'date' ? dpDrawDate() : dpDrawTime();
  dpPlace();
  el.addEventListener('keydown', dpKey);
  el.addEventListener('click', dpClick);
  el.addEventListener('change', e => {
    if (!e.target.classList.contains('dpy') || !DP.st) return;
    let c = `${e.target.value}-${DP.st.cur.slice(5, 7)}-01`;
    if (DP.st.min && c < DP.st.min.slice(0, 7) + '-01') c = DP.st.min; if (DP.st.max && c > DP.st.max) c = DP.st.max.slice(0, 7) + '-01';
    DP.st.cur = c; dpDrawDate(); $('.dpy', DP.el)?.focus();
  });
  el.addEventListener('input', e => { if (e.target.id === 'dp-tin') e.target.classList.toggle('bad', parseHM(e.target.value) === null); });
  setTimeout(() => (o.kind === 'date' ? $('.dpg [tabindex="0"]', el) : $('#dp-tin', el))?.focus(), 20);
  return el;
}
function dpPlace() {
  const el = DP.el; if (!el) return;
  if (matchMedia('(max-width:899px)').matches) { el.classList.add('sheet'); return; }
  const r = DP.anchor?.getBoundingClientRect?.() || {left: innerWidth / 2 - 150, bottom: innerHeight / 3, top: innerHeight / 3};
  const w = el.offsetWidth || 300, h = el.offsetHeight || 330;
  let x = Math.min(r.left, innerWidth - w - 12), y = r.bottom + 6;
  if (y + h > innerHeight - 12) y = Math.max(12, r.top - h - 6);
  el.style.left = Math.max(12, x) + 'px'; el.style.top = y + 'px';
}
function dpDrawDate() {
  const st = DP.st, el = DP.el, [y, m] = st.cur.split('-').map(Number), first = `${st.cur.slice(0, 7)}-01`;
  const start = weekStartOf(first), order = wdOrder(), t0 = today();
  const ok = d => (!st.min || d >= st.min) && (!st.max || d <= st.max);
  let rows = '';
  for (let w = 0; w < 6; w++) {
    let cells = '';
    for (let i = 0; i < 7; i++) {
      const d = addDays(start, w * 7 + i), x = pd(d), out = x.getMonth() !== m - 1;
      cells += `<button type="button" role="gridcell" class="dpd ${out ? 'out' : ''} ${d === t0 ? 'today' : ''} ${d === st.sel ? 'sel' : ''}" data-d="${d}" tabindex="${d === st.cur ? 0 : -1}" aria-selected="${d === st.sel}" ${ok(d) ? '' : 'disabled aria-disabled="true"'} aria-label="${esc(fmtDay('year', x))}${d === t0 ? ' · ' + esc(tr('Today')) : ''}">${x.getDate()}</button>`;
    }
    rows += `<div role="row" class="dpr">${cells}</div>`;
    if (w >= 3 && pd(addDays(start, w * 7 + 7)).getMonth() !== m - 1) break;
  }
  el.innerHTML = `<div class="dph"><button type="button" class="iconbtn" data-dm="-1" aria-label="${tr('Previous month')}">${ic('left')}</button><span class="dpt"><span id="dp-t" aria-live="polite">${MON[m - 1]}<span class="sr"> ${y}</span></span> <select class="dpy" data-native aria-label="${esc(tr('Year'))}">${dpYears(y).map(n => `<option value="${n}" ${n === y ? 'selected' : ''}>${n}</option>`).join('')}</select></span><button type="button" class="iconbtn" data-dm="1" aria-label="${tr('Next month')}">${ic('right')}</button></div>
    <div class="dpg" role="grid" aria-labelledby="dp-t"><div role="row" class="dpr dpwd">${order.map(i => `<span role="columnheader" aria-label="${esc(WDL[i])}">${esc(WD[i])}</span>`).join('')}</div>${rows}</div>
    <div class="dpf"><button type="button" class="btn sm" data-dq="today" ${ok(t0) ? '' : 'disabled'}>${tr('Today')}</button>${st.clear === false ? '' : `<button type="button" class="btn sm" data-dq="clear">${tr('No date|clear')}</button>`}<span class="spacer"></span><button type="button" class="btn sm" data-dq="close">${tr('Cancel')}</button></div>`;
}
// 2.19.0: the year is a select in the title (a passport that runs out in 10 years: one choice, not 120 taps)
function dpYears(y) {
  const st = DP.st, t = new Date().getFullYear(), lo = Math.max(st.min ? +st.min.slice(0, 4) : 1900, Math.min(y, t) - 10), hi = Math.min(st.max ? +st.max.slice(0, 4) : 2200, Math.max(y, t) + 12);
  return [...Array(Math.max(0, hi - lo + 1))].map((_, i) => lo + i);
}
function dpDrawTime() {
  const st = DP.st, el = DP.el, cur = st.sel || '', [ch, cm] = cur ? cur.split(':').map(Number) : [-1, -1], h12 = hour12();
  const hl = h => { try { return new Date(2000, 0, 1, h).toLocaleTimeString(dpLocale(), {hour: h12 ? 'numeric' : '2-digit'}); } catch { return pad(h); } };
  const hb = h => `<button type="button" role="option" class="${h === ch ? 'sel' : ''}" data-th="${h}" aria-selected="${h === ch}" aria-label="${esc(hl(h))}" tabindex="${h === (ch < 0 ? 9 : ch) ? 0 : -1}">${h12 ? (h % 12 || 12) : pad(h)}</button>`;
  const ap = h => { try { return new Date(2000, 0, 1, h).toLocaleTimeString(dpLocale(), {hour: 'numeric', hour12: true}).replace(/[\d\s\u202f]/g, '') || (h < 12 ? 'AM' : 'PM'); } catch { return h < 12 ? 'AM' : 'PM'; } };
  el.innerHTML = `<div class="tpk"><label class="tpl" for="dp-tin">${tr('Time')}</label><input id="dp-tin" class="tpin" value="${esc(fmtTimeLoc(cur) || '')}" inputmode="text" autocomplete="off" enterkeyhint="done" placeholder="${esc(fmtTimeLoc('09:30'))}" aria-describedby="dp-thint"></div>
    <div class="muted tphint" id="dp-thint">${tr('Type it or pick hour and minutes')}</div>
    <div class="tpcols"><div class="tph ${h12 ? 'h12' : ''}" role="listbox" aria-label="${tr('Hour')}">${h12 ? `<span class="tpap">${esc(ap(0))}</span>${[...Array(12)].map((_, h) => hb(h)).join('')}<span class="tpap">${esc(ap(12))}</span>${[...Array(12)].map((_, h) => hb(h + 12)).join('')}` : [...Array(24)].map((_, h) => hb(h)).join('')}</div>
      <div class="tpm" role="listbox" aria-label="${tr('Minutes')}">${[...Array(12)].map((_, i) => i * 5).map(mi => `<button type="button" role="option" class="${mi === cm ? 'sel' : ''}" data-tm="${mi}" aria-selected="${mi === cm}" tabindex="${mi === (cm < 0 || cm % 5 ? 0 : cm) ? 0 : -1}">:${pad(mi)}</button>`).join('')}</div></div>
    <div class="dpf">${st.clear === false ? '' : `<button type="button" class="btn sm" data-tq="clear">${esc(st.empty || tr('No time'))}</button>`}<span class="spacer"></span><button type="button" class="btn sm" data-dq="close">${tr('Cancel')}</button><button type="button" class="btn sm pri" data-tq="ok">${tr('OK')}</button></div>`;
}
function dpPick(v) {
  const st = DP.st; if (!st) return;
  dpClose(true);
  st.onPick?.(v);
}
function dpClick(e) {
  const st = DP.st; if (!st) return;
  const b = e.target.closest('button'); if (!b || b.disabled) return;
  e.stopPropagation();
  if (b.dataset.dm) { const [y, m] = st.cur.split('-').map(Number); st.cur = ds(new Date(y, m - 1 + +b.dataset.dm, 1)); dpDrawDate(); $(`.dph [data-dm="${b.dataset.dm}"]`, DP.el)?.focus(); return; }
  if (b.dataset.d) { dpPick(b.dataset.d); return; }
  const q = b.dataset.dq || b.dataset.tq;
  if (q === 'close') { dpClose(true); return; }
  if (q === 'today') { dpPick(today()); return; }
  if (q === 'clear') { dpPick(''); return; }
  if (b.dataset.th !== undefined || b.dataset.tm !== undefined) {
    const cur = parseHM($('#dp-tin', DP.el).value) || st.sel || '09:00';
    let [h, m] = cur.split(':').map(Number);
    if (b.dataset.th !== undefined) h = +b.dataset.th; else m = +b.dataset.tm;
    st.sel = `${pad(h)}:${pad(m)}`;
    if (b.dataset.tm !== undefined) { dpPick(st.sel); return; }
    dpDrawTime(); $(`[data-th="${h}"]`, DP.el)?.focus(); return;
  }
  if (q === 'ok') { const v = parseHM($('#dp-tin', DP.el).value); if (v === null) { $('#dp-tin', DP.el).classList.add('bad'); $('#dp-tin', DP.el).focus(); return; } dpPick(v || st.sel || ''); }
}
function dpKey(e) {
  const st = DP.st; if (!st) return;
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); dpClose(true); return; }
  if (e.key === 'Tab') {  // stay inside the popover
    const f = $$('button:not([disabled]),input,select', DP.el).filter(x => x.tabIndex >= 0); if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    return;
  }
  const a = document.activeElement;
  if (st.kind === 'time') {
    if (a && a.id === 'dp-tin' && e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); const v = parseHM(a.value); if (v === null) { a.classList.add('bad'); return; } dpPick(v); return; }
    const grid = a?.closest?.('.tph, .tpm'); if (!grid) return;
    const bs = $$('button', grid), i = bs.indexOf(a), cols = grid.classList.contains('tph') ? 6 : 4;
    const mv = {ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols}[e.key];
    if (mv !== undefined) { e.preventDefault(); e.stopPropagation(); const n = bs[Math.max(0, Math.min(bs.length - 1, i + mv))]; bs.forEach(x => { x.tabIndex = -1; }); n.tabIndex = 0; n.focus(); }
    return;
  }
  if (!a?.dataset?.d) return;
  let d = a.dataset.d;
  const k = e.key;
  if (k === 'Enter' || k === ' ') { e.preventDefault(); e.stopPropagation(); if (!a.disabled) dpPick(d); return; }
  const idx = (pd(d).getDay() - weekStart() + 7) % 7;
  const mvd = {ArrowRight: 1, ArrowLeft: -1, ArrowDown: 7, ArrowUp: -7, Home: -idx, End: 6 - idx}[k];
  if (mvd !== undefined) d = addDays(d, mvd);
  else if (k === 'PageUp' || k === 'PageDown') { const x = pd(d); x.setMonth(x.getMonth() + (k === 'PageUp' ? -1 : 1) * (e.shiftKey ? 12 : 1)); d = ds(x); }
  else return;
  e.preventDefault(); e.stopPropagation();
  st.cur = d; dpDrawDate(); $(`.dpg [data-d="${d}"]`, DP.el)?.focus();
}
document.addEventListener('click', e => {  // a field button opens its picker
  const b = e.target.closest?.('[data-dpfor]'); if (!b || b.disabled) return;
  e.preventDefault(); e.stopPropagation();
  if (DP.el && DP.anchor === b) { dpClose(true); return; }
  const inp = document.getElementById(b.dataset.dpfor); if (!inp) return;
  dpOpen(b, {kind: inp.dataset.dp, value: inp.value, min: inp.dataset.min, max: inp.dataset.max, clear: !inp.dataset.noclear, label: inp.dataset.label, empty: inp.dataset.empty,
    onPick: v => { if (inp.isConnected) dpSet(inp, v); }});
}, true);
document.addEventListener('pointerdown', e => { if (DP.el && !DP.el.contains(e.target) && !(DP.anchor && DP.anchor.contains?.(e.target))) dpClose(false); }, true);
window.addEventListener('resize', () => { if (DP.el) dpPlace(); });
// 1.5.1: one tap "Today" / "Tomorrow" (task menu, detail panel, keys t / Shift+T, selection bar): only the day changes;
// time, reminders and repeat stay (a recurring task just moves, like in the date popover); one undo step
async function quickDue(id, days) {
  const t = taskById(id); if (!t) return;
  if (!canEdit(t)) { roToast(); return; }
  const d = addDays(today(), days);
  if (t.due === d) { toast(tr('Already due {0}', dayLabel(d))); return; }
  await patchUndoable(id, {due: d, ...(t.start && t.start >= d ? {start: null} : {})}, tr('Date: {0}', dayLabel(d)));
  if (S.sel === id) renderDetail();
}
const quickDueRow = id => { const t = taskById(id), d0 = today(), d1 = addDays(d0, 1);
  return {row: [{label: tr('Today'), icon: 'sun', title: isMobile() ? '' : `${tr('Due today')} (${keyName('t')})`, on: t?.due === d0, fn: () => quickDue(id, 0)},
    {label: tr('Tomorrow'), icon: 'sunrise', title: isMobile() ? '' : `${tr('Due tomorrow')} (${kbText('Shift+T')})`, on: t?.due === d1, fn: () => quickDue(id, 1)}]}; };
// ---- 2.1.0 (#335): "Waiting on external": who / what + a follow-up day (reminder + News on that day, agents get
// followup_due). A chip on the row and a bar in the task panel; clearing it is one click.
function waitLabel(t) {
  return [t.wait_note, t.wait_until ? tr('follow up {0}', dayLabel(t.wait_until)) : ''].filter(Boolean).join(' · ');
}
function waitChip(t) {
  const due = t.wait_until && t.wait_until <= today();
  return `<span class="waitm ${due ? 'due' : ''}" title="${esc(tr('Waiting on someone') + (waitLabel(t) ? ': ' + waitLabel(t) : ''))}">${ic('hourglass', 's')}${esc(t.wait_until ? dayLabel(t.wait_until) : tr('waiting|external'))}</span>`;
}
function waitBar(t, ro) {
  const due = t.wait_until && t.wait_until <= today();
  return `<div class="waitbar ${due ? 'due' : ''}">${ic('hourglass', 's')}<button type="button" class="wtxt" data-act="wait-edit" data-id="${t.id}" ${ro ? 'disabled' : ''}><b>${tr('Waiting on someone')}</b>${waitLabel(t) ? `<span>${esc(waitLabel(t))}</span>` : ''}</button>${ro ? '' : `<button type="button" class="iconbtn" data-act="wait-clear" data-id="${t.id}" title="${esc(tr('No longer waiting'))}" aria-label="${esc(tr('No longer waiting'))}">${ic('x', 's')}</button>`}</div>`;
}
function waitDialog(id) {
  const t = taskById(id); if (!t) return;
  if (!canEdit(t)) { roToast(); return; }
  const md = modal(`<h3>${tr('Waiting on someone')}</h3>
    <div class="shint">${tr('The task waits for someone outside (a client, an office, a delivery). On the follow-up day you get a reminder and a News item; agents that follow the task are told too.')}</div>
    <div class="row"><label for="w-note">${tr('Waiting on')}</label><input id="w-note" maxlength="300" value="${esc(t.wait_note || '')}" placeholder="${esc(tr('who or what, e.g. offer from the carpenter'))}" enterkeyhint="done"></div>
    <div class="row"><label for="w-until">${tr('Follow up on')}</label>${dateIn('w-until', t.wait_until || addDays(today(), 7), {min: today(), label: tr('Follow up on'), empty: tr('none')})}</div>
    <div class="foot">${t.waiting_at ? `<button class="btn" data-m="clear">${ic('x', 's')} ${tr('No longer waiting')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Save')}</button></div>`);
  md.classList.add('waitmodal');
  const save = async () => {
    const body = {note: $('#w-note', md).value.trim(), until: $('#w-until', md).value || null};
    try { putTask(await api('PUT', `/api/tasks/${id}/waiting`, body)); } catch { return; }
    md.remove(); render(); if (S.sel === id) renderDetail(); toast(tr('Waiting on someone'));
  };
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') md.remove();
    else if (b.dataset.m === 'ok') save();
    else if (b.dataset.m === 'clear') { md.remove(); waitClear(id); }
  });
  $('#w-note', md).addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
  if (!isMobile()) setTimeout(() => $('#w-note', md).focus(), 50);
}
async function waitClear(id) {
  const t = taskById(id); if (!t || !t.waiting_at) return;
  const before = {note: t.wait_note || '', until: t.wait_until || null};
  try { putTask(await api('DELETE', `/api/tasks/${id}/waiting`)); } catch { return; }
  render(); if (S.sel === id) renderDetail();
  toast(tr('No longer waiting'), async () => { putTask(await api('PUT', `/api/tasks/${id}/waiting`, before)); render(); if (S.sel === id) renderDetail(); });
}
// 2.24.0 (UX-09): ONE task menu in a fixed order (right-click, "…" in the row / the task panel, "All…" of the short
// menus): date · priority · assignee · list / section · waiting · pin · time · template · structure · delete. The short
// menus (swipe, selection) keep the same order and end with "All…".
const PRIO_ROW = id => { const t = taskById(id); return {row: [[5, N_('High')], [3, N_('Medium')], [1, N_('Low')], [0, N_('None')]].map(([p, n]) => ({label: tr(n), icon: 'flag', cls: p ? 'flag-' + p : '', on: t?.priority === p, title: tr('Priority') + ': ' + tr(n), fn: () => patchTask(id, {priority: p})}))}; };
const moveListItem = (anchor, id) => ({label: tr('Move to list…'), icon: 'list', keys: 'm', fn: () => { const t = taskById(id); menu(anchor, S.lists.filter(l => !l.archived && l.id !== t?.list_id && canAddTo(l.id)).map(l => ({label: lname(l), icon: l.is_inbox ? 'inbox' : 'list', fn: () => patchUndoable(id, {list_id: l.id}, tr('Moved to {0}', lname(l)))}))); }});
function taskMenu(anchor, id, o = {}) {
  const t = taskById(id);
  if (!canEdit(t)) { roToast(); return; }
  const sib = siblings(t), i = sib.findIndex(x => x.id === t.id);
  const l = listById(t.list_id), open = t.status === 0;
  menu(anchor, [
    // 2.25.0 (UX-11): opened by a long press: the title on top, then "Select" (more tasks follow with a tap)
    ...(o.select ? [{label: t.title.length > 60 ? t.title.slice(0, 59) + '…' : t.title, cls: 'mhead', dis: true, fn: () => {}}, {label: tr('Select'), icon: 'select', fn: () => { S.multiMode = true; S.multi.add(id); S.multiLast = id; render(); }}, '-'] : []),
    // date
    quickDueRow(id), {label: tr('New date…'), icon: 'clock', keys: 's', fn: () => snoozeSheet(id, anchor)},
    ...(t.repeat && t.due && open ? [{label: tr('Skip this occurrence'), icon: 'skip', fn: async () => {
      const b0 = snapTask(t);
      const j = await api('POST', `/api/tasks/${id}/skip`);
      putTask(j); render(); if (S.sel === id) renderDetail();
      if (j.next_due) histFields(tr('Skipped an occurrence of {0}', qn(t.title.slice(0, 40))), [[b0, snapTask(S.tasks.get(id)), ['due', 'start', 'repeat']]], {res: j});
      toast(j.next_due ? tr('Skipped, next occurrence: {0}', dayLabel(j.next_due)) : tr('Will be sent as soon as the server is reachable'));
    }}] : []), '-',
    // priority, assignee
    PRIO_ROW(id),
    ...(collab() && l?.shared && t.id > 0 && !t.context && canAssign(t) ? [{label: tr('Assign…'), icon: 'user', fn: () => assignMenu(anchor, id)}] : []), '-',
    // where it lives
    ...(open ? [moveListItem(anchor, id)] : []),
    ...(open && !t.parent_id && (S.sections.some(x => x.list_id === t.list_id) || canEditList(t.list_id)) ? [{label: tr('Move to section…'), icon: 'columns', fn: () => sectionPicker(anchor, id)}] : []),
    // 2.16.0 (#473, WCAG 2.5.7): what dragging does, as menu items (also Alt+↑ / ↓)
    ...(open && t.id > 0 && S.route.mod === 'tasks' && $(`#view .trow[data-id="${id}"]`) ? [{row: [{label: tr('Move up'), icon: 'up', title: kt(tr('Move up'), 'Alt+ArrowUp'), fn: () => taskNudge(id, -1)}, {label: tr('Move down'), icon: 'down', title: kt(tr('Move down'), 'Alt+ArrowDown'), fn: () => taskNudge(id, 1)}]}] : []), '-',
    // waiting
    ...(open ? [t.waiting_at ? {label: tr('No longer waiting'), icon: 'hourglass', fn: () => waitClear(id)}
      : {label: tr('Waiting on someone…'), icon: 'hourglass', fn: () => waitDialog(id)}] : []),
    // 2.23.0 (#463): an approval (a person of the shared list decides)
    ...(open && t.id > 0 && collab() && l?.shared && t.approval !== 'pending' ? [{label: tr('Ask for approval…'), icon: 'eye', fn: () => approvalRequest(id)}] : []),
    // pin
    {label: t.pinned ? tr('Unpin') : tr('Pin'), icon: 'pin', fn: () => patchTask(id, {pinned: t.pinned ? 0 : 1})}, '-',
    // time
    ...(feat('pomo') ? [{label: tr('Start focus session'), icon: 'timer', fn: () => { pomoStart(id); go('pomo'); }}] : []),
    ...(tFor(t) ? [S.timer && S.timer.task_id === id ? {label: tr('Stop timer'), icon: 'stop', fn: timerStop} : {label: tr('Start time tracking'), icon: 'clock', fn: () => timerStart({task_id: id})},
      {label: tr('Add time…'), icon: 'plus', fn: () => entryModal(null, {task_id: id})}] : []), '-',
    // template
    {label: tr('Save as template'), icon: 'copy', fn: () => saveTemplate({task_id: id}, t.title)},
    {label: tr('Duplicate'), icon: 'sub', fn: () => createTask({title: t.title, content: t.content, list_id: t.list_id, section_id: t.section_id, priority: t.priority, due: t.due, due_time: t.due_time, reminders: t.reminders, repeat: t.repeat, repeat_from: t.repeat_from, tags: t.tags, parent_id: t.parent_id, url: t.url || null, ...(t.ms ? {ms: 1} : {}), ...(t.milestone_id ? {milestone_id: t.milestone_id} : {}), ...(t.fields && Object.keys(t.fields).length ? {fields: t.fields} : {})})}, '-',
    // structure + more
    ...(isMs(t) || (!t.parent_id && !children(t.id).length && t.id > 0) ? [{label: isMs(t) ? tr('Make it a normal task') : tr('Make it a milestone'), icon: 'flag', fn: () => msToggle(id)}] : []),  // 2.18.0 (#430)
    ...(i > 0 && depthOf(sib[i - 1]) < 2 && !isMs(t) && !isMs(sib[i - 1]) ? [{label: tr('Indent (under “{0}”)', sib[i - 1].title.slice(0, 24)), icon: 'indent', fn: () => patchTask(id, {parent_id: sib[i - 1].id})}] : []),
    ...(t.parent_id ? [{label: tr('Outdent'), icon: 'outdent', fn: () => patchTask(id, {parent_id: S.tasks.get(t.parent_id)?.parent_id || null})}] : []),
    ...(t.parent_id && S.tasks.get(t.parent_id)?.parent_id ? [{label: tr('Make it a main task'), icon: 'arrow', fn: () => patchTask(id, {parent_id: null})}] : []),
    ...(propBreakOk(t) ? [{label: propWith(N_('Break down with {0}…'), N_('Break down with an agent…')), icon: 'bot', fn: () => propRequest('subtasks', {tid: id})}] : []),  // 2.3.0 (#261)
    ...(t.id > 0 && !t.context && listRepos(t.list_id).length && !codeShown(t) ? [{label: tr('Link code…'), icon: 'git', title: tr('Copies a branch name for this task; commits and pull requests that name #{0} are linked too', t.id), fn: () => gitCopyBranch(t)}] : []),  // 2.4.2 (#387)
    {label: t.status === -1 ? tr('Reopen') : tr("Won't do (discard)"), icon: 'ban', fn: () => t.status === -1 ? toggleTask(id) : wontDo(id)},
    '-',
    ...(canDelete(t) ? [{label: tr('Delete'), icon: 'trash', cls: 'flag-5', fn: () => deleteTask(id)}] : []),
  ].reduce((o, x) => x === '-' && (!o.length || o[o.length - 1] === '-') ? o : [...o, x], []).filter((x, k, a) => x !== '-' || k < a.length - 1));
}
const propBreakOk = t => propOn() && t && t.id > 0 && t.status === 0 && depthOf(t) < 2 && canEditList(t.list_id);
function siblings(t) {  // same parent (or same list at top level), in custom order
  return [...S.tasks.values()].filter(x => x.status === 0 && x.parent_id === t.parent_id && (t.parent_id || x.list_id === t.list_id)).sort(bySort);
}
function snoozeSheet(id, anchor, extra = [], head = false, pre = []) {
  const t = taskById(id); if (!t) return;
  if (!canEdit(t)) { roToast(); return; }
  const now = new Date();
  const inH = h => { const d = new Date(now.getTime() + h * 36e5); d.setMinutes(Math.ceil(d.getMinutes() / 5) * 5, 0, 0); return {due: ds(d), due_time: `${pad(d.getHours())}:${pad(d.getMinutes())}`}; };
  const go2 = (body, label) => patchUndoable(id, body, tr('Snoozed: {0}', label));
  menu(anchor || $('#top h1'), [
    ...(head ? [{label: t.title.length > 60 ? t.title.slice(0, 59) + '…' : t.title, dis: true, cls: 'mhead'}, '-'] : []),  // 2.24.0 (UX-14)
    ...pre,  // 2.25.0 (UX-37): in the inbox "Move to list…" comes first
    {label: tr('In 1 hour'), icon: 'clock', fn: () => go2(inH(1), tr('in 1 h'))},
    {label: tr('In 3 hours'), icon: 'clock', fn: () => go2(inH(3), tr('in 3 h'))},
    ...(now.getHours() < 18 ? [{label: tr('Tonight (7 pm)'), icon: 'sun', fn: () => go2({due: today(), due_time: '19:00'}, tr('today 7 pm'))}] : []),
    {label: tr('Tomorrow'), icon: 'sunrise', fn: () => go2({due: addDays(today(), 1), due_time: t.due_time}, tr('tomorrow'))},
    {label: tr('Tomorrow 9 am'), icon: 'sunrise', fn: () => go2({due: addDays(today(), 1), due_time: '09:00'}, tr('tomorrow 9 am'))},
    {label: tr('Next week (Mon)'), icon: 'week', fn: () => go2({due: nextWeekday(1), due_time: t.due_time}, dayLabel(nextWeekday(1)))},
    {label: tr('Pick a date…'), icon: 'cal', fn: () => datePop(anchor || $('#top h1'), id)},
    ...extra,
  ]);
}
function sortMenu(anchor) {
  const cur = sortMode();
  const l = routeList(), cfs = l ? fieldsOf(l.id).filter(f => f.type !== 'url') : [];
  // 2.27.0 (#988): owner / list admins set the list's sort for everyone; a member's choice stays on this device (and the view
  // says that it is an own sort)
  const set = async m => {
    if (l && !l.is_inbox && canManage(l)) {
      const k = S.route.key, before = l.sort_mode || '';
      LS.del('sort2.' + k); l.sort_mode = m; render();
      try { await api('PATCH', '/api/lists/' + l.id, {sort_mode: m}); } catch { l.sort_mode = before; render(); }
      return;
    }
    LS.set('sort2.' + S.route.key, m); render();
  };
  // 1.7.0: "Flow" = in the order the dependencies allow (only with the dependencies module)
  // 2.0.8 (#319): "Created" newest first; picking it again while it is on flips to oldest first (and back)
  const crOn = cur === 'created' || cur === 'created_asc';
  menu(anchor, [...[['prio', N_('Priority, then manual')], ['custom', N_('Manual only')], ['date', N_('Date')], ['title', N_('Title')], ['creator', N_('Creator|sort')], ...(depsOn() ? [['flow', N_('Flow|sort')]] : [])].map(([m, n]) => ({label: tr(n), on: cur === m, fn: () => set(m)})),
    {label: !crOn ? tr('Created|sort') : cur === 'created' ? tr('Created: newest first') : tr('Created: oldest first'), on: crOn, cls: 'sortcr', title: crOn ? tr('Click again to reverse the direction') : '', fn: () => set(cur === 'created' ? 'created_asc' : 'created')},
    ...(cfs.length ? ['-', ...cfs.map(f => ({label: tr('Field: {0}', f.name), icon: FT_ICON[f.type], on: cur === 'cf:' + f.id, fn: () => set('cf:' + f.id)}))] : []),
    ...(doneToggleView() ? ['-', doneItem()] : []),
    ...(l && isOwner(l) && listView(l) === 'list' && !isOverview() ? ['-', dabItem(l)] : [])]);
}
// 2.7.2 (#414): the list option "Show completed at the bottom" (owner; for everyone in the list, one undo step)
const dabItem = l => ({label: tr('Show completed at the bottom'), icon: 'cart', on: !!l.checklist, cls: 'dabitem', fn: () => setDab(l.id, !l.checklist)});
async function setDab(id, on) {
  const l = listById(id); if (!l) return;
  const e = await listPatch(id, {checklist: on}, tr('Show completed at the bottom'));
  if (e) offerUndo(on ? tr('Completed tasks stay at the bottom') : tr('Completed tasks are listed as before'), e);
}

// ---- 1.9.0 (Galaxy Fold): dialogs follow the visual viewport. On Android the on-screen keyboard can leave the visual
// viewport scrolled (offsetTop > 0) or the page scrolled after it hides, and a fixed dialog then sat too far down.
// --vvt / --vvh / --vvb (hidden above, visible height, hidden below) keep the dialog in what is visible; after the keyboard
// is gone a leftover page scroll is undone, so every dialog is centred again.
// 2.24.0 (#832, DeX): the keyboard compensation only acts for a REAL on-screen keyboard: a touch screen whose primary
// pointer is not fine (a mouse / trackpad in DeX or a desktop window never counts) and a visible height that shrank by more
// than 120 px (Samsung's autofill bar, ~50 px, does not). Without one the page as a whole never scrolls (only the content
// areas do), so focusing the quick add can no longer slide the whole app up.
function kbReal() {
  const vv = window.visualViewport; if (!vv) return false;
  let fine = false; try { fine = matchMedia('(pointer:fine)').matches; } catch { /* old browser */ }
  return !fine && vv.height < Math.max(S.vvMax || 0, innerHeight) - 120;
}
function vvSync() {
  const vv = window.visualViewport; if (!vv) return;
  const st = document.documentElement.style;
  if (!editFocused() || !(S.vvMax > 0)) S.vvMax = vv.height;  // the height without a keyboard
  const kb = kbReal();
  st.setProperty('--vvt', Math.max(0, Math.round(vv.offsetTop)) + 'px');
  st.setProperty('--vvh', Math.round(vv.height) + 'px');
  st.setProperty('--vvb', kb ? Math.max(0, Math.round(window.innerHeight - vv.offsetTop - vv.height)) + 'px' : '0px');  // hidden below (keyboard)
  if ((vv.height >= window.innerHeight - 2 || !kb) && !kbBlind() && !typingTouch() && (window.scrollY || document.documentElement.scrollTop)) { window.scrollTo(0, 0); vvSoon(); }
  chatFit(); tlKbSync(); vvPin(kb);
  vvDebugUpd();
  // the focused field of a sheet / the docked composer stays above a real keyboard (iOS does not resize the layout)
  const a = document.activeElement;
  // 2.27.0 (#958, again #669): typing must never move what is behind. Each key can fire a viewport event (iOS' suggestion bar,
  // its own caret reveal); a scrollIntoView then scrolled every scrolled ancestor (the list scrolled up, the task panel) and
  // the page. Now: never for the boxes that sit above the keyboard anyway (the add sheet, a pinned box), only when the field
  // really is under the keyboard, and once per focus.
  if (kb && a && a.getBoundingClientRect && !a.closest('#view .chview, .vvpin, .qadd.sheet') && a._vvRev !== vvFocusN) {
    const r = a.getBoundingClientRect(), lim = vv.offsetTop + vv.height;
    if (r.bottom > lim - 4) { a._vvRev = vvFocusN; a.scrollIntoView?.({block: 'nearest'}); }
  }
}
// 2.27.0 (#958): while a field has the focus on a touch screen, the page is left where the phone put it (only the numbers
// --vvt / --vvh / --vvb follow); the reset to the top waits for the focus to leave (focusout below). A desktop / DeX window
// (fine pointer) keeps the reset at once (#832: focusing the quick add must not slide the whole app up).
let vvFocusN = 0;
document.addEventListener('focusin', () => { vvFocusN++; });
const typingTouch = () => editFocused() && coarseOnly();
// 2.26.0 (#937): iOS ignores interactive-widget=resizes-content, so a box docked at the bottom of a scrolling area (the
// docked quick add, the comment box of the task panel, the team chat's composer) stays at the bottom of the LAYOUT
// viewport, under the keyboard. While a real keyboard is up and the focus is in such a box that is not fully visible, the
// box is pinned (position: fixed) right above the keyboard: bottom = --vvb, its own left / width kept, a placeholder of
// its height keeps the layout behind it still. It follows every visual viewport resize / scroll (vvSync) and is let go
// when the keyboard or the focus leaves. Android (the layout shrinks) finds the box visible and never pins it.
const VV_PIN = '#view .qdock, #detail .dbot, #view .tccomp';
function vvPin(kb) {
  const vv = window.visualViewport, a = document.activeElement;
  const box = kb && vv && editFocused() && a?.closest ? a.closest(VV_PIN) : null;
  for (const x of $$('.vvpin')) if (x !== box) vvUnpin(x);
  if (!box || box.classList.contains('vvpin')) return;
  const r = box.getBoundingClientRect(), top = vv.offsetTop, lim = top + vv.height;
  if (!r.height || (r.bottom <= lim + 1 && r.top >= top - 1)) return;  // fully visible already
  const ph = document.createElement('div'); ph.className = 'vvph'; ph.style.height = Math.round(r.height) + 'px'; ph.setAttribute('aria-hidden', 'true');
  box.before(ph); box._vvph = ph;
  box.style.transition = 'none';  // jumps, never slides (and is measured where it really is)
  box.style.left = Math.round(r.left) + 'px'; box.style.width = Math.round(r.width) + 'px';
  box.classList.add('vvpin');
}
function vvUnpin(x) { x.style.transition = 'none'; x.classList.remove('vvpin'); x.style.left = ''; x.style.width = ''; x._vvph?.remove(); x._vvph = null; }
// another field took the focus with the keyboard still up (no viewport event follows): decided again a moment later (a
// tap on a button of the pinned box must land before it moves)
let vvPinT = 0;
for (const t of ['focusin', 'focusout']) document.addEventListener(t, () => { clearTimeout(vvPinT); vvPinT = setTimeout(() => { if ($('.vvpin') || kbReal()) vvPin(kbReal()); }, 350); });
// the document itself never stays scrolled without a keyboard (a focus / caret reveal moved it): back to the top at once
// 2.26.x (#952, iPhone): --vvb = innerHeight - offsetTop - height is only right for the scroll position it was measured at.
// iOS fires ONE visual viewport resize when the keyboard comes up, with the page scrolled up (offsetTop 415), and then
// scrolls it back without a visual viewport event: --vvb stayed 0 and the sheet sat under the keyboard. So vvSync runs
// again (once per frame) on every page scroll and after each own scrollTo(0, 0), and a few times after a resize.
let vvSoonF = 0;
function vvSoon() { if (vvSoonF || !window.visualViewport) return; vvSoonF = requestAnimationFrame(() => { vvSoonF = 0; vvSync(); }); }
if (window.visualViewport) visualViewport.addEventListener('resize', () => { for (const ms of [120, 350, 700]) setTimeout(vvSoon, ms); });
window.addEventListener('scroll', () => { if ((window.scrollY || document.documentElement.scrollTop) && !kbReal() && !kbBlind() && !typingTouch()) window.scrollTo(0, 0); vvSoon(); }, {passive: true});
// 2.26.x (#952): on an iPhone / iPad touch screen (no fine pointer) a focused field of the add sheet or a docked box whose
// keyboard is not reported (yet) may leave the page scrolled: iOS's own reveal is not undone. (A top-anchored sheet
// fallback was tried and dropped: iOS does report the keyboard once it is up; the sheet only has to get the focus in the
// tap itself, see openQuickSheet.) Android / Fold / desktop (a fine pointer, or not iOS) never get here.
const IOS_DEV = /iPad|iPhone|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
const coarseOnly = () => { try { return !matchMedia('(pointer:fine)').matches && matchMedia('(pointer:coarse)').matches; } catch { return false; } };
const kbBlind = () => IOS_DEV && coarseOnly() && editFocused() && !kbReal() && !!document.activeElement?.closest?.('.qadd.sheet, ' + VV_PIN);
document.addEventListener('focusin', () => { vvRec('focusin'); setTimeout(vvDebugUpd, 0); });
document.addEventListener('focusout', () => { setTimeout(() => {
  if (editFocused()) return;
  if (!kbReal() && (window.scrollY || document.documentElement.scrollTop)) { window.scrollTo(0, 0); vvSoon(); }
  vvDebugUpd();
}, 0); });
// 2.26.x (#952): a hidden read-only diagnostics box for the keyboard / viewport numbers (no data): opens with #vvdebug in
// the address or five taps on the version number (Settings > Help); a tap on the numbers moves the box to the middle and
// back (so the sheet above the keyboard stays visible for a screenshot)
function vvDebug(on = true) {
  let el = document.getElementById('vvdbg');
  if (!on) { el?.remove(); clearInterval(vvDebug.t); return; }
  if (el || !document.body) return;
  el = document.createElement('div'); el.id = 'vvdbg'; el.setAttribute('aria-live', 'off');
  el.innerHTML = '<button type="button" class="vvdx" aria-label="Close">\u00d7</button><pre></pre>';
  document.body.appendChild(el);
  el.addEventListener('mousedown', e => e.preventDefault());  // a tap on the box keeps the focus (and the keyboard)
  el.querySelector('.vvdx').addEventListener('click', e => { e.stopPropagation(); vvDebug(false); });
  el.querySelector('pre').addEventListener('click', () => { el.classList.toggle('mid'); vvDebugUpd(); });
  clearInterval(vvDebug.t); vvDebug.t = setInterval(vvDebugUpd, 500); vvDebugUpd();
}
// the moment the keyboard came up, recorded from the last focus on (only while the box is open): the lowest visible
// height, the highest offsetTop / scrollY, whether visualViewport fired resize at all and how long after the focus, and
// kbReal() over the last 3 s
const VVR = {t0: 0, n: 0, first: null, minH: null, maxOT: 0, maxSY: 0, kb: []};
function vvRec(type) {
  if (!document.getElementById('vvdbg')) return;
  const vv = window.visualViewport, now = Math.round(performance.now()), kb = kbReal() ? 1 : 0;
  if (type === 'focusin') Object.assign(VVR, {t0: now, n: 0, first: null, minH: vv ? vv.height : null, maxOT: 0, maxSY: 0});
  if (type === 'resize') { VVR.n++; if (VVR.first == null && VVR.t0) VVR.first = now - VVR.t0; }
  if (vv) { VVR.minH = VVR.minH == null ? vv.height : Math.min(VVR.minH, vv.height); VVR.maxOT = Math.max(VVR.maxOT, vv.offsetTop); }
  VVR.maxSY = Math.max(VVR.maxSY, window.scrollY || 0);
  const last = VVR.kb[VVR.kb.length - 1];
  if (!last || last[1] !== kb) VVR.kb.push([now, kb]);
  VVR.kb = VVR.kb.filter(x => now - x[0] <= 3000).slice(-12);
}
function vvDebugUpd() {
  const el = document.getElementById('vvdbg'); if (!el) return;
  const vv = window.visualViewport, de = document.documentElement, st = de.style;
  vvRec('tick');
  // always in the visible part, also when iOS scrolled the visual viewport (the keyboard is up)
  const ot = Math.max(0, Math.round(vv?.offsetTop || 0));
  el.style.top = el.classList.contains('mid') ? Math.round(ot + (vv?.height || innerHeight) * .3) + 'px' : `calc(${ot}px + env(safe-area-inset-top, 0px) + .25rem)`;
  const mm = q => { try { return matchMedia(q).matches ? 1 : 0; } catch { return '?'; } };
  const n = v => v == null || Number.isNaN(+v) ? '-' : Math.round(v * 10) / 10;
  const a = document.activeElement, ua = navigator.userAgent;
  const uam = ua.match(/(iPhone|iPad|Android)[^;)]*|OS [\d_]+|Version\/[\d.]+|Chrome\/\d+|Firefox\/\d+|Safari\/[\d.]+/g) || [];
  el.querySelector('pre').textContent = [
    `inner ${innerWidth}x${innerHeight}  outer ${outerWidth}x${outerHeight}`,
    `vv h ${n(vv?.height)} w ${n(vv?.width)} offTop ${n(vv?.offsetTop)} pageTop ${n(vv?.pageTop)} scale ${n(vv?.scale)}`,
    `scrollY ${n(window.scrollY)}  docEl.clientH ${de.clientHeight}  S.vvMax ${n(S.vvMax)}`,
    `kbReal ${kbReal() ? 1 : 0}  kbBlind ${kbBlind() ? 1 : 0}  editFocused ${editFocused() ? 1 : 0}  vvpin ${$('.vvpin') ? 1 : 0}`,
    `--vvb ${st.getPropertyValue('--vvb') || '-'}  --vvh ${st.getPropertyValue('--vvh') || '-'}  --vvt ${st.getPropertyValue('--vvt') || '-'}`,
    `standalone ${mm('(display-mode: standalone)')}/${navigator.standalone ? 1 : 0}  coarse ${mm('(pointer:coarse)')}  fine ${mm('(pointer:fine)')}  hover:none ${mm('(hover:none)')}`,
    `since focus: vv resize ${VVR.n}x, first after ${VVR.first == null ? '-' : VVR.first + ' ms'}, min vv h ${n(VVR.minH)}, max offTop ${n(VVR.maxOT)}, max scrollY ${n(VVR.maxSY)}`,
    `kbReal 3s: ${VVR.kb.map(x => Math.round(performance.now() - x[0]) + 'ms ago=' + x[1]).join(', ') || '-'}`,
    `focus ${a ? a.tagName + (a.id ? '#' + a.id : '') : '-'}  ${new Date().toLocaleTimeString()}`,
    `UA ${uam.join(' ') || ua.slice(0, 80)}`].join('\n');
}
{
  const open = () => { if (/vvdebug/.test(location.hash)) vvDebug(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', open); else setTimeout(open, 0);
  window.addEventListener('hashchange', open);
  if (window.visualViewport) for (const t of ['resize', 'scroll']) visualViewport.addEventListener(t, () => { vvRec(t); vvDebugUpd(); });
  let taps = [];
  document.addEventListener('click', e => {
    if (!e.target.closest?.('.aboutver')) return;
    const now = Date.now(); taps = taps.filter(t => now - t < 3000); taps.push(now);
    if (taps.length >= 5) { taps = []; vvDebug(); }
  });
}
// 2.22.0 (#686): a right-click on a task row (list, Kanban, Today …) opens the task's menu ("Waiting on external…", snooze,
// pin, section …) at the row; touch: long press selects the row, the selection bar has "Waiting on external…"
document.addEventListener('contextmenu', e => {
  const r = e.target.closest?.('#view .trow[data-id]');
  if (!r || isTouch() || S.multiMode || e.target.closest('input,textarea,a[href],.ttlin') || e.shiftKey) return;
  const t = taskById(+r.dataset.id); if (!t || !(t.id > 0) || !canEdit(t)) return;
  e.preventDefault();
  taskMenu(r.querySelector('.ttl') || r, t.id);
});
