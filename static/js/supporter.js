// 2.74.0 (#338): the supporter licence -- self-hosted servers only (on a hosted one S.about carries none of the fields and
// /api/supporter answers 404: nothing is shown). It unlocks nothing: a small badge in Settings > Help > About and in
// Settings > Account. The raw key never comes back from the server; undo / redo exchange the current and the previous
// key there (POST /api/supporter/<kind>/swap). Admins get a quiet hint at most once a year (switchable off).
const sup_on = () => !!S.about && 'support_url' in S.about;
const SUP_KIND_LABEL = {server: N_('Server licence'), person: N_('Personal licence')};
function sup_badge(l) {
  return l ? `<span class="supbadge">${ic('heart', 's')}<b>${esc(tr('Supporter'))}</b><span>${esc(tr(SUP_KIND_LABEL[l.kind]))}</span></span>` : '';
}
// Settings > Account: the badge(s) under "Logged in as"
function sup_accountRow() {
  if (!sup_on()) return '';
  const a = S.about, b = sup_badge(a.supporter_me) + sup_badge(a.supporter);
  return b ? `<div class="row suprow" id="a-sup"><label>${tr('Supporter')}</label><span class="supbadges">${b}</span></div>` : '';
}
function sup_licRow(l, kind, can) {
  const date = l ? new Date(l.date + 'T12:00:00').toLocaleDateString(I18N.code || 'en') : '';
  return `<div class="row suplic"><label>${esc(tr(SUP_KIND_LABEL[kind]))}</label>${l
    ? `<span class="supbadges">${sup_badge(l)}<span class="muted">${esc(tr('since {0}', date))}${l.id ? ' · ' + esc(l.id) : ''}</span></span>${can ? `<button type="button" class="btn sm" data-sup="del" data-kind="${kind}">${esc(tr('Remove'))}</button>` : ''}`
    : `<span class="muted">${esc(kind === 'server' && !can ? tr('None yet (an admin enters it)') : tr('None yet'))}</span>`}</div>`;
}
// 2.144.0 D (#2158): the prices (once, VAT included) under the explanation
function sup_pricesHtml(p) {
  if (!p || !p.currency) return '';
  const fmt = n => { try { return new Intl.NumberFormat(I18N.code || 'en', {style: 'currency', currency: p.currency, maximumFractionDigits: 0}).format(n); } catch { return `${n} ${p.currency}`; } };
  const one = k => Number.isFinite(p[k]) ? `<span class="supprice" data-kind="${k}"><b>${esc(tr(SUP_KIND_LABEL[k]))}</b> ${esc(tr('{0} once', fmt(p[k])))}</span>` : '';
  const body = one('person') + one('server');
  return body ? `<div class="supprices">${body}</div><div class="shint">${esc(tr('Prices include VAT. Pay once, no subscription.'))}</div>` : '';
}
// Settings > Help: "Support Kalmido" under "About"
function sup_aboutHtml() {
  if (!sup_on()) return '';
  const a = S.about, adm = !!S.me?.is_admin;
  const url = a.support_url ? `<a class="btn sm pri" href="${esc(a.support_url)}" target="_blank" rel="noopener noreferrer">${ic('heart', 's')} ${esc(tr('Become a supporter'))}</a>` : '';
  return `<div id="s-sup"><h4 id="s-sup-h">${tr('Support Kalmido')}</h4>
    <div class="shint">${esc(tr('A supporter licence is voluntary and paid once. It unlocks nothing — everything in Kalmido stays free. It helps the further development and shows a small badge.'))}</div>
    ${sup_pricesHtml(a.support_prices)}
    ${url ? `<div class="row suplink"><label></label>${url}</div>` : ''}
    ${sup_licRow(a.supporter, 'server', adm)}${sup_licRow(a.supporter_me, 'person', true)}
    <div class="row supkey"><label for="s-supkey">${tr('Enter key')}</label><input id="s-supkey" autocomplete="off" spellcheck="false" maxlength="600" placeholder="KSUP1…" enterkeyhint="done"><button type="button" class="btn sm" data-sup="add">${esc(tr('Add'))}</button></div>
    ${adm ? `<label class="chkl"><input type="checkbox" id="s-supnudge" ${a.sup_nudge_on !== false ? 'checked' : ''}> ${tr('Remind me once a year')}</label><div class="shint">${esc(tr('A quiet hint for admins, only while there is no licence.'))}</div>` : ''}</div>`;
}
function sup_redraw() {
  const box = $('#s-sup'); if (box) box.outerHTML = sup_aboutHtml();
  const r = $('#a-sup'), nr = sup_accountRow();
  if (r) { if (nr) r.outerHTML = nr; else r.remove(); }
  sup_barSync();
}
async function sup_call(method, path, b) {
  const j = await api(method, path, b);
  S.about = {...S.about, ...j}; sup_redraw();
  return {skipped: []};
}
// one history step: undo and redo exchange the current and the previous key on the server
function sup_hist(kind, label) {
  const swap = () => sup_call('POST', `/api/supporter/${kind}/swap`, {});
  const e = histAdd({label, sett: true, undo: swap, redo: swap});
  if (typeof setSaved === 'function') setSaved(e);
}
async function sup_add() {
  const inp = $('#s-supkey'), key = (inp?.value || '').replace(/\s+/g, '');
  if (!key) { inp?.focus(); return; }
  // the key says its kind; the server checks the signature and the kind of the route
  let kind = 'person';
  try { kind = JSON.parse(atob(key.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).t === 'server' ? 'server' : 'person'; } catch { /* the server answers */ }
  if (kind === 'server' && !S.me?.is_admin) { toast(tr('This is a server licence: an admin enters it for the whole server.')); return; }
  try { await sup_call('PUT', `/api/supporter/${kind}`, {key}); } catch { return; }
  sup_hist(kind, tr('Added supporter licence'));
  toast(tr('Thank you for supporting Kalmido!'));
}
async function sup_del(kind) {
  try { await sup_call('DELETE', `/api/supporter/${kind}`); } catch { return; }
  sup_hist(kind, tr('Removed supporter licence'));
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-sup]'); if (!b) return;
  if (b.dataset.sup === 'add') sup_add();
  else if (b.dataset.sup === 'del') sup_del(b.dataset.kind);
  else if (b.dataset.sup === 'more') { sup_seen(); S.supBarOff = true; sup_barSync(); settingsModal('about'); setTimeout(() => $('#s-sup-h')?.scrollIntoView({block: 'start'}), 60); }
  else if (b.dataset.sup === 'hide') { sup_seen(); S.supBarOff = true; sup_barSync(); }
});
document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target?.id === 's-supkey') { e.preventDefault(); sup_add(); } });
document.addEventListener('change', async e => {
  if (e.target?.id !== 's-supnudge') return;
  const on = e.target.checked, put = v => sup_call('PATCH', '/api/supporter/nudge', {on: v});
  try { await put(on); } catch { e.target.checked = !on; return; }
  const h = histAdd({label: tr('Changed setting: {0}', tr('Remind me once a year')), sett: true, undo: () => put(!on), redo: () => put(on)});
  if (typeof setSaved === 'function') setSaved(h);
});
// the quiet yearly hint for admins (the server decides: S.about.sup_nudge); marked as shown the first time it appears
function sup_seen() {
  if (S.supSeen) return;
  S.supSeen = true;
  api('PATCH', '/api/supporter/nudge', {seen: true}).catch(() => {});
}
function sup_barSync() {
  const main = $('#main'); if (!main) return;
  let bar = $('#supbar');
  const on = sup_on() && (S.about.sup_nudge || S.supBarShown) && S.me?.is_admin && !S.me?.kid && !S.supBarOff
    && !S.about.supporter && !S.about.supporter_me;
  if (!on) { bar?.remove(); return; }
  if (!bar) { bar = document.createElement('div'); bar.id = 'supbar'; bar.className = 'annbar supbar'; bar.setAttribute('role', 'status'); const ab = $('#ntfask') || $('#annbar'); if (ab) ab.after(bar); else main.prepend(bar); }
  const html = `${ic('heart', 's')}<span class="annt">${esc(tr('Kalmido is free. If it helps you, a voluntary supporter licence helps its further development.'))}</span><button type="button" class="btn sm" data-sup="more">${esc(tr('Learn more'))}</button><button type="button" class="iconbtn" data-sup="hide" aria-label="${esc(tr('Hide this notice'))}" title="${esc(tr('Hide this notice'))}">${ic('x', 's')}</button>`;
  if (bar.innerHTML !== html) bar.innerHTML = html;
  S.supBarShown = true;  // stays for this session until hidden (the server already counts it as shown)
  sup_seen();
}
