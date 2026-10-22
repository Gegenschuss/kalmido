// @ts-check
/* Kalmido web client: 2.115.0 A (#2061) -- inbound webhooks of a list. A section "Inbound webhook" in the list settings
   (owner and list admins only): add -> the secret URL once with a copy button and a curl example; per webhook: name, last
   used, count, paused reason, "New URL" (the old one stops at once) and delete (asks first, one undo step). A request to
   the URL creates a task in this list with the rights of the person who set it up (server: integrations/hookin.py).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const WHI = {};  // list id -> {hooks, limit, available, reason, url: {id, url} shown once}
function whiCurl(url) {
  return `curl -X POST -H 'Content-Type: application/json' -d '{"title": "${tr('Call back')}", "due": "2026-01-31", "priority": "high"}' '${url}'`;
}
function whiRowsHtml(lid) {
  const d = WHI[lid]; if (!d) return `<div class="muted mhint">${tr('Loading…')}</div>`;
  if (!d.available) return `<div class="muted mhint">${esc(d.reason || tr('Inbound webhooks are not available in this project'))}</div>`;
  const rows = d.hooks.map(h => {
    const st = [h.uses ? trn('{0} task created', '{0} tasks created', h.uses) : tr('Not used yet'), h.last_used_at ? tr('last {0}', relTime(h.last_used_at)) : ''].filter(Boolean).join(' · ');
    const nm = h.name || tr('Inbound webhook');
    const shown = d.url && d.url.id === h.id ? `<div class="shint lhint whi-url" role="status">${esc(tr('Webhook URL (shown only now, keep it secret):'))} <code>${esc(d.url.url)}</code>
      <button type="button" class="linkbtn" data-whi-copy="url">${ic('copy', 's')} ${tr('Copy')}</button>
      <div class="whi-ex"><span class="muted">${tr('Example')}</span> <code>${esc(whiCurl(d.url.url))}</code> <button type="button" class="linkbtn" data-whi-copy="curl">${ic('copy', 's')} ${tr('Copy')}</button></div></div>` : '';
    return `<div class="mrow rul-row whi-row${h.paused_reason ? ' off' : ''}" data-whi="${h.id}">${ic('zap', 's')}
      <div class="rul-txt"><b>${esc(nm)}</b><span class="muted">${esc(st)}</span>${h.paused_text ? `<span class="rul-paused">${esc(tr('Paused: {0}', h.paused_text))}</span>` : ''}</div>
      <button type="button" class="iconbtn" data-whi-menu="${h.id}" title="${esc(nm)}: ${esc(tr('More'))}" aria-label="${esc(nm)}: ${esc(tr('More'))}">${ic('dots', 's')}</button></div>${shown}`;
  }).join('');
  return rows + `<div class="mrow"><button type="button" class="btn sm" data-whi-add="1" ${d.hooks.length >= d.limit ? 'disabled' : ''}>${ic('plus', 's')} ${tr('Add inbound webhook')}</button></div>
    <div class="shint lhint">${tr('Each request creates one task in this project with your rights: JSON with title (required), notes, due, priority, tags and fields, or plain text.')}</div>`;
}
async function whiLoad(lid) {
  const j = await api('GET', `/api/lists/${lid}/hooks-in`);
  WHI[lid] = {hooks: j.hooks || [], limit: j.limit || 10, available: j.available !== false, reason: j.reason || '', url: WHI[lid]?.url || null};
}
function whiMount(md, l) {
  const box = $('#l-whi', md); if (!box || box._whi) return;
  box._whi = true;
  const lid = l.id, draw = () => { const b = $('#l-whi', md); if (b) b.innerHTML = whiRowsHtml(lid); };
  const again = async () => { await whiLoad(lid).catch(() => {}); draw(); return {skipped: []}; };
  WHI[lid] = null;
  whiLoad(lid).then(draw).catch(() => { box.innerHTML = `<div class="muted mhint">${tr('Could not load the inbound webhooks.')}</div>`; });
  const showUrl = async x => { WHI[lid] = WHI[lid] || {hooks: []}; await whiLoad(lid).catch(() => {}); WHI[lid].url = {id: x.id, url: x.url}; draw(); $('#l-whi [data-whi-copy="url"]', md)?.focus(); };
  box.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('button'); if (!b) return;
    e.stopPropagation();
    const d = WHI[lid], h = d?.hooks.find(x => x.id === +(b.dataset.whiMenu || 0));
    if (b.dataset.whiCopy) {
      const u = d?.url?.url || '', x = b.dataset.whiCopy === 'curl' ? whiCurl(u) : u;  // never the secret URL in a toast
      try { await navigator.clipboard.writeText(x); toast(tr('Copied')); } catch { toast(x); }
      return;
    }
    if (b.dataset.whiAdd) {
      const name = await askDialog({title: tr('Add inbound webhook'), body: tr('A name helps you tell them apart (e.g. the tool that sends).'),
        input: {placeholder: tr('e.g. Home Assistant'), max: 60}, ok: tr('Add'), cancel: undefined, after: undefined});
      if (name == null) return;
      let x; try { x = await api('POST', `/api/lists/${lid}/hooks-in`, {name: name.trim()}); } catch { return; }
      await showUrl(x);
      return;
    }
    if (!h) return;
    menu(b, [
      {label: tr('Rename'), icon: 'edit', fn: async () => {
        const name = await askDialog({title: tr('Rename'), input: {value: h.name, max: 60}, ok: tr('Save'), cancel: undefined, after: undefined});
        if (name == null) return;
        try { await api('PATCH', `/api/hooks-in/${h.id}`, {name: name.trim()}); } catch { return; }
        again();
      }},
      ...(h.paused_reason ? [{label: tr('Resume with my rights'), icon: 'play', fn: async () => {
        try { await api('PATCH', `/api/hooks-in/${h.id}`, {resume: true}); } catch { return; } again();
      }}] : []),
      {label: tr('New URL (the old one stops working)'), icon: 'sync', fn: async () => {
        let x; try { x = await api('POST', `/api/hooks-in/${h.id}/rotate`); } catch { return; } await showUrl(x);
      }},
      '-', {label: tr('Delete'), icon: 'trash', cls: 'flag-5', fn: async () => {
        if (!await askConfirm(tr('Delete the inbound webhook “{0}”?', h.name || tr('Inbound webhook')), tr('Its URL stops working at once.'), {ok: tr('Delete'), danger: true})) return;
        try { await api('DELETE', `/api/hooks-in/${h.id}`); } catch { return; }
        if (WHI[lid]?.url?.id === h.id) WHI[lid].url = null;
        await again();
        const hh = histAdd({label: tr('Deleted the inbound webhook {0}', tr('“{0}”', h.name || tr('Inbound webhook'))), snaps: [], after: [], ids: [], lids: [lid],
          undo: async () => { await api('POST', `/api/hooks-in/${h.id}/restore`); return again(); },
          redo: async () => { await api('DELETE', `/api/hooks-in/${h.id}`); return again(); }});
        histToast(tr('Inbound webhook deleted'), hh);
      }}]);
  });
}
