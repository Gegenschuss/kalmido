// @ts-check
// 2.153.0 (#2031): "Let the agent draft an answer" at an incoming document (letterdoc.js ltd_slot shows lta_docBtn).
// The slot fills itself: GET /api/office/letters/doc/<id>/agents names the agents the document is shared with (office admins
// only; nothing shown otherwise). A press (with several agents: a choice) sends the event letter_draft_requested; the agent
// writes the draft through its API and a card arrives in the person's chat with it. Nothing is shared automatically.
'use strict';
const LTA = {id: null, d: null, seq: 0, at: 0};
function lta_docBtn(d) {
  if (typeof officeOn === 'function' && !officeOn()) return '';
  if (LTA.id !== d.id || Date.now() - LTA.at > 30000) { if (LTA.id !== d.id) LTA.d = null; LTA.id = d.id; LTA.at = Date.now(); lta_load(); }  // fresh after a share
  return `<div class="lta-slot">${lta_html()}</div>`;
}
async function lta_load() {
  const id = LTA.id, seq = ++LTA.seq;
  let j = null; try { j = await rawFetch('GET', `/api/office/letters/doc/${id}/agents`); } catch { j = null; }
  if (seq !== LTA.seq) return;
  LTA.d = j; const el = $('.lta-slot'); if (el) el.innerHTML = lta_html();
}
function lta_html() {
  const j = LTA.d; if (!j) return '';
  if (j.data?.length) return `<button type="button" class="btn sm" data-lta="ask">${ic('bot', 's')} ${tr('Let an agent draft the answer')}</button>`;
  return j.others ? `<p class="muted lta-hint">${tr('An agent can draft the answer once you share the document with it.')}</p>` : '';
}
async function lta_ask() {
  const id = LTA.id, ags = LTA.d?.data || []; if (!ags.length) return;
  const one = ags.length === 1;
  const html = `${one ? `<p>${esc(tr('{0} drafts an answer to this document. You check and send it.', ags[0].name))}</p>`
    : `<label for="lta-ag">${tr('Agent')}</label><select id="lta-ag">${ags.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select>
       <p class="muted">${tr('The agent drafts an answer to this document. You check and send it.')}</p>`}
    <label for="lta-note">${tr('Note for the agent (optional)')}</label><textarea id="lta-note" rows="3" maxlength="1000"></textarea>`;
  let pick = null;
  const ok = await askDialog(/** @type {any} */ ({title: tr('Let an agent draft the answer'), html, ok: tr('Ask the agent'),
    after: md => md.querySelector('form').addEventListener('submit', () => {
      pick = {agent_id: one ? ags[0].id : +$('#lta-ag', md).value, note: $('#lta-note', md).value.trim()};
    }, true)}));
  if (!ok || !pick) return;
  try { await api('POST', `/api/office/letters/doc/${id}/ask-agent`, pick); } catch { return; }
  const name = ags.find(a => a.id === pick.agent_id)?.name || '';
  toast(tr('{0} was asked to draft an answer. The draft arrives in your chat with the agent and in the correspondence.', name));
}
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest('[data-lta="ask"]'); if (!b) return;
  e.preventDefault(); lta_ask();
});
