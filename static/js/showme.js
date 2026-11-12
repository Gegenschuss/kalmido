// @ts-check
/* Kalmido web client: "Show me" (2.1086.0, #5860). An agent that explains a way through the app puts the places of that way
   under its chat message (message.show: [{target, text, route, sel, label}], the named places of docs/help-targets.json,
   checked by the server: api/showme.py). The button "Show me" (agentchat.js) loads this file; it opens the step's view
   (route) and lays the spotlight of the welcome tour (palette.js spotMake / spotPlace) over the control the person presses
   next, with the agent's line for the step. Several steps: Next / Back like the tour; the last one: Done (stays there).
   Close (Escape, Back on a phone) goes back to where the button was pressed and opens the chat again when it stepped aside.
   The agent shows, the person changes: nothing here clicks, opens a menu or a dialog, switches or saves anything; the layer
   lets every press through to the app (the person opens the settings, the dialog ... themselves; the next step then finds
   its control there). A control that does not show (a phone, a right missing, an area switched off) says so in one line
   after SHW_WAIT ms instead of doing nothing; the card keeps looking (a view still loading, a dialog opened meanwhile).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

/** @type {any} */
const SHW = {on: false, steps: [], i: 0, el: null, back: '', aid: 0, chat: false, since: 0, miss: false, rk: '', iv: 0, drawn: '', seen: false};
const SHW_WAIT = 2500;  // ms a step looks for its control before the card says it is not on the screen
const SHW_TICK = 250;   // ms between two looks (the control may appear, move or go)

// the first visible control of a step: the selectors one after the other (the list's order, not the page's)
/** @param {string} sel @returns {HTMLElement | null} */
function shw_find(sel) {
  for (const q of String(sel || '').split(',')) {
    let els; try { els = $$(q.trim()); } catch { continue; }  // a selector this browser does not know: the next one
    const e = /** @type {HTMLElement[]} */ (els).find(x => { const r = x.getBoundingClientRect(); return (r.width || r.height) && getComputedStyle(x).visibility !== 'hidden'; });
    if (e) return e;
  }
  return null;
}

/** @param {any[]} steps */
function shw_start(steps) {
  steps = (Array.isArray(steps) ? steps : []).filter(s => s && typeof s.sel === 'string');
  if (!steps.length) return;
  if (DW_CHAT && window.opener && !window.opener.closed) {  // the chat in its own small window (chatwin.js): the main window shows
    try { if (typeof window.opener.shw_open === 'function') { window.opener.focus(); window.opener.shw_open(steps); return; } } catch { /* another origin */ }  // sprung-ok: the person asked to be shown the way in the main window
  }
  if (DW_CHAT) { toast(tr('Open Kalmido in the main window to be shown the way.')); return; }
  if (SHW.on) shw_end('');
  if (typeof TOUR === 'object' && TOUR.on) tourEnd(true);
  closePalette(); closePop();
  Object.assign(SHW, {on: true, steps, i: 0, back: location.hash.slice(1), aid: S.chat?.aid || 0, chat: false, drawn: ''});
  // a chat over the view steps aside: a narrow window or a floating chat closes (Close opens it again); a phone's chat is a page
  // of its own: the route leaves it, Close comes back to it; a computer's chat beside the view stays
  const p = $('#achat');
  if (p && !p.classList.contains('hidden') && !chatFull() && (innerWidth < 1000 || p.classList.contains('float'))) { SHW.chat = true; chatClose(); }
  SHW.el = spotMake('spot');
  SHW.el.addEventListener('click', e => {
    const b = /** @type {HTMLElement | null} */ (/** @type {HTMLElement} */ (e.target).closest('[data-shw]')); if (!b) return;
    const a = b.dataset.shw;
    if (a === 'next') shw_next(); else if (a === 'back') shw_go(SHW.i - 1); else shw_end('close');
  });
  window.addEventListener('keydown', shw_key, true);
  SHW.iv = setInterval(shw_tick, SHW_TICK);
  shw_go(0);
}
// the same from a small chat window (above): the main window starts it
/** @param {any[]} steps */
function shw_open(steps) { shw_start(steps); }

/** @param {number} i */
function shw_go(i) {
  if (!SHW.on) return;
  SHW.i = Math.max(0, Math.min(SHW.steps.length - 1, i));
  const st = SHW.steps[SHW.i];
  if (st.route && location.hash !== st.route) go(st.route.slice(1));
  Object.assign(SHW, {since: Date.now(), miss: false, rk: '', seen: false});
  shw_tick();
}
function shw_next() { if (SHW.i >= SHW.steps.length - 1) shw_end('done'); else shw_go(SHW.i + 1); }

/** @param {KeyboardEvent} e */
function shw_key(e) {
  if (!SHW.on) return;
  const k = e.key;
  if (k === 'Escape' && !$('.modal')) { e.preventDefault(); e.stopPropagation(); shw_end('close'); return; }  // an open dialog closes first
  if (typing(e.target) || $('.modal')) return;
  if (k === 'ArrowRight') { e.preventDefault(); e.stopPropagation(); shw_next(); }
  else if (k === 'ArrowLeft') { e.preventDefault(); e.stopPropagation(); shw_go(SHW.i - 1); }
}

// one look: the control of the step, its place; the card is drawn anew only when the step or its state changes, the ring
// follows the control when it moves
function shw_tick() {
  if (!SHW.on || !SHW.el?.isConnected) { if (SHW.on) shw_end(''); return; }
  const st = SHW.steps[SHW.i], e = shw_find(st.sel);
  if (e && !SHW.seen) {  // once per step: a control outside the window comes into view
    SHW.seen = true;
    const r = e.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) e.scrollIntoView({block: 'center', inline: 'nearest'});  // sprung-ok: the person asked to be shown this control
  }
  const r = e ? e.getBoundingClientRect() : null;
  SHW.miss = !e && Date.now() - SHW.since > SHW_WAIT;
  const state = e ? 'on' : SHW.miss ? 'missing' : 'wait', dk = SHW.i + ':' + state;
  if (dk !== SHW.drawn) { SHW.drawn = dk; SHW.rk = ''; shw_draw(st, state); }
  const rk = r ? [r.left, r.top, r.width, r.height].map(Math.round).join() : state;
  if (rk !== SHW.rk) { SHW.rk = rk; spotPlace(SHW.el, r); }
}

/** @param {any} st @param {string} state */
function shw_draw(st, state) {
  const el = SHW.el, card = $('.tcard', el), n = SHW.steps.length, last = SHW.i === n - 1, pos = `${SHW.i + 1}/${n}`;
  el.dataset.target = st.target || ''; el.dataset.state = state; el.dataset.step = String(SHW.i);
  card.innerHTML = `<div class="tstep"><span>${esc(pos)}</span><span class="tdots">${SHW.steps.map((_, j) => `<i class="${j === SHW.i ? 'on' : j < SHW.i ? 'past' : ''}"></i>`).join('')}</span></div>
    <h3>${esc(st.label || '')}</h3>${st.text ? `<p>${esc(st.text)}</p>` : ''}
    ${state === 'missing' ? `<p class="shw-miss" role="status">${esc(tr('Not on the screen here: on a phone, without the right or with the area switched off it does not show.'))}</p>` : ''}
    <div class="tfoot"><button type="button" class="btn sm tskip" data-shw="close">${tr('Close')}</button><span class="spacer"></span>${SHW.i ? `<button type="button" class="btn sm" data-shw="back">${tr('Back')}</button>` : ''}<button type="button" class="btn sm pri" data-shw="next">${last ? tr('Done') : tr('Next')}</button></div>`;
}

// how = 'done' (the last step: stays where it is, the person goes on there), 'close' (back to where the button was pressed,
// the chat again when it stepped aside), '' (ended by another start / the layer gone)
/** @param {string} how */
function shw_end(how) {
  if (!SHW.on) return;
  SHW.on = false; clearInterval(SHW.iv); SHW.iv = 0;
  window.removeEventListener('keydown', shw_key, true);
  SHW.el?.remove(); SHW.el = null;
  if (how !== 'close') return;
  if (location.hash.slice(1) !== SHW.back) go(SHW.back);
  if (SHW.chat && SHW.aid) chatOpen(SHW.aid);
}
window.addEventListener('resize', () => { if (SHW.on) { SHW.rk = ''; shw_tick(); } });
