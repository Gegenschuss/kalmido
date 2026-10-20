/* Kalmido web client: Office & finance > Settings > Packs (2.76.0, #1023). Country and industry packs from the instance's
   catalogue (KALMIDO_PACKS_CATALOG): search, badges (Verified / Community), install, update, uninstall, undo; the
   industry pack boxes of the calculation rules follow the packs this office has. Packs are pure data, never code;
   finalised documents keep the pack version they were made with (server snapshot).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const PKC = {oid: null, q: '', kind: '', data: null, loading: false, seq: 0, packs: null, packsBusy: false, busy: '', err: {}, open: {}, t: null};
const pkc_key = it => `${it.kind}/${it.code}`;
const pkc_de = () => /^de/i.test(LOCALE());
const pkc_nm = p => { const n = p.name && typeof p.name === 'object' ? (pkc_de() ? p.name.de : p.name.en) || p.name.en || p.name.de : pkc_de() ? p.name : p.name_en || p.name; return n || p.code; };  // (a pack file's name may be {de, en})
const pkc_when = iso => iso ? (typeof ofdWhen === 'function' ? ofdWhen(iso) : iso) : '';
OFC_II.packs = N_('Packs bring the tax rates, formats and texts of a country or the calculation of an industry. They are pure data, never program code. Finalised documents keep the pack version they were made with.');
// a new office (workspace switch): forget the lists of the previous one
function pkc_sync() {
  const oid = OFC.info?.org_id ?? null;
  if (PKC.oid === oid) return;
  Object.assign(PKC, {oid, data: null, packs: null, packsBusy: false, loading: false, seq: PKC.seq + 1, err: {}, open: {}, busy: ''});
  OFC.packs = null;
}
// ---- loading
// the packs of this office (built in + installed): the country pack choice and the industry pack boxes
async function pkc_loadPacks() {
  if (PKC.packsBusy) return;
  PKC.packsBusy = true;
  const oid = PKC.oid;
  try {
    const j = await api('GET', '/api/office/packs');
    if (oid !== PKC.oid) return;
    PKC.packs = {country: j.packs || [], industry: j.industry || null};
    OFC.packs = PKC.packs.country.map(p => [p.code, `${pkc_nm(p)} (${p.code})`]);
  } catch { if (oid === PKC.oid) PKC.packs = {country: [], industry: null, failed: true}; }
  finally { PKC.packsBusy = false; }
  ofcDraw();
}
async function pkc_load(refresh) {
  const seq = ++PKC.seq, oid = PKC.oid;
  PKC.loading = true; pkc_paint();
  let j;
  try {
    j = refresh ? await api('POST', '/api/office/catalog/refresh', {}) : null;
    // the refresh answers with the full list; the search (q, kind) is asked again from the fresh cache
    if (!j || PKC.q || PKC.kind) j = await api('GET', `/api/office/catalog?q=${encodeURIComponent(PKC.q)}&kind=${encodeURIComponent(PKC.kind)}`);
  } catch (x) { j = {...(PKC.data || {}), error: x instanceof Offline ? tr('Offline: only works again with a connection') : x.message || tr('unknown'), items: PKC.data?.items || [], failed: !PKC.data}; }  // (the last list stays)
  if (seq !== PKC.seq || oid !== PKC.oid) return;
  PKC.loading = false; PKC.data = j; pkc_paint();
}
// ---- drawing
function pkc_html() {
  pkc_sync();
  if (!PKC.packs && !PKC.packsBusy) setTimeout(pkc_loadPacks, 0);
  if (!PKC.data && !PKC.loading) setTimeout(() => pkc_load(), 0);
  const d = PKC.data, kinds = [['', N_('All|packs')], ['country', N_('Countries')], ['industry', N_('Industries')]];
  return `<section class="pkc" id="pkc" data-fg-skip aria-labelledby="pkc-h">
    <h3 id="pkc-h">${tr('Packs')}</h3>${ofcII('packs')}
    <div class="pkc-bar">
      <input type="search" id="pkc-q" value="${esc(PKC.q)}" placeholder="${esc(tr('Search packs'))}" aria-label="${esc(tr('Search packs'))}" maxlength="80" autocomplete="off" enterkeyhint="search">
      <span class="pkc-kinds" role="group" aria-label="${esc(tr('Kind'))}">${kinds.map(([v, n]) => `<button type="button" class="btn sm${PKC.kind === v ? ' on' : ''}" data-pkc="kind" data-kind="${v}" aria-pressed="${PKC.kind === v}">${esc(tr(n))}</button>`).join('')}</span>
      ${d?.can_manage ? `<button type="button" class="btn sm" data-pkc="refresh">${ic('sync', 's')} ${tr('Refresh')}</button>` : ''}
    </div>
    <div id="pkc-body" aria-live="polite">${pkc_bodyHtml()}</div>
  </section>`;
}
function pkc_paint() { const el = $('#pkc-body'); if (el) el.innerHTML = pkc_bodyHtml(); const b = $('#pkc .pkc-bar'); if (b && PKC.data?.can_manage && !$('[data-pkc="refresh"]', b)) ofcDraw(); }
function pkc_bodyHtml() {
  const d = PKC.data;
  if (!d) return `<p class="muted">${tr('Loading…')}</p>`;
  const src = d.configured ? `<p class="muted pkc-src">${esc(d.fetched_at ? tr('Catalogue: {0}, as of {1}', d.source, pkc_when(d.fetched_at)) : tr('Catalogue: {0}', d.source))}${d.skipped ? ' · ' + esc(trn('{0} entry of the catalogue was skipped (not valid)', '{0} entries of the catalogue were skipped (not valid)', d.skipped)) : ''}</p>`
    : d.failed ? '' : `<p class="muted pkc-src">${tr('No catalogue set up – only the built-in packs are available.')}</p>`;
  const err = d.error ? `<p class="pkc-err" role="alert">${esc(d.error)}</p>` : '';
  const items = d.items || [];
  const list = items.length ? `<ul class="pkc-list" role="list">${items.map(pkc_itemHtml).join('')}</ul>`
    : `<p class="muted">${PKC.q || PKC.kind ? tr('No pack matches the search.') : tr('No packs yet.')}</p>`;
  return src + err + list + (PKC.loading ? `<p class="muted pkc-wait">${tr('Loading…')}</p>` : '');
}
const pkc_badge = b => b === 'verified' ? `<span class="pkc-badge ok">${ic('check', 's')} ${tr('Verified')}</span>`
  : `<span class="pkc-badge com" title="${esc(tr('Community packs are not checked by the Kalmido team. Check tax rates and texts before you send documents with it.'))}">${ic('alert', 's')} ${tr('Community')}</span>`;
function pkc_itemHtml(it) {
  const k = pkc_key(it), inst = it.installed, lt = it.latest, adm = !!PKC.data?.can_manage, busy = PKC.busy === k;
  const st = inst ? tr('Installed v{0}', inst.version) : it.builtin ? tr('Built in') : lt ? tr('Version {0}', lt.version) : '';
  const upd = it.update && lt ? `<span class="pkc-upd">${esc(tr('Update to v{0} available', lt.version))}</span>` : '';
  const desc = it.description || '', long = desc.length > 140 || desc.includes('\n'), open = PKC.open[k];
  const meta = [it.kind === 'industry' ? tr('Industry') : tr('Country'), it.code, it.author ? tr('by {0}', it.author) : '', it.license].filter(Boolean).map(esc).join(' · ');
  const btns = !adm ? '' : [
    !inst && !it.builtin && lt ? `<button type="button" class="btn sm pri" data-pkc="install" data-k="${esc(k)}" ${busy ? 'disabled' : ''}>${ic('download', 's')} ${tr('Install')}</button>` : '',
    it.update && lt ? `<button type="button" class="btn sm pri" data-pkc="update" data-k="${esc(k)}" ${busy ? 'disabled' : ''}>${ic('sync', 's')} ${tr('Update')}</button>` : '',
    inst ? `<button type="button" class="btn sm" data-pkc="remove" data-k="${esc(k)}" ${busy ? 'disabled' : ''}>${ic('trash', 's')} ${tr('Uninstall')}</button>` : ''].join('');
  return `<li class="pkc-item" data-pkc-item="${esc(k)}">
    <div class="pkc-head"><b class="pkc-name">${esc(it.name || it.code)}</b>${pkc_badge(inst?.badge || it.badge)}</div>
    <div class="muted pkc-meta">${meta}</div>
    ${desc ? `<div class="pkc-desc${long && !open ? ' clamp' : ''}">${mdFmt(desc)}</div>${long ? `<button type="button" class="btn sm pkc-more" data-pkc="more" data-k="${esc(k)}" aria-expanded="${!!open}">${open ? tr('Less') : tr('More')}</button>` : ''}` : ''}
    <div class="pkc-st"><span class="pkc-state">${esc(st)}</span>${upd}${inst?.installed_at ? `<span class="muted">${esc([inst.installed_by_name ? tr('by {0}', inst.installed_by_name) : '', pkc_when(inst.installed_at)].filter(Boolean).join(' · '))}</span>` : ''}</div>
    ${it.update && lt?.changes ? `<div class="muted pkc-changes">${mdFmt(lt.changes)}</div>` : ''}
    ${it.homepage && /^https:\/\//i.test(it.homepage) ? `<a class="pkc-home" href="${esc(it.homepage)}" target="_blank" rel="noopener noreferrer">${tr('Homepage')}</a>` : ''}
    ${PKC.err[k] ? `<p class="pkc-err" role="alert">${esc(PKC.err[k])}</p>` : ''}
    ${it.kind === 'industry' && (inst || it.builtin) ? pkc_onHtml(it, adm) : ''}
    ${btns ? `<div class="pkc-acts">${btns}</div>` : ''}
  </li>`;
}
// 2.113.0 (#2246): an industry pack's card says whether the pack is switched on in this office and switches it at once
// (office.js ost_save: saved like every settings field, one undo step; the same setting as the box in the calculation rules)
function pkc_onHtml(it, adm) {
  const on = (OFC.info?.settings?.industry_packs || []).includes(it.code);
  return `<div class="pkc-on"><label class="chkl swl"><span class="swc"><input type="checkbox" role="switch" data-pkc-on="${esc(it.code)}" ${on ? 'checked' : ''} ${adm ? '' : 'disabled'} aria-label="${esc(tr('Industry pack {0}', it.name || it.code))}"><span class="swt" aria-hidden="true"></span></span><span class="pkc-onst">${esc(on ? tr('Switched on') : tr('Off'))}</span></label></div>`;
}
document.addEventListener('change', e => { const t = e.target; if (t.dataset?.pkcOn && t.closest('#pkc')) { const st = t.closest('.pkc-on')?.querySelector('.pkc-onst'); if (st) st.textContent = t.checked ? tr('Switched on') : tr('Off'); } });
// the industry pack boxes of the calculation rules: film keeps its id os-ind-film (and its text), the others os-ind-<code>
function pkc_indHtml(s, dis) {
  pkc_sync();
  const on = s.industry_packs || [], list = PKC.packs?.industry || [{code: 'film'}];
  if (!list.some(p => p.code === 'film') && on.includes('film')) list.unshift({code: 'film'});
  return list.map(p => p.code === 'film'
    ? ofcChk('os-ind-film', tr('Industry pack Film & Video (shoot calculation in quotations)'), on.includes('film')) + ofcII('indfilm')
    : `<div class="row"><label class="chkl" style="min-width:0"><input type="checkbox" id="os-ind-${esc(p.code)}" data-ind="${esc(p.code)}" ${on.includes(p.code) ? 'checked' : ''} ${dis}> ${esc(tr('Industry pack {0}', pkc_nm(p)))}</label>${p.badge === 'community' ? pkc_badge('community') : ''}</div>`).join('');
}
const pkc_indBody = form => $$('input[id^="os-ind-"]', form).filter(x => x.checked).map(x => x.dataset.ind || x.id.slice(7));
// ---- actions (one undo step each)
const pkc_item = k => (PKC.data?.items || []).find(x => pkc_key(x) === k);
const pkc_url = it => `/api/office/packs/installed/${encodeURIComponent(it.kind)}/${encodeURIComponent(it.code)}`;
async function pkc_after() {
  PKC.packs = null; await pkc_loadPacks();
  if (typeof ofcInfo === 'function') await ofcInfo(true);  // the country pack in use may have changed version
  await pkc_load();
}
// quietly for undo / redo: errors as a toast, the step reports itself
const pkc_req = async (m, url, b) => { try { await api(m, url, b); } catch (x) { toast(x.status === 404 && m === 'POST' && url.endsWith('/install') ? tr('That version is no longer in the catalogue.') : x.message || tr('unknown')); } await pkc_after(); return {}; };
async function pkc_install(k, update) {
  const it = pkc_item(k); if (!it?.latest || PKC.busy) return;
  const body = {kind: it.kind, code: it.code, version: it.latest.version}, prev = it.installed?.version || null, name = it.name || it.code;
  // 2.76.0 review (M1): an update of the pack in effect recalculates the open documents -- said before, never blocking
  const aff = it.affects_text ? ' ' + it.affects_text : '';
  const ask = () => askConfirm(tr('Install the community pack “{0}”?', name), tr('Community packs are not checked by the Kalmido team. Check tax rates and texts before you send documents with it.') + aff, {ok: update ? tr('Update') : tr('Install')});
  if (it.badge === 'community') { if (!await ask()) return; body.accept_community = true; }
  else if (aff && !await askConfirm(tr('Update “{0}”?', name), aff.trim(), {ok: tr('Update')})) return;
  PKC.busy = k; delete PKC.err[k]; pkc_paint();
  try {
    try { await api('POST', '/api/office/packs/install', body); }
    catch (x) {
      if (x.status !== 409 || body.accept_community) throw x;
      if (!await ask()) return;  // the downloaded file says community although the catalogue says verified
      body.accept_community = true; await api('POST', '/api/office/packs/install', body);
    }
  } catch (x) {
    PKC.err[k] = x.status === 422 ? [x.message, ...(x.data?.problems || []).slice(0, 5)].filter(Boolean).join(' · ') : x instanceof Offline ? tr('Offline: only works again with a connection') : x.message || tr('unknown');
    return;
  } finally { PKC.busy = ''; pkc_paint(); }
  // undo: a new install is removed again; an update goes back to the version before (built in: remove the installed one)
  const undo = !prev ? () => pkc_req('DELETE', pkc_url(it)) : () => pkc_back(it, prev, name);
  const redo = () => pkc_req('POST', '/api/office/packs/install', {...body, accept_community: true});
  offerUndo(update ? tr('“{0}” updated to v{1}', name, body.version) : tr('“{0}” installed', name), histAdd({label: update ? tr('Update “{0}”', name) : tr('Install “{0}”', name), undo, redo}));
  await pkc_after();
}
// 2.76.0 review (N5): undo of an update installs the version before; a community version asks with the warning again
async function pkc_back(it, version, name) {
  const b = {kind: it.kind, code: it.code, version};
  try { await api('POST', '/api/office/packs/install', b); }
  catch (x) {
    if (x.status === 409 && await askConfirm(tr('Install the community pack “{0}”?', name), tr('Community packs are not checked by the Kalmido team. Check tax rates and texts before you send documents with it.'), {ok: tr('Install')})) return pkc_req('POST', '/api/office/packs/install', {...b, accept_community: true});
    if (x.status !== 409) toast(x.status === 404 ? tr('That version is no longer in the catalogue.') : x.message || tr('unknown'));
  }
  await pkc_after(); return {};
}
async function pkc_remove(k) {
  const it = pkc_item(k); if (!it?.installed || PKC.busy) return;
  const name = it.name || it.code;
  const aff = it.affects_text ? ' ' + it.affects_text : '';  // 2.76.0 review (M1)
  if (!await askConfirm(tr('Uninstall “{0}”?', name), (it.builtin ? tr('The office goes back to the built-in version. Finalised documents keep the pack version they were made with.') : tr('Finalised documents keep the pack version they were made with.')) + aff, {ok: tr('Uninstall'), danger: true})) return;
  PKC.busy = k; delete PKC.err[k]; pkc_paint();
  try { await api('DELETE', pkc_url(it)); }
  catch (x) { PKC.err[k] = x instanceof Offline ? tr('Offline: only works again with a connection') : x.message || tr('unknown'); return; }  // 409: what still uses it, in plain words
  finally { PKC.busy = ''; pkc_paint(); }
  offerUndo(tr('“{0}” uninstalled', name), histAdd({label: tr('Uninstall “{0}”', name), undo: () => pkc_req('POST', pkc_url(it) + '/restore'), redo: () => pkc_req('DELETE', pkc_url(it))}));
  await pkc_after();
}
// ---- events (the section sits inside the settings form: its keys and buttons never submit it)
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-pkc]'); if (!b || !b.closest('#pkc')) return;
  e.preventDefault();
  const a = b.dataset.pkc, k = b.dataset.k;
  if (a === 'kind') { PKC.kind = b.dataset.kind || ''; for (const x of $$('[data-pkc="kind"]')) { const on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on); } pkc_load(); }
  else if (a === 'refresh') pkc_load(true);
  else if (a === 'more') { PKC.open[k] = !PKC.open[k]; pkc_paint(); }
  else if (a === 'install' || a === 'update') pkc_install(k, a === 'update');
  else if (a === 'remove') pkc_remove(k);
});
document.addEventListener('input', e => {
  if (e.target.id !== 'pkc-q') return;
  PKC.q = e.target.value.trim();
  clearTimeout(PKC.t); PKC.t = setTimeout(() => pkc_load(), 250);
});
document.addEventListener('keydown', e => { if (e.target.id === 'pkc-q' && e.key === 'Enter') { e.preventDefault(); clearTimeout(PKC.t); pkc_load(); } });
