/* Kalmido web client: related tasks (2.59.0 B, #1375). A folded "Related tasks" section in a task (loads when unfolded),
   the hint "Similar: #… title" under the quick add while typing, "also similar meaning" in the search, the switch in
   Administration > Server. Everything stays hidden while the server runs without its embedding service (enabled: false).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const RT9 = {on: null, ask: null, cache: new Map(), qseq: 0, qtimer: 0, TTL: 60000};
// GET /api/related/config once per page (rawFetch: no outbox, no toast; offline / an error = hidden)
function rt9_cfg() {
  if (RT9.on !== null) return Promise.resolve(RT9.on);
  return RT9.ask || (RT9.ask = rawFetch('GET', '/api/related/config').then(j => (RT9.on = !!j?.enabled), () => (RT9.on = false)));
}

// ---- in a task
function rt9_detailHtml(t) {
  if (!t || !(t.id > 0) || t.context) return '';
  if (RT9.on !== true) {
    if (RT9.on === null) rt9_cfg().then(on => { if (on && S.sel) renderDetail(); });
    return '';
  }
  const open = !!LS.get('rt9Open', false), c = RT9.cache.get(t.id);
  if (open && (!c || Date.now() - c.at > RT9.TTL) && !c?.busy) setTimeout(() => rt9_load(t.id), 0);
  const dup = (c?.items || []).some(x => x.dup);
  return `<details class="dsec rt9sec" id="d-rel" data-tid="${t.id}" ${open ? 'open' : ''}><summary><span>${tr('Related tasks')}</span>${dup ? `<span class="rt9dupb">${esc(tr('probably a duplicate'))}</span>` : ''}</summary><div class="rt9list" aria-live="polite">${rt9_listHtml(c)}</div></details>`;
}
function rt9_listHtml(c) {
  if (!c || (c.busy && !c.items)) return `<div class="muted rt9empty">${tr('Loading…')}</div>`;
  if (c.pending) return `<div class="muted rt9empty">${esc(tr('Being computed, please check again in a minute.'))}</div>`;
  if (!c.items?.length) return `<div class="muted rt9empty">${esc(tr('Nothing similar found.'))}</div>`;
  return c.items.map(x => `<button type="button" class="rt9it ${x.done ? 'rt9done' : ''}" data-act="open-id" data-id="${x.id}"><span class="rt9n">#${x.id}</span><span class="rt9t">${esc(mdPlain(x.title))}</span>${x.dup ? `<span class="rt9dup">${esc(tr('probably a duplicate'))}</span>` : ''}</button>`).join('');
}
async function rt9_load(tid) {
  const old = RT9.cache.get(tid);
  if (old?.busy) return;
  RT9.cache.set(tid, {...(old || {}), busy: true, at: old?.at || 0});
  let c;
  try { const j = await rawFetch('GET', `/api/tasks/${tid}/related`); c = {items: j.items || [], pending: !!j.pending, at: Date.now()}; if (!j.enabled) RT9.on = false; }
  catch { c = {items: [], pending: false, at: Date.now()}; }
  if (c.pending) c.at = Date.now() - RT9.TTL + 10000;  // asked again after 10 s
  RT9.cache.set(tid, c);
  const box = document.querySelector(`#d-rel[data-tid="${tid}"]`);
  if (!box) return;
  if (RT9.on === false) { box.remove(); return; }
  $('.rt9list', box).innerHTML = rt9_listHtml(c);
  const s = $('summary', box), dup = c.items.some(x => x.dup), b = $('.rt9dupb', s);
  if (dup && !b) s.insertAdjacentHTML('beforeend', `<span class="rt9dupb">${esc(tr('probably a duplicate'))}</span>`);
  else if (!dup && b) b.remove();
}
document.addEventListener('toggle', e => {  // toggle does not bubble: caught on the way down
  const d = e.target; if (d?.id !== 'd-rel') return;
  LS.set('rt9Open', d.open);
  const tid = +d.dataset.tid, c = RT9.cache.get(tid);
  if (d.open && (!c || Date.now() - c.at > RT9.TTL)) rt9_load(tid);
}, true);

// ---- the hint while adding (quick add / the add sheet): after a pause in typing, at most two, a tap opens the task
function rt9_qaHint(input) {
  if (!input || !['qinput', 'qsheet'].includes(input.id)) return;
  if (RT9.on === null) { rt9_cfg(); return; }
  if (RT9.on !== true) return;
  clearTimeout(RT9.qtimer);
  const box = input.closest('.qadd'); if (!box) return;
  let r; try { r = parseQuick(input.value, S.quick.ignore); } catch { return; }
  const title = (r.title || '').trim();
  if (title.length < 4) { RT9.qseq++; rt9_qaShow(box, []); return; }
  RT9.qtimer = setTimeout(async () => {
    const seq = ++RT9.qseq;
    let lid = r.list_id || null;
    try { lid = lid || quickDefaults().list_id || null; } catch { /* no defaults here */ }
    let j; try { j = await rawFetch('POST', '/api/tasks/similar', {title, list_id: lid}); } catch { return; }
    if (seq !== RT9.qseq || !input.isConnected || !input.value.trim()) return;
    rt9_qaShow(box, (j.items || []).slice(0, 2));
  }, 600);
}
function rt9_qaShow(box, items) {
  let el = $('.rt9qh', box);
  if (!items.length) { el?.remove(); return; }
  if (!el) { el = document.createElement('div'); el.className = 'rt9qh'; el.setAttribute('role', 'status'); (box.querySelector('.chips') || box).insertAdjacentElement('afterend', el); }
  el.innerHTML = `<span class="rt9ql">${ic('copy', 's')}${esc(tr('Similar:'))}</span>` + items.map(x => `<button type="button" class="linkbtn rt9qi" data-act="open-id" data-id="${x.id}">#${x.id} ${esc(mdPlain(x.title).slice(0, 80))}${x.dup ? ` <span class="rt9dup">${esc(tr('probably a duplicate'))}</span>` : ''}</button>`).join('');
}
document.addEventListener('input', e => { if (e.target?.id === 'qinput' || e.target?.id === 'qsheet') rt9_qaHint(e.target); });
document.addEventListener('keydown', e => {  // Enter adds the task: the hint goes with the text
  if (e.key !== 'Enter' || !(e.target?.id === 'qinput' || e.target?.id === 'qsheet')) return;
  RT9.qseq++; clearTimeout(RT9.qtimer);
  const box = e.target.closest('.qadd'); if (box) setTimeout(() => rt9_qaShow(box, []), 0);
});

// ---- the search: "also similar meaning" (per device)
function rt9_searchToggleHtml() {
  if (RT9.on === null) rt9_cfg().then(on => { const w = $('#rt9-semw'); if (on && w) w.innerHTML = rt9_semBox(); });
  return `<div id="rt9-semw" class="rt9semw">${RT9.on ? rt9_semBox() : ''}</div>`;
}
const rt9_semBox = () => `<label class="chkl rt9sem"><input type="checkbox" id="rt9-sem" ${LS.get('rt9Sem', false) ? 'checked' : ''}> ${esc(tr('also similar meaning'))}</label>`;
const rt9_semQ = () => RT9.on && LS.get('rt9Sem', false) ? '&semantic=1' : '';
document.addEventListener('change', e => {
  if (e.target?.id !== 'rt9-sem') return;
  LS.set('rt9Sem', e.target.checked);
  if ((S.searchQ || '').trim()) { if (S.msg) S.msg.q = S.searchQ; doSearch(S.searchQ); }  // the messages below stay as they are
});
// the heading above the first hit of similar meaning
const rt9_simHead = (t, prev) => t.similar && !prev?.similar ? `<div class="ghead rt9simh">${esc(tr('Similar meaning'))}</div>` : '';

// ---- Administration > Server: the switch and the state of the service
function rt9_adminHtml(hint) {
  return `<h4 id="s-rt9-h">${tr('Related tasks')}</h4>
    ${hint(tr('Shows tasks of similar meaning in a task, a hint on likely duplicates while adding and “also similar meaning” in the search; agents get them too. A small local model on this server computes them (the optional service kalmido-embed); nothing leaves the server.'))}
    <div id="s-rt9" aria-labelledby="s-rt9-h"><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
async function rt9_adminDraw(md) {
  const box = $('#s-rt9', md); if (!box) return;
  let j; try { j = await rawFetch('GET', '/api/admin/related'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  if (!j.configured) { box.innerHTML = `<div class="shint keep">${ic('alert', 's')} ${esc(tr('Off: the embedding service is not set up (KALMIDO_EMBED_URL), see SELF-HOSTING.md.'))}</div>`; return; }
  const st = j.reachable ? [tr('Service reachable'), j.model ? tr('Model: {0}', j.model) : '', tr('{0} tasks computed, {1} waiting', fmtNum(j.done), fmtNum(j.open))].filter(Boolean).join(' · ') : tr('Service not reachable');
  box.innerHTML = `<div class="featgrid"><label class="wide"><input type="checkbox" id="s-rt9-on" ${j.on ? 'checked' : ''}><span>${esc(tr('Show related tasks'))}<small class="muted">${esc(st)}</small></span></label></div>`;
  if (!box._rt9) {
    box._rt9 = true;
    box.addEventListener('change', async e => {
      if (e.target.id !== 's-rt9-on') return;
      const on = e.target.checked;
      try { await rawFetch('PUT', '/api/admin/related', {on}); RT9.on = null; RT9.ask = null; RT9.cache.clear(); toast(tr('Saved')); rt9_adminDraw(md); }
      catch { e.target.checked = !on; toast(tr('Offline: only works again with a connection')); }
    });
  }
}
