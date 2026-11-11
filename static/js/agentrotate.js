// @ts-check
/* Kalmido web client: the agent runtime section "Interim summary" (2.233.0 B, #3189): when the agent's host ends a chat
   conversation with a summary and starts a fresh one (session size, runs, minutes of pause, the daily summary time =
   runtime nightly_reset). Kalmido only stores it (GET /api/v1/agent "runtime"); every field saves at once. Shown in the
   admin's agent dialog (agentchat.js, below "Runtime") and in the permissions dialog of a personal agent (settings.js).
   base = /api/admin/agents/<id> or /api/my/agents/<id>.
   2.396.0 A (#3386): below it the block "Git author": name + mail the host sets for the agent's commits (empty = the neutral
   default) and whether it appends a Co-Authored-By line; saved at once like the fields above.
   2.481.0 (#3662): below it "Work the list off": the starter's mechanical dispatcher (mcp/agent_dispatch.py) off, as a dry
   run or on (runtime.dispatch); which lists and how is the project's KALMIDO-DISPATCH.json on the agent's computer.
   2.974.0 (#5668) / 2.992.0 (#5684): the section "Model" (the model per run: decisions, reviews, routine; the usage per kind of
   the last 7 days); the chat header's "runs with …" opens it as a dialog of its own (agm_open). */
'use strict';

const AGZ_SIZES = [['small', N_('Small'), '0.4 MB'], ['medium', N_('Medium'), '0.8 MB'], ['large', N_('Large'), '1.5 MB']];
// the section; own = also its own time field (the admin dialog already has #ag-nr: agz_wire moves it in here)
/** @param {any} a @param {boolean} [own] */
function agz_html(a, own) {
  if (!a) return '';
  const rt = a.runtime || {}, size = rt.rotate_size || 'medium', idle = rt.rotate_idle_min ?? 45;
  return `<div class="agzsec" data-agz="${a.id}"><h4 id="agz-h">${tr('Interim summary')}</h4>
    <div class="shint">${tr('The agent then starts a new conversation with a summary of the previous one: this saves cost, but it can forget details. Its host applies it.')}</div>
    <div class="row"><label for="agz-size">${tr('Session size')}</label><select id="agz-size" data-agzk="rotate_size">${AGZ_SIZES.map(([k, n, mb]) => `<option value="${k}" ${size === k ? 'selected' : ''}>${esc(tr(n))} (${mb})</option>`).join('')}</select></div>
    <div class="row"><label for="agz-runs">${tr('After messages')}</label><input id="agz-runs" class="numin" data-agzk="rotate_runs" type="number" min="10" max="500" step="1" inputmode="numeric" value="${rt.rotate_runs ?? 60}"></div>
    <div class="row"><label for="agz-idle">${tr('After a pause of')}</label><span class="agpct"><input id="agz-idle" class="numin" data-agzk="rotate_idle_min" type="number" min="0" max="1440" step="1" inputmode="numeric" value="${idle}"><span class="muted">${tr('min')}</span></span></div>
    <div class="shint">${tr('Pause: 0 = never; it counts only from the small size on.')}</div>
    ${own ? `<div class="row agznr"><label>${tr('Daily summary')}</label>${timeIn('agz-nr', rt.nightly_reset || '', {label: tr('Daily summary'), empty: tr('Agent default')})}</div>` : '<div class="agznr-slot"></div>'}</div>${agg_html(a)}${agd_html(a)}${/*html-ok*/ own ? agm_html(a) : ''}`;  // 2.974.0 (#5668): agm_html escapes its values
}
// 2.974.0 (#5668): the model and the model per run in the owner's dialog of a personal agent (the admin dialog has them in
// "Runtime", agentchat.js agSplitFields); saved at once like the fields above. 2.992.0 (#5684): a third model for reviews
// (empty = the first) and the usage per kind of the last 7 days below them (agmu_load); the same section is the dialog the
// chat header opens (agm_open)
/** @param {any} a */
function agm_html(a) {
  const rt = a.runtime || {}, on = !!rt.model_split;
  /** @param {string} id @param {string} k @param {string} [ph] */
  const mi = (id, k, ph) => `<input id="${esc(id)}" data-agzk="${esc(k)}" list="agm-models" value="${esc(rt[k] || '')}" maxlength="100" placeholder="${esc(ph || tr('Agent default'))}" autocomplete="off" autocapitalize="off" spellcheck="false">`;
  return `<div class="agzsec agzmod" data-agz="${esc(String(a.id))}"><h4 id="agm-h">${tr('Model')}</h4>
    <div class="row"><label for="agm-model">${tr('Model')}</label>${/*html-ok*/ mi('agm-model', 'model')}<datalist id="agm-models">${['opus', 'sonnet', 'haiku'].map(m => `<option value="${esc(m)}"></option>`).join('')}</datalist></div>
    <label class="chkl swl"><span class="swc"><input type="checkbox" role="switch" id="agm-split" data-agzk="model_split" ${on ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${tr('Select the model per run')}</span></label>
    <div class="row agm-r" ${on ? '' : 'hidden'}><label for="agm-dec">${tr('For your messages and decisions')}</label>${/*html-ok*/ mi('agm-dec', 'model_decide')}</div>
    <div class="row agm-r" ${on ? '' : 'hidden'}><label for="agm-rev">${tr('For reviews')}</label>${/*html-ok*/ mi('agm-rev', 'model_review', tr('Like messages and decisions'))}</div>
    <div class="row agm-r" ${on ? '' : 'hidden'}><label for="agm-rou">${tr('For routine')}</label>${/*html-ok*/ mi('agm-rou', 'model_routine')}</div>
    <div class="shint agm-r" ${on ? '' : 'hidden'}>${tr('Your messages, buttons, reactions and comments and every run that may need a decision use the first model; reviews (a review you ask it for, a planned job of the kind Review, a scheduled check of a project) the second, empty = the first; quiet wake-ups, new tasks, follow-ups and planned jobs without a warning sign the third. When in doubt the first.')}</div>
    <div class="agmu agm-r" aria-live="polite" ${on ? '' : 'hidden'}></div></div>`;
}
// 2.992.0 (#5684): the usage per kind of run of the last 7 days (GET <base>/model-usage): runs, tokens, the costs only when
// its computer reports them (nothing estimated)
const AGM_CLASSES = {decide: N_('Messages and decisions'), review: N_('Reviews'), routine: N_('Routine'), '': N_('Without a kind')};
/** @param {any} box @param {string} base */
async function agmu_load(box, base) {
  if (!box) return;
  /** @type {any} */
  let j; try { j = await api('GET', `${base}/model-usage`); } catch { box.textContent = ''; return; }
  if (!box.isConnected) return;
  const any = (j.classes || []).some((/** @type {any} */ x) => x.calls);
  box.innerHTML = `<div class="lbl">${esc(tr('Last 7 days'))}</div>` + (any ? `<ul class="agmul">${(j.classes || []).map((/** @type {any} */ x) =>
    `<li data-cls="${esc(x.run_class)}"><span class="agmuk">${esc(tr(AGM_CLASSES[x.run_class] || AGM_CLASSES['']))}</span><span class="muted">${esc([
      tr('Runs: {0}', String(x.runs)), tr('{0} tokens', fmtTok(x.tokens)), ...j.cost && x.cost != null ? [fmtUsd(x.cost)] : []].join(' · '))}</span></li>`).join('')}</ul>`
    : `<div class="muted">${esc(tr('No usage reported yet'))}</div>`)
    + (j.cost ? '' : `<div class="shint">${esc(tr('Its computer reports no costs: runs and tokens only.'))}</div>`);
}
// the section's autosave (the owner's permissions dialog and the header's dialog); base = /api/admin/agents/<id> or /api/my/agents/<id>
/** @param {any} mod @param {any} a @param {string} base */
function agm_wire(mod, a, base) {
  if (!mod) return;
  mod.addEventListener('change', async (/** @type {any} */ e) => {
    const el = e.target, k = el.dataset.agzk; if (!k) return;
    const rt = a.runtime || (a.runtime = {}), v = k === 'model_split' ? !!el.checked : String(el.value).trim();
    /** @param {boolean} on */
    const show = on => $$('.agm-r', mod).forEach((/** @type {any} */ x) => { x.hidden = !on; });
    if (k === 'model_split') show(!!v);
    try {
      const r = await api('PATCH', base, {runtime: {[k]: v}});
      if (r?.runtime) a.runtime = r.runtime;
      if (k !== 'model_split') el.value = v;
      else agm_headSync(a.id, !!v);
      savedTick(el);
    } catch {
      if (k === 'model_split') { el.checked = !!rt[k]; show(!!rt[k]); } else el.value = rt[k] || '';
    }
  });
  agmu_load($('.agmu', mod), base);
}
// the open chat of this agent follows the switch at once (the header's "runs with …")
/** @param {number} id @param {boolean} on */
function agm_headSync(id, on) {
  const ag = typeof agentById === 'function' ? agentById(id) : null;
  if (!ag) return;
  ag.model_split = on;
  if (typeof chatHeadSync === 'function') chatHeadSync(ag, true);
}
// 2.992.0 (#5684): the tap on "runs with …" in the chat header: the section Model of this agent in a dialog of its own (its
// owner: the personal agent; an admin: any agent)
/** @param {any} ag */
async function agm_open(ag) {
  const own = !!ag.owner_id && ag.owner_id === S.me?.id, base = own ? `/api/my/agents/${ag.id}` : `/api/admin/agents/${ag.id}`;
  /** @type {any} */
  let a; try { a = ((await api('GET', own ? '/api/my/agents' : '/api/admin/agents')).agents || []).find((/** @type {any} */ x) => x.id === ag.id); } catch { return; }
  if (!a) return;
  /** @type {any} */
  const md = modal(`<h3>${esc(tr('Model of {0}', a.name))}</h3>${/*html-ok*/ agm_html(a)}<div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  agm_wire($('.agzmod', md), a, base);
  $('[data-m="close"]', md)?.addEventListener('click', () => md.remove());
}
// 2.396.0 A (#3386): the git author block (same section style, same autosave in agz_wire)
const AGG_DEFAULT = ['Kalmido', 'noreply@kalmido.com'];
const AGG_MAIL = /^[^@\s<>,]{1,100}@[^@\s<>,]{1,100}\.[^@\s<>,]{1,60}$/;
/** @param {any} a */
function agg_html(a) {
  const rt = a.runtime || {};
  return `<div class="agzsec agzgit" data-agz="${a.id}"><h4 id="agg-h">${tr('Git author')}</h4>
    <div class="shint">${tr('Appears publicly in GitHub with every commit of this agent.')}</div>
    <div class="row"><label for="agg-name">${tr('Name')}</label><input id="agg-name" data-agzk="git_author_name" maxlength="100" autocomplete="off" value="${esc(rt.git_author_name || '')}" placeholder="${AGG_DEFAULT[0]}"></div>
    <div class="row"><label for="agg-mail">${tr('E-mail')}</label><input id="agg-mail" data-agzk="git_author_email" type="email" maxlength="200" autocomplete="off" autocapitalize="off" spellcheck="false" value="${esc(rt.git_author_email || '')}" placeholder="${AGG_DEFAULT[1]}" aria-describedby="agg-err"></div>
    <div class="calerr" role="alert" id="agg-err" hidden></div>
    <label class="chkl swl"><span class="swc"><input type="checkbox" role="switch" id="agg-co" data-agzk="git_coauthor" ${rt.git_coauthor ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${tr('Append Co-Authored-By')}</span></label>
    <div class="shint">${tr('Empty = {0}. A project with a repository can set its own author.', esc(AGG_DEFAULT[0] + ' <' + AGG_DEFAULT[1] + '>'))}</div></div>`;
}
// 2.481.0 (#3662): the dispatcher switch (same section style, saved at once)
const AGD_MODES = [['', N_('Off')], ['dry', N_('Dry run')], ['on', N_('Active')]];
/** @param {any} a */
function agd_html(a) {
  const v = (a.runtime || {}).dispatch || '';
  return `<div class="agzsec agzdisp" data-agz="${a.id}"><h4 id="agd-h">${tr('Work the list off')}</h4>
    <div class="shint">${tr('The agent works the lists named on its computer off one after the other: it starts the next job when a place is free and closes tasks once they are built. Dry run = it only reports what it would do.')}</div>
    <div class="row"><label for="agd-mode">${tr('Mode')}</label><select id="agd-mode" data-agzk="dispatch">${AGD_MODES.map(([k, n]) => `<option value="${k}" ${v === k ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select></div></div>`;
}
/** @type {Record<string, number[]>} */
const AGZ_RANGE = {rotate_runs: [10, 500], rotate_idle_min: [5, 1440]};
// autosave of the section's fields; in the admin dialog the existing "Nightly fresh restart" row moves in as "Daily summary"
/** @param {any} md @param {any} a @param {string} base */
function agz_wire(md, a, base) {
  const sec = a && $(`.agzsec[data-agz="${a.id}"]`, md); if (!sec) return;
  const git = $(`.agzgit[data-agz="${a.id}"]`, md);  // 2.396.0 A (#3386): its own section element, the same autosave
  if (git) git.addEventListener('change', (/** @type {any} */ e) => agg_save(md, a, base, e.target));
  const disp = $(`.agzdisp[data-agz="${a.id}"]`, md);  // 2.481.0 (#3662)
  if (disp) disp.addEventListener('change', async (/** @type {any} */ e) => {
    const el = e.target; if (el.dataset.agzk !== 'dispatch') return;
    try {
      const r = await api('PATCH', base, {runtime: {dispatch: el.value}});
      if (r?.runtime) a.runtime = r.runtime;
      savedTick(el);
    } catch { el.value = (a.runtime || {}).dispatch || ''; /* api() said it */ }
  });
  agm_wire($(`.agzmod[data-agz="${a.id}"]`, md), a, base);  // 2.974.0 (#5668), 2.992.0 (#5684): agm_wire
  const slot = $('.agznr-slot', sec), nr = slot && $('#ag-nr', md)?.closest('.row');
  if (nr) { const l = $('label', nr); if (l) l.textContent = tr('Daily summary'); slot.replaceWith(nr); nr.classList.add('agznr'); }
  sec.addEventListener('change', async (/** @type {any} */ e) => {
    const el = e.target, k = el.dataset.agzk || (['ag-nr', 'agz-nr'].includes(el.id) ? 'nightly_reset' : ''); if (!k) return;
    const rt = a.runtime || (a.runtime = {});
    const raw = String(el.value);
    /** @type {string | number} */
    let v = raw;
    if (AGZ_RANGE[k]) {
      const [lo, hi] = AGZ_RANGE[k], n = +raw;
      if (!/^\d+$/.test(raw) || !((n >= lo && n <= hi) || (k === 'rotate_idle_min' && n === 0))) {
        toast(k === 'rotate_runs' ? tr('Messages: a number from {0} to {1}', lo, hi) : tr('Pause: 0 or {0} to {1} minutes', lo, hi));
        el.value = rt[k] ?? ''; return;
      }
      v = n;
    }
    try {
      const r = await api('PATCH', base, {runtime: {[k]: v}});
      if (r?.runtime) a.runtime = r.runtime;
      savedTick(el.type === 'hidden' ? $(`[data-dpfor="${el.id}"]`, md) || el : el);
    } catch { if (el.type !== 'hidden') el.value = rt[k] ?? ''; /* api() said it */ }
  });
}
// 2.396.0 A (#3386): saves one git author field; an invalid mail = the error at the field, nothing saved
/** @param {any} md @param {any} a @param {string} base @param {any} el */
async function agg_save(md, a, base, el) {
  const k = el.dataset.agzk; if (!k) return;
  const rt = a.runtime || (a.runtime = {}), err = $('#agg-err', md);
  const v = k === 'git_coauthor' ? !!el.checked : String(el.value).trim();
  const bad = k === 'git_author_email' && v && !AGG_MAIL.test(String(v)) ? tr('Git author: please enter a valid e-mail address')
    : k === 'git_author_name' && /[<>]/.test(String(v)) ? tr('Invalid value: {0}', tr('Name')) : '';
  if (err) { err.textContent = bad; err.hidden = !bad; }
  el.setAttribute('aria-invalid', bad ? 'true' : 'false');
  if (bad) return;
  try {
    const r = await api('PATCH', base, {runtime: {[k]: v}});
    if (r?.runtime) a.runtime = r.runtime;
    if (k !== 'git_coauthor') el.value = v;
    savedTick(el);
  } catch (e) {
    if (err && e?.status === 400) { err.textContent = e.message; err.hidden = false; }
    if (k === 'git_coauthor') el.checked = !!rt[k]; else el.value = rt[k] ?? '';
  }
}
