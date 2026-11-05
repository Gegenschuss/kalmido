// 2.50.0 (#1196, part B): the sales pipeline in the office (tab "Pipeline", admins of the office area only): deals in the
// stages inquiry, quotation sent, order and lost -- columns on a computer (drag a card = change its stage), on the phone one
// stage at a time with a switcher. On top: the open sum, the weighted sum and what is expected to come in per month (next
// month marked). A deal makes its quotation (the office's own quotation code) and, once won, its project; a quotation set
// to accepted moves its deal to "Order" on the server. Every change is one undo step. Server: kalmido/office/pipeline.py.
const PPS = {data: null, err: null, oid: null, stage: 'inquiry', loading: false, drag: null, gen: 0};
// 2.94.0 A (#1930): + the first column "Leads" (office_leads.js: its cards, fields, convert, CSV import)
const PP_STAGES = [['lead', N_('Leads')], ['inquiry', N_('Enquiry')], ['offer', N_('Quotation sent')], ['won', N_('Order|pipeline')], ['lost', N_('Lost|pipeline')]];
OFC_TABS.splice(Math.max(0, OFC_TABS.findIndex(t => t[0] === 'cashflow' || t[0] === 'settings')), 0, ['pipeline', 'target', N_('Pipeline'), 1, () => pp_html()]);  // admins only

const pp_stageName = k => tr(PP_STAGES.find(s => s[0] === k)?.[1] || k);
const pp_month = ym => { if (!ym) return ''; const [y, m] = ym.split('-').map(Number); return new Date(y, m - 1, 1).toLocaleDateString(LOCALE(), {month: 'short', year: 'numeric'}); };
async function pp_load() {
  if (PPS.loading) return;
  PPS.loading = true; const gen = PPS.gen;
  let j = null;
  try { j = await api('GET', '/api/office/deals'); PPS.err = null; }
  catch (x) { if (!PPS.data) PPS.err = x.message || tr('unknown'); }  // 2.559.0 (#4660): a failed background reload keeps the cards
  PPS.loading = false;
  if (gen !== PPS.gen) return pp_load();  // 2.559.0 (#4660): an answer from before an own change is fetched again, the cards stay
  if (j) { PPS.data = j; for (const p of OPT) p.put(); }  // own changes still on the way stay on top of the fresh board
  ofcDraw();
}
const pp_reload = () => { PPS.data = null; ofcDraw(); };
// 2.559.0 (#4660): moving, changing, adding and deleting a deal show at once (optWrite): the board changes locally, the request
// runs behind it, a refusal puts the old state back (api() says why); the answer's deal replaces the local one, the sums on
// top (open, weighted, expected) are the server's: the board is fetched again in the background, the cards stay meanwhile.
// A new deal is a provisional card with a negative id until the answer. Quotation / project from a deal stay waiting.
const pp_refresh = () => { PPS.gen++; if (PPS.data) pp_load(); };
const pp_wait = id => { if (!(+id < 0)) return false; toast(tr('Still syncing, try again in a moment')); return true; };  // a provisional card
const pp_item = id => (PPS.data?.items || []).find(i => i.id === id);
function pp_itemSet(x, was = x?.id) {  // the server's deal in place of the local one (was: its provisional id)
  const its = PPS.data?.items; if (!its || !x) return;
  const {before, ...d} = x, k = its.findIndex(i => i.id === was || i.id === d.id);
  if (k >= 0) its[k] = {...its[k], ...d}; else its.push(d);
}
const pp_local = b => ({...b, value: (+b.value || 0).toFixed(2), ...('client_id' in b ? {client_name: cdn_name(b.client_id, '')} : {})});

function pp_html() {
  if (PPS.oid !== OFC.info?.org_id) Object.assign(PPS, {oid: OFC.info?.org_id, data: null, err: null});  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only for admins of the office.')}</div>`;
  if (PPS.err) return `<div class="empty">${esc(PPS.err)}</div>`;
  if (!PPS.data) { setTimeout(() => { if (!PPS.data) pp_load(); }, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = PPS.data, s = d.summary, items = d.items || [];
  const top = `<div class="ofcbar">${lst_sortBtn('pipeline', LST_MANUAL)}<span class="spacer"></span>${typeof leadBar === 'function' ? leadBar() : ''}<button class="btn sm pri" data-pp="new">${ic('plus', 's')}<span>${tr('New enquiry')}</span></button></div>
    <div class="pptiles"><div class="pptile"><small class="muted">${tr('Open|pipeline')}</small><b>${ofcMoney(s.open)}</b><small class="muted">${esc(trn('{0} deal', '{0} deals', s.count_open))}</small></div>
    <div class="pptile"><small class="muted">${tr('Weighted')}</small><b>${ofcMoney(s.weighted)}</b><small class="muted">${tr('value × probability')}</small></div></div>
    <section class="pipfc" aria-label="${esc(tr('Expected to come in'))}"><h3 class="ofcgrp">${tr('Expected to come in')}</h3><ol class="ppfcl" role="list">${s.forecast.map(f => `<li class="${f.next ? 'next' : ''}"><small>${esc(pp_month(f.month))}${f.next ? ` <span class="rotag">${tr('next month')}</span>` : ''}</small><b>${ofcMoney(f.weighted)}</b></li>`).join('')}</ol>
    ${+s.undated ? `<p class="muted ofchint">${tr('Without an expected date: {0}', ofcMoney(s.undated))}</p>` : ''}</section>`;
  if (!items.length) return top + `<div class="empty nempty eact">${ic('target')}<span>${tr('No deals yet. Note every enquiry here and follow it to the order.')}</span><button class="btn pri" data-pp="new">${ic('plus', 's')}<span>${tr('New enquiry')}</span></button>${oim_link('leads', true, true)}</div>`;  // 2.122.3 A (#2335): + the leads import
  const sw = `<div class="seg ppseg" role="tablist" aria-label="${esc(tr('Stage'))}">${PP_STAGES.map(([k, n]) => `<button type="button" role="tab" data-pp="stage" data-v="${k}" aria-selected="${PPS.stage === k}" class="${PPS.stage === k ? 'on' : ''}">${tr(n)} <span class="muted">${items.filter(x => x.stage === k).length}</span></button>`).join('')}</div>`;
  const cols = PP_STAGES.map(([k, n]) => {
    const lead = k === 'lead' && typeof leadCard === 'function';  // 2.94.0 A (#1930): leads by follow-up day, no sum
    let its = items.filter(x => x.stage === k);
    if (lead) its = leadSort(its);
    its = lst_sorted(its, 'pipeline', x => ({date: lead ? x.follow_up : x.expected_date, client: lead ? x.company || x.contact : cdn_name(x.client_id, x.client_name) || x.contact, amount: lead ? null : x.value, name: x.title}), LST_MANUAL);  // 2.451.0 (#3834)
    const sum = its.reduce((a, x) => a + +x.value, 0);
    return `<section class="pipcol ${PPS.stage === k ? 'on' : ''}" data-pipcol="${k}" aria-label="${esc(tr(n))}"><header><b>${tr(n)}</b><span class="muted">${its.length}</span><span class="spacer"></span>${lead ? '' : `<span class="rksum muted" title="${esc(tr('Values net, in the office currency.'))}">${ofcMoney(sum)}</span>`}</header>
      <ul class="ppcards" role="list">${its.map(lead ? leadCard : pp_card).join('') || `<li class="muted ppnone">${lead ? tr('No leads yet. Note people who might become clients, with the next step and a follow-up day.') + oim_link('leads', true, true) : tr('Nothing here')}</li>`}</ul>${lead && its.length ? oim_link('leads', false, true) : ''}</section>`;  // 2.122.3 A (#2335): + the import link
  }).join('');
  // 2.298.0 A2 (#3186): the drag hint only where columns are side by side (.pphint hidden under 900 px, app.css); "net" as
  // the title of each column sum
  return top + sw + `<div class="pipcols">${cols}</div><p class="muted ofchint pphint">${tr('Drag a card into another column to change its stage.')}</p>`;
}
function pp_card(x) {
  const who = cdn_name(x.client_id, x.client_name) || x.contact;  // 2.97.0 B (#1951)
  const offer = x.offer_id ? `<span class="rotag ${x.offer_status === 'declined' ? 'ppdecl' : `st-${esc(x.offer_status)}`}">${esc(tr('Quotation {0}', x.offer_number || ''))}${x.offer_status === 'declined' ? ' · ' + tr('declined') : x.offer_status === 'superseded' ? ' · ' + tr('Superseded') : ''}</span>` : '';
  return `<li><div role="button" tabindex="0" class="ppcard${x.offer_status === 'declined' && x.stage !== 'lost' ? ' warn' : ''}" draggable="true" data-pp="open" data-id="${x.id}">
    <span class="pptitle">${esc(x.title)}</span>${who ? `<small class="muted">${esc(who)}</small>` : ''}
    <span class="ppmeta"><b class="rksum">${ofcMoney(x.value)}</b><span class="muted" title="${esc(tr('Probability'))}">${x.probability} %</span>${x.expected_date ? `<span class="muted" title="${esc(tr('Expected date'))}">${esc(fmtDateLoc(x.expected_date))}</span>` : ''}</span>
    ${offer || x.list_id ? `<span class="ppmeta">${offer}${x.list_id ? `<span class="rotag">${ic('brief', 's')}${tr('Project')}</span>` : ''}</span>` : ''}</div></li>`;
}

async function pp_patch(id, body, msg = tr('Saved'), expect = null) {  // 2.559.0 (#4660): at once, see above; throws on a refusal (api() / the caller says why)
  // 2.560.0 C (#4700): the dialog sends the updated_at it opened with (saved elsewhere meanwhile -> 409); the undo
  // writes back only the keys that really changed, with the version this save left
  const j = await optWrite(optSet(() => pp_item(id), pp_local(body)), () => (expect ? rawFetch : api)('PATCH', `/api/office/deals/${id}`, expect ? {...body, expect_updated_at: expect} : body), ofcDraw);
  pp_itemSet(j); pp_refresh();
  const before = Object.fromEntries(Object.entries(j.before || {}).filter(([k, v]) => JSON.stringify(v ?? null) !== JSON.stringify(j[k] ?? null)));
  if (Object.keys(before).length) toast(msg, async () => { const r = await undoWrite(`/api/office/deals/${id}`, before, j.updated_at, {label: j.title}).catch(() => null); if (r?.id) pp_itemSet(r); pp_refresh(); });  // 2.566.0 (#4704): core.js undoWrite
  else toast(msg);
  return j;
}
async function pp_move(id, stage) {
  const x = pp_item(id);
  if (!x || x.stage === stage || pp_wait(id)) return;
  // at once (pp_patch); 2.559.0 (#4660): a refusal puts the card back into its column, api() says why
  try { await pp_patch(id, {stage}, tr('Moved to {0}', pp_stageName(stage))); } catch { /* back already */ }
}

function pp_modal(x, stage) {
  const cls = typeof ofdClientOpts === 'function' ? ofdClientOpts() : [];
  const st = x?.stage || stage || 'inquiry';
  const lf = typeof leadFields === 'function', isL = lf && st === 'lead';  // 2.94.0 A (#1930): the lead's rows instead of client / probability / date
  const md = modal(`<h3>${x ? (x.stage === 'lead' ? tr('Edit lead') : tr('Edit deal')) : isL ? tr('New lead') : tr('New enquiry')}</h3>
    ${ofcRowF('pp-title', tr('Name'), ofcIn('pp-title', x?.title, {ph: tr('e.g. Image film for the spring')}))}
    ${cls.length ? `<div class="ppnolead" ${isL ? 'hidden' : ''}>${ofcRowF('pp-client', tr('Client'), ofcSel('pp-client', x?.client_id, cls, tr('none')))}</div>` : ''}
    ${ofcRowF('pp-contact', tr('Contact|person'), ofcIn('pp-contact', x?.contact, {ph: tr('Name, if there is no client yet')}))}
    ${lf ? leadFields(x, isL) : ''}
    ${ofcRowF('pp-value', tr('Value (net)'), ofcIn('pp-value', x ? fmtNum(+x.value, 2) : '', {num: true}), ofcCur(), {keep: 1})}
    ${ofcRowF('pp-stage', tr('Stage'), ofcSel('pp-stage', st, PP_STAGES.map(([k, n]) => [k, tr(n)])))}
    <div class="ppnolead" ${isL ? 'hidden' : ''}>${ofcRowF('pp-prob', tr('Probability (%)'), `<input id="pp-prob" type="number" min="0" max="100" step="5" inputmode="numeric" value="${x ? x.probability : isL ? 10 : 20}">`)}
    <div class="row"><label id="pp-datel">${tr('Expected date')}</label>${dateIn('pp-date', x?.expected_date || '', {label: tr('Expected date'), empty: tr('open')})}</div></div>
    <div class="row pplost" ${st === 'lost' ? '' : 'hidden'}><label for="pp-lost">${tr('Why lost')}</label>${ofcIn('pp-lost', x?.lost_reason, {max: 500})}</div>
    <div class="row"><label for="pp-note">${tr('Note')}</label><textarea id="pp-note" rows="3" maxlength="4000">${esc(x?.note || '')}</textarea></div>
    ${x && x.stage !== 'lead' ? `<div class="ppacts">${x.offer_id ? `<a class="btn" href="#office/offers/${x.offer_id}" data-m="close">${ic('receipt', 's')}<span>${tr('Open quotation')}</span></a>`
      : `<button class="btn" data-m="offer">${ic('receipt', 's')}<span>${tr('Create quotation')}</span></button>`}
      ${x.list_id ? `<a class="btn" href="#l/${x.list_id}" data-m="close">${ic('brief', 's')}<span>${tr('Open project')}</span></a>` : x.stage === 'won' ? `<button class="btn" data-m="project">${ic('brief', 's')}<span>${tr('Create project')}</span></button>` : ''}</div>
      ${x.offer_status === 'declined' && x.stage !== 'lost' ? `<p class="muted ofchint">${tr('The client declined the quotation. Set the stage to "Lost" or make a new quotation.')}</p>` : ''}` : ''}
    <div class="aerr" role="alert"></div>
    <div class="foot">${x ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${x ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  const PROB = PPS.data?.probabilities || {lead: 10, inquiry: 20, offer: 50, won: 100, lost: 0};
  $('#pp-stage', md).addEventListener('change', e => {
    const v = e.target.value, p = $('#pp-prob', md), was = PROB[md.dataset.st || st];
    if (+p.value === was || v === 'won' || v === 'lost') p.value = PROB[v];  // the stage's preset unless set by hand
    md.dataset.st = v;
    $('.pplost', md).hidden = v !== 'lost';
    if (lf) { $('.leadf', md).hidden = v !== 'lead'; $$('.ppnolead', md).forEach(r => { r.hidden = v === 'lead'; }); }
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    const err = m => { const el = $('.aerr', md); if (el) el.textContent = m || ''; };
    try {
      if (b.dataset.m === 'del') {  // 2.559.0 (#4660): gone at once, a refusal brings it back
        md.remove();
        const out = () => { const its = PPS.data?.items, k = its ? its.findIndex(i => i.id === x.id) : -1; if (k < 0) return null; const [o] = its.splice(k, 1); return () => { if (PPS.data && !pp_item(x.id)) PPS.data.items.splice(Math.min(k, PPS.data.items.length), 0, o); }; };
        try { await optWrite(out, () => api('DELETE', `/api/office/deals/${x.id}`), ofcDraw); } catch { return; }
        pp_refresh();
        toast(tr('Deleted'), async () => { pp_itemSet(await api('POST', `/api/office/deals/${x.id}/restore`)); pp_refresh(); });
        return;
      }
      if (b.dataset.m === 'offer') {
        const j = await api('POST', `/api/office/deals/${x.id}/offer`); md.remove(); pp_reload();
        if (typeof OFD === 'object') { OFD.list = null; OFD.kind = 'offer'; }
        toast(tr('Quotation draft created'), async () => { await api('DELETE', `/api/office/docs/${j.doc_id}`); await undoWrite(`/api/office/deals/${x.id}`, {offer_id: null, stage: x.stage, probability: x.probability}, j.deal?.updated_at, {label: x.title}).catch(() => null); pp_reload(); });  // 2.566.0 (#4704): the deal against the version the offer left
        go(`office/offers/${j.doc_id}`);
        return;
      }
      if (b.dataset.m === 'convert') { await leadConvert(x, md); return; }  // 2.94.0 A (#1930)
      if (b.dataset.m === 'project') {
        const j = await api('POST', `/api/office/deals/${x.id}/project`); md.remove(); pp_reload();
        if (typeof load === 'function') await load();
        if (typeof modulesOnToast === 'function') modulesOnToast(j.modules_on);
        toast(tr('Project created'), async () => { await api('PATCH', `/api/lists/${j.list_id}`, {archived: true}); await undoWrite(`/api/office/deals/${x.id}`, {list_id: null}, j.deal?.updated_at, {label: x.title}).catch(() => null); pp_reload(); if (typeof load === 'function') await load(); });  // 2.566.0 (#4704): the deal against the version the project left
        return;
      }
      const v = id => $(id, md)?.value ?? '';
      const body = {title: v('#pp-title'), contact: v('#pp-contact'), value: ofcNum(v('#pp-value')) ?? 0, stage: v('#pp-stage'),
        probability: Math.max(0, Math.min(100, Math.round(+v('#pp-prob') || 0))), expected_date: v('#pp-date'), note: v('#pp-note'), lost_reason: v('#pp-lost')};
      if ($('#pp-client', md) && body.stage !== 'lead') body.client_id = v('#pp-client') ? +v('#pp-client') : null;
      if (lf && body.stage === 'lead') Object.assign(body, leadBody(md));  // 2.94.0 A (#1930): the lead's fields
      // 2.559.0 (#4660): the dialog closes at once, the card shows (a new one: provisional); a refusal puts the board back
      md.remove();
      if (x) {
        try { await pp_patch(x.id, body, tr('Saved'), x.updated_at || null); } catch (x2) {
          // 2.560.0 C (#4700) kept: saved elsewhere meanwhile -> the card is back, the dialog opens again with this input and the
          // bar; "Reload" opens the saved state (this input is not saved)
          if (x2.status === 409 && x2.data?.row) {
            const m2 = pp_modal({...x, ...body}), el = $('.aerr', m2);
            if (el) {
              el.innerHTML = `${esc(tr('Changed in the meantime'))} · ${esc(tr('Reload shows the saved version; your input here is not saved.'))} <button type="button" class="btn sm" data-pp-reload>${tr('Reload')}</button>`;
              $('[data-pp-reload]', el).addEventListener('click', () => { m2.remove(); pp_reload(); pp_modal(x2.data.row); });
            } else toast(tr('Changed in the meantime'));
          }
          else if (x.updated_at && x2.message) toast(x2.message);  // rawFetch does not show it itself
        }
        return;
      }
      const tmp = -Date.now(), was = PPS.stage;
      const put = () => { if (!PPS.data) return null; if (!pp_item(tmp)) PPS.data.items.push({offer_id: null, list_id: null, ...pp_local(body), id: tmp}); return () => { if (PPS.data) PPS.data.items = PPS.data.items.filter(i => i.id !== tmp); }; };
      PPS.stage = body.stage;
      let j; try { j = await optWrite(put, () => api('POST', '/api/office/deals', body), ofcDraw); } catch { if (PPS.stage === body.stage) PPS.stage = was; ofcDraw(); return; }
      pp_itemSet(j, tmp); pp_refresh();
      toast(tr('Added'), async () => { await api('DELETE', `/api/office/deals/${j.id}`); pp_refresh(); });
    } catch (x2) { err(x2.message); }
  });
  setTimeout(() => $('#pp-title', md)?.focus(), 30);
  return md;
}

// 2.525.0 (#4281): one-meaning guard: data-pp - new / newlead / stage / open only, else return before preventDefault (the proposal dialogs)
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-pp]'); if (!b) return;
  const a = b.dataset.pp;
  if (a === 'new') pp_modal(null);
  else if (a === 'newlead') pp_modal(null, 'lead');  // 2.94.0 A (#1930)
  else if (a === 'stage') { PPS.stage = b.dataset.v; ofcDraw(); }
  else if (a === 'open') { const x = pp_item(+b.dataset.id); if (x && !pp_wait(x.id)) pp_modal(x); }  // 2.559.0 (#4660): not a provisional card
  else return;
  e.preventDefault();
});
document.addEventListener('keydown', e => {  // the card is a div (Firefox drags no buttons): Enter / Space open it
  if ((e.key === 'Enter' || e.key === ' ') && e.target.classList?.contains('ppcard')) { e.preventDefault(); e.target.click(); }
});
// drag a card into another column (computer); the phone changes the stage in the card's dialog
document.addEventListener('dragstart', e => {
  const b = e.target.closest?.('.ppcard'); if (!b) return;
  PPS.drag = +b.dataset.id; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(PPS.drag));
  b.classList.add('dragging');
});
document.addEventListener('dragend', e => { e.target.closest?.('.ppcard')?.classList.remove('dragging'); $$('.pipcol.over').forEach(x => x.classList.remove('over')); });
document.addEventListener('dragover', e => {
  const col = PPS.drag && e.target.closest?.('.pipcol'); if (!col || col.dataset.pipcol === 'lead') return;  // 2.94.0 A (#1930): no drop into the leads
  e.preventDefault(); e.dataTransfer.dropEffect = 'move';
  $$('.pipcol.over').forEach(x => x !== col && x.classList.remove('over')); col.classList.add('over');
});
document.addEventListener('drop', e => {
  const col = PPS.drag && e.target.closest?.('.pipcol'); if (!col || col.dataset.pipcol === 'lead') return;
  e.preventDefault(); col.classList.remove('over');
  const id = PPS.drag; PPS.drag = null;
  pp_move(id, col.dataset.pipcol);
});
