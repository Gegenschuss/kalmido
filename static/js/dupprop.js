/* Kalmido web client: 2.70.0 B (#1357) -- tidy up contacts with an agent. "Find duplicates with an agent…" (the contacts
   view's menu, the command palette) asks an agent for a proposal of kind "merge" for one address book the person may change;
   the agent gets only name, company, e-mails and phones. The proposal sheet of agents.js (propOpen / propDraw) shows for this
   kind one row per group: the contacts side by side as they are now (loaded fresh by the server), the agent's reason, the
   main contact (switchable) and its own tick. Groups with a contact that is gone or changed are greyed out and skipped.
   Applying merges the ticked groups as the person (2.66 merge), one undo step takes all of them back (server:
   agents/dupprop.py). Classic script sharing the global scope with the others (load order: index.html). */
'use strict';

const DUP_MAX = 2000;  // contacts of one address book per request (server: DUP_MAX_CONTACTS)
const dup_is = v => v?.kind === 'merge';
const dup_books = () => (S.books || []).filter(b => (b.role === 'owner' || b.role === 'edit') && !b.imported && wsObjIn(b));  // contacts.js loads on demand
function dup_open(bid) {
  if (!propOn()) { toast(tr('Connect an agent first (Settings > Agents)')); return; }
  const books = dup_books();
  if (!books.length) { toast(tr('There is no address book you can change')); return; }
  const pre = books.find(b => b.id === +(bid || (typeof CT !== 'undefined' && CT.book) || 0)) || books[0];
  const md = modal(`<h3>${ic('bot', 's')} ${esc(tr('Find duplicates with an agent'))}</h3>
    ${books.length > 1 ? `<div class="row"><label for="dup-book">${tr('Address book')}</label><select id="dup-book">${books.map(b => `<option value="${b.id}" ${b.id === pre.id ? 'selected' : ''}>${esc(b.name)} (${b.count || 0})</option>`).join('')}</select></div>`
      : `<div class="pptask">${ic('users', 's')}<b>${esc(pre.name)}</b></div><input type="hidden" id="dup-book" value="${pre.id}">`}
    ${propAgentRow()}<div class="shint" id="pp-priv"></div>
    <div class="calerr" role="alert" id="pp-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${ic('bot', 's')} ${tr('Ask for a proposal')}</button></div>`);
  md.classList.add('ppreq', 'dupreq');
  const book = () => books.find(b => b.id === +$('#dup-book', md).value) || pre;
  const err = m => { const e = $('#pp-err', md); e.textContent = m || ''; e.hidden = !m; };
  const priv = () => {  // what exactly leaves: the consent line under the form
    const id = +($('#pp-agent', md)?.value || 0), a = (S.proposers.find(x => x.id === id) || S.proposers[0]), b = book(), n = b.count || 0;
    $('#pp-priv', md).innerHTML = tr('{0} gets the name, company, e-mail addresses and phone numbers of the {1} contacts of this address book, nothing else, and proposes which belong together. Nothing is merged until you apply it.', `<b>${esc(a.name)}</b>`, n.toLocaleString(LOCALE()));
    const ok = $('[data-m="ok"]', md);
    err(n > DUP_MAX ? tr('This address book has more than {0} contacts: split it into smaller address books first', DUP_MAX.toLocaleString(LOCALE())) : n < 2 ? tr('This address book has fewer than two contacts') : '');
    ok.disabled = n > DUP_MAX || n < 2;
  };
  priv();
  md.addEventListener('change', e => { if (e.target.id === 'pp-agent' || e.target.id === 'dup-book') priv(); });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const q = {agent_id: +$('#pp-agent', md).value, kind: 'merge', book_id: book().id};
    b.disabled = true; err('');
    try { await calReq('POST', '/api/proposals', q); } catch (x) { err(x.message); b.disabled = false; return; }
    md.remove();
    toast(tr('Sent to {0} – you will be notified.', (S.proposers.find(a => a.id === q.agent_id) || {}).name || ''));
    if (S.route.mod === 'agents') loadJobs();
  });
  setTimeout(() => $('[data-m="ok"]', md)?.focus(), 50);
}
// ---- the review (agents.js propDraw): keys = the groups that can still be merged
const dup_keys = v => (v.dup_groups || []).filter(g => g.ok).map(g => g.key);
function dup_contactHtml(x, tgt) {
  const st = x.state === 'gone' ? tr('No longer available') : x.state === 'changed' ? tr('Changed since the request') : '';
  return `<div class="dupc ${x.id === tgt ? 'tgt' : ''} ${x.state ? 'dupx' : ''}" data-cid="${x.id}">
    <b>${esc(x.fn || x.org || (x.state === 'gone' ? '–' : '?'))}</b>${x.org && x.org !== x.fn ? `<small>${esc(x.org)}</small>` : ''}
    ${(x.emails || []).map(m => `<small class="muted">${ic('mail', 's')}${esc(m)}</small>`).join('')}
    ${(x.phones || []).map(p => `<small class="muted">${ic('phone', 's')}${esc(p)}</small>`).join('')}
    ${st ? `<small class="dupst">${esc(st)}</small>` : ''}</div>`;
}
function dup_groupHtml(g) {
  const P = S.prop, on = g.ok && P.sel.has(g.key), tgt = P.ed[g.key]?.target_id || g.target_id, live = g.contacts.filter(x => !x.state);
  const names = g.contacts.map(x => x.fn || x.org).filter(Boolean).join(', ');
  return `<div class="ppi dupg ${on ? '' : 'off'} ${g.ok ? '' : 'dupx'}" data-k="${g.key}">
    <label class="ppcl"><input type="checkbox" class="ppc" ${on ? 'checked' : ''} ${g.ok ? '' : 'disabled'} aria-label="${esc(tr('Merge {0}', names))}"></label>
    <div class="ppb"><div class="dupcs">${g.contacts.map(x => dup_contactHtml(x, tgt)).join('')}</div>
      ${g.ok ? `<div class="duprow"><label for="dup-t-${g.key}">${tr('Keep as main contact')}</label><select id="dup-t-${g.key}" data-f="target_id">${live.map(x => `<option value="${x.id}" ${x.id === tgt ? 'selected' : ''}>${esc(x.fn || x.org || '?')}</option>`).join('')}</select></div>`
        : `<div class="muted dupskip">${esc(tr('A contact of this group is gone or changed since the request: it is skipped.'))}</div>`}
      ${g.reason ? `<div class="ppn muted">${esc(tr('Reason: {0}', g.reason))}</div>` : ''}</div></div>`;
}
function dup_draw(v) {
  const p = v.proposal || {}, gs = v.dup_groups || [], book = v.input?.book?.name || '';
  const main = `${p.summary ? `<div class="ppsum">${commentBody(p.summary, {})}</div>` : ''}
    <div class="muted dupbook">${esc(tr('Address book {0}', book))} · ${esc(trn('{0} group', '{0} groups', gs.length))}</div>
    <div class="ppbar"><button class="btn sm" data-pp="all">${tr('Select all')}</button><button class="btn sm" data-pp="none">${tr('Select none')}</button></div>
    <div class="ppl">${gs.length ? gs.map(dup_groupHtml).join('') : `<div class="ppwait">${ic('check')}<p>${esc(tr('{0} found no duplicates in this address book.', v.agent.name))}</p></div>`}</div>
    <div class="shint keep">${esc(tr('Merging keeps the main contact and moves the others into it (e-mails, phones, links), as you. One step, undo takes back every merge of this proposal.'))}</div>`;
  const foot = `<button class="btn danger" data-pp="discard">${tr('Discard')}</button><span class="spacer"></span><span class="muted ppcount ppfc"></span><button class="btn" data-pp="close">${tr('Close')}</button><button class="btn pri" data-pp="apply"></button>`;
  return {main, foot};
}
function dup_count(P) {
  const n = P.sel.size, b = $('[data-pp="apply"]', P.md);
  $$('.ppcount', P.md).forEach(c => { c.textContent = tr('{0} of {1} selected', n, dup_keys(P.v).length); });
  if (b) { b.disabled = !n; b.innerHTML = `${ic('check', 's')} ${esc(trn('Merge {0} group', 'Merge {0} groups', n))}`; }
}
function dup_edit(el) {  // another main contact for a group
  if (!S.prop || !dup_is(S.prop.v) || el.dataset?.f !== 'target_id') return false;
  const row = el.closest('.ppi'), k = row?.dataset.k; if (k === undefined) return true;
  S.prop.ed[k] = {target_id: +el.value};
  $$('.dupc', row).forEach(c => c.classList.toggle('tgt', +c.dataset.cid === +el.value));
  return true;
}
const dup_toast = r => r.skipped ? tr('{0} merged, {1} skipped', trn('{0} group', '{0} groups', r.merged), r.skipped) : trn('{0} group merged', '{0} groups merged', r.merged);
function dup_hist(e) {  // undo / redo: the contacts view shows the result
  const wrap = f => async () => { const x = await f(); if (typeof ctLoad === 'function' && typeof CT !== 'undefined' && CT.items !== null) ctLoad(); return x; };
  e.undo = wrap(e.undo); e.redo = wrap(e.redo);
  if (typeof ctLoad === 'function' && typeof CT !== 'undefined' && CT.items !== null) ctLoad();
}
