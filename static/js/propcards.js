// @ts-check
/* Kalmido web client: the review dialog of an agent's proposal (propOpen: select, edit, apply, discard) (2.1156.0, #4280: moved here from agents.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

const PROP_ST = {requested: N_('Waiting for the proposal'), ready: N_('Proposal ready'), applied: N_('Applied'), discarded: N_('Discarded')};
function propKeys(v) {
  const p = v.proposal; if (!p) return [];
  if (typeof sht_is === 'function' && sht_is(v)) return sht_keys(v);  // 2.126.1 B (#2125): the table rows that can still be carried over (sheetprop.js)
  if (pk2_is(v.kind)) return pk2_keys(v);  // 2.51.0 (#1351 #1358): propkinds2.js
  if (lyp_is(v) || rul_is(v)) return ['0'];  // 2.55.0 (#1066): one arrangement (lyprop.js); 2.71.0 A (#1457): one rule (rules.js)
  if (aim_is(v)) return aim_keys(v);  // 2.68.0 (#1839): the new rows of an import (importprop.js)
  if (dup_is(v)) return dup_keys(v);  // 2.70.0 B (#1357): the groups still mergeable (dupprop.js)
  if (ctr_is(v)) return ['0'];  // 2.70.0 C (#1359): one note (contractprop.js)
  if (typeof ast_is === 'function' && ast_is(v)) return ['0'];  // 2.126.1 A (#2123 #2124): one text (asstprop.js)
  if (typeof objp_is === 'function' && objp_is(v)) return ['0'];  // 2.623.0 (#4718): one change of an object (objprop.js)
  if (v.kind === 'project') return p.tasks.flatMap((t, i) => [String(i), ...t.subtasks.map((s, k) => `${i}.${k}`)]);
  if (v.kind === 'dayplan') return p.items.map((x, i) => String(i));  // 2.10.0 (#440); 2.11.0: "does not fit" entries change nothing
  return (v.kind === 'extract' ? p.tasks : p.items).map((x, i) => String(i));
}
async function propOpen(jid) {
  let v;
  try { v = await rawFetch('GET', `/api/proposals/${jid}`); } catch (e) {  // 2.5.2 (K19): a readable reason instead of "unknown"
    toast(e instanceof Offline ? tr('Offline: only works again with a connection') : e.status === 404 ? tr('This proposal is not available: only the person who asked for it can open it, or it was removed.') : e.message); return;
  }
  if (v?.kind === 'ideas') { await loadModule('mindmap').catch(() => {}); if (typeof mm_ideasOpen === 'function') mm_ideasOpen(v); return; }  // 2.156.0 A (#1201): ideas show in the mind map
  if (aim_is(v) && typeof ofcMoney !== 'function') await loadModule('office').catch(() => {});  // 2.68.0 (#1839, review): the preview uses the office module (lazy)
  if (ctr_is(v) && typeof noticeWord !== 'function') await loadModule('life').catch(() => {});  // 2.70.0 C (#1359): the card uses life.js (loaded on demand since 2.65.0)
  if (['office_text', 'doc_summary', 'report', 'receipt_read', 'card_statement_read', 'sheet_tasks'].includes(v?.kind) && (typeof ast_is !== 'function' || typeof sht_is !== 'function')) await loadModule('asstprop').catch(() => {});  // 2.126.1 A (#2123 #2124): asstprop.js on demand
  if (v?.kind === 'obj_patch' && typeof objp_is !== 'function') await loadModule('objprop').catch(() => {});  // 2.623.0 (#4718): objprop.js on demand
  if (v?.input?.assistant) v.agent = {...(v.agent || {}), name: tr('Assistant')};  // 2.75.0 (#1411): the built-in assistant, not an agent
  $('.ppm')?.remove();
  /** @type {any} */
  const md = modal('');
  md.classList.add('ppm');
  S.prop = {jid, v, md, sel: new Set(propKeys(v)), ed: {}};
  propDraw();
  md.addEventListener('input', (/** @type {any} */ e) => propEdit(e.target));
  // 2.139.0 D (#2401): the whole row is the tap target of its checkbox (not the title field, date button or links)
  md.addEventListener('click', (/** @type {any} */ e) => {
    const row = e.target.closest?.('.ppi'); if (!row || e.target.closest('input,button,a,select,textarea,label,.dp')) return;
    const cb = $('.ppc', row); if (cb && !cb.disabled) cb.click();
  });
  md.addEventListener('change', (/** @type {any} */ e) => {
    if (e.target.classList.contains('ppc')) {
      const k = e.target.closest('.ppi')?.dataset.k; if (k === undefined) return;
      const on = e.target.checked;
      on ? S.prop.sel.add(k) : S.prop.sel.delete(k);
      if (!k.includes('.')) $$(`.ppi[data-k^="${k}."]`, md).forEach(x => { const c = $('.ppc', x); c.checked = on; on ? S.prop.sel.add(x.dataset.k) : S.prop.sel.delete(x.dataset.k); x.classList.toggle('off', !on); });  // subtasks follow their task
      else if (on) { const p = k.split('.')[0]; S.prop.sel.add(p); const pr = $(`.ppi[data-k="${p}"]`, md); if (pr) { $('.ppc', pr).checked = true; pr.classList.remove('off'); } }
      e.target.closest('.ppi').classList.toggle('off', !on);
      propCount();
      return;
    }
    propEdit(e.target);
  });
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('[data-pp]'); if (!b) return;
    const a = b.dataset.pp;
    if (a === 'close') { md.remove(); S.prop = null; }
    if (a === 'all' || a === 'none') { S.prop.sel = new Set(a === 'all' ? propKeys(S.prop.v) : []); propDraw(); }
    if (a === 'discard') propDiscard();
    if (a === 'apply') propApply(b);
  });
}
function propEdit(el) {
  if (aim_propEdit(el)) return;  // 2.68.0 (#1839): tick / VAT of an import row (importprop.js)
  if (ap_propEdit(el)) return;  // 2.51.0 C (#1353 #1355): times / place of time and shoot proposals (agentplan.js)
  if (dup_edit(el)) return;  // 2.70.0 B (#1357): the main contact of a group (dupprop.js)
  const f = el.dataset?.f, row = el.closest?.('.ppi'); if (!f || !row || !S.prop) return;
  const k = row.dataset.k, v = el.value, e = S.prop.ed[k] ||= {};
  if (f === 'title') e.title = v.trim();
  else if (f === 'due') e.due = v || null;
  else if (f === 'section') e.section = v || null;
  else if (f === 'assignee_id') e.assignee_id = v ? +v : null;
  else if (f === 'list_id') {  // triage: another list -> its sections
    e.list_id = v ? +v : null; e.section_id = null;
    const s = $('[data-f="section_id"]', row); if (s) s.outerHTML = propSecSel(e.list_id, null);
  } else if (f === 'section_id') { e.section_id = v ? +v : null; if (!('list_id' in e)) e.list_id = +$('[data-f="list_id"]', row)?.value || null; }
}
function propSecSel(lid, sid) {
  const l = (S.prop.v.input.lists || []).find(x => x.id === lid);
  return `<select data-f="section_id" aria-label="${esc(tr('Section'))}" ${l && l.sections.length ? '' : 'hidden'}><option value="">${tr('No section')}</option>${(l?.sections || []).map(s => `<option value="${s.id}" ${s.id === sid ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>`;
}
function propItemsHtml() {
  const {v} = S.prop, p = v.proposal, inp = v.input;
  if (typeof sht_is === 'function' && sht_is(v)) return '';  // 2.126.1 B (#2125): sht_draw shows it
  if (pk2_is(v.kind)) return pk2_itemsHtml();  // 2.51.0 B (#1351 #1358): propkinds2.js
  if (lyp_is(v) || rul_is(v)) return '';  // 2.55.0 (#1066): lyp_draw shows it; 2.71.0 A: rul_draw
  if (dup_is(v)) return '';  // 2.70.0 B (#1357): dup_draw shows it
  if (ctr_is(v)) return '';  // 2.70.0 C (#1359): ctr_draw shows it
  if (typeof ast_is === 'function' && ast_is(v)) return '';  // 2.126.1 A (#2123 #2124): ast_draw shows it
  if (typeof objp_is === 'function' && objp_is(v)) return '';  // 2.623.0 (#4718): objp_draw shows it
  if (v.kind === 'dayplan') return propDayplanHtml();  // 2.10.0 (#440)
  if (v.kind === 'cleanup') return clnItemsHtml();  // 2.39.0 (#1151): cleanup.js
  if (AP_KINDS.includes(v.kind)) return ap_propItemsHtml();  // 2.51.0 C (#1353 #1355): agentplan.js
  if (v.kind === 'project') {
    const secOpts = cur => `<option value="">${tr('No section')}</option>${p.sections.map(s => `<option ${s === cur ? 'selected' : ''}>${esc(s)}</option>`).join('')}`;
    return p.tasks.map((t, i) => propItemHtml(String(i), t, {
      fields: p.sections.length ? `<select data-f="section" aria-label="${esc(tr('Section'))}">${secOpts(t.section)}</select>` : '',
      chips: propPrio(t.priority) + (t.depends_on.length ? `<span class="ppchip">${ic('deps', 's')}${esc(tr('blocked by {0}', t.depends_on.map(d => '“' + p.tasks[d].title.slice(0, 24) + '”').join(', ')))}</span>` : '')})
      + t.subtasks.map((s, k) => propItemHtml(`${i}.${k}`, s, {sub: true})).join('')).join('');
  }
  if (v.kind === 'subtasks') return p.items.map((t, i) => propItemHtml(String(i), t, {
    chips: (t.estimate ? `<span class="ppchip">${ic('clock', 's')}${esc(fmtDur(t.estimate * 60))}</span>` : '')
      + p.dependencies.filter(d => d[0] === i).map(d => `<span class="ppchip">${ic('deps', 's')}${esc(tr('blocked by {0}', '“' + p.items[d[1]].title.slice(0, 24) + '”'))}</span>`).join('')})).join('');  // 2.5.2 (K03): no stray commas
  if (v.kind === 'extract') {
    const secs = [...new Set([...(inp.list?.sections || []), ...p.tasks.map(t => t.section).filter(Boolean)])];
    return p.tasks.map((t, i) => propItemHtml(String(i), t, {
      fields: `<select data-f="assignee_id" aria-label="${esc(tr('Assignee'))}"><option value="">${tr('Nobody')}</option>${(inp.members || []).map(m => `<option value="${m.id}" ${m.id === t.assignee_id ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</select>
        <select data-f="section" aria-label="${esc(tr('Section'))}"><option value="">${tr('No section')}</option>${secs.map(s => `<option ${s === t.section ? 'selected' : ''}>${esc(s)}${(inp.list?.sections || []).includes(s) ? '' : ' ' + esc(tr('(new)'))}</option>`).join('')}</select>`})).join('');
  }
  // triage: the inbox item as it is now, where it should go
  return p.items.map((t, i) => {
    const it = (inp.items || []).find(x => x.task_id === t.task_id) || {}, cur = taskById(t.task_id);
    return propItemHtml(String(i), {title: t.rewrite_title || cur?.title || it.title || '', due: t.due, notes: ''}, {
      orig: t.rewrite_title ? cur?.title || it.title : '',
      fields: `<select data-f="list_id" aria-label="${esc(tr('Project'))}"><option value="">${tr('Stay in the basket')}</option>${(inp.lists || []).map(l => `<option value="${l.id}" ${l.id === t.list_id ? 'selected' : ''}>${esc(l.name)}</option>`).join('')}</select>${propSecSel(t.list_id, t.section_id)}`,
      chips: propPrio(t.priority) + (t.tags || []).map(g => `<span class="ppchip">#${esc(g)}</span>`).join('')});
  }).join('');
}
function propCount() {
  const P = S.prop, n = P.sel.size, all = propKeys(P.v).length, b = $('[data-pp="apply"]', P.md);
  if (lyp_is(P.v) || rul_is(P.v)) return;  // 2.55.0 (#1066): its own buttons; 2.71.0 A (#1457)
  if (aim_is(P.v)) return aim_count();  // 2.68.0 (#1839)
  if (dup_is(P.v)) return dup_count(P);  // 2.70.0 B (#1357): groups to merge
  if (ctr_is(P.v)) return;  // 2.70.0 C (#1359): its own buttons
  if (typeof ast_is === 'function' && ast_is(P.v)) return;  // 2.126.1 A (#2123 #2124): its own buttons
  if (typeof objp_is === 'function' && objp_is(P.v)) return;  // 2.623.0 (#4718): its own buttons
  $$('.ppcount', P.md).forEach(c => { c.textContent = tr('{0} of {1} selected', n, all); });
  if (b) { b.disabled = !n; b.innerHTML = `${ic('check', 's')} ${esc(trn('Apply {0} entry', 'Apply {0} entries', n))}`; }
}
function propDraw() {
  const P = S.prop, v = P.v, st = v.state, j = v.job, p = v.proposal, agent = `<b>${esc(v.agent.name)}</b>`;
  let main = '', foot = `<span class="spacer"></span><button class="btn" data-pp="close">${tr('Close')}</button>`;
  if (st === 'requested') {
    main = `<div class="ppwait">${ic('bot')}<p>${tr('{0} is working on it. You get a notification when the proposal is ready.', agent)}</p></div>`;
    foot = `<button class="btn danger" data-pp="discard">${tr('Cancel the request')}</button>` + foot;
  } else if (st === 'ready') {
    main = `${p.summary ? `<div class="ppsum">${commentBody(p.summary, {})}</div>` : ''}
      ${v.kind === 'project' || v.kind === 'inquiry' ? `<div class="row"><label for="pp-name">${tr('Project name')}</label><input id="pp-name" maxlength="120" value="${esc(p.name)}"></div>
        <div class="row"><label for="pp-folder">${tr('Folder')}</label><input id="pp-folder" maxlength="60" value="${esc(p.folder || v.input.folder || '')}" placeholder="${esc(tr('optional'))}"></div>
        <label class="ppshare"><input type="checkbox" id="pp-share"> ${tr('Share the new project with {0}', esc(v.agent.name))}</label>` : ''}
      <div class="ppbar"><button class="btn sm" data-pp="all">${tr('Select all')}</button><button class="btn sm" data-pp="none">${tr('Select none')}</button></div>
      <div class="ppl">${propItemsHtml()}</div>
      <div class="shint keep">${AP_KINDS.includes(v.kind) ? ap_propHint(v) : v.kind === 'cleanup' ? tr('Applying changes the selected tasks as you. Tasks someone is editing right now or that changed since the request are skipped. Undo possible.') : v.kind === 'dayplan' ? tr('Applying sets the planned start and duration of the selected tasks as you; due dates stay as they are. Undo possible.') : v.kind === 'triage' ? tr('Applying moves and changes the selected basket items as you. Undo possible.') : tr('Applying creates the selected entries as you (you own them, the history names {0}). Undo possible.', esc(v.agent.name))}</div>`;
    // 2.5.2 (K03): the footer stays visible below the entries (sticky), with the count next to Apply
    foot = `<button class="btn danger" data-pp="discard">${tr('Discard')}</button><span class="spacer"></span><span class="muted ppcount ppfc"></span><button class="btn" data-pp="close">${tr('Close')}</button><button class="btn pri" data-pp="apply"></button>`;
    if (typeof sht_is === 'function' && sht_is(v)) ({main, foot} = sht_draw(v));  // 2.126.1 B (#2125): table, list, one row per table row (sheetprop.js)
    if (lyp_is(v)) ({main, foot} = lyp_draw(v));  // 2.55.0 (#1066): before / after, 👍 / 👎 (lyprop.js)
    if (aim_is(v)) ({main, foot} = aim_draw(v));  // 2.68.0 (#1839): the import preview (importprop.js)
    if (dup_is(v)) ({main, foot} = dup_draw(v));  // 2.70.0 B (#1357): one row per group (dupprop.js)
    if (ctr_is(v)) ({main, foot} = ctr_draw(v));  // 2.70.0 C (#1359): the contract, the sentence, note / remind me (contractprop.js)
    if (rul_is(v)) ({main, foot} = rul_draw(v));  // 2.71.0 A (#1457): the rule in one sentence, 👍 / 👎 (rules.js)
    if (typeof ast_is === 'function' && ast_is(v)) ({main, foot} = ast_draw(v));  // 2.126.1 A (#2123 #2124): the text to edit, copy / take over (asstprop.js)
    if (typeof objp_is === 'function' && objp_is(v)) ({main, foot} = objp_draw(v));  // 2.623.0 (#4718): the object, old -> new, 👍 / 👎 (objprop.js)
  } else {
    main = `<div class="ppwait">${ic(st === 'applied' ? 'check' : 'x')}<p>${st === 'applied' ? (v.applied?.undone ? tr('Applied, then undone.') : tr('Applied.')) : tr('Discarded. {0} was told.', agent)}</p></div>`;
  }
  P.md.querySelector('.card').innerHTML = `<h3>${ic('bot', 's')} ${esc(j.title)}</h3>
    <div class="pphead muted"><span class="jst">${esc(tr(PROP_ST[st] || st))}</span>${agent} · ${esc(relTime(j.updated_at))}${v.kind === 'cleanup' && clnPack(v) ? ' · ' + esc(clnPack(v)) : ''}</div>
    <div class="calerr" role="alert" id="pp-err" hidden></div>${main}<div class="foot ${st === 'ready' ? 'ppfoot' : ''}">${foot}</div>`;
  if (st === 'ready') propCount();
}
const F8C_PROJ_TOAST_MS = 10000;  // 2.58.0 (#1810): the Undo toast after a proposal became a project stays longer
async function propApply(b) {
  const P = S.prop; if (!P || !P.sel.size) return;
  const v = P.v, q = {select: [...P.sel], edits: Object.fromEntries(Object.entries(P.ed).filter(([k]) => P.sel.has(k)))};
  if (v.kind === 'project' || v.kind === 'inquiry') { q.name = $('#pp-name', P.md).value.trim() || v.proposal.name; q.folder = $('#pp-folder', P.md).value.trim(); q.share_agent = $('#pp-share', P.md).checked; }
  if (lyp_is(v)) q.use = $('#lyp-use', P.md)?.checked !== false;  // 2.55.0 (#1066)
  if (aim_is(v)) q.version = v.import?.version;  // 2.68.0 (#1839, review): 409 when the agent replaced the rows meanwhile
  if (ctr_is(v)) q.remind = b.dataset.ctrRemind === '1';  // 2.70.0 C (#1359): "Remind me"
  if (typeof ast_is === 'function' && ast_is(v)) ast_apply(P, q);  // 2.126.1 A (#2123 #2124): the edited text
  b.disabled = true;
  let r;
  try { r = await calReq('POST', `/api/proposals/${P.jid}/apply`, q); } catch (x) { const e = $('#pp-err', P.md); e.textContent = x.message; e.hidden = false; b.disabled = false; return; }
  P.md.remove(); S.prop = null;
  await load().catch(() => {}); await window.mwLoad?.(true); if (lyp_is(v)) await lyp_after(v); if (aim_is(v)) aim_after(); render();
  const name = v.agent.name, jid = P.jid, ly = lyp_is(v) ? () => load().then(() => lyp_after(v)).then(render).catch(() => {}) : aim_is(v) ? aim_after : () => {};  // 2.55.0 (#1066); 2.68.0 (#1839)
  // 2.58.0 (#1810): a new project opens its list; Undo removes it again, so it goes back to the view before (when still on it)
  const proj = (v.kind === 'project' || v.kind === 'inquiry') && r.list_id && listById(r.list_id), back = location.hash.slice(1) || LS.get('lastKey', START_KEY);
  const f8c_back = () => { if (proj && location.hash === '#l/' + r.list_id) go(back); };
  const e = histAdd({label: tr('Applied the proposal of {0}', name), snaps: [], after: [], ids: [], lids: r.list_id ? [r.list_id] : [],
    undo: async () => { const x = await api('POST', `/api/proposals/${jid}/undo`); ly(); f8c_back(); return {skipped: x.skipped || [], none: !!x.none}; },
    redo: async () => { const x = await api('POST', `/api/proposals/${jid}/redo`); ly(); return {skipped: x.skipped || [], none: !!x.none}; }});
  if (dup_is(v)) dup_hist(e);  // 2.70.0 B (#1357): the contacts view follows undo / redo
  if (ctr_is(v)) { histToast(ctr_toast(v, r), e); if (S.route.mod === 'agents') loadJobs(); return; }  // 2.70.0 C (#1359)
  if (typeof ast_is === 'function' && ast_is(v)) { ast_hist(v, e); histToast(ast_toast(v), e); ast_after(v, true); if (S.route.mod === 'agents') loadJobs(); return; }  // 2.126.1 A (#2123 #2124)
  if (typeof objp_is === 'function' && objp_is(v)) { histToast(objp_toast(v, r), e); if (S.route.mod === 'agents') loadJobs(); return; }  // 2.623.0 (#4718)
  if (proj) go('l/' + r.list_id);  // first: the toast belongs to the new list's page (2.218.0 #2801 hides an undo message on a page change)
  histToast(dup_is(v) ? dup_toast(r) : lyp_is(v) ? lyp_toast(v, r) : rul_is(v) ? rul_toast(v) : aim_is(v) ? aim_toast(r) : pk2_is(v.kind) ? pk2_toast(v, r) : v.kind === 'cleanup' ? clnDone(r) : v.kind === 'dayplan' ? trn('{0} task planned', '{0} tasks planned', r.changed) : r.changed ? trn('{0} basket item sorted', '{0} basket items sorted', r.changed) : trn('{0} entry created', '{0} entries created', r.created), e, proj ? F8C_PROJ_TOAST_MS : undefined);
  if (S.route.mod === 'agents') loadJobs();
}
async function propDiscard() {
  const P = S.prop; if (!P) return;
  const req = P.v.state === 'requested';
  if (!await askConfirm(req ? tr('Cancel the request?') : tr('Discard this proposal?'), tr('{0} is told at once. Nothing is created or changed.', P.v.agent.name), {ok: req ? tr('Cancel the request') : tr('Discard'), danger: true})) return;
  try { await calReq('POST', `/api/proposals/${P.jid}/discard`); } catch (x) { toast(x.message); return; }
  P.md.remove(); S.prop = null;
  toast(req ? tr('Request cancelled') : tr('Proposal discarded'));
  load().then(() => window.mwLoad?.(true)).then(render).catch(() => {});
  if (S.route.mod === 'agents') loadJobs();
}
