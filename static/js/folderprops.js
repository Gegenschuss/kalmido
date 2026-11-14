// @ts-check
/* Kalmido web client: the settings dialog of a folder (folderPropsModal: name, colour, defaults of its projects) (2.1156.0, #4280: moved here from sidebar.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

// 2.41.0 (#1423): like the list dialog: switches (a third state "Not set" for a folder), every change saved at once with
// "Saved · Undo", the same texts and order as the list's agent part. The agents themselves are chosen in the Share dialog
// (several per folder, #1420); here their switches, with a link there. "Apply to" stays: the existing lists follow or not.
async function folderPropsModal(f, opt = {}) {
  let info, ags = null;
  try { [info, ags] = await Promise.all([api('GET', '/api/folders/props?folder=' + encodeURIComponent(f)), collab() && agentsOn() ? api('GET', '/api/folders/agents?folder=' + encodeURIComponent(f)).catch(() => null) : null]); } catch { return; }
  const p = {...(info.props || {})}, inh = info.inherited || {};
  const ownN = (info.lists || []).filter(l => l.own.length).length, nL = (info.lists || []).length;
  const agNames = () => ags ? (ags.agents.length ? ags.agents : ags.inherited).map(a => a.name) : [];
  const hasAg = () => agNames().length > 0;
  const stTxt = k => k in p ? '' : inh[k] ? tr('As the folder above: {0}', folderValTxt(k, inh[k].value)) : tr('Not set (each project decides)');
  const effOn = k => k in p ? !!p[k] : !!inh[k]?.value;
  // a switch with a third state: not set (dimmed, says so) -> a tap sets it; "Not set" puts it back
  const fsw = (id, k, label, hint) => `<div class="fsw ${k in p ? '' : 'unset'}" data-fsw="${k}"><label class="chkl swl"><span class="swc"><input type="checkbox" role="switch" id="${id}" data-fk="${k}" ${effOn(k) ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${esc(label)}</span></label><span class="fsst muted">${esc(stTxt(k))}</span><button type="button" class="linkbtn fsclr" data-fsclr="${k}" ${k in p ? '' : 'hidden'}>${tr('Not set')}</button></div>${hint ? `<div class="shint aghint">${hint}</div>` : ''}`;
  const sel = (id, k, opts, dis = '') => `<div class="row"><label for="${id}">${tr(FP_KEYS[k])}</label><select id="${id}" data-fk="${k}" ${dis}><option value="">${esc(inh[k] ? tr('As the folder above: {0}', folderValTxt(k, inh[k].value)) : tr('Not set (each project decides)'))}</option>${opts.map(([v, n]) => `<option value="${esc(String(v))}" ${k in p && String(p[k] === true ? 1 : p[k] === false ? 0 : p[k]) === String(v) ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>`;
  // 2.757.0 (#4501): a number (hours per day, rate) and a value taken from one of my projects (columns, fields, tags)
  const fnum = (id, k, unit) => `<div class="row" data-fnum="${esc(k)}"><label for="${esc(id)}">${tr(FP_KEYS[k])}</label><input id="${esc(id)}" data-fk="${esc(k)}" data-fnumin="1" inputmode="decimal" value="${k in p ? esc(fmtNum(p[k])) : ''}" placeholder="${esc(stTxt(k))}" style="max-width:6.875rem"><span class="muted">${esc(unit)}</span><button type="button" class="linkbtn fsclr" data-fsclr="${esc(k)}" ${k in p ? '' : 'hidden'}>${tr('Not set')}</button></div>`;
  const cpLists = () => (S.lists || []).filter(l => isOwner(l) && !l.is_inbox && !l.archived).sort((a, b) => ((info.lists || []).some(x => x.id === b.id) - (info.lists || []).some(x => x.id === a.id)));
  const cpTxt = k => k in p ? folderValTxt(k, p[k]) : stTxt(k);
  const fcopy = (id, k) => `<div class="row" data-fcp="${esc(k)}"><label for="${esc(id)}">${tr(FP_KEYS[k])}</label><select id="${esc(id)}" data-fk="${esc(k)}" data-fcopy="1"><option value="">${esc(tr('Take from project…'))}</option>${cpLists().map(l => `<option value="${esc(String(l.id))}">${esc(lname(l))}</option>`).join('')}</select><button type="button" class="linkbtn fsclr" data-fsclr="${esc(k)}" ${k in p ? '' : 'hidden'}>${tr('Not set')}</button></div><div class="shint lhint fcpst" data-fcpst="${esc(k)}">${esc(cpTxt(k))}</div>`;
  // 2.37.0 (#1158): a folder without lists of my own (e.g. only lists others shared with me): the settings hold for new lists
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${ic('sliders', 's')} ${esc(tr('Folder settings “{0}”', fDisp(f)))}</h3><span class="ssaved" role="status" aria-live="polite"></span><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    ${nL ? '' : `<div class="shint cnote fsnone">${ic('info', 's')} ${tr('Applies to new projects in this folder. Shared projects of others keep their settings.')}</div>`}
    <p class="muted">${tr('Defaults for every project in the folder, also new ones. Projects changed on their own keep their value.')}</p>
    <div class="shint">${tr('“Not set” again: the projects keep the value they have.')}</div>
    ${wsOn() ? sel('fs-ws', 'org_id', [[0, wsName('private')], ...(S.me.workspaces || []).map(w => [w.id, w.name])]) : ''}
    ${sel('fs-pt', 'ptype', PTYPE_UI.filter(([k]) => k).map(([k, n]) => [k, tr(n)]))}<div class="shint lhint">${tr('New projects in the folder start with this type and its sections. Existing projects keep theirs.')}</div>${''/* 2.411.0 (#3516) */}
    ${collab() && agentsOn() ? `<h4 id="fs-ag-h">${tr('Agents')}</h4>
      <div class="row fsagrow"><label>${tr('Agent')}</label><span class="fsags" id="fs-ags">${esc(agNames().join(', ') || tr('No agent'))}</span><button type="button" class="linkbtn" data-m="share-ag">${ic('users', 's')} ${tr('In the Share dialog…')}</button></div>
      <div class="shint lhint">${tr('Which agents work in this folder you select in its Share dialog; the switches here are the defaults for its projects.')}</div>
      ${fsw('fs-am', 'agent_members', tr('Members may see and use the agent'), tr('Off: only you and project admins can chat with the agent, @mention it or assign it tasks here. Members still see what it does.') + (av_folderPersonal(f).length ? `<span class="avpers"> ${esc(av_personalHint(av_folderPersonal(f)))}</span>` : ''))}
      ${fsw('fs-af', 'agent_followup', tr('Agent follows up'), tr('Once a day the agent gets the tasks of this project that lie idle and asks about them in a comment or drafts a reminder. Nothing is sent to anyone outside. Off by default.'))}
      ${sel('fs-td', 'agent_tidy', TIDY.map(([k, n]) => [k, tr(n)]), hasAg() || 'agent_tidy' in p ? '' : 'disabled')}
      <div class="shint lhint" id="fs-tdhint">${hasAg() ? tr('Tidy up by: the agent of each project.') : tr('Add an agent in the Share dialog first.')}</div>
      ${fsw('fs-al', 'agent_listen', tr('Agent listens in'), tr('Off: the agent reacts only to an @mention, an assignment or a wake. Per agent in the Share dialog.'))}` : ''}
    <h4>${tr('Completed')}</h4>
    ${fsw('fs-hd', 'hide_done', tr('Hide completed'), '')}
    <div class="shint lhint fshdhint">${tr('Default for your projects in the folder. Shared projects of others and ones you changed yourself keep their setting.')}</div>
    ${typeof timeOn === 'function' && timeOn() ? `<h4>${tr('Time tracking')}</h4>${fsw('fs-tt', 'time_tracking', tr('Time tracking'), '')}${/*html-ok*/ fnum('fs-dayh', 'day_hours', 'h')}${/*html-ok*/ fnum('fs-rate', 'rate', S.settings.time_currency || '')/* #4501: fnum() escapes its values */}` : ''}
    <h4>${tr('Display and behaviour')}</h4>${''/* 2.757.0 (#4501): view, columns, fields, tags, reminder, progress bar */}
    ${/*html-ok*/ sel('fs-vw', 'view', [['list', tr('List')], ...(feat('kanban') ? [['kanban', tr('Kanban')]] : []), ...(feat('timeline') ? [['timeline', tr('Timeline')]] : [])])/* #4501: sel() escapes its options */}
    ${/*html-ok*/ fcopy('fs-cols', 'columns')}${/*html-ok*/ typeof fieldsOn === 'function' && fieldsOn() ? fcopy('fs-flds', 'fields') : ''}${/*html-ok*/ collab() ? fcopy('fs-tags', 'ltags') : ''/* #4501: fcopy() escapes ids and names */}
    <div class="shint lhint">${tr('Columns, custom fields and project tags are taken from one of your projects. Fields and tags the projects lack are added; nothing is removed, the values of the tasks stay.')}</div>
    ${/*html-ok*/ sel('fs-nag', 'nag', NAG_OPTS.map(([v, n]) => [v, tr(n)]))/* #4501: sel() escapes */}
    ${/*html-ok*/ progressOn() ? fsw('fs-pg', 'show_progress', tr('Show the progress bar'), '') : ''/* #4501: fsw() escapes */}
    ${collab() ? `<div class="row"><label>${tr('People')}</label><button type="button" class="btn sm" data-m="people">${ic('users', 's')} ${tr('Share…')}</button></div>` : ''}
    <div class="row"><label>${tr('Repository')}</label><button type="button" class="btn sm" data-m="repos">${ic('git', 's')} ${tr('Repository…')}</button></div>
    <fieldset class="fsapply" ${nL ? '' : 'hidden'}><legend>${tr('Apply to')}</legend>
      <label class="chkl"><input type="radio" name="fs-ap" value="all" ${nL ? 'checked' : ''}> ${trh('New projects and the {0} projects in the folder', nL)}</label>
      <label class="chkl"><input type="radio" name="fs-ap" value="new" ${nL ? '' : 'checked'}> ${tr('Only new projects')}</label>
      ${ownN ? `<label class="chkl"><input type="checkbox" id="fs-force"> ${esc(trn('Also the {0} project changed on its own', 'Also the {0} projects changed on their own', ownN))}</label>` : ''}</fieldset>
    <div class="fsprev" id="fs-prev" role="status" hidden></div>
    ${pbOn() ? pbAreaHtml('folder') : ''}
    <div class="foot">${collab() ? `<button class="btn" data-m="people">${ic('users', 's')} ${tr('Share…')}</button>` : ''}<span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);  // 2.910.0 (#5442): "Done" also as a sub-dialog (was "Back")
  md.classList.add('fsmodal');
  if (pbOn()) pbMount(md, {folder: f});  // 2.39.0 (#1168): the folder's playbook (saved on its own)
  const saved = undo => {
    const el = $('.ssaved', md); if (!el) return;
    el.innerHTML = `${ic('check', 's')}<span>${tr('Saved')}</span>${undo ? `<button type="button" class="linkbtn" data-m="fs-undo">${tr('Undo')}</button>` : ''}`;
    el.classList.add('on'); el._undo = undo;
    clearTimeout(el._t); el._t = setTimeout(() => { el.classList.remove('on'); el._undo = null; }, 6000);
  };
  const sync = k => {  // the row of key k shows what is saved now
    const row = $(`[data-fsw="${k}"]`, md);
    if (row) { row.classList.toggle('unset', !(k in p)); $('input', row).checked = effOn(k); $('.fsst', row).textContent = stTxt(k); $('.fsclr', row).hidden = !(k in p); return; }
    const fc = $(`[data-fcp="${k}"]`, md), fn = $(`[data-fnum="${k}"]`, md);  // 2.757.0 (#4501)
    if (fc) { $('select', fc).value = ''; $('.fsclr', fc).hidden = !(k in p); const st = $(`[data-fcpst="${k}"]`, md); if (st) st.textContent = cpTxt(k); return; }
    if (fn) { $('input', fn).value = k in p ? fmtNum(p[k]) : ''; $('.fsclr', fn).hidden = !(k in p); return; }
    const s = $(`select[data-fk="${k}"]`, md); if (s) s.value = k in p ? String(p[k] === true ? 1 : p[k] === false ? 0 : p[k]) : '';
  };
  const put = async (k, v, undo = true) => {
    const prev = k in p ? p[k] : null, er = $('#fs-prev', md);
    const body = {folder: f, props: {[k]: v}, apply: $('[name="fs-ap"]:checked', md)?.value || 'all', ...($('#fs-force', md)?.checked ? {force: true} : {})};
    let r; try { r = await api('PUT', '/api/folders/props', body); } catch { sync(k); return; }
    if (v === null) delete p[k]; else p[k] = r.props && k in r.props ? r.props[k] : v;  // 2.757.0 (#4501): {from: id} -> the stored value
    sync(k);
    const bad = (r.lists || []).filter(l => l.skipped.length || l.own.length);
    er.innerHTML = bad.length ? `<b>${esc(trn('{0} project does not follow:', '{0} projects do not follow:', bad.length))}</b><ul>${bad.map(l => `<li>${esc(l.name)}: ${esc([...l.skipped.map(x => `${tr(FP_KEYS[x.key])} – ${x.reason}`), ...l.own.map(x => tr('{0} changed on its own', tr(FP_KEYS[x])))].join('; '))}</li>`).join('')}</ul>` : '';
    er.hidden = !bad.length;
    saved(undo ? () => put(k, prev, false) : null);
    if (v === null && nL) toast(tr('Not set: the projects keep the value they have.'));
    else if (r.changed) toast(tmm_msg(trn('{0} project changed', '{0} projects changed', r.changed), r));  // 2.46.1 (#1422): the counter; 2.363.3 (#3133): what the workspace change ended
    await load(); render();
  };
  md.addEventListener('change', (/** @type {any} */ e) => {
    const t = e.target, k = t.dataset?.fk; if (!k) return;
    e.stopPropagation();
    if (t.type === 'checkbox') { put(k, t.checked).then(() => { if (k === 'agent_members' && t.checked && av_folderPersonal(f).length) toast(tr('Saved') + ' · ' + av_personalHint(av_folderPersonal(f)), undefined, 9000); }); return; }  // 2.46.6 (#1680)
    if (t.dataset.fcopy) { if (t.value) put(k, {from: +t.value}); return; }  // 2.757.0 (#4501)
    if (t.dataset.fnumin) { put(k, t.value.trim() === '' ? null : numBody(t.value)); return; }
    put(k, t.value === '' ? null : ['agent_tidy', 'ptype', 'view', 'nag'].includes(k) ? t.value : +t.value);  // 2.411.0 (#3516): ptype is a key; 2.757.0 (#4501): view, nag
  });
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.fsclr) { put(b.dataset.fsclr, null); return; }
    if (b.dataset.m === 'fs-undo') { const el = $('.ssaved', md); const u = el?._undo; if (u) { el.classList.remove('on'); el._undo = null; u(); } return; }
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'people' || b.dataset.m === 'share-ag') { if (opt.back) { md.remove(); return; } modalSub(md, () => folderShareModal(f, {back: true, ...(b.dataset.m === 'share-ag' ? {focus: 'agents'} : {})})); return; }
    if (b.dataset.m === 'repos') { modalSub(md, () => folderRepoModal(f, {back: true})); return; }  // 2.33.0 (#934)
  });
  // the Share dialog (opened over this one) may have changed the agents: their names and the tidy row follow
  md.addEventListener('focusin', async () => {
    if (!ags || md._agt > Date.now() - 1500) return; md._agt = Date.now();
    try { ags = await api('GET', '/api/folders/agents?folder=' + encodeURIComponent(f)); } catch { return; }
    const n = $('#fs-ags', md); if (n) n.textContent = agNames().join(', ') || tr('No agent');
    const td = $('#fs-td', md); if (td) td.disabled = !(hasAg() || 'agent_tidy' in p);
    const h = $('#fs-tdhint', md); if (h) h.textContent = hasAg() ? tr('Tidy up by: the agent of each project.') : tr('Add an agent in the Share dialog first.');
  });
  return md;
}
