// 2.40.0 (#1371): one guard for forms with unsaved input. A form marks itself with data-fg="<key>" (the key names the
// form and its organisation / document, e.g. "ofc-set:<org>"); what is typed there is kept here as a draft until it is
// saved (fgDone) or discarded. Every redraw (setHtml: live events, ofcInfo(true), a bump, leaving the view and coming back)
// puts the draft back into the new fields, the focused field keeps its caret, and a bar says "Unsaved changes" with
// Save / Discard. data-fg-live = a form that saves each field on "change" itself (the document editor): only the field
// being typed in is kept, until its change event. Closing or reloading the page with a draft asks first (beforeunload).
// Dialogs use fgModal(md): Cancel / Esc / the backdrop ask "Discard changes?" when something was changed (modalGuard).
const FG = {d: {}, watch: [], pend: []};
const FDF_DAYS = 3;  // 2.577.0 (#4708 8): a dialog's kept input is dropped at the start after so many days
const fgField = el => /^(INPUT|SELECT|TEXTAREA)$/.test(el?.tagName) && el.type !== 'file' && el.type !== 'button' && el.type !== 'submit' && !el.closest('[data-fg-skip]');
// a field's name across redraws: its id, else its name, else its data-* attributes (positions: data-i + data-k)
const fgKey = el => el.id || el.name || [...el.attributes].filter(a => a.name.startsWith('data-')).map(a => a.name + '=' + a.value).join('&');
const fgVal = el => el.type === 'checkbox' || el.type === 'radio' ? el.checked : el.value;
const fgDef = el => el.type === 'checkbox' || el.type === 'radio' ? el.defaultChecked
  : el.tagName === 'SELECT' ? ([...el.options].find(o => o.defaultSelected) || el.options[0])?.value ?? '' : el.defaultValue;
const fgFields = root => [...root.querySelectorAll('input,select,textarea')].filter(fgField);
const fgDirty = key => !!FG.d[key] && Object.keys(FG.d[key].f).length > 0;
const fgAny = () => Object.keys(FG.d).some(fgDirty) || [...FG.watch, ...FG.pend.map(p => p.ask)].some(fn => { try { return !!fn?.(); } catch { return false; } });
function fgDone(key) { delete FG.d[key]; for (const f of document.querySelectorAll('[data-fg]')) if (f.dataset.fg === key) fgBar(f); }
// another module with its own unsaved state (the import preview) adds a check for beforeunload
const fgWatch = fn => { FG.watch.push(fn); };
// 2.422.0 A (#3468): a save still waiting (a debounce, a field typed in but never left): send() puts it out at once in a way
// that outlives the page (core.js keepSend / outKeep) and runs at pagehide; ask() = true while something waits that is not
// safe that way (no queue behind it): closing / reloading asks first. Returns the function that ends the registration.
function fgPending(send, ask) {
  const p = {send, ask}; FG.pend.push(p);
  return () => { FG.pend = FG.pend.filter(x => x !== p); };
}

function fgNote(t, live) {
  const form = t.closest?.('[data-fg]'); if (!form || !fgField(t)) return;
  const key = form.dataset.fg, d = FG.d[key] || (FG.d[key] = {f: {}}), k = fgKey(t);
  if (live && 'fgLive' in form.dataset) { delete d.f[k]; return; }  // saved by the form itself
  const v = fgVal(t);
  if (v === fgDef(t)) delete d.f[k]; else d.f[k] = v;
  if (!('fgLive' in form.dataset)) fgBar(form);
}
document.addEventListener('input', e => fgNote(e.target, false), true);
document.addEventListener('change', e => fgNote(e.target, true), true);

function fgBar(form) {
  const key = form.dataset.fg, on = fgDirty(key) && !('fgLive' in form.dataset);
  let bar = form.querySelector(':scope > .fgbar');
  if (!on) { bar?.remove(); return; }
  if (bar) return;
  bar = document.createElement('div'); bar.className = 'fgbar'; bar.setAttribute('role', 'status');
  bar.innerHTML = `${ic('info', 's')}<span>${esc(tr('Unsaved changes'))}</span><span class="spacer"></span><button type="button" class="btn sm" data-fgb="discard">${esc(tr('Discard'))}</button><button type="button" class="btn sm pri" data-fgb="save">${esc(tr('Save'))}</button>`;
  form.prepend(bar);
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-fgb]'); if (!b) return;
  const form = b.closest('[data-fg]'); if (!form) return;
  e.preventDefault();
  if (b.dataset.fgb === 'save') {
    const sv = form.dataset.fgSave ? form.querySelector(form.dataset.fgSave) : null;
    if (sv) sv.click(); else if (form.requestSubmit) form.requestSubmit(); else form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
  } else {
    delete FG.d[form.dataset.fg];
    for (const el of fgFields(form)) { if (el.type === 'checkbox' || el.type === 'radio') el.checked = el.defaultChecked; else el.value = fgDef(el); }
    fgBar(form);
    form.dispatchEvent(new CustomEvent('fg-discard', {bubbles: true}));
  }
});

// called by setHtml before it replaces el's content: returns what puts the drafts back afterwards (null = nothing to do)
function fgKeep(el) {
  if (!el || !Object.keys(FG.d).length) return null;
  const a = document.activeElement, af = a && el.contains(a) && a.closest('[data-fg]') && fgField(a) ? {form: a.closest('[data-fg]').dataset.fg, k: fgKey(a), s: a.selectionStart, e: a.selectionEnd} : null;
  return () => {
    const forms = [...(el.matches?.('[data-fg]') ? [el] : []), ...el.querySelectorAll('[data-fg]')];
    for (const form of forms) {
      const d = FG.d[form.dataset.fg]; if (!d) continue;
      const fs = fgFields(form);
      // the focus first, then the value: a browser fires "change" on blur only for input made while focused
      let n = null;
      if (af && af.form === form.dataset.fg && (!a.isConnected || document.activeElement === document.body)) {
        n = fs.find(x => fgKey(x) === af.k);
        if (n && !n.disabled) { try { n.focus({preventScroll: true}); } catch { n = null; } } else n = null;
      }
      for (const f of fs) {
        const k = fgKey(f); if (!(k in d.f)) continue;
        const v = d.f[k];
        if (fgDef(f) === v) { delete d.f[k]; continue; }  // the saved value caught up (saved elsewhere)
        if (fgVal(f) !== v) { if (typeof v === 'boolean') f.checked = v; else f.value = v; }
        const det = f.closest('details'); if (det && !det.open) det.open = true;
      }
      if (n && af.s != null && n.setSelectionRange) { try { n.setSelectionRange(af.s, af.e); } catch { /* a field without a caret */ } }
      fgBar(form);
    }
  };
}

// a dialog: asks before its unsaved input is thrown away; returns the close function for its Cancel button
// 2.577.0 (#4708 8): and its input survives an ended session / a reload / a closed tab (fdDialog) in every such dialog: the
// key is the dialog's title + its fields + their values when it opened (fgAutoKey), so a draft only comes back into the same
// dialog of the same record in the same state (saved elsewhere since: other values, other key). A dialog that calls
// fdDialog itself (own key, base) keeps that; fd = false or data-fd-skip on the dialog: nothing kept.
function fgModal(md, fd) {
  const snap = () => JSON.stringify(fgFields(md).map(fgVal)), start = snap();
  const close = modalGuard(md, () => snap() !== start);
  if (fd !== false && typeof fdDialog === 'function' && !md.matches?.('[data-fd-skip]') && !md.querySelector?.('[data-fd-skip]')) {
    const fs = fgFields(md), key = fgAutoKey(md, fs, start);
    if (fs.length) setTimeout(() => { if (!md._fdOn && md.isConnected) fdDialog(md, key); }, 0);  // after the caller's own setup
  }
  return close;
}
function fgAutoKey(md, fs, start) {
  const s = (md.querySelector('h1,h2,h3,h4')?.textContent || '').trim() + '|' + fs.map(fgKey).join(',') + '|' + start;
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
  return 'auto.' + h.toString(36) + '.' + s.length.toString(36);
}

// 2.527.0 (#4304 A5): a dialog's input survives the end of the session (401 -> sign-in -> reload), a closed tab or a crash:
// kept in this browser while it is typed (core.js fdKeep, kind 'fdf', per account) and put back into the same fields when the
// same dialog (key) opens again; base = the record's updated_at (saved elsewhere since: dropped with a hint). The dialog
// leaving the page (saved, discarded, closed) drops it. Call after fgModal, so Cancel asks for what came back.
// 2.552.0 (#4547): x = {get, put} for what is no plain field (rows drawn by the dialog, a picker): get() = its value while
// changed (undefined = nothing to keep), put(v) puts it back; a change there fires "change" on the dialog
function fdDialog(md, key, base = '', x) {
  md._fdOn = true;  // 2.577.0 (#4708 8): fgModal's automatic key steps back
  const k = fdTake('fdf', key, undefined, base);
  if (k && typeof k === 'object') {
    let n = 0;
    for (const f of fgFields(md)) {
      const fk = fgKey(f); if (!(fk in k) || f.disabled) continue;
      if (typeof k[fk] === 'boolean') f.checked = k[fk]; else f.value = k[fk];
      n++; const det = f.closest('details'); if (det && !det.open) det.open = true;
    }
    if (x && k._fdx !== undefined) { try { x.put(k._fdx); n++; } catch { /* an older shape: the fields are back */ } }
    if (n) toast(tr('Your unsaved input is back'));
  }
  let t = 0, done = false;
  const keep = () => {
    clearTimeout(t); if (done) return;
    const o = {};
    for (const f of fgFields(md)) { if (f.type === 'password' || f.disabled) continue; const v = fgVal(f); if (v !== fgDef(f)) o[fgKey(f)] = v; }
    const xv = x?.get(); if (xv !== undefined) o._fdx = xv;  // 2.552.0 (#4547)
    if (Object.keys(o).length) fdKeep('fdf', key, o, base); else fdDrop('fdf', key);
  };
  const soon = () => { clearTimeout(t); t = setTimeout(keep, 300); };
  md.addEventListener('input', soon); md.addEventListener('change', keep);
  const hide = () => { gone = true; keep(); };  // the page goes (a reload after the sign-in page, a closed tab): kept, not dropped
  let gone = false;
  const back = () => { gone = false; };  // review (#4304): back from the bfcache, the dialog lives on: closing it drops the input again
  addEventListener('pagehide', hide); addEventListener('pageshow', back);
  onRemove(md, () => { done = true; clearTimeout(t); removeEventListener('pagehide', hide); removeEventListener('pageshow', back); if (!gone) fdDrop('fdf', key); });
}

window.addEventListener('beforeunload', e => { if (fgAny()) { e.preventDefault(); e.returnValue = ''; } });
addEventListener('pagehide', () => { for (const p of FG.pend) { try { p.send(); } catch { /* the next one still goes */ } } });
