// ---- 2.73.0 B (#1473): Settings > Data > "Move and export everything". Export: one ZIP with all of the person's data
// (kalmido/admin/acctexport.py: start, state polled while it runs, download, delete). Import: the ZIP uploaded in pieces,
// checked on the server, a preview with the people (found by e-mail, shared only when ticked) and the target, the run in
// the background, the result with undo (kalmido/admin/acctimport.py). One undo step = the whole import.
const UMZ = {timer: 0, up: null};
const umzHtml = hint => `<h4 id="s-umz-h">${tr('Move and export everything')}</h4>
  ${hint(tr('One file with everything that is yours: projects, tasks, comments, files, calendars, contacts, habits and settings. Use it to move to your own Kalmido server (or back) or as your own copy of your data.'))}
  <div id="s-umz-exp" aria-live="polite"><div class="muted mhint">${tr('Loading…')}</div></div>
  <div class="row"><label for="s-umz-file">${tr('Take over from a Kalmido export')}</label>${fileBtn('s-umz-file', '.zip,application/zip')}${''/* lazy-ok: 2.149.0 F (#2519): settings.js draws this section */}</div>
  <div id="s-umz-imp" aria-live="polite"></div>
  <details class="umzhow"><summary>${tr('Move to your own server')}</summary><ol class="umzsteps">
    <li>${tr('Here: “Export everything” and download the file.')}</li>
    <li>${tr('Set up your own Kalmido server (see SELF-HOSTING.md, section “Moving from and to app.kalmido.com”).')}</li>
    <li>${tr('There: sign in, Settings > Data > “Take over from a Kalmido export”, check the preview and start.')}</li>
    <li>${tr('Invite the people you work with; your projects are shared with them again once you tick them in the preview. Moving back works the same way.')}</li></ol></details>`;
function umzExpHtml(j) {
  const start = lbl => `<button type="button" class="btn sm" data-umz="exp">${ic('download', 's')} ${lbl}</button>`;
  if (j.state === 'running') return `<div class="row"><span class="muted">${tr('The export is being created…')}</span></div>`;
  if (j.state === 'done') return `<div class="row umzdone"><span class="n">${esc(j.file)} <span class="muted">(${esc(fmtSize(j.bytes || 0))}) · ${esc(tr('available until {0}', fmtWhen(j.expires_at)))}</span></span></div>
    <div class="row"><a class="btn sm pri" href="/api/account/export/file" download>${ic('download', 's')} ${tr('Download')}</a><button type="button" class="btn sm" data-umz="exp-del">${ic('trash', 's')} ${tr('Delete now')}</button>${start(tr('Create again'))}</div>`;
  return (j.state === 'failed' ? `<div class="shint keep">${ic('alert', 's')} ${esc(j.error || '')}</div>` : '') + `<div class="row">${start(tr('Export everything'))}</div>`;
}
async function umzExpLoad(md) {
  const box = $('#s-umz-exp', md); if (!box) return;
  let j; try { j = await api('GET', '/api/account/export'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box.innerHTML = umzExpHtml(j);
  if (j.state === 'running') { clearTimeout(UMZ.timer); UMZ.timer = setTimeout(() => { if (box.isConnected) umzExpLoad(md); }, 2500); }
}
const umzCount = (k, n) => ({lists: trn('{0} project', '{0} projects', n), tasks: trn('{0} task', '{0} tasks', n), comments: trn('{0} comment', '{0} comments', n),
  attachments: trn('{0} file', '{0} files', n), list_files: trn('{0} project file', '{0} project files', n), habits: trn('{0} habit', '{0} habits', n),
  events: trn('{0} event', '{0} events', n), contacts: trn('{0} contact', '{0} contacts', n), journal: trn('{0} journal entry', '{0} journal entries', n),
  time_entries: trn('{0} time entry', '{0} time entries', n), templates: trn('{0} template', '{0} templates', n), filters: trn('{0} filter', '{0} filters', n)})[k];
const umzCounts = o => Object.entries(o || {}).filter(([k, n]) => n && umzCount(k, n)).map(([k, n]) => esc(umzCount(k, n))).join(' · ');
function umzPreviewHtml(j) {
  const p = j.preview, org = p.kind === 'org', src = p.source.url ? esc(p.source.url) : tr('unknown');
  const people = p.people.length ? `<div class="muted mhint">${tr('People of your projects')}</div>` + p.people.map((x, i) => `<div class="mrow umzp">
    <span class="n">${esc(x.name || tr('Unknown'))}<br><span class="muted">${x.found ? esc(tr('found: {0}', x.found_name)) : esc(tr('not on this server'))}</span></span>
    ${x.found ? `<label class="umzck"><input type="checkbox" data-umzp="${i}" data-k="share"> <span data-umzsl>${org && p.targets[0]?.id !== 'private' ? tr('Add to the organisation and share the projects') : tr('Share my projects')}</span></label>`
      : p.can_invite ? `<label class="umzck"><input type="checkbox" data-umzp="${i}" data-k="invite"> ${tr('Invite by e-mail')}</label>${x.need_address === false ? '' : `<input type="email" class="umzem" data-umze="${i}" autocomplete="off" placeholder="${esc(tr('Their e-mail address'))}" aria-label="${esc(tr('E-mail address of {0}', x.name || ''))}"><span class="muted umzmis" data-umzm="${i}" hidden>${tr('This is not the address in the file: nobody is invited.')}</span>`}` : `<span class="muted">${tr('Skipped')}</span>`}</div>`).join('')
    + hintK(tr('Nothing is shared without a tick: an address on another server can belong to somebody else here.')) : '';
  const lists = p.lists.length ? `<div class="umzlists">${p.lists.slice(0, 12).map(l => `<div class="mrow"><span class="n">${esc(l.inbox ? tr('Basket') : l.name)}${l.folder ? ` <span class="muted">${esc(l.folder)}</span>` : ''}</span><span class="muted">${trn('{0} task', '{0} tasks', l.tasks)}</span></div>`).join('')}${p.lists.length > 12 ? `<div class="muted mhint">${esc(trn('and {0} more', 'and {0} more', p.lists.length - 12))}</div>` : ''}</div>` : '';
  const notes = [p.again ? `<div class="shint warn" role="alert">${ic('alert', 's')} ${tr('You have imported this export already. Importing it again creates everything a second time.')}</div>` : '',
    p.server_links.length ? hintK(tr('Set up the connection to {0} again (Settings > Account > Servers): access keys never move along.', p.server_links.map(esc).join(', '))) : '',
    p.encrypted.attachments || p.encrypted.locked_notes ? hintK(tr('Encrypted content stays encrypted: you open it with your passwords as before.')) : '',
    (p.taken_areas || []).length ? hintK(tr('Also taken over: {0}', p.taken_areas.map(x => `${esc(x.what)} (${x.count})`).join(', '))) : '',  // 2.137.0 (#2344)
    p.not_taken.length ? hintK(tr('Not taken over: {0}', p.not_taken.map(x => `${esc(x.what)} (${x.count})`).join(', '))) : ''].join('');
  const tgt = p.targets.length > 1 || org ? `<div class="row"><label for="s-umz-tgt">${tr('Into')}</label><select id="s-umz-tgt">${p.targets.map(t => `<option value="${esc(String(t.id))}">${esc(t.id === 'private' ? tr('Private|workspace') : t.name)}</option>`).join('')}</select></div>` : '';
  const none = org && !p.targets.length;  // 2.73.0 B (part 4): an organisation export needs an organisation I administer here
  return `<div class="impbox umzbox" role="status"><div class="imphead"><b>${org ? tr('Organisation export of {0}', esc(p.user.name)) : tr('Export of {0}', esc(p.user.name || p.user.email))}</b></div>
    <div class="muted">${org ? esc(fmtWhen(p.created_at)) : tr('From {0}, created {1}', src, esc(fmtWhen(p.created_at)))}</div>
    <div class="umzcnt">${umzCounts(p.counts)}</div>${lists}${people}${notes}${tgt}
    ${none ? hintK(tr('You are not the admin of an organisation on this server. Create one or ask its admin first.')) : ''}
    <div class="row"><button type="button" class="btn sm pri" data-umz="go" ${none ? 'disabled' : ''}>${ic('download', 's')} ${tr('Start the import')}</button><button type="button" class="btn sm" data-umz="cancel">${tr('Cancel')}</button></div></div>`;
}
// review M1: the file names other people only by a hash of their address; an address typed for an invitation is checked
// against it here (the server checks again in the run)
async function umzHash(em) {
  if (!window.crypto?.subtle) return '';
  const b = await crypto.subtle.digest('SHA-256', new TextEncoder().encode('kalmido-people|' + em.trim().toLowerCase()));
  return [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, '0')).join('');
}
async function umzEmailOk(p, i, em) {
  const h = em.trim() ? await umzHash(em) : '';
  return !h || h === p.people[i].key;
}
function umzResultHtml(j) {
  const r = j.result || {};
  const ppl = (r.people || []).map(x => `<div class="mrow"><span class="n">${esc(x.name || x.email || '')}</span><span class="muted">${esc({shared: tr('Shared'), invited: tr('Invited'), skipped: tr('Skipped'), failed: tr('Not possible'), mismatch: tr('Address does not match')}[x.state] || '')}${x.lists ? ' · ' + esc(trn('{0} project', '{0} projects', x.lists)) : ''}</span></div>`).join('');
  const w = (r.warnings || []).map(x => `<li>${esc(x.text)}${x.count > 1 ? ` (${x.count})` : ''}</li>`).join('');
  return `<div class="impbox umzbox" role="status"><div class="imphead"><b>${esc(r.stopped || tr('Import finished'))}</b></div>
    <div class="umzcnt">${umzCounts(r.created)}</div>${ppl}${w ? `<ul class="impwarn">${w}</ul>` : ''}
    <div class="row">${r.import_id ? `<button type="button" class="btn sm" data-umz="undo" data-id="${+r.import_id}">${tr('Undo this import')}</button><span class="muted">${tr('possible for 24 hours')}</span>` : ''}<button type="button" class="btn sm" data-umz="close">${tr('Close')}</button></div></div>`;
}
function umzImpHtml(j) {
  if (!j) return '';
  const bar = (a, b, lbl) => `<div class="umzbar">${botBusy(`<div class="muted">${lbl}</div><progress max="${b || 1}" value="${a || 0}"></progress>`)}</div>`;  // 2.161.2 (#2611): + the bot at work
  if (j.state === 'upload') return bar(j.received, j.size, tr('Uploading… {0} of {1}', fmtSize(j.received || 0), fmtSize(j.size || 0)))
    + `<div class="row"><button type="button" class="btn sm" data-umz="cancel">${tr('Cancel')}</button></div>`;
  if (j.state === 'checking') return bar(0, 0, tr('Checking the file…'));
  if (j.state === 'preview') return umzPreviewHtml(j);
  if (j.state === 'key') return `<div class="impbox umzbox" role="status"><div class="imphead"><b>${tr('Organisation export of {0}', esc(j.preview?.org || ''))}</b></div>
    <div class="shint">${tr('The file is encrypted. Enter the recovery key of the organisation (on the old server: Settings > Organisation > Encryption).')}</div>
    ${j.error ? `<div class="shint keep" role="alert">${ic('alert', 's')} ${esc(j.error)}</div>` : ''}
    <div class="row"><label for="s-umz-key">${tr('Recovery key')}</label><input id="s-umz-key" type="password" autocomplete="off" spellcheck="false" autocapitalize="characters"></div>
    <div class="row"><button type="button" class="btn sm pri" data-umz="key">${tr('Open')}</button><button type="button" class="btn sm" data-umz="cancel">${tr('Cancel')}</button></div></div>`;
  if (j.state === 'running') return bar(j.progress?.done, j.progress?.total, tr('Importing…'));
  if (j.state === 'done' || j.state === 'stopped') return umzResultHtml(j);
  return `<div class="shint keep" role="alert">${ic('alert', 's')} ${esc(j.error || tr('The import failed.'))}</div><div class="row"><button type="button" class="btn sm" data-umz="cancel">${tr('Close')}</button></div>`;
}
function umzImpDraw(md, j) {
  UMZ.cur = j; const box = $('#s-umz-imp', md); if (!box) return;
  box.innerHTML = umzImpHtml(j);
  if (j && ['checking', 'running'].includes(j.state)) { clearTimeout(UMZ.itimer); UMZ.itimer = setTimeout(() => { if (box.isConnected) umzImpPoll(md); }, 2000); }
}
async function umzImpPoll(md) {
  if (!UMZ.cur) return;
  try { umzImpDraw(md, await api('GET', `/api/account/import/${UMZ.cur.id}`)); } catch { /* api() showed it */ }
}
async function umzUpload(md, file) {
  let j = await api('POST', '/api/account/import', {size: file.size, name: file.name});
  const id = j.id, chunk = j.chunk; let off = 0;
  UMZ.up = id; umzImpDraw(md, {id, state: 'upload', size: file.size, received: 0});
  while (off < file.size) {
    if (UMZ.up !== id) return;  // cancelled
    const part = file.slice(off, Math.min(file.size, off + chunk));
    let r;
    try { r = await fetch(`/api/account/import/${id}?offset=${off}`, {method: 'PUT', body: part, headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/octet-stream'}}); }
    catch { toast(tr('Offline: only works again with a connection')); return; }
    j = await r.json().catch(() => ({}));
    if (!r.ok) { if (r.status === 409 && typeof j.received === 'number') { off = j.received; continue; } toast(j.error || tr('Error {0}', r.status)); umzImpDraw(md, null); return; }
    off += part.size;
    umzImpDraw(md, j);
  }
  UMZ.up = null;
}
function umzInit(md) {
  if (!$('#s-umz-exp', md)) return;
  umzExpLoad(md);
  api('GET', '/api/account/import').then(j => { if (j.current && j.current.state !== 'upload') umzImpDraw(md, j.current); }).catch(() => {});
  $('#s-umz-file', md)?.addEventListener('change', e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) umzUpload(md, f).catch(() => umzImpDraw(md, null)); });
  md.addEventListener('change', async e => {  // review M1: a typed address that is not the one in the file -> hint at once
    if (e.target.id === 's-umz-tgt' && UMZ.cur?.preview?.kind === 'org') {  // 2.96.0 D (#1941): into Private nobody joins an organisation
      const t = e.target.value === 'private' ? tr('Share my projects') : tr('Add to the organisation and share the projects');
      md.querySelectorAll('[data-umzsl]').forEach(x => { x.textContent = t; });
      return;
    }
    const x = e.target.closest?.('[data-umze]'); if (!x || !UMZ.cur?.preview) return;
    const m = $(`[data-umzm="${x.dataset.umze}"]`, md); if (m) m.hidden = await umzEmailOk(UMZ.cur.preview, +x.dataset.umze, x.value);
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-umz]'); if (!b) return;
    const a = b.dataset.umz;
    try {
      if (a === 'exp') { b.disabled = true; await api('POST', '/api/account/export'); return umzExpLoad(md); }
      if (a === 'exp-del') {
        if (!await askConfirm(tr('Delete the export now?'), tr('The file is removed from the server. You can create a new one at any time.'), {ok: tr('Delete'), danger: true})) return;
        await api('DELETE', '/api/account/export'); toast(tr('Deleted')); return umzExpLoad(md);
      }
      if (a === 'cancel') { UMZ.up = null; if (UMZ.cur?.id) await api('DELETE', `/api/account/import/${UMZ.cur.id}`).catch(() => {}); return umzImpDraw(md, null); }
      if (a === 'close') { if (UMZ.cur?.id) await api('DELETE', `/api/account/import/${UMZ.cur.id}`).catch(() => {}); return umzImpDraw(md, null); }
      if (a === 'key') {
        const k = $('#s-umz-key', md)?.value || ''; if (!k.trim()) return;
        b.disabled = true;
        return umzImpDraw(md, await api('POST', `/api/account/import/${UMZ.cur.id}/key`, {recovery_key: k}));
      }
      if (a === 'go') {
        const p = UMZ.cur.preview, people = {};
        for (const x of md.querySelectorAll('[data-umzp]')) {
          if (!x.checked) continue;
          const i = +x.dataset.umzp, k = p.people[i].key, em = $(`[data-umze="${i}"]`, md)?.value.trim() || '';
          if (x.dataset.k === 'invite' && p.people[i].need_address !== false) {
            if (!em) { toast(tr('Type the e-mail address of {0} for the invitation.', p.people[i].name || '')); return; }
            if (!await umzEmailOk(p, i, em)) { const m = $(`[data-umzm="${i}"]`, md); if (m) m.hidden = false; return; }
          }
          people[k] = {...people[k], [x.dataset.k]: true, ...(em ? {email: em} : {})};
        }
        let t = $('#s-umz-tgt', md)?.value || 'private';
        // 2.87.9 (#1940): where the account's data goes, in words; from an organisation also into the private space
        const to = await importTargetConfirm({what: tr('the data of the account'), ws: t === 'private' ? 'private' : 'org:' + t, privOk: true});
        if (!to) return;
        if (to === 'private') t = 'private';
        b.disabled = true;
        return umzImpDraw(md, await api('POST', `/api/account/import/${UMZ.cur.id}/run`, {target: t === 'private' ? 'private' : +t, people, ...(UMZ.cur.preview?.again ? {again: true} : {})}));  // 2.269.0 D (#3046): the warning was shown
      }
      if (a === 'undo') {
        if (!await askConfirm(tr('Undo this import?'), tr('Everything this import created is removed again.'), {ok: tr('Undo'), danger: true})) return;
        const r = await api('POST', `/api/imports/${+b.dataset.id}/undo`);
        toast(trn('{0} task removed', '{0} tasks removed', r.tasks || 0));
        if (UMZ.cur?.id) await api('DELETE', `/api/account/import/${UMZ.cur.id}`).catch(() => {});
        umzImpDraw(md, null); if (typeof load === 'function') load();
      }
    } catch { b.disabled = false; /* api() showed it */ }
  });
}
