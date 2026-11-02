/* Kalmido web client: 2.63.0 B (#1513) customer reports in the task panel. A task that came in through a form with a status
   link has a ticket (GET /timeline: ticket): the box "Client report" (who reported it, the address and the status link
   for people who may change the task, mails to the customer on / off), the composer's switch "To the client" (off by
   default = internal) and the marks of the comments the customer sees ("to the client", "Customer"). A public comment
   stays public (the customer may have it by mail already); deleting works as before.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const PTL = {on: {}};  // task id -> the composer's switch "To the client" (per task, until the comment is sent)
const ptl_ticket = t => t && S.tl.id === t.id ? S.tl.ticket || null : null;
function ptl_boxHtml(t) {
  const k = ptl_ticket(t); if (!k) return '';
  const cl = k.client_name ? ` · <a href="#client/${k.client_id}">${esc(k.client_name)}</a>` : '';
  const acts = k.can_write ? `<div class="ptlacts"><button type="button" class="btn sm" data-ptl="copy">${ic('link', 's')} ${tr('Copy the status link')}</button>
    ${k.email ? `<label class="chkl ptlmail"><input type="checkbox" data-ptl="notify" ${k.notify ? 'checked' : ''}> ${tr('E-mails to the client')}</label>` : ''}</div>` : '';
  return `<section class="ptlbox" aria-label="${esc(tr('Client report'))}"><div class="ptlh">${ic('megaphone', 's')}<b>${tr('Client report')}</b><span class="muted">${esc(fmtWhen(k.created_at))}</span></div>
    <p class="ptlwho">${k.name ? esc(k.name) : `<span class="muted">${esc(tr('Without a name'))}</span>`}${k.email ? ` · <a href="mailto:${esc(k.email)}">${esc(k.email)}</a>` : ''}${cl}</p>${acts}</section>`;
}
function ptl_switchHtml(t) {
  const k = ptl_ticket(t); if (!k || !k.can_write) return '';
  const on = !!PTL.on[t.id];
  return `<button type="button" class="btn sm ptlsw ${on ? 'on' : ''}" data-ptl="switch" aria-pressed="${on}" title="${esc(on ? tr('The client sees this comment and gets it by e-mail') : tr('Internal: only the team sees this comment'))}">${ic(on ? 'globe' : 'eye', 's')} ${on ? tr('To the client') : tr('Internal')}</button>`;
}
// the mark next to the time of a public answer (a customer's own comment says "customer" in its name already, cv_who)
const ptl_mark = c => c.portal && c.user_id != null ? `<span class="rotag ptltag pub" title="${esc(tr('to the client'))}">${ic('globe', 's')}<span class="ptlt">${tr('to the client')}</span></span>` : '';
// called by drawTimeline (the ticket arrives with the comments): the box and the switch follow
function ptl_draw() {
  const t = taskById(S.sel); if (!t) return;
  const b = $('#d-ptl'); if (b) b.innerHTML = ptl_boxHtml(t);
  const w = $('#c-ptl'); if (w) w.innerHTML = ptl_switchHtml(t);
  const m = $('#c-mrep'); if (m) m.innerHTML = mrep_switchHtml(t);  // 2.393.2 B (#3375)
}
// sendComment: the flag of the comment being sent (then the switch goes back to internal)
function ptl_take(tid) { const on = !!PTL.on[tid] && !!S.tl.ticket && S.tl.id === tid; delete PTL.on[tid]; return on; }
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-ptl]'); if (!b || b.dataset.ptl === 'notify') return;
  const t = taskById(S.sel), k = ptl_ticket(t); if (!k) return;
  if (b.dataset.ptl === 'switch') { PTL.on[t.id] = !PTL.on[t.id]; ptl_draw(); $('#c-input')?.focus(); return; }
  if (b.dataset.ptl === 'copy') { try { await navigator.clipboard.writeText(k.url); toast(tr('Copied')); } catch { toast(tr('Copy failed')); } }
});
document.addEventListener('change', async e => {
  const b = e.target.closest('[data-ptl="notify"]'); if (!b) return;
  const tid = S.sel, to = b.checked;
  const put = v => async () => { const j = await api('PATCH', `/api/tasks/${tid}/ticket`, {notify: v}); if (S.tl.id === tid) { S.tl.ticket = j; ptl_draw(); } };
  try { await put(to)(); offerUndo(to ? tr('E-mails to the client on') : tr('E-mails to the client off'), histAdd({label: to ? tr('E-mails to the client on') : tr('E-mails to the client off'), undo: put(!to), redo: put(to)})); }
  catch { b.checked = !to; }
});
// the client's card (clientpage.js, block "Customer reports"): open ones first, each a link to its task
function ptl_clientHtml(c) {
  const ks = c.tickets || []; if (!ks.length) return '';
  const row = k => `<li><a class="linkbtn" href="#t/${k.task_id}">${ic('megaphone', 's')} ${esc(k.title)}</a><span class="muted"> · ${esc(fmtDayAbs(k.created_at.slice(0, 10)))} · ${k.done ? tr('Done') : tr('Open|report')}</span></li>`;
  return `<div class="ctsec"><h4>${tr('Client reports')}</h4><ul class="ctlinks ptlcl">${[...ks.filter(k => !k.done), ...ks.filter(k => k.done)].map(row).join('')}</ul></div>`;
}

// 2.393.2 B (#3375): a task that came in by e-mail has a reporter (GET /timeline: mail_reporter {address, may, e2e}): the
// composer's switch "Also by e-mail to the reporter" (off by default, back off after each comment; people who may change the
// task, hidden in a list with the lock and on a task with a client report, whose own switch answers the client)
const MREP = {on: {}};
function mrep_switchHtml(t) {
  const k = t && S.tl.id === t.id ? S.tl.mail_reporter : null; if (!k || !k.may || ptl_ticket(t)) return '';
  return `<label class="chkl mrepsw" title="${esc(tr('The reporter gets this comment by e-mail: {0}', k.address))}"><input type="checkbox" data-mrep="switch" ${MREP.on[t.id] ? 'checked' : ''}> ${tr('Also by e-mail to the reporter')}</label>`;
}
function mrep_take(tid) { const on = !!MREP.on[tid] && S.tl.id === tid && !!S.tl.mail_reporter?.may; delete MREP.on[tid]; return on; }
function mrep_done(v) { toast(!v || v === 'sent' ? tr('Sent to the reporter by e-mail') : tr('The comment is saved, but the e-mail to the reporter was not sent')); }
document.addEventListener('change', e => {
  const b = e.target.closest('[data-mrep="switch"]'); if (!b || !S.sel) return;
  MREP.on[S.sel] = b.checked;
});
