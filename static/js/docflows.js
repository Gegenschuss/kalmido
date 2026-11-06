// @ts-check
// 2.581.0 (#4803): document flows ("Abläufe") -- the rules of the documents with a trigger, filters and actions. Loaded with the
// documents (lazyload.js LD_MODS.docs). docs.js dc_sDraw draws the list and the form through dfl_ruleHtml / dfl_formHtml, its
// click handler sends the form through dfl_collect; the document sheet shows the runs with "Undo" (dfl_runs).
const DFL_TRIGGERS = [['received', N_('When a document comes in')], ['changed', N_('When a document is changed')], ['scheduled', N_('Some days after a date')]];
const DFL_ON = [['tags', N_('Tags')], ['type', N_('Document type')], ['sender', N_('Sender')], ['field', N_('Custom fields')]];
const DFL_FROM = [['date', N_('Date')], ['due', N_('Due')], ['added', N_('Added')]];
const DFL_SOURCES = [['upload', N_('Upload')], ['mail', N_('E-mail')], ['scan', N_('Scan inbox')], ['fetcher', N_('Receipt fetcher')], ['import', N_('Import')]];

function dfl_list(v) { return Array.isArray(v) ? v.join(', ') : (v || ''); }
function dfl_ruleHtml(r, can) {  // one flow in the list: trigger, filters, actions
  const kinds = typeof DC_KINDS !== 'undefined' ? DC_KINDS : [];
  const trig = r.trigger || 'received';
  const when = trig === 'scheduled' ? tr('{0} days after {1}', r.days || 0, tr(DFL_FROM.find(x => x[0] === r.from)?.[1] || 'Date'))
    : tr(DFL_TRIGGERS.find(x => x[0] === trig)?.[1] || trig) + (trig === 'changed' && r.on?.length ? ` (${r.on.map(o => tr(DFL_ON.find(x => x[0] === o)?.[1] || o)).join(', ')})` : '');
  const ifs = [r.match && `${tr(kinds.find(k => k[0] === r.kind)?.[1] || r.kind || '')} <b>${esc(r.match)}</b>${r.case ? ` (${tr('case-sensitive')})` : ''}`,
    r.sources?.length && `${tr('Source')}: ${esc(r.sources.map(s => tr(DFL_SOURCES.find(x => x[0] === s)?.[1] || s)).join(', '))}`,
    r.filename && `${tr('File name')}: ${esc(r.filename)}`, r.has_tags?.length && `${tr('has tag')}: ${esc(dfl_list(r.has_tags))}`,
    r.has_type && `${tr('Document type')} = ${esc(r.has_type)}`, r.has_sender && `${tr('Sender')} = ${esc(r.has_sender)}`].filter(Boolean);
  const does = [r.sender && `${tr('Sender')}: ${r.sender}`, r.type && `${tr('Document type')}: ${r.type}`, r.tags?.length && `${tr('Tags')}: ${dfl_list(r.tags)}`,
    r.folder && `${tr('Folder')}: ${r.folder}`, r.untag?.length && `${tr('Remove tags')}: ${dfl_list(r.untag)}`,
    r.fields && Object.keys(r.fields).length && `${tr('Custom fields')}: ${Object.entries(r.fields).map(([k, v]) => `${k} = ${v ?? ''}`).join(', ')}`,
    r.task && tr('Create task'), r.notify?.length && `${tr('Notify')}: ${r.notify.length}`, r.webhook && `${tr('Webhook')}: ${r.webhook}`].filter(Boolean);
  return `<li class="dc-rule${r.off ? ' muted' : ''}"><span>${r.name ? `<b>${esc(r.name)}</b> · ` : ''}<span class="muted">${esc(when)}</span>${ifs.length ? ` · ${ifs.join(' · ')}` : ''} → ${esc(does.join(' · '))}${r.off ? ` <span class="muted">(${tr('off')})</span>` : ''}</span>${can ? `<span>
    <button type="button" class="iconbtn" data-dcs="rtog:${r.id}" aria-label="${esc(r.off ? tr('Turn on') : tr('Turn off'))}" title="${esc(r.off ? tr('Turn on') : tr('Turn off'))}">${ic(r.off ? 'play' : 'pause')}</button>
    <button type="button" class="iconbtn" data-dcs="rdel:${r.id}" aria-label="${esc(tr('Delete rule'))}">${ic('trash')}</button></span>` : ''}</li>`;
}
function dfl_formHtml(s) {  // the form "New flow" (ids dcr-* as before for the words and the sorting)
  const kinds = typeof DC_KINDS !== 'undefined' ? DC_KINDS : [];
  const dl = (id, xs) => `<datalist id="${id}">${(xs || []).map(x => `<option value="${esc(x.name)}">`).join('')}</datalist>`;
  const row = (id, label, input) => `<div class="row"><label for="${id}">${label}</label>${input}</div>`;
  const inp = (id, max, extra = '') => `<input id="${id}" maxlength="${max}" autocomplete="off" ${extra}>`;
  const chk = (name, xs) => `<div class="row dfl-chk" role="group">${xs.map(([v, l]) => `<label class="chkl"><input type="checkbox" data-dfl="${name}" value="${esc(String(v))}"> ${esc(tr(l))}</label>`).join('')}</div>`;
  return `<details class="dc-radd dfl-add"><summary>${tr('New flow')}</summary>
    ${row('dfl-name', tr('Name'), inp('dfl-name', 120))}
    ${row('dfl-trig', tr('Trigger'), `<select id="dfl-trig" data-dcs="dfltrig">${DFL_TRIGGERS.map(([v, l]) => `<option value="${v}">${tr(l)}</option>`).join('')}</select>`)}
    <div class="dfl-t dfl-t-changed" hidden><p class="muted">${tr('Only when this changes (nothing chosen: any of them)')}</p>${chk('on', DFL_ON)}</div>
    <div class="dfl-t dfl-t-scheduled" hidden>${row('dfl-days', tr('Days after'), `<input id="dfl-days" type="number" min="0" max="3650" value="30">`)}
      ${row('dfl-from', tr('Date'), `<select id="dfl-from">${DFL_FROM.map(([v, l]) => `<option value="${v}">${tr(l)}</option>`).join('')}</select>`)}
      <p class="muted">${tr('Runs once per document and date, for dates from today on.')}</p></div>
    <h5>${tr('Filters')}</h5>
    ${row('dcr-kind', tr('If the document'), `<select id="dcr-kind">${kinds.map(([v, l]) => `<option value="${v}">${tr(l)}</option>`).join('')}</select>`)}
    ${row('dcr-match', tr('Words or pattern'), inp('dcr-match', 200, `placeholder="${esc(tr('empty: every document'))}"`))}
    <p class="muted">${tr('Source')}</p>${chk('src', DFL_SOURCES)}
    ${row('dfl-fn', tr('File name'), inp('dfl-fn', 200, `placeholder="${esc(tr('e.g. invoice*.pdf'))}"`))}
    ${row('dfl-htags', tr('has one of the tags'), inp('dfl-htags', 300, `list="dcr-gl" placeholder="${esc(tr('comma-separated'))}"`))}
    ${row('dfl-htype', tr('Document type is'), inp('dfl-htype', 120, 'list="dcr-tl"'))}
    ${row('dfl-hsender', tr('Sender is'), inp('dfl-hsender', 120, 'list="dcr-sl"'))}
    <h5>${tr('Actions')}</h5>
    ${row('dcr-sender', tr('then sender'), inp('dcr-sender', 120, 'list="dcr-sl"') + dl('dcr-sl', s.senders))}
    ${row('dcr-type', tr('then document type'), inp('dcr-type', 120, 'list="dcr-tl"') + dl('dcr-tl', s.types))}
    ${row('dcr-tags', tr('then tags'), inp('dcr-tags', 300, `list="dcr-gl" placeholder="${esc(tr('comma-separated'))}"`) + dl('dcr-gl', s.tags))}
    ${row('dfl-untag', tr('Remove tags'), inp('dfl-untag', 300, `list="dcr-gl" placeholder="${esc(tr('comma-separated'))}"`))}
    ${row('dcr-folder', tr('then folder'), inp('dcr-folder', 120, 'list="dcr-fl"') + `<datalist id="dcr-fl">${(s.folders || []).map(x => `<option value="${esc(x.path || x.name)}">`).join('')}</datalist>`)}
    ${(s.fields || []).length ? row('dfl-field', tr('Set custom field'), `<select id="dfl-field"><option value="">–</option>${s.fields.map(f => `<option value="${esc(f.name)}">${esc(f.name)}</option>`).join('')}</select><input id="dfl-fval" maxlength="500" autocomplete="off" aria-label="${esc(tr('Value'))}">`) : ''}
    <label class="chkl"><input type="checkbox" id="dfl-task"> ${tr('Create task')}</label>
    <div class="dfl-taskx" hidden>${row('dfl-ttitle', tr('Title'), inp('dfl-ttitle', 200, `placeholder="${esc(tr('e.g. Pay {sender}'))}"`))}
      <label class="chkl"><input type="checkbox" id="dfl-tdue"> ${tr('Due on the due date of the document')}</label></div>
    ${(s.people || []).length ? `<p class="muted">${tr('Notify')}</p>${chk('notify', (s.people || []).map(p => [p.id, p.name]))}` : ''}
    ${s.hooks ? row('dfl-hook', tr('Webhook'), inp('dfl-hook', 2000, 'type="url" placeholder="https://"')) : ''}
    <p class="muted">${tr('A flow never starts another one. Every run can be taken back in the document.')}</p>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-dcs="radd">${tr('Add flow')}</button></div></details>`;
}
function dfl_change(e) {  // the parts of the form for the chosen trigger / the task
  const md = e.target.closest('.dfl-add'); if (!md) return false;
  if (e.target.id === 'dfl-trig') { md.querySelectorAll('.dfl-t').forEach(x => { /** @type {HTMLElement} */ (x).hidden = !x.classList.contains('dfl-t-' + e.target.value); }); return true; }
  if (e.target.id === 'dfl-task') { const x = /** @type {HTMLElement|null} */ (md.querySelector('.dfl-taskx')); if (x) x.hidden = !e.target.checked; return true; }
  return false;
}
function dfl_collect(md, s) {  // the form -> the body of POST /api/docs/rules
  const v = id => (/** @type {HTMLInputElement|null} */ (md.querySelector('#' + id))?.value || '').trim();
  const on = name => [...md.querySelectorAll(`[data-dfl="${name}"]:checked`)].map(x => /** @type {HTMLInputElement} */ (x).value);
  const trig = v('dfl-trig') || 'received';
  const r = {ws: s.ws, name: v('dfl-name'), trigger: trig, kind: v('dcr-kind'), match: v('dcr-match'), sender: v('dcr-sender'), type: v('dcr-type'),
    tags: v('dcr-tags'), folder: v('dcr-folder'), untag: v('dfl-untag'), sources: on('src'), filename: v('dfl-fn'), has_tags: v('dfl-htags'),
    has_type: v('dfl-htype'), has_sender: v('dfl-hsender'), notify: on('notify').map(Number)};
  if (trig === 'changed') r.on = on('on');
  if (trig === 'scheduled') { r.days = +v('dfl-days') || 0; r.from = v('dfl-from') || 'date'; }
  if (v('dfl-field')) r.fields = {[v('dfl-field')]: v('dfl-fval')};
  if (/** @type {HTMLInputElement|null} */ (md.querySelector('#dfl-task'))?.checked) r.task = {title: v('dfl-ttitle'), due: !!(/** @type {HTMLInputElement|null} */ (md.querySelector('#dfl-tdue'))?.checked)};
  if (v('dfl-hook')) r.webhook = v('dfl-hook');
  return r;
}
function dfl_secret(sec) {  // a new webhook secret: shown once
  if (!sec) return;
  const md = modal(`<h3>${tr('Webhook secret')}</h3><p class="muted">${tr('The calls are signed with this secret (header X-Kalmido-Signature). It is shown only now.')}</p>
    <p><code class="dfl-sec">${esc(sec)}</code></p><div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-dfl="close">${tr('Close')}</button></div>`);
  md.addEventListener('click', e => { if (/** @type {HTMLElement} */ (e.target).closest('[data-dfl="close"]')) md.remove(); });
}
// ---- the document sheet: the runs of flows, each with "Undo"
const DFL_DID = {sender: N_('Sender'), type: N_('Document type'), folder: N_('Folder'), tags: N_('Tags'), fields: N_('Custom fields')};
async function dfl_runs(md, d) {
  const box = md.querySelector('.dc-flows'); if (!box || !d) return;
  let j; try { j = await api('GET', `/api/docs/${d.id}/flowruns`); } catch { return; }
  if (!box.isConnected || !j.runs.length) { box.innerHTML = ''; return; }
  box.innerHTML = `<details class="dc-text"><summary><h4>${tr('Flows')} (${j.runs.length})</h4>${ic('chev', 's dc-chev')}</summary><ul class="dc-rules">${j.runs.map(r => {
    const what = [...r.did.map(k => tr(DFL_DID[k] || k)), r.task_id && tr('Task'), r.told && tr('{0} notified', r.told), r.hook && tr('Webhook')].filter(Boolean).join(', ');
    return `<li class="dc-rule"><span>${esc(r.name || tr('Flow'))} <span class="muted">${esc(fmtWhen(r.at))} · ${esc(what)}${r.undone ? ` · ${tr('taken back')}` : ''}</span></span>${j.can_undo && !r.undone ? `<button type="button" class="btn sm" data-dflundo="${r.id}">${tr('Undo')}</button>` : ''}</li>`;
  }).join('')}</ul></details>`;
  if (!box._on) {
    box._on = true;
    box.addEventListener('click', async e => {
      const b = /** @type {HTMLElement} */ (e.target).closest('[data-dflundo]'); if (!b) return;
      try { await api('POST', `/api/docs/flowruns/${b.dataset.dflundo}/undo`); } catch { return; }
      toast(tr('Taken back'));
      if (typeof dc_open === 'function' && DC.doc) dc_open(DC.doc.id, {pane: !!md.classList.contains('dc-pane')});
    });
  }
}
