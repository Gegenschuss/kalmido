// @ts-check
/* Kalmido web client: 2.630.0 (#4510) ONE registry for keyboard shortcuts instead of a keydown listener per area.
   kb_on(scope, key, fn, {help, group, inField}) registers a key for a scope; kb_push(scope, el, {close}) puts an open dialog /
   popover on the scope stack (kb_pop takes it off; an element that left the page drops off by itself). ONE keydown listener
   asks the scopes from the innermost out: the stack (the last one opened first: a menu opened in a dialog before the dialog,
   a dialog opened over a menu before the menu), then 'overlay' (open things that are not on the stack yet), the view
   ('view:<module>', then 'view'), then 'global'. The first handler that does not return false has the key: only ONE reacts.
   An open dialog is modal: the scopes below it get no key. Letter keys never fire while typing (input, textarea,
   contenteditable) unless the handler asks for it (inField). The help (palette.js SHORTCUTS) lists every key registered
   with a help text.
   The listener sits on window (the bubble phase): every area's own listener on the element or the document has its say
   first; one that took the key (preventDefault / stopPropagation) wins. Older listeners keep working until they move here.
   2.655.0 (#4998): the scope 'first' runs in the capture phase before every field and area (see kb_runFirst). A script
   loaded before keys.js registers late: domReady(() => kb_on(...)). */
'use strict';

/** @typedef {{key: string, spec: string, fn: (e: KeyboardEvent, s: KbScope) => any, help: string, group: string, inField: boolean}} KbHandler */
/** @typedef {{scope: string, el?: any, close?: (() => any) | null}} KbScope */
const KBR = {/** @type {Map<string, KbHandler[]>} */ on: new Map(), /** @type {KbScope[]} */ st: []};
/** @type {Record<string, string>} */
const KB_ALIAS = {esc: 'escape', ' ': 'space', spacebar: 'space', '↑': 'arrowup', '↓': 'arrowdown', '←': 'arrowleft', '→': 'arrowright', del: 'delete'};
// 'Mod+Shift+K' -> 'mod+shift+k' (Mod = Ctrl, or ⌘ on a Mac), 'Esc' -> 'escape'; the modifiers in a fixed order
function kb_norm(/** @type {string} */ spec) {
  const p = String(spec).split('+'); let k = p.pop() || ''; if (k === '' && p.length) { p.pop(); k = '+'; }  // 'Mod++'
  const m = new Set(p.map(x => x.toLowerCase()).map(x => x === 'ctrl' || x === 'cmd' || x === 'meta' ? 'mod' : x === 'option' ? 'alt' : x));
  k = KB_ALIAS[k.toLowerCase()] || k.toLowerCase();
  return ['alt', 'mod', 'shift'].filter(x => m.has(x)).concat(k).join('+');
}
// the key of an event in the same form; Shift counts for letters and named keys, not for a sign it already makes ('?', '/')
function kb_keyOf(/** @type {KeyboardEvent} */ e) {
  const raw = e.key || ''; if (!raw || raw === 'Dead' || raw === 'Unidentified' || ['Shift', 'Control', 'Alt', 'Meta'].includes(raw)) return '';
  let k = KB_ALIAS[raw.toLowerCase()] || raw.toLowerCase();
  const sign = raw.length === 1 && raw.toLowerCase() === raw.toUpperCase();  // a sign or digit, not a letter
  const m = [e.altKey && 'alt', (e.ctrlKey || e.metaKey) && 'mod', e.shiftKey && !sign && 'shift'].filter(Boolean);
  return m.concat(k).join('+');
}
const kb_typing = (/** @type {any} */ t) => !!t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') || !!t.isContentEditable);
/** registers fn for key in scope; returns the function that takes it off again. fn(e, scope) returning false = not mine. */
function kb_on(/** @type {string} */ scope, /** @type {string} */ key, /** @type {(e: KeyboardEvent, s: KbScope) => any} */ fn, /** @type {{help?: string, group?: string, inField?: boolean}} */ opt = {}) {
  const h = {key: kb_norm(key), spec: key, fn, help: opt.help || '', group: opt.group || '', inField: !!opt.inField};
  const a = KBR.on.get(scope) || []; a.push(h); KBR.on.set(scope, a);
  return () => { const b = KBR.on.get(scope) || [], i = b.indexOf(h); if (i >= 0) b.splice(i, 1); };
}
/** puts an open dialog / popover (el) on top of the scope stack; the same element again moves it to the top */
function kb_push(/** @type {string} */ scope, /** @type {any} */ el, /** @type {{close?: () => any}} */ opt = {}) {
  KBR.st = KBR.st.filter(s => s.el !== el && (!s.el || s.el.isConnected));  // the same element moves up; gone ones drop off
  const s = {scope, el, close: opt.close || null}; KBR.st.push(s); return s;
}
/** takes an element (or the entry kb_push returned) off the stack */
function kb_pop(/** @type {any} */ x) { KBR.st = KBR.st.filter(s => s !== x && s.el !== x); }
// an entry counts while its element is on the page and shown (a dialog folding away (an-out) is closed already)
const kb_alive = (/** @type {KbScope} */ s) => !s.el || (s.el.isConnected && !s.el.classList?.contains('hidden') && !s.el.classList?.contains('an-out'));
/** the scopes from the innermost out (the open stack entries, the last one first, then overlay, the view, global) */
function kb_scopes() {
  KBR.st = KBR.st.filter(s => !s.el || s.el.isConnected);  // gone from the page = off the stack
  const mod = typeof S !== 'undefined' && S.route ? S.route.mod : '';
  return [...KBR.st.filter(kb_alive).reverse(), {scope: 'overlay'}, ...(mod ? [{scope: 'view:' + mod}] : []), {scope: 'view'}, {scope: 'global'}];
}
/** runs the key of e through the scopes; true = a handler took it (then the event's default is prevented) */
function kb_run(/** @type {KeyboardEvent} */ e) {
  if (e.defaultPrevented || e.isComposing) return false;  // an area's own listener took it, or a text is being composed (IME)
  const k = kb_keyOf(e); if (!k) return false;
  const letter = !/^(alt|mod)\+/.test(k) && (e.key || '').length === 1, typ = kb_typing(e.target);
  for (const s of kb_scopes()) {
    for (const h of KBR.on.get(s.scope) || []) {
      if (h.key !== k || (letter && typ && !h.inField)) continue;
      if (h.fn(e, s) !== false) { e.preventDefault(); return true; }
    }
    if (s.el && s.scope === 'dialog') return false;  // a dialog is modal: nothing below it gets the key
  }
  return false;
}
window.addEventListener('keydown', e => { kb_run(e); });
// ---- 2.655.0 (#4998): 'first' = what went before everything as a capture listener on the document (a tooltip, a drag that
// Esc cancels, a mode like connecting bars): asked in the capture phase on window, before any field or area, and NOT held by an
// open dialog (they never were). A handler that takes the key stops it there (preventDefault + stopPropagation); one that only
// watches (hides its preview and lets the key go on) returns false. The registration order is the order they are asked in.
function kb_runFirst(/** @type {KeyboardEvent} */ e) {
  if (e.defaultPrevented) return false;  // a window capture listener before it took the key (the tour of palette.js)
  const k = kb_keyOf(e); if (!k) return false;
  const letter = !/^(alt|mod)\+/.test(k) && (e.key || '').length === 1, typ = kb_typing(e.target);
  for (const h of [...(KBR.on.get('first') || [])]) {
    if (h.key !== k || (letter && typ && !h.inField)) continue;
    if (h.fn(e, {scope: 'first'}) !== false) { e.preventDefault(); e.stopPropagation(); return true; }
  }
  return false;
}
window.addEventListener('keydown', e => { kb_runFirst(e); }, true);
/** the help's rows of the registered keys with a help text: [[group, [[key, text]]]] (texts are i18n keys) */
function kb_helpRows() {
  /** @type {Map<string, Array<[string, string]>>} */
  const g = new Map();
  for (const hs of KBR.on.values()) for (const h of hs) if (h.help) {
    const n = h.group || 'General', rows = g.get(n) || [];
    if (!rows.some(([k, t]) => k === h.spec && t === h.help)) rows.push([h.spec, h.help]);
    g.set(n, rows);
  }
  return [...g.entries()];
}

// ---- the Escape of the shell (moved from events.js, #4510): the innermost open thing closes, only that one
kb_on('dialog', 'Escape', (e, s) => { if (s.close) s.close(); else modalClose(s.el); });
kb_on('popover', 'Escape', (e, s) => { if (s.close) s.close(); else closePop(); });
kb_on('overlay', 'Escape', e => ev_escOverlay(e));
kb_on('global', 'Escape', e => ev_escGlobal(e));
