/* Kalmido web client: 2.70.0 C (#1359) -- contracts in view. An agent that got the event contract_notice proposes ONE
   sentence about a contract's notice deadline; the proposal sheet of agents.js (propOpen / propDraw) shows for kind "notice"
   the contract (last day to cancel, end of the term, cost), the agent's sentence and the buttons Discard / Remind me / Take it
   as a note. Taking it writes the sentence as a comment on the contract task as the person ("Remind me": plus a reminder 3
   days before the last day to cancel); one undo step takes it back (server: agents/contractprop.py). Nothing is cancelled.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const ctr_is = v => v?.kind === 'notice';
function ctr_draw(v) {
  const p = v.proposal || {}, k = v.contract || v.input || {}, gone = v.contract === null;
  const cost = k.cost != null ? fmtMoney(k.cost) + ' ' + tr(PERIOD_WORD[k.per] || 'per month') + (k.per !== 'month' && k.monthly != null ? ` (${fmtMoney(k.monthly)} ${tr('per month')})` : '') : '';
  const fact = (label, val) => val ? `<div class="ctr-f"><span class="muted">${esc(label)}</span><b>${esc(val)}</b></div>` : '';
  const main = `<div class="ctr-head"><span class="ctr-by">${esc(tr('Proposal by {0}', v.agent.name))}</span> · <b>${esc(k.name || '')}</b>${k.provider ? ` · ${esc(k.provider)}` : ''}</div>
    <blockquote class="ctr-text">${esc(p.text || '')}</blockquote>
    ${gone ? `<div class="shint">${esc(tr('The contract is no longer available.'))}</div>` : `<div class="ctr-facts">
      ${fact(tr('Cancel by'), k.due ? fmtDateLoc(k.due) + (k.days != null ? ' · ' + daysWord(k.days) : '') : '')}
      ${fact(tr('Term ends'), k.ends ? fmtDateLoc(k.ends) : '')}
      ${fact(tr('Notice period'), noticeWord(k.notice, k.notice_unit))}
      ${fact(tr('Cost'), cost)}</div>`}
    <div class="shint keep">${esc(tr('Taking it adds the sentence as your note on the contract; nothing is cancelled or sent. One step, undo takes it back.'))}</div>`;
  const remind = !gone && v.contract?.can_remind ? `<button class="btn" data-pp="apply" data-ctr-remind="1">${ic('bell', 's')} ${esc(tr('Remind me'))}</button>` : '';
  const foot = `<button class="btn danger" data-pp="discard" aria-label="${esc(tr('Discard'))}">👎 ${esc(tr('Discard'))}</button><span class="spacer"></span>
    <button class="btn" data-pp="close">${tr('Close')}</button>${remind}<button class="btn pri" data-pp="apply" ${gone ? 'disabled' : ''}>${ic('check', 's')} ${esc(tr('Take it as a note'))}</button>`;
  return {main, foot};
}
const ctr_toast = (v, r) => r.reminder ? tr('Note added, reminder 3 days before') : tr('Note added to the contract');
