/* Kalmido web client: the sidebar's messenger rows (2.45.0, #1509).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- #1509: "Messages" on top of "Conversations" (always there while the team chat is on), below it the last conversations
// (direct messages + list channels, at most 5, unread first and bold); every person row has a speech bubble for a direct message
const SB_RECENT = 5;
function sb_rooms() {
  if (!teamOn()) return [];
  if (S.tc.rooms === null && !S.tc.loading) { S.tc.loading = true; loadTeam().then(() => { S.tc.loading = false; if (S.tc.rooms !== null) renderSide(); }); }  // failed (offline): the next drawing asks again
  const rs = (S.tc.rooms || []).filter(r => r.last && (r.kind === 'dm' || inWs(listById(r.list_id))));  // newest first (server)
  const un = r => r.unread > 0 && (!r.muted || r.mention);
  return [...rs.filter(un), ...rs.filter(r => !un(r))].slice(0, SB_RECENT);
}
function sb_msgRows() {
  if (!teamOn()) return '';
  const rs = sb_rooms(), rid = S.route.mod === 'team' ? (S.cw?.lt ? S.cw.home?.rid : S.tc.rid) : null, lit = rs.some(r => r.id === rid);  // 2.47.1 (#1720): the team view's conversation, not one live in the chat panel
  const n = S.team?.unread || 0, lab = tr('Team chat');  // 2.364.0 B (#3040): one name everywhere (was "Messages")
  const head = `<button class="srow sbmsg ${S.route.mod === 'team' && !lit ? 'on' : ''}" data-go="team" ${isTouch() ? '' : `title="${esc(kt(lab, 'g n'))}"`}>${ic('comment')}<span class="n">${esc(lab)}</span><span class="c ${n ? 'nunread' : ''}">${n ? `${n}<span class="sr"> ${esc(tr('unread'))}</span>` : ''}</span></button>`;
  return head + rs.map(r => {
    const u = r.unread > 0 && (!r.muted || r.mention), nm = roomName(r);
    const ico = r.kind === 'dm' ? av(r.user_id, r.name, 'avatar sbav') : `<span class="sic" aria-hidden="true">${listIconHtml(listById(r.list_id)) || ic('users', 's')}</span>`;
    return `<button class="srow sbconv ${u ? 'sbun' : ''} ${r.id === rid ? 'on' : ''}" data-go="team/${r.id}" title="${esc(r.kind === 'dm' ? tr('Direct message with {0}', nm) : tr('Team chat') + ' · ' + nm)}">${ico}<span class="n">${esc(nm)}</span><span class="c ${u ? 'nunread' : ''}">${r.unread ? `${r.unread}<span class="sr"> ${esc(tr('unread'))}</span>` : ''}</span></button>`;
  }).join('');
}
// a person row: the row opens their tasks (who/<id>), the bubble next to it the direct message
function sb_personRow(p, on) {
  const row = `<button class="srow steam ${on ? 'on' : ''}" data-go="who/${p.id}" title="${esc(tr('Tasks of {0}', p.name))}"><span class="sdot"${ac_mk(p.id)}><i class="pdot"></i></span><span class="n">${esc(p.name)}</span></button>`;
  if (!teamOn()) return row;
  const lab = tr('Message {0}', p.name);
  return `<div class="sbpw">${row}<button type="button" class="iconbtn sbdm" data-sb="dm" data-uid="${p.id}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic('comment', 's')}</button></div>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-sb="dm"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); closeSide(); dmOpen(+b.dataset.uid, personNameAny(+b.dataset.uid));
}, true);

// ---- 2.99.0 E (#2187): the "Conversations" group does not grow with every person a list is shared with: people only while
// pinned (at most 5; one already standing there as a conversation is not shown twice), agents only while pinned, unread or
// working (the others under "Agents"), at the end "All people …" (a dialog: their tasks, a message, pin). The pins are the
// person's settings side_people / side_agents (every device); a person no longer shared with drops out quietly.
const SB_PINS = 5;
const sbp_ids = k => String(S.settings?.[k] || '').split(',').filter(x => /^\d+$/.test(x)).map(Number);
const sbp_is = (k, id) => sbp_ids(k).includes(+id);
function sbp_people() {
  const tp = new Map(teamPeople().map(p => [p.id, p])), dm = new Set(sb_rooms().filter(r => r.kind === 'dm').map(r => r.user_id));
  return sbp_ids('side_people').filter(id => tp.has(id) && !dm.has(id)).map(id => tp.get(id));
}
function sbp_agents() {
  const pin = new Set(sbp_ids('side_agents'));
  return shownAgents().filter(a => pin.has(a.id) || a.waiting || a.chat_unread || a.approvals_open || agentHst(a) === 'working');
}
// pin / unpin: ONE undo step (setApply); ids that are no longer mine (sharing ended, agent removed) are dropped on the way
async function sbp_pin(k, id, on, name) {
  const mine = new Set(k === 'side_people' ? teamPeople().map(p => p.id) : (S.agents || []).map(a => a.id));
  const ids = sbp_ids(k).filter(x => mine.has(x) && x !== +id);
  if (on) {
    if (k === 'side_people' && ids.length >= SB_PINS) { toast(tr('At most {0} people in the sidebar: unpin one first', SB_PINS)); return false; }
    ids.push(+id);
  }
  // 2.350.0 C (#2806): sent as single entries (set_delta): a page state that lags behind (a reload crossing the last save)
  // no longer sends an older whole list that drops a pin; people no longer shared go along as removals
  const drop = sbp_ids(k).filter(x => !mine.has(x) && x !== +id).map(String);
  const sd = add => ({set_delta: {[k]: add ? {remove: drop, add: [String(id)]} : {remove: [String(id), ...drop]}}});
  return setApply({[k]: ids.join(',')}, `${on ? tr('Pin to the sidebar') : tr('Unpin from the sidebar')} · ${name}`, {send: sd(on), back: sd(!on)});
}
const sbp_item = (k, id, name) => sbp_is(k, id) ? {label: tr('Unpin from the sidebar'), icon: 'pin', fn: () => sbp_pin(k, id, false, name)}
  : {label: tr('Pin to the sidebar'), icon: 'pin', fn: () => sbp_pin(k, id, true, name)};
// the pin entry of a sidebar row's menu (chatwins.js: agents and conversations; favtiles.js fv2_rowMenu: people)
function sbp_menuRow(el) {
  if (!el.closest?.('#side')) return [];
  const who = /^who\/(\d+)$/.exec(el.dataset.go || ''), p = who && teamPeople().find(x => x.id === +who[1]);
  if (p) return [sbp_item('side_people', p.id, p.name)];
  if (el.dataset.aid) { const a = agentById(+el.dataset.aid); return a ? [sbp_item('side_agents', a.id, a.name)] : []; }
  const r = /^team\/(\d+)$/.exec(el.dataset.go || '') && (S.tc.rooms || []).find(x => x.id === +el.dataset.go.split('/')[1]);
  if (r && r.kind === 'dm' && r.user_id && teamPeople().some(p => p.id === r.user_id)) return [sbp_item('side_people', r.user_id, roomName(r))];
  return [];
}
const sbp_allRow = () => collab() && (teamPeople().length || shownAgents().length) ? `<button class="srow smore sbpall" data-act="sb-people" title="${esc(tr('Their tasks, a message, pin to the sidebar'))}">${ic('users')}<span class="n">${esc(tr('All people …'))}</span></button>` : '';
// "All people …": everyone I share a list with; a row = their tasks, the bubble = a message, the pin = in the sidebar or not
function sbp_dialog() {
  const md = modal(`<h3>${esc(tr('People'))}</h3>
    ${teamPeople().length > 8 ? `<input type="search" class="sbpq" placeholder="${esc(tr('Search people'))}" aria-label="${esc(tr('Search people'))}">` : ''}
    <div class="members sbpl"></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('sbpmd');
  const draw = () => {
    const q = ($('.sbpq', md)?.value || '').trim().toLowerCase(), ps = teamPeople().filter(p => !q || p.name.toLowerCase().includes(q));
    $('.sbpl', md).innerHTML = ps.map(p => {
      const on = sbp_is('side_people', p.id), pl = on ? tr('Unpin from the sidebar') : tr('Pin to the sidebar'), ml = tr('Message {0}', p.name);
      return `<div class="mrow" data-uid="${p.id}">${av(p.id, p.name)}<button type="button" class="n sbpgo" data-sbp="go" title="${esc(tr('Tasks of {0}', p.name))}">${esc(p.name)}</button>`
        + (teamOn() ? `<button type="button" class="iconbtn" data-sbp="dm" title="${esc(ml)}" aria-label="${esc(ml)}">${ic('comment', 's')}</button>` : '')
        + `<button type="button" class="iconbtn sbppin ${on ? 'on' : ''}" data-sbp="pin" aria-pressed="${on}" title="${esc(pl)}" aria-label="${esc(pl + ' · ' + p.name)}">${ic(on ? 'pinf' : 'pin', 's')}</button></div>`;
    }).join('') || (shownAgents().length ? '' : `<div class="muted mhint">${esc(tr('Nobody to show.'))}</div>`);
    // 2.119.0 B (#2210): the agents I may see (the sidebar's source), pin = side_agents; the same bearing as the people (no long press on iPhone)
    const ags = shownAgents().filter(a => !q || a.name.toLowerCase().includes(q));
    $('.sbpl', md).innerHTML += ags.length ? `<h4 class="sbph">${esc(tr('Agents'))}</h4>` + ags.map(a => {
      const on = sbp_is('side_agents', a.id), pl = on ? tr('Unpin from the sidebar') : tr('Pin to the sidebar');
      return `<div class="mrow" data-aid="${a.id}"><span class="sdot"${ac_mk(a.id)}>${hdot(agentHst(a))}</span><button type="button" class="n sbpgo" data-sbp="ago" title="${esc(agentHstLine(a))}">${esc(a.name)}</button>`
        + `<button type="button" class="iconbtn sbppin ${on ? 'on' : ''}" data-sbp="apin" aria-pressed="${on}" title="${esc(pl)}" aria-label="${esc(pl + ' · ' + a.name)}">${ic(on ? 'pinf' : 'pin', 's')}</button></div>`;
    }).join('') : '';
  };
  draw();
  $('.sbpq', md)?.addEventListener('input', draw);
  md.addEventListener('click', async e => {
    if (e.target.closest('[data-m="close"]')) { md.remove(); return; }
    const b = e.target.closest('[data-sbp]'); if (!b) return;
    const ar = b.closest('[data-aid]');  // 2.119.0 B (#2210): an agent row
    if (ar) {
      const ag = agentById(+ar.dataset.aid); if (!ag) return;
      if (b.dataset.sbp === 'ago') { md.remove(); closeSide(); if (ag.enabled) chatOpen(ag.id); else go('agents'); }
      else { await sbp_pin('side_agents', ag.id, !sbp_is('side_agents', ag.id), ag.name); draw(); }
      return;
    }
    const id = +b.closest('[data-uid]').dataset.uid, p = teamPeople().find(x => x.id === id); if (!p) return;
    if (b.dataset.sbp === 'go') { md.remove(); closeSide(); go('who/' + id); }
    else if (b.dataset.sbp === 'dm') { md.remove(); closeSide(); dmOpen(id, p.name); }
    else { await sbp_pin('side_people', id, !sbp_is('side_people', id), p.name); draw(); }
  });
}
