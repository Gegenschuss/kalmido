// @ts-check
/* Kalmido web client: 2.623.0 (#4718) -- an agent's change of a core object as a proposal (kind "obj_patch"). The agent
   proposes new values for fields of an object it can see (POST /api/v1/agent/objects/<kind>/<id>/proposals); the proposal
   sheet of agents.js (propOpen / propDraw) shows for this kind the object, per field the value now -> the proposed one and
   the buttons Decline / Accept. Accepting writes the values AS THE PERSON with the version the agent read: changed by
   someone since = 409 with a plain message in the sheet, nothing written. One undo step takes it back (server:
   agents/objprop.py). Loaded on demand (lazyload.js LD_MODS objprop) the first time such a proposal opens.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const objp_is = v => v?.kind === 'obj_patch';
const objp_val = x => {
  const s = x === null || x === undefined || x === '' ? '' : typeof x === 'object' ? JSON.stringify(x) : String(x);
  return s ? esc(s.length > 300 ? s.slice(0, 300) + ' …' : s) : `<span class="muted">${esc(tr('(empty)'))}</span>`;
};
function objp_draw(v) {
  const p = v.proposal || {}, o = v.object, rows = v.changes || [];
  const gone = !o, stale = !!o?.stale, ro = o && !o.can_write;
  const what = o ? `${esc(o.label)}: <b>${esc(o.title || '#' + o.id)}</b>` : '';
  const list = rows.map(x => `<div class="ppi"><div class="ppb">
      <div class="muted">${esc(x.field)}</div>
      <div class="pprow"><s class="muted">${objp_val(x.now)}</s> ${ic('arrow', 's')} <b>${objp_val(x.after)}</b></div>
      ${stale && JSON.stringify(x.before) !== JSON.stringify(x.now) ? `<div class="ppn muted">${esc(tr('The agent saw: {0}', x.before === null || x.before === '' ? tr('(empty)') : String(x.before).slice(0, 120)))}</div>` : ''}
    </div></div>`).join('');
  const hint = gone ? tr('The object is no longer available to you.')
    : ro ? tr('You may only view this object, so you cannot accept the change.')
    : stale ? tr('Changed by someone else since the proposal: accepting is refused. Check the object and ask the agent again.')
    : tr('Accepting changes these fields as you, with the version the agent read. Nothing else changes. Undo possible.');
  const main = `<div class="lyp-head"><span class="lyp-by">${esc(tr('Proposal by {0}', v.agent.name))}</span>${what ? ' · ' + what : ''}</div>
    ${p.summary ? `<div class="ppsum">${commentBody(p.summary, {})}</div>` : ''}
    ${gone ? '' : `<div class="ppl">${list}</div>`}
    <div class="shint keep">${esc(hint)}</div>`;
  const off = gone || stale || ro;
  const foot = `<button class="btn danger" data-pp="discard" aria-label="${esc(tr('Reject|proposal'))}">${thumbIc(false)} ${esc(tr('Reject|proposal'))}</button><span class="spacer"></span>
    <button class="btn" data-pp="close">${tr('Close')}</button><button class="btn pri" data-pp="apply" ${off ? 'disabled' : ''} aria-label="${esc(tr('Accept|suggestion'))}">${thumbIc(true)} ${esc(tr('Accept|suggestion'))}</button>`;
  return {main, foot};
}
const objp_toast = (v, r) => trn('{0} field changed', '{0} fields changed', r.changed || 0);
