// 2.50.0 (#1196, part B): the sales pipeline in the office (tab "Pipeline", admins of the office area only): deals in the
// stages inquiry, quotation sent, order and lost -- columns on a computer (drag a card = change its stage), on the phone one
// stage at a time with a switcher. On top: the open sum, the weighted sum and what is expected to come in per month (next
// month marked). A deal makes its quotation (the office's own quotation code) and, once won, its project; a quotation set
// to accepted moves its deal to "Order" on the server. Every change is one undo step. Server: kalmido/office/pipeline.py.
const PPS = {data: null, err: null, oid: null, stage: 'inquiry', loading: false, drag: null};
const PP_STAGES = [['inquiry', N_('Inquiry')], ['offer', N_('Quotation sent')], ['won', N_('Order|pipeline')], ['lost', N_('Lost|pipeline')]];
OFC_TABS.splice(Math.max(0, OFC_TABS.findIndex(t => t[0] === 'cashflow' || t[0] === 'settings')), 0, ['pipeline', 'target', N_('Pipeline'), 1, () => pp_html()]);  // admins only

const pp_stageName = k => tr(PP_STAGES.find(s => s[0] === k)?.[1] || k);
const pp_month = ym => { if (!ym) return ''; const [y, m] = ym.split('-').map(Number); return new Date(y, m - 1, 1).toLocaleDateString(LOCALE(), {month: 'short', year: 'numeric'}); };
async function pp_load() {
  if (PPS.loading) return;
  PPS.loading = true;
  try { PPS.data = await api('GET', '/api/office/deals'); PPS.err = null; }
  catch (x) { PPS.err = x.message || tr('unknown'); }
  PPS.loading = false;
  ofcDraw();
}
const pp_reload = () => { PPS.data = null; ofcDraw(); };

function pp_html() {
  if (PPS.oid !== OFC.info?.org_id) Object.assign(PPS, {oid: OFC.info?.org_id, data: null, err: null});  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only the admins of the office see the pipeline.')}</div>`;
  if (PPS.err) return `<div class="empty">${esc(PPS.err)}</div>`;
  if (!PPS.data) { setTimeout(() => { if (!PPS.data) pp_load(); }, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = PPS.data, s = d.summary, items = d.items || [];
  const top = `<div class="ofcbar"><span class="spacer"></span><button class="btn sm pri" data-pp="new">${ic('plus', 's')}<span>${tr('New inquiry')}</span></button></div>
    <div class="pptiles"><div class="pptile"><small class="muted">${tr('Open|pipeline')}</small><b>${ofcMoney(s.open)}</b><small class="muted">${esc(trn('{0} deal', '{0} deals', s.count_open))}</small></div>
    <div class="pptile"><small class="muted">${tr('Weighted')}</small><b>${ofcMoney(s.weighted)}</b><small class="muted">${tr('value × probability')}</small></div></div>
    <section class="ppfc" aria-label="${esc(tr('Expected to come in'))}"><h3 class="ofcgrp">${tr('Expected to come in')}</h3><ol class="ppfcl" role="list">${s.forecast.map(f => `<li class="${f.next ? 'next' : ''}"><small>${esc(pp_month(f.month))}${f.next ? ` <span class="rotag">${tr('next month')}</span>` : ''}</small><b>${ofcMoney(f.weighted)}</b></li>`).join('')}</ol>
    ${+s.undated ? `<p class="muted ofchint">${tr('Without an expected date: {0}', ofcMoney(s.undated))}</p>` : ''}</section>`;
  if (!items.length) return top + `<div class="empty nempty eact">${ic('target')}<span>${tr('No deals yet. Note every inquiry here and follow it to the order.')}</span><button class="btn pri" data-pp="new">${ic('plus', 's')}<span>${tr('New inquiry')}</span></button></div>`;
  const sw = `<div class="seg ppseg" role="tablist" aria-label="${esc(tr('Stage'))}">${PP_STAGES.map(([k, n]) => `<button type="button" role="tab" data-pp="stage" data-v="${k}" aria-selected="${PPS.stage === k}" class="${PPS.stage === k ? 'on' : ''}">${tr(n)} <span class="muted">${items.filter(x => x.stage === k).length}</span></button>`).join('')}</div>`;
  const cols = PP_STAGES.map(([k, n]) => {
    const its = items.filter(x => x.stage === k), sum = its.reduce((a, x) => a + +x.value, 0);
    return `<section class="ppcol ${PPS.stage === k ? 'on' : ''}" data-ppcol="${k}" aria-label="${esc(tr(n))}"><header><b>${tr(n)}</b><span class="muted">${its.length}</span><span class="spacer"></span><span class="rksum muted">${ofcMoney(sum)}</span></header>
      <ul class="ppcards" role="list">${its.map(pp_card).join('') || `<li class="muted ppnone">${tr('Nothing here')}</li>`}</ul></section>`;
  }).join('');
  return top + sw + `<div class="ppcols">${cols}</div><p class="muted ofchint">${tr('Drag a card into another column to change its stage. Values net, in the office currency.')}</p>`;
}
function pp_card(x) {
  const who = x.client_name || x.contact;
  const offer = x.offer_id ? `<span class="rotag ${x.offer_status === 'declined' ? 'ppdecl' : `st-${esc(x.offer_status)}`}">${esc(tr('Quotation {0}', x.offer_number || ''))}${x.offer_status === 'declined' ? ' · ' + tr('declined') : ''}</span>` : '';
  return `<li><div role="button" tabindex="0" class="ppcard${x.offer_status === 'declined' && x.stage !== 'lost' ? ' warn' : ''}" draggable="true" data-pp="open" data-id="${x.id}">
    <span class="pptitle">${esc(x.title)}</span>${who ? `<small class="muted">${esc(who)}</small>` : ''}
    <span class="ppmeta"><b class="rksum">${ofcMoney(x.value)}</b><span class="muted">${x.probability} %</span>${x.expected_date ? `<span class="muted">${esc(fmtDateLoc(x.expected_date))}</span>` : ''}</span>
    ${offer || x.list_id ? `<span class="ppmeta">${offer}${x.list_id ? `<span class="rotag">${ic('brief', 's')}${tr('Project')}</span>` : ''}</span>` : ''}</div></li>`;
}

async function pp_patch(id, body, msg = tr('Saved')) {
  const j = await api('PATCH', `/api/office/deals/${id}`, body);
  pp_reload();
  const before = j.before || {};
  if (Object.keys(before).length) toast(msg, async () => { await api('PATCH', `/api/office/deals/${id}`, before); pp_reload(); });
  return j;
}
async function pp_move(id, stage) {
  const x = (PPS.data?.items || []).find(i => i.id === id);
  if (!x || x.stage === stage) return;
  x.stage = stage; ofcDraw();  // at once; the reload brings the server's values
  try { await pp_patch(id, {stage}, tr('Moved to {0}', pp_stageName(stage))); } catch (e) { toast(e.message || tr('unknown')); pp_reload(); }
}

function pp_modal(x) {
  const cls = typeof ofdClientOpts === 'function' ? ofdClientOpts() : [];
  const st = x?.stage || 'inquiry';
  const md = modal(`<h3>${x ? tr('Edit deal') : tr('New inquiry')}</h3>
    ${ofcRowF('pp-title', tr('Name'), ofcIn('pp-title', x?.title, {ph: tr('e.g. Image film for the spring')}))}
    ${cls.length ? ofcRowF('pp-client', tr('Client'), ofcSel('pp-client', x?.client_id, cls, tr('none'))) : ''}
    ${ofcRowF('pp-contact', tr('Contact|person'), ofcIn('pp-contact', x?.contact, {ph: tr('Name, if there is no client yet')}))}
    ${ofcRowF('pp-value', tr('Value (net)'), ofcIn('pp-value', x ? fmtNum(+x.value, 2) : '', {num: true}), ofcCur())}
    ${ofcRowF('pp-stage', tr('Stage'), ofcSel('pp-stage', st, PP_STAGES.map(([k, n]) => [k, tr(n)])))}
    ${ofcRowF('pp-prob', tr('Probability (%)'), `<input id="pp-prob" type="number" min="0" max="100" step="5" inputmode="numeric" value="${x ? x.probability : 20}">`)}
    <div class="row"><label id="pp-datel">${tr('Expected date')}</label>${dateIn('pp-date', x?.expected_date || '', {label: tr('Expected date'), empty: tr('open')})}</div>
    <div class="row pplost" ${st === 'lost' ? '' : 'hidden'}><label for="pp-lost">${tr('Why lost')}</label>${ofcIn('pp-lost', x?.lost_reason, {max: 500})}</div>
    <div class="row"><label for="pp-note">${tr('Note')}</label><textarea id="pp-note" rows="3" maxlength="4000">${esc(x?.note || '')}</textarea></div>
    ${x ? `<div class="ppacts">${x.offer_id ? `<a class="btn" href="#office/offers/${x.offer_id}" data-m="close">${ic('receipt', 's')}<span>${tr('Open quotation')}</span></a>`
      : `<button class="btn" data-m="offer">${ic('receipt', 's')}<span>${tr('Create quotation')}</span></button>`}
      ${x.list_id ? `<a class="btn" href="#l/${x.list_id}" data-m="close">${ic('brief', 's')}<span>${tr('Open project')}</span></a>` : x.stage === 'won' ? `<button class="btn" data-m="project">${ic('brief', 's')}<span>${tr('Create project')}</span></button>` : ''}</div>
      ${x.offer_status === 'declined' && x.stage !== 'lost' ? `<p class="muted ofchint">${tr('The client declined the quotation. Set the stage to "Lost" or make a new quotation.')}</p>` : ''}` : ''}
    <div class="aerr" role="alert"></div>
    <div class="foot">${x ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${x ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  const PROB = PPS.data?.probabilities || {inquiry: 20, offer: 50, won: 100, lost: 0};
  $('#pp-stage', md).addEventListener('change', e => {
    const v = e.target.value, p = $('#pp-prob', md), was = PROB[md.dataset.st || st];
    if (+p.value === was || v === 'won' || v === 'lost') p.value = PROB[v];  // the stage's preset unless set by hand
    md.dataset.st = v;
    $('.pplost', md).hidden = v !== 'lost';
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    const err = m => { const el = $('.aerr', md); if (el) el.textContent = m || ''; };
    try {
      if (b.dataset.m === 'del') {
        await api('DELETE', `/api/office/deals/${x.id}`); md.remove(); pp_reload();
        toast(tr('Deleted'), async () => { await api('POST', `/api/office/deals/${x.id}/restore`); pp_reload(); });
        return;
      }
      if (b.dataset.m === 'offer') {
        const j = await api('POST', `/api/office/deals/${x.id}/offer`); md.remove(); pp_reload();
        if (typeof OFD === 'object') { OFD.list = null; OFD.kind = 'offer'; }
        toast(tr('Quotation draft created'), async () => { await api('DELETE', `/api/office/docs/${j.doc_id}`); await api('PATCH', `/api/office/deals/${x.id}`, {offer_id: null, stage: x.stage, probability: x.probability}); pp_reload(); });
        go(`office/offers/${j.doc_id}`);
        return;
      }
      if (b.dataset.m === 'project') {
        const j = await api('POST', `/api/office/deals/${x.id}/project`); md.remove(); pp_reload();
        if (typeof load === 'function') await load();
        if (typeof modulesOnToast === 'function') modulesOnToast(j.modules_on);
        toast(tr('Project created'), async () => { await api('PATCH', `/api/lists/${j.list_id}`, {archived: true}); await api('PATCH', `/api/office/deals/${x.id}`, {list_id: null}); pp_reload(); if (typeof load === 'function') await load(); });
        return;
      }
      const v = id => $(id, md)?.value ?? '';
      const body = {title: v('#pp-title'), contact: v('#pp-contact'), value: ofcNum(v('#pp-value')) ?? 0, stage: v('#pp-stage'),
        probability: Math.max(0, Math.min(100, Math.round(+v('#pp-prob') || 0))), expected_date: v('#pp-date'), note: v('#pp-note'), lost_reason: v('#pp-lost')};
      if ($('#pp-client', md)) body.client_id = v('#pp-client') ? +v('#pp-client') : null;
      if (x) { await pp_patch(x.id, body); md.remove(); }
      else {
        const j = await api('POST', '/api/office/deals', body); md.remove(); PPS.stage = j.stage; pp_reload();
        toast(tr('Added'), async () => { await api('DELETE', `/api/office/deals/${j.id}`); pp_reload(); });
      }
    } catch (x2) { err(x2.message); }
  });
  setTimeout(() => $('#pp-title', md)?.focus(), 30);
  return md;
}

document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-pp]'); if (!b) return;
  const a = b.dataset.pp;
  if (a === 'new') pp_modal(null);
  else if (a === 'stage') { PPS.stage = b.dataset.v; ofcDraw(); }
  else if (a === 'open') { const x = (PPS.data?.items || []).find(i => i.id === +b.dataset.id); if (x) pp_modal(x); }
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
document.addEventListener('dragend', e => { e.target.closest?.('.ppcard')?.classList.remove('dragging'); $$('.ppcol.over').forEach(x => x.classList.remove('over')); });
document.addEventListener('dragover', e => {
  const col = PPS.drag && e.target.closest?.('.ppcol'); if (!col) return;
  e.preventDefault(); e.dataTransfer.dropEffect = 'move';
  $$('.ppcol.over').forEach(x => x !== col && x.classList.remove('over')); col.classList.add('over');
});
document.addEventListener('drop', e => {
  const col = PPS.drag && e.target.closest?.('.ppcol'); if (!col) return;
  e.preventDefault(); col.classList.remove('over');
  const id = PPS.drag; PPS.drag = null;
  pp_move(id, col.dataset.ppcol);
});
