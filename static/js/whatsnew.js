// @ts-check
/* Kalmido web client: 2.556.0 (#4685) the dialog "New for you" after an update. Loaded on demand (lazyload.js LD_MODS
   whatsnew) by wn_boot, only when GET /api/whatsnew (accounts/whatsnew.py) names versions the person has not seen: ONE
   dialog with every version since the one seen last, newest first, a line per version ("v2.553 · 05.11."), scrolling, no
   limit of items; "Older changes" links the public change log when the seen version is older than the file reaches.
   Closing it in any way (button, Esc, backdrop) = seen, on every device. Switch: Settings > Help.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// "2.553.0" -> "v2.553", "2.553.1" -> "v2.553.1"
const wn_label = v => 'v' + String(v).split('.').filter((p, i) => i < 2 || +p).join('.');
const wn_date = d => /^\d{4}-\d\d-\d\d$/.test(d || '') ? fmtDateNum(pd(d), false) : '';

function wn_open(j) {
  if ($('.wnmd') || !j?.versions?.length) return;
  const md = modal(`<h3>${ic('sparkle', 's')} ${tr('New for you')}</h3>
    <div class="wnlist">${j.versions.map(v => `<section class="wnver"><h4 class="wnhead">${esc([wn_label(v.version), wn_date(v.date)].filter(Boolean).join(' · '))}</h4>
      <ul>${v.items.map(t => `<li>${esc(t)}</li>`).join('')}</ul></section>`).join('')}
      ${j.older && j.link ? `<p class="wnolder muted">${tr('Older changes')}: <a href="${esc(j.link)}" target="_blank" rel="noopener">${tr('All changes')}</a></p>` : ''}</div>
    <div class="shint lhint keep">${tr('You can switch this off in Settings > Help.')}</div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-m="close">${tr('Got it')}</button></div>`);
  md.classList.add('wnmd');
  const wl = md.querySelector('.wnlist'), wnMore = () => wl.classList.toggle('wnmore', wl.scrollTop + wl.clientHeight < wl.scrollHeight - 1);  // #4822: line only while more can be scrolled
  wl.addEventListener('scroll', wnMore, {passive: true}); wnMore();
  md.addEventListener('click', e => { if (/** @type {HTMLElement} */ (e.target).closest?.('[data-m="close"]')) md.remove(); });
  onRemove(md, () => api('POST', '/api/whatsnew/seen').then(r => { S.settings.whatsnew_seen = r.seen; }, () => { /* offline: shown again on the next start */ }));
}
