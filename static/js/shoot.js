// @ts-check
/* Kalmido web client: the storyboard of a shoot (2.636.0, #4565), module "shoot" (lazyload.js, loaded on the first draw of
   such a board). A project of type Shoot (server lists/templates.py PTYPES["shoot"], only with the industry Film & Video):
   every card is one shot (fields Scene, Shot size, Lens, Location), every column a shooting day; on the board each card
   shows its picture -- the first image file of the card (not one encrypted in the browser, not one the virus scanner locked)
   -- or an empty 16:9 frame, so the board reads as the storyboard. Above the board: the shot list as PDF (one table per day,
   GET /api/lists/<id>/shotlist.pdf). calendar.js viewKanban calls sht_bar / sht_pic.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

/** the picture file of shot t (a task), or null */
const sht_file = t => (t.attachments || []).find(a => !a.enc && isImg(a) && !upLocked(a)) || null;
/** @param {any} t the picture tile at the top of a card (a click opens the shot like the rest of the card) */
function sht_pic(t) {
  const a = sht_file(t);
  return a ? `<div class="shtpic"><img src="${esc(attUrl(a))}" alt="" loading="lazy" decoding="async"></div>`
    : `<div class="shtpic none" aria-hidden="true">${ic('camera', 's')}</div>`;
}
/** @param {number} lid the bar above the storyboard: the shot list as PDF */
function sht_bar(lid) {
  return `<div class="shtbar"><a class="btn sm" href="/api/lists/${lid}/shotlist.pdf" download data-sht="pdf">${ic('download', 's')} ${tr('Shot list (PDF)')}</a>
    <span class="muted">${tr('One card per shot, one column per shooting day; the first picture of a card is its frame.')}</span></div>`;
}
