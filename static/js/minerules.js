// @ts-check
/* Kalmido web client: 2.823.0 (#4773) -- the person's own rules of "My tasks" (view menu > Rules…; module minerules, loaded
   on demand). A rule only moves a task inside the person's own view: into one of the own sections, at the top or the end. It
   never changes the task, its project or the project's order, sees only what "My tasks" shows and runs once per task and
   occasion: what the person moves by hand afterwards stays. The server decides and moves (kalmido/tasks/minerules.py); the
   app sends the shown tasks (mineorder.js mrApply). The topmost rule that holds wins. At most 20.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const MR = {rules: [], limit: 20};
const MR_TRIG = [['before', N_('Some days before the due date')], ['today', N_('Due today')], ['now', N_('Due today or overdue')], ['overdue', N_('Overdue')],
  ['new', N_('Newly assigned to me')], ['prio', N_('Priority becomes high')], ['list', N_('From the project')], ['ltag', N_('Gets the project tag')]];
const MR_PRIO = [['none', N_('None')], ['low', N_('Low')], ['medium', N_('Medium')], ['high', N_('High')], ['urgent', N_('Urgent')]];
const mr_q = s => tr('“{0}”', s);
const mr_lists = () => (S.lists || []).filter(l => !l.archived && l.life !== 'health');
const mr_secs = () => mseList().filter(s => s.kind !== 'recent');
const mr_trigKey = t => t.kind === 'due' ? t.when || 'today' : t.kind;
const mr_tagName = (lid, id) => listTags(lid).find(g => g.id === id)?.name;

function mr_trigText(t) {
  const k = mr_trigKey(t), l = t.list_id ? listById(t.list_id) : null;
  if (k === 'before') return trn('a task is due in {0} day', 'a task is due in {0} days', t.days || 1);
  if (k === 'today') return tr('a task is due today');
  if (k === 'now') return tr('a task is due today or overdue');
  if (k === 'overdue') return tr('a task is overdue');
  if (k === 'new') return tr('a task is newly assigned to me');
  if (k === 'prio') return tr('the priority of a task becomes high');
  if (k === 'list') return tr('a task is in the project {0}', mr_q(l ? lname(l) : tr('(deleted)')));
  return tr('a task gets the tag {0}', mr_q((l && mr_tagName(l.id, t.tag_id)) || tr('(deleted)')));
}
function mr_condText(r) {
  const c = r.conditions || {}, xs = [];
  if (c.priority) xs.push(tr('the priority is {0}', tr((MR_PRIO.find(x => x[0] === c.priority) || MR_PRIO[0])[1])));
  if (c.list_id) { const l = listById(c.list_id); xs.push(tr('it is in the project {0}', mr_q(l ? lname(l) : tr('(deleted)')))); }
  if (c.tag_id) xs.push(tr('it has the tag {0}', mr_q(mr_tagName(c.tag_list_id, c.tag_id) || tr('(deleted)'))));
  return xs.join(', ');
}
function mr_sentence(r) {
  const s = mr_secs().find(x => x.id === r.section_id), where = s ? mr_q(mseName(s)) : tr('(deleted)');
  const c = mr_condText(r), then = r.place === 'bottom' ? tr('move it to the end of {0}', where) : tr('move it to the top of {0}', where);
  return tr('When {0}, {1}', mr_trigText(r.trigger || {}), then) + (c ? ' ' + tr('(only if {0})', c) : '');
}
function mr_title(r) { return r.name || (r.default ? tr('Due today or overdue to Now') : tr((MR_TRIG.find(x => x[0] === mr_trigKey(r.trigger || {})) || ['', N_('Rule')])[1])); }  // without a name: its trigger

async function mr_load() {
  const j = await api('GET', '/api/mine-rules');
  MR.rules = j.rules || []; MR.limit = j.limit || 20;
}
function mr_took(j) {  // an answer of a change: the rules, the sections (with the number of active rules), then run them at once
  if (j?.rules) MR.rules = j.rules;
  if (j?.mine_sections) mseFromState(j);
  mrSig = ''; render();
}
function mr_rowsHtml() {
  const n = MR.rules.length;
  const rows = MR.rules.map((r, i) => `<div class="mrow rul-row mr-row${r.active ? '' : ' off'}" data-rid="${/*html-ok*/ r.id}">${ic('zap', 's')}
    <div class="rul-txt"><b>${esc(mr_title(r))}</b><span class="muted">${esc(mr_sentence(r))}</span>${r.waiting ? `<span class="rul-paused">${esc(tr('Waiting: its section was deleted'))}</span>` : ''}</div>
    <label class="rul-sw" title="${esc(tr('Active'))}"><input type="checkbox" data-mr-on="${/*html-ok*/ r.id}" ${r.active ? 'checked' : ''} aria-label="${esc(tr('Active') + ': ' + mr_title(r))}"></label>
    ${i > 0 ? `<button type="button" class="iconbtn" data-mr-up="${/*html-ok*/ r.id}" title="${esc(tr('Move up'))}" aria-label="${esc(tr('Move up') + ': ' + mr_title(r))}">${ic('up', 's')}</button>` : ''}
    <button type="button" class="iconbtn" data-mr-edit="${/*html-ok*/ r.id}" title="${esc(tr('Edit'))}" aria-label="${esc(tr('Edit') + ': ' + mr_title(r))}">${ic('edit', 's')}</button>
    <button type="button" class="iconbtn" data-mr-del="${/*html-ok*/ r.id}" title="${esc(tr('Delete'))}" aria-label="${esc(tr('Delete') + ': ' + mr_title(r))}">${ic('trash', 's')}</button></div>`).join('');
  return (rows || `<div class="muted mhint">${tr('No rules yet.')}</div>`)
    + `<div class="mrow"><button type="button" class="btn sm" data-mr-add="1" ${n >= MR.limit ? 'disabled' : ''}>${ic('plus', 's')} ${tr('Add rule')}</button>${n >= MR.limit ? `<span class="muted">${esc(tr('At most {0} rules', MR.limit))}</span>` : ''}</div>`;
}

// the dialog "Rules" of My tasks: the list of rules, a switch, move up, edit, delete (Undo in the toast)
async function mr_open() {
  const md = /** @type {any} */ (modal(`<h3>${tr('Rules for My tasks')}</h3>
    <div class="shint">${tr('Rules only sort your own view: they move a task into one of your sections, the task itself never changes. What you move by hand stays where you put it. The topmost rule that applies wins.')}</div>
    <div class="members rul-box" id="mr-list"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`));
  md.classList.add('mr-dlg');
  const draw = () => { const b = $('#mr-list', md); if (b) b.innerHTML = mr_rowsHtml(); };
  try { await mr_load(); } catch { $('#mr-list', md).innerHTML = `<div class="muted mhint">${tr('Could not load the rules.')}</div>`; return; }
  draw();
  const call = async (method, url, b) => { try { const j = await api(method, url, b); mr_took(j); draw(); return j; } catch (e) { if (e?.status === 409 || e?.status === 404) { await mr_load().catch(() => {}); draw(); } return null; } };
  md.addEventListener('change', e => {
    const el = /** @type {any} */ (e.target), i = el.dataset?.mrOn; if (!i) return;
    const r = MR.rules.find(x => x.id === +i);
    call('PATCH', `/api/mine-rules/${i}`, {active: el.checked, ...(r ? {expect_updated_at: r.updated_at} : {})});
  });
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('button'); if (!b || !md.contains(b)) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const find = id => MR.rules.find(r => r.id === +id);
    if (b.dataset.mrAdd) { e.stopPropagation(); mr_dialog(null, draw); return; }
    if (b.dataset.mrEdit) { e.stopPropagation(); mr_dialog(find(b.dataset.mrEdit), draw); return; }
    if (b.dataset.mrUp) {
      e.stopPropagation();
      const ids = MR.rules.map(r => r.id), i = ids.indexOf(+b.dataset.mrUp); if (i < 1) return;
      ids.splice(i, 1); ids.splice(i - 1, 0, +b.dataset.mrUp);
      call('PUT', '/api/mine-rules/order', {ids});
      return;
    }
    if (b.dataset.mrDel) {
      e.stopPropagation();
      const r = find(b.dataset.mrDel); if (!r) return;
      if (!await call('DELETE', `/api/mine-rules/${r.id}`, {expect_updated_at: r.updated_at})) return;
      toast(tr('Rule deleted'), () => call('POST', `/api/mine-rules/${r.id}/restore`, {}));
    }
  });
}

// the dialog of one rule: Name (optional), When [trigger][days | project | project + tag], Move into [section] [top | end],
// Only if [priority][project][tag]
function mr_dialog(r, done) {
  const t = r?.trigger || {kind: 'due', when: 'now'}, cond = {...(r?.conditions || {})};
  const secs = mr_secs();
  if (!secs.length) { toast(tr('Make a section first')); return; }
  const opt = (v, n, cur) => `<option value="${esc(String(v))}" ${String(v) === String(cur ?? '') ? 'selected' : ''}>${esc(n)}</option>`;
  const any = tr('Any|condition'), lists = mr_lists();
  const listOpts = cur => lists.map(l => opt(l.id, lname(l), cur)).join('');
  const md = /** @type {any} */ (modal(`<h3>${r ? tr('Edit rule') : tr('New rule')}</h3>
    <div class="row"><label for="mr-name">${tr('Name')}</label><input id="mr-name" maxlength="80" value="${esc(r?.name || '')}" placeholder="${esc(tr('Optional'))}"></div>
    <div class="row"><label for="mr-trig">${tr('When')}</label><select id="mr-trig">${/*html-ok*/ MR_TRIG.map(([k, n]) => opt(k, tr(n), mr_trigKey(t))).join('')}</select></div>
    <div class="row" id="mr-tv" hidden></div>
    <div class="row" id="mr-tv2" hidden></div>
    <div class="row"><label for="mr-sec">${tr('Move into')}</label><select id="mr-sec">${/*html-ok*/ secs.map(s => opt(s.id, mseName(s), r?.section_id ?? secs[0].id)).join('')}</select></div>
    <div class="row"><label for="mr-place">${tr('Place')}</label><select id="mr-place">${/*html-ok*/ opt('top', tr('At the top'), r?.place || 'top')}${/*html-ok*/ opt('bottom', tr('At the end'), r?.place)}</select></div>
    <details class="rul-cond" id="mr-cond" ${Object.keys(cond).filter(k => k !== 'tag_list_id').length ? 'open' : ''}><summary>${tr('Only if')}</summary>
      <div class="row"><label for="mr-cprio">${tr('Priority')}</label><select id="mr-cprio">${/*html-ok*/ opt('', any, cond.priority)}${/*html-ok*/ MR_PRIO.map(([v, n]) => opt(v, tr(n), cond.priority)).join('')}</select></div>
      <div class="row"><label for="mr-clist">${tr('Project')}</label><select id="mr-clist">${/*html-ok*/ opt('', any, cond.list_id)}${/*html-ok*/ listOpts(cond.list_id)}</select></div>
      <div class="row" id="mr-ctagrow"></div>
    </details>
    <div class="shint">${tr('Only your own view changes. Each rule moves a task once per occasion.')}</div>
    <div class="calerr" role="alert" id="mr-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`));
  md.classList.add('rul-dlg', 'mr-edit');
  const tagSel = (id, lid, cur, empty) => {
    const tg = lid ? listTags(+lid) : [];
    return `<label for="${/*html-ok*/ id}">${tr('Tag')}</label><select id="${/*html-ok*/ id}">${/*html-ok*/ empty ? opt('', empty, cur) : ''}${/*html-ok*/ tg.map(g => opt(g.id, g.name, cur)).join('') || (empty ? '' : opt('', tr('No project tags yet')))}</select>`;
  };
  const drawT = () => {
    const k = $('#mr-trig', md).value, x = $('#mr-tv', md), y = $('#mr-tv2', md);
    if (k === 'before') x.innerHTML = `<label for="mr-days">${tr('Days')}</label><input id="mr-days" type="number" inputmode="numeric" min="1" max="30" step="1" value="${esc(String(t.days || 3))}"><span class="muted">${esc(tr('before the due date'))}</span>`;
    else if (k === 'list' || k === 'ltag') x.innerHTML = `<label for="mr-tlist">${tr('Project')}</label><select id="mr-tlist">${/*html-ok*/ listOpts(t.list_id)}</select>`;
    else x.innerHTML = '';
    x.hidden = !x.innerHTML;
    y.innerHTML = k === 'ltag' ? tagSel('mr-ttag', $('#mr-tlist', md)?.value, t.tag_id) : '';
    y.hidden = !y.innerHTML;
  };
  const drawC = () => {
    const lid = $('#mr-clist', md).value, row = $('#mr-ctagrow', md);
    row.innerHTML = lid ? tagSel('mr-ctag', lid, cond.tag_id, any) : '';
    row.hidden = !lid;
  };
  drawT(); drawC();
  setTimeout(() => $('#mr-trig', md)?.focus(), 50);
  md.addEventListener('change', e => {
    const el = /** @type {any} */ (e.target);
    if (el.id === 'mr-trig') drawT();
    else if (el.id === 'mr-tlist' && $('#mr-trig', md).value === 'ltag') { const y = $('#mr-tv2', md); y.innerHTML = tagSel('mr-ttag', el.value, null); }
    else if (el.id === 'mr-clist') drawC();
  });
  const err = m => { const x = $('#mr-err', md); x.textContent = m; x.hidden = !m; };
  md.addEventListener('click', async e => {
    const b0 = /** @type {any} */ (e.target).closest('[data-m]'); if (!b0) return;
    e.stopPropagation();
    if (b0.dataset.m === 'close') { md.remove(); return; }
    if (b0.dataset.m !== 'save') return;
    const k = $('#mr-trig', md).value, v = id => $('#' + id, md)?.value || '';
    const trigger = /** @type {any} */ (['before', 'today', 'now', 'overdue'].includes(k) ? {kind: 'due', when: k, ...(k === 'before' ? {days: +v('mr-days') || 0} : {})}
      : k === 'list' ? {kind: 'list', list_id: +v('mr-tlist') || null} : k === 'ltag' ? {kind: 'ltag', tag_id: +v('mr-ttag') || null} : {kind: k});
    if (k === 'before' && !(trigger.days >= 1 && trigger.days <= 30)) { err(tr('Days: 1 to 30')); return; }
    if (k === 'ltag' && !trigger.tag_id) { err(tr('Select a project tag')); return; }
    const conditions = {...(v('mr-cprio') ? {priority: v('mr-cprio')} : {}), ...(v('mr-clist') ? {list_id: +v('mr-clist')} : {}), ...(v('mr-clist') && v('mr-ctag') ? {tag_id: +v('mr-ctag')} : {})};
    const b = {name: v('mr-name').trim(), trigger, section_id: +v('mr-sec'), place: v('mr-place'), conditions, ...(r ? {expect_updated_at: r.updated_at} : {})};
    b0.disabled = true;
    try {
      const j = await rawFetch(r ? 'PATCH' : 'POST', r ? `/api/mine-rules/${r.id}` : '/api/mine-rules', b);
      md.remove(); mr_took(j); done?.();
      toast(r ? tr('Rule saved') : tr('Rule added'));
    } catch (x) {
      b0.disabled = false;
      err(x instanceof Offline ? tr('Offline: only works again with a connection') : x?.status === 409 ? tr('This rule was changed on another device. Its current state is shown in the list.') : x?.message || tr('Could not save.'));
      if (x?.status === 409 || x?.status === 404) { await mr_load().catch(() => {}); done?.(); }
    }
  });
}
