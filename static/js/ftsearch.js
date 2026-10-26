// @ts-check
// 2.116.0 B (#2065): the command palette's group "Everywhere": the server's ranked full-text hits (GET /api/search: tasks by
// title, notes, comments, custom fields, file texts -- also completed tasks and tasks of areas that are not loaded), below the
// local hits. From 2 characters, 250 ms after the last key; a newer query aborts the older request; offline: nothing (the
// local hits stay). Tasks the palette already lists come once. Lists with the lock are never on the server (it holds only
// ciphertexts): the local search of the palette covers them.
// 2.250.0 A (#2992): + the group "Office": clients and quotations / invoices of the office the person works in (the
// server's key office: only when the person sees the office), above the task hits; a pick opens the client / the document.
const FTSP = {q: '', hits: null, office: [], t: 0, ctl: null};
PAL_GROUP.fts = N_('Everywhere');
PAL_GROUP.office = N_('Office');
const BS_KIND = {client: N_('Client'), offer: N_('Quotation'), invoice: N_('Invoice'), credit: N_('Credit note'), reminder: N_('Reminder'), delivery: N_('Delivery note')};
async function ftsFetch(q, signal) {
  const r = await fetch('/api/search?limit=8&q=' + encodeURIComponent(q), {headers: {'X-Requested-With': 'kalmido'}, signal});
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}
function ftsPalItems(q, shown) {
  q = q.trim();
  if (q.length < 2 || S.me?.kid || !OUT.online || OUT.down) return [];
  if (FTSP.q !== q) {
    FTSP.q = q; FTSP.hits = null; FTSP.office = []; clearTimeout(FTSP.t); FTSP.ctl?.abort(); FTSP.ctl = null;
    FTSP.t = setTimeout(async () => {
      const ctl = FTSP.ctl = new AbortController();
      let r; try { r = await ftsFetch(q, ctl.signal); } catch { return; }  // aborted, offline, error: no group
      if (FTSP.q !== q) return;
      FTSP.hits = r.hits || []; FTSP.office = Array.isArray(r.office) ? r.office : [];
      if ($('.palette') && PAL.q.trim() === q) palDraw();
    }, 250);
    return [];
  }
  const have = new Set(shown.map(x => String(x.id).replace(/^t(id)?:/, '')));
  const office = FTSP.office.filter(h => /^(client|office\/offers)\/\d+$/.test(String(h.go))).map(h => ({id: 'bs:' + h.kind + ':' + h.id, kind: 'view', group: 'office', label: h.label || '…',
    sub: [tr(BS_KIND[h.kind] || 'Office'), h.sub].filter(Boolean).join(' · '), icon: h.kind === 'client' ? 'brief' : 'receipt', fn: () => go(h.go)}));
  return office.concat((FTSP.hits || []).filter(h => !have.has(String(h.task.id))).map(h => {
    const t = h.task, l = listById(t.list_id), snip = h.where !== 'title' && h.snippet?.text ? msgSnip({snippet: h.snippet.text, marks: h.snippet.marks}) : '';
    const pre = [l ? lname(l) : '', t.status !== 0 ? tr('Completed') : '', {comment: tr('Comment'), field: tr('Field'), file: tr('File')}[h.where] || ''].filter(Boolean).join(' · ');
    return {id: 'fts:' + t.id, kind: 'tasks', group: 'fts', label: t.title || '…', icon: 'check',
      subHtml: esc(pre) + (pre && snip ? ' · ' : '') + snip, fn: () => ftsOpen(h)};
  }));
}
async function ftsOpen(h) {
  const tid = h.task.id;
  if (h.where === 'comment' && h.comment_id) return window.msgJump?.({art: 'c', id: h.comment_id, task: tid});  // opens + shows the comment
  if (!taskById(tid)) { try { (S.extra ||= []).push(await rawFetch('GET', `/api/tasks/${tid}`)); } catch { return; } }
  openDetail(tid);
}
