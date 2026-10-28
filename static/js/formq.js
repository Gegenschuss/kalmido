/* 2.98.0 B (#1954): questionnaires -- the own questions of a form (team/formq.py) in the form dialog of clients.js:
   add / change / delete questions (short / long text, choice, multiple choice, date, number, file, yes / no), required, a
   help text, the options of a choice; the order by dragging the grip (mouse and touch, pointer events) or with the up /
   down buttons (keyboard, WCAG 2.5.7). Switches: one question per step, the client by e-mail, unknown address = new client.
   The submissions (= the tasks the form made) with their answers in their own dialog, with a CSV download.
   The question list lives in the DOM of the dialog until Save (Cancel throws the changes away); a deleted question can be
   brought back from the message (Undo) until the dialog is saved. */
const FQ_KINDS = [['short', N_('Short text')], ['long', N_('Long text')], ['choice', N_('Choice (one)')], ['multi', N_('Choice (several)')],
  ['date', N_('Date')], ['number', N_('Number')], ['file', N_('File upload')], ['yesno', N_('Yes / no')]];
const fq_kindName = k => tr((FQ_KINDS.find(x => x[0] === k) || FQ_KINDS[0])[1]);

function fq_rowHtml(q) {
  const opts = q.kind === 'choice' || q.kind === 'multi';
  return `<div class="fqe" data-qid="${esc(q.id || '')}" data-k="${esc(q.kind)}">
    <button type="button" class="iconbtn fqe-grip" data-fq="grip" title="${esc(tr('Drag to reorder'))}" aria-label="${esc(tr('Drag to reorder'))}">${ic('grip', 's')}</button>
    <div class="fqe-main">
      <div class="fqe-top"><span class="fqe-kind">${esc(fq_kindName(q.kind))}</span><input class="fqe-label" maxlength="300" value="${esc(q.label || '')}" placeholder="${esc(tr('Question'))}" aria-label="${esc(tr('Question'))}"></div>
      <input class="fqe-help" maxlength="500" value="${esc(q.help || '')}" placeholder="${esc(tr('Help text (optional)'))}" aria-label="${esc(tr('Help text (optional)'))}">
      ${opts ? `<textarea class="fqe-opts" rows="3" placeholder="${esc(tr('One option per line'))}" aria-label="${esc(tr('Options'))}">${esc((q.options || []).join('\n'))}</textarea>` : ''}
      <label class="chkl"><input type="checkbox" class="fqe-req" ${q.required ? 'checked' : ''}> ${tr('Required')}</label>
    </div>
    <div class="fqe-btns"><button type="button" class="iconbtn" data-fq="up" title="${esc(tr('Move up'))}" aria-label="${esc(tr('Move up'))}">${ic('up', 's')}</button>
      <button type="button" class="iconbtn" data-fq="down" title="${esc(tr('Move down'))}" aria-label="${esc(tr('Move down'))}">${ic('down', 's')}</button>
      <button type="button" class="iconbtn" data-fq="del" title="${esc(tr('Delete question'))}" aria-label="${esc(tr('Delete question'))}">${ic('trash', 's')}</button></div></div>`;
}

// the part of the form dialog (f = the form, null = a new one)
function fq_dialogHtml(f) {
  const qs = f?.questions || [];
  return `<div class="fq-ed" id="fq-ed"><div class="fq-head"><b>${tr('Questions')}</b><span class="muted">${tr('Without own questions the form asks for subject and description.')}</span></div>
      <div class="fq-list" id="fq-list">${qs.map(fq_rowHtml).join('')}</div>
      <div class="fq-add"><select id="fq-kind" aria-label="${esc(tr('Kind of question'))}">${FQ_KINDS.map(([k, n]) => `<option value="${k}">${esc(tr(n))}</option>`).join('')}</select>
        <button type="button" class="btn sm" data-fq="add">${ic('plus', 's')} ${tr('Add question')}</button></div>
      <div class="row"><label>${tr('Appearance')}</label><label class="chkl"><input type="checkbox" id="fq-step" ${f?.one_per_step ? 'checked' : ''}> ${tr('One question per step (else all on one page)')}</label></div>
      <div class="row"><label>${tr('Client')}</label><span class="fq-chks"><label class="chkl"><input type="checkbox" id="fq-cm" ${f?.client_match ? 'checked' : ''}> ${tr('Match the e-mail to a client')}</label>
        <label class="chkl"><input type="checkbox" id="fq-cn" ${f?.client_new ? 'checked' : ''} ${f?.client_match ? '' : 'disabled'}> ${tr('Unknown address: create a new client')}</label></span></div>
      ${f ? fq_ckRowHtml(f) : ''}
      ${f ? `<div class="row"><label>${tr('Submissions')}</label><button type="button" class="btn sm" data-fq="entries">${ic('list', 's')} ${esc(trn('{0} sent', '{0} sent', f.count))}</button>
        <a class="btn sm" href="${esc(f.url)}" target="_blank" rel="noopener">${ic('eye', 's')} ${tr('Preview')}</a></div>` : ''}</div>`;
}

// 2.102.0 C (#2201): the link for one client (a client of the list's workspace): what is sent through it lands with this
// client, also without a known e-mail address (the server signs the client into the link and checks it on every send)
function fq_ckRowHtml(f) {
  const l = listById(f.list_id), org = l?.org_id || null;
  const cs = (S.clients || []).filter(c => !c.archived && (c.org_id || null) === org);
  if (!cs.length) return '';
  return `<div class="row fq-ck"><label for="fq-ckc">${tr('Link for a client')}</label><select id="fq-ckc"><option value="">${tr('Choose a client')}</option>${cs.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select>
      <button type="button" class="btn sm" data-fq="cklink">${ic('copy', 's')} ${tr('Copy link')}</button></div>
      <p class="muted mhint">${tr('What is sent through this link lands with the client, also without a known e-mail address.')}</p>`;
}
async function fq_ckCopy(url) {
  try { await navigator.clipboard.writeText(url); toast(tr('Copied')); } catch { toast(url, null, 8000); }
}
// a client's "…" menu (clientpage.js): the link of an open form of the client's workspace for this client (one form: copied
// at once, several: a menu with the forms)
async function fq_clientLink(c, anchor) {
  let j; try { j = await rawFetch('GET', `/api/clients/${c.id}/forms`); } catch (x) { toast(x.message || tr('Only available online.')); return; }
  if (!j.forms.length) { toast(tr('No open form in this workspace yet: create one in a project (… > Forms).')); return; }
  if (j.forms.length === 1) { fq_ckCopy(j.forms[0].url); return; }
  menu(anchor, j.forms.map(f => ({label: `${f.title} · ${f.list_name}`, icon: 'copy', fn: () => fq_ckCopy(f.url)})));
}

function fq_read(ed) {  // the questions as the server takes them
  return [...$$('#fq-list .fqe', ed)].map(r => {
    const q = {kind: r.dataset.k, label: $('.fqe-label', r).value.trim(), help: $('.fqe-help', r).value.trim(), required: $('.fqe-req', r).checked};
    if (r.dataset.qid) q.id = r.dataset.qid;
    const o = $('.fqe-opts', r); if (o) q.options = o.value.split('\n').map(x => x.trim()).filter(Boolean);
    return q;
  });
}

function fq_body(ed) {
  return {questions: fq_read(ed), one_per_step: $('#fq-step', ed).checked, client_match: $('#fq-cm', ed).checked, client_new: $('#fq-cm', ed).checked && $('#fq-cn', ed).checked};
}

function fq_bind(ed, f) {
  const list = $('#fq-list', ed);
  $('#fq-cm', ed).addEventListener('change', e => { const n = $('#fq-cn', ed); n.disabled = !e.target.checked; if (!e.target.checked) n.checked = false; });
  ed.addEventListener('click', e => {
    const b = e.target.closest('[data-fq]'); if (!b || b.dataset.fq === 'grip') return;
    const row = b.closest('.fqe'), k = b.dataset.fq;
    if (k === 'add') {
      if ($$('.fqe', list).length >= 30) { toast(tr('At most {0} questions per form', 30)); return; }
      const kind = $('#fq-kind', ed).value;
      list.insertAdjacentHTML('beforeend', fq_rowHtml({kind, label: '', options: kind === 'choice' || kind === 'multi' ? ['', ''] : undefined}));
      $('.fqe:last-child .fqe-label', list).focus();
    } else if (k === 'up' && row.previousElementSibling) { row.previousElementSibling.before(row); $('[data-fq="up"]', row).focus(); }
    else if (k === 'down' && row.nextElementSibling) { row.nextElementSibling.after(row); $('[data-fq="down"]', row).focus(); }
    else if (k === 'del') {
      const next = row.nextElementSibling, label = $('.fqe-label', row).value || fq_kindName(row.dataset.k);
      row.remove();
      toast(tr('Question “{0}” removed', label), () => { if (next && next.isConnected) next.before(row); else list.append(row); });
    } else if (k === 'entries') fq_entriesOpen(f);
    else if (k === 'cklink') {  // 2.102.0 C (#2201)
      const cid = +$('#fq-ckc', ed).value;
      if (!cid) { $('#fq-ckc', ed).focus(); toast(tr('Choose a client')); return; }
      rawFetch('GET', `/api/forms/${f.id}/client-link?client=${cid}`).then(j => fq_ckCopy(j.url), x => toast(x.message || tr('Only available online.')));
    }
  });
  // dragging by the grip: mouse, pen and touch alike (pointer events; the row follows the pointer's height; touch-action
  // none on the grip keeps the page from scrolling)
  list.addEventListener('pointerdown', e => {
    const g = e.target.closest('.fqe-grip'); if (!g || e.button) return;
    const row = g.closest('.fqe'); e.preventDefault();
    row.classList.add('dragging');  // the listeners sit on the document: moving the row in the DOM ends a pointer capture
    const move = ev => {
      const rows = [...$$('.fqe', list)].filter(r => r !== row);
      const after = rows.find(r => { const b = r.getBoundingClientRect(); return ev.clientY < b.top + b.height / 2; });
      if (after) { if (after.previousElementSibling !== row) after.before(row); } else if (list.lastElementChild !== row) list.append(row);
    };
    const dc = list.ownerDocument;
    const end = () => { row.classList.remove('dragging'); dc.removeEventListener('pointermove', move); dc.removeEventListener('pointerup', end); dc.removeEventListener('pointercancel', end); };
    dc.addEventListener('pointermove', move); dc.addEventListener('pointerup', end); dc.addEventListener('pointercancel', end);
  });
}

// the submissions of a form: newest first, the answers folded, the task one tap away, a CSV of all
async function fq_entriesOpen(f) {
  let j; try { j = await rawFetch('GET', `/api/forms/${f.id}/entries`); } catch (x) { toast(x.message || tr('Only available online.')); return; }
  const show = (q, v) => v == null || v === '' ? '—' : Array.isArray(v) ? v.join(', ') : q.kind === 'yesno' ? tr(v === 'yes' ? 'Yes' : 'No') : String(v);
  const row = en => `<details class="fqen"><summary><span class="n"><b>${esc(en.title)}</b> <span class="muted">${esc(fmtWhen(en.created_at))}${en.sender || en.email ? ' · ' + esc([en.sender, en.email].filter(Boolean).join(' ')) : ''}${en.client ? ' · ' + esc(en.client.name) + (en.client_typed ? ' (' + esc(tr('not confirmed')) + ')' : '') : ''}${en.done ? ' · ' + esc(tr('done')) : ''}</span></span></summary>
      <dl>${j.questions.map(q => `<dt>${esc(q.label)}</dt><dd>${esc(show(q, en.answers[q.id]))}</dd>`).join('')}</dl>
      <button type="button" class="btn sm" data-fq="task" data-tid="${en.task_id}">${ic('arrow', 's')} ${tr('Open task')}</button></details>`;
  const md = modal(`<div class="lhdr"><h3>${tr('Submissions')} · ${esc(f.title)}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="fq-entries">${j.entries.map(row).join('') || `<div class="muted mhint">${tr('Nothing sent yet.')}</div>`}</div>
    <div class="foot"><span class="spacer"></span>${j.entries.length ? `<a class="btn" href="/api/forms/${f.id}/entries.csv" download>${ic('download', 's')} CSV</a>` : ''}<button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-m],[data-fq]'); if (!b) return;
    if (b.dataset.m === 'close') md.remove();
    else if (b.dataset.fq === 'task') { $$('.modal').forEach(m => m.remove()); openTaskById(+b.dataset.tid); }  // the task in front: the form dialogs close
  });
}
