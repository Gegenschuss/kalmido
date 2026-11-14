// @ts-check
/* Kalmido web client: the project dialog (listModal: name, type, sections, stale days, the webhook box) and its parts (2.1156.0, #4280: moved here from dialogs.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

const PTYPE_KINDS = {software: ['open', 'open', 'progress', 'review', 'done']};  // 2.577.0 (#3354): as PTYPES section_kinds
const ptSecKind = (k, n) => PTYPE_KINDS[k]?.[(PTYPE_SECS[k] || []).findIndex(x => tr(x) === n)] || '';
// 2.4.0 (#243): a new Software / AI dev project: the next steps (repository of the 2.2.0 Git integration, a coding agent)
async function projectNextSteps(lid) {
  let ags = [];
  if (collab()) { try { ags = (await api('GET', '/api/users')).users.filter(u => u.agent && !u.disabled); } catch { /* offline */ } }
  // 2.40.0 (#1414): an agent already in the list (e.g. the folder's default agent) is not offered again; one agent per list,
  // so then the step only says who is connected
  const l0 = listById(lid), inL = listAgents(l0);
  const joined = inL.length ? `<div class="nstep nsjoined"><b>${tr('Coding agent')}</b><span class="muted">${ic('bot', 's')} ${esc(l0?.folder ? tr('{0} is already connected through the folder “{1}”.', inL.map(a => a.display_name || a.username).join(', '), fDisp(l0.folder)) : tr('{0} is already in this project.', inL.map(a => a.display_name || a.username).join(', ')))}</span></div>` : '';
  if (inL.length) ags = [];
  /** @type {any} */
  const md = modal(`<h3>${ic('code', 's')} ${tr('Next steps for {0}', esc(lname(listById(lid))))}</h3>
    <div class="nsteps"><div class="nstep"><b>${tr('Connect a repository')}</b><span class="muted">${tr('GitHub, GitLab, Gitea / Forgejo or Bitbucket: pull requests, commits and CI show up at the tickets, “fixes #id” completes them.')}</span><button class="btn sm" data-m="repo">${ic('git', 's')} ${tr('Repository…')}</button></div>
    ${joined}${ags.length ? `<div class="nstep"><b>${tr('Share with a coding agent')}</b><span class="muted">${tr('Optional: the agent gets the tickets of this project as events, works in the repository and asks for approval before merging.')}</span><div class="row"><select id="ns-agent" aria-label="${esc(tr('Agent'))}">${ags.map(a => `<option value="${a.id}">${esc(a.display_name)}</option>`).join('')}</select><button class="btn sm" data-m="share">${ic('bot', 's')} ${tr('Share')}</button></div></div>` : ''}</div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('nsmodal');
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') md.remove();
    if (b.dataset.m === 'repo') { md.remove(); listModal(lid, '', {open: 'proj'}); setTimeout(() => { const r = $('.lmodal #l-repos-h'); r?.scrollIntoView?.({block: 'start'}); }, 150); }
    if (b.dataset.m === 'share') {
      if (!await agSafeFirst()) return;  // 2.30.0 (#920 / #919)
      try { await bridgeTry(ok => api('PUT', `/api/lists/${lid}/members`, {user_id: +$('#ns-agent', md).value, role: 'edit', ...(ok ? {bridge_ok: true} : {})})); } catch { return; }
      b.disabled = true; b.textContent = tr('Shared'); await load(); render();
    }
  });
}
const ptypeHint = k => tr(ptypeUi('shoot').find(x => x[0] === (k || ''))?.[3] || PTYPE_UI[0][3]);
// the Repository area of a project: for software projects and for every list that already has a repository
const repoShown = l => l.ptype === 'software' || !!(l.repos || []).length;  // 2.352.0 B (#2752): kind is not read
// 2.22.0 (#746): the software parts of a list's properties (ticket types, repository) only for a software project or a list
// that has a repository; never for family / household lists, kids or people who set Kalmido up for home or family
const swArea = l => repoShown(l);
const swOffer = l => !!l && !l.is_inbox && !l.family && !l.life && !S.me?.kid && !['family', 'home'].includes(S.settings.purpose || '') && !swArea(l);
function ptypeRowHtml(l) {
  const may = canManage(l), why = may ? '' : tr('Only the owner and project admins can switch progress and status');
  return `<div class="row lptrow"><label for="l-ptype">${tr('Project type')}</label><select id="l-ptype" ${may ? '' : `disabled title="${esc(why)}"`}>${ptypeUi(l.ptype).map(([k, n]) => `<option value="${k}" ${(l.ptype || '') === k ? 'selected' : ''}>${k ? tr(n) : tr('None|project type')}</option>`).join('')}</select></div>
    <div class="shint lhint" id="l-pthint">${esc(ptypeHint(l.ptype || ''))}</div><div id="l-ptoffer" aria-live="polite"></div>`;
}
async function setListPtype(id, pt, o = {}) {  // o.post: runs after an undo / redo (the open dialog follows)
  const l = listById(id); if (!l) return false;
  const old = l.ptype || '';
  if (old === pt) return false;
  let r; try { r = await api('PATCH', '/api/lists/' + id, {ptype: pt}); } catch { return false; }
  await load(); render();
  modulesOnToast(r.modules_on);
  const prev = r.ptype_prev || {}, x = listById(id) || l;
  const before = {ptype: old, ...prev}, after = {ptype: pt};
  for (const k in prev) after[k] = lv(k, x[k]);  // 0 / 1 for the ticket types, as stored (the server's _prev check)
  // list admins: only the type itself (kind / ticket types / view are the owner's settings; they stay switched on)
  const go = (to, from) => async () => {
    const own = isOwner(listById(id) || l), pick = o => own ? o : {ptype: o.ptype, ...('props' in o ? {props: o.props} : {})};  // 2.412.0 (#3552): props = owner + admins
    const res = await api('PATCH', '/api/lists/' + id, {...pick(to), _prev: pick(from)});
    return {skipped: (res.conflicts || []).length ? [`${qn(lname(listById(id)) || '')}: ${tr('Project type')}`] : []};
  };
  const e = histAdd({label: tr('Project type of {0}: {1}', qn(lname(x)), ptypeName(pt)), res: r, undo: go(before, after), redo: go(after, before), lids: [id], post: o.post});  // 2.1074.0 (#5493): res = its server step
  return {e, missing: r.ptype_missing || {sections: [], fields: []}};
}
// after a type change: offer (never force) the type's sections the list does not have yet; added = one undo step
function ptypeOfferDraw(box, id, k, names) {
  if (!names.length || !canEditList(id)) { box.innerHTML = ''; return; }
  box.innerHTML = `<div class="shint keep lhint ptoffer"><span>${esc(tr('Add the sections of {0}: {1}?', ptypeName(k), names.join(', ')))}</span>
    <span class="ptobtns"><button type="button" class="btn sm pri" data-pto="add">${ic('plus', 's')} ${tr('Add sections')}</button><button type="button" class="btn sm" data-pto="no">${tr('No thanks')}</button></span></div>`;
  box.onclick = async e => {
    const b = e.target.closest('[data-pto]'); if (!b) return;
    if (b.dataset.pto === 'no') { box.innerHTML = ''; return; }
    b.disabled = true;
    const made = await ptypeAddSections(id, names, k);
    box.innerHTML = '';
    if (made) $('#l-ptype', box.closest('.modal') || document)?.focus();
  };
}
async function ptypeAddSections(id, names, k) {
  const made = [];
  for (const n of names) { try { const r = await api('POST', '/api/sections', {list_id: id, name: n, kind: ptSecKind(k, n)}); made.push({id: r.id, name: n, kind: ptSecKind(k, n), ug: r.undo_group}); } catch { break; } }  // 2.809.0 (#5476): ug = its step on the server
  if (!made.length) return null;
  await load(); render();
  const del = async () => {
    let skip = 0;
    for (const s of made) { const r = await api('DELETE', '/api/sections/' + s.id, {_prev: {name: s.name, tasks: []}}); if (r && r.ok === false) skip++; }
    return {skipped: skip ? [tr('Sections of {0}', qn(lname(listById(id)) || ''))] : []};
  };
  const add = async () => { for (const s of made) s.id = (await api('POST', '/api/sections', {list_id: id, name: s.name, kind: s.kind})).id; return {}; };
  offerUndo(trn('{0} section added', '{0} sections added', made.length), histAdd({label: tr('Sections of {0}', qn(lname(listById(id)) || '')), undo: del, redo: add, lids: [id], ...(made.every(s => s.ug) ? {srv: true} : {})}));
  return made;
}
function staleRowHtml(l) {
  const v = l.stale_days == null ? '' : String(l.stale_days), d = S.staleDays || 7;
  const opts = [['', tr('Default ({0} days)', d)], ...STALE_OPTS.filter(n => n !== d).map(n => [String(n), trn('{0} day', '{0} days', n)]), ['0', tr('Never|idle')]];
  if (v && !opts.some(o => o[0] === v)) opts.splice(1, 0, [v, trn('{0} day', '{0} days', +v)]);
  return `<div class="row lstalerow"><label for="l-stale">${tr('Lying idle after')}</label><select id="l-stale">${opts.map(([k, n]) => `<option value="${k}" ${k === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>
    <div class="shint lhint">${tr('Open tasks without a change, comment or time entry for this long show in “Lying idle”.')}</div>`;
}
async function staleDaysSet(lid, sel) {
  const sd = sel.value === '' ? null : +sel.value;  // 2.41.2 (#1501): at once, no GET /api/state afterwards
  try { await optWrite(optSet(() => listById(lid), {stale_days: sd}), () => api('PATCH', `/api/lists/${lid}`, {stale_days: sd})); toast(tr('Saved')); staleLoad(true); }
  catch { const l = listById(lid); sel.value = l?.stale_days == null ? '' : String(l.stale_days); }
}
// 2.46.2 (#1659): the list name while it is typed: sidebar and header show it at once (l._live, read by licName); it is
// saved after the 0.9 s pause as before (one undo step); a state that arrives meanwhile gets it again (OPT, like optWrite)
const FL_LIVE = new Map();
const fl_liveDraw = debounce(() => { renderSide(); renderTop(); }, 16);  // 2.599.0 (#4506): debounce instead of a clearTimeout / setTimeout pair
function fl_nameLive(id, name) {
  let p = FL_LIVE.get(id);
  if (!p) { p = {v: null, put: () => { const l = listById(id); if (l) { if (p.v == null) delete l._live; else l._live = p.v; } }}; FL_LIVE.set(id, p); OPT.add(p); }
  p.v = name || null; p.put();
  fl_liveDraw();
}
function fl_nameEnd(id) {
  const p = FL_LIVE.get(id); if (!p) return;
  OPT.delete(p); FL_LIVE.delete(id); const l = listById(id); if (l) delete l._live;
  fl_liveDraw.cancel(); renderSide(); renderTop();
}
// 2.22.0 (#682): a new list / project gets a fitting emoji from its name (a local word list in the six languages, no AI):
// suggested in the dialog as soon as a word matches, one tap on it changes or removes it; existing lists stay as they are
const AUTO_EMO = [
  ['🛒', 'einkauf shopping grocer groceries supermarkt supermarket courses épicerie compra compras spesa boodschappen'],
  ['💼', 'arbeit work job büro office travail trabajo oficina lavoro ufficio werk kantoor business'],
  ['👨‍👩‍👧', 'familie family famille familia famiglia gezin kinder kids enfants niños bambini'],
  ['🏖️', 'urlaub holiday vacation ferien vacances vacaciones vacanze vakantie strand beach plage playa spiaggia'],
  ['✈️', 'reise trip travel flug flight voyage viaje viaggio reis'],
  ['🏠', 'haus house home zuhause haushalt household maison casa hogar huis wohnung apartment appartement'],
  ['🌱', 'garten garden jardin jardín giardino tuin pflanzen plants'],
  ['🚗', 'auto car voiture coche macchina wagen kfz'],
  ['💰', 'geld money finanzen finance finances dinero soldi geld budget steuer tax taxes impôts impuestos tasse belasting bank'],
  ['🩺', 'gesundheit health arzt doctor santé médecin salud médico salute medico gezondheid dokter'],
  ['🏃', 'sport fitness training laufen running gym deporte allenamento hardlopen'],
  ['📚', 'lesen reading bücher books lecture livres lectura libros lettura libri lezen boeken studium study school schule uni université universidad università'],
  ['🎁', 'geschenk geschenke gift gifts cadeau cadeaux regalo regali'],
  ['🎂', 'geburtstag birthday anniversaire cumpleaños compleanno verjaardag party feier fête fiesta festa feest'],
  ['🍳', 'kochen cooking rezepte recipes essen meals cuisine recettes cocina recetas cucina ricette koken recepten'],
  ['🐾', 'haustier pet pets hund dog katze cat chien chat perro gato cane gatto hond kat'],
  ['🔧', 'reparatur repair renovierung renovation werkzeug diy bricolage reparación riparazione klussen'],
  ['💻', 'software code coding dev entwicklung development app website web it programmierung'],
  ['📝', 'notizen notes ideen ideas idées ideas idee ideeën'],
  ['🎵', 'musik music musique música musica muziek'],
  ['📦', 'umzug moving déménagement mudanza trasloco verhuizing'],
  ['💍', 'hochzeit wedding mariage boda matrimonio bruiloft'],
  ['🎄', 'weihnachten christmas noël navidad natale kerst'],
  ['📄', 'verträge contracts vertrag contract contrats contratos contratti contracten versicherung insurance assurance seguro assicurazione verzekering'],
  ['👶', 'baby bébé bebé neonato'],
  ['🧹', 'putzen cleaning ménage limpieza pulizie schoonmaken'],
];
function autoEmoji(name) {
  if (S.settings && S.settings.list_emoji === '0') return '';  // 2.32.0 (#1077): switched off in Settings > Appearance
  const words = String(name || '').toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(w => w.length > 2);
  if (!words.length) return '';
  const hit = f => AUTO_EMO.find(([, ks]) => ks.split(' ').some(k => words.some(w => f(w, k))));  // the beginning of a word first
  return (hit((w, k) => w === k || (k.length > 3 && w.startsWith(k))) || hit((w, k) => k.length > 4 && w.endsWith(k)) || [''])[0];
}
// 2.352.0 C (#2751): a folding part of the project dialog, built like the Share dialog's (shSec): closed at first, its
// short state in the folded line (lmSum), open / closed remembered per device (LS lmSecs), a dot when a setting in it
// differs from the folder's (folder_own); a part without content is left out. o.open / an archived project open a part
const LM_FKEYS = {time: ['time_tracking'], show: ['hide_done'], agents: ['agent_id', 'agent_members', 'agent_tidy', 'agent_listen', 'agent_followup']};
const lmOpen = k => !!(LS.get('lmSecs', {}) || {})[k];
function lmSec(k, title, inner, fown = [], open = false) {
  if (!inner.replace(/<[^>]*>/g, '').trim()) return '';  // no text = nothing in it
  const dot = (LM_FKEYS[k] || []).some(x => fown.includes(x));
  return `<details class="shsec lmsec" id="lm-sec-${k}" data-lmsec="${k}" ${open || lmOpen(k) ? 'open' : ''}><summary><h4>${title}</h4>${dot ? `<span class="lmdot" role="img" aria-label="${esc(tr('Differs from the folder'))}" title="${esc(tr('Differs from the folder'))}"></span>` : ''}<span class="shsecst muted" id="lm-st-${k}"></span>${ic('chev', 's shchev')}</summary><div class="lmsecb">${inner}</div></details>`;
}
// the short state: the switches that are on (the row's label, or the switch's own text in a row with several), the
// selects not at their default ("label: choice"), the filled number fields, and texts marked .lmsum; else a default
function lmSum(sec) {
  const out = [], lab = el => (el.closest('.row')?.querySelector(':scope > label')?.textContent || '').trim();
  for (const el of sec.querySelectorAll('.lmsecb input, .lmsecb select, .lmsecb .lmsum, .lmsecb #l-e2e-st')) {
    if (el.closest('[hidden], .members, .emogrid, .pbarea, .pzlist')) continue;  // 2.412.0 (#3552): .pzlist says its state in .lmsum
    if (el.matches('.lmsum, #l-e2e-st')) { if (el.textContent.trim()) out.push(el.textContent.trim()); continue; }
    if (el.type === 'checkbox') { if (!el.checked) continue; const r = el.closest('.row'), n = r ? r.querySelectorAll('input[type="checkbox"]').length : 0; out.push(n === 1 && lab(el) ? lab(el) : (el.closest('label')?.textContent || '').trim()); continue; }
    if (el.tagName === 'SELECT') { const d = el.dataset.lmdef ?? el.options[0]?.value; if (el.value !== d && el.selectedOptions[0]) out.push(`${lab(el)}: ${el.selectedOptions[0].textContent.trim()}`); continue; }
    if (el.type !== 'hidden' && el.type !== 'radio' && el.value.trim() && el.id) out.push(`${lab(el)}: ${el.value.trim()}${el.id === 'l-rate' && S.settings.time_currency ? ' ' + S.settings.time_currency : ''}`);
  }
  const k = sec.dataset.lmsec;
  const nf = k === 'proj' ? sec.querySelectorAll('#l-fields [data-fid]').length : 0;  // 2.582.0 (#4490): the custom fields count in the folded line
  if (nf) out.push(trn('{0} custom field', '{0} custom fields', nf));
  if (!out.length) out.push(k === 'time' && $('#l-time', sec) ? `${tr('Time tracking')}: ${tr('Off')}` : k === 'sec' ? tr('Off') : k === 'acts' ? '' : tr('Default'));
  return out.filter(Boolean).join(' · ');
}
function lmSecWire(md) {
  const draw = () => { for (const sec of $$('.lmsec', md)) { const st = $('.shsecst', sec); if (st) st.textContent = lmSum(sec); } };
  let q = 0; const later = () => { if (!q) q = requestAnimationFrame(() => { q = 0; if (md.isConnected) draw(); }); };
  md.addEventListener('toggle', (/** @type {any} */ e) => {  // toggle does not bubble: caught on the way down
    const k = e.target.dataset?.lmsec; if (!k) return;
    LS.set('lmSecs', {...(LS.get('lmSecs', {}) || {}), [k]: e.target.open});
  }, true);
  md.addEventListener('change', later); md.addEventListener('input', later);
  new MutationObserver(later).observe(md, {childList: true, subtree: true});  // parts that load later (lock, agents)
  draw();
}
async function lmStatusSet(lid, sel) {  // the status at once, without a note (the status dialog adds one, with the history)
  const v = sel.value;
  try { await lstStatusOpt(lid, v); } catch { sel.value = listById(lid)?.status || ''; return; }  // 2.559.0 (#4660): at once, no load()
  toast(v ? tr('Status: {0}', statusLabel(v)) : tr('Status cleared'));
}
// 2.361.2 (#2923): moving a project into an organisation: a member gets it back only through its admins (they ask for it)
function lwsBack(org, from) {
  if (!org || +org === +(from || 0) || (S.me?.workspaces || []).find(w => w.id === +org)?.role === 'admin') return '';
  return ' ' + tr('Back into your private workspace only after an admin of the organisation releases it (you ask for it).');
}
// 2.364.0 D (#3033): "New project" in short: "For whom?" (the workspace) on top, then the name; the rest under "More options"
// (closed; open when the dialog comes with a project type or a use). The fields stay in the form and are sent as before.
function lnew_short(md, o) {
  const h = $('h3', md), box = h?.parentElement, ws = $('.lwsrow', md), wh = $('#l-wshint', md), grid = $('#l-emogrid', md), foot = $('.foot', md);
  if (!box || !grid || !foot || foot.parentElement !== box) return;
  if (ws) { const lab = $('label[for="l-ws"]', ws); if (lab) lab.textContent = tr('For whom?'); h.after(ws); if (wh) ws.after(wh); }
  const det = document.createElement('details');
  det.className = 'lnmore'; det.innerHTML = `<summary>${esc(tr('More options'))}</summary>`; det.open = !!(o.ptype || o.family);
  for (let n = grid.nextElementSibling; n && n !== foot;) { const nx = n.nextElementSibling; det.append(n); n = nx; }
  foot.before(det);
}
// 2.401.0 (#2924): the workspace field of an existing project runs the server's dry run first (POST …/move-space {dry: 1}):
// what the move ends (Undo brings it back), takes along or leaves in the old workspace -- or what refuses it -- shows in the
// move dialog before anything moves (true = move). Nothing to say = moved at once, as before.
async function lwsDry(id, from, to) {
  if ((from || null) === (to || null)) return true;
  const check = async org => {
    try { return await rawFetch('POST', `/api/lists/${id}/move-space`, {to: smv_ws(org), dry: 1}); }
    catch (x) { return {block: x.message || tr('The check failed. Please try again.'), out_request: x?.data?.out_request}; }
  };
  const r = await check(to);
  if (!r.block && !(r.notes || []).length) return true;
  return !!await smv_open({what: qn(lname(listById(id)) || ''), from, only: [smv_ws(to)], check, run: async () => true});
}
function listModal(id, folder = '', o = {}) {
  /** @type {any} */
  const l = id ? listById(id) : {name: '', color: '', folder, view: (typeof folderEff === 'function' && folderEff(folder).view) || 'list', kind: o.kind || 'list', tickets: 0};  // 2.757.0 (#4501): the folder's view
  const own = isOwner(l), dis = own ? '' : 'disabled';
  // 2.40.0 (#1431): a list admin changes name, icon and colour too (the rest stays the owner's)
  const ladm = !!id && !own && l.role === 'admin' && !l.is_inbox, adis = own || ladm ? '' : 'disabled';
  const m0 = l.name.match(EMO_RE);
  let emo = m0 ? m0[1] : '';
  const base = l.is_inbox && inboxDef(l.name) ? tr('Basket') : m0 ? l.name.slice(m0[0].length) : l.name;  // inbox keeps its stored name unless renamed
  // 1.5.1: an existing list saves itself like the settings (every change at once, "Saved · Undo", one history step each);
  // a new list keeps Cancel / Create
  // 2.352.0 C (#2751): the basics stay on top (name, folder, workspace, visibility, client, view, status, sharing); the rest
  // folds into parts (lmSec), closed at first with a short state in the folded line; "Progress and status" is gone (#2752)
  const fown = id ? (() => { try { return JSON.parse(l.folder_own || '[]'); } catch { return []; } })() : [];
  /** @type {any} */
  const md = modal(`${id ? `<div class="lhdr"><h3>${tr('Edit project')}</h3><span class="ssaved" role="status" aria-live="polite"></span><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>` : `<h3>${tr('New project')}</h3>`}
    <div class="row"><label for="l-name">${tr('Name')}</label><button class="emobtn" id="l-emo" title="${tr('Select icon')}" ${adis}>${id && l.icon ? licon(l, 'licon m') : sbiEmo(emo) || ic('list')}</button><input id="l-name" value="${esc(base)}" ${adis}></div>
    <div class="emogrid hidden" id="l-emogrid"><button data-emo="" class="none" title="${tr('No icon')}">${ic('ban', 's')}</button>${sbiGrid().map(e => `<button data-emo="${e}" class="${e === emo && !l.icon ? 'on' : ''}">${sbiEmo(e)}</button>`).join('')}<input id="l-emocustom" placeholder="${tr('custom')}" maxlength="8">
      ${id && (own || ladm) ? `<div class="lipickw"><span class="muted lipl">${tr('Or a picture')}</span>${liconPickHtml(l)}</div>` : ''}</div>
    ${id ? '' : `<input type="hidden" id="l-kind" value="${(l.kind || 'list') === 'project' ? 'project' : 'list'}">`}
    <div class="row"><label for="l-folder">${tr('Folder')}</label><input id="l-folder" value="${esc(fDisp(l.folder))}" list="l-folders" placeholder="${esc(tr('optional · Folder / Subfolder'))}" ${l.mirrored ? `disabled title="${esc(mirroredMsg(l))}"` : ''}><datalist id="l-folders">${folderNames().map(f => `<option value="${esc(fDisp(f))}">`).join('')}</datalist></div>
    <div class="lfolderhint" id="l-fhint" role="note" ${folderHintHtml(l, id, folder) ? '' : 'hidden'}>${folderHintHtml(l, id, folder)}</div>
    ${wsOn() && !l.is_inbox && (own || id) ? `<div class="row lwsrow"><label for="l-ws">${tr('Workspace')}</label>${own ? wsSelectHtml('l-ws', id ? l.org_id : (o.org_id !== undefined ? o.org_id : wsDefaultOrg(folder, true))) : `<span class="muted">${esc(wsLabel(l.org_id))}</span>`}</div>
    <div class="shint lhint" id="l-wshint">${(id ? l.org_id : (o.org_id !== undefined ? o.org_id : wsDefaultOrg(folder, true))) ? tr('Shared only inside the organisation; its agents may join. Shopping lists and Home & life are private only.') + lwsBack(id ? l.org_id : (o.org_id !== undefined ? o.org_id : wsDefaultOrg(folder, true)), id ? l.org_id : null) : tr('Private: share it with anyone you may see; the organisation’s agents cannot join. Switching to an organisation needs every person in it to be a member.')}</div>
    ${id && (S.wsMismatches || {})[String(id)] ? `<div class="shint keep lhint">${ic('alert', 's')} ${esc(tr('An agent of another workspace is in this project (from before the workspaces): take it out in the Share dialog, or keep it on purpose.'))}</div>` : ''}` : ''}
    ${id ? ovRowHtml(l) : ''}
    ${listDlgTeamHtml(l, id, 'client')}
    <div class="row"><label for="l-view">${tr('View')}</label><select id="l-view"><option value="list">${tr('List')}</option>${feat('kanban') ? `<option value="kanban" ${l.view === 'kanban' ? 'selected' : ''}>${tr('Kanban')}</option>` : ''}${feat('timeline') ? `<option value="timeline" ${l.view === 'timeline' ? 'selected' : ''}>${tr('Timeline')}</option>` : ''}</select></div>
    ${id && !l.is_inbox && statusOn() ? `<div class="row lstrow"><label for="l-status">${tr('Status')}</label><select id="l-status" ${canEditList(id) ? '' : 'disabled'}><option value="">${tr('No status')}</option>${STATUSES.map(([k, n]) => `<option value="${k}" ${l.status === k ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select><button type="button" class="btn sm" data-act="status" data-id="${id}">${ic('pulse', 's')} ${tr('History')}</button></div>` : ''}
    ${id && shareOk(l) ? `<div class="row shsum"><label>${tr(collab() ? N_('Sharing') : N_('Owner'))}</label><span class="muted" id="l-shsum">${esc(shareSummary(l))}</span><button class="btn sm" data-m="share-open">${ic('users', 's')} ${tr(collab() ? N_('Share…') : N_('Ownership…'))}</button></div>` : ''}
    ${lmSec('time', tr('Time and billing'), `
    ${id && timeOn() && !l.is_inbox ? `<div class="row ltimerow"><label for="l-time">${tr('Time tracking')}</label><label class="chkl"><input type="checkbox" id="l-time" ${l.time_tracking ? 'checked' : ''} ${dis}> ${tr('Track time in this project')}</label></div>
    <div class="shint lhint">${tr('Timer and time entries on the tasks of this project, for everyone in it. Time tracked already stays in the review when it is switched off.')}</div>` : ''}
    ${timeOn() ? `<div class="ltimex" ${id && l.time_tracking ? '' : 'hidden'}>` : ''}
    ${id && timeOn() && (own || l.day_hours) ? `<div class="row"><label for="l-dayh">${tr('Hours per day')}</label><input id="l-dayh" inputmode="decimal" value="${l.day_hours != null ? esc(String(l.day_hours).replace('.', numDec())) : ''}" placeholder="${esc(fmtNum(S.timeDayH || 8))}" style="max-width:5rem" ${dis}></div>
      <div class="shint">${trh('Hours per day or shift, for the time sum in the header. Empty = {0} h.', fmtNum(S.timeDayH || 8))}</div>` : ''}
    ${timeOn() && (own || l.rate) ? `<div class="row"><label for="l-rate">${tr('Hourly rate')}</label><input id="l-rate" inputmode="decimal" value="${l.rate != null ? esc(String(l.rate).replace('.', numDec())) : ''}" placeholder="${tr('optional')}" style="max-width:6.875rem" ${dis}><span class="muted">${esc(S.settings.time_currency || '')} · ${tr('time reports')}</span></div>` : ''}
    ${timeOn() ? '</div>' : ''}`, fown)}
    ${lmSec('show', tr('Display and behaviour'), `
    <div class="row"><label>${tr('Colour')}</label><div class="colors" id="l-col" role="group" aria-label="${esc(tr('Colour'))}">${lp_dlgBtns(id || l.color ? lp_col(l) : lp_folderColor(folder), adis) /* 2.53.0 (#1426): the 12 tones; a new list: its folder's */}</div></div>
    ${''/* 2.396.0 (#3385): the row "Used for" is gone; a list keeps its stored family (shopping mode, aisles); a shopping list offers it in the list itself (render.js hint shop) */}
    ${id ? `<div class="row lmtrow"><label>${tr('My tasks')}</label><label class="chkl"><input type="checkbox" id="l-inmine" ${mtShown(id) ? 'checked' : ''}> ${tr('Show in My tasks')}</label><span class="muted">${tr('only for you')}</span></div>` : ''}
    ${id && progressOn() ? `<div class="row"><label>${tr('Progress')}</label><label class="chkl"><input type="checkbox" id="l-showprog" ${progHidden(id) ? '' : 'checked'}> ${tr('Show the progress bar')}</label><span class="muted">${tr('only for you')}</span></div>` : ''}
    ${own ? `<div class="row ldabrow"><label>${tr('Completed')}</label><span class="lchks"><label class="chkl"><input type="checkbox" id="l-dab" ${l.checklist ? 'checked' : ''}> ${tr('Show completed at the bottom')}</label>${id && !l.is_inbox ? `<label class="chkl ldsxrow"><input type="checkbox" id="l-dsx" ${dsxOn(l) ? 'checked' : ''} ${dsxFixedOff(l) ? 'disabled' : ''}> ${tr('Keep completed in their section')}</label>` : ''}</span></div>
    <div class="shint lhint" id="l-dsxhint">${ic('donedown', 's')} ${tr('What you tick off stays visible at the bottom and comes back with one tap, for example in shopping lists.')}${id && !l.is_inbox ? ' ' + tr('Completed tasks stay crossed out at their place, for everyone in the project. Not with “Show completed at the bottom” or for shopping lists.') : ''}</div>` : ''}
    ${id ? tp_rowHtml(l) : ''}
    ${id ? rvw_rowHtml(l) : ''}${''/* 2.60.0 C (#1512): review step (review.js) */}
    ${id ? o3c_rowHtml(l) : ''}${''/* 2.83.0 C (#1427): header strip (listhead.js) */}
    ${id && !l.is_inbox && collab() ? `<h4>${tr('Project tags')}</h4><div class="shint lhint">${tr('Tags of this project: everyone in it sees them, with their colour. Personal tags (with the person icon) stay yours.')}${l.shared ? '' : ' ' + tr('They become visible to everyone as soon as you share the project.')}</div><div class="members" id="l-ltags">${ltagsBoxHtml(l)}</div>` : ''}`, fown)}
    ${lmSec('remind', tr('Reminders'), `
    <div class="row lnagrow"><label for="l-nag">${tr('Repeat reminders')}</label><select id="l-nag" ${dis}><option value="">${tr('Off|nag')}</option>${NAG_OPTS.slice(1).map(([v, n]) => `<option value="${v}" ${(l.nag || '') === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
    <div class="shint lhint">${tr('The reminder repeats until done. Quiet hours: Settings > Notifications.')}</div>
    ${id && ['owner', 'admin'].includes(l.role || 'owner') && !l.family && !l.life ? staleRowHtml(l) : ''}
    ${id && !l.is_inbox && collab() && l.shared ? `<div class="row"><label for="l-bell">${ic(BELL_ICON[l.bell || 'default'], 's')} ${tr('Notifications')}</label><select id="l-bell" data-native data-lmdef="default">${BELLS.map(([m, n]) => `<option value="${m}" ${(l.bell || 'default') === m ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
    <div class="shint lhint" id="l-bellhint">${tr(BELLS.find(b => b[0] === (l.bell || 'default'))[2])} · ${tr('only for you')}</div>${isOwner(l) ? '' : ntfMemberHint(l)}
    <div class="row" id="l-bellc" ${l.bell === 'custom' ? '' : 'hidden'}><span class="spacer"></span><button type="button" class="btn sm" data-m="bell-custom">${ic('sliders', 's')} ${tr('Select events…')}</button></div>` : ''}`, fown)}
    ${lmSec('agents', tr('Agents'), `
    ${id && shareOk(l) && collab() && agentsOn() && listAgents(l).length ? `<div class="row lagrow"><label>${tr('Agents')}</label><span class="muted lmsum">${esc([listAgents(l).map(a => a.name || '').filter(Boolean).join(', '), listenLabel(l)].filter(Boolean).join(' · '))}</span><button class="btn sm" data-m="share-open">${ic('users', 's')} ${tr('Share…')}</button></div>` : ''}
    ${id && !l.is_inbox && pbOn(l) ? (l.e2e && typeof le2u_pbHtml === 'function' ? le2u_pbHtml() : pbAreaHtml('list')) : ''}`, fown)}
    ${lmSec('forms', tr('Forms and software'), `
    ${listDlgTeamHtml(l, id, 'forms')}
    ${id && own && swOffer(l) ? `<div class="row lswoffer"><label>${tr('Software')}</label><button type="button" class="linkbtn" data-m="sw-setup">${ic('code', 's')} ${tr('Set up as a software project…')}</button></div>` : ''}
    ${id ? whiBoxHtml(l) /* 2.115.0 A (#2061): inbound webhooks (hookin.js) */ : ''}
    ${id ? rul_boxHtml(l) /* 2.71.0 A (#1457): rules of the list (rules.js) */ : ''}`, fown)}
    ${lmSec('sec', tr('Security|project'), `${id && typeof le2u_listRowHtml === 'function' ? le2u_listRowHtml(l) : ''}${''/* 2.64.1 (#1817): the lock of the list (liste2eui.js) */}`, fown)}
    ${l.is_inbox ? '' : lmSec('proj', tr('Project features'), `
    ${id ? '' : `<div class="lptype"><div class="ptlab">${tr('Start from')}</div><div class="ptcards" role="radiogroup" aria-label="${esc(tr('Start from'))}">${ptypeUi().map(([k, n, i, dsc]) => `<button type="button" class="ptcard ${k === (o.ptype || '') ? 'on' : ''}" role="radio" aria-checked="${k === (o.ptype || '')}" data-pt="${k}">${ic(i, 's')}<b>${tr(n)}</b><small class="muted">${tr(dsc)}</small></button>`).join('')}${tplOf('list').map(tp => `<button type="button" class="ptcard" role="radio" aria-checked="false" data-pt="tpl:${tp.id}">${ic('copy', 's')}<b>${esc(tp.name)}</b><small class="muted" data-ptd="${tp.id}">${tr('Your template')}</small></button>`).join('')}</div>
      <div class="row ptsecs" ${PTYPE_SECS[o.ptype || ''] ? '' : 'hidden'}><label class="chkl"><input type="checkbox" id="l-ptsecs"> ${tr('With the default sections')}</label><span class="muted" id="l-ptsecsl">${esc(ptSecsLine(o.ptype || ''))}</span></div>
      <div class="row ptbug" ${o.ptype === 'software' ? '' : 'hidden'}><label class="chkl"><input type="checkbox" id="l-ptbug"> ${tr('With a bug inbox')}</label><span class="muted">${tr('A second project; bugs with a release move here by themselves')}</span></div>${''/* 2.473.0 (#3378) */}
      <div class="ptdates" hidden><div class="row"><label>${tr('Project start')}</label>${dateIn('l-pstart', today(), {label: tr('Project start'), clear: false})}</div><div class="row"><label>${tr('End (optional)')}</label>${dateIn('l-pend', '', {label: tr('End (optional)'), empty: tr('none')})}<span class="muted">${tr('stretches or squeezes the dates')}</span></div></div></div>`}
    ${id ? ptypeRowHtml(l) : ''}
    ${own ? `<div class="row ltkrow" ${swArea(l) || l.tickets ? '' : 'hidden'}><label>${tr('Ticket types')}</label><label class="chkl"><input type="checkbox" id="l-tickets" ${l.tickets ? 'checked' : ''}> ${tr('Bug, feature, task')}</label>${id ? `<button class="btn sm" data-m="tt-tpl" type="button">${tr('Types and templates…')}</button>` : ''}</div>
    <div class="shint lhint ltkhint" ${swArea(l) || l.tickets ? '' : 'hidden'}>${tr('Tasks get a type with an icon, a filter and quick add !bug / !feature; new bugs and features start with a note template.')}</div>` : ''}
    ${tk_listRow(l)}${''/* 2.390.0 (#3353): ticket key (git.js) */}
    ${id ? spr_dlgRow(l) : ''}${''/* 2.60.0 (#343) */}
    ${spt_listRow(l, own)}${''/* 2.60.0 (#1511) */}
    ${ow_listRow(l, own)}${''/* 2.392.0 C (#3370) */}
    ${id && own && depsOn() ? `<div class="row"><label>${tr('Dependencies')}</label><label class="chkl"><input type="checkbox" id="l-depshift" ${l.dep_shift ? 'checked' : ''}> ${tr('Move dependent tasks along')}</label></div>
    <div class="shint lhint">${tr('Postponing a task moves the tasks it blocks by the same number of days. One undo reverses the whole chain.')}</div>` : ''}
    ${id && canManage(l) && fieldsOn() ? `<h4 title="${esc(tr('Own columns for this project: budget, stage, client, …'))}">${tr('Custom fields')}</h4><div class="members" id="l-fields">${fieldsBox(id)}</div><div class="members" id="l-ftrash" hidden></div>` : id && fieldsOf(id).length ? `<h4>${tr('Custom fields')}</h4><div class="muted mhint">${esc(fieldsOf(id).map(f => f.name).join(', '))} · ${tr('only the owner and project admins can change them')}</div>` : ''}
    ${id ? `<div class="lrepo" ${repoShown(l) ? '' : 'hidden'}><div class="shint keep lhint lrepohint" hidden>${ic('git', 's')} ${tr('Connect a repository (optional)')}</div>${repoBoxHtml(l)}</div>` : ''}`, fown, o.open === 'proj' || (!id && (o.kind === 'project' || !!o.ptype)))}
    ${id && !l.is_inbox ? lmSec('props', tr('Properties'), pz_boxHtml(l), fown) : ''}${''/* 2.412.0 (#3552): the properties of the tasks (props.js) */}
    ${lmSec('acts', tr('Actions'), `<div class="row lacts">${id && !l.is_inbox && canManage(l) ? (l.archived ? `<button class="btn" data-m="arch">${ic('undo', 's')} ${tr('Restore project from the archive')}</button><button class="btn danger" data-m="del">${ic('trash', 's')} ${l.e2e ? tr('Delete project permanently…') : tr('Delete project…') /* 2.102.0 (#1988): into the trash */}</button>` : `<button class="btn" data-m="arch" title="${tr('Hidden from your projects; undo or restore any time. Deleting permanently is only possible from the archive.')}">${ic('archive', 's')} ${tr('Archive project')}</button>`) : ''}${id && !own ? `<button class="btn danger" data-m="leave">${ic('logout', 's')} ${tr('Leave project')}</button>` : ''}${id && canEditList(id) /* 2.126.0 D (#1992 A6) */ ? `<button class="btn" data-m="tpl" title="${l.e2e ? esc(tr('Not available in encrypted projects')) : tr('Save the sections and open tasks as a template')}" ${l.e2e ? 'disabled' : ''}>${ic('copy', 's')} ${tr('Save as template')}</button>` : ''}${id && dupOk(l) ? `<button class="btn" data-m="dup" title="${tr('A copy of this project with its sections, tasks and notepads')}">${ic('copy', 's')} ${tr('Duplicate')}</button>` : ''}</div>`, fown, l.archived)}
    ${id && !o.back ? '' : `<div class="foot"><span class="spacer"></span>${id ? `<button class="btn pri" data-m="close">${tr('Done')}</button>` : `<button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Create')}</button>`}</div>`}`)  // 2.910.0 (#5442): a dialog that saves by itself closes with "Done" (was "Back");
  lmSecWire(md);
  if (id) md.classList.add('lmodal'); else { md.classList.add('lnew'); lnew_short(md, o); }  // 2.364.0 D (#3033)
  if (!id && tplOf('list').length) api('GET', '/api/templates').then(j => {  // 2.4.0 (#328): what each own template brings
    for (const tp of j.templates || []) { const el = $(`[data-ptd="${tp.id}"]`, md); if (el) el.textContent = tp.data?.rel ? tr('Dates from the project start · {0} days', tp.data.span || 0) : trn('{0} task', '{0} tasks', tp.count); }
  }).catch(() => {});
  if (id && !l.is_inbox) repoWire(md, id);  // 2.2.0 (#271)
  if (id && !l.is_inbox && collab()) ltagsWire(md, id);
  if (id && !l.is_inbox && pbOn(l) && !l.e2e) pbMount(md, {lid: id});  // 2.39.0 (#1168)
  if (id && typeof le2u_listWire === 'function') le2u_listWire(md, id);  // 2.64.1 (#1817)
  const bellHint = v => { const h = $('#l-bellhint', md); if (h) h.textContent = tr(BELLS.find(x => x[0] === v)[2]) + ' · ' + tr('only for you'); const c = $('#l-bellc', md); if (c) c.hidden = v !== 'custom'; };
  $('#l-bell', md)?.addEventListener('change', async (/** @type {any} */ e) => { e.stopPropagation(); if (e.target.value === 'custom') { bellHint('custom'); bellCustomModal(id); return; } await bellSet(id, e.target.value); bellHint(e.target.value); });
  $('#l-bell', md)?.addEventListener('bell-sync', (/** @type {any} */ e) => bellHint(e.target.value));
  $('#l-stale', md)?.addEventListener('change', (/** @type {any} */ e) => { e.stopPropagation(); staleDaysSet(id, e.target); });  // 2.34.0 (#266)
  if (id) ovWire(md, id);  // 2.46.0 (#1603): "Everyone in the organisation"
  if (id) tp_wire(md, id);  // 2.46.4 (#1751): "Tap does not open details"
  if (id) pz_wire(md, id);  // 2.412.0 (#3552): properties
  if (id) rvw_wire(md, id);  // 2.60.0 C (#1512): review step
  if (id) o3c_wire(md, id);  // 2.83.0 C (#1427): header strip
  $('#l-dsx', md)?.addEventListener('change', (/** @type {any} */ e) => { e.stopPropagation(); dsxSet(id, e.target.checked).then(() => { const x = listById(id), c = $('#l-dsx', md); if (x && c) c.checked = dsxOn(x); }); });  // 2.36.2 (#1136)
  $('[data-m="bell-custom"]', md)?.addEventListener('click', (/** @type {any} */ e) => { e.stopPropagation(); bellCustomModal(id); });
  // ---- autosave (existing lists)
  const pend = new Map();
  const formBody = () => {
    const nm = $('#l-name', md).value.trim().replace(EMO_RE, '');
    const body = own ? {name: l.is_inbox && !emo && nm === tr('Basket') ? (inboxDef(l.name) ? l.name : 'Eingang') : emo + nm, folder: fNorm($('#l-folder', md).value), view: $('#l-view', md).value, color: $('#l-col button.on', md)?.dataset.c || '', ...($('#l-depshift', md) ? {dep_shift: $('#l-depshift', md).checked} : {}), ...($('#l-rate', md) ? {rate: numBody($('#l-rate', md).value)} : {}), ...($('#l-tickets', md) ? {tickets: $('#l-tickets', md).checked} : {}),  // 2.352.0 C (#2752): no kind
      ...($('#l-nag', md) ? {nag: $('#l-nag', md).value} : {}), ...($('#l-dayh', md) ? {day_hours: numBody($('#l-dayh', md).value)} : {}), ...($('#l-time', md) ? {time_tracking: $('#l-time', md).checked} : {}), ...($('#l-dab', md) ? {checklist: $('#l-dab', md).checked} : {}),
      ...(listById(id)?.family && $('#l-ws', md)?.value ? {family: ''} : {}),  // 2.396.0 (#3385): into an organisation ends the private list kind, as the row "Used for" did
      ...($('#l-ws', md) ? {org_id: $('#l-ws', md).value ? +$('#l-ws', md).value : null} : {})}  // 2.28.0 (#935)
      : {folder: fNorm($('#l-folder', md).value), view: $('#l-view', md).value,  // members: only their own placement / view
        ...(ladm ? {name: emo + nm, color: $('#l-col button.on', md)?.dataset.c || ''} : {})};  // 2.40.0 (#1431)
    if ((own || ladm) && !nm) delete body.name;  // an empty name is never saved (leaving the field puts the saved one back)
    if ('color' in body) body.color = lp_keep(listById(id) || l, body.color);  // 2.53.0 (#1426): an old free colour stays stored
    return body;
  };
  const lsaved = e => {
    const el = $('.ssaved', md); if (!el) return;
    el.innerHTML = `${ic('check', 's')}<span>${tr('Saved')}</span>${e ? `<button type="button" class="linkbtn" data-m="l-undo">${tr('Undo')}</button>` : ''}`;
    el.classList.add('on'); el._e = e;
    clearTimeout(el._t); el._t = setTimeout(() => { el.classList.remove('on'); el._e = null; }, 6000);
  };
  let ptKeys = false, ptPend = false, ptRun = Promise.resolve();  // 2.18.0 review (R1): project type select, see ptCommit
  // 2.270.0 A (#3019): the list as this dialog showed it (opened / last saved / synced): the autosave sends only what was
  // changed here, with these values as _prev (a value another device set meanwhile is not set back); lfail = last save failed
  let lbase = {...l}, lfail = false;
  let wsHold = false;  // 2.401.0 (#2924): a workspace change waits for its dry run / the move dialog (no other save takes it along)
  const lsync = (force = false) => {  // after an undo / redo or a failed save: the dialog shows what is saved
    if (!md.isConnected) return;
    const x = listById(id); if (!x) return;
    const m1 = x.name.match(EMO_RE);
    if (force || document.activeElement !== $('#l-name', md)) { emo = m1 ? m1[1] : ''; $('#l-name', md).value = x.is_inbox && inboxDef(x.name) ? tr('Basket') : m1 ? x.name.slice(m1[0].length) : x.name; $('#l-emo', md).innerHTML = sbiEmo(emo) || ic('list'); }
    if (document.activeElement !== $('#l-folder', md)) $('#l-folder', md).value = fDisp(x.folder || '');
    $('#l-view', md).value = listView(x);
    if ($('#l-status', md)) $('#l-status', md).value = x.status || '';  // 2.352.0 C (#2751)
    $$('#l-col button', md).forEach(b => { b.classList.toggle('on', lp_col(x) === b.dataset.c); b.setAttribute('aria-pressed', String(lp_col(x) === b.dataset.c)); });  // 2.53.0 (#1426)
    if ($('#l-depshift', md)) $('#l-depshift', md).checked = !!x.dep_shift;
    if ($('#l-tickets', md)) $('#l-tickets', md).checked = !!x.tickets;
    if ($('#l-ptype', md) && !ptPend) { $('#l-ptype', md).value = x.ptype || ''; $('#l-pthint', md).textContent = ptypeHint(x.ptype || ''); }
    if ($('.lrepo', md)) $('.lrepo', md).hidden = !repoShown(x);
    $$('.ltkrow, .ltkhint', md).forEach(r => { r.hidden = !(swArea(x) || x.tickets); });  // 2.22.0 (#746)
    if ($('#l-tickets', md)) $('#l-tickets', md).checked = !!x.tickets;
    if ($('#l-rate', md) && document.activeElement !== $('#l-rate', md)) $('#l-rate', md).value = x.rate != null ? String(x.rate).replace('.', numDec()) : '';
    if ($('#l-time', md)) { $('#l-time', md).checked = !!x.time_tracking; if ($('.ltimex', md)) $('.ltimex', md).hidden = !x.time_tracking; }  // 2.41.0 (#1471)
    if ($('#l-dayh', md) && document.activeElement !== $('#l-dayh', md)) $('#l-dayh', md).value = x.day_hours != null ? String(x.day_hours).replace('.', numDec()) : '';
    if ($('#l-nag', md)) $('#l-nag', md).value = x.nag || '';
    if ($('#l-dab', md)) $('#l-dab', md).checked = !!x.checklist;
    if ($('#l-dsx', md)) { $('#l-dsx', md).checked = dsxOn(x); $('#l-dsx', md).disabled = dsxFixedOff(x); }  // 2.36.2 (#1136)
    tp_sync(md, x);  // 2.46.4 (#1751)
    pz_sync(md, x);  // 2.412.0 (#3552)
    const keep = force ? [] : [['l-name', 'name'], ['l-folder', 'folder'], ['l-rate', 'rate'], ['l-dayh', 'day_hours']].filter(([e]) => document.activeElement === $('#' + e, md)).map(([, k]) => k);
    lbase = {...x, ...Object.fromEntries(keep.map(k => [k, lbase[k]]))};  // 2.270.0 A (#3019): a field being typed keeps its base
  };
  let saving = Promise.resolve(), lbusy = 0;
  const autosave = () => {
    if (!id) return saving;
    lbusy++;
    saving = saving.then(async () => {
      for (const t of pend.values()) clearTimeout(t);
      pend.clear();
      const cur = listById(id); if (!cur) return;
      const body = formBody(), diff = {}, prev = {};
      for (const k in body) if (lv(k, lbase[k]) !== lv(k, body[k]) && lv(k, cur[k]) !== lv(k, body[k])) { diff[k] = body[k]; prev[k] = lbase[k] ?? null; }  // 2.270.0 A (#3019)
      if (wsHold) { delete diff.org_id; delete prev.org_id; }  // 2.401.0 (#2924): e.g. the name's focusout while the move dialog opens
      if (!Object.keys(diff).length) { lfail = false; return; }
      if ('folder' in diff && own) {  // 2.39.1 (#1188): a folder with other workspace / agent defaults asks first
        const fa = await lmFolderAsk({[id]: diff.folder}); if (fa === null) { lsync(true); return; }
        if (fa.length) diff.folder_adopt = true;
      }
      if (diff.folder && !folderNames().includes(diff.folder)) await api('PATCH', '/api/settings', {set_delta: {folders: {add: [diff.folder]}}, _auto: 1}).catch(() => {});  // 2.269.0 B (#3014): only the new folder; 2.1013.0 (#5773): a part of the list edit, no undo step
      /** @type {any} */
      let cfl = null;
      // 2.527.0 (#4304 A5): kept until the server has it (the session ends during the save: sent after the sign-in, core.js fdWrite)
      const fk = fdWrite('PATCH', '/api/lists/' + id, {...diff, _prev: prev}, {slot: 'list.' + id, send: false});
      const e = await listPatch(id, {...diff, _prev: prev}, null, {post: lsync, conflicts: c => { cfl = c; }});
      if (e === false) { lfail = true; return; }
      fdDrop('fdw', fk);  // 2.359.2 B (#3049): the form keeps what was typed (the next save sends it again)
      lfail = false;
      for (const k in diff) lbase[k] = diff[k];
      if (cfl) { for (const c of cfl) lbase[c.field] = c.server; lsync(true); }  // the form shows what stayed
      lsaved(e);
    }).catch(() => { lfail = true; toast(tr('Could not save')); }).then(() => { lbusy--; if (!pend.size) fl_nameEnd(id); });  // 2.270.0 A (#3019): not swallowed  // 2.46.2 (#1659): saved (or not): the live name ends
    return saving;
  };
  const later = el => { clearTimeout(pend.get(el.id)); pend.set(el.id, setTimeout(autosave, 900)); };
  // 2.359.2 B (#3049): the save failed: the dialog stays unless the person discards what is not saved
  const lDiscard = async () => {
    toast(tr('Could not save'));
    if (md._asking) return false;
    md._asking = true;
    const ok = await askConfirm(tr('Discard changes?'), tr('Your changes in this dialog are not saved yet.'), {ok: tr('Discard'), danger: true, cancel: tr('Keep editing')});
    md._asking = false; if (ok) fdDrop('fdw', 'list.' + id); return ok;  // 2.527.0 (#4304): discarded = not sent later either
  };
  if (id) {
    md.addEventListener('input', (/** @type {any} */ e) => { if (['l-name', 'l-folder', 'l-rate', 'l-dayh'].includes(e.target.id)) later(e.target); if (e.target.id === 'l-name') fl_nameLive(id, formBody().name); });  // 2.46.2 (#1659)
    md.addEventListener('focusout', (/** @type {any} */ e) => { if (['l-name', 'l-folder', 'l-rate', 'l-dayh'].includes(e.target.id)) { const empty = e.target.id === 'l-name' && !e.target.value.trim().replace(EMO_RE, ''); autosave().then(() => { if (empty) lsync(true); }); } });
    // 2.422.0 A (#3468): the page goes away within the 0.9 s of typing: the fields waiting go out with keepalive (core.js
    // keepSend; a list has no queue, so closing / reloading asks while one waits or a save runs). A folder is not sent then
    // (a new one / one with other defaults asks first in autosave); the question keeps it. 2.440.0 (#3654): + after a failed save (the text is only in the form)
    const leave = () => {
      if (!pend.size) return;
      const ks = [...pend.keys()].map(e => ({'l-name': 'name', 'l-rate': 'rate', 'l-dayh': 'day_hours'})[e]).filter(Boolean);
      const cur = listById(id); if (!cur || !ks.length) return;  // the timers stay: a page kept for "back" saves the rest then
      const body = formBody(), diff = {}, prev = {};
      for (const k of ks) if (k in body && lv(k, lbase[k]) !== lv(k, body[k]) && lv(k, cur[k]) !== lv(k, body[k])) { diff[k] = body[k]; prev[k] = lbase[k] ?? null; }
      if (Object.keys(diff).length && fdWrite('PATCH', '/api/lists/' + id, {...diff, _prev: prev}, {slot: 'list.' + id})) for (const k in diff) lbase[k] = diff[k];  // 2.527.0 (#4304 A6): + kept for the next start
    };
    const fgOff = typeof fgPending === 'function' ? fgPending(leave, () => pend.size > 0 || lbusy > 0 || lfail) : () => {};
    onRemove(md, () => { fgOff(); if (pend.size) autosave(); else fl_nameEnd(id); });
    // 2.359.2 B (#3049): Esc / the backdrop like "Close" when something is not saved yet (else at once, as before)
    md._close = async () => { if (pend.size || lfail || lbusy) { await autosave(); if (lfail && !await lDiscard()) return; } md.remove(); };
  }
  md.addEventListener('change', (/** @type {any} */ e) => {
    if (id && e.target.id === 'l-status') { lmStatusSet(id, e.target); return; }  // 2.352.0 C (#2751): the status instead of the switch "Progress and status"
    if (id && e.target.id === 'l-ptype') {
      // 2.18.0 review (R1): arrow keys on a closed select fire "change" for every value passed; while the keyboard
      // walks the options only the hint follows, the type is saved once on Enter / leaving the field
      if (ptKeys) { ptPend = true; $('#l-pthint', md).textContent = ptypeHint(e.target.value); return; }
      ptypeChange(e.target.value); return;
    }
    if (e.target.id === 'l-ws') {  // 2.28.0 (#935): the hint follows
      const org = !!e.target.value;
      const h = $('#l-wshint', md); if (h) h.textContent = org ? tr('Shared only inside the organisation; its agents may join. Shopping lists and Home & life are private only.') + lwsBack(+e.target.value, id ? listById(id)?.org_id : null) : tr('Private: share it with anyone you may see; the organisation’s agents cannot join. Switching to an organisation needs every person in it to be a member.');
      if (id) {  // 2.401.0 (#2924): the server's dry run first; cancelled = the field goes back
        const sel = e.target, to = sel.value ? +sel.value : null, from = listById(id)?.org_id || null;
        wsHold = true;
        lwsDry(id, from, to).finally(() => { wsHold = false; }).then(go => {
          if (go) { autosave(); return; }
          if (!sel.isConnected) return;
          sel.value = from ? String(from) : ''; sel.dispatchEvent(new Event('change', {bubbles: true}));
        });
      }
      return;
    }
    if (id && ['l-view', 'l-depshift', 'l-tickets', 'l-nag', 'l-dab', 'l-time'].includes(e.target.id)) { if (e.target.id === 'l-time' && $('.ltimex', md)) $('.ltimex', md).hidden = !e.target.checked; autosave(); return; }  // 2.41.0 (#1471): l-time
    if (id && e.target.id === 'l-showprog') { setProgHidden(id, !e.target.checked).then(() => lsaved(null)); return; }
    if (id && e.target.id === 'l-inmine') { mtSet(id, e.target.checked, {post: () => { const x = $('#l-inmine', md); if (x) x.checked = mtShown(id); }}).then(() => lsaved(null)); return; }  // 2.41.0 (#1365)
  });
  // 2.18.0 (#408): the project type of an existing list: saved at once (one history step), then the dialog shows what
  // the server switched on, offers the type's missing sections and, for Software, the repository area
  const ptCommit = () => { const sel = $('#l-ptype', md); ptKeys = false; if (!ptPend || !sel) return; ptPend = false; ptypeChange(sel.value); };
  md.addEventListener('keydown', (/** @type {any} */ e) => {
    if (e.target.id !== 'l-ptype') return;
    if (e.key === 'Enter') { if (ptPend) { e.preventDefault(); ptCommit(); } return; }
    // walking a CLOSED select (Alt+arrows / Space open the option list: its choice comes as one change)
    ptKeys = !e.altKey && (/^(Arrow(Up|Down|Left|Right)|Home|End|Page(Up|Down))$/.test(e.key) || (e.key.length === 1 && e.key !== ' '));
  });
  md.addEventListener('pointerdown', (/** @type {any} */ e) => { if (e.target.id === 'l-ptype') ptKeys = false; });
  md.addEventListener('focusout', (/** @type {any} */ e) => { if (e.target.id === 'l-ptype') ptCommit(); });
  if (id) onRemove(md, () => { const sel = $('#l-ptype', md); if (ptPend && sel) { ptPend = false; setListPtype(id, sel.value); } });  // closed while walking the options: still saved once
  // changes run one after the other; a change superseded meanwhile is skipped, so the offer always matches the type shown
  const ptypeChange = v => (ptRun = ptRun.then(() => { const sel = $('#l-ptype', md); if (md.isConnected && sel && sel.value === v) return ptypeChange1(v); }).catch(() => {}));
  const ptypeChange1 = async v => {
    await autosave();
    if (!await pz_askType(listById(id) || l, v)) { lsync(); return; }  // 2.412.0 (#3552): first what the new type hides
    const sel = $('#l-ptype', md), r = await setListPtype(id, v, {post: () => lsync()});
    if (!md.isConnected) return;
    if (!r) { lsync(); return; }
    lsaved(r.e); lsync(); drawFields();
    const off = $('#l-ptoffer', md);
    if (off) ptypeOfferDraw(off, id, v, r.missing?.sections || []);
    if (v === 'software' && $('.lrepo', md)) {
      $('.lrepohint', md).hidden = false;
      $('.lrepo', md).scrollIntoView?.({block: 'nearest'});
    }
    sel?.focus();
  };
  const drawFields = () => { const box = $('#l-fields', md); if (box) { box.innerHTML = fieldsBox(id); ofs_mount(box, id, drawFields); } ftrDraw($('#l-ftrash', md), id); };  // 2.609.0 (#3373): + the organisation's fields; 2.550.0 (#4528): + the deleted fields
  if (id && $('#l-fields', md)) ofs_mount($('#l-fields', md), id, drawFields);
  ftrDraw($('#l-ftrash', md), id);
  if (id) rul_mount(md, l);  // 2.71.0 A (#1457)
  if (id) whiMount(md, l);  // 2.115.0 A (#2061)
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'field-add') { fieldModal(id, null, drawFields); return; }  // 2.39.1 (#1217): no project needed any more
    if (b.dataset.fedit) { fieldModal(id, fieldById(+b.dataset.fedit), drawFields); return; }
    // 2.554.0 (#4658): a new field still on its way (stand-in id below 0): pin / order wait for the real ids, a stand-in never goes to the server
    if ((b.dataset.fpin || b.dataset.fup) && typeof fdReal === 'function' && fieldsOf(id).some(f => f.id < 0)) {
      for (const k of ['fpin', 'fup']) if (+b.dataset[k] < 0) { const r = await fdReal(+b.dataset[k]); if (!r) return; b.dataset[k] = r; }
      await Promise.all(fieldsOf(id).filter(f => f.id < 0).map(f => fdReal(f.id)));
    }
    if (b.dataset.ftrest) { if (await ftrRestore(+b.dataset.ftrest)) { drawFields(); toast(tr('Field restored')); } return; }  // 2.550.0 (#4528)
    if (b.dataset.fpin) {
      const f = fieldById(+b.dataset.fpin);
      // 2.41.2 (#1501): pinned / order at once (optimistic), no GET /api/state afterwards
      const pin = !f.pinned;  // before the local change (the request reads it later)
      try { await optWrite(optSet(() => fieldById(f.id), {pinned: pin}), () => api('PATCH', '/api/fields/' + f.id, {pinned: pin}), () => { render(); drawFields(); }); } catch { /* shown, put back */ }
      return;
    }
    if (b.dataset.fup) {
      const fs = fieldsOf(id), i = fs.findIndex(f => f.id === +b.dataset.fup); if (i < 1) return;
      const a = fs[i], z = fs[i - 1], sa = z.sort, sz = a.sort === z.sort ? a.sort + 1 : a.sort;
      const put = () => { const x = optSet(() => fieldById(a.id), {sort: sa})(), y = optSet(() => fieldById(z.id), {sort: sz})(); return () => { x?.(); y?.(); }; };
      try { await optWrite(put, async () => { await api('PATCH', '/api/fields/' + a.id, {sort: sa}); await api('PATCH', '/api/fields/' + z.id, {sort: sz}); }, () => { render(); drawFields(); }); } catch { load().then(() => { render(); drawFields(); }).catch(() => {}); }
      return;
    }
    if (b.dataset.m === 'share-open') { await autosave(); if (o.back) { md.remove(); return; } modalSub(md, () => shareModal(id, {back: true})); return; }  // 2.6.0 (K12); 2.46.0 (#1604): back, no stack
    if (b.dataset.m === 'tt-tpl') { await autosave(); ticketTplModal(id); return; }
    if (b.dataset.pt !== undefined) {  // 2.4.0 (#243 / #328): what the new project starts from
      md._ptUser = 1;  // 2.411.0 (#3516): chosen by hand, a folder change keeps it
      $$('.ptcard', md).forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); });
      const tp = b.dataset.pt.startsWith('tpl:');
      $('.ptdates', md).hidden = !tp;
      $('.ptsecs', md).hidden = !PTYPE_SECS[b.dataset.pt]; $('#l-ptsecsl', md).textContent = ptSecsLine(b.dataset.pt);  // 2.27.0 (#972)
      $('.ptbug', md).hidden = b.dataset.pt !== 'software';  // 2.473.0 (#3378)
      // 2.387.0 (#1957): a social media plan works through its sections (the approval step sits on one): ticked for it
      if (b.dataset.pt === 'social' && $('#l-ptsecs', md)) $('#l-ptsecs', md).checked = true;
      const pt = ptypeUi('shoot').find(x => x[0] === b.dataset.pt);
      // 2.22.0 (#749): every new list opens as a list (the board is one tap away)
      if ($('#l-tickets', md)) { $('#l-tickets', md).checked = b.dataset.pt === 'software'; $('#l-tickets', md).closest('.row').hidden = !!b.dataset.pt; }
      if (!$('#l-name', md).value.trim() && (tp || (pt && pt[0]))) $('#l-name', md).value = tp ? $('b', b).textContent : tr(pt[1]);
      return;
    }
    if (b.dataset.m === 'leave') {
      if (!await askConfirm(tr('Leave the project “{0}”?', listName(l.name)), tr('You will no longer see its tasks. The owner can share it with you again.'), {ok: tr('Leave project'), danger: true})) return;
      try { await api('DELETE', `/api/lists/${id}/members/${S.me.id}`); } catch { return; }
      md.remove(); await load(); go(START_KEY); return;
    }
    if (b.dataset.m === 'l-undo') { const el = $('.ssaved', md); if (el?._e && HIST.undo[HIST.undo.length - 1] === el._e) { el.classList.remove('on'); histStep('undo', 1, [el._e]); } return; }  // 2.905.0 (#5255): exactly this step
    if (b.dataset.c !== undefined) { $$('#l-col button', md).forEach(x => x.classList.remove('on')); b.classList.add('on'); if (id) autosave(); }
    if (b.id === 'l-emo') { $('#l-emogrid', md).classList.toggle('hidden'); return; }
    if (b.dataset.licon) {  // 2.0.2: a picture instead of the emoji (the emoji leaves the name)
      const k = b.dataset.licon;
      const url = k === 'upload' ? await liconUpload(id) : await liconSet(id, k);
      if (url === null) return;
      if (!md.isConnected) return;
      const x = listById(id) || l;
      if (url && emo) { emo = ''; $$('#l-emogrid [data-emo]', md).forEach(y => y.classList.remove('on')); await autosave(); }
      $('#l-emo', md).innerHTML = x.icon ? licon(x, 'licon m') : sbiEmo(emo) || ic('list');
      const w = $('.lipickw', md); if (w) w.innerHTML = `<span class="muted lipl">${tr('Or a picture')}</span>${liconPickHtml(x)}`;
      if (url) $('#l-emogrid', md).classList.add('hidden');
      return;
    }
    if (b.dataset.emo !== undefined) {
      if (id && listById(id)?.icon && b.dataset.emo) await liconSet(id, 'none');  // 2.0.2: an emoji replaces the picture
      const w = $('.lipickw', md); if (w && listById(id)) w.innerHTML = `<span class="muted lipl">${tr('Or a picture')}</span>${liconPickHtml(listById(id))}`;
      emo = b.dataset.emo;
      $$('#l-emogrid button', md).forEach(x => x.classList.toggle('on', x === b && !!emo));
      $('#l-emo', md).innerHTML = sbiEmo(emo) || ic('list');
      $('#l-emogrid', md).classList.add('hidden');
      if (id) autosave();
      return;
    }
    const a = b.dataset.m;
    if (a === 'close') {  // 2.270.0 A (#3019): a failed save keeps the dialog open
      // 2.359.2 B (#3049): also on the next tap: closing without the save only after "Discard changes?"
      if (id) { await autosave(); if (lfail && !await lDiscard()) return; }
      md.remove();
    }
    if (a === 'dup') { await autosave(); md.remove(); listDuplicate(id); return; }  // 2.78.0 (#1881)
    if (a === 'tpl') { await autosave(); md.remove(); saveTemplate({list_id: id, relative: true}, lname(l)); return; }  // 2.4.0 (#328): projects keep their dates relative to the project start; 2.352.0 C (#2752): every project
    if (a === 'save' && !id) {  // a new list (an existing one saves itself)
      const nm = $('#l-name', md).value.trim().replace(EMO_RE, '');
      if (!nm) {  // 2.354.0 C (#3013): say why nothing happens, mark the field
        const ni = $('#l-name', md); ni.setAttribute('aria-invalid', 'true'); ni.addEventListener('input', () => ni.removeAttribute('aria-invalid'), {once: true});
        toast(tr('Name missing')); return ni.focus();
      }
      /** @type {any} */
      const body = own ? {name: l.is_inbox && !emo && nm === tr('Basket') ? (inboxDef(l.name) ? l.name : 'Eingang') : emo + nm, folder: fNorm($('#l-folder', md).value), view: $('#l-view', md).value, color: $('#l-col button.on', md)?.dataset.c || '', kind: $('#l-kind', md).value, ...($('#l-depshift', md) ? {dep_shift: $('#l-depshift', md).checked} : {}), ...($('#l-rate', md) ? {rate: numBody($('#l-rate', md).value)} : {}), ...($('#l-nag', md)?.value ? {nag: $('#l-nag', md).value} : {}), ...($('#l-dab', md)?.checked ? {checklist: true} : {}), ...($('#l-ws', md) ? {org_id: $('#l-ws', md).value ? +$('#l-ws', md).value : null} : {})}  // 2.28.0 (#935)
        : {folder: fNorm($('#l-folder', md).value), view: $('#l-view', md).value};  // members: only their own placement / view
      if (body.folder && !folderNames().includes(body.folder)) await api('PATCH', '/api/settings', {set_delta: {folders: {add: [body.folder]}}, _auto: 1});  // 2.269.0 B (#3014); 2.1013.0 (#5773): a part of the list edit, no undo step
      const {rate, nag, day_hours: _dh, ...b0} = body;
      const pt = $('.ptcard.on', md)?.dataset.pt || '';  // 2.352.0 C (#2752): every project may start from a type
      let n;
      if (pt.startsWith('tpl:')) {  // 2.4.0 (#328): the person's own template, dates from the project start (optionally to an end)
        try { n = {id: (await api('POST', `/api/templates/${+pt.slice(4)}/apply`, {name: body.name, folder: body.folder, ...(body.color ? {color: body.color} : {}), start: $('#l-pstart', md).value || today(), ...($('#l-pend', md).value ? {end: $('#l-pend', md).value} : {})})).list_id}; } catch { return; }
      } else {
        // 2.411.0 (#3516): no type in a folder that has one = chosen so (ptype ""), the server would give it the folder's type
        try { n = await api('POST', '/api/lists', pt ? {name: b0.name, folder: b0.folder, color: b0.color, ptype: pt, ...($('#l-ptsecs', md)?.checked ? {sections: true} : {}), ...(pt === 'software' && $('#l-ptbug', md)?.checked ? {bug_inbox: true} : {}), ...('org_id' in b0 ? {org_id: b0.org_id} : {})} : own && folderPtype(b0.folder) ? {...b0, ptype: ''} : b0); } catch { return; }
      }
      // 2.359.2 B (#3049): the rate / reminder sent after the create: a failure says so, with the list's dialog one tap away
      const rnFail = (rate || nag) && await api('PATCH', '/api/lists/' + n.id, {...(rate ? {rate} : {}), ...(nag ? {nag} : {})}).then(() => false, () => true);
      if ($('#l-ws', md)) LS.set('wsLastProj', $('#l-ws', md).value ? 'org:' + $('#l-ws', md).value : 'private');  // 2.364.0 D (#3033): the next one starts there
      md.remove(); await load(); go('l/' + n.id);
      if (rnFail) toast(tr('Could not save'), () => listModal(n.id), 10000, tr('Open'));
      modulesOnToast(n.modules_on);
      if (pt === 'software') projectNextSteps(n.id);
      return;
    }
    if (a === 'arch') { await autosave(); md.remove(); await listArchive(id, !l.archived); }
    if (a === 'sw-setup') { await autosave(); md.remove(); if (await setListPtype(id, 'software')) listModal(id); }  // 2.22.0 (#746)
    if (a === 'del') { if (await listDeleteForGood(id)) md.remove(); }
  });
  md.addEventListener('keydown', (/** @type {any} */ e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT' && e.target.id !== 'l-emocustom' && !e.target.id.startsWith('lp-')) { if (id) { e.preventDefault(); autosave(); } else $('[data-m="save"]', md).click(); } });
  if (!own && !ladm) { if (!isTouch()) setTimeout(() => $('#l-folder', md).focus(), 50); return; }
  let emoTouched = !!id;  // 2.22.0 (#682): the suggestion follows the name until the person picks something themselves
  md.addEventListener('click', (/** @type {any} */ e) => { if (e.target.closest('#l-emogrid [data-emo]')) emoTouched = true; }, true);
  md.addEventListener('input', (/** @type {any} */ e) => {
    if (e.target.id !== 'l-name' || emoTouched) return;
    const s = autoEmoji(e.target.value);
    if (s === emo) return;
    emo = s;
    const b = $('#l-emo', md); b.innerHTML = sbiEmo(emo) || ic('list'); b.title = emo ? tr('Suggested icon: tap to change or remove it') : tr('Select icon');
    b.classList.toggle('sugg', !!emo);
    $$('#l-emogrid button', md).forEach(x => x.classList.toggle('on', !!emo && x.dataset.emo === emo));
  });
  md.addEventListener('input', (/** @type {any} */ e) => {  // any emoji typed (or picked from the OS keyboard) into the custom field
    if (e.target.id !== 'l-emocustom') return;
    emoTouched = true;
    const m = e.target.value.match(EMO_RE);
    if (m) { emo = m[1]; $('#l-emo', md).innerHTML = emo; $$('#l-emogrid button', md).forEach(x => x.classList.remove('on')); if (id) later(e.target); }
  });
  if (!id && !o.ptype && !o.kind) lmFolderPtype(md, folder);  // 2.411.0 (#3516)
  if (!isTouch()) setTimeout(() => $('#l-name', md).focus(), 50);  // 2.13.0: touch: no keyboard popping up on open
  return md;
}
// 2.115.0 (#2061): the inbound webhook section of the list settings; the rest of it loads on demand (hookin.js, whiMount)
const whiOn = l => !!l && !l.is_inbox && l.life !== 'health' && l.life !== 'budget' && canManage(l);

function whiBoxHtml(l) {
  if (!whiOn(l)) return '';
  return `<h4 title="${esc(tr('Create tasks in this project from other tools (n8n, Make, Zapier, Home Assistant)'))}">${tr('Inbound webhook')}</h4><div class="members whi-box" id="l-whi"><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
