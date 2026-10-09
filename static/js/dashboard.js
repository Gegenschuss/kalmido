/* Kalmido web client: News bundled per task, the dashboard and Settings > Tasks by e-mail.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ #452 News bundled
// News grouped per task (or list / kind) with one line of what happened ("3 comments · completed"), "Needs you"
// (approvals, proposals, mentions, assignments, follow-ups) above "For your information", "Mark read" per group, and
// "Summarize": the unread items go to an agent's chat, which answers with a short summary. Per device: bundled or the
// plain list (the toggle in the bar).
const NEWS_NEEDS = ['approval', 'proposal', 'mention', 'assign', 'take', 'followup'];
const newsBundled = () => LS.get('newsBundle', true) !== false;
function newsGroups(items) {
  const groups = new Map();
  for (const [it, i] of items) {
    const key = it.task_id && !(it.tasks || []).length ? 't' + it.task_id : it.list_id && ['share', 'role', 'unshare', 'owner', 'status'].includes(it.kind) ? 'l' + it.list_id : 'k' + it.kind + (it.kind === 'comment' ? it.actor_id : '');
    if (!groups.has(key)) groups.set(key, {key, items: [], needs: false, unread: 0, at: it.created_at});
    const g = groups.get(key);
    // 2.25.0 (UX-45): a comment that names me (@me) needs me too, like a mention
    const toMe = it.kind === 'comment' && S.me && (it.excerpt || '').includes(`<@${S.me.id}>`);
    g.items.push([it, i]); if (NEWS_NEEDS.includes(it.kind) || toMe) g.needs = true; if (!it.read) g.unread++;
  }
  return [...groups.values()];
}
function newsSummaryLine(g) {
  const c = {};
  for (const [it] of g.items) c[it.kind] = (c[it.kind] || 0) + (it.count || 1);
  const L = {comment: n => trn('{0} comment', '{0} comments', n), mention: n => trn('{0} mention', '{0} mentions', n), assign: () => tr('assigned to you'),
    unassign: () => tr('unassigned'), complete: () => tr('completed'), newtask: n => trn('{0} new task', '{0} new tasks', n), status: () => tr('status changed'),
    share: () => tr('shared with you'), approval: n => trn('{0} approval waits', '{0} approvals wait', n), proposal: () => tr('a proposal is ready'),
    followup: () => tr('follow up today'), unblock: () => tr('unblocked'), take: () => tr('taken'), role: () => tr('your role changed'), owner: () => tr('you own it now'),
    unshare: () => tr('removed'), usage: () => tr('usage limit'), errreport: () => tr('new error'), agentjoin: () => tr('an agent joined')};
  return Object.entries(c).map(([k, n]) => (L[k] || (() => k))(n)).join(' · ');
}
function newsGroupHtml(g, pop) {
  const [first] = g.items[0], U = S.nf.users;
  const title = first.task_id && !(first.tasks || []).length ? esc(first.task_title || '') : first.list_id && g.key[0] === 'l' ? esc(newsListName(first)) : newsText(first, U);
  const actors = [...new Set(g.items.flatMap(([it]) => it.actors || [it.actor_id]).filter(Boolean))].slice(0, 4);
  const ids = g.items.flatMap(([it]) => it.ids || [it.id]);
  const open = g.items.length === 1 ? (pop ? 'data-bp="open"' : 'data-act="news-open"') + ` data-i="${g.items[0][1]}"` : `data-act="news-group" data-g="${esc(g.key)}"`;
  const exp = S.nf.openG === g.key;
  return `<div class="ngroup ${g.unread ? 'unread' : ''} ${g.needs ? 'needs' : ''}" data-gk="${esc(g.key)}">
    <div class="nghead"><div class="ngav">${actors.map(a => av(a, uname(a, U), 'avatar sm')).join('')}</div>
      <div class="ngmain" role="button" tabindex="0" ${open} ${g.items.length > 1 ? `aria-expanded="${exp}"` : ''}><div class="ngt">${title}${g.items.length > 1 ? `<span class="ngn">${g.items.length}</span>` : ''}</div><div class="ngs muted">${esc(newsSummaryLine(g))} · <time>${esc(relTime(g.at))}</time></div>${(() => {  // 2.25.0 (UX-45): what was written, one line
        const ex = g.items.map(([it]) => it).find(it => (it.kind === 'mention' || it.kind === 'comment') && it.excerpt);
        return ex ? `<div class="nexc ngex">${newsExcerpt(ex.excerpt, U)}</div>` : ''; })()}</div>
      ${g.unread ? `<button type="button" class="iconbtn" data-act="news-gread" data-ids="${ids.join(',')}" title="${esc(tr('Mark read'))}" aria-label="${esc(tr('Mark read') + ': ' + title.replace(/<[^>]+>/g, ''))}">${ic('check', 's')}</button>` : ''}</div>
    ${exp && g.items.length > 1 ? `<div class="nlist ngitems">${g.items.map(([it, i]) => newsItemHtml(it, i, pop)).join('')}</div>` : ''}</div>`;
}
function newsBundledHtml(vis, pop) {
  // 2.18.0 (#652): the two sections are h2 (the page's h1 is the header title; the bell's panel has no heading above them)
  const gs = newsGroups(vis), needs = gs.filter(g => g.needs), info = gs.filter(g => !g.needs);
  return (needs.length ? `<section class="nsect" aria-labelledby="ns-need"><h2 id="ns-need" class="nsh">${tr('Needs you')}<span class="c">${needs.length}</span></h2>${needs.map(g => newsGroupHtml(g, pop)).join('')}</section>` : '')
    + (info.length ? `<section class="nsect" aria-labelledby="ns-info"><h2 id="ns-info" class="nsh">${tr('For your information')}<span class="c">${info.length}</span></h2>${info.map(g => newsGroupHtml(g, pop)).join('')}</section>` : '');
}
async function newsGroupRead(ids) {
  try { await rawFetch('POST', '/api/news/read', {ids}); } catch (e) { toast(e.message); return; }
  for (const it of S.nf.items || []) if ((it.ids || [it.id]).some(x => ids.includes(x))) { it.read = true; it.keep = S.nf.unread; }
  announce(tr('Marked read')); render();
  await loadNews().catch(() => {}); render();  // the counts from the server (an item may stand for several)
}
// "Summarize": the unread News as plain lines to an agent's chat
function newsSummarize(anchor) {
  const ags = (S.agents || []).filter(a => a.enabled);
  const items = (S.nf.items || []).filter(it => !it.read);
  if (!items.length) { toast(tr('No unread news')); return; }
  const send = async a => {
    const U = S.nf.users;
    const lines = items.slice(0, 120).map(it => '- ' + newsText(it, U).replace(/<[^>]+>/g, '') + (it.task_title ? ` (${it.task_title})` : '') + (it.excerpt ? `: ${String(it.excerpt).replace(/<@(\d+)>/g, (_, id) => '@' + uname(+id, U)).slice(0, 160)}` : ''));
    const text = tr('Please summarize my {0} unread news items in at most 5 short lines: what needs me first, then the rest.', items.length) + '\n\n' + lines.join('\n');
    try { await rawFetch('POST', `/api/agents/${a.id}/chat`, {body: text.slice(0, 7900)}); } catch (e) { toast(e.message); return; }
    closePop(); chatOpen(a.id); toast(tr('Sent to {0}', a.name));
  };
  if (ags.length === 1) send(ags[0]);
  else menu(anchor, ags.map(a => ({label: tr('Ask {0}', a.name), icon: 'bot', fn: () => send(a)})));
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act="news-gread"],[data-act="news-group"],[data-act="news-bundle"],[data-act="news-sum"]'); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  if (a.dataset.act === 'news-gread') {  // 2.17.2: the focus moves on to the group in the same place (or the last one)
    const gs = $$('#view .ngroup, .bplist .ngroup'), gi = gs.indexOf(a.closest('.ngroup')), inPop = !!a.closest('.bplist');
    newsGroupRead(a.dataset.ids.split(',').map(Number)).then(() => { if (!document) return; const n = $$((inPop ? '.bplist' : '#view') + ' .ngroup .ngmain'); (n[Math.min(gi, n.length - 1)] || $('#view h1, #top h1'))?.focus?.(); });
  }
  else if (a.dataset.act === 'news-group') { S.nf.openG = S.nf.openG === a.dataset.g ? null : a.dataset.g; render(); if ($('#pop .bpop')) { const p = $('#pop'); p.innerHTML = bellPopHtml(); } }
  else if (a.dataset.act === 'news-bundle') { LS.set('newsBundle', !newsBundled()); render(); if ($('#pop .bpop')) $('#pop').innerHTML = bellPopHtml(); }
  else if (a.dataset.act === 'news-sum') newsSummarize(a);
}, true);
document.addEventListener('keydown', e => { const g = e.target.closest?.('.ngmain[data-act="news-group"]'); if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); g.click(); } });

// ------------------------------------------------------------------ #475 the dashboard (a tap on the logo)
// Small cards, in your order, each can be hidden ("Customize": ↑ ↓ and a switch per card, keyboard too); stored with your
// settings (all devices). What waits for you, today, bundled news, team chat, projects, pinned tasks, notes, agents, a
// few numbers and a search field.
const DASH = [['wait', N_('Waiting for you'), 'hourglass'], ['today', N_('Today'), 'sun'], ['news', N_('News'), 'bell'], ['chat', N_('Team chat'), 'comment'],
  ['projects', N_('Projects'), 'brief'], ['pinned', N_('Pinned|view'), 'pin'], ['notes', N_('Notes'), 'edit'], ['agents', N_('Agents'), 'bot'],
  ['stats', N_('Statistics'), 'chart'], ['search', N_('Search'), 'search'], ['family', N_('Family'), 'family']];
S.dash = {custom: false};
// ------------------------------------------------------------------ 2.32.0 (#1063) the view builder ("Customize")
// One module for every view built from blocks (start page, Today, Time tracking, the project page): show / hide, order,
// width half / full (two side by side on a computer), optional "Different on the phone", saved switches of a block (opts).
// LY[view] = {key | src/save, blocks: () => [[key, name, icon, 'half'|'full', fixed]], title, grid (css class), quick}.
// Stored per person (all devices) as json {order, hidden, half, full, opts, mobile} (accounts/layouts.py); the start
// page keeps its key "dashboard". The project page: the project's standard (owner / admins) or my own override.
const LY = {};
S.ly = {view: null, phone: false, std: false};
const lyBlocks = v => LY[v].blocks().filter(Boolean);
function lyRaw(v, std) {
  const d = LY[v]; let s = d.src ? d.src(std) : LY_PEND[d.key] ?? S.settings?.[d.key];  // a value still on its way wins over a reload
  try { const o = JSON.parse(s || '{}'); return o && typeof o === 'object' ? o : {}; } catch { return {}; }
}
function lyPref(v, o = {}) {
  const raw = o.raw || lyRaw(v, o.std), bs = lyBlocks(v), keys = bs.map(b => b[0]);
  const phone = o.phone ?? (S.ly.view === v ? S.ly.phone : isMobile());
  const p = phone && raw.mobile ? raw.mobile : raw, po = (p.order || []).filter(k => keys.includes(k));
  const fixed = new Set(bs.filter(b => b[4]).map(b => b[0]));
  // 2.34.0 (#264): a block that is new since the arrangement was saved goes where it stands in the default order (before the
  // next block it already has), not to the end -- the briefing belongs on top of Today
  const order = po.slice();
  keys.forEach((k, i) => { if (order.includes(k)) return; const nx = keys.slice(i + 1).find(x => order.includes(x)); order.splice(nx ? order.indexOf(nx) : order.length, 0, k); });
  const hidden = new Set((p.hidden || []).filter(k => keys.includes(k) && !fixed.has(k)));
  const size = k => (p.full || []).includes(k) ? 'full' : (p.half || []).includes(k) ? 'half' : (bs.find(b => b[0] === k)?.[3] || 'half');
  return {raw, part: p, order, hidden, size, fixed, mobile: !!raw.mobile, opts: raw.opts || {}};
}
// change the arrangement being edited (the phone one when "Different on the phone" is on and it is chosen)
function lyChange(v, fn) {
  const std = S.ly.view === v && S.ly.std, pr = lyPref(v, {std}), raw = JSON.parse(JSON.stringify(pr.raw));
  const tgt = (S.ly.view === v ? S.ly.phone : isMobile()) && raw.mobile ? raw.mobile : raw;
  const bs = lyBlocks(v), st = {order: pr.order.slice(), hidden: new Set(pr.hidden), sizes: Object.fromEntries(bs.map(b => [b[0], pr.size(b[0])]))};
  fn(st, raw);
  tgt.order = st.order; tgt.hidden = [...st.hidden];
  tgt.half = bs.filter(b => b[3] !== 'half' && st.sizes[b[0]] === 'half').map(b => b[0]);
  tgt.full = bs.filter(b => b[3] !== 'full' && st.sizes[b[0]] === 'full').map(b => b[0]);
  lyStore(v, raw, std);
}
// saves go out one after the other (two quick changes must not arrive the wrong way round)
let lyQ = Promise.resolve();
const LY_PEND = {};
function lyPatch(key, o) {
  LY_PEND[key] = o;
  lyQueue(() => api('PATCH', '/api/settings', {[key]: o}).catch(() => { /* api() said it */ }).finally(() => { if (LY_PEND[key] === o) { delete LY_PEND[key]; if (S.settings) S.settings[key] = o; } }));
}
const lyQueue = fn => (lyQ = lyQ.then(fn, fn));
function lyStore(v, raw, std) {
  const o = raw && Object.keys(raw).length ? JSON.stringify(raw) : '';
  const d = LY[v];
  if (d.save) { d.save(o, std); return; }
  S.settings[d.key] = o; lyPatch(d.key, o); renderView();
}
// a saved switch of a block (e.g. the period of the time report): read / write without a new arrangement
const lyOpt = (v, b, n, def) => lyPref(v).opts?.[b]?.[n] ?? def;
function lyOptSet(v, b, n, x) {
  const raw = lyRaw(v); if ((raw.opts?.[b] || {})[n] === x) return;
  ((raw.opts ||= {})[b] ||= {})[n] = x;
  if (LY[v].save) { LY[v].save(JSON.stringify(raw), false); return; }
  S.settings[LY[v].key] = JSON.stringify(raw); lyPatch(LY[v].key, JSON.stringify(raw));
}
const lyAct = v => v === 'home' ? 'dash' : 'ly';
const lyCustomBtn = v => `<button type="button" class="btn sm" data-act="${lyAct(v)}-custom" data-lyv="${v}">${ic('sliders', 's')}${tr('Customize')}</button>`;
// the blocks of view v in the chosen order and widths; parts = {key: html | fn(closeButton) | ''} ('' = nothing to show now)
function lyHtml(v, parts, o = {}) {
  const d = LY[v], {order, hidden, size} = lyPref(v);
  if (S.ly.view === v) return lyEditor(v, {...o, parts});  // 2.35.0 (#1097): the editor shows the blocks themselves
  const xb = (k, n) => d.quick && o.canHide !== false ? `<button type="button" class="iconbtn lyx" data-act="ly-hide" data-lyv="${v}" data-k="${k}" title="${esc(tr('Hide {0}', tr(n)))}" aria-label="${esc(tr('Hide {0}', tr(n)))}">${ic('x', 's')}</button>` : '';
  const bs = lyBlocks(v), out = [];
  for (const k of order) {
    if (hidden.has(k)) continue;
    const b = bs.find(x => x[0] === k), p = parts[k], h = typeof p === 'function' ? p(b[4] ? '' : xb(k, b[1])) : p;
    if (h) out.push(`<div class="lyb ly-${size(k)}" data-lyk="${k}">${h}</div>`);
  }
  const hid = bs.filter(b => hidden.has(b[0]) && parts[b[0]] !== undefined);
  const add = d.quick && o.canHide !== false && hid.length ? `<div class="lyadd"><button type="button" class="btn sm" data-act="ly-add" data-lyv="${v}" aria-haspopup="menu">${ic('plus', 's')}<span>${tr('Block')}</span></button></div>` : '';
  return `<div class="${d.grid || 'lygrid'}" data-ly="${v}">${out.join('') || (o.empty ?? d.empty ?? `<p class="muted">${tr('Every block is hidden. Customize brings them back.')}</p>`)}</div>${add}`;
}
function lyEditor(v, o = {}) {
  const d = LY[v], pr = lyPref(v, {std: S.ly.std}), {order, hidden, size, fixed} = pr, bs = lyBlocks(v), A = lyAct(v), n = order.length;
  const desk = !isMobile();
  const rows = order.map((k, i) => { const [_, nm, icon, def] = bs.find(b => b[0] === k), sz = size(k);
    return `<li data-k="${k}" ${desk ? 'draggable="true"' : ''} tabindex="-1">${desk ? `<span class="lyg" aria-hidden="true">${ic('grip', 's')}</span>` : ''}${ic(icon, 's')}<span class="dcl">${tr(nm)}</span>
      ${d.nosize || !desk ? '' : `<button type="button" class="btn sm lysz" data-act="ly-size" data-lyv="${v}" data-k="${k}" aria-pressed="${sz === 'full'}" title="${esc(tr('Width'))}" aria-label="${esc(tr('Width') + ': ' + tr(nm) + ', ' + (sz === 'full' ? tr('full width') : tr('half width')))}">${sz === 'full' ? tr('Full') : tr('Half')}</button>`}
      <button type="button" class="iconbtn" data-act="${A}-mv" data-lyv="${v}" data-k="${k}" data-d="-1" ${i ? '' : 'disabled'} aria-label="${esc(tr('Move up') + ': ' + tr(nm))}">${ic('up', 's')}</button>
      <button type="button" class="iconbtn" data-act="${A}-mv" data-lyv="${v}" data-k="${k}" data-d="1" ${i < n - 1 ? '' : 'disabled'} aria-label="${esc(tr('Move down') + ': ' + tr(nm))}">${ic('down', 's')}</button>
      <label class="swc"><input type="checkbox" data-dshow="${k}" data-lyv="${v}" ${hidden.has(k) ? '' : 'checked'} ${fixed.has(k) ? 'disabled' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Show {0}', tr(nm)))}</span></label></li>`; }).join('');
  const scope = o.canStd ? `<div class="seg lyscope" role="group" aria-label="${esc(tr('Arrangement for'))}"><button type="button" class="${S.ly.std ? '' : 'on'}" aria-pressed="${!S.ly.std}" data-act="ly-scope" data-lyv="${v}" data-k="mine">${tr('Only for me')}</button><button type="button" class="${S.ly.std ? 'on' : ''}" aria-pressed="${S.ly.std}" data-act="ly-scope" data-lyv="${v}" data-k="std">${tr('Standard for everyone')}</button></div>` : '';
  const ph = `<label class="chkl lyph"><input type="checkbox" data-lyphone="${v}" ${pr.mobile ? 'checked' : ''}> ${tr('Different on the phone')}</label>${pr.mobile ? `<div class="seg" role="group" aria-label="${esc(tr('Arrangement for'))}"><button type="button" class="${S.ly.phone ? '' : 'on'}" aria-pressed="${!S.ly.phone}" data-act="ly-dev" data-lyv="${v}" data-k="0">${tr('Computer')}</button><button type="button" class="${S.ly.phone ? 'on' : ''}" aria-pressed="${S.ly.phone}" data-act="ly-dev" data-lyv="${v}" data-k="1">${tr('Phone')}</button></div>` : ''}`;
  const reset = o.override ? `<button type="button" class="linkbtn" data-act="${A}-reset" data-lyv="${v}">${S.ly.std ? tr('Reset to defaults') : tr('Reset to the standard')}</button>` : `<button type="button" class="linkbtn" data-act="${A}-reset" data-lyv="${v}">${tr('Reset to defaults')}</button>`;
  // 2.35.0 (#1097): the blocks right in the view (drag them by the handle, on a phone hold a block; hide, width at the
  // block; hidden ones at the bottom), the list with the arrows stays below for the keyboard and screen readers
  const list = `<details class="lylist" ${LS.get('lyList', true) ? 'open' : ''}><summary>${ic('chev', 's fcar')}<span>${tr('Order as a list')}</span></summary>
    <ol class="dcust" aria-label="${esc(v === 'home' ? tr('Cards') : tr('Blocks'))}" aria-describedby="lyhint-${v}">${rows}</ol><p class="muted lyhint" id="lyhint-${v}">${desk ? tr('Drag a row or use the arrows; Alt + arrow keys move the focused row.') : tr('Use the arrows to change the order.')}</p></details>`;
  return `<div class="lyed" data-lyed="${v}"><div class="dashhead"><h2>${esc(d.title())}</h2><span class="spacer"></span><button type="button" class="btn sm pri" data-act="${A}-done" data-lyv="${v}">${tr('Done')}</button></div>
    <div class="lyopts">${scope}${ph}</div>
    ${lydragCanvas(v, pr, o.parts || {})}
    ${list}
    ${reset}</div>`;
}
function lyOpen(v, on) {
  if (on) { S.ly = {view: v, phone: lyRaw(v).mobile ? isMobile() : false, std: false, at: location.hash}; }
  else S.ly = {view: null, phone: false, std: false};
  if (v === 'home') S.dash.custom = on;
  renderView();
  setTimeout(() => on ? $('#view .dcust button:not([disabled])')?.focus({preventScroll: true}) : $(`#view [data-act="${lyAct(v)}-custom"]`)?.focus(), 0);
}
function lyMove(v, k, dlt) {
  lydragDo(v, st => { const i = st.order.indexOf(k), j = i + dlt; if (i < 0 || j < 0 || j >= st.order.length) return; [st.order[i], st.order[j]] = [st.order[j], st.order[i]]; },
    dlt < 0 ? tr('Moved up') : tr('Moved down'), true);  // 2.35.0 (#1097): undoable
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act^="dash-"],[data-act^="ly-"]'); if (!a) return;
  const v = a.dataset.lyv || 'home', act = a.dataset.act.replace(/^(dash|ly)-/, ''); if (!LY[v]) return;
  e.preventDefault(); e.stopPropagation();
  if (act === 'custom') lyOpen(v, true);
  else if (act === 'done') lyOpen(v, false);
  else if (act === 'reset') { const raw = lyRaw(v, S.ly.std); lyStore(v, LY[v].src ? '' : (raw.opts ? {opts: raw.opts} : ''), S.ly.std); S.ly.phone = false; announce(tr('Reset')); }
  else if (act === 'mv') {
    lyMove(v, a.dataset.k, +a.dataset.d);
    setTimeout(() => $(`#view .dcust [data-act$="-mv"][data-k="${a.dataset.k}"][data-d="${a.dataset.d}"]:not([disabled])`)?.focus() || $(`#view .dcust [data-act$="-mv"][data-k="${a.dataset.k}"]:not([disabled])`)?.focus(), 30);
  }
  else if (act === 'size') { const k = a.dataset.k, cv = !!a.closest('.lycanvas'); lydragDo(v, st => { st.sizes[k] = st.sizes[k] === 'full' ? 'half' : 'full'; }, tr('Width changed'), true); setTimeout(() => $(`#view ${cv ? '.lycanvas' : '.dcust'} [data-act="ly-size"][data-k="${k}"]`)?.focus(), 30); }
  else if (act === 'scope') { S.ly.std = a.dataset.k === 'std'; S.ly.phone = false; renderView(); setTimeout(() => $(`#view [data-act="ly-scope"][data-k="${a.dataset.k}"]`)?.focus(), 0); }
  else if (act === 'dev') { S.ly.phone = a.dataset.k === '1'; renderView(); setTimeout(() => $(`#view [data-act="ly-dev"][data-k="${a.dataset.k}"]`)?.focus(), 0); }
  else if (act === 'hide') { const k = a.dataset.k, bl = lyBlocks(v).find(b => b[0] === k); S.ly.std = false; lyChange(v, st => st.hidden.add(k)); toast(tr('{0} hidden. “+ Block” brings it back.', tr(bl?.[1] || k))); setTimeout(() => $(`#view [data-act="ly-add"][data-lyv="${v}"]`)?.focus(), 30); }
  else if (act === 'add') {
    const {hidden} = lyPref(v);
    menu(a, lyBlocks(v).filter(b => hidden.has(b[0])).map(b => ({label: tr(b[1]), icon: b[2], fn: () => { S.ly.std = false; lyChange(v, st => { st.hidden.delete(b[0]); }); }})));
  }
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.dataset?.lyphone) {  // "Different on the phone": a copy of the arrangement for phones (off = the copy goes)
    const v = t.dataset.lyphone, raw = lyRaw(v, S.ly.std);
    if (t.checked) { const {order, hidden} = lyPref(v, {raw, phone: false}); raw.mobile = {order, hidden: [...hidden], half: raw.half || [], full: raw.full || []}; S.ly.phone = true; }
    else { delete raw.mobile; S.ly.phone = false; }
    lyStore(v, raw, S.ly.std); setTimeout(() => $(`#view [data-lyphone="${v}"]`)?.focus(), 30); return;
  }
  const k = t.dataset?.dshow; if (!k) return;
  const v = t.dataset.lyv || 'home'; if (!LY[v]) return;
  lydragDo(v, st => { if (t.checked) st.hidden.delete(k); else st.hidden.add(k); }, t.checked ? tr('Shown') : tr('Hidden'), true);  // 2.35.0 (#1097): undoable
  setTimeout(() => $(`#view [data-dshow="${k}"][data-lyv="${v}"]`)?.focus(), 30);
});
// keyboard: Alt + ↑ / ↓ on a row (or a control in it) moves the block
document.addEventListener('keydown', e => {
  if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
  const li = e.target.closest?.('.lyed .dcust li'); if (!li) return;
  e.preventDefault(); const v = li.closest('.lyed').dataset.lyed, k = li.dataset.k;
  lyMove(v, k, e.key === 'ArrowUp' ? -1 : 1);
  setTimeout(() => $(`#view .lyed .dcust li[data-k="${k}"]`)?.focus(), 30);
});
// leaving the view ends Customize (it never shows up on another page)
window.addEventListener('hashchange', () => { if (S.ly.view && S.ly.at !== location.hash) { if (S.ly.view === 'home') S.dash.custom = false; S.ly = {view: null, phone: false, std: false}; setTimeout(() => renderView(), 0); } });
// a computer: drag the rows of the editor
let lyDrag = null;
document.addEventListener('dragstart', e => { const li = e.target.closest?.('.lyed .dcust li[draggable]'); if (!li) return; lyDrag = li.dataset.k; e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', li.dataset.k); } catch { /* old browsers */ } li.classList.add('lydragging'); });
document.addEventListener('dragover', e => { if (!lyDrag) return; const li = e.target.closest?.('.lyed .dcust li'); if (!li) return; e.preventDefault(); $$('.lyed .dcust li.lyover').forEach(x => x.classList.remove('lyover')); li.classList.add('lyover'); });
document.addEventListener('dragend', () => { lyDrag = null; $$('.lyed .dcust li.lyover,.lyed .dcust li.lydragging').forEach(x => x.classList.remove('lyover', 'lydragging')); });
document.addEventListener('drop', e => {
  if (!lyDrag) return; const li = e.target.closest?.('.lyed .dcust li'); if (!li) return;
  e.preventDefault(); e.stopPropagation();
  const v = li.closest('.lyed').dataset.lyed, k = lyDrag, to = li.dataset.k; lyDrag = null;
  if (k !== to) lydragDo(v, st => { const i = st.order.indexOf(k), j = st.order.indexOf(to); st.order.splice(i, 1); st.order.splice(j, 0, k); }, tr('Moved'));  // 2.35.0: undoable
});

// Today and Time tracking (2.32.0): the first views on the builder; the blocks a view does not show right now simply stay out
LY.today = {key: 'view_today', empty: '', title: () => tr('Customize Today'), blocks: () => [['brief', N_('Briefing'), 'sunrise', 'full'], ['wait', N_('Waiting for you'), 'hourglass', 'full'], ['review', N_('Daily review'), 'journal', 'full'],
  ['overdue', N_('Overdue'), 'alert', 'full'], ['events', N_('Events today'), 'cal', 'full'], ['tasks', N_('Tasks'), 'list', 'full', true], ['inbox', N_('Inbox'), 'inbox', 'full']]};
LY.time = {key: 'view_time', empty: '', title: () => tr('Customize time tracking'), blocks: () => [['tiles', N_('Totals'), 'clock', 'full'],
  ['chart', N_('Per day'), 'chart', 'full'], ['lists', N_('By list and task'), 'list', 'full'], ['entries', N_('Entries'), 'rows', 'full']]};
// the Agents overview (status, usage, jobs; not the settings) and the projects overview ("Where is it stuck?")
LY.agents = {key: 'view_agents', empty: '', title: () => tr('Customize the agents overview'), blocks: () => [['agents', N_('Agents'), 'bot', 'full'], ['usage', N_('Usage'), 'chart', 'full'],
  ['jobs', N_('Jobs'), 'list', 'full', true], ['hint', N_('Explanation'), 'info', 'full']]};
LY.projects = {key: 'view_projects', empty: '', title: () => tr('Customize the projects overview'), blocks: () => [['tiles', N_('Totals'), 'chart', 'full'], ['projects', N_('Projects'), 'brief', 'full', true],
  ['note', N_('Explanation'), 'info', 'full']]};
// the project page (#983; its blocks: POV_BLOCKS in projects.js)
LY.project = {quick: true, title: () => tr('Customize the project page'), blocks: () => POV_BLOCKS,
  src: std => { const y = S.povD[routeList()?.id]?.j?.layout || {}; return std ? y.std : (y.mine || y.std); },
  save: (v, std) => {
    const l = routeList(), d = l && S.povD[l.id]; if (!d?.j) return;
    const old = d.j.layout, seq = d.lySeq = (d.lySeq || 0) + 1; d.j.layout = {...old, [std ? 'std' : 'mine']: v}; renderView();
    lyQueue(async () => {
      try { const r = await api('PUT', `/api/lists/${l.id}/layout`, {layout: v, scope: std ? 'standard' : 'mine'}); if (seq === d.lySeq && d.j) { d.j.layout = r; renderView(); } }
      catch { if (seq === d.lySeq && d.j) { d.j.layout = old; renderView(); } }
    });
  }};
// the start page (#475) on the view builder
LY.home = {key: 'dashboard', grid: 'dgrid', title: () => tr('Customize the start page'), blocks: () => DASH.filter(d => d[0] !== 'family' || famOn()).map(d => [d[0], d[1], d[2], 'half'])};
function dashCard(k) {
  const [_, name, icon] = DASH.find(d => d[0] === k), t0 = today();
  const card = (body, more = '', n = '') => `<section class="dcard dc-${k}" aria-labelledby="dh-${k}"><h3 id="dh-${k}">${ic(icon, 's')}<span>${tr(name)}</span>${n !== '' ? `<span class="dcn">${n}</span>` : ''}<span class="spacer"></span>${more}</h3>${body}</section>`;
  const tasksList = ts => ts.length ? `<ul class="dtl">${ts.slice(0, 6).map(t => `<li><button type="button" class="chk p${t.priority}" data-act="toggle" data-id="${t.id}" role="checkbox" aria-checked="false" aria-label="${esc(tr('Complete: {0}', t.title))}"></button><a href="#t/${t.id}" class="dtt">${esc(t.title)}</a>${t.due ? `<span class="dt ${dueClass(t)}">${esc(dayLabel(t.due))}${t.due_time ? ' ' + t.due_time : ''}</span>` : ''}</li>`).join('')}</ul>${ts.length > 6 ? `<p class="muted dmore">${tr('{0} more', ts.length - 6)}</p>` : ''}` : '';
  if (k === 'wait') {
    const js = waitJobs ? waitJobs() : [], ments = (S.nf.items || []).filter(it => !it.read && ['mention', 'assign', 'approval', 'proposal'].includes(it.kind));
    const rows = [...js.map(j => `<li><a href="#agents">${hdot('waiting')}<span class="dwt">${esc(tr('{0} waits for you', j.agent_name))}: ${esc(j.title)}</span></a></li>`),
      ...ments.slice(0, 5).map(it => `<li><a href="${it.task_id ? '#t/' + it.task_id : '#news'}">${ic(NEWS_ICON[it.kind] || 'bell', 's')}<span class="dwt">${newsText(it, S.nf.users)}${it.task_title ? ' · ' + esc(it.task_title) : ''}</span></a></li>`)];
    return card(rows.length ? `<ul class="dwl">${rows.join('')}</ul>` : `<p class="muted">${tr('Nothing waits for you.')}</p>`, '', rows.length || '');
  }
  if (k === 'today') {
    const ts = openTasks().filter(t => !t.parent_id && t.due && t.due <= t0).sort((a, b) => dueKey(a).localeCompare(dueKey(b)) || b.priority - a.priority);
    const ev = (S.calToday || []).length;
    return card(tasksList(ts) || `<p class="muted">${tr('Nothing left for today.')}</p>`, `<a class="linkbtn" href="#today">${tr('Open')}</a>`, ts.length || '') ;
  }
  if (k === 'news') {
    if (S.nf.items === null || S.nf.sig !== (S.news?.sig ?? '')) { if (!S.nf.loading) loadNews().then(() => { if (S.route.mod === 'home') renderView(); }); }
    const vis = (S.nf.items || []).map((it, i) => [it, i]).filter(([it]) => !it.read);
    const gs = newsGroups(vis).slice(0, 5);
    return card(gs.length ? `<div class="dng">${gs.map(g => newsGroupHtml(g, false)).join('')}</div>` : `<p class="muted">${tr('No unread news')}</p>`, `<a class="linkbtn" href="#news">${tr('Show all')}</a>`, S.news?.unread || '');
  }
  if (k === 'chat') {
    if (!teamOn()) return '';
    if (S.tc.rooms === null && !S.tc.loading) { S.tc.loading = true; loadTeam().then(() => { S.tc.loading = false; if (S.route.mod === 'home') renderView(); }); }
    const rs = (S.tc.rooms || []).filter(r => r.last).slice(0, 4);
    return card(rs.length ? `<ul class="dwl">${rs.map(r => `<li><a href="#team/${r.id}">${roomIcon(r)}<span class="dwt"><b>${esc(roomName(r))}</b> ${esc(r.last.text)}</span>${r.unread ? `<span class="nbadge">${r.unread}</span>` : ''}</a></li>`).join('')}</ul>` : `<p class="muted">${tr('No messages yet')}</p>`, `<a class="linkbtn" href="#team">${tr('Open')}</a>`, S.team?.unread || '');
  }
  if (k === 'projects') {
    const ps = S.lists.filter(l => l.kind === 'project' && !l.archived);
    if (!ps.length) return '';
    return card(`<ul class="dpl">${ps.slice(0, 6).map(l => { const all = [...S.tasks.values()].filter(t => t.list_id === l.id && !t.parent_id), dn = all.filter(t => t.status === 2).length, pc = all.length ? Math.round(dn / all.length * 100) : 0;
      return `<li><a href="#l/${l.id}"><span class="dpn">${esc(lname(l))}</span><span class="dpb" role="img" aria-label="${esc(tr('{0} % done', pc))}"><i style="width:${pc}%"></i></span><span class="dpp">${pc} %</span></a></li>`; }).join('')}</ul>`, '', ps.length);
  }
  if (k === 'pinned') {
    const ts = openTasks().filter(t => t.pinned && !t.parent_id);
    return ts.length ? card(tasksList(ts), `<a class="linkbtn" href="#pinned">${tr('Open')}</a>`, ts.length) : '';
  }
  if (k === 'notes') {
    const ns = (S.notes || []).slice(0, 5);
    return ns.length ? card(`<ul class="dwl">${ns.map(n => `<li><a href="#note/${n.id}">${ic('edit', 's')}<span class="dwt"><b>${esc(n.title)}</b> <span class="muted">${esc(lname(listById(n.list_id)) || '')} · ${esc(relTime(n.updated_at))}</span></span></a></li>`).join('')}</ul>`) : '';
  }
  if (k === 'agents') {
    const ags = (S.agents || []).filter(a => a.enabled);
    return ags.length ? card(`<ul class="dwl">${ags.map(a => `<li><a href="#agents/${a.id}">${hdot(agentHst(a))}<span class="dwt">${esc(agentHstLine(a))}</span></a></li>`).join('')}</ul>`) : '';
  }
  if (k === 'stats') {
    const done7 = [...S.tasks.values()].filter(t => t.status === 2 && t.completed_at && t.completed_at.slice(0, 10) >= addDays(t0, -6)).length;
    const doneT = [...S.tasks.values()].filter(t => t.status === 2 && t.completed_at && t.completed_at.slice(0, 10) === t0).length;
    const over = openTasks().filter(t => !t.parent_id && t.due && t.due < t0).length;
    const tile = (n, l, href) => `<a class="dtile" href="${href}"><b>${n}</b><span>${esc(l)}</span></a>`;
    return card(`<div class="dtiles">${tile(doneT, tr('done today'), '#done')}${tile(done7, tr('done in 7 days'), '#stats')}${tile(over, tr('overdue'), '#today')}${tile(openTasks().filter(t => !t.parent_id).length, tr('open'), '#all')}</div>`);
  }
  if (k === 'family') {  // 2.19.0 (#653): the next birthdays, whose turn it is, today's meal
    if (!famOn()) return '';
    const d = famData(), t0x = today(), rows = [];
    for (const t of d.occ.filter(x => daysTo(x.due) <= 14).slice(0, 3)) rows.push(`<li><a href="#t/${t.id}"><span aria-hidden="true">${t.fam.kind === 'birthday' ? '🎂' : '💍'}</span><span class="dwt"><b>${esc(t.fam.name || t.title)}</b> ${esc([occWhat(t), daysWord(daysTo(t.due))].filter(Boolean).join(' · '))}</span></a></li>`);
    for (const t of d.rots.filter(x => x.assignee_id === S.me?.id).slice(0, 3)) rows.push(`<li><a href="#t/${t.id}">${ic('turns', 's')}<span class="dwt">${esc(tr('Your turn: {0}', t.title))}</span></a></li>`);
    for (const t of d.meals.filter(x => x.due === t0x).slice(0, 2)) rows.push(`<li><a href="#t/${t.id}">${ic('meal', 's')}<span class="dwt">${esc(tr('Today: {0}', t.title))}</span></a></li>`);
    return card(rows.length ? `<ul class="dwl">${rows.join('')}</ul>` : `<p class="muted">${tr('Nothing coming up.')}</p>`, `<a class="linkbtn" href="#family">${tr('Open')}</a>`);
  }
  if (k === 'search') {
    return card(`<form class="dsearch" data-dsearch role="search"><input id="dash-q" type="search" placeholder="${esc(tr('Jump, create, ask an agent…'))}" aria-label="${esc(tr('Search and commands'))}" autocomplete="off"><button type="submit" class="btn sm">${ic('search', 's')}<span class="sr">${tr('Search')}</span></button></form>`);
  }
  return '';
}
// 2.28.0 (#987): "N messages for you" above everything on the start page while something from people is unread
function forMeBanner() {
  if (!collab()) return '';
  const n = bellCount(); if (!n) return '';
  if (S.nf.items === null || S.nf.sig !== (S.news?.sig ?? '')) { if (!S.nf.loading) loadNews().then(() => { if (S.route.mod === 'home') renderView(); }); }
  const its = (S.nf.items || []).map((it, i) => [it, i]).filter(([it]) => !it.read && newsForMe(it) && newsInWs(it)).slice(0, 4), dms = dmRows().slice(0, 3);
  return `<section class="dtome" aria-labelledby="dtome-h"><h3 id="dtome-h">${ic('at', 's')}<span>${trn('{0} message for you', '{0} messages for you', n)}</span><span class="spacer"></span><a class="linkbtn" href="#news">${tr('Show all')}</a></h3>
    <ul class="dwl">${dms.map(r => `<li><a href="#team/${r.id}">${av(r.user_id, r.name, 'avatar')}<span class="dwt"><b>${esc(r.name)}</b> ${esc(r.last ? mdBrief(r.last.text) : '')}</span><span class="nbadge">${r.unread}</span></a></li>`).join('')}${its.map(([it, i]) => `<li><button type="button" class="dwb" data-act="news-open" data-i="${i}">${av(it.actor_id, uname(it.actor_id, S.nf.users), 'avatar')}<span class="dwt">${newsText(it, S.nf.users)}${it.task_title ? ' · ' + esc(it.task_title) : ''}</span></button></li>`).join('')}</ul></section>`;
}
function viewHome() {
  const greet = (() => { const h = new Date().getHours(); return h < 11 ? tr('Good morning, {0}', S.me?.display_name || '') : h < 18 ? tr('Hello, {0}', S.me?.display_name || '') : tr('Good evening, {0}', S.me?.display_name || ''); })();
  const parts = Object.fromEntries(lyBlocks('home').map(b => [b[0], dashCard(b[0])]));
  if (S.ly.view === 'home') return `<div class="dash">${lyEditor('home', {parts})}</div>`;  // 2.35.0 (#1097): with the cards
  return `<div class="dash"><div class="dashhead"><h2>${esc(greet)}</h2><span class="muted">${esc(fmtDateLoc(today()))}</span><span class="spacer"></span>${lyCustomBtn('home')}</div>
    ${forMeBanner()}${lyHtml('home', parts, {empty: `<p class="muted">${tr('Every card is hidden. Customize brings them back.')}</p>`})}</div>`;
}
document.addEventListener('submit', e => {
  if (!e.target.matches?.('[data-dsearch]')) return;
  e.preventDefault();
  const q = $('#dash-q')?.value.trim() || '';
  openPalette(); const inp = $('.palette .pqin'); if (inp && q) { inp.value = q; PAL.q = q; palDraw(); }
});

// ------------------------------------------------------------------ #443 Settings: tasks by e-mail
const mchk = (id, on, label) => `<label class="chkl"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}> ${esc(label)}</label>`;
function mailHtml(j) {
  if (!j) return `<div class="muted">${tr('Loading…')}</div>`;
  const row = (lab, addr, lid) => `<div class="row mailrow"><label>${esc(lab)}</label>${addr ? `<code class="topic mailaddr">${esc(addr)}</code><button type="button" class="btn sm" data-mail="copy" data-addr="${esc(addr)}">${ic('copy', 's')} ${tr('Copy')}</button><button type="button" class="btn sm" data-mail="new" data-lid="${lid ?? ''}">${ic('sync', 's')} ${tr('New address')}</button><button type="button" class="iconbtn" data-mail="del" data-lid="${lid ?? ''}" aria-label="${esc(tr('Remove') + ': ' + addr)}">${ic('x', 's')}</button>`
    : `<button type="button" class="btn sm pri" data-mail="new" data-lid="${lid ?? ''}">${ic('plus', 's')} ${tr('Create an address')}</button>`}</div>`;
  const own = S.lists.filter(l => !l.archived && !l.is_inbox && canEditList(l.id) && !j.lists.some(x => x.list_id === l.id));
  return j.enabled ? `${row(tr('Your inbox'), j.address)}
    ${j.lists.map(x => row(x.name, x.address, x.list_id)).join('')}
    ${own.length ? `<div class="row"><label for="mail-list">${tr('For a list')}</label><select id="mail-list" data-native>${own.map(l => `<option value="${l.id}">${esc(lname(l))}</option>`).join('')}</select><button type="button" class="btn sm" data-mail="newlist">${ic('plus', 's')} ${tr('Create')}</button></div>` : ''}
    <div class="shint">${tr('Subject = title, the text = description, attachments become files. Keep the address secret: whoever knows it can add tasks.')}</div>
    <div class="row"><label></label>${mchk('s-mailme', j.from_me, tr('Mails from my own address ({0}) to {1} go to my inbox', j.email || tr('none set'), j.plain))}</div>`
    : `<div class="shint">${S.me?.is_admin ? tr('Not set up on this server: an admin sets KALMIDO_MAIL_ADDRESS and KALMIDO_IMAP_* (see the README).') : tr('Not set up on this server yet. Ask your admin.')}</div>`;  // 2.25.0 (UX-20): server details only for admins
}
function mailDigestHtml(j) {
  if (!j) return '';
  return `<div class="row"><span class="rlab">${tr('Summary by e-mail')}</span>${j.digest.enabled ? mchk('s-digmail', j.digest.on, tr('Also send the daily summary by e-mail (at the time above, to {0})', j.email || tr('your e-mail address'))) : `<span class="muted">${tr('E-mail sending is not set up on this server')}</span>`}${j.digest.enabled && j.email ? `<button type="button" class="btn sm" data-mail="test">${ic('send', 's')} ${tr('Send now')}</button>` : ''}</div>`;
}
async function mailWire(md) {
  const box = $('#s-mail', md), dbx = $('#s-digmail-w', md); if (!box && !dbx) return;
  let j = null;
  const draw = () => { if (box) box.innerHTML = mailHtml(j); if (dbx) dbx.innerHTML = mailDigestHtml(j); };
  const reload = async () => { try { j = await api('GET', '/api/me/mail'); } catch { return; } draw(); };
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-mail]'); if (!b) return;
    const k = b.dataset.mail, lid = b.dataset.lid ? +b.dataset.lid : null;
    if (k === 'copy') { navigator.clipboard?.writeText(b.dataset.addr).then(() => toast(tr('Copied'))); return; }
    if (k === 'new' || k === 'newlist') {
      if (k === 'new' && (lid ? j.lists.some(x => x.list_id === lid) : j.address) && !await askConfirm(tr('A new address?'), tr('The old one stops working at once.'), {ok: tr('New address')})) return;
      try { await api('POST', '/api/me/mail/token', {list_id: k === 'newlist' ? +$('#mail-list', md).value : lid}); } catch { return; }
      await reload(); announce(tr('New address created')); return;
    }
    if (k === 'del') { if (!await askConfirm(tr('Remove this address?'), tr('Mails to it are no longer imported.'), {ok: tr('Remove'), danger: true})) return; try { await api('DELETE', '/api/me/mail/token' + (lid ? `?list_id=${lid}` : '')); } catch { return; } await reload(); return; }
    if (k === 'test') { try { const r = await api('POST', '/api/me/mail/test'); toast(tr('Sent to {0}', r.to)); } catch { /* api() said it */ } }
  });
  md.addEventListener('change', async e => {
    if (e.target.id === 's-mailme') { await api('PATCH', '/api/settings', {mail_from_me: e.target.checked ? '1' : '0'}).catch(() => {}); S.settings.mail_from_me = e.target.checked ? '1' : '0'; }
    if (e.target.id === 's-digmail') { await api('PATCH', '/api/settings', {digest_mail: e.target.checked ? '1' : '0'}).catch(() => {}); S.settings.digest_mail = e.target.checked ? '1' : '0'; }
  });
  reload();
}

// ---- 2.35.0 (#1097): Customize right in the view. The blocks of the view (their real content, not clickable while
// arranging) with a handle each: drag with the mouse, on a phone hold a block (then drag; the view scrolls along at the
// edges; a swipe or the Back swipe stays a swipe). The other blocks make room while dragging. Hide and the width at the
// block, hidden blocks at the bottom ("Hidden", a tap brings one back). Every change can be undone (toast, Ctrl+Z).
// One code path for every view of the builder (lyEditor); the list with the arrows below stays for keyboards.
function lydragCanvas(v, pr, parts) {
  const d = LY[v], {order, hidden, size, fixed} = pr, bs = lyBlocks(v), desk = !isMobile();
  const blk = k => {
    const b = bs.find(x => x[0] === k); if (!b) return '';
    const [, nm, icon] = b, sz = size(k), p = parts[k], h = typeof p === 'function' ? p('') : p;
    const body = h || `<div class="lyempty">${ic(icon, 's')}<b>${esc(tr(nm))}</b><span class="muted">${esc(p === undefined ? tr('Shown here') : tr('Nothing to show right now'))}</span></div>`;
    const wbtn = d.nosize || !desk ? '' : `<button type="button" class="btn sm lysz" data-act="ly-size" data-lyv="${v}" data-k="${k}" aria-pressed="${sz === 'full'}" title="${esc(tr('Width'))}" aria-label="${esc(tr('Width') + ': ' + tr(nm) + ', ' + (sz === 'full' ? tr('full width') : tr('half width')))}">${sz === 'full' ? tr('Full') : tr('Half')}</button>`;
    const hbtn = fixed.has(k) ? '' : `<button type="button" class="iconbtn" data-act="ly-cvhide" data-lyv="${v}" data-k="${k}" title="${esc(tr('Hide {0}', tr(nm)))}" aria-label="${esc(tr('Hide {0}', tr(nm)))}">${ic('eyeoff', 's')}</button>`;
    return `<div class="lyb ly-${sz} lyedb" data-lyk="${k}"><div class="lytool"><button type="button" class="lyhandle" data-lyhandle="${k}" title="${esc(desk ? tr('Drag to move; arrow keys move it too') : tr('Hold the block, then drag; arrow keys move it too'))}" aria-label="${esc(tr('Move {0}', tr(nm)))}" aria-describedby="lycvh-${v}">${ic('grip', 's')}<span>${esc(tr(nm))}</span></button><span class="spacer"></span>${wbtn}${hbtn}</div><div class="lybody" inert>${body}</div></div>`;
  };
  const hid = order.filter(k => hidden.has(k));
  const tray = hid.length ? `<div class="lyhid" aria-labelledby="lyhidh-${v}"><h3 id="lyhidh-${v}">${tr('Hidden')}</h3><div class="lyhidl">${hid.map(k => { const b = bs.find(x => x[0] === k); return b ? `<button type="button" class="btn sm" data-act="ly-cvshow" data-lyv="${v}" data-k="${k}" aria-label="${esc(tr('Show {0}', tr(b[1])))}">${ic('plus', 's')}${ic(b[2], 's')}<span>${esc(tr(b[1]))}</span></button>` : ''; }).join('')}</div></div>` : '';
  return `<p class="muted lyhint" id="lycvh-${v}">${desk ? tr('Drag a block by its handle to move it. Hide it or change its width at the block.') : tr('Hold a block, then drag it to move it. Hide it at the block.')}</p>
    <div class="${d.grid || 'lygrid'} lycanvas" data-lycanvas="${v}">${order.filter(k => !hidden.has(k)).map(blk).join('')}</div>${tray}`;
}
// one undoable change of the arrangement (drag, hide, show, width, arrows): the whole stored value before / after
function lydragDo(v, fn, msg, quiet) {
  const std = S.ly.view === v && S.ly.std, before = JSON.stringify(lyRaw(v, std));
  lyChange(v, fn);
  const after = JSON.stringify(lyRaw(v, std)); if (after === before) return;
  const put = s => () => { const o = JSON.parse(s); lyStore(v, Object.keys(o).length ? o : '', std); return {}; };
  const e = histAdd({label: msg || tr('Arrangement changed'), undo: put(before), redo: put(after)});
  if (quiet) announce(msg); else histToast(msg, e);
}
// the visible blocks in their new DOM order -> the order (hidden ones keep their places)
function lydragOrder(v, keys) {
  return st => { const vis = new Set(keys); let i = 0; st.order = st.order.map(k => vis.has(k) ? keys[i++] : k); };
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act="ly-cvhide"],[data-act="ly-cvshow"]'); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  const v = a.dataset.lyv, k = a.dataset.k, b = LY[v] && lyBlocks(v).find(x => x[0] === k); if (!b) return;
  const show = a.dataset.act === 'ly-cvshow';
  lydragDo(v, st => { if (show) st.hidden.delete(k); else st.hidden.add(k); }, show ? tr('{0} shown', tr(b[1])) : tr('{0} hidden', tr(b[1])));
  setTimeout(() => (show ? $(`#view .lycanvas [data-lyhandle="${k}"]`) : $(`#view .lyhid [data-act="ly-cvshow"][data-k="${k}"]`))?.focus(), 30);
}, true);
document.addEventListener('toggle', e => { if (e.target.classList?.contains('lylist')) LS.set('lyList', e.target.open); }, true);
// keyboard on a block's handle: arrow keys move the block one place
document.addEventListener('keydown', e => {
  const hd = e.target.closest?.('.lycanvas .lyhandle'); if (!hd || !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) return;
  e.preventDefault();
  const v = hd.closest('.lycanvas').dataset.lycanvas, k = hd.dataset.lyhandle, dl = e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 1;
  const keys = $$('.lyedb', hd.closest('.lycanvas')).map(x => x.dataset.lyk), i = keys.indexOf(k), j = i + dl;
  if (j < 0 || j >= keys.length) return;
  [keys[i], keys[j]] = [keys[j], keys[i]];
  lydragDo(v, lydragOrder(v, keys), dl < 0 ? tr('Moved up') : tr('Moved down'), true);
  setTimeout(() => $(`#view .lycanvas [data-lyhandle="${k}"]`)?.focus(), 30);
});
// dragging: mouse / pen from the handle (pointer events), touch from a long press anywhere on the block (touch events,
// as the sidebar: only an active drag stops the page from scrolling)
let lyDg = null;
function lydragScroller(el) {
  for (let p = el?.parentElement; p; p = p.parentElement) { const oy = getComputedStyle(p).overflowY; if ((oy === 'auto' || oy === 'scroll') && p.scrollHeight > p.clientHeight) return p; }
  return document.scrollingElement;
}
function lydragBegin(el, x, y) {
  const cv = el.closest('.lycanvas'), r = el.getBoundingClientRect(), g = el.cloneNode(true);
  g.removeAttribute('data-lyk'); g.classList.add('lyghost');
  g.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${Math.min(r.height, 240)}px;z-index:96;pointer-events:none`;
  document.body.appendChild(g);
  el.classList.add('lyplace');
  lyDg = {...lyDg, el, cv, v: cv.dataset.lycanvas, g, dx: x - r.left, dy: y - r.top, active: true, start: $$('.lyedb', cv).map(n => n.dataset.lyk), sc: lydragScroller(cv)};
  document.body.classList.add('lydragging');
  if (navigator.vibrate) navigator.vibrate(12);
}
function lydragMove(x, y) {
  const st = lyDg; if (!st?.active) return;
  st.x = x; st.y = y;
  st.g.style.left = (x - st.dx) + 'px'; st.g.style.top = (y - st.dy) + 'px';
  const t = document.elementFromPoint(x, y)?.closest?.('.lycanvas .lyedb');
  if (t && t !== st.el && t.parentElement === st.cv) {
    const r = t.getBoundingClientRect(), wide = r.width > st.cv.clientWidth * .75;
    const after = wide ? y > r.top + r.height / 2 : x > r.left + r.width / 2;
    const ref = after ? t.nextSibling : t;
    if (ref !== st.el && st.el.nextSibling !== ref) st.cv.insertBefore(st.el, ref);
  }
  // near the top / bottom edge the view scrolls along
  clearInterval(st.auto); st.auto = null;
  const vh = innerHeight, edge = 56, dir = y < edge ? -1 : y > vh - edge ? 1 : 0;
  if (dir) st.auto = setInterval(() => { st.sc?.scrollBy(0, dir * 14); lydragMove(st.x, st.y); }, 30);
}
function lydragEnd(cancel) {
  const st = lyDg; lyDg = null;
  if (!st) return;
  clearTimeout(st.timer); clearInterval(st.auto);
  if (!st.active) return;
  st.g.remove(); st.el.classList.remove('lyplace'); document.body.classList.remove('lydragging');
  const keys = $$('.lyedb', st.cv).map(n => n.dataset.lyk);
  if (cancel || keys.join() === st.start.join()) { if (cancel) renderView(); return; }
  const nm = lyBlocks(st.v).find(b => b[0] === st.el.dataset.lyk)?.[1];
  lydragDo(st.v, lydragOrder(st.v, keys), tr('{0} moved', tr(nm || '')));
  setTimeout(() => $(`#view .lycanvas [data-lyhandle="${st.el.dataset.lyk}"]`)?.focus({preventScroll: true}), 30);
}
document.addEventListener('pointerdown', e => {
  if (e.pointerType === 'touch' || e.button !== 0) return;
  const hd = e.target.closest?.('.lycanvas .lyhandle'); if (!hd) return;
  lyDg = {x0: e.clientX, y0: e.clientY, hd, el: hd.closest('.lyedb'), active: false, mouse: true};
});
document.addEventListener('pointermove', e => {
  if (!lyDg?.mouse) return;
  if (!lyDg.active) { if (Math.hypot(e.clientX - lyDg.x0, e.clientY - lyDg.y0) < 5) return; lydragBegin(lyDg.el, lyDg.x0, lyDg.y0); }
  e.preventDefault(); lydragMove(e.clientX, e.clientY);
});
document.addEventListener('pointerup', () => { if (lyDg?.mouse) lydragEnd(false); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && lyDg?.active) { e.preventDefault(); e.stopPropagation(); lydragEnd(true); } }, true);
document.addEventListener('touchstart', e => {
  const el = e.target.closest?.('.lycanvas .lyedb'); if (!el || e.touches.length > 1 || e.target.closest('.lytool button:not(.lyhandle)')) return;
  const p = e.touches[0]; if (p.clientX < 24 || p.clientX > innerWidth - 24) return;  // the Back swipe from the edge stays free
  lyDg = {x0: p.clientX, y0: p.clientY, el, active: false, touch: true};
  lyDg.timer = setTimeout(() => { if (lyDg?.touch && !lyDg.active) lydragBegin(el, lyDg.x0, lyDg.y0); }, 420);
}, {passive: true});
document.addEventListener('touchmove', e => {
  if (!lyDg?.touch) return;
  const p = e.touches[0];
  if (!lyDg.active) { if (Math.hypot(p.clientX - lyDg.x0, p.clientY - lyDg.y0) > 8) { clearTimeout(lyDg.timer); lyDg = null; } return; }  // a scroll / swipe
  e.preventDefault(); lydragMove(p.clientX, p.clientY);
}, {passive: false});
document.addEventListener('touchend', e => { if (lyDg?.touch) { if (lyDg.active && e.cancelable) e.preventDefault(); lydragEnd(false); } });
document.addEventListener('touchcancel', () => { if (lyDg?.touch) lydragEnd(true); });
document.addEventListener('contextmenu', e => { if (e.target.closest?.('.lycanvas .lyedb') && isTouch()) e.preventDefault(); });  // the long press is the drag
