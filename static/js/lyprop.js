/* Kalmido web client: 2.55.0 (#1066) -- an agent proposes how a view is arranged, the person decides. The proposal sheet
   of agents.js (propOpen / propDraw) shows for kind "layout" a before / after of the view as two small schematic grids
   (block names and widths, never content), a tick "Use it right away" and 👍 Accept / 👎 Decline. Accepting stores it as a
   saved arrangement (#1069) and switches to it when ticked; one undo step takes it back (server: agents/lyprop.py).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const lyp_is = v => v?.kind === 'layout';
// planned jobs (agents.js SCHED_TPL): a template before "Own plan" -- the agent looks at the start page once a week
SCHED_TPL.splice(SCHED_TPL.findIndex(t => t.k === 'own'), 0,
  {k: 'lyprop', t: N_('Propose a better start page'), freq: 'weekly', days: [1], time: '08:30',
    p: N_('Look at how my start page is arranged (tools get_view_layout and list_layout_blocks, view dashboard, user_id = my id) and which lists I use most. Only if a clearly better arrangement exists (for example my favourites and what I use every day on top), send me ONE proposal (tool propose_layout) with a short reason. Never repeat one I declined. Change nothing yourself.')});
// the grid of one arrangement: the visible blocks in order (span = width in columns of six), the hidden ones below
function lyp_grid(lay, names, label, other) {
  if (!lay) return '';
  const hid = new Set(lay.hidden || []), vis = (lay.order || []).filter(k => !hid.has(k));
  const changed = k => other && ((other.widths || {})[k] !== (lay.widths || {})[k] || (other.order || []).filter(x => !(other.hidden || []).includes(x)).indexOf(k) !== vis.indexOf(k));
  const cell = k => { const w = [2, 3, 4, 6].includes(lay.widths?.[k]) ? lay.widths[k] : 6, h = [1, 3].includes(lay.heights?.[k]) ? lay.heights[k] : 2;
    return `<div class="lyp-c lyp-w${w} lyp-h${h}${changed(k) ? ' lyp-new' : ''}" title="${esc(names[k] || k)}"><span>${esc(names[k] || k)}</span></div>`; };
  const gone = (lay.order || []).filter(k => hid.has(k));
  return `<figure class="lyp-f"><figcaption>${esc(label)}</figcaption><div class="lyp-g" role="img" aria-label="${esc(label + ': ' + vis.map(k => names[k] || k).join(', '))}">${vis.map(cell).join('')}</div>
    ${gone.length ? `<div class="lyp-hid muted">${esc(tr('Hidden: {0}', gone.map(k => names[k] || k).join(', ')))}</div>` : ''}</figure>`;
}
function lyp_draw(v) {
  const p = v.proposal || {}, names = Object.fromEntries((v.blocks || []).map(b => [b.key, tr(b.name)]));
  const main = `<div class="lyp-head"><span class="lyp-by">${esc(tr('Proposal by {0}', v.agent.name))}</span> · ${esc(v.view_name || p.view || '')} · <b>${esc(p.name || '')}</b></div>
    ${p.summary ? `<div class="ppsum">${commentBody(p.summary, {})}</div>` : ''}
    <div class="lyp-ba">${lyp_grid(v.layout_now, names, tr('Before'))}${lyp_grid(p.proposed, names, tr('After'), v.layout_now)}</div>
    ${p.proposed?.mobile ? `<div class="shint">${esc(tr('Different on the phone'))}: ${esc(p.proposed.mobile.order.filter(k => !p.proposed.mobile.hidden.includes(k)).map(k => names[k] || k).join(', '))}</div>` : ''}
    <label class="ppshare lyp-use"><input type="checkbox" id="lyp-use" checked> ${esc(tr('Use it right away'))}</label>
    <div class="shint keep">${esc(tr('Accepting saves it as an arrangement of this view; nothing else changes. One step, undo takes it back.'))}${v.expires_at ? ' ' + esc(tr('Open until {0}', dayLabel(v.expires_at.slice(0, 10)))) : ''}</div>`;
  const foot = `<button class="btn danger" data-pp="discard" aria-label="${esc(tr('Decline'))}">👎 ${esc(tr('Decline'))}</button><span class="spacer"></span>
    <button class="btn" data-pp="close">${tr('Close')}</button><button class="btn pri" data-pp="apply" aria-label="${esc(tr('Accept'))}">👍 ${esc(tr('Accept'))}</button>`;
  return {main, foot};
}
// after accept / undo / redo: the view shows the new value (state reload; the project page loads its arrangement again)
async function lyp_after(v) {
  const key = v.proposal?.view || '';
  if (typeof lyv_reload === 'function') await Promise.resolve(lyv_reload(key)).catch(() => {});  // #1069 (lysets.js)
  if (key.startsWith('list:') && typeof povLoad === 'function' && S.povD?.[+key.slice(5)]) await Promise.resolve(povLoad(+key.slice(5), true)).catch(() => {});
}
const lyp_toast = (v, r) => r.used ? tr('Arrangement “{0}” in use', v.proposal?.name || '') : tr('Arrangement “{0}” saved', v.proposal?.name || '');
