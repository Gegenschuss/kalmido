// @ts-check
// 2.235.0 C (#2903): the section "Standing rules" of the agent dialog (awOpen in agentwork.js calls it with the dialog and the agent; it draws into its own container).
// The agent stores a rule itself when someone tells it "from now on always ..." (POST /api/v1/agent/rules, with its source) and
// confirms it in one line; here the owner / an instance admin reads, rewords, pauses and deletes them (GET / POST / PATCH / DELETE
// /api/agents/<id>/rules; the server answers 404 for everyone else -> the section stays empty). Own data-awr-* attributes:
// data-aw is agentwork.js' autosave.
const awr_src = (r, aid) => {
  const s = r.source || {}, when = fmtDate(String(r.created_at || '').slice(0, 10));
  const name = s.kind === 'chat' ? tr('from the chat') : s.kind === 'comment' ? tr('from a comment') : tr('added by hand');
  const link = s.visible && (s.kind === 'chat' || s.kind === 'comment')
    ? `<button type="button" class="linkbtn" data-awr-src="${r.id}" data-awr-art="${s.kind === 'chat' ? 'a' : 'c'}" data-awr-mid="${s.id}" data-awr-task="${s.task_id || ''}" data-awr-agent="${aid}" ${s.excerpt ? `title="${esc(s.excerpt)}"` : ''}>${esc(name)}</button>`
    : esc(name);
  return `<small class="muted awrmeta">${esc(when)} · ${link}${s.visible && s.excerpt ? `<span class="awrex">“${esc(s.excerpt)}”</span>` : ''}</small>`;
};
function awr_row(r, aid, max) {
  const on = r.state === 'active';
  return `<div class="mrow awr ${on ? '' : 'paused'}" data-awr-id="${r.id}">
    <span class="n"><span class="awrt" id="awr-t-${r.id}">${esc(r.text)}</span>${awr_src(r, aid)}</span>
    <label class="chkl swl" title="${esc(on ? tr('Active') : tr('Paused'))}"><span class="swc"><input type="checkbox" role="switch" data-awr-on="${r.id}" ${on ? 'checked' : ''} aria-label="${esc(tr('Rule active'))}" aria-describedby="awr-t-${r.id}"><span class="swt" aria-hidden="true"></span></span></label>
    <button type="button" class="iconbtn" data-awr-edit="${r.id}" data-awr-max="${max}" title="${esc(tr('Edit'))}" aria-label="${esc(tr('Edit'))}">${ic('edit', 's')}</button>
    <button type="button" class="iconbtn danger" data-awr-del="${r.id}" title="${esc(tr('Delete'))}" aria-label="${esc(tr('Delete'))}">${ic('trash', 's')}</button>
  </div>`;
}
function awr_html(j, aid) {
  const rules = j.rules || [], full = rules.length >= j.max;
  return `<h4 id="awr-h">${tr('Standing rules')}</h4>
    ${rules.length ? `<div class="awrl" role="list" aria-labelledby="awr-h">${rules.map(r => awr_row(r, aid, j.text_max)).join('')}</div>`
    : `<div class="muted mhint" id="awr-empty">${tr('No standing rules yet. Tell the agent in the chat or in a comment "from now on always ..." - it saves the rule here and confirms it in one line.')}</div>`}
    <div class="row awradd"><input id="awr-new" maxlength="${j.text_max}" autocomplete="off" placeholder="${esc(tr('Add a rule by hand'))}" aria-label="${esc(tr('Add a rule by hand'))}" ${full ? 'disabled' : ''}><button type="button" class="btn sm" data-awr-add="1" ${full ? 'disabled' : ''}>${tr('Add')}</button></div>
    <div class="shint">${tr('Paused rules stay here but the agent does not follow them.')}</div>
    <div class="calerr" role="alert" id="awr-err" hidden></div>`;
}
/** @param {any} md @param {any} agent */
function awr_mount(md, agent) {
  const box = $('#aw-rules', md); if (!box) return;
  const base = `/api/agents/${agent.id}/rules`;
  let j = null;
  const err = m => { const e = $('#awr-err', box); if (e) { e.textContent = m || ''; e.hidden = !m; } };
  const fail = e => err(e instanceof Offline ? tr('Only available online.') : e.message);
  const draw = () => { box.innerHTML = j ? awr_html(j, agent.id) : ''; };
  // a plain fetch for the first look: no rights / an older server = no section, never the reload api() does on an HTML answer
  fetch(base, {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.ok ? r.json() : null).catch(() => null).then(x => { j = x; draw(); });
  const reload = async () => { try { j = await api('GET', base); draw(); } catch (e) { fail(e); } };
  const add = async () => {
    const i = $('#awr-new', box), v = i.value.trim(); if (!v) return;
    try { await api('POST', base, {text: v}); await reload(); toast(tr('Rule saved')); $('#awr-new', box)?.focus(); } catch (e) { fail(e); }
  };
  box.addEventListener('change', async e => {
    const el = /** @type {any} */ (e.target).closest('[data-awr-on]'); if (!el) return;
    e.stopPropagation(); err('');
    try { await api('PATCH', `${base}/${el.dataset.awrOn}`, {state: el.checked ? 'active' : 'paused'}); await reload(); toast(el.checked ? tr('Rule active again') : tr('Rule paused')); }
    catch (x) { el.checked = !el.checked; fail(x); }
  });
  box.addEventListener('keydown', e => { if (e.key === 'Enter' && /** @type {any} */ (e.target).id === 'awr-new') { e.preventDefault(); add(); } });
  box.addEventListener('click', async e => {
    const t = /** @type {any} */ (e.target);
    if (t.closest('[data-awr-add]')) { err(''); add(); return; }
    const ed = t.closest('[data-awr-edit]');
    if (ed) {
      const r = (j?.rules || []).find(x => x.id === +ed.dataset.awrEdit); if (!r) return;
      const row = ed.closest('.awr'), n = $('.n', row);
      n.innerHTML = `<textarea class="awredit" rows="2" maxlength="${+ed.dataset.awrMax || 500}" aria-label="${esc(tr('Rule'))}">${esc(r.text)}</textarea><span class="awrbtns"><button type="button" class="btn sm pri" data-awr-save="${r.id}">${tr('Save')}</button><button type="button" class="btn sm" data-awr-cancel="1">${tr('Cancel')}</button></span>`;
      $('textarea', n).focus(); return;
    }
    if (t.closest('[data-awr-cancel]')) { draw(); return; }
    const sv = t.closest('[data-awr-save]');
    if (sv) {
      const v = $('.awredit', sv.closest('.awr')).value.trim(); if (!v) { err(tr('The rule is empty.')); return; }
      err('');
      try { await api('PATCH', `${base}/${sv.dataset.awrSave}`, {text: v}); await reload(); toast(tr('Rule saved')); } catch (x) { fail(x); }
      return;
    }
    const del = t.closest('[data-awr-del]');
    if (del) {
      const r = (j?.rules || []).find(x => x.id === +del.dataset.awrDel); if (!r) return;
      if (!await askConfirm(tr('Delete this rule?'), r.text, {ok: tr('Delete'), danger: true})) return;
      err('');
      try { await api('DELETE', `${base}/${r.id}`); await reload(); toast(tr('Rule deleted')); } catch (x) { fail(x); }
      return;
    }
    const src = t.closest('[data-awr-src]');
    if (src) { const d = src.dataset; md.remove(); msgJump({art: d.awrArt, id: +d.awrMid, task: +d.awrTask || undefined, agent: +d.awrAgent}); }
  });
}
