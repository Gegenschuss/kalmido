// 2.51.0 (#1351 #1358): the review dialog of the proposal kinds inquiry (an inquiry becomes a project: tasks, shoot days as
// event drafts, a quotation draft) and setup (modules, lists, a first project), drawn into agents.js propDraw; and the entry
// "Set up with your agent" (Settings > Modules, the last card of the welcome tour). Keys like the server
// (agents/propkinds2.py): tasks "i" / "i.k", shoot days 300+i, the quotation 400 / "400.j"; setup modules i, lists 100+i,
// the project 200.
const PK2_SHOOT = 300, PK2_OFFER = 400, PK2_LIST = 100, PK2_PROJECT = 200;
const pk2_is = k => k === 'inquiry' || k === 'setup';
const pk2_offerOk = v => !!(v.input?.office?.ok);
function pk2_keys(v) {
  const p = v.proposal; if (!p) return [];
  if (v.kind === 'setup') return [...p.modules.map((m, i) => String(i)), ...p.lists.map((x, i) => String(PK2_LIST + i)), ...(p.project ? [String(PK2_PROJECT)] : [])];
  return [...p.tasks.flatMap((t, i) => [String(i), ...t.subtasks.map((s, k) => `${i}.${k}`)]),
    ...p.shoot_days.map((s, i) => String(PK2_SHOOT + i)),
    ...(p.offer && pk2_offerOk(v) ? [String(PK2_OFFER), ...p.offer.items.map((x, j) => `${PK2_OFFER}.${j}`)] : [])];
}
const pk2_h = t => `<h4 class="pk2h">${esc(t)}</h4>`;
const pk2_chip = (icon, t) => `<span class="ppchip">${ic(icon, 's')}${esc(t)}</span>`;
// a line without title / date fields (a module, a quotation line): checkbox + text + chips
function pk2_plain(k, text, chips = '', o = {}) {
  const on = !o.off && S.prop.sel.has(k), id = ppSafe(k);
  return `<div class="ppi pk2p ${o.sub ? 'sub' : ''} ${on ? '' : 'off'}" data-k="${k}">
    <label class="ppcl"><input type="checkbox" class="ppc" id="ppc-${id}" ${on ? 'checked' : ''} ${o.off ? 'disabled' : ''} aria-label="${esc(tr('Select {0}', text))}"></label>
    <div class="ppb"><div class="pprow"><label class="pk2t" for="ppc-${id}">${esc(text)}</label></div>${chips ? `<div class="ppf">${chips}</div>` : ''}</div></div>`;
}
// a line with an editable name and no date (a list, the first project)
function pk2_named(k, title, chips = '') {
  const on = S.prop.sel.has(k), id = ppSafe(k);
  return `<div class="ppi ${on ? '' : 'off'}" data-k="${k}">
    <label class="ppcl"><input type="checkbox" class="ppc" id="ppc-${id}" ${on ? 'checked' : ''} aria-label="${esc(tr('Select {0}', title))}"></label>
    <div class="ppb"><div class="pprow"><input class="ppt" data-f="title" value="${esc(title)}" maxlength="120" aria-label="${esc(tr('Name'))}"></div>${chips ? `<div class="ppf">${chips}</div>` : ''}</div></div>`;
}
const pk2_money = (n, cur) => { try { return new Intl.NumberFormat(S.settings?.lang || undefined, {style: 'currency', currency: cur || 'EUR'}).format(n); } catch { return String(n); } };
function pk2_shootWhen(s) {  // the date is the field; the chip says the span and the time
  return [s.end_date ? `${fmtDate(s.date)} – ${fmtDate(s.end_date)}` : '', s.start_time ? `${s.start_time}${s.end_time ? '–' + s.end_time : ''}` : tr('All day')].filter(Boolean).join(' · ');
}
function pk2_itemsHtml() {
  const {v} = S.prop, p = v.proposal;
  if (v.kind === 'setup') {
    const fname = k => tr((FEATS.find(f => f[0] === k) || [k, k])[1]);
    const pt = p.project && PTYPE_UI.find(x => x[0] === p.project.type);
    return (p.modules.length ? pk2_h(tr('Modules')) + p.modules.map((m, i) => pk2_plain(String(i), m.on ? tr('Switch on: {0}', fname(m.key)) : tr('Switch off: {0}', fname(m.key)))).join('') : '')
      + (p.lists.length ? pk2_h(tr('Projects')) + p.lists.map((x, i) => pk2_named(String(PK2_LIST + i), x.name,
        (x.folder ? pk2_chip('folder', x.folder) : '') + x.sections.map(s => `<span class="ppchip">${esc(s)}</span>`).join(''))).join('') : '')
      + (p.project ? pk2_h(tr('First project')) + pk2_named(String(PK2_PROJECT), p.project.name, pk2_chip('folder', tr(pt ? pt[1] : p.project.type))) : '')
      + `<div class="shint keep pk2hint">${esc(pk2_hint(v))}</div>`;
  }
  const secOpts = cur => `<option value="">${tr('No section')}</option>${p.sections.map(s => `<option ${s === cur ? 'selected' : ''}>${esc(s)}</option>`).join('')}`;
  let h = '';
  const cl = p.client, off = v.input?.offer;
  if (cl || off) h += `<div class="pk2info">${off ? pk2_chip('file', tr('From the accepted quotation {0}', off.number || off.title || '#' + off.id)) : ''}
    ${cl ? pk2_chip('users', cl.id ? tr('Client: {0}', cl.name) : tr('New client: {0} (create it in the office)', cl.name)) : ''}</div>`;
  h += pk2_h(tr('Tasks')) + p.tasks.map((t, i) => propItemHtml(String(i), t, {
    fields: p.sections.length ? `<select data-f="section" aria-label="${esc(tr('Section'))}">${secOpts(t.section)}</select>` : '',
    chips: propPrio(t.priority)}) + t.subtasks.map((s, k) => propItemHtml(`${i}.${k}`, s, {sub: true})).join('')).join('');
  if (p.shoot_days.length) h += pk2_h(tr('Shoot days (event drafts)')) + p.shoot_days.map((s, i) => propItemHtml(String(PK2_SHOOT + i), {title: s.title, due: s.date, notes: s.notes},
    {chips: pk2_chip('cal', pk2_shootWhen(s)) + (s.location ? pk2_chip('pin', s.location) : '')})).join('');
  if (p.offer) {
    const ok = pk2_offerOk(v), sum = p.offer.items.reduce((a, x) => a + (x.price == null ? 0 : x.qty * x.price * (1 - (x.discount || 0) / 100)), 0);
    h += pk2_h(tr('Quotation draft')) + (ok ? '' : `<div class="shint keep pk2no">${esc(tr('Not possible: no office rights (the agent’s switch “May draft office documents” and the office’s privacy switch)'))}</div>`)
      + pk2_plain(String(PK2_OFFER), p.offer.title, pk2_chip('file', tr('Net about {0}', pk2_money(sum))), {off: !ok})
      + p.offer.items.map((x, j) => pk2_plain(`${PK2_OFFER}.${j}`, x.text, `<span class="ppchip">${esc(`${x.qty} ${x.unit || ''}`.trim())}${x.price == null ? '' : ' × ' + esc(pk2_money(x.price))}</span>`
        + (x.service_id ? '' : pk2_chip('flag', tr('free item'))) + (x.discount ? `<span class="ppchip">${esc(tr('Discount {0} %', x.discount))}</span>` : ''), {sub: true, off: !ok})).join('');
  }
  return h + `<div class="shint keep pk2hint">${esc(pk2_hint(v))}</div>`;
}
function pk2_hint(v) {
  if (v.kind === 'setup') return tr('Applying switches the modules and creates the projects as you, only for you. One step, undo takes it back (projects only while they are empty).');
  if (!v.proposal?.offer) return tr('Applying creates the project, its tasks and the shoot days as event drafts in your calendar, as you. Nothing is sent. One step, undo takes it back.');  // 2.58.0 (#1810): no quotation in it
  return tr('Applying creates the project, its tasks, the shoot days as event drafts in your calendar and the quotation as a draft, as you. Nothing is sent. One step, undo takes it back.');
}
function pk2_toast(v, r) {
  if (v.kind === 'setup') return tr('Set up: {0} modules, {1} projects', r.modules || 0, r.lists || 0);
  return [trn('{0} task created', '{0} tasks created', r.created), r.events ? trn('{0} event draft', '{0} event drafts', r.events) : '', r.offer_id ? tr('quotation draft') : ''].filter(Boolean).join(', ');
}
// ---- #1358: "Set up with your agent" (Settings > Modules, the welcome tour)
const pk2_setupHtml = () => feat('agents') ? `<div class="pk2setup"><button type="button" class="btn sm" data-pk2="setup">${ic('bot', 's')} ${esc(tr('Set up with your agent'))}</button>
  <span class="muted">${esc(tr('Tell your agent what you use Kalmido for: it proposes modules, projects and a project template, you decide.'))}</span></div>` : '';
async function pk2_setupGo() {
  let ags = [];
  try { ags = (await api('GET', '/api/proposals/agents')).agents || []; } catch { /* offline: as without an agent */ }
  const a = ags.find(x => x.online && !x.limit_reached) || ags.find(x => !x.limit_reached);
  if (!a) { settingsModal('agents'); toast(tr('Connect an agent first (Settings > Agents), then it can set Kalmido up with you.')); return; }
  $$('.modal').forEach(m => { if (m.classList.contains('smodal')) m.remove(); });
  chatOpen(a.id);
  const text = tr('I use Kalmido for … Please propose modules, projects and a project template for me (setup proposal).');
  for (let i = 0; i < 20; i++) {  // the chat input appears once the chat is drawn (on a phone after the route change)
    const inp = $('#chat-in');
    if (inp) { if (!inp.value) { inp.value = text; inp.dispatchEvent(new Event('input', {bubbles: true})); } inp.focus(); const at = text.indexOf('…'); if (at >= 0) inp.setSelectionRange(at, at + 1); return; }
    await new Promise(res => setTimeout(res, 150));
  }
}
document.addEventListener('click', e => {
  if (!e.target.closest?.('[data-pk2="setup"]')) return;
  if ($('.tour') && typeof tourEnd === 'function') tourEnd(true);
  pk2_setupGo();
});
