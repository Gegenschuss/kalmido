// @ts-check
// 2.235.0 B (#2902): the section "Data the agent never sees" of the agent dialog (awOpen in agentwork.js calls it with the dialog and the agent; it draws into its own container).
// Areas as switches (the fixed ones locked and greyed, the defaults marked), projects and tags to add / remove. Autosave: PATCH
// /api/agents/<id>/data-lock with only the changed part; the server enforces the lock in every read path of the agent (core/dlock.py).
const AWL_AREAS = [['mail', N_('Private e-mails')], ['contracts', N_('Contracts')], ['home', N_('Home & devices')], ['travel', N_('Private trips')],
  ['journal', N_('Journal')], ['mood', N_('Mood')], ['health', N_('Health')], ['budget', N_('Household budget')], ['reading', N_('Read later')]];
function awl_html(j) {
  const d = j.data_lock, always = new Set(j.always), def = j.defaults || {};
  const area = ([k, n]) => {
    const fixed = always.has(k), on = fixed || !!d.areas[k];
    const note = fixed ? tr('always') : def[k] ? tr('default') : '';
    return `<label class="chkl awl-a"><input type="checkbox" id="awl-a-${k}" data-awl-area="${k}" ${on ? 'checked' : ''} ${fixed ? 'disabled' : ''}> ${esc(tr(n))}${note ? ` <small class="muted">${esc(note)}</small>` : ''}</label>`;
  };
  const locked = new Set(d.lists.map(x => x.id)), tagsLow = new Set(d.tags.map(t => t.toLowerCase()));
  const lists = d.lists.map(x => `<div class="mrow awl-i"><span class="n">${esc(x.name ?? tr('A project you cannot see'))}</span><button type="button" class="iconbtn" data-awl-rmlist="${x.id}" aria-label="${esc(tr('Remove'))}" title="${esc(tr('Remove'))}">${ic('x', 's')}</button></div>`).join('');
  const tags = d.tags.map(t => `<div class="mrow awl-i"><span class="n">#${esc(t)}</span><button type="button" class="iconbtn" data-awl-rmtag="${esc(t)}" aria-label="${esc(tr('Remove'))}" title="${esc(tr('Remove'))}">${ic('x', 's')}</button></div>`).join('');
  const opts = j.options.lists.filter(x => !locked.has(x.id)).map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join('');
  return `<h4 id="awl-h">${esc(tr('Data the agent never sees'))}</h4>
    <div class="shint">${esc(tr('The agent cannot read, find or change these, not in events either. You still see everything.'))}</div>
    <div class="awl-areas" role="group" aria-labelledby="awl-h">${AWL_AREAS.map(area).join('')}</div>
    <div class="row"><label for="awl-addlist">${esc(tr('Projects'))}</label><select id="awl-addlist" data-awl-addlist="1"><option value="">${esc(tr('Add a project…'))}</option>${opts}</select></div>
    <div class="awl-l">${lists || `<div class="muted mhint">${esc(tr('No project locked.'))}</div>`}</div>
    <div class="row"><label for="awl-tagin">${esc(tr('Tags'))}</label><input id="awl-tagin" data-awl-tagin="1" list="awl-tagopts" autocomplete="off" maxlength="50" placeholder="${esc(tr('Add a tag…'))}"><button type="button" class="btn sm" data-awl-addtag="1">${esc(tr('Add'))}</button>
      <datalist id="awl-tagopts">${j.options.tags.filter(t => !tagsLow.has(t.toLowerCase())).map(t => `<option value="${esc(t)}"></option>`).join('')}</datalist></div>
    <div class="awl-l">${tags || `<div class="muted mhint">${esc(tr('No tag locked.'))}</div>`}</div>
    <div class="calerr" role="alert" id="awl-err" hidden></div>`;
}
/** @param {any} md @param {any} agent */
function awl_mount(md, agent) {
  const box = md.querySelector('#aw-lock'); if (!box) return;
  const url = `/api/agents/${agent.id}/data-lock`;
  let j = null, chain = Promise.resolve();
  const err = m => { const e = box.querySelector('#awl-err'); if (e) { e.textContent = m || ''; e.hidden = !m; } };
  const draw = () => { box.innerHTML = awl_html(j); };
  const save = (part, el, redraw) => chain = chain.then(async () => {
    err('');
    try { j = await api('PATCH', url, part); if (redraw) draw(); savedTick(redraw ? box.querySelector(redraw) : el); }
    catch (e) { err(e instanceof Offline ? tr('Only available online.') : e.message); if (j) draw(); }
  });
  const addTag = () => {
    const inp = /** @type {any} */ (box.querySelector('#awl-tagin')), t = (inp?.value || '').trim().replace(/^#+/, '').trim();
    if (!t) return;
    if (j.data_lock.tags.some(x => x.toLowerCase() === t.toLowerCase())) { inp.value = ''; return; }
    save({tags: [...j.data_lock.tags, t]}, inp, '#awl-tagin');
  };
  box.addEventListener('change', e => {
    const el = /** @type {any} */ (e.target);
    if (el.dataset.awlArea) save({areas: {[el.dataset.awlArea]: el.checked}}, el, '');
    else if (el.dataset.awlAddlist && el.value) save({lists: [...j.data_lock.lists.map(x => x.id), +el.value]}, el, '#awl-addlist');
  });
  box.addEventListener('click', e => {
    const t = /** @type {any} */ (e.target).closest('[data-awl-rmlist], [data-awl-rmtag], [data-awl-addtag]'); if (!t) return;
    if (t.dataset.awlAddtag) addTag();
    else if (t.dataset.awlRmlist) save({lists: j.data_lock.lists.map(x => x.id).filter(x => x !== +t.dataset.awlRmlist)}, t, '#awl-addlist');
    else save({tags: j.data_lock.tags.filter(x => x !== t.dataset.awlRmtag)}, t, '#awl-tagin');
  });
  box.addEventListener('keydown', e => {
    if (/** @type {any} */ (e).key === 'Enter' && /** @type {any} */ (e.target).dataset?.awlTagin) { e.preventDefault(); addTag(); }
  });
  api('GET', url).then(r => { j = r; draw(); }).catch(() => { box.innerHTML = ''; });  // 404 / offline: no section
}
