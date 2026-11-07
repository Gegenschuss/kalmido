/* Kalmido web client: 2.71.0 A (#1457) -- rules of a list ("When ... then ..."). A section "Rules" in the list settings
   (owner and list admins only): one sentence per rule, a switch, edit / delete (one undo step), "Add rule" -> a small dialog
   Name, When [trigger][value], Then [action][value]. A rule runs with the rights of the person who set it up; a change made
   by a rule never triggers another rule (server: lists/rules.py). The history and comments show "Rule <name>".
   Also the proposal card of kind "rule" (an agent proposes, the person accepts / declines; agents.js propDraw).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const RUL = {};  // list id -> {rules, limit, available}
const RUL_TRIG = [['section', N_('A task comes into a column')], ['done', N_('A task is completed')], ['reopen', N_('A task is opened again')],
  ['ltag', N_('A task gets a project tag')], ['due', N_('The due date is reached')],
  // 2.138.0 D (#2060): + created, assigned, custom field changed
  ['created', N_('A task is created')], ['assigned', N_('A task is assigned')], ['field', N_('A custom field changes')]];
const RUL_ACT = [['assign', N_('Assign to')], ['due', N_('Set the due date')], ['comment', N_('Write a comment')], ['move', N_('Move to')],
  ['priority', N_('Set the priority')], ['tag', N_('Add a project tag')], ['field', N_('Set a custom field')],  // 2.138.0 D (#2060)
  ['done', N_('Mark it as done')], ['reopen', N_('Open it again')]];  // 2.633.0 (#4781)
const RX_PRIO = [['none', N_('None')], ['low', N_('Low')], ['medium', N_('Medium')], ['high', N_('High')], ['urgent', N_('Urgent')]];
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
  if (t.days && t.when === 'overdue') return trn('a task is overdue for {0} day', 'a task is overdue for {0} days', t.days);  // 2.637.0 (#4768)
  if (t.days) return trn('a task is due in {0} day', 'a task is due in {0} days', t.days);
  return tr('the due date of a task is reached');
}
function rul_dueText(d) {
  return d == null ? tr('remove its due date') : d === 0 ? tr('make it due today') : trn('make it due in {0} day', 'make it due in {0} days', d);
}
// 2.637.0 (#4768): a chain of up to five actions ("A, B and C") and the conditions "only if"
const RUL_ACT_MAX = 5, RUL_DUE_OFF_MAX = 30;
const rul_acts = r => (r.actions?.length ? r.actions : [r.action || {}]);
function rul_actText(r) {
  const n = r.names || {}, xs = rul_acts(r).map((a, i) => rul_actOne(a, n.acts?.[i] || (i ? {} : n)));
  return xs.length > 1 ? tr('{0} and {1}', xs.slice(0, -1).join(', '), xs[xs.length - 1]) : xs[0];
}
function rul_condText(r) {
  const c = r.conditions || {}, n = r.names?.cond || {}, xs = [];
  if (c.priority) xs.push(tr('the priority is {0}', tr((RX_PRIO.find(x => x[0] === c.priority) || RX_PRIO[0])[1])));
  if (c.user_id) xs.push(tr('it is assigned to {0}', n.user || rul_gone()));
  if (c.tag_id) xs.push(tr('it has the tag {0}', rul_q(n.tag || rul_gone())));
  if (c.section_id) xs.push(tr('it is in the column {0}', rul_q(n.section || rul_gone())));
  return xs.join(', ');
}
function rul_actOne(a, n) {
  if (a.kind === 'assign') return tr('assign it to {0}', n.user || rul_gone());
  if (a.kind === 'due') return rul_dueText(a.days);
  if (a.kind === 'comment') return tr('comment {0}', rul_q((a.text || '').length > 60 ? a.text.slice(0, 59) + '…' : a.text || ''));
  if (a.kind === 'priority') return tr('set its priority to {0}', tr((RX_PRIO.find(x => x[0] === a.priority) || RX_PRIO[0])[1]));
  if (a.kind === 'tag') return tr('add the tag {0}', rul_q(n.tag_to || rul_gone()));
  if (a.kind === 'field') return rxActField(a, n);
  if (a.kind === 'done') return tr('mark it as done');  // 2.633.0 (#4781)
  if (a.kind === 'reopen') return tr('open it again');
  const where = [n.list, n.section_to].filter(Boolean).join(' › ') || (a.section_id ? rul_gone() : '');
  return tr('move it to {0}', where);
}
// 2.138.0 D (#2060): the sentences of the custom field trigger / action
function rxTrigField(t, n) {
  const f = rul_q(n.field || rul_gone());
  if (t.value == null) return tr('the field {0} changes', f);
  if (t.value === '*') return tr('the field {0} is filled', f);  // 2.473.0 (#3378)
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
function rxTrigValHtml(lid, fid, cur) {  // "set to" of a selection / checkbox field; 2.473.0 (#3378): every field but a checkbox: "is filled"
  const f = fieldById(+fid); if (!f) return '';
  const os = f.type === 'checkbox' ? [['1', tr('Checked|checkbox')], ['0', tr('Unchecked|checkbox')]] : [['*', tr('Filled|value')], ...(f.options?.options || []).map(o => [o.id, o.name])];
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
const rul_sentence = r => { const c = rul_condText(r); return c ? tr('When {0} and {1}, then {2}.', rul_trigText(r), c, rul_actText(r)) : tr('When {0}, then {1}.', rul_trigText(r), rul_actText(r)); };

// ---- the section in the list settings (dialogs.js listModal)
function rul_boxHtml(l) {
  if (!rul_on(l)) return '';
  return `<h4 title="${esc(tr('Automatic steps for the tasks of this project'))}">${tr('Rules')}</h4><div class="members rul-box" id="l-rules"><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
function rul_rowsHtml(lid) {
  const d = RUL[lid]; if (!d) return `<div class="muted mhint">${tr('Loading…')}</div>`;
  if (!d.available) return `<div class="muted mhint">${tr('Rules are not available in this project')}</div>`;
  const rows = d.rules.map(r => `<div class="mrow rul-row${r.active ? '' : ' off'}" data-rid="${r.id}">${ic('zap', 's')}
    <div class="rul-txt"><b>${esc(r.name)}</b><span class="muted">${esc(rul_sentence(r))}</span>${r.paused_text ? `<span class="rul-paused">${esc(tr('Paused: {0}', r.paused_text))}</span>` : ''}</div>
    <label class="rul-sw" title="${esc(tr('Active'))}"><input type="checkbox" data-rul-on="${r.id}" ${r.active ? 'checked' : ''} aria-label="${esc(tr('Active') + ': ' + r.name)}"></label>
    <button type="button" class="iconbtn" data-rul-edit="${r.id}" title="${esc(tr('Edit'))}" aria-label="${esc(tr('Edit') + ': ' + r.name)}">${ic('edit', 's')}</button>
    <button type="button" class="iconbtn" data-rul-del="${r.id}" title="${esc(tr('Delete'))}" aria-label="${esc(tr('Delete') + ': ' + r.name)}">${ic('trash', 's')}</button></div>`).join('');
  return rows + `<div class="mrow"><button type="button" class="btn sm" data-rul-add="1" ${d.rules.length >= d.limit ? 'disabled' : ''}>${ic('plus', 's')} ${tr('Add rule')}</button>${d.rules.length ? '' : `<span class="muted">${tr('Automatic, e.g.: a task that moves to “Review” is assigned to Anna.')}</span>`}</div>`;
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
  const l = listById(lid), t = r?.trigger || {kind: 'section'};
  const acts = (r ? rul_acts(r) : [{kind: 'assign'}]).map(x => ({...x}));  // 2.637.0 (#4768): up to five, block i has the ids rul-act-<i> (i = 0: rul-act)
  const cond = {...(r?.conditions || {})};
  const opt = (v, n, cur) => `<option value="${esc(String(v))}" ${String(v) === String(cur ?? '') ? 'selected' : ''}>${esc(n)}</option>`;
  const any = tr('Any|condition');
  const md = modal(`<h3>${r ? tr('Edit rule') : tr('New rule')}</h3>
    <div class="row"><label for="rul-name">${tr('Name')}</label><input id="rul-name" maxlength="80" value="${esc(r?.name || '')}" placeholder="${esc(tr('e.g. Review'))}"></div>
    <div class="row"><label for="rul-trig">${tr('When')}</label><select id="rul-trig">${RUL_TRIG.map(([k, n]) => opt(k, tr(n), t.kind)).join('')}</select></div>
    <div class="row" id="rul-tv"></div>
    <div class="row" id="rul-tv2" hidden></div>
    <details class="rul-cond" id="rul-cond" ${Object.keys(cond).length ? 'open' : ''}><summary>${tr('Only if')}</summary>
      <div class="row"><label for="rul-cprio">${tr('Priority')}</label><select id="rul-cprio">${opt('', any, cond.priority)}${RX_PRIO.map(([v, n]) => opt(v, tr(n), cond.priority)).join('')}</select></div>
      <div class="row"><label for="rul-cuser">${tr('Assigned to')}</label><select id="rul-cuser">${opt('', any, cond.user_id)}${listPeople(l).map(p => opt(p.user_id, p.name, cond.user_id)).join('')}</select></div>
      <div class="row"><label for="rul-ctag">${tr('Tag')}</label><select id="rul-ctag">${opt('', any, cond.tag_id)}${listTags(lid).map(g => opt(g.id, g.name, cond.tag_id)).join('')}</select></div>
      <div class="row"><label for="rul-csec">${tr('Column')}</label><select id="rul-csec">${opt('', any, cond.section_id)}${rul_secs(lid).map(x => opt(x.id, x.name, cond.section_id)).join('')}</select></div>
    </details>
    <div id="rul-acts"></div>
    <div class="row"><span class="lbl"></span><button type="button" class="btn sm" data-rul-addact="1">${ic('plus', 's')} ${tr('Add action')}</button></div>
    <div class="shint">${tr('The rule runs with your rights. A change made by a rule never starts another rule.')}</div>
    <div class="calerr" role="alert" id="rul-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('rul-dlg');
  if (!r) rul_tplMount(md, lid);  // 2.634.0 (#4774): the templates on top of a new rule
  const sx = i => (i ? '-' + i : '');
  const drawT = () => {
    const k = $('#rul-trig', md).value, x = $('#rul-tv', md);
    if (k === 'section') x.innerHTML = `<label for="rul-tsec">${tr('Column')}</label><select id="rul-tsec">${rul_secs(lid).map(s => opt(s.id, s.name, t.section_id)).join('') || opt('', tr('No columns yet'))}</select>`;
    else if (k === 'ltag') x.innerHTML = `<label for="rul-ttag">${tr('Tag')}</label><select id="rul-ttag">${listTags(lid).map(g => opt(g.id, g.name, t.tag_id)).join('') || opt('', tr('No project tags yet'))}</select>`;
    else if (k === 'assigned') x.innerHTML = `<label for="rul-tuser">${tr('Person')}</label><select id="rul-tuser">${opt('', tr('Anyone'), t.user_id)}${listPeople(l).map(p => opt(p.user_id, p.name, t.user_id)).join('')}</select>`;
    else if (k === 'field') x.innerHTML = `<label for="rul-tfld">${tr('Field')}</label><select id="rul-tfld">${rxFields(lid).map(f => opt(f.id, f.name, t.field_id)).join('') || opt('', tr('No custom fields yet'))}</select>`;
    else if (k === 'due') x.innerHTML = `<label for="rul-dwhen">${tr('Due date|rule')}</label><select id="rul-dwhen">${opt('before', tr('Before the due date'), t.when || 'before')}${opt('overdue', tr('Overdue|rule'), t.when)}</select>`;  // 2.637.0 (#4768)
    else x.innerHTML = '';
    x.hidden = !x.innerHTML;
    drawTV();
  };
  const drawTV = () => {  // 2.138.0 D (#2060): the value of a field trigger; 2.637.0 (#4768): the days of the due trigger
    const x = $('#rul-tv2', md), k = $('#rul-trig', md).value, fid = $('#rul-tfld', md)?.value;
    x.innerHTML = k === 'field' ? rxTrigValHtml(lid, fid, +fid === t.field_id ? t.value : '')
      : k === 'due' ? `<label for="rul-ddays">${tr('Days')}</label><input id="rul-ddays" type="number" inputmode="numeric" min="0" max="${RUL_DUE_OFF_MAX}" step="1" value="${esc(String(t.kind === 'due' ? t.days || 0 : 0))}"><span class="muted">${esc(tr('0 = on the due date'))}</span>` : '';
    x.hidden = !x.innerHTML;
  };
  const actHtml = (i, lst) => {
    const a = acts[i] || {kind: 'assign'}, k = a.kind, z = sx(i);
    let h;
    if (k === 'assign') h = `<div class="row"><label for="rul-user${z}">${tr('Person')}</label><select id="rul-user${z}">${listPeople(l).map(p => opt(p.user_id, p.name, a.user_id)).join('')}</select></div>`;
    else if (k === 'due') h = `<div class="row"><label for="rul-days${z}">${tr('Due')}</label><select id="rul-days${z}">${RUL_DAYS.map(d => opt(d, d ? trn('in {0} day', 'in {0} days', d) : tr('today'), a.days)).join('')}${opt('none', tr('No date|clear'), a.kind === 'due' && a.days == null ? 'none' : '')}</select></div>`;
    else if (k === 'comment') h = `<div class="row"><label for="rul-text${z}">${tr('Comment')}</label><textarea id="rul-text${z}" rows="3" maxlength="2000">${esc(a.text || '')}</textarea></div>`;
    else if (k === 'priority') h = `<div class="row"><label for="rul-prio${z}">${tr('Priority')}</label><select id="rul-prio${z}">${RX_PRIO.map(([v, n]) => opt(v, tr(n), a.priority || 'high')).join('')}</select></div>`;
    else if (k === 'tag') h = `<div class="row"><label for="rul-atag${z}">${tr('Tag')}</label><select id="rul-atag${z}">${listTags(lid).map(g => opt(g.id, g.name, a.tag_id)).join('') || opt('', tr('No project tags yet'))}</select></div>`;
    else if (k === 'field') {
      const fs = rxFields(lid), fid = lst || a.field_id || fs[0]?.id;
      h = `<div class="row"><label for="rul-afld${z}">${tr('Field')}</label><select id="rul-afld${z}">${fs.map(f => opt(f.id, f.name, fid)).join('') || opt('', tr('No custom fields yet'))}</select></div>
        <div class="row" id="rul-afv${z}">${rxActValHtml(l, fid, +fid === a.field_id ? a.value : '').replaceAll('rul-fval', 'rul-fval' + z)}</div>`;
    }
    else if (k === 'done' || k === 'reopen') h = '';  // 2.633.0 (#4781): no value
    else {
      const to = lst || a.list_id || lid;
      h = `<div class="row"><label for="rul-list${z}">${tr('Project')}</label><select id="rul-list${z}">${rul_targets(lid).map(y => opt(y.id, y.id === lid ? tr('This project') : lname(y), to)).join('')}</select></div>
        <div class="row"><label for="rul-sec${z}">${tr('Column')}</label><select id="rul-sec${z}">${opt('', tr('No column'), a.section_id)}${rul_secs(+to).map(s => opt(s.id, s.name, a.section_id)).join('')}</select></div>`;
    }
    const del = acts.length > 1 ? `<button type="button" class="iconbtn" data-rul-delact="${i}" title="${esc(tr('Remove action'))}" aria-label="${esc(tr('Remove action'))}">${ic('x', 's')}</button>` : '';
    return `<div class="rul-ablk" data-i="${i}"><div class="row"><label for="rul-act${z}">${i ? tr('And then|rule') : tr('Then|rule')}</label><select id="rul-act${z}">${RUL_ACT.map(([kk, n]) => opt(kk, tr(n), k)).join('')}</select>${del}</div>
      <div id="rul-av${z}">${h}</div></div>`;
  };
  const drawAll = () => {
    $('#rul-acts', md).innerHTML = acts.map((_, i) => actHtml(i)).join('');
    const ab = $('[data-rul-addact]', md); ab.disabled = acts.length >= RUL_ACT_MAX; ab.closest('.row').hidden = acts.length >= RUL_ACT_MAX;
  };
  const drawA = (i, lst) => {  // one block again (its kind / target list / field changed)
    const b = $(`.rul-ablk[data-i="${i}"]`, md); if (!b) return;
    acts[i] = {...acts[i], kind: $('#rul-act' + sx(i), md).value};
    b.outerHTML = actHtml(i, lst);
  };
  const read = i => {  // the action of block i as the dialog shows it
    const z = sx(i), ak = $('#rul-act' + z, md)?.value, v = id => $('#' + id + z, md)?.value || '';
    return {kind: ak, ...(ak === 'assign' ? {user_id: +v('rul-user') || null} : ak === 'due' ? {days: v('rul-days') === 'none' ? null : +v('rul-days')}
      : ak === 'comment' ? {text: v('rul-text')} : ak === 'priority' ? {priority: v('rul-prio')} : ak === 'tag' ? {tag_id: +v('rul-atag') || null}
      : ak === 'field' ? {field_id: +v('rul-afld') || null, value: v('rul-fval').trim() || null}
      : ak === 'done' || ak === 'reopen' ? {} : {list_id: +v('rul-list') || lid, section_id: +v('rul-sec') || null})};
  };
  const readAll = () => acts.forEach((_, i) => { acts[i] = read(i); });
  drawT(); drawAll();
  md.addEventListener('change', e => {
    const id = e.target.id || '', m = /^rul-(act|list|afld)(?:-(\d))?$/.exec(id), i = m ? +(m[2] || 0) : -1;
    if (id === 'rul-trig') drawT();
    if (id === 'rul-tfld') drawTV();
    if (m && m[1] === 'act') { acts[i] = {kind: e.target.value}; drawA(i); }
    if (m && m[1] !== 'act') { acts[i] = read(i); drawA(i, +e.target.value); }
  });
  md.addEventListener('click', async e => {
    const ad = e.target.closest('[data-rul-addact]'), dl = e.target.closest('[data-rul-delact]');
    if (ad) { readAll(); if (acts.length < RUL_ACT_MAX) acts.push({kind: 'comment'}); drawAll(); $(`#rul-act-${acts.length - 1}`, md)?.focus(); return; }
    if (dl) { readAll(); acts.splice(+dl.dataset.rulDelact, 1); drawAll(); return; }
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m !== 'save') return;
    const tk = $('#rul-trig', md).value, v = id => $('#' + id, md)?.value || '';
    const trig = {kind: tk, ...(tk === 'section' ? {section_id: +v('rul-tsec') || null} : tk === 'ltag' ? {tag_id: +v('rul-ttag') || null}
      : tk === 'assigned' ? {user_id: +v('rul-tuser') || null} : tk === 'field' ? {field_id: +v('rul-tfld') || null, value: v('rul-tfv') || null}
      : tk === 'due' ? {when: v('rul-dwhen') || 'before', days: Math.max(0, Math.min(RUL_DUE_OFF_MAX, parseInt(v('rul-ddays'), 10) || 0))} : {})};
    readAll();
    const conditions = {...(v('rul-cprio') ? {priority: v('rul-cprio')} : {}), ...(+v('rul-cuser') ? {user_id: +v('rul-cuser')} : {}),
      ...(+v('rul-ctag') ? {tag_id: +v('rul-ctag')} : {}), ...(+v('rul-csec') ? {section_id: +v('rul-csec')} : {})};
    const q = {name: v('rul-name').trim() || tr(RUL_TRIG.find(x => x[0] === tk)[1]), trigger: trig, actions: acts.slice(0, RUL_ACT_MAX), conditions};
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
    <div class="shint keep">${esc(tr('Accepting adds the rule to the project; it runs with your rights and belongs to you. Nothing else changes. Undo possible.'))}</div>`;
  const foot = `<button class="btn danger" data-pp="discard" aria-label="${esc(tr('Reject|proposal'))}">${thumbIc(false)} ${esc(tr('Reject|proposal'))}</button><span class="spacer"></span>
    <button class="btn" data-pp="close">${tr('Close')}</button><button class="btn pri" data-pp="apply" aria-label="${esc(tr('Accept|suggestion'))}">${thumbIc(true)} ${esc(tr('Accept|suggestion'))}</button>`;
  return {main, foot};
}
const rul_toast = v => tr('Rule {0} added', rul_q(v.proposal?.rule?.name || ''));

// ---- 2.634.0 (#4774): templates on top of the dialog of a new rule. A click fills the dialog (name, when, then); the person
// picks the column / person still open and saves: a normal rule, nothing stored as a template. Only triggers / actions the
// dialog offers (RUL_TRIG / RUL_ACT): a template whose kind is missing is not shown (e.g. the action "done" before #4781).
// Columns and tags are proposed by name (current language, English and German, case-insensitive); none fits = the field
// stays empty with "Select …" and saving asks for it.
const RUL_TPL = [
  {k: 'done_move', t: N_('Completed → move to {0}'), trig: {kind: 'done'}, act: {kind: 'move', sec: 'done'}},
  {k: 'reopen_move', t: N_('Opened again → move to {0}'), trig: {kind: 'reopen'}, act: {kind: 'move', sec: 'wip'}},
  {k: 'created_me', t: N_('Created → assign to me'), trig: {kind: 'created'}, act: {kind: 'assign', me: true}},
  {k: 'review_assign', t: N_('Comes into {0} → assign to a person'), trig: {kind: 'section', sec: 'review'}, act: {kind: 'assign'}},
  {k: 'due_prio', t: N_('Due today → priority high'), trig: {kind: 'due'}, act: {kind: 'priority', priority: 'high'}},
  {k: 'urgent_prio', t: N_('Gets the tag {0} → priority high'), trig: {kind: 'ltag', tag: 'urgent'}, act: {kind: 'priority', priority: 'high'}},
  {k: 'done_mark', t: N_('Comes into {0} → mark as done'), trig: {kind: 'section', sec: 'done'}, act: {kind: 'done'}},
];
// role -> the section keys of the project types (lists/templates.py PTYPES), translated + English, and German words
const RUL_TPL_NAMES = {review: ['Review'], done: ['Done|section'], wip: ['In progress'], approval: ['Approval'], billing: ['Billing'],
  production: ['Production'], urgent: ['Urgent']};
const RUL_TPL_DE = {review: ['Prüfung'], done: ['Fertig', 'Erledigt'], wip: ['In Arbeit'], approval: ['Abnahme', 'Freigabe'], billing: ['Abrechnung'],
  production: ['Umsetzung', 'Produktion'], urgent: ['Dringend']};
// project type -> the roles of a template's column, in the order tried; agency: Approval / Billing
const RUL_TPL_ROLES = {agency: {review: ['approval', 'review'], done: ['billing', 'done'], wip: ['production', 'wip']}};
const RUL_TPL_FIRST = ['review_assign', 'done_move', 'done_mark'];  // software / agency: review and done first
const rul_tplNorm = s => String(s || '').trim().toLocaleLowerCase();
function rul_tplFind(items, roles) {  // the first item whose name fits a name of the roles (in role order)
  for (const ro of roles) {
    const ns = new Set([...(RUL_TPL_NAMES[ro] || []).flatMap(n => [n.split('|')[0], tr(n)]), ...(RUL_TPL_DE[ro] || [])].map(rul_tplNorm));
    const hit = items.find(x => ns.has(rul_tplNorm(x.name)));
    if (hit) return hit;
  }
  return null;
}
function rul_tplList(lid) {  // the templates of a list: available kinds only, sorted by project type, with their proposals
  const l = listById(lid), pt = l?.ptype || '', has = (xs, k) => xs.some(x => x[0] === k);
  const roles = role => RUL_TPL_ROLES[pt]?.[role] || [role];
  const out = RUL_TPL.filter(tp => has(RUL_TRIG, tp.trig.kind) && has(RUL_ACT, tp.act.kind)).map(tp => {
    const sec = tp.trig.sec || tp.act.sec, s = sec ? rul_tplFind(rul_secs(lid), roles(sec)) : null;
    const g = tp.trig.tag ? rul_tplFind(listTags(lid), [tp.trig.tag]) : null;
    const nm = sec ? (s?.name || tr(RUL_TPL_NAMES[roles(sec)[0]][0])) : g?.name || tr(RUL_TPL_NAMES.urgent[0]);
    return {...tp, sec: s, tag: g, label: tr(tp.t, rul_q(nm))};
  });
  if (pt === 'software' || pt === 'agency') out.sort((x, y) => (RUL_TPL_FIRST.indexOf(x.k) + 1 || 99) - (RUL_TPL_FIRST.indexOf(y.k) + 1 || 99));
  return out;
}
function rul_tplMount(md, lid) {
  const tps = rul_tplList(lid), h = $('h3', md); if (!tps.length || !h) return;
  h.insertAdjacentHTML('afterend', `<div class="row rul-tpl"><span class="lbl">${tr('Templates')}</span><div class="mschips" role="group" aria-label="${esc(tr('Templates'))}">${tps.map(tp => `<button type="button" class="chip" data-rul-tpl="${tp.k}" aria-pressed="false">${esc(tp.label)}</button>`).join('')}</div></div>`);
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-rul-tpl]'); if (!b) return;
    const tp = tps.find(x => x.k === b.dataset.rulTpl); if (!tp) return;
    md.querySelectorAll('[data-rul-tpl]').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', String(x === b)); });
    rul_tplFill(md, lid, tp);
  });
  md.addEventListener('click', e => {  // capture: before the dialog's save, a field the template left open must be chosen
    const b = e.target.closest('[data-m="save"]'); if (!b) return;
    const open = [...md.querySelectorAll('select')].find(s => s.selectedOptions[0]?.dataset.rulPick);
    if (!open) return;
    e.stopImmediatePropagation(); e.preventDefault();
    const er = $('#rul-err', md); if (er) { er.textContent = open.selectedOptions[0].textContent; er.hidden = false; }
    open.focus();
  }, true);
}
function rul_tplFill(md, lid, tp) {
  const sel = id => $('#' + id, md);
  const kick = (id, v) => { const s = sel(id); if (!s) return; s.value = v; s.dispatchEvent(new Event('change', {bubbles: true})); };
  const pick = (id, v, why) => {  // the proposal, or an empty "Select …" entry
    const s = sel(id); if (!s) return;
    s.querySelector('[data-rul-pick]')?.remove();
    if (v != null && [...s.options].some(o => o.value === String(v))) { s.value = String(v); return; }
    s.insertAdjacentHTML('afterbegin', `<option value="" data-rul-pick="1">${esc(why)}</option>`);
    s.selectedIndex = 0;
  };
  sel('rul-name').value = tp.label.slice(0, 80);
  const er = sel('rul-err'); if (er) er.hidden = true;
  kick('rul-trig', tp.trig.kind);
  if (tp.trig.kind === 'section') pick('rul-tsec', tp.sec?.id, tr('Select a column'));
  if (tp.trig.kind === 'ltag') pick('rul-ttag', tp.tag?.id, tr('Select a tag'));
  kick('rul-act', tp.act.kind);
  if (tp.act.kind === 'assign') pick('rul-user', tp.act.me ? S.me?.id : null, tr('Select a person'));
  if (tp.act.kind === 'priority') sel('rul-prio').value = tp.act.priority;
  if (tp.act.kind === 'move') { kick('rul-list', String(lid)); pick('rul-sec', tp.sec?.id, tr('Select a column')); }
}
