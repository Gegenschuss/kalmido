/* Kalmido web client: 2.39.0 (#1168) the Playbook of a list or a folder: how the agents work on the tasks there.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   A Markdown text (at most PB_MAX characters) at a list or at a folder of its owner; a folder's playbook holds for every list
   in it (subfolders inherit), a list's own one adds to it. Every saved text stays as a version (who, when, source); agents
   only propose changes, a person applies or discards them. A list can have regular checks: an agent of the list looks at
   the list at a planned time (the planned jobs of 2.34.0, #272, marked as a list check). */
'use strict';

const PB_MAX = 8000;
const PB_SRC = {edit: N_('edited|playbook'), restore: N_('restored|playbook'), proposal: N_('agent proposal'), import: N_('imported|playbook'), template: N_('from a template')};
// the three examples of the help and of the empty editor (made up, general texts; the person adapts them)
const PB_EX = [
  {k: 'receipts', t: N_('Receipts and insurance refunds'),
    intro: N_('Each task is a receipt (a photo or a mail) that should be refunded by the health insurance.'),
    steps: [N_('Read amount, date and issuer from the attachment and write them into the notes as a short list.'),
      N_('Add the list tag #submitted once the receipt is in the insurance portal; ask in a comment if anything is unclear.'),
      N_('When a refund arrives, compare the amount and complete the task; a difference goes into a comment.')],
    rules: [N_('Never send anything to anyone outside; uploading is done by a person.'), N_('Do not delete attachments.')]},
  {k: 'invoices', t: N_('Incoming invoices'),
    intro: N_('Each task is an invoice that has to be checked and paid.'),
    steps: [N_('Read supplier, invoice number, amount and due date; set the due date of the task to the payment date.'),
      N_('Check whether an order or a contract in this list fits; link it in a comment.'),
      N_('Mark duplicates with a comment instead of closing them.')],
    rules: [N_('Never pay or approve anything yourself; a person does that.'), N_('Ask before changing amounts.')]},
  {k: 'bugs', t: N_('Bug tickets'),
    intro: N_('Each task is an error report for our software.'),
    steps: [N_('Make the title short and clear: where, what happens, what was expected.'),
      N_('Ask in a comment for the missing steps to reproduce, the version and the device.'),
      N_('Set the priority: high for data loss or a blocked login, else medium or low.')],
    rules: [N_('Do not close a ticket without a fix or a reply from the reporter.'), N_('Code changes go through a merge request with a review.')]}];
function pbExText(x) {
  return `## ${tr(x.t)}\n\n${tr(x.intro)}\n\n### ${tr('How to work here')}\n${x.steps.map((s, i) => `${i + 1}. ${tr(s)}`).join('\n')}\n\n### ${tr('Rules')}\n${x.rules.map(s => '- ' + tr(s)).join('\n')}\n`;
}
const pbLen = s => [...String(s || '')].length;  // characters as the server counts them (code points)
const pbUrl = (sc, sub = '') => sc.lid ? `/api/lists/${sc.lid}/playbook${sub}` : `/api/folders/playbook${sub}?folder=${encodeURIComponent(sc.folder)}`;
const pbBody = (sc, b) => sc.lid ? b : {folder: sc.folder, ...b};
const pbTitle = sc => sc.lid ? lname(listById(sc.lid) || {name: ''}) : fDisp(sc.folder);
const pbWho = by => by ? esc(by.name || '') + (by.kind === 'agent' ? ' ' + agentBadge() : '') : '';
const pbWhen = iso => typeof schedWhen === 'function' ? schedWhen(iso) : fmtWhen(iso);
// the area: with agents (a folder too), and in a list with a playbook also for members who do not see its agent (they read
// it); the menu entry: with a playbook, or for those who may write one
const pbOn = l => agentsOn() || (collab() && !!l?.playbook);
function pbMenuItem(l) {
  if (!l || !pbOn(l) || l.is_inbox || l.archived) return null;
  if (l.playbook) return {label: tr('Playbook'), icon: 'book', cls: 'mplaybook', fn: () => pbOpen(l.id)};
  return canManage(l) && listAgents(l).length ? {label: tr('Playbook…'), icon: 'book', cls: 'mplaybook', rare: 1, fn: () => pbOpen(l.id)} : null;
}

// ---- a small line diff (longest common subsequence over the lines; very long texts: the changed middle as removed + added)
function pbDiff(a, b) {
  const A = String(a || '').split('\n'), B = String(b || '').split('\n');
  let s = 0; while (s < A.length && s < B.length && A[s] === B[s]) s++;
  let e = 0; while (e < A.length - s && e < B.length - s && A[A.length - 1 - e] === B[B.length - 1 - e]) e++;
  const a1 = A.slice(s, A.length - e), b1 = B.slice(s, B.length - e), mid = [];
  if (a1.length * b1.length > 1500000) { a1.forEach(x => mid.push(['-', x])); b1.forEach(x => mid.push(['+', x])); }
  else {
    const n = a1.length, m = b1.length, L = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = a1[i] === b1[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    let i = 0, j = 0;
    while (i < n && j < m) { if (a1[i] === b1[j]) { mid.push([' ', a1[i]]); i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) mid.push(['-', a1[i++]]); else mid.push(['+', b1[j++]]); }
    while (i < n) mid.push(['-', a1[i++]]); while (j < m) mid.push(['+', b1[j++]]);
  }
  return [...A.slice(0, s).map(x => [' ', x]), ...mid, ...A.slice(A.length - e).map(x => [' ', x])];
}
function pbDiffHtml(a, b) {
  const d = pbDiff(a, b), add = d.filter(x => x[0] === '+').length, del = d.filter(x => x[0] === '-').length;
  if (!add && !del) return `<div class="muted mhint">${tr('No differences.')}</div>`;
  // long unchanged stretches fold to "…" (three lines of context around each change)
  const near = d.map((x, i) => x[0] !== ' ' || d.slice(Math.max(0, i - 3), i + 4).some(y => y[0] !== ' '));
  let h = '', gap = false;
  d.forEach(([t, x], i) => {
    if (!near[i]) { if (!gap) h += `<div class="pbd gap" aria-hidden="true">…</div>`; gap = true; return; }
    gap = false;
    const cls = t === '+' ? 'add' : t === '-' ? 'del' : '';
    h += `<div class="pbd ${cls}"><span class="pbdm" aria-hidden="true">${t === ' ' ? '' : t === '+' ? '+' : '−'}</span><span class="sr">${t === '+' ? tr('added:') : t === '-' ? tr('removed:') : ''}</span><span class="pbdx">${esc(x) || '&nbsp;'}</span></div>`;
  });
  return `<div class="pbdsum muted">${esc(tr('Lines: {0} added, {1} removed', add, del))}</div><div class="pbdiff" role="group" aria-label="${esc(tr('Changes'))}">${h}</div>`;
}

// ---- the area in the list dialog / folder dialog / its own dialog
function pbAreaHtml(kind) {
  return `<h4 id="pb-h-${kind}">${tr('Playbook')}</h4><div class="pbarea" id="pb-area" aria-labelledby="pb-h-${kind}"><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
function pbPrevHtml(j, sc) {
  const parts = (j.folders || []).filter(f => (f.text || '').trim()).map(f => `<div class="pbpart pbinh"><div class="pbparth">${ic('folder', 's')} ${esc(tr('From the folder {0}', fDisp(f.folder)))} <span class="muted">· ${tr('read only here')}</span></div><div class="md">${renderMd(f.text, true)}</div></div>`);
  if ((j.text || '').trim()) parts.push(`<div class="pbpart pbown">${parts.length ? `<div class="pbparth">${ic(sc.lid ? 'list' : 'folder', 's')} ${esc(sc.lid ? tr('This list adds') : tr('This folder adds'))}</div>` : ''}<div class="md">${renderMd(j.text, true, sc.lid ? {lid: sc.lid} : {})}</div></div>`);
  return parts.length ? `<div class="pbprev">${parts.join('')}</div>` : `<div class="muted mhint pbempty">${esc(j.can_edit ? tr('No playbook yet. Describe how agents should work on the tasks here.') : tr('No playbook yet.'))}</div>`;
}
function pbAreaDraw(box, j, sc) {
  const l = sc.lid ? listById(sc.lid) : null;
  const hint = sc.lid ? tr('The playbook tells the agents of this list how to work here. Every agent event from this list brings it along; rights and approvals stay as they are.')
    : tr('Applies to all lists in this folder and its subfolders; a list’s own playbook adds to it.');
  const props = (j.proposals || []).map(p => `<div class="pbprop" data-pbp="${p.id}">${ic('bot', 's')}<span class="pbpropt"><b>${esc(tr('Proposal from {0}', p.agent?.name || ''))}</b>${p.note ? `<small class="muted">${esc(p.note)}</small>` : ''}<small class="muted">${esc(relTime(p.created_at))}</small></span><button type="button" class="btn sm pri" data-pb="prop" data-pbp="${p.id}">${tr('Open')}</button></div>`).join('');
  const checks = j.checks || [];
  const ckLine = sc.lid && j.can_edit ? `<div class="pbckline muted">${ic('clock', 's')} <span>${checks.length ? esc(checks.map(c => `${c.agent?.name || ''}: ${schedRhythm(c)}${c.enabled ? '' : ' (' + tr('paused') + ')'}`).join(' · ')) : esc(tr('No regular check yet.'))}</span></div>` : '';
  box.innerHTML = `<div class="shint lhint ${sc.folder ? 'keep' : ''}">${esc(hint)}${sc.folder && (j.lists || []).length ? ' ' + esc(trn('Currently {0} list in it.', 'Currently {0} lists in it.', j.lists.length)) : ''}</div>
    ${l && l.life === 'health' ? `<div class="shint keep lhint">${ic('lock', 's')} ${esc(tr('Health lists never reach an agent: this playbook is kept, but not sent.'))}</div>` : ''}
    ${props}${pbPrevHtml(j, sc)}
    ${j.version ? `<div class="pbmeta muted">${esc(tr('Version {0}', j.version))}${j.updated_at ? ' · ' + esc(pbWhen(j.updated_at)) : ''}${j.updated_by ? ' · ' + pbWho(j.updated_by) : ''}</div>` : ''}
    ${ckLine}
    <div class="row pbbtns">${j.can_edit ? `<button type="button" class="btn sm" data-pb="edit">${ic('edit', 's')} ${tr('Edit')}</button>` : `<span class="muted pbro">${ic('lock', 's')} ${esc(sc.lid ? tr('Only the owner and list admins can change it.') : tr('Only the owner of the folder can change it.'))}</span>`}
      ${j.version ? `<button type="button" class="btn sm" data-pb="versions">${ic('clock', 's')} ${tr('Versions')}</button>` : ''}
      ${sc.lid && j.can_edit ? `<button type="button" class="btn sm" data-pb="checks">${ic('repeat', 's')} ${tr('Regular check…')}</button>` : ''}</div>`;
}
// mounts the area into dialog md (box #pb-area); sub-dialogs open over md (modalSub) and refresh the area when they close
function pbMount(md, sc, o = {}) {
  const box = $('#pb-area', md); if (!box) return;
  let j = null;
  const reload = async (after) => {
    try { j = await api('GET', pbUrl(sc)); } catch (e) { box.innerHTML = `<div class="muted mhint">${esc(e instanceof Offline ? tr('Only available online.') : e.message)}</div>`; return; }
    if (!box.isConnected) return;
    pbAreaDraw(box, j, sc); after?.();
  };
  const changed = async () => { await reload(); load().then(render).catch(() => {}); };  // the list's playbook flag (menu entry)
  box.onclick = e => {
    const b = e.target.closest('[data-pb]'); if (!b || !j) return;
    e.stopPropagation();
    const a = b.dataset.pb;
    if (a === 'edit') modalSub(md, () => pbEditor(sc, j, changed));
    else if (a === 'versions') modalSub(md, () => pbVersions(sc, j, changed));
    else if (a === 'checks') modalSub(md, () => pbChecks(sc.lid, reload));
    else if (a === 'prop') { const p = (j.proposals || []).find(x => x.id === +b.dataset.pbp); if (p) modalSub(md, () => pbProposal(sc, j, p, changed)); }
  };
  reload(() => {
    if (o.focus === 'proposals' && (j.proposals || []).length) {
      const p = (j.proposals || []).find(x => x.id === +o.proposal) || j.proposals[0];
      modalSub(md, () => pbProposal(sc, j, p, changed));
    } else if (o.focus === 'proposals') toast(tr('No open proposals'));
  });
}
// its own dialog: from the list menu and from News
function pbOpen(lid, o = {}) {
  const l = listById(lid); if (!l) return;
  const md = modal(`<div class="lhdr"><h3>${ic('book', 's')} ${esc(tr('Playbook: {0}', lname(l)))}</h3><span class="spacer"></span><button class="iconbtn" data-pbx="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="pbarea" id="pb-area"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-pbx="close">${tr('Done')}</button></div>`);
  md.classList.add('pbmodal');
  md.addEventListener('click', e => { if (e.target.closest('[data-pbx="close"]')) md.remove(); });
  pbMount(md, {lid}, o);
  return md;
}

// ---- the editor: Markdown with a preview, x / 8000, Save / Cancel; saved meanwhile elsewhere -> a clear message
function pbEditor(sc, j, done) {
  let base = j.version || 0, mode = 'edit';
  const md = modal(`<h3>${ic('book', 's')} ${esc(tr('Playbook: {0}', pbTitle(sc)))}</h3>
    <div class="shint keep lhint">${esc(sc.lid ? tr('How should agents work on the tasks of this list? Steps, rules, what they must not do. Markdown: # heading, - list, **bold**.') : tr('Applies to all lists in this folder. Markdown: # heading, - list, **bold**.'))}</div>
    ${(j.folders || []).some(f => (f.text || '').trim()) ? `<div class="shint keep lhint">${ic('folder', 's')} ${esc(tr('Adds to the playbook of the folder {0}; the preview shows both.', fDisp(j.folders[j.folders.length - 1].folder)))}</div>` : ''}
    <div class="pbedbar"><div class="seg pbmode" role="group" aria-label="${esc(tr('Mode'))}"><button type="button" data-pbm="edit" class="on" aria-pressed="true">${tr('Edit')}</button><button type="button" data-pbm="prev" aria-pressed="false">${tr('Preview')}</button></div>
      <span class="spacer"></span><button type="button" class="btn sm" data-pe="ex" aria-haspopup="menu">${ic('bulb', 's')} ${tr('Insert an example')}</button></div>
    <textarea id="pb-text" class="pbtext" rows="14" aria-label="${esc(tr('Playbook'))}" placeholder="${esc(tr('e.g. how to work here: steps, rules, what agents must not do'))}">${esc(j.text || '')}</textarea>
    <div class="pbprevw" id="pb-prev" hidden></div>
    <div class="row pbcntrow"><span class="spacer"></span><span class="muted pbcnt" id="pb-cnt" aria-live="polite"></span></div>
    <div class="calerr" role="alert" id="pb-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-pe="cancel">${tr('Cancel')}</button><button type="button" class="btn pri" data-pe="save">${tr('Save')}</button></div>`);
  md.classList.add('pbedmd');
  const ta = $('#pb-text', md); let start = j.text || '';
  const close = modalGuard(md, () => ta.value !== start);
  const cnt = () => {
    const n = pbLen(ta.value), over = n > PB_MAX, c = $('#pb-cnt', md);
    c.textContent = tr('{0} / {1} characters', n, PB_MAX); c.classList.toggle('over', over);
    $('[data-pe="save"]', md).disabled = over;
    $('[data-pe="ex"]', md).hidden = !!ta.value.trim();
    return over;
  };
  cnt();
  ta.addEventListener('input', cnt);
  const err = h => { const e = $('#pb-err', md); e.innerHTML = h; e.hidden = !h; };
  const setMode = m => {
    mode = m;
    $$('[data-pbm]', md).forEach(b => { b.classList.toggle('on', b.dataset.pbm === m); b.setAttribute('aria-pressed', String(b.dataset.pbm === m)); });
    ta.hidden = m !== 'edit'; const pv = $('#pb-prev', md); pv.hidden = m === 'edit';
    if (m !== 'edit') pv.innerHTML = pbPrevHtml({...j, text: ta.value, can_edit: true}, sc);
    else ta.focus();
  };
  const save = async (force) => {
    if (cnt()) { err(esc(tr('At most {0} characters', PB_MAX))); return; }
    const b = $('[data-pe="save"]', md); b.disabled = true; err('');
    try {
      await rawFetch('PUT', pbUrl(sc).split('?')[0], pbBody(sc, {text: ta.value, ...(force || base ? {base_version: force || base} : {})}));
    } catch (e) {
      b.disabled = false;
      if (e.status === 409) {
        base = e.data?.current_version || base;
        err(`<b>${esc(tr('Changed in the meantime'))}</b> ${esc(tr('Someone saved a newer version while you were writing.'))}
          <span class="pbconfl"><button type="button" class="btn sm" data-pe="reload">${ic('sync', 's')} ${tr('Reload')}</button><button type="button" class="btn sm" data-pe="mine">${tr('Save mine anyway')}</button></span>`);
        return;
      }
      err(esc(e instanceof Offline ? tr('Only available online.') : e.message)); return;
    }
    toast(tr('Playbook saved')); md.remove(); done?.();
  };
  md.addEventListener('click', async e => {
    const m = e.target.closest('[data-pbm]'); if (m) { setMode(m.dataset.pbm); return; }
    const b = e.target.closest('[data-pe]'); if (!b) return;
    const a = b.dataset.pe;
    if (a === 'cancel') close();
    else if (a === 'save') save();
    else if (a === 'mine') save(base);
    else if (a === 'reload') {
      if (ta.value !== start && !await askConfirm(tr('Load the newest version?'), tr('Your text in the field is replaced by the newest version.'), {ok: tr('Reload')})) return;
      let n; try { n = await api('GET', pbUrl(sc)); } catch { return; }
      Object.assign(j, n); base = n.version || 0; ta.value = start = n.text || ''; err(''); cnt(); if (mode !== 'edit') setMode(mode);
    } else if (a === 'ex') menu(b, PB_EX.map(x => ({label: tr(x.t), icon: 'bulb', fn: () => { ta.value = (ta.value.trim() ? ta.value.replace(/\s*$/, '\n\n') : '') + pbExText(x); cnt(); setMode('edit'); }})));
  });
  setTimeout(() => ta.focus(), 50);
  return md;
}

// ---- versions: who, when, source, characters; view one, compare it with the current text, restore it (asks first)
async function pbVersions(sc, j, done) {
  let vs; try { vs = (await api('GET', pbUrl(sc, '/versions'))).versions || []; } catch { return null; }
  const md = modal('<div class="pbvbody"></div>');
  md.classList.add('pbvmd');
  const body = $('.pbvbody', md), cur = j.version;
  const listHtml = () => `<h3>${ic('clock', 's')} ${esc(tr('Versions: {0}', pbTitle(sc)))}</h3>
    <div class="pbvlist">${vs.length ? vs.map(v => `<div class="pbvrow" data-v="${v.version}"><div class="pbvi"><b>${esc(tr('Version {0}', v.version))}</b>${v.version === cur ? ` <span class="pbcur">${tr('current')}</span>` : ''}
        <small class="muted">${esc(pbWhen(v.created_at))}${v.by ? ' · ' : ''}${pbWho(v.by)} · ${esc(tr(PB_SRC[v.source] || v.source || ''))} · ${esc(trn('{0} character', '{0} characters', v.chars || 0))}</small></div>
      <div class="pbvb"><button type="button" class="btn sm" data-pv="view">${tr('Show')}</button>${v.version !== cur ? `<button type="button" class="btn sm" data-pv="cmp">${tr('Compare')}</button>${j.can_edit ? `<button type="button" class="btn sm" data-pv="restore">${ic('undo', 's')} ${tr('Restore')}</button>` : ''}` : ''}</div></div>`).join('')
      : `<div class="muted mhint">${tr('No versions yet.')}</div>`}</div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-pv="close">${tr('Close')}</button></div>`;
  const one = async v => { try { return await api('GET', pbUrl(sc, '/versions/' + v)); } catch { return null; } };
  body.innerHTML = listHtml();
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-pv]'); if (!b) return;
    const a = b.dataset.pv, v = +(b.closest('[data-v]')?.dataset.v || 0);
    if (a === 'close') { md.remove(); return; }
    if (a === 'back') { body.innerHTML = listHtml(); return; }
    if (a === 'view' || a === 'cmp') {
      const x = await one(v); if (!x || !md.isConnected) return;
      body.innerHTML = `<h3>${esc(tr('Version {0}', v))}</h3><div class="muted pbmeta">${esc(pbWhen(x.created_at))}${x.by ? ' · ' : ''}${pbWho(x.by)} · ${esc(tr(PB_SRC[x.source] || x.source || ''))}</div>
        ${a === 'view' ? `<div class="pbprev"><div class="pbpart"><div class="md">${(x.text || '').trim() ? renderMd(x.text, true) : `<p class="muted">${tr('Empty text')}</p>`}</div></div></div>`
          : `<div class="shint keep lhint">${esc(tr('From version {0} to the current text:', v))}</div>${pbDiffHtml(x.text, j.text)}`}
        <div class="foot"><button type="button" class="btn" data-pv="back">${ic('back', 's')} ${tr('Back')}</button><span class="spacer"></span>${j.can_edit && v !== cur ? `<button type="button" class="btn" data-v="${v}" data-pv="restore">${ic('undo', 's')} ${tr('Restore')}</button>` : ''}</div>`;
      return;
    }
    if (a === 'restore') {
      if (!await askConfirm(tr('Restore version {0}?', v), tr('Its text becomes the playbook again, as a new version. The current text stays in the versions.'), {ok: tr('Restore')})) return;
      try { await api('POST', pbUrl(sc, '/restore').split('?')[0], pbBody(sc, {version: v})); } catch { return; }
      toast(tr('Version {0} restored', v)); md.remove(); done?.();
    }
  });
  return md;
}

// ---- an agent's proposal: what changes against the current text, apply (optionally edited first) or discard
function pbProposal(sc, j, p, done) {
  const md = modal(`<h3>${ic('bot', 's')} ${esc(tr('Proposal from {0}', p.agent?.name || ''))}</h3>
    <div class="muted pbmeta">${esc(pbWhen(p.created_at))}</div>
    ${p.note ? `<blockquote class="pbnote">${esc(p.note)}</blockquote>` : ''}
    ${p.base_version && j.version && p.base_version !== j.version ? `<div class="shint keep lhint">${ic('alert', 's')} ${esc(tr('Written for version {0}; the playbook changed since then. Check the changes carefully.', p.base_version))}</div>` : ''}
    <div class="shint keep lhint">${esc(tr('Changes against the current playbook:'))}</div>
    <div id="pb-pdiff">${pbDiffHtml(j.text, p.text)}</div>
    <details class="sdet pbpedit"><summary>${tr('Edit before applying')}</summary><textarea id="pb-ptext" class="pbtext" rows="10" aria-label="${esc(tr('Playbook'))}">${esc(p.text || '')}</textarea><div class="muted pbcnt" id="pb-pcnt"></div></details>
    <div class="calerr" role="alert" id="pb-perr" hidden></div>
    <div class="foot"><button type="button" class="btn" data-pp="discard">${ic('x', 's')} ${tr('Discard')}</button><span class="spacer"></span><button type="button" class="btn" data-pp="close">${tr('Later')}</button><button type="button" class="btn pri" data-pp="apply">${ic('check', 's')} ${tr('Apply')}</button></div>`);
  md.classList.add('pbpmd');
  const ta = $('#pb-ptext', md);
  const cnt = () => { const n = pbLen(ta.value), c = $('#pb-pcnt', md); c.textContent = tr('{0} / {1} characters', n, PB_MAX); c.classList.toggle('over', n > PB_MAX); $('[data-pp="apply"]', md).disabled = n > PB_MAX; $('#pb-pdiff', md).innerHTML = pbDiffHtml(j.text, ta.value); };
  cnt(); ta.addEventListener('input', cnt);
  const close = modalGuard(md, () => ta.value !== (p.text || ''));
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-pp]'); if (!b) return;
    const a = b.dataset.pp, er = $('#pb-perr', md);
    if (a === 'close') { close(); return; }
    if (a === 'discard' && !await askConfirm(tr('Discard this proposal?'), tr('{0} learns that it was discarded. The playbook stays as it is.', p.agent?.name || ''), {ok: tr('Discard'), danger: true})) return;
    b.disabled = true;
    try { await rawFetch('POST', `/api/lists/${sc.lid}/playbook/proposals/${p.id}/${a}`, a === 'apply' && ta.value !== (p.text || '') ? {text: ta.value} : {}); }
    catch (x) { b.disabled = false; er.textContent = x instanceof Offline ? tr('Only available online.') : x.message; er.hidden = false; return; }
    toast(a === 'apply' ? tr('Proposal applied') : tr('Proposal discarded')); md.remove(); done?.();
  });
  return md;
}

// ---- regular checks of a list: an agent of the list looks at it at a planned time (the planned jobs of #272)
async function pbChecks(lid, done) {
  const l = listById(lid);
  let j; try { j = await api('GET', `/api/lists/${lid}/checks`); } catch { return null; }
  const md = modal('<div class="schedbody pbckbody"></div>');
  md.classList.add('schedmd', 'pbckmd');
  const box = $('.pbckbody', md);
  const row = c => {
    const last = c.last_state ? tr(SCHED_LAST[c.last_state] || c.last_state) + (c.last_at ? ' · ' + schedWhen(c.last_at) : '') : '';
    return `<div class="schedrow ${c.enabled ? '' : 'off'}" data-cid="${c.id}"><div class="schedi"><b>${esc(c.agent?.name || '')}</b>
      <small class="muted">${esc(schedRhythm(c))}${c.prompt ? ' · ' + esc(c.prompt.slice(0, 80)) : ''}${c.by ? ' · ' + esc(tr('by {0}', c.by.name)) : ''}</small>
      <small class="${c.enabled ? '' : 'muted'}">${esc(schedNext(c))}${last ? ` <span class="muted">· ${esc(tr('last: {0}', last))}</span>` : ''}</small></div>
      <div class="schedb"><label class="chkl schedon" title="${esc(tr('Active'))}"><input type="checkbox" data-ck="toggle" ${c.enabled ? 'checked' : ''} aria-label="${esc(tr('Active: {0}', c.agent?.name || ''))}"></label>
        <button type="button" class="btn sm" data-ck="run" ${c.enabled ? '' : 'disabled'}>${ic('play', 's')} ${tr('Check now')}</button>
        <button type="button" class="btn sm" data-ck="edit" aria-label="${esc(tr('Edit'))}">${ic('edit', 's')}<span class="schedtx"> ${tr('Edit')}</span></button>
        <button type="button" class="btn sm danger" data-ck="del" aria-label="${esc(tr('Delete'))}">${ic('trash', 's')}</button></div></div>`;
  };
  const draw = () => {
    box.onclick = null;
    box.innerHTML = `<h3>${ic('repeat', 's')} ${esc(tr('Regular check: {0}', lname(l || {name: ''})))}</h3>
      <div class="shint">${esc(tr('At the planned time the agent looks at the open tasks of this list according to the playbook, also without anything new happening (e.g. compare receipts with the bank account).'))}</div>
      <div class="schedlist">${(j.checks || []).length ? j.checks.map(row).join('') : `<div class="muted mhint">${esc(tr('No regular check yet.'))}</div>`}</div>
      ${(j.agents || []).length ? '' : `<div class="shint keep">${esc(tr('Give this list an agent first (Share > Agents).'))}</div>`}
      <div class="foot"><span class="spacer"></span><button class="btn" data-ck="close">${tr('Close')}</button>${(j.agents || []).length ? `<button class="btn pri" data-ck="new" ${(j.checks || []).length >= (j.max || 5) ? 'disabled' : ''}>${ic('plus', 's')} ${tr('New check')}</button>` : ''}</div>`;
  };
  const reload = async () => { try { j = await api('GET', `/api/lists/${lid}/checks`); } catch { /* shown */ } if (md.isConnected) draw(); };
  draw();
  onRemove(md, () => done?.());
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-ck]'); if (!b || b.dataset.ck === 'toggle' || !box.contains(b) || box.onclick) return;
    const cid = +(b.closest('[data-cid]')?.dataset.cid || 0), c = (j.checks || []).find(x => x.id === cid);
    if (b.dataset.ck === 'close') md.remove();
    else if (b.dataset.ck === 'new') pbCheckForm(box, lid, j, null, reload);
    else if (b.dataset.ck === 'edit' && c) pbCheckForm(box, lid, j, c, reload);
    else if (b.dataset.ck === 'del' && c) {
      if (!await askConfirm(tr('Delete this check?'), c.agent?.name || '', {ok: tr('Delete'), danger: true})) return;
      try { await api('DELETE', `/api/list-checks/${cid}`); toast(tr('Deleted')); } catch { return; }
      await reload();
    } else if (b.dataset.ck === 'run' && c) {
      b.disabled = true;
      try { await api('POST', `/api/list-checks/${cid}/run`); toast(tr('Sent to {0}', c.agent?.name || '')); } catch { b.disabled = false; return; }
      await reload();
    }
  });
  md.addEventListener('change', async e => {
    const x = e.target.closest('[data-ck="toggle"]'); if (!x) return;
    const cid = +x.closest('[data-cid]').dataset.cid;
    try { await api('PATCH', `/api/list-checks/${cid}`, {enabled: x.checked}); } catch { x.checked = !x.checked; return; }
    await reload();
  });
  return md;
}
// the form (new or change) in the same dialog, the rhythm as in the planned jobs; "Cancel" goes back to the list
function pbCheckForm(box, lid, j, c, done) {
  const isNew = !c, ags = j.agents || [];
  const tz = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch { return ''; } })();
  const v = c ? {...c, agent_id: c.agent?.id} : {agent_id: ags[0]?.id, freq: 'daily', days: [1], time: '07:00', prompt: '', enabled: true};
  box.innerHTML = `<h3>${ic('repeat', 's')} ${esc(isNew ? tr('New regular check') : tr('Edit check'))}</h3>
    <div class="row"><label for="pc-ag">${tr('Agent')}</label><select id="pc-ag">${ags.map(a => `<option value="${a.id}" ${a.id === v.agent_id ? 'selected' : ''}>${esc(a.name)}</option>`).join('')}${v.agent_id && !ags.some(a => a.id === v.agent_id) ? `<option value="${v.agent_id}" selected>${esc(c?.agent?.name || '?')}</option>` : ''}</select></div>
    <div class="row schedrh"><label for="pc-freq">${tr('Repeat')}</label><select id="pc-freq">${Object.keys(SCHED_FREQ).map(f => `<option value="${f}" ${v.freq === f ? 'selected' : ''}>${esc(tr(SCHED_FREQ[f]))}</option>`).join('')}</select>
      <span class="schedwd" id="pc-wd" role="group" aria-label="${esc(tr('Weekdays'))}">${[1, 2, 3, 4, 5, 6, 7].map(i => `<label class="chkl"><input type="checkbox" data-wd="${i}" ${(v.days || []).includes(i) ? 'checked' : ''}> ${esc(schedWd(i))}</label>`).join('')}</span>
      <input id="pc-dom" type="number" min="1" max="31" value="${v.freq === 'monthly' ? (v.days || [1])[0] : 1}" aria-label="${esc(tr('Day of the month'))}">
      <label for="pc-time" class="sr">${tr('Time')}</label>${timeIn('pc-time', v.time, {label: tr('Time'), clear: false})}</div>
    <div class="row ppcol"><label for="pc-prompt">${tr('Job (optional)')}</label><textarea id="pc-prompt" rows="3" maxlength="4000" placeholder="${esc(tr('Check the list according to the playbook'))}">${esc(v.prompt || '')}</textarea></div>
    <div class="row"><label class="chkl"><input type="checkbox" id="pc-on" ${v.enabled ? 'checked' : ''}> ${tr('Active')}</label></div>
    <div class="shint">${esc(tr('The agent gets the playbook and the open tasks of the list at the planned time. Times in your time zone ({0}).', c?.tz || tz || '–'))}</div>
    <div class="calerr" role="alert" id="pc-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-pf="back">${tr('Cancel')}</button><button class="btn pri" data-pf="save">${tr('Save')}</button></div>`;
  const vis = () => { const f = $('#pc-freq', box).value; $('#pc-wd', box).hidden = f !== 'weekly'; $('#pc-dom', box).hidden = f !== 'monthly'; };
  vis(); $('#pc-freq', box).addEventListener('change', vis);
  box.onclick = async e => {
    const b = e.target.closest('[data-pf]'); if (!b) return;
    e.stopPropagation();
    if (b.dataset.pf === 'back') { box.onclick = null; done(); return; }
    const f = $('#pc-freq', box).value;
    const d = {agent_id: +$('#pc-ag', box).value, freq: f, time: $('#pc-time', box).value || '07:00', prompt: $('#pc-prompt', box).value.trim(), enabled: $('#pc-on', box).checked,
      days: f === 'weekly' ? $$('[data-wd]:checked', box).map(x => +x.dataset.wd) : f === 'monthly' ? [Math.max(1, Math.min(31, +$('#pc-dom', box).value || 1))] : []};
    if (isNew && tz) d.tz = tz;
    const er = $('#pc-err', box), fail = m => { er.textContent = m; er.hidden = false; };
    if (!d.agent_id) return fail(tr('Give this list an agent first (Share > Agents).'));
    if (f === 'weekly' && !d.days.length) return fail(tr('Pick at least one weekday'));
    b.disabled = true;
    try { await rawFetch(isNew ? 'POST' : 'PATCH', isNew ? `/api/lists/${lid}/checks` : `/api/list-checks/${c.id}`, d); }
    catch (x) { b.disabled = false; return fail(x instanceof Offline ? tr('Only available online.') : x.message); }
    toast(tr('Saved')); box.onclick = null; done();
  };
}

// ---- help (Settings > Agents): the word in one sentence and the three examples to copy
function pbHelpHtml() {
  return `<details class="shelp sdet pbhelp" id="s-pbhelp"><summary>${tr('Playbook: a list’s working instructions for its agents.')}</summary>
    <p>${esc(tr('A playbook is a Markdown text at a list or a folder that tells agents how to work on its tasks; every agent event from the list brings it along. Only the owner and list admins change it (in the list settings); agents can only propose changes. Rights and approvals stay as they are.'))}</p>
    ${PB_EX.map(x => `<div class="pbex"><div class="pbexh"><b>${esc(tr(x.t))}</b><span class="spacer"></span><button type="button" class="btn sm" data-pbcopy="${x.k}">${ic('copy', 's')} ${tr('Copy')}</button></div><pre class="pbexpre">${esc(pbExText(x))}</pre></div>`).join('')}</details>`;
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-pbcopy]'); if (!b) return;
  const x = PB_EX.find(y => y.k === b.dataset.pbcopy); if (!x) return;
  toast(await clipCopy(pbExText(x)) ? tr('Copied') : tr('Copy failed, select the text by hand'));
});
// ---- News: an agent proposed a change (kind playbook_proposal)
const pbNewsText = (it, who, q) => tr('{0} proposes a change to the playbook of {1}', who, q(newsListName(it)));
function pbNewsOpen(it) {
  const lid = it.list_id || it.data?.list_id;
  if (!lid || !listById(lid)) { toast(tr('List not found')); return; }
  pbOpen(lid, {focus: 'proposals', proposal: it.data?.proposal_id});
}
if (typeof NEWS_ICON === 'object') NEWS_ICON.playbook_proposal = 'book';
