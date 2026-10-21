// @ts-check
/* Kalmido web client: a list / project as CSV and as a printable page (2.116.0 C, #2064).
   The CSV comes from the server (GET /api/lists/<id>/export.csv, listexport.py); the print view is drawn from the loaded state
   like the timesheet (time.js): an overlay with the page, "Print / save as PDF" = window.print(), only the page is printed.
   2.145.0 C (#2432): a project gets a compact head on top (description, status, period + progress, members, milestones) from
   the project page's own source (GET /api/lists/<id>/overview, the same visibility); empty parts are left out. */
function lexCsv(lid) {
  const l = listById(lid); if (!l) return;
  const a = document.createElement('a');
  a.href = `/api/lists/${lid}/export.csv?done=${LS.get('lexDone', true) ? 1 : 0}`;
  a.download = ''; a.hidden = true;
  document.body.appendChild(a); a.click(); a.remove();
}
function lexRows(lid, done) {  // [{t, depth}] by section (null = no section), subtasks right under their parent
  const all = [...S.tasks.values()].filter(t => t.list_id === lid && !t.deleted_at && (done || t.status === 0));
  const byParent = new Map(), ids = new Set(all.map(t => t.id));
  for (const t of all) { const k = t.parent_id && ids.has(t.parent_id) ? t.parent_id : 0; (byParent.get(k) || byParent.set(k, []).get(k)).push(t); }
  for (const a of byParent.values()) a.sort((x, y) => (x.sort || 0) - (y.sort || 0) || x.id - y.id);
  const walk = (t, d, out) => { out.push({t, depth: d}); for (const s of byParent.get(t.id) || []) walk(s, d + 1, out); return out; };
  const secs = S.sections.filter(s => s.list_id === lid).sort((a, b) => (a.sort || 0) - (b.sort || 0));
  const top = byParent.get(0) || [], out = [];
  for (const s of [null, ...secs]) {
    const rows = top.filter(t => (t.section_id || null) === (s ? s.id : null)).flatMap(t => walk(t, 0, []));
    if (rows.length) out.push({name: s ? s.name : '', rows});
  }
  return out;
}
// 2.145.0 C (#2432): the project head (j = the overview as the project page gets it; null = a plain list or not loaded)
function lexHead(l, j) {
  if (!j) return '';
  const parts = [], row = (k, v) => `<div class="lxhr"><dt>${esc(k)}</dt><dd>${v}</dd></div>`;
  const st = j.status || {};
  if (statusFor(l) && st.current) {
    const h = (st.history || [])[0], who = h && h.status === st.current ? h.name : '';
    parts.push(row(tr('Status'), `<b>${esc(statusLabel(st.current))}</b>${st.note ? ` · ${esc(st.note)}` : ''}${who || st.at ? ` <span class="muted">(${esc([who, st.at ? fmtDateLoc(ds(new Date(st.at))) : ''].filter(Boolean).join(', '))})</span>` : ''}`));
  }
  const days = [...S.tasks.values()].filter(t => t.list_id === l.id && !t.deleted_at).flatMap(t => [t.start, t.due]).filter(Boolean).sort();
  const p = l.progress || {done: 0, total: 0};
  const per = days.length ? tr('Period: {0} – {1}', fmtDateLoc(days[0]), fmtDateLoc(days[days.length - 1])) : '';
  const prog = progressFor(l) && p.total ? tr('{0} of {1} done ({2}%)', p.done, p.total, pct(p)) : '';
  if (per || prog) parts.push(row(tr('Progress'), esc([per, prog].filter(Boolean).join(' · '))));
  if (collab() && (j.members || []).length) parts.push(row(tr('Members'), esc(j.members.map(m => `${m.name} (${roleLabel(m.role)})`).join(', '))));
  const t0 = today(), ms = (j.milestones || []).map(m => `<li>${esc(m.name)} <span class="muted">· ${esc(m.day ? fmtDateLoc(m.day) : tr('No date'))} · ${esc(m.done ? tr('Done') : m.day && m.day < t0 ? tr('Overdue') : tr('Open|report'))}</span></li>`).join('');  // the state, not the verb
  if (ms) parts.push(row(tr('Milestones'), `<ul class="lxms">${ms}</ul>`));
  const desc = j.description ? `<div class="md lxdesc">${renderMd(j.description, true, {lid: l.id})}</div>` : '';
  return desc || parts.length ? `<div class="lxhead">${desc}${parts.length ? `<dl class="lxfacts">${parts.join('')}</dl>` : ''}</div>` : '';
}
function lexDoc(lid, done, notes, head) {
  const l = listById(lid), groups = lexRows(lid, done);
  const row = ({t, depth}) => {
    const meta = [t.due ? fmtDateLoc(t.due) + (t.due_time ? ' ' + t.due_time : '') : '', t.priority ? tr(PRIO_NAMES[t.priority] || '') : '',
      (t.tags || []).map(g => '#' + g).join(' ')].filter(Boolean);
    return `<li class="lxr ${t.status ? 'done' : ''}" style="margin-left:${depth * 1.5}rem"><span class="lxbox" aria-hidden="true">${t.status === 2 ? '&#10003;' : ''}</span>
      <div class="lxt"><b>${esc(t.title)}</b>${meta.length ? `<span class="muted"> · ${esc(meta.join(' · '))}</span>` : ''}${notes && t.content ? `<div class="lxn">${esc(t.content)}</div>` : ''}</div></li>`;
  };
  const n = groups.reduce((a, g) => a + g.rows.length, 0);
  return `<h1>${esc(lname(l))}</h1><div class="tssub">${esc(trn('{0} task', '{0} tasks', n))} · ${esc(tr('created {0}', fmtDate(today())))}</div>${lexHead(l, head)}
    ${groups.map(g => `${g.name ? `<h2>${esc(g.name)}</h2>` : ''}<ul class="lxl">${g.rows.map(row).join('')}</ul>`).join('') || `<p class="muted">${tr('No tasks.')}</p>`}`;
}
function lexPrint(lid) {
  const l = listById(lid); if (!l) return;
  $('.tsheet')?.remove();
  /** @type {any} */
  const el = document.createElement('div');
  el.className = 'tsheet';
  let head = l.kind === 'project' ? S.povD?.[lid]?.j || null : null;  // 2.145.0 C (#2432): the project page's data, fresh below
  const draw = () => {
    const done = LS.get('lexDone', true), notes = LS.get('lexNotes', false);
    $('.tspage', el).innerHTML = lexDoc(lid, done, notes, head);
    $('#lex-done', el).checked = done; $('#lex-notes', el).checked = notes;
  };
  el.innerHTML = `<div class="tsbar"><button class="btn pri" data-ts="print">${ic('download', 's')} ${tr('Print / save as PDF')}</button>
    <label class="chkl"><input type="checkbox" id="lex-done"> ${tr('Show completed')}</label><label class="chkl"><input type="checkbox" id="lex-notes"> ${tr('Notes')}</label>
    <span class="spacer"></span><button class="btn" data-ts="close">${tr('Close')}</button></div><div class="tspage lexpage"></div>`;
  document.body.appendChild(el);
  document.body.classList.add('tsprint');
  const close = () => { el.remove(); document.body.classList.remove('tsprint'); document.title = APP_NAME; };
  el.addEventListener('click', ev => {
    const b = ev.target.closest('[data-ts]'); if (!b) return;
    if (b.dataset.ts === 'close') close(); else window.print();
  });
  el.addEventListener('change', ev => {
    if (ev.target.id === 'lex-done') LS.set('lexDone', ev.target.checked);
    else if (ev.target.id === 'lex-notes') LS.set('lexNotes', ev.target.checked);
    else return;
    draw();
  });
  el.addEventListener('keydown', ev => { if (ev.key === 'Escape') close(); });
  draw();
  document.title = lname(l);
  if (l.kind === 'project') rawFetch('GET', `/api/lists/${lid}/overview`).then(j => { head = j; if (el.isConnected) draw(); }, () => {});  // offline / no right: the page without head
}
