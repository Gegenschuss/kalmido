// 2.40.0 (#1371): one guard for forms with unsaved input. A form marks itself with data-fg="<key>" (the key names the
// form and its organisation / document, e.g. "ofc-set:<org>"); what is typed there is kept here as a draft until it is
// saved (fgDone) or discarded. Every redraw (setHtml: live events, ofcInfo(true), a bump, leaving the view and coming back)
// puts the draft back into the new fields, the focused field keeps its caret, and a bar says "Unsaved changes" with
// Save / Discard. data-fg-live = a form that saves each field on "change" itself (the document editor): only the field
// being typed in is kept, until its change event. Closing or reloading the page with a draft asks first (beforeunload).
// Dialogs use fgModal(md): Cancel / Esc / the backdrop ask "Discard changes?" when something was changed (modalGuard).
const FG = {d: {}, watch: []};
const fgField = el => /^(INPUT|SELECT|TEXTAREA)$/.test(el?.tagName) && el.type !== 'file' && el.type !== 'button' && el.type !== 'submit' && !el.closest('[data-fg-skip]');
// a field's name across redraws: its id, else its name, else its data-* attributes (positions: data-i + data-k)
const fgKey = el => el.id || el.name || [...el.attributes].filter(a => a.name.startsWith('data-')).map(a => a.name + '=' + a.value).join('&');
const fgVal = el => el.type === 'checkbox' || el.type === 'radio' ? el.checked : el.value;
const fgDef = el => el.type === 'checkbox' || el.type === 'radio' ? el.defaultChecked
  : el.tagName === 'SELECT' ? ([...el.options].find(o => o.defaultSelected) || el.options[0])?.value ?? '' : el.defaultValue;
const fgFields = root => [...root.querySelectorAll('input,select,textarea')].filter(fgField);
const fgDirty = key => !!FG.d[key] && Object.keys(FG.d[key].f).length > 0;
const fgAny = () => Object.keys(FG.d).some(fgDirty) || FG.watch.some(fn => { try { return fn(); } catch { return false; } });
function fgDone(key) { delete FG.d[key]; for (const f of document.querySelectorAll('[data-fg]')) if (f.dataset.fg === key) fgBar(f); }
// another module with its own unsaved state (the import preview) adds a check for beforeunload
const fgWatch = fn => { FG.watch.push(fn); };

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
function fgModal(md) {
  const snap = () => JSON.stringify(fgFields(md).map(fgVal)), start = snap();
  return modalGuard(md, () => snap() !== start);
}

window.addEventListener('beforeunload', e => { if (fgAny()) { e.preventDefault(); e.returnValue = ''; } });
