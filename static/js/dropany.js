// @ts-check
/* Kalmido web client: 2.591.0 (#4894) files dragged from the computer onto the window, wherever the view or the open dialog
   has an upload button -- ONE shared part instead of code per module (receipts, credit card statements, letterhead, imports, ...).
   It looks for the visible file inputs of the topmost open dialog, else of the view (#view):
     * exactly one -> the whole window takes the drop: a frame and the button's text ("Drop here: Upload files")
     * several (e.g. one button per credit card line) -> each button / its row takes the drop, the window says "Drag onto a row"
   Releasing puts the files into that input (input.files) and fires its input + change events: the module's own handler
   uploads, there is no second upload path. accept and multiple hold (a wrong type / several files on a single field ->
   a hint, nothing happens).
   Places with their own drop win: their listeners run first (document; ours is on window, bubbling) and cancel the event,
   or the input sits inside their drop area (DA_OWN). Left out: inputs marked data-nodrop (the encrypted attachment of e2e.js
   is chosen on purpose only), camera inputs (capture) next to a normal upload button, and inputs whose button cannot be
   seen (hidden, closed, disabled, behind an inert part). Mouse only ((hover: hover)); touch stays as it is.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// the drop areas of modules with their own drop (documents, file store, project files, chats, bank without receipt)
const DA_OWN = '.dc-view, .abview, #pov-files, .chview, #achat, .tcroom, [data-bnr-drop], [data-dropown]';
const DA = {k: 0};
const da_mouse = () => { try { return matchMedia('(hover: hover)').matches; } catch { return false; } };
const da_files = (/** @type {DragEvent} */ e) => [...(e.dataTransfer?.types || [])].includes('Files');
/** @param {Element|null} el */
const da_seen = el => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden' && !el.closest('[inert], [aria-hidden="true"]');
// where to look: the topmost open dialog (it covers the view), else the view
function da_scope() {
  // 2.591.0 (#4894, review): a covering viewer (PDF / picture lightbox) counts as a dialog too - without an upload in it nothing drops
  const ms = [...document.querySelectorAll('.modal, .lightbox, [aria-modal="true"]')].filter(m => !m.classList.contains('closing') && !m.classList.contains('hidden') && da_seen(m));
  return ms.length ? ms[ms.length - 1] : document.getElementById('view');
}
// the visible control of an input: the input itself, its label, or the button right after a hidden input (<input hidden><button>)
/** @param {HTMLInputElement} inp @returns {HTMLElement|null} */
function da_anchor(inp) {
  if (inp.matches(':disabled') || inp.closest('[data-nodrop]')) return null;  // :disabled also inside a disabled fieldset (review)
  /** @type {any} */ let a = !inp.hidden && da_seen(inp) ? inp : inp.closest('label') || (inp.id ? document.querySelector(`label[for="${CSS.escape(inp.id)}"]`) : null);
  if (!a) { const n = inp.nextElementSibling; if (n && n.matches('button')) a = n; }
  if (!a || !da_seen(a) || a.matches(':disabled') || a.classList.contains('dis') || a.getAttribute('aria-disabled') === 'true') return null;
  return a;
}
/** @returns {{inp: HTMLInputElement, a: HTMLElement, z?: Element}[]} */
function da_cands() {
  const sc = da_scope(); if (!sc || !da_seen(sc)) return [];
  let c = /** @type {HTMLInputElement[]} */ ([...sc.querySelectorAll('input[type="file"]')]).filter(i => !i.closest(DA_OWN))
    .map(inp => ({inp, a: da_anchor(inp)})).filter(x => x.a).map(x => /** @type {{inp: HTMLInputElement, a: HTMLElement}} */ (x));
  if (c.some(x => !x.inp.hasAttribute('capture'))) c = c.filter(x => !x.inp.hasAttribute('capture'));  // the camera button next to "Upload files"
  if (c.length > 1) for (const x of c) {  // its row: the largest part around the button that holds no other button (and stays a row)
    /** @type {Element} */ let z = x.a;
    for (let p = x.a.parentElement; p && p !== sc && p !== document.body; p = p.parentElement) {
      if (c.some(o => o !== x && p.contains(o.a)) || p.getBoundingClientRect().height > 160) break;
      z = p;
    }
    /** @type {any} */ (x).z = z;
  }
  return c;
}
/** @param {HTMLElement} a */
const da_label = a => (a.matches('input') ? a.getAttribute('aria-label') || (a.id && document.querySelector(`label[for="${CSS.escape(a.id)}"]`)?.textContent) || ''
  : a.textContent || a.getAttribute('aria-label') || a.title || '').replace(/\s+/g, ' ').trim() || tr('Files');
function da_clear() {
  document.documentElement.classList.remove('dropany-on', 'dropany-one');
  document.querySelectorAll('.dropany-zone').forEach(x => x.classList.remove('dropany-zone', 'dropany-over'));
  document.getElementById('dahint')?.remove();
}
/** @param {string} txt @param {boolean} one */
function da_hint(txt, one) {
  let h = document.getElementById('dahint');
  if (!h) { h = document.createElement('div'); h.id = 'dahint'; h.setAttribute('role', 'status'); document.body.appendChild(h); }
  document.documentElement.classList.toggle('dropany-one', one);
  if (h.textContent !== txt) { h.innerHTML = `<span>${ic('upload', 's')}${esc(txt)}</span>`; }
}
/** @param {string} acc @param {File} f */
function da_fits(acc, f) {
  const ts = String(acc || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean); if (!ts.length) return true;
  const n = (f.name || '').toLowerCase(), ty = (f.type || '').toLowerCase();
  return ts.some(t => t[0] === '.' ? n.endsWith(t) : t.endsWith('/*') ? ty.startsWith(t.slice(0, -1)) : ty === t);
}
/** @param {HTMLInputElement} inp @param {File[]} files */
function da_put(inp, files) {
  if (!files.length) return;
  if (!inp.multiple && files.length > 1) { toast(tr('Only one file fits here')); return; }
  if (files.some(f => !da_fits(inp.accept, f))) { toast(tr('This file type does not fit here')); return; }
  const dt = new DataTransfer(); files.forEach(f => dt.items.add(f));
  inp.files = dt.files;
  inp.dispatchEvent(new Event('input', {bubbles: true}));
  inp.dispatchEvent(new Event('change', {bubbles: true}));
}
window.addEventListener('dragover', e => {
  if (!da_files(e) || !da_mouse()) return;
  if (e.defaultPrevented) { da_clear(); return; }  // a module with its own drop has it
  const c = da_cands(); if (!c.length) { da_clear(); return; }
  e.preventDefault(); clearTimeout(DA.k); DA.k = setTimeout(da_clear, 1500); document.documentElement.classList.add('dropany-on');
  const dt = /** @type {DataTransfer} */ (e.dataTransfer);
  if (c.length === 1) { dt.dropEffect = 'copy'; da_hint(tr('Drop here: {0}', da_label(c[0].a)), true); return; }
  const hit = c.find(x => x.z?.contains(/** @type {Node} */ (e.target)));
  for (const x of c) { x.z?.classList.add('dropany-zone'); x.z?.classList.toggle('dropany-over', x === hit); }
  dt.dropEffect = hit ? 'copy' : 'none';
  da_hint(tr('Drag onto a row'), false);
});
window.addEventListener('dragleave', e => { if (!e.relatedTarget) da_clear(); });  // left the window (a drag that ends without one: the timer above)
window.addEventListener('drop', da_clear, true);
window.addEventListener('drop', e => {
  if (!da_files(e) || !da_mouse() || e.defaultPrevented) return;
  const c = da_cands(); if (!c.length) return;
  e.preventDefault();
  const x = c.length === 1 ? c[0] : c.find(y => y.z?.contains(/** @type {Node} */ (e.target)));
  if (x) da_put(x.inp, [...(e.dataTransfer?.files || [])]);
});
