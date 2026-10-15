// 2.46.2 (#1660): new chat messages and comments fade in softly; "New message ↓" / "New comment ↓" when the person has
// scrolled up and something new arrives below. Only entries that are newer than everything seen in this conversation
// animate: opening a chat / task and loading older entries stay quiet (the first fill of a box only seeds the state).
const cf_idNum = n => +String(n.dataset?.mid || '').split(':')[1] || 0;
const cf_still = () => !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
// call right after a box was patched; scope = the conversation (so another chat starts quiet). -> the new nodes
const CF = {};  // per box id: {scope, n, max}; kept here, not on the element (a full redraw replaces the box)
function cf_after(box, scope, skip) {
  const nodes = [...box.children].filter(n => n.dataset?.mid), st = CF[box.id] ||= {};
  const max = nodes.reduce((m, n) => Math.max(m, cf_idNum(n)), 0), same = st.scope === scope && st.n > 0;
  const added = same && !skip ? nodes.filter(n => cf_idNum(n) > st.max) : [];
  st.scope = scope; st.n = nodes.length; st.max = same ? Math.max(max, st.max) : max;
  if (!cf_still()) for (const n of added) { n.classList.add('cfin'); n.addEventListener('animationend', () => n.classList.remove('cfin'), {once: true}); }
  return added;
}
function cf_scroller(el) {
  for (let p = el.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowY; if ((o === 'auto' || o === 'scroll') && p.scrollHeight > p.clientHeight + 1) return p; }
  return null;
}
// is the end of this element inside what the person sees?
function cf_visible(el) {
  const s = cf_scroller(el), lim = Math.min(s ? s.getBoundingClientRect().bottom : Infinity, window.innerHeight);
  return el.getBoundingClientRect().bottom <= lim + 8;
}
const cf_pill = (id, on) => { const b = document.getElementById(id); if (b && b.classList.contains('hidden') === on) b.classList.toggle('hidden', !on); };
// a full redraw of the team view (a message arrived while nobody types): the new ones still fade in
function cf_view() { const box = $('#tc-msgs'); if (box) cf_after(box, 't:' + S.tc.rid); }
// the comments of the open task: the box is patched in drawTimeline; `wasSeen` = the last comment was in view before
function cf_comments(box, wasSeen) {
  const added = cf_after(box, 'c:' + S.tl?.id);
  if (added.length && !wasSeen && !cmtNew()) cf_pill('cm-new', true);
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('#tc-new, #cm-new'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  if (b.id === 'tc-new') { const box = $('#tc-msgs'); if (box) box.scrollTop = box.scrollHeight; }
  else $('#d-tl-items')?.lastElementChild?.scrollIntoView({block: 'nearest', behavior: cf_still() ? 'auto' : 'smooth'});
  b.classList.add('hidden');
}, true);
// the pill goes when the end is in view again (scrolled down by hand)
document.addEventListener('scroll', e => {
  const t = e.target;
  if (t.id === 'tc-msgs') { if (t.scrollHeight - t.scrollTop - t.clientHeight < 80) cf_pill('tc-new', false); return; }
  const p = document.getElementById('cm-new'); if (!p || p.classList.contains('hidden')) return;
  const last = $('#d-tl-items')?.lastElementChild; if (!last || cf_visible(last)) p.classList.add('hidden');
}, true);
// a tap on a pill keeps the focus (and the keyboard) where it is
for (const ev of ['pointerdown', 'mousedown']) document.addEventListener(ev, e => { if (e.target.closest?.('#tc-new, #cm-new')) e.preventDefault(); });
