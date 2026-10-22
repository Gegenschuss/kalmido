/* Kalmido web client: 2.70.0 A (#1354) -- a meeting becomes tasks. The chat with an agent that takes proposal requests
   from me offers "Turn a meeting into tasks" (a button next to the clip): the dialog of the proposal kind "extract"
   (Tasks from notes) with this agent chosen, a list (one I may write in, never a health list), the notes and up to
   MTG_IMG photos (the phone's camera via accept="image/*"). The photos are stored as my files in my chat with that agent
   (POST /api/agents/{id}/meeting-images), the request carries their ids. The list menu's "Tasks from notes" opens the same
   dialog (agents.js propRequest). When the proposal is ready, the chat shows ONE card per proposal: each task with its
   assignee and date and a tick, "Create selected" (the same apply as the review dialog: as me, one undo step), "Discard"
   and "Edit" (the review dialog). Server: kalmido/agents/meetprop.py.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const MTG_IMG = 4, MTG_IMG_MB = 50;
S.mtg = {};      // agent id -> its ready "extract" proposals for me (the chat's cards)
S.mtgSel = {};   // proposal id -> Set of the ticked task keys
const mtg_ok = aid => typeof propOn === 'function' && propOn() && (S.proposers || []).some(a => a.id === +aid);
const mtg_lists = () => S.lists.filter(l => !l.archived && l.life !== 'health' && l.life !== 'budget' && !l.e2e && canEditList(l.id));  // 2.64.1 (#1817): no list with the lock

// the entry in the chat's input line (only for an agent that takes my proposal requests)
function mtg_btnHtml(a) {
  if (!a?.enabled || !mtg_ok(a.id)) return '';
  const t = tr('Turn a meeting into tasks');
  return `<button type="button" class="iconbtn mtgbtn" data-mtg="open" data-aid="${a.id}" title="${esc(t)}" aria-label="${esc(t)}">${ic('list')}</button>`;
}

// the request dialog: ctx.lid = a fixed list (list menu), ctx.aid = this agent (the chat)
function mtg_request(ctx = {}) {
  if (!propOn()) return;
  const fixed = ctx.lid ? listById(ctx.lid) : null; if (ctx.lid && !fixed) return;
  const lists = mtg_lists(); if (!fixed && !lists.length) { toast(tr('There is no project you can write in')); return; }
  const last = +LS.get('mtgList') || 0, def = lists.find(l => l.id === last) || lists.find(l => !l.is_inbox) || lists[0];
  const imgs = [];
  const agentRow = ctx.aid && mtg_ok(ctx.aid) ? `<input type="hidden" id="pp-agent" value="${+ctx.aid}">` : propAgentRow();
  const md = modal(`<h3>${ic('bot', 's')} ${esc(tr('Tasks from notes'))}</h3>
    ${fixed ? `<div class="pptask">${listIconHtml(fixed, {cls: 's'}) || ic('list', 's')}<b>${esc(lname(fixed))}</b></div>`
      : `<div class="row"><label for="mtg-list">${tr('Project')}</label><select id="mtg-list">${lists.map(l => `<option value="${l.id}" ${l === def ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>`}
    <div class="row ppcol"><label for="pp-text">${tr('Notes')}</label><textarea id="pp-text" rows="7" maxlength="50000" placeholder="${esc(tr('Paste the meeting notes'))}"></textarea></div>
    <div class="row mtgimgrow"><label class="btn sm mtgadd">${ic('upload', 's')} ${tr('Add a photo or image')}<input type="file" id="mtg-file" accept="image/*" multiple hidden></label><span class="muted">${esc(tr('up to {0}', MTG_IMG))}</span></div>
    <div class="mtgimgs" id="mtg-imgs"></div>
    ${agentRow}<div class="shint" id="pp-priv"></div>
    <div class="calerr" role="alert" id="pp-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${ic('bot', 's')} ${tr('Ask for a proposal')}</button></div>`);
  md.classList.add('ppreq', 'mtgreq');
  const aid = () => +$('#pp-agent', md).value;
  const lid = () => fixed ? fixed.id : +$('#mtg-list', md).value;
  const err = m => { const e = $('#pp-err', md); e.textContent = m || ''; e.hidden = !m; };
  const priv = () => {  // what exactly leaves: the consent line, with the photos
    const who = `<b>${esc((S.proposers.find(a => a.id === aid()) || {}).name || '')}</b>`, l = `<b>${esc(lname(listById(lid())))}</b>`;
    $('#pp-priv', md).innerHTML = !imgs.length ? tr('{0} gets these notes and the names of the people in {1} (to suggest who does what) and proposes tasks for this project. Nothing is created until you apply them.', who, l)
      : trn('{1} gets these notes, {0} image and the names of the people in {2} (to suggest who does what) and proposes tasks for this project. Nothing is created until you apply them. The image stays in your chat with {1}.',
        '{1} gets these notes, {0} images and the names of the people in {2} (to suggest who does what) and proposes tasks for this project. Nothing is created until you apply them. The images stay in your chat with {1}.', imgs.length, who, l);
  };
  const drawImgs = () => {
    $('#mtg-imgs', md).innerHTML = imgs.map((f, i) => `<span class="cfile">${ic('clip', 's')}<span>${esc(f.name || tr('Image'))}</span><button type="button" data-mtgi="${i}" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove') + ': ' + (f.name || tr('Image')))}">${ic('x', 's')}</button></span>`).join('');
    $('.mtgadd', md).classList.toggle('dis', imgs.length >= MTG_IMG); $('#mtg-file', md).disabled = imgs.length >= MTG_IMG;
    priv();
  };
  priv();
  md.addEventListener('change', e => {
    if (e.target.id === 'pp-agent' || e.target.id === 'mtg-list') priv();
    if (e.target.id !== 'mtg-file') return;
    let fs = noEmpty([...e.target.files || []]); e.target.value = '';
    if (fs.some(f => !/^image\//.test(f.type))) { err(tr('Only images')); fs = fs.filter(f => /^image\//.test(f.type)); } else err('');
    const big = fs.find(f => f.size > MTG_IMG_MB * 1024 * 1024);
    if (big) { err(tr('{0} is larger than 50 MB', big.name)); fs = fs.filter(f => f !== big); }
    if (imgs.length + fs.length > MTG_IMG) err(tr('At most {0} images', MTG_IMG));
    imgs.push(...fs.slice(0, Math.max(0, MTG_IMG - imgs.length)));
    drawImgs();
  });
  md.addEventListener('click', async e => {
    const x = e.target.closest('[data-mtgi]'); if (x) { imgs.splice(+x.dataset.mtgi, 1); drawImgs(); err(''); return; }
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const q = {agent_id: aid(), kind: 'extract', list_id: lid(), text: $('#pp-text', md).value.trim()};
    if (!q.text && !imgs.length) { need($('#pp-text', md), tr('Paste the notes or add a photo')); return; }
    b.disabled = true; err('');
    let ids = [];
    try {
      if (imgs.length) {
        const fd = new FormData(); imgs.forEach(f => fd.append('file', f, f.name || 'image.jpg'));
        ids = ((await rawFetch('POST', `/api/agents/${q.agent_id}/meeting-images`, fd)).images || []).map(f => f.id);
        q.image_ids = ids;
      }
      await calReq('POST', '/api/proposals', q);
    } catch (x) {
      ids.forEach(id => rawFetch('DELETE', `/api/chat-files/${id}`).catch(() => {}));  // the request failed: the photos go again
      err(x instanceof Offline ? tr('Only available online.') : x.message); b.disabled = false; return;
    }
    if (!fixed) LS.set('mtgList', String(q.list_id));
    md.remove();
    toast(tr('Sent to {0}: you get a notification when the proposal is ready', (S.proposers.find(a => a.id === q.agent_id) || {}).name || ''));
    if (S.chat.aid === q.agent_id && ids.length) chatLoad();
    if (S.route.mod === 'agents') loadJobs();
  });
  setTimeout(() => $('#pp-text', md)?.focus(), 50);
}

// ---- the cards in the chat: the ready proposals of this agent
async function mtg_load(aid) {
  if (!mtg_ok(aid)) { if (S.mtg[aid]?.length) { S.mtg[aid] = []; mtg_draw(aid); } return; }
  let j; try { j = await api('GET', `/api/agents/${aid}/meeting-proposals`); } catch { return; }
  const ps = j.proposals || [], ids = new Set(ps.map(p => p.id));
  for (const k of Object.keys(S.mtgSel)) if (!ids.has(+k) && (S.mtg[aid] || []).some(p => p.id === +k)) delete S.mtgSel[k];
  const sig = p => JSON.stringify(p), same = (S.mtg[aid] || []).map(sig).join() === ps.map(sig).join();
  ps.forEach(p => { const old = (S.mtg[aid] || []).find(x => x.id === p.id); if (old && sig(old) !== sig(p)) delete S.mtgSel[p.id]; });
  S.mtg[aid] = ps;
  if (!same) mtg_draw(aid);
}
function mtg_draw(aid) {
  const box = $('#chat-mtg'); if (box && S.chat.aid === +aid) box.innerHTML = mtg_cardsHtml(aid);
}
const mtg_sel = p => S.mtgSel[p.id] ||= new Set(p.tasks.map((t, i) => String(i)));
function mtg_cardsHtml(aid) {
  if (S.chat.job) return '';  // a job's history: the plain conversation only
  return (S.mtg[aid] || []).map(p => {
    const sel = mtg_sel(p), n = p.tasks.length;
    return `<section class="mtgcard" data-jid="${p.id}" aria-label="${esc(trn('{0} task from the meeting', '{0} tasks from the meeting', n))}">
      <div class="mtgh">${ic('bot', 's')}<b>${esc(trn('{0} task from the meeting', '{0} tasks from the meeting', n))}</b><span class="muted">${esc(p.list.name || '')}</span></div>
      ${p.summary ? `<div class="mtgsum">${commentBody(p.summary, {})}</div>` : ''}
      <ul class="mtgl">${p.tasks.map((t, i) => `<li class="${sel.has(String(i)) ? '' : 'off'}"><label><input type="checkbox" data-mtg="tick" data-i="${i}" ${sel.has(String(i)) ? 'checked' : ''}><span class="mtgt">${esc(t.title)}</span><span class="mtgm muted">${t.assignee ? `<span>${ic('user', 's')}${esc(t.assignee)}</span>` : ''}${t.due ? `<span>${ic('cal', 's')}${esc(fmtDateLoc(t.due))}</span>` : ''}</span></label></li>`).join('')}</ul>
      <div class="mtgf"><button type="button" class="btn sm" data-mtg="discard">${tr('Discard')}</button><button type="button" class="btn sm" data-mtg="edit">${ic('edit', 's')} ${tr('Edit')}</button><span class="spacer"></span><button type="button" class="btn sm pri" data-mtg="apply" ${sel.size ? '' : 'disabled'}>${ic('check', 's')} ${esc(trn('Create {0} task', 'Create {0} tasks', sel.size))}</button></div></section>`;
  }).join('');
}
async function mtg_apply(aid, p, b) {
  const sel = [...mtg_sel(p)]; if (!sel.length) return;
  b.disabled = true;
  let r; try { r = await calReq('POST', `/api/proposals/${p.id}/apply`, {select: sel}); } catch (x) { toast(x.message); b.disabled = false; return; }
  delete S.mtgSel[p.id]; S.mtg[aid] = (S.mtg[aid] || []).filter(x => x.id !== p.id); mtg_draw(aid);
  await load().catch(() => {}); render();
  const jid = p.id, name = agentById(aid)?.name || '';
  const e = histAdd({label: tr('Applied the proposal of {0}', name), snaps: [], after: [], ids: [], lids: [],
    undo: async () => { const x = await api('POST', `/api/proposals/${jid}/undo`); return {skipped: x.skipped || [], none: !!x.none}; },
    redo: async () => { const x = await api('POST', `/api/proposals/${jid}/redo`); return {skipped: x.skipped || [], none: !!x.none}; }});
  histToast(trn('{0} entry created', '{0} entries created', r.created), e);
}
async function mtg_discard(aid, p) {
  if (!await askConfirm(tr('Discard this proposal?'), tr('{0} is told at once. Nothing is created or changed.', agentById(aid)?.name || ''), {ok: tr('Discard'), danger: true})) return;
  try { await calReq('POST', `/api/proposals/${p.id}/discard`); } catch (x) { toast(x.message); return; }
  delete S.mtgSel[p.id]; S.mtg[aid] = (S.mtg[aid] || []).filter(x => x.id !== p.id); mtg_draw(aid);
  toast(tr('Proposal discarded'));
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-mtg]'); if (!b || b.dataset.mtg === 'tick') return;
  if (b.dataset.mtg === 'open') { mtg_request({aid: +b.dataset.aid}); return; }
  const aid = S.chat.aid, jid = +b.closest('.mtgcard')?.dataset.jid, p = (S.mtg[aid] || []).find(x => x.id === jid); if (!p) return;
  if (b.dataset.mtg === 'apply') mtg_apply(aid, p, b);
  else if (b.dataset.mtg === 'discard') mtg_discard(aid, p);
  else if (b.dataset.mtg === 'edit') propOpen(p.id);
});
document.addEventListener('change', e => {
  const c = e.target.closest?.('[data-mtg="tick"]'); if (!c) return;
  const card = c.closest('.mtgcard'), p = (S.mtg[S.chat.aid] || []).find(x => x.id === +card.dataset.jid); if (!p) return;
  const sel = mtg_sel(p); c.checked ? sel.add(c.dataset.i) : sel.delete(c.dataset.i);
  c.closest('li').classList.toggle('off', !c.checked);
  const a = $('[data-mtg="apply"]', card); a.disabled = !sel.size; a.innerHTML = `${ic('check', 's')} ${esc(trn('Create {0} task', 'Create {0} tasks', sel.size))}`;
});
