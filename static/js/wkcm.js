// @ts-check
/* Kalmido web client: 2.554.0 (#4052) -- the ONE editor of knowledge pages, on CodeMirror 6 (like SilverBullet).
   - A page one may write opens ready to type (a phone first shows it read, its pen opens this editor). There is no
     Read / Edit switch and no Source / Preview button any more; the page's "…" menu has "Edit as Markdown" (the plain
     field #wk-body, the way out) and "Read only" (a lock of this device). LS "wkEd" (the former choice, LOOK_KEYS) is ignored.
   - Live preview by decorations: Markdown marks (**, _, #, `, the parts of [text](address) and [[Page]]) show only while
     the cursor / selection is inside that element, everything else is drawn formatted. Boxes (- [ ]) are ticked by the
     first click, links open by the first click ([[…]], #123 and addresses like the read view). Tables are drawn as tables:
     a click edits only that cell, Tab goes to the next one, the text goes back into the Markdown. Pictures, formulas,
     Mermaid diagrams, mind maps, embedded pages / tables, ```seiten / ```abfrage blocks are drawn by the page renderer
     (wiki.js wk_render, diagram.js) as widgets; a click into one shows its Markdown.
   - The page stays ONE Markdown string: wiki.js wk_flush -> wk_src -> wkcm_src gives the editor's text; untouched it is
     the page's text byte for byte (no new line breaks, no trimmed spaces). Saving, conflicts, the offline outbox, history
     and locked spaces (wikie2e.js: the page arrives decrypted, the editor holds it only in memory like the former fields)
     are those of wiki.js. A failed load of CodeMirror (offline before the first use) falls back to the plain field.
   - The slash menu, the [[ / task suggestions (#wk-ac), Ctrl/Cmd+B / I / K, Ctrl/Cmd+Shift+7 / 8 / 9 and the bar
     (wkembed.js wem_bar) work on the editor through wkcm_ta(): a stand-in with the fields of a <textarea> (value,
     selectionStart / End, setSelectionRange, setRangeText); every change is one CodeMirror transaction = one undo step.
   - CodeMirror (static/vendor/codemirror, MIT, README) is loaded on the first editing only, never from a CDN.
   Classic script sharing the global scope with wiki.js (lazyload.js: module "wiki"). */
'use strict';

/** @type {any} */
const WKCM = {view: null, pid: 0, p: null, base: '', baseDoc: null, ld: null, ok: false, fail: false, cache: new Map(), px: null, foc: false, defs: null, cell: null, dgT: 0};
const wkcm_C = () => /** @type {any} */ (window).CM6;
// ---- loading (the bundle once; a failure is forgotten so the next opening tries again)
function wkcm_load() {
  if (WKCM.ok) return Promise.resolve();
  if (!WKCM.ld) {
    WKCM.ld = new Promise((ok, no) => {
      const s = document.createElement('script'); s.src = '/static/vendor/codemirror/codemirror.min.js';
      s.onload = () => (wkcm_C() ? ok(null) : no(new Error('CM6')));
      s.onerror = () => { s.remove(); no(new Error(tr('Could not be loaded'))); };
      document.head.appendChild(s);
    }).then(() => { WKCM.ok = true; WKCM.fail = false; }, e => { WKCM.ld = null; throw e; });
  }
  return WKCM.ld;
}
// the editor can be used here (not yet loaded = it is loading; failed = the plain field). CodeMirror measures text with
// Range.getClientRects: a browser without it (a document without layout, the jsdom suites) gets the plain field
const wkcm_can = () => !WKCM.fail && typeof window.Range === 'function' && typeof window.Range.prototype.getClientRects === 'function';
// ---- the stand-in field: what wiki.js / wkembed.js / wklive.js expect of a <textarea>
function wkcm_ta() {
  const v = WKCM.view; if (!v || !v.dom.isConnected) return null;
  if (WKCM.px && WKCM.px._v === v) return WKCM.px;
  const sel = () => v.state.selection.main, len = () => v.state.doc.length;
  const put = (a, b, t, s0, s1) => {
    const n = len(); a = Math.max(0, Math.min(a, n)); b = Math.max(a, Math.min(b, n));
    const x = /** @type {any} */ ({changes: {from: a, to: b, insert: t}, scrollIntoView: true, userEvent: 'input'});
    if (s0 != null) { const m = n - (b - a) + t.length; x.selection = {anchor: Math.min(s0, m), head: Math.min(s1 ?? s0, m)}; }
    v.dispatch(x);
  };
  WKCM.px = {
    _v: v, cm: true, id: 'wk-cm', el: v.contentDOM,
    get value() { return v.state.doc.toString(); },
    set value(t) {  // only the part that changed (one undo step, the drawn widgets around stay)
      const o = v.state.doc.toString(); let a = 0, z = 0;
      while (a < o.length && a < t.length && o[a] === t[a]) a++;
      while (z < o.length - a && z < t.length - a && o[o.length - 1 - z] === t[t.length - 1 - z]) z++;
      if (a === o.length && a === t.length) return;
      put(a, o.length - z, t.slice(a, t.length - z));
    },
    get selectionStart() { return sel().from; },
    get selectionEnd() { return sel().to; },
    setSelectionRange(a, b) { const n = len(); v.dispatch({selection: {anchor: Math.max(0, Math.min(a, n)), head: Math.max(0, Math.min(b ?? a, n))}, scrollIntoView: true}); },
    setRangeText(t, a, b) { put(a, b, t, a + t.length); },
    cmRep(a, b, t, s0, s1) { v.focus(); put(a, b, t, s0, s1); },  // wkembed.js wem_rep
    focus() { v.focus(); },
    dispatchEvent() { return true; },  // the change is saved by the editor's own listener (wkcm_upd)
    get isConnected() { return v.dom.isConnected; },
    getBoundingClientRect() { const c = v.coordsAtPos(sel().head); return c || v.contentDOM.getBoundingClientRect(); },
  };
  return WKCM.px;
}
// the editor holds the focus (not view.hasFocus: that also asks document.hasFocus(), false in a window without the system's focus)
const wkcm_focused = () => { const v = WKCM.view; return !!v && v.contentDOM === document.activeElement; };
const wkcm_isEl = t => !!t?.classList?.contains('cm-content') && !!t.closest?.('#wk-cm');
// the text to save while the editor holds page p (null = it does not); untouched = the page's own string
function wkcm_val() { const v = WKCM.view; return !v ? '' : v.state.doc === WKCM.baseDoc ? WKCM.base : v.state.doc.toString(); }
function wkcm_src(p) { const v = WKCM.view; return p && v && v._pid === p.id ? {value: wkcm_val()} : null; }
// ---- the place in wiki.js wk_pageHtml: an empty box the editor moves into (morph: data-fl-fill keeps it, render.js)
function wkcm_html(p) {
  if (WKCM.view && WKCM.view._pid !== p.id) wkcm_drop();
  WKCM.pid = p.id; WKCM.p = p; WKCM.foc = wkcm_focused();
  if (typeof wem_st === 'function') wem_st(p);  // the widgets share the page's file / link answers (wkembed.js)
  Promise.resolve().then(wkcm_mount); setTimeout(wkcm_mount, 0);
  const wait = WKCM.ok ? '' : `<div class="wkcmwait">${wk_bodyStrip(p.body).trim() ? wk_render(p) : ''}<p class="muted mhint">${esc(tr('Loading…'))}</p></div>`;
  return `<div id="wk-cm" class="wkcm md ntmd wkmd" data-fl-fill="1" data-pid="${p.id}">${wait}</div>`;
}
function wkcm_gone() { const v = WKCM.view; if (v && (!WK.pg || WK.pg.id !== v._pid) && !WK.dirty) wkcm_drop(); }
function wkcm_drop() { try { WKCM.view?.destroy(); } catch { /* gone */ } WKCM.view = null; WKCM.px = null; WKCM.cache.clear(); WKCM.cell = null; }
function wkcm_mount() {
  const box = /** @type {any} */ ($('#wk-cm')), p = WK.pg;
  if (!box || !p || p.id !== WKCM.pid || +box.dataset.pid !== p.id) return;
  if (!WKCM.ok) {
    wkcm_load().then(wkcm_mount, () => { WKCM.fail = true; if (S.route.mod === 'wiki' && $('#wk-cm')) renderView(); });
    return;
  }
  let v = WKCM.view;
  if (v && v._pid !== p.id) { wkcm_drop(); v = null; }
  if (v) {
    if (!box.contains(v.dom)) { box.textContent = ''; box.appendChild(v.dom); v.requestMeasure(); if (WKCM.foc) v.focus(); }
    if (!WK.dirty && wkcm_val() !== String(p.body ?? '')) wkcm_reset(p);  // the page changed under the editor (theirs taken, reloaded)
    return;
  }
  const C = wkcm_C();
  box.textContent = '';
  v = WKCM.view = new C.EditorView({state: wkcm_state(p), parent: box});
  v._pid = p.id; WKCM.px = null;
  if (box.contains(document.activeElement)) wkcm_focFx(v);
  wkcm_dgSoon();
  if (WKCM.caretAt != null) { const at = WKCM.caretAt; WKCM.caretAt = null; WKCM.focusNext = false; wkcm_caret(at); }
  else if (WKCM.focusNext) { WKCM.focusNext = false; v.focus(); }
}
function wkcm_state(p) {
  const C = wkcm_C(), body = String(p.body ?? '');
  const st = C.EditorState.create({doc: body, extensions: wkcm_ext(p)});
  WKCM.base = body; WKCM.baseDoc = st.doc;
  return st;
}
// a new text from outside (not typed): no undo step, not saved again
function wkcm_reset(p) {
  const v = WKCM.view, C = wkcm_C(), body = String(p.body ?? ''); if (!v) return;
  v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: body}, annotations: [C.Transaction.addToHistory.of(false), WKCM_EXT.of(true)]});
  WKCM.base = body; WKCM.baseDoc = v.state.doc;
}
/** @type {any} */
let WKCM_EXT = null, WKCM_FOC = null, WKCM_FX = null, WKCM_FIELD = null, WKCM_VP = null;
// keys of CodeMirror's default keymap that do something else here (Ctrl+I = italic, Ctrl+/ = Ctrl+Shift+7 on a German keyboard)
const WKCM_NOKEY = new Set(['Mod-i', 'Mod-/', 'Alt-A', 'Shift-Alt-a', 'Mod-[', 'Mod-]']);
function wkcm_ext(p) {
  const C = wkcm_C(); wkcm_defs();
  return [
    C.history(), C.drawSelection(), C.EditorView.lineWrapping, C.markdown(), C.search({top: true}),
    C.EditorState.phrases.of(wkcm_phrases()),
    C.EditorView.contentAttributes.of({'aria-label': tr('Text') + ': ' + wk_base(p.path), spellcheck: 'true', autocapitalize: 'sentences', autocorrect: 'on'}),
    C.placeholder(tr('Write … ([[Page]], [[#123]], / for commands)')),
    // files pasted / dropped: uploaded by wkembed.js (its document listener), CodeMirror must not insert their text
    C.Prec.highest(C.EditorView.domEventHandlers({mousedown: wkcm_down, click: wkcm_click,
      paste: e => !!e.clipboardData?.files?.length, drop: e => !!e.dataTransfer?.files?.length})),
    C.Prec.high(C.keymap.of([{key: 'Enter', run: wkcm_enter}, {key: 'Tab', run: v => wkcm_indent(v, 1)}, {key: 'Shift-Tab', run: v => wkcm_indent(v, -1)}])),
    C.keymap.of([...C.historyKeymap, ...C.searchKeymap, ...C.defaultKeymap.filter(k => !WKCM_NOKEY.has(k.key) && !WKCM_NOKEY.has(k.mac))]),
    WKCM_FIELD, C.EditorView.domEventHandlers({focus: (_e, v) => wkcm_focFx(v), blur: (_e, v) => wkcm_focFx(v)}),
    C.EditorView.updateListener.of(wkcm_upd),
  ];
}
// the words of CodeMirror's search panel
function wkcm_phrases() {
  return {Find: tr('Find'), Replace: tr('Replace'), next: tr('Next match'), previous: tr('Previous match'), all: tr('All'), 'match case': tr('Match case'),
    'by word': tr('Whole word'), regexp: tr('Regular expression'), replace: tr('Replace'), 'replace all': tr('Replace all'), close: tr('Close')};
}
// the marks at the cursor show while the editor has the focus (after the event: no dispatch inside CodeMirror's own handling)
function wkcm_focFx(v) {
  queueMicrotask(() => { const on = v.contentDOM === document.activeElement; if (v.state.field(WKCM_FIELD).foc !== on) v.dispatch({effects: WKCM_FOC.of(on)}); });
  return false;
}
function wkcm_upd(u) {
  if (u.docChanged && u.transactions.some(t => !t.annotation(WKCM_EXT))) wk_queue();
  if ((u.view.contentDOM === document.activeElement) !== u.state.field(WKCM_FIELD).foc) wkcm_focFx(u.view);  // a window without the system's focus sends no focus events
  if ((u.docChanged || u.selectionSet) && u.view.contentDOM === document.activeElement) { const ta = wkcm_ta(); if (ta) wk_acUpdate(ta); }
  if (u.docChanged || u.viewportChanged || u.transactions.some(t => t.effects.length)) wkcm_dgSoon();
  if (u.viewportChanged) wkcm_vpFx(u.view);  // 2.574.0 (#4681)
}
// 2.574.0 (#4681): a long page (more than WKCM_LONG lines) gets its decorations only for the lines on screen and WKCM_SPAN lines
// above and below (one typed letter rebuilt them over the whole text: 15-17 ms for 2000 lines, measured p2574_b_wkcm_ui);
// $$ blocks are still paired from the top (a block that starts above the part is drawn whole). Scrolled out of that part =
// built again around the new one (after the event, like wkcm_focFx: no dispatch inside CodeMirror's own update)
const WKCM_LONG = 600, WKCM_SPAN = 200;
function wkcm_rng(st, vp) {
  const doc = st.doc; if (doc.lines <= WKCM_LONG) return null;
  const a = doc.lineAt(Math.min(vp.from, doc.length)).number, z = doc.lineAt(Math.min(Math.max(vp.to, vp.from), doc.length)).number;
  return {from: doc.line(Math.max(1, a - WKCM_SPAN)).from, to: doc.line(Math.min(doc.lines, z + WKCM_SPAN)).to};
}
function wkcm_vpFx(v) {
  queueMicrotask(() => {
    if (!WKCM_VP || v !== WKCM.view) return;
    const f = v.state.field(WKCM_FIELD, false), p = v.viewport;
    if (f?.r && (p.from < f.r.from || p.to > f.r.to)) v.dispatch({effects: WKCM_VP.of({from: p.from, to: p.to})});
  });
}
// formulas / diagrams in the widgets are drawn by diagram.js (it finds them in .wkmd)
function wkcm_dgSoon() {
  clearTimeout(WKCM.dgT);
  WKCM.dgT = setTimeout(() => { const b = $('#wk-cm'); if (b && b.querySelector('pre[data-lang="math"]:not([data-dg]), pre[data-lang="mermaid"]:not([data-dg]), .wkimath:not([data-dg])')) { if (typeof dg_draw === 'function') dg_draw(); else loadModule('diagram').then(() => dg_draw(), () => {}); } }, 60);
}
// wkembed.js: the file / link answers came - the widgets are drawn again
function wkcm_redraw() { WKCM.cache.clear(); const v = WKCM.view; if (v && WKCM_FX) v.dispatch({effects: WKCM_FX.of(null)}); }
// writing starts there (wiki.js wk_caretAt)
function wkcm_caret(at) {
  const v = WKCM.view; if (!v || !v.dom.isConnected) { WKCM.focusNext = true; WKCM.caretAt = at; return false; }
  const n = v.state.doc.length; v.dispatch({selection: {anchor: Math.min(at, n)}, scrollIntoView: true}); v.focus(); return true;
}
// ---- Enter continues a list / a checkbox list (an empty item ends it), Tab indents list lines
const WKCM_LI = /^(\s*)([-*+]|\d{1,9}[.)])([ \t]+)(\[[ xX]\][ \t]+)?/;
function wkcm_inCode(st, pos) {
  for (let n = wkcm_C().syntaxTree(st).resolveInner(pos, -1); n; n = n.parent) if (/^(FencedCode|CodeBlock|InlineCode)$/.test(n.name)) return true;
  return false;
}
function wkcm_enter(v) {
  if (WK.ac) return false;
  const st = v.state, r = st.selection.main; if (!r.empty || st.selection.ranges.length > 1) return false;
  const l = st.doc.lineAt(r.head), m = WKCM_LI.exec(l.text);
  if (!m || r.head < l.from + m[0].length || wkcm_inCode(st, r.head)) return false;
  if (!l.text.slice(m[0].length).trim() && r.head === l.to) { v.dispatch({changes: {from: l.from, to: l.to, insert: m[1]}, selection: {anchor: l.from + m[1].length}, userEvent: 'delete'}); return true; }
  const mk = /\d/.test(m[2]) ? (parseInt(m[2], 10) + 1) + m[2].slice(-1) : m[2];
  v.dispatch(st.replaceSelection('\n' + m[1] + mk + m[3] + (m[4] ? '[ ] ' : '')), {scrollIntoView: true, userEvent: 'input'});
  return true;
}
function wkcm_indent(v, d) {
  if (WK.ac) return false;
  const C = wkcm_C(), st = v.state, l = st.doc.lineAt(st.selection.main.head);
  if (!WKCM_LI.test(l.text) || wkcm_inCode(st, l.from)) return false;
  return d > 0 ? C.indentMore(v) : C.indentLess(v);
}
// ---- the drawing: decorations from the Markdown tree, rebuilt when the text, the selection or the focus changes
function wkcm_defs() {
  if (WKCM.defs) return WKCM.defs;
  const C = wkcm_C();
  WKCM_EXT = C.Annotation.define(); WKCM_FOC = C.StateEffect.define(); WKCM_FX = C.StateEffect.define(); WKCM_VP = C.StateEffect.define();
  class Html extends C.WidgetType {
    constructor(h, block, cls) { super(); this.h = h; this.block = block; this.cls = cls || ''; }
    eq(o) { return o.h === this.h && o.block === this.block && o.cls === this.cls; }
    toDOM(view) {
      const d = document.createElement(this.block ? 'div' : 'span');
      d.className = 'cm-wkw' + (this.block ? ' cm-wkwb' : '') + (this.cls ? ' ' + this.cls : ''); d.innerHTML = this.h;
      d.addEventListener('mousedown', e => wkcm_wDown(view, d, e));
      return d;
    }
    ignoreEvent() { return true; }
    get estimatedHeight() { return this.block ? 48 : -1; }
  }
  class Box extends C.WidgetType {
    constructor(on) { super(); this.on = on; }
    eq(o) { return o.on === this.on; }
    toDOM(view) {
      const s = document.createElement('span'); s.className = 'cm-wkcb';
      const b = document.createElement('input'); b.type = 'checkbox'; b.checked = this.on; b.setAttribute('aria-label', tr('Done'));
      b.addEventListener('mousedown', e => { e.preventDefault(); e.stopPropagation(); });
      b.addEventListener('click', e => { e.preventDefault(); wkcm_tick(view, s); });
      b.addEventListener('keydown', e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); wkcm_tick(view, s); } });
      s.appendChild(b); return s;
    }
    ignoreEvent() { return true; }
  }
  class Txt extends C.WidgetType {
    constructor(t, cls) { super(); this.t = t; this.cls = cls; }
    eq(o) { return o.t === this.t && o.cls === this.cls; }
    toDOM() { const s = document.createElement('span'); s.className = this.cls; s.textContent = this.t; return s; }
    ignoreEvent() { return false; }
  }
  class Table extends C.WidgetType {
    constructor(t) { super(); this.t = t; }  // t = {from, rows: [{cells: [{a, b, raw}]}], al: [...], h: the cells' drawn html}
    eq(o) { return o.t.key === this.t.key; }
    toDOM(view) { const d = /** @type {any} */ (document.createElement('div')); d.className = 'cm-wktbl'; d._wk = this; wkcm_tblDraw(view, d, this.t); return d; }
    updateDOM(d, view) { return wkcm_tblUpdate(view, d, this); }
    ignoreEvent() { return true; }
    get estimatedHeight() { return 32 * this.t.rows.length; }
  }
  // 2.574.0 (#4681): vp = the part on screen as last told (wkcm_vpFx), r = the part the decorations cover (null = all of it)
  WKCM_FIELD = C.StateField.define({
    create: st => { const vp = {from: 0, to: 0}, r = wkcm_rng(st, vp); return {foc: false, vp, r, d: wkcm_build(st, false, r)}; },
    update(x, t) {
      let foc = x.foc, vp = t.docChanged ? {from: t.changes.mapPos(x.vp.from), to: t.changes.mapPos(x.vp.to)} : x.vp, far = false;
      for (const e of t.effects) { if (e.is(WKCM_FOC)) foc = e.value; if (e.is(WKCM_VP)) { vp = e.value; far = true; } }
      if (t.docChanged || t.selection || far || foc !== x.foc || t.effects.some(e => e.is(WKCM_FX))) { const r = wkcm_rng(t.state, vp); return {foc, vp, r, d: wkcm_build(t.state, foc, r)}; }
      return x.vp === vp ? x : {...x, vp};
    },
    provide: f => C.EditorView.decorations.from(f, x => x.d),
  });
  WKCM.defs = {Html, Box, Txt, Table};
  return WKCM.defs;
}
// a widget's own Markdown drawn by the page renderer (cached by its text)
function wkcm_md(txt, inline) {
  const p = WKCM.p || WK.pg; if (!p) return esc(txt);
  const k = (inline ? 'i' : 'b') + txt;
  let h = WKCM.cache.get(k);
  if (h == null) {
    h = wk_render(Object.assign({}, p, {body: txt}))
      .replace(/<div class="wemcbbar">[\s\S]*?<\/div>/, '').replace(/<button type="button" class="iconbtn wemcb"[\s\S]*?<\/button>/g, '');  // no "as a task" buttons (they count the whole page's lines)
    if (inline) h = h.replace(/^\s*<p>([\s\S]*)<\/p>\s*$/, '$1');
    if (WKCM.cache.size > 400) WKCM.cache.clear();
    WKCM.cache.set(k, h);
  }
  return h;
}
const WKCM_BLK = /^(mindmap|math|mermaid|seiten|pages|abfrage|query)$/i;
const WKCM_WL = /(!?)\[\[([^\[\]\n]{1,500})\]\]/g;
const WKCM_REF = /^#(\d{1,12})$/;  // 2.619.0 (#4947): the inside of [[#123]] -- the task link of a page (a bare #123 is text)
const WKCM_TAG = /(?<![\p{L}\p{N}_&/#\\])#(\p{L}[\p{L}\p{N}_/-]{0,59})/gu;
function wkcm_build(st, foc, r) {  // 2.574.0 (#4681): r = {from, to}: only the lines of that part (null = all)
  const C = wkcm_C(), D = C.Decoration, W = wkcm_defs(), doc = st.doc, out = [], sel = st.selection.ranges;
  const near = (a, z) => foc && sel.some(s => s.from <= z && s.to >= a), inR = (a, z) => !r || (a <= r.to && z >= r.from);
  const lineNear = (a, z) => near(doc.lineAt(a).from, doc.lineAt(z).to);
  const hide = (a, z) => { if (z > a) out.push(D.replace({}).range(a, z)); };
  const mark = (a, z, cls, attrs) => { if (z > a) out.push(D.mark(attrs ? {class: cls, attributes: attrs} : {class: cls}).range(a, z)); };
  const line = (a, cls) => out.push(D.line({class: cls}).range(doc.lineAt(a).from));
  const lines = (a, z, cls) => { for (let n = doc.lineAt(a).number, e = doc.lineAt(z).number; n <= e; n++) out.push(D.line({class: cls}).range(doc.line(n).from)); };
  const blocks = [], skip = [];  // ranges drawn as one widget (nothing else inside), ranges no inline pattern may touch (code)
  const inside = (a, z, rs) => rs.some(x => a < x[1] && z > x[0]), within = (a, z, rs) => rs.some(x => a >= x[0] && z <= x[1]);
  const block = (a, z, h, cls) => { out.push(D.replace({widget: new W.Html(h, true, cls), block: true}).range(a, z)); blocks.push([a, z]); };
  // front matter: muted, never parsed as a heading
  const fm = /^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/.exec(doc.sliceString(0, Math.min(doc.length, 20000)));
  const fmEnd = fm ? Math.min(fm[0].replace(/\r?\n$/, '').length, doc.length) : 0;
  if (fmEnd) { lines(0, fmEnd, 'cm-wkfm'); skip.push([0, fmEnd]); }
  // $$ … $$ lines / blocks (wiki.js wk_dgCut makes them formulas)
  if (doc.length < 400000 && doc.sliceString(0, doc.length).includes('$$')) {
    for (let n = 1; n <= doc.lines; n++) {
      const l = doc.line(n); if (l.from < fmEnd || !l.text.includes('$$') || wkcm_inCode(st, l.from + 1)) continue;  // 2.574.0 (#4681): the cheap test first
      if (/^\s*\$\$(.+?)\$\$\s*$/.test(l.text)) { if (inR(l.from, l.to)) { if (!lineNear(l.from, l.to)) block(l.from, l.to, wkcm_md(l.text, false)); skip.push([l.from, l.to]); } continue; }
      if (/^\s*\$\$\s*$/.test(l.text)) {
        let z = n + 1; while (z <= doc.lines && !/^\s*\$\$\s*$/.test(doc.line(z).text)) z++;
        if (z > doc.lines) continue;
        const e = doc.line(z); if (inR(l.from, e.to)) { if (!near(l.from, e.to)) block(l.from, e.to, wkcm_md(doc.sliceString(l.from, e.to), false)); skip.push([l.from, e.to]); } n = z;
      }
    }
  }
  const tree = C.ensureSyntaxTree(st, r ? r.to : doc.length, 200) || C.syntaxTree(st), part = r ? {from: r.from, to: r.to} : {};
  // code first (no inline pattern inside), then the [[ links (the tree reads [[A|B]] as a link "[A|B]")
  // first pass: code (no inline pattern inside), tables and drawn fences as widgets (before the [[ links: nothing inside a widget)
  tree.iterate({...part, enter: n => {
    const a = n.from, z = n.to, k = n.name;
    if (z <= fmEnd || within(a, z, blocks)) return false;
    if (k === 'FencedCode') {
      const info = n.node.getChild('CodeInfo'), lang = info ? doc.sliceString(info.from, info.to).trim() : '', la = doc.lineAt(a).from, lz = doc.lineAt(z).to;
      if (WKCM_BLK.test(lang) && !near(la, lz)) block(la, lz, wkcm_md(doc.sliceString(la, lz), false), 'cm-wkfig');
      skip.push([a, z]); return false;
    }
    if (k === 'Table') {
      const t = wkcm_tbl(st, a, z);
      if (t && !near(t.from, t.to)) { out.push(D.replace({widget: new W.Table(t), block: true}).range(t.from, t.to)); blocks.push([t.from, t.to]); }
      return false;
    }
    if (/^(CodeBlock|InlineCode|HTMLBlock|Autolink)$/.test(k)) { skip.push([a, z]); return false; }
  }});
  const wl = [];
  const o = r ? r.from : 0, txt = doc.sliceString(o, r ? r.to : doc.length);  // 2.574.0 (#4681): whole lines, the patterns never span one
  for (const m of txt.matchAll(WKCM_WL)) {
    const a = o + m.index, z = a + m[0].length; if (inside(a, z, skip)) continue;
    wl.push([a, z]);
    if (inside(a, z, blocks)) continue;
    const body = m[2], emb = !!m[1] || /^\s*(datei|tabelle)\s*:/i.test(body);
    if (emb) {  // ![[Page]], [[datei:…]], [[tabelle:…]]: drawn (a whole line = a block)
      if (near(a, z)) { mark(a, z, 'cm-wksrc'); continue; }
      const l = doc.lineAt(a), whole = !l.text.replace(m[0], '').trim();
      if (whole && l.from === a - (l.text.length - l.text.trimStart().length)) block(l.from, l.to, wkcm_md(l.text.trim(), false), 'cm-wkemb');
      else out.push(D.replace({widget: new W.Html(wkcm_md(m[0], true), false, 'cm-wkemb')}).range(a, z));
      continue;
    }
    const bar = body.indexOf('|'), tm = WKCM_REF.exec(bar < 0 ? body : body.slice(0, bar));
    if (tm) {  // 2.619.0 (#4947): [[#123]] / [[#123|label]] = a task I see: its link with the title; else the text stays as it is
      const t = typeof taskById === 'function' ? taskById(+tm[1]) : null; if (!t) continue;
      const open = !near(a, z);
      if (open) { hide(a, a + 2); if (bar >= 0) hide(a + 2, a + 3 + bar); hide(z - 2, z); }
      mark(open ? a + (bar >= 0 ? 3 + bar : 2) : a, open ? z - 2 : z, 'cm-wkl cm-wkref', open ? {'data-wkgo': '#t/' + t.id, title: String(t.title || '')} : undefined);
      continue;
    }
    const path = (bar < 0 ? body : body.slice(0, bar)).replace(/#.*$/, '').trim(), sp = (WKCM.p || WK.pg)?.space;
    const pg = sp ? wk_byPath(sp, path) : null, open = !near(a, z);
    const attrs = open ? (pg ? {'data-wkgo': '#wiki/' + pg.id} : {'data-wknew': path}) : null;
    if (open) { hide(a, a + 2); if (bar >= 0) hide(a + 2, a + 3 + bar); hide(z - 2, z); }
    mark(open ? a + (bar >= 0 ? 3 + bar : 2) : a, open ? z - 2 : z, 'cm-wkl cm-wkwl' + (pg ? '' : ' cm-wkmiss'), attrs || undefined);
  }
  tree.iterate({...part, enter: n => {
    const a = n.from, z = n.to, k = n.name;
    if (z <= fmEnd || within(a, z, blocks)) return false;
    if (/^ATXHeading(\d)$/.test(k)) {
      line(a, 'cm-wkh cm-wkh' + k.slice(-1));
      if (!lineNear(a, z)) { const c = n.node.getChildren('HeaderMark'); for (const h of c) { if (h.from === a) hide(h.from, Math.min(h.to + (doc.sliceString(h.to, h.to + 1) === ' ' ? 1 : 0), z)); else hide(h.from, h.to); } }
      return;
    }
    if (/^SetextHeading(\d)$/.test(k)) { line(a, 'cm-wkh cm-wkh' + k.slice(-1)); const h = n.node.getChild('HeaderMark'); if (h) { line(h.from, 'cm-wkfm'); } return; }
    if (k === 'StrongEmphasis' || k === 'Emphasis' || k === 'Strikethrough') {
      mark(a, z, k === 'StrongEmphasis' ? 'cm-wkb' : k === 'Emphasis' ? 'cm-wki' : 'cm-wks');
      if (!near(a, z)) for (const c of n.node.getChildren(k === 'Strikethrough' ? 'StrikethroughMark' : 'EmphasisMark')) hide(c.from, c.to);
      return;
    }
    if (k === 'FencedCode') { lines(a, z, 'cm-wkcode'); return false; }
    if (k === 'CodeBlock') { lines(a, z, 'cm-wkcode'); return false; }
    if (k === 'InlineCode') { mark(a, z, 'cm-wkc'); if (!near(a, z)) for (const c of n.node.getChildren('CodeMark')) hide(c.from, c.to); return false; }
    if (k === 'Link' || k === 'Image') {
      if (inside(a, z, wl)) return false;
      const u = n.node.getChild('URL'), ms = n.node.getChildren('LinkMark');
      if (!u || ms.length < 3) return false;  // [ref] links / no address: as written
      const href = doc.sliceString(u.from, u.to);
      if (k === 'Image') {
        if (near(a, z)) { mark(a, z, 'cm-wksrc'); return false; }
        const l = doc.lineAt(a), src = doc.sliceString(a, z);
        if (!l.text.replace(src, '').trim()) block(l.from, l.to, wkcm_md(l.text.trim(), false), 'cm-wkimg');
        else out.push(D.replace({widget: new W.Html(wkcm_md(src, true), false, 'cm-wkimg')}).range(a, z));
        return false;
      }
      const open = !near(a, z), go = wkcm_href(href);
      if (open) { hide(a, ms[0].to); hide(ms[1].from, z); }
      mark(open ? ms[0].to : a, open ? ms[1].from : z, 'cm-wkl', open && go ? {'data-wkgo': go, title: href} : undefined);
      return false;
    }
    if (k === 'URL' && !inside(a, z, wl)) { const go = wkcm_href(doc.sliceString(a, z)); mark(a, z, 'cm-wkl', !near(a, z) && go ? {'data-wkgo': go} : undefined); return; }
    if (k === 'Blockquote') { lines(a, z, 'cm-wkq'); return; }
    if (k === 'QuoteMark') { if (!lineNear(a, z)) hide(a, Math.min(z + (doc.sliceString(z, z + 1) === ' ' ? 1 : 0), doc.lineAt(a).to)); return; }
    if (k === 'HorizontalRule') { if (!lineNear(a, z)) out.push(D.replace({widget: new W.Html('<hr>', false, 'cm-wkhr')}).range(a, z)); return; }
    if (k === 'ListMark') {
      const t = doc.sliceString(a, z), task = n.node.nextSibling?.name === 'Task';
      if (task && !lineNear(a, z)) { hide(a, Math.min(z + 1, doc.lineAt(a).to)); return; }  // the box stands for the "- "
      if (/^[-*+]$/.test(t) && !lineNear(a, z)) out.push(D.replace({widget: new W.Txt('•', 'cm-wkbul')}).range(a, z));
      else mark(a, z, 'cm-wklm');
      return;
    }
    if (k === 'TaskMarker') {
      const on = /x/i.test(doc.sliceString(a, z));
      if (on) mark(z, doc.lineAt(a).to, 'cm-wkdone');
      if (!near(a, z)) out.push(D.replace({widget: new W.Box(on)}).range(a, z + (doc.sliceString(z, z + 1) === ' ' ? 1 : 0)));
      return;
    }
    if (k === 'Table') { lines(a, z, 'cm-wkcode'); return false; }
  }});
  // #tags as links, \( … \) as formulas (2.619.0, #4947: a bare #123 is text; the task link is [[#123]], above)
  const free = (a, z) => !inside(a, z, skip) && !inside(a, z, blocks) && !inside(a, z, wl) && a >= fmEnd;
  if (typeof wkt_go === 'function') for (const m of txt.matchAll(WKCM_TAG)) {
    const a = o + m.index, x = m[1].replace(/[/-]+$/, ''), z = a + 1 + x.length; if (!free(a, z)) continue;
    const sp = (WKCM.p || WK.pg)?.space; if (!sp) continue;
    mark(a, z, 'cm-wkl cm-wktag', near(a, z) ? undefined : {'data-wkgo': '#' + wkt_go(x, sp)});
  }
  if (txt.includes('\\(')) for (const m of txt.matchAll(/\\\((.+?)\\\)/g)) {
    const a = o + m.index, z = a + m[0].length; if (!free(a, z) || near(a, z)) continue;
    out.push(D.replace({widget: new W.Html(wkcm_md(m[0], true), false, 'cm-wkmath')}).range(a, z));
  }
  try { return D.set(out, true); } catch (e) { console.error(e); return D.none; }  // overlapping ranges: drawn plain rather than not at all
}
// where a link opens (only what the read view would link: web, mail, the app's own addresses)
function wkcm_href(u) {
  u = String(u || '').trim();
  if (/^(https?:|mailto:)/i.test(u)) return u;
  if (/^#[\w/-]/.test(u) || /^\/(?!\/)/.test(u)) return u;
  return '';
}
function wkcm_go(go) {
  if (go.startsWith('#')) { wk_flush(); location.hash = go; return; }
  if (/^\/(?!\/)/.test(go)) { window.open(go, '_blank', 'noopener'); return; }
  window.open(go, '_blank', 'noopener,noreferrer');
}
// a link / [[page]] / #123 opens by the first click (no modifier, the main button); Alt+click puts the cursor there
function wkcm_down(e, v) {
  const t = /** @type {any} */ (e.target), a = t.closest?.('[data-wkgo], [data-wknew]');
  if (!a || e.button !== 0 || e.altKey || e.shiftKey) return false;
  e.preventDefault(); v._wkGo = a;
  return true;
}
function wkcm_click(e, v) {
  const t = /** @type {any} */ (e.target), a = t.closest?.('[data-wkgo], [data-wknew]');
  if (!a || a !== v._wkGo) { v._wkGo = null; return false; }
  v._wkGo = null; e.preventDefault();
  if (a.dataset.wkgo) wkcm_go(a.dataset.wkgo);
  else if (WK.idx[WK.pg?.space || wk_cur()]?.mayWrite !== false) wk_new(a.dataset.wknew);
  return true;
}
// a click into a drawn widget: what works in reading works (links, players, buttons), else its Markdown opens there
function wkcm_wDown(v, d, e) {
  const t = /** @type {any} */ (e.target);
  if (e.button !== 0 || t.closest('a[href], button, input, select, summary, label, video, audio, [data-wka], [data-wem]')) return;
  e.preventDefault();
  const at = v.posAtDOM(d);
  v.dispatch({selection: {anchor: at}, scrollIntoView: false}); v.focus();
}
function wkcm_tick(v, s) {
  const at = v.posAtDOM(s), m = /^\[( |x|X)\]/.exec(v.state.sliceDoc(at, at + 3)); if (!m) return;
  v.dispatch({changes: {from: at + 1, to: at + 2, insert: m[1] === ' ' ? 'x' : ' '}, userEvent: 'input'});
}
// ---- tables: the rows of a GFM table as cells with their place in the text (escaped \| stays in a cell)
function wkcm_cells(t, off) {
  const ps = []; let code = false;
  for (let i = 0; i < t.length; i++) { const c = t[i]; if (c === '\\') { i++; continue; } if (c === '`') code = !code; else if (c === '|' && !code) ps.push(i); }
  const b = ps.slice(); if (!/^\s*\|/.test(t)) b.unshift(-1); if (!/\|\s*$/.test(t) || ps.length === 0) b.push(t.length);
  const out = [];
  for (let k = 0; k + 1 < b.length; k++) {
    const s = b[k] + 1, e = b[k + 1], seg = t.slice(s, e), l = seg.length - seg.trimStart().length, r = seg.length - seg.trimEnd().length;
    const a = seg.trim() ? s + l : s + (seg.length ? 1 : 0), z = seg.trim() ? e - r : a;
    out.push({a: off + a, b: off + z, raw: t.slice(a, z)});
  }
  return out;
}
function wkcm_tbl(st, a, z) {
  const doc = st.doc, l0 = doc.lineAt(a), l1 = doc.lineAt(z), rows = [];
  let al = [];
  for (let n = l0.number; n <= l1.number; n++) {
    const l = doc.line(n);
    if (n === l0.number + 1) { al = wkcm_cells(l.text, l.from).map(c => /^:-+:$/.test(c.raw.trim()) ? 'center' : /-:$/.test(c.raw.trim()) ? 'right' : ''); continue; }
    rows.push({from: l.from, cells: wkcm_cells(l.text, l.from)});
  }
  if (rows.length < 1 || !rows[0].cells.length) return null;
  return {from: l0.from, to: l1.to, rows, al, key: doc.sliceString(l0.from, l1.to)};
}
const wkcm_cellMd = raw => raw.replace(/\\\|/g, '|');
const wkcm_cellRaw = t => t.replace(/\r?\n/g, ' ').replace(/\|/g, '\\|');  // the field shows | where the text has \|
// the table of a widget as it is in the text now (a widget kept by eq() may stand at another place than when it was drawn)
function wkcm_tblNow(v, d) {
  let at; try { at = v.posAtDOM(d); } catch { return null; }
  for (let n = wkcm_C().syntaxTree(v.state).resolveInner(Math.min(at + 1, v.state.doc.length), 1); n; n = n.parent) if (n.name === 'Table') return wkcm_tbl(v.state, n.from, n.to);
  return null;
}
function wkcm_tblDraw(v, d, t) {
  const n = Math.max(...t.rows.map(r => r.cells.length));
  const cell = (r, c) => { const x = t.rows[r].cells[c], tag = r ? 'td' : 'th', al = t.al[c] ? ` style="text-align:${t.al[c]}"` : '';
    return `<${tag} data-r="${r}" data-c="${c}" tabindex="-1"${al}>${x ? wkcm_md(wkcm_cellMd(x.raw), true) : ''}</${tag}>`; };
  d.innerHTML = `<table><thead><tr>${Array.from({length: n}, (_, c) => cell(0, c)).join('')}</tr></thead><tbody>${t.rows.slice(1).map((_, i) => `<tr>${Array.from({length: n}, (_, c) => cell(i + 1, c)).join('')}</tr>`).join('')}</tbody></table>`
    + `<button type="button" class="iconbtn cm-wktsrc" title="${esc(tr('Edit the table as text'))}" aria-label="${esc(tr('Edit the table as text'))}">${ic('code', 's')}</button>`;
  d.onmousedown = e => {
    const x = /** @type {any} */ (e.target);
    if (e.button !== 0 || x.closest('input')) return;
    if (x.closest('.cm-wktsrc')) { e.preventDefault(); const w = wkcm_tblNow(v, d); if (w) v.dispatch({selection: {anchor: w.from}}); v.focus(); return; }
    if (x.closest('a[href]')) return;
    const c = x.closest('[data-r]'); if (!c) return;
    e.preventDefault(); wkcm_cellEdit(v, d, +c.dataset.r, +c.dataset.c);
  };
}
// the text changed (a cell typed, or elsewhere): the same table keeps its DOM (the field with the focus stays), the other cells follow
function wkcm_tblUpdate(v, d, w) {
  const o = d._wk?.t, t = w.t;
  if (!o || o.rows.length !== t.rows.length || o.rows.some((r, i) => r.cells.length !== t.rows[i].cells.length)) return false;
  d._wk = w;
  for (const c of d.querySelectorAll('[data-r]')) {
    if (c.querySelector('input')) continue;
    const x = t.rows[+c.dataset.r]?.cells[+c.dataset.c], h = x ? wkcm_md(wkcm_cellMd(x.raw), true) : '';
    if (c.innerHTML !== h) c.innerHTML = h;
  }
  return true;
}
function wkcm_cellEdit(v, d, r, c) {
  const t = wkcm_tblNow(v, d), x = t?.rows[r]?.cells[c], el = d.querySelector(`[data-r="${r}"][data-c="${c}"]`);
  if (!x || !el) return;
  const old = el.querySelector('input'); if (old) { old.focus(); return; }
  const inp = document.createElement('input'); inp.type = 'text'; inp.className = 'cm-wkcell'; inp.value = wkcm_cellMd(x.raw);
  inp.setAttribute('aria-label', tr('Cell {0}, {1}', r + 1, c + 1));
  el.textContent = ''; el.appendChild(inp); inp.focus(); inp.select();
  WKCM.cell = inp;
  const write = () => {
    const w = wkcm_tblNow(v, d), y = w?.rows[r]?.cells[c]; if (!y) return;
    const raw = wkcm_cellRaw(inp.value), empty = y.a === y.b;
    const ins = empty && raw ? (v.state.sliceDoc(y.a - 1, y.a) === '|' ? ' ' : '') + raw + (v.state.sliceDoc(y.b, y.b + 1) === '|' ? ' ' : '') : raw;
    if (ins === v.state.sliceDoc(y.a, y.b)) return;
    v.dispatch({changes: {from: y.a, to: y.b, insert: ins}, userEvent: 'input'});
  };
  const close = () => {
    if (!inp.isConnected) return; WKCM.cell = null;
    const w = wkcm_tblNow(v, d), y = w?.rows[r]?.cells[c]; el.innerHTML = y ? wkcm_md(wkcm_cellMd(y.raw), true) : '';
  };
  const move = (r2, c2) => {
    const w = wkcm_tblNow(v, d); if (!w) return;
    const n = Math.max(...w.rows.map(q => q.cells.length));
    if (c2 >= n) { c2 = 0; r2++; } if (c2 < 0) { r2--; c2 = n - 1; }
    if (r2 < 0) { close(); v.dispatch({selection: {anchor: Math.max(0, w.from - 1)}}); v.focus(); return; }
    if (r2 >= w.rows.length) {  // Tab after the last cell: a new row
      const at = w.to, row = '\n|' + '  |'.repeat(n);
      inp.removeEventListener('blur', blur); close();
      v.dispatch({changes: {from: at, insert: row}, userEvent: 'input'});
      setTimeout(() => { const nd = [...document.querySelectorAll('#wk-cm .cm-wktbl')].find(q => wkcm_tblNow(v, q)?.from === w.from); if (nd) wkcm_cellEdit(v, nd, r2, c2); }, 0);
      return;
    }
    inp.removeEventListener('blur', blur); close(); wkcm_cellEdit(v, d, r2, c2);
  };
  const blur = () => close();
  inp.addEventListener('input', write);
  inp.addEventListener('blur', blur);
  inp.addEventListener('keydown', e => {
    if (e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); move(r, c + (e.shiftKey ? -1 : 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); move(r + 1, c); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); inp.removeEventListener('blur', blur); close(); const w = wkcm_tblNow(v, d); v.dispatch({selection: {anchor: w ? Math.min(w.to + 1, v.state.doc.length) : 0}}); v.focus(); }
    else if ((e.ctrlKey || e.metaKey) && /^[zy]$/i.test(e.key)) { e.preventDefault(); const C = wkcm_C(); (e.key.toLowerCase() === 'y' || e.shiftKey ? C.redo : C.undo)(v); const w = wkcm_tblNow(v, d), y = w?.rows[r]?.cells[c]; if (y) inp.value = wkcm_cellMd(y.raw); }
  });
}
// the suggestions / commands just below the caret (a phone with its keyboard open keeps wkembed.js wem_acPlace)
function wkcm_acPlace(box) {
  const ta = wkcm_ta();
  if (!ta || box.style.position === 'fixed' || !$('#wk-cm')) return;
  const wr = box.parentElement?.getBoundingClientRect(); if (!wr) return;
  box.style.top = Math.round(ta.getBoundingClientRect().bottom - wr.top + 4) + 'px';
}
