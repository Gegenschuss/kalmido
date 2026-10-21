/* Kalmido web client: 2.71.0 A (#1457) -- rules of a list ("When ... then ..."). A section "Rules" in the list settings
   (owner and list admins only): one sentence per rule, a switch, edit / delete (one undo step), "Add rule" -> a small dialog
   Name, When [trigger][value], Then [action][value]. A rule runs with the rights of the person who set it up; a change made
   by a rule never triggers another rule (server: lists/rules.py). The history and comments show "Rule <name>".
   Also the proposal card of kind "rule" (an agent proposes, the person accepts / declines; agents.js propDraw).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const RUL = {};  // list id -> {rules, limit, available}
const RUL_TRIG = [['section', N_('A task comes into a column')], ['done', N_('A task is completed')], ['reopen', N_('A task is opened again')],
  ['ltag', N_('A task gets a list tag')], ['due', N_('The due date is reached')],
  // 2.138.0 D (#2060): + created, assigned, custom field changed
  ['created', N_('A task is created')], ['assigned', N_('A task is assigned')], ['field', N_('A custom field changes')]];
const RUL_ACT = [['assign', N_('Assign to')], ['due', N_('Set the due date')], ['comment', N_('Write a comment')], ['move', N_('Move to')],
  ['priority', N_('Set the priority')], ['tag', N_('Add a list tag')], ['field', N_('Set a custom field')]];  // 2.138.0 D (#2060)
const RX_PRIO = [['none', N_('None')], ['low', N_('Low')], ['medium', N_('Medium')], ['high', N_('High')]];
const RUL_DAYS = [0, 1, 2, 3, 7, 14, 30];
const rul_on = l => !!l && !l.is_inbox && l.life !== 'health' && canManage(l);
const rul_secs = lid => S.sections.filter(s => s.list_id === lid);
const rul_q = s => tr('“{0}”', s);
const rul_gone = () => tr('(deleted)');

function rul_trigText(r) {
  const t = r.trigger || {}, n = r.names || {};
  if (t.kind === 'section') return tr('a task comes into the column {0}', rul_q(n.section || rul_gone()));
  if (t.kind === 'done') return tr('a task is completed');
  if (t.kind === 'reopen') return tr('a task is opened again');
  if (t.kind === 'ltag') return tr('a task gets the tag {0}', rul_q(n.tag || rul_gone()));
  if (t.kind === 'created') return tr('a task is created');
  if (t.kind === 'assigned') return t.user_id ? tr('a task is assigned to {0}', n.trig_user || rul_gone()) : tr('a task is assigned to someone');
  if (t.kind === 'field') return rxTrigField(t, n);
  return tr('the due date of a task is reached');
}
function rul_dueText(d) {
  return d == null ? tr('remove its due date') : d === 0 ? tr('make it due today') : trn('make it due in {0} day', 'make it due in {0} days', d);
}
function rul_actText(r) {
  const a = r.action || {}, n = r.names || {};
  if (a.kind === 'assign') return tr('assign it to {0}', n.user || rul_gone());
  if (a.kind === 'due') return rul_dueText(a.days);
  if (a.kind === 'comment') return tr('comment {0}', rul_q((a.text || '').length > 60 ? a.text.slice(0, 59) + '…' : a.text || ''));
  if (a.kind === 'priority') return tr('set its priority to {0}', tr((RX_PRIO.find(x => x[0] === a.priority) || RX_PRIO[0])[1]));
  if (a.kind === 'tag') return tr('add the tag {0}', rul_q(n.tag_to || rul_gone()));
  if (a.kind === 'field') return rxActField(a, n);
  const where = [n.list, n.section_to].filter(Boolean).join(' › ') || (a.section_id ? rul_gone() : '');
  return tr('move it to {0}', where);
}
// 2.138.0 D (#2060): the sentences of the custom field trigger / action
function rxTrigField(t, n) {
  const f = rul_q(n.field || rul_gone());
  if (t.value == null) return tr('the field {0} changes', f);
  if (fieldById(t.field_id)?.type === 'checkbox' || t.value === '0') return t.value === '1' ? tr('the field {0} is checked', f) : tr('the field {0} is unchecked', f);
  return tr('the field {0} is set to {1}', f, rul_q(n.value || t.value));
}
function rxActField(a, n) {
  const f = rul_q(n.field_to || rul_gone());
  if (a.value == null) return tr('clear the field {0}', f);
  if (n.field_type === 'checkbox') return tr('check the field {0}', f);
  return tr('set the field {0} to {1}', f, rul_q(n.value_to || a.value));
}
const rxFields = lid => fieldsAll(lid).filter(f => !['formula', 'multiselect', 'task'].includes(f.type));  // 2.156.0 B (#2069): no rule sets a multiple choice / task link
const rxOpt = (v, n, cur) => `<option value="${esc(String(v))}" ${String(v) === String(cur ?? '') ? 'selected' : ''}>${esc(n)}</option>`;
function rxTrigValHtml(lid, fid, cur) {  // "set to" of a selection / checkbox field (else: any change)
  const f = fieldById(+fid); if (!f || !['select', 'checkbox'].includes(f.type)) return '';
  const os = f.type === 'checkbox' ? [['1', tr('Checked|checkbox')], ['0', tr('Unchecked|checkbox')]] : (f.options?.options || []).map(o => [o.id, o.name]);
  return `<label for="rul-tfv">${tr('Value')}</label><select id="rul-tfv">${rxOpt('', tr('Any change'), cur)}${os.map(([v, nm]) => rxOpt(v, nm, cur)).join('')}</select>`;
}
function rxActValHtml(l, fid, cur) {  // the fixed value, as the field type asks
  const f = fieldById(+fid); if (!f) return '';
  const lab = `<label for="rul-fval">${tr('Value')}</label>`, c = cur ?? '';
  if (f.type === 'checkbox') return lab + `<select id="rul-fval">${rxOpt('1', tr('Checked|checkbox'), c ? '1' : '')}${rxOpt('', tr('Unchecked|checkbox'), c ? '1' : '')}</select>`;
  if (f.type === 'select') return lab + `<select id="rul-fval">${rxOpt('', tr('Empty|value'), c)}${(f.options?.options || []).map(o => rxOpt(o.id, o.name, c)).join('')}</select>`;
  if (f.type === 'person') return lab + `<select id="rul-fval">${rxOpt('', tr('Empty|value'), c)}${listPeople(l).map(p => rxOpt(p.user_id, p.name, c)).join('')}</select>`;
  if (f.type === 'date') return lab + dateIn('rul-fval', c, {label: tr('Value')});
  return lab + `<input id="rul-fval" ${['number', 'currency', 'rating'].includes(f.type) ? 'inputmode="decimal"' : ''} maxlength="1000" value="${esc(String(c))}" placeholder="${esc(tr('Empty|value'))}">`;
}
const rul_sentence = r => tr('When {0}, then {1}.', rul_trigText(r), rul_actText(r));

// ---- the section in the list settings (dialogs.js listModal)
function rul_boxHtml(l) {
  if (!rul_on(l)) return '';
  return `<h4 title="${esc(tr('Automatic steps for the tasks of this list'))}">${tr('Rules')}</h4><div class="members rul-box" id="l-rules"><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
function rul_rowsHtml(lid) {
  const d = RUL[lid]; if (!d) return `<div class="muted mhint">${tr('Loading…')}</div>`;
  if (!d.available) return `<div class="muted mhint">${tr('Rules are not available in this list')}</div>`;
  const rows = d.rules.map(r => `<div class="mrow rul-row${r.active ? '' : ' off'}" data-rid="${r.id}">${ic('zap', 's')}
    <div class="rul-txt"><b>${esc(r.name)}</b><span class="muted">${esc(rul_sentence(r))}</span>${r.paused_text ? `<span class="rul-paused">${esc(tr('Paused: {0}', r.paused_text))}</span>` : ''}</div>
    <label class="rul-sw" title="${esc(tr('Active'))}"><input type="checkbox" data-rul-on="${r.id}" ${r.active ? 'checked' : ''} aria-label="${esc(tr('Active') + ': ' + r.name)}"></label>
    <button type="button" class="iconbtn" data-rul-edit="${r.id}" title="${esc(tr('Edit'))}" aria-label="${esc(tr('Edit') + ': ' + r.name)}">${ic('edit', 's')}</button>
    <button type="button" class="iconbtn" data-rul-del="${r.id}" title="${esc(tr('Delete'))}" aria-label="${esc(tr('Delete') + ': ' + r.name)}">${ic('trash', 's')}</button></div>`).join('');
  return rows + `<div class="mrow"><button type="button" class="btn sm" data-rul-add="1" ${d.rules.length >= d.limit ? 'disabled' : ''}>${ic('plus', 's')} ${tr('Add rule')}</button>${d.rules.length ? '' : `<span class="muted">${tr('Runs with your rights; a change made by a rule never starts another rule.')}</span>`}</div>`;
}
async function rul_load(lid) {
  const j = await api('GET', `/api/lists/${lid}/rules`);
  RUL[lid] = {rules: j.rules || [], limit: j.limit || 50, available: j.available !== false};
}
function rul_mount(md, l) {
  const box = $('#l-rules', md); if (!box || box._rul) return;
  box._rul = true;
  const lid = l.id, draw = () => { const b = $('#l-rules', md); if (b) b.innerHTML = rul_rowsHtml(lid); };
  rul_load(lid).then(draw).catch(() => { box.innerHTML = `<div class="muted mhint">${tr('Could not load the rules.')}</div>`; });
  box.addEventListener('change', async e => {
    const i = e.target.dataset.rulOn; if (!i) return;
    try { await api('PATCH', `/api/rules/${i}`, {active: e.target.checked}); await rul_load(lid); } catch { /* api() showed it */ }
    draw();
  });
  box.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    e.stopPropagation();
    const d = RUL[lid], find = id => d?.rules.find(r => r.id === +id);
    if (b.dataset.rulAdd) { rul_dialog(lid, null, draw); return; }
    if (b.dataset.rulEdit) { rul_dialog(lid, find(b.dataset.rulEdit), draw); return; }
    if (b.dataset.rulDel) {
      const r = find(b.dataset.rulDel); if (!r) return;
      try { await api('DELETE', `/api/rules/${r.id}`); } catch { return; }
      await rul_load(lid).catch(() => {}); draw();
      const again = async () => { await rul_load(lid).catch(() => {}); draw(); return {skipped: []}; };
      const h = histAdd({label: tr('Deleted the rule {0}', rul_q(r.name)), snaps: [], after: [], ids: [], lids: [lid],
        undo: async () => { await api('POST', `/api/rules/${r.id}/restore`); return again(); },
        redo: async () => { await api('DELETE', `/api/rules/${r.id}`); return again(); }});
      histToast(tr('Rule deleted'), h);
    }
  });
}

// ---- the dialog of one rule
function rul_targets(lid) {
  const l = listById(lid), org = l?.org_id || null;
  return [l, ...S.lists.filter(x => x.id !== lid && !x.archived && !x.is_inbox && x.life !== 'health' && (x.org_id || null) === org && canEditList(x.id))].filter(Boolean);
}
function rul_dialog(lid, r, done) {
  const l = listById(lid), t = r?.trigger || {kind: 'section'}, a = r?.action || {kind: 'assign'};
  const opt = (v, n, cur) => `<option value="${esc(String(v))}" ${String(v) === String(cur ?? '') ? 'selected' : ''}>${esc(n)}</option>`;
  const md = modal(`<h3>${r ? tr('Edit rule') : tr('New rule')}</h3>
    <div class="row"><label for="rul-name">${tr('Name')}</label><input id="rul-name" maxlength="80" value="${esc(r?.name || '')}" placeholder="${esc(tr('e.g. Review'))}"></div>
    <div class="row"><label for="rul-trig">${tr('When')}</label><select id="rul-trig">${RUL_TRIG.map(([k, n]) => opt(k, tr(n), t.kind)).join('')}</select></div>
    <div class="row" id="rul-tv"></div>
    <div class="row" id="rul-tv2" hidden></div>
    <div class="row"><label for="rul-act">${tr('Then|rule')}</label><select id="rul-act">${RUL_ACT.map(([k, n]) => opt(k, tr(n), a.kind)).join('')}</select></div>
    <div id="rul-av"></div>
    <div class="shint keep">${tr('The rule runs with your rights. A change made by a rule never starts another rule.')}</div>
    <div class="calerr" role="alert" id="rul-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('rul-dlg');
  const drawT = () => {
    const k = $('#rul-trig', md).value, x = $('#rul-tv', md);
    if (k === 'section') x.innerHTML = `<label for="rul-tsec">${tr('Column')}</label><select id="rul-tsec">${rul_secs(lid).map(s => opt(s.id, s.name, t.section_id)).join('') || opt('', tr('No columns yet'))}</select>`;
    else if (k === 'ltag') x.innerHTML = `<label for="rul-ttag">${tr('Tag')}</label><select id="rul-ttag">${listTags(lid).map(g => opt(g.id, g.name, t.tag_id)).join('') || opt('', tr('No list tags yet'))}</select>`;
    else if (k === 'assigned') x.innerHTML = `<label for="rul-tuser">${tr('Person')}</label><select id="rul-tuser">${opt('', tr('Anyone'), t.user_id)}${listPeople(l).map(p => opt(p.user_id, p.name, t.user_id)).join('')}</select>`;
    else if (k === 'field') x.innerHTML = `<label for="rul-tfld">${tr('Field')}</label><select id="rul-tfld">${rxFields(lid).map(f => opt(f.id, f.name, t.field_id)).join('') || opt('', tr('No custom fields yet'))}</select>`;
    else x.innerHTML = '';
    x.hidden = !x.innerHTML;
    drawTV();
  };
  const drawTV = () => {  // 2.138.0 D (#2060): the value of a field trigger
    const x = $('#rul-tv2', md), k = $('#rul-trig', md).value, fid = $('#rul-tfld', md)?.value;
    x.innerHTML = k === 'field' ? rxTrigValHtml(lid, fid, +fid === t.field_id ? t.value : '') : '';
    x.hidden = !x.innerHTML;
  };
  const drawA = (lst) => {
    const k = $('#rul-act', md).value, x = $('#rul-av', md);
    if (k === 'assign') x.innerHTML = `<div class="row"><label for="rul-user">${tr('Person')}</label><select id="rul-user">${listPeople(l).map(p => opt(p.user_id, p.name, a.user_id)).join('')}</select></div>`;
    else if (k === 'due') x.innerHTML = `<div class="row"><label for="rul-days">${tr('Due')}</label><select id="rul-days">${RUL_DAYS.map(d => opt(d, d ? trn('in {0} day', 'in {0} days', d) : tr('today'), a.days)).join('')}${opt('none', tr('No date|clear'), a.kind === 'due' && a.days == null ? 'none' : '')}</select></div>`;
    else if (k === 'comment') x.innerHTML = `<div class="row"><label for="rul-text">${tr('Comment')}</label><textarea id="rul-text" rows="3" maxlength="2000">${esc(a.text || '')}</textarea></div>`;
    else if (k === 'priority') x.innerHTML = `<div class="row"><label for="rul-prio">${tr('Priority')}</label><select id="rul-prio">${RX_PRIO.map(([v, n]) => opt(v, tr(n), a.priority || 'high')).join('')}</select></div>`;
    else if (k === 'tag') x.innerHTML = `<div class="row"><label for="rul-atag">${tr('Tag')}</label><select id="rul-atag">${listTags(lid).map(g => opt(g.id, g.name, a.tag_id)).join('') || opt('', tr('No list tags yet'))}</select></div>`;
    else if (k === 'field') {
      const fs = rxFields(lid), fid = lst || (a.kind === 'field' && a.field_id) || fs[0]?.id;
      x.innerHTML = `<div class="row"><label for="rul-afld">${tr('Field')}</label><select id="rul-afld">${fs.map(f => opt(f.id, f.name, fid)).join('') || opt('', tr('No custom fields yet'))}</select></div>
        <div class="row" id="rul-afv">${rxActValHtml(l, fid, a.kind === 'field' && +fid === a.field_id ? a.value : '')}</div>`;
    }
    else {
      const to = lst || a.list_id || lid;
      x.innerHTML = `<div class="row"><label for="rul-list">${tr('List')}</label><select id="rul-list">${rul_targets(lid).map(y => opt(y.id, y.id === lid ? tr('This list') : lname(y), to)).join('')}</select></div>
        <div class="row"><label for="rul-sec">${tr('Column')}</label><select id="rul-sec">${opt('', tr('No column'), a.section_id)}${rul_secs(+to).map(s => opt(s.id, s.name, a.section_id)).join('')}</select></div>`;
    }
  };
  drawT(); drawA();
  md.addEventListener('change', e => {
    if (e.target.id === 'rul-trig') drawT();
    if (e.target.id === 'rul-act') drawA();
    if (e.target.id === 'rul-list') drawA(+e.target.value);
    if (e.target.id === 'rul-tfld') drawTV();
    if (e.target.id === 'rul-afld') drawA(+e.target.value);
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m !== 'save') return;
    const tk = $('#rul-trig', md).value, ak = $('#rul-act', md).value, v = id => $('#' + id, md)?.value || '';
    const trig = {kind: tk, ...(tk === 'section' ? {section_id: +v('rul-tsec') || null} : tk === 'ltag' ? {tag_id: +v('rul-ttag') || null}
      : tk === 'assigned' ? {user_id: +v('rul-tuser') || null} : tk === 'field' ? {field_id: +v('rul-tfld') || null, value: v('rul-tfv') || null} : {})};
    const act = {kind: ak, ...(ak === 'assign' ? {user_id: +v('rul-user') || null} : ak === 'due' ? {days: v('rul-days') === 'none' ? null : +v('rul-days')}
      : ak === 'comment' ? {text: v('rul-text')} : ak === 'priority' ? {priority: v('rul-prio')} : ak === 'tag' ? {tag_id: +v('rul-atag') || null}
      : ak === 'field' ? {field_id: +v('rul-afld') || null, value: v('rul-fval').trim() || null} : {list_id: +v('rul-list') || lid, section_id: +v('rul-sec') || null})};
    const q = {name: v('rul-name').trim() || tr(RUL_TRIG.find(x => x[0] === tk)[1]), trigger: trig, action: act};
    b.disabled = true;
    try { await calReq(r ? 'PATCH' : 'POST', r ? `/api/rules/${r.id}` : `/api/lists/${lid}/rules`, q); }
    catch (x) { const er = $('#rul-err', md); er.textContent = x.message; er.hidden = false; b.disabled = false; return; }
    md.remove();
    await rul_load(lid).catch(() => {}); done?.();
    toast(r ? tr('Rule saved') : tr('Rule added'));
  });
  setTimeout(() => $('#rul-name', md)?.focus(), 50);
}

// ---- comments written by a rule (collab.js commentHtml)
const rul_cmtTag = c => c?.rule_name ? `<span class="rul-tag">${ic('zap', 's')}${esc(tr('Rule {0}', c.rule_name))}</span>` : '';

// ---- the proposal card (agents.js): an agent proposes a rule, the person accepts (👍) or declines (👎)
const rul_is = v => v?.kind === 'rule';
function rul_draw(v) {
  const p = v.proposal || {}, rv = v.rule_view;
  const main = `<div class="lyp-head"><span class="lyp-by">${esc(tr('Proposal by {0}', v.agent.name))}</span> · ${esc(v.list_name || '')}</div>
    ${p.summary ? `<div class="ppsum">${commentBody(p.summary, {})}</div>` : ''}
    ${rv ? `<div class="rul-prop">${ic('zap', 's')}<div class="rul-txt"><b>${esc(rv.name)}</b><span>${esc(rul_sentence(rv))}</span></div></div>` : ''}
    <div class="shint keep">${esc(tr('Accepting adds the rule to the list; it runs with your rights and belongs to you. Nothing else changes. One step, undo takes it back.'))}</div>`;
  const foot = `<button class="btn danger" data-pp="discard" aria-label="${esc(tr('Decline'))}">${thumbIc(false)} ${esc(tr('Decline'))}</button><span class="spacer"></span>
    <button class="btn" data-pp="close">${tr('Close')}</button><button class="btn pri" data-pp="apply" aria-label="${esc(tr('Accept'))}">${thumbIc(true)} ${esc(tr('Accept'))}</button>`;
  return {main, foot};
}
const rul_toast = v => tr('Rule {0} added', rul_q(v.proposal?.rule?.name || ''));
