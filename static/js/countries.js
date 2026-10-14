// 2.40.0 (#1372): the country of a client / the company / an import row as a choice instead of a typed ISO code. The names
// come from the browser in the app's language (Intl.DisplayNames, no own catalogue); stored is the ISO 3166-1 alpha-2 code
// (the server accepts only these, UK -> GB, EL -> GR). Germany, Austria and Switzerland stand on top; typing "Öst" or "AT"
// finds Austria. Empty = Germany, shown as "Germany (default)". A stored value that is no code is shown marked, not changed.
// ctyField(id, code, {attrs, dis, label}) -> the HTML: a hidden <input id> (the value, with attrs such as data-clb="country")
// and a search field with its list; picking fires input + change on the hidden field (the forms read it like before).
const CTY_CODES = ('AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF ' +
  'CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH ' +
  'GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW ' +
  'KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG ' +
  'NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN ' +
  'SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ' +
  'ZA ZM ZW').split(' ');
const CTY_TOP = ['DE', 'AT', 'CH'];
const CTY_FIX = {UK: 'GB', EL: 'GR'};
const CTYS = {names: null, lang: ''};  // (CTY is taken by listedit.js)
function ctyNames() {
  const lg = typeof LOCALE === 'function' ? LOCALE() : 'en';
  if (CTYS.names && CTYS.lang === lg) return CTYS.names;
  let dn = null;
  try { dn = new Intl.DisplayNames([lg, 'en'], {type: 'region'}); } catch { dn = null; }
  const m = {};
  for (const c of CTY_CODES) { let n = c; try { n = (dn && dn.of(c)) || c; } catch { n = c; } m[c] = n; }
  CTYS.names = m; CTYS.lang = lg;
  return m;
}
const ctyFold = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ß/g, 'ss');
const ctyCode = v => { const s = String(v || '').trim().toUpperCase(); return CTY_FIX[s] || s; };
const ctyValid = v => !v || CTY_CODES.includes(ctyCode(v));
const ctyName = code => code ? `${ctyNames()[code] || code} (${code})` : '';
// [[code, label]] in the order of the list: the three on top, then every country by name; q filters by name or code
function ctyList(q) {
  const n = ctyNames(), f = ctyFold(q).trim();
  const rest = CTY_CODES.filter(c => !CTY_TOP.includes(c)).sort((a, b) => n[a].localeCompare(n[b], typeof LOCALE === 'function' ? LOCALE() : undefined));
  const all = [...CTY_TOP, ...rest];
  if (!f) return all;
  const up = f.toUpperCase();
  const hit = all.filter(c => c === up || ctyFold(n[c]).includes(f) || (f.length <= 3 && c.startsWith(up)));
  return hit.sort((a, b) => (b === up) - (a === up) || ctyFold(n[b]).startsWith(f) - ctyFold(n[a]).startsWith(f));
}
function ctyField(id, code, o = {}) {
  const v = String(code || '').trim(), ok = ctyValid(v);
  const shown = v ? (ok ? ctyName(ctyCode(v)) : v) : '';
  return `<span class="cty ${ok ? '' : 'bad'}" data-cty><input type="hidden" id="${esc(id)}" value="${esc(v)}" ${o.attrs || ''}>
    <input type="text" class="ctyq" id="${esc(id)}-q" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${esc(id)}-l" autocomplete="off" spellcheck="false"
      aria-label="${esc(o.label || tr('Country'))}" value="${esc(shown)}" placeholder="${esc(tr('Germany (default)'))}" ${o.dis || ''}>
    <ul class="ctyl" id="${esc(id)}-l" role="listbox" hidden></ul>
    ${ok ? '' : `<small class="ctybad" role="alert">${esc(tr('“{0}” is no country code: please choose the country', v))}</small>`}</span>`;
}
function ctyOpen(q, filter) {
  const box = q.closest('[data-cty]'), ul = box && $('.ctyl', box); if (!ul) return;
  const codes = ctyList(filter ? q.value : '');
  const cur = ctyCode($('input[type=hidden]', box).value);
  ul.innerHTML = codes.length ? codes.map((c, i) => `<li role="option" id="${esc(q.id)}-o${i}" data-code="${c}" aria-selected="${c === cur}" class="${c === cur ? 'on' : ''}${i === CTY_TOP.length - 1 && !filter ? ' sep' : ''}">${esc(ctyNames()[c])} <span class="muted">${c}</span></li>`).join('')
    : `<li class="muted" aria-disabled="true">${esc(tr('Nothing matches.'))}</li>`;
  ul.hidden = false; q.setAttribute('aria-expanded', 'true');
  const on = $('li.on', ul); if (on && !filter) on.scrollIntoView?.({block: 'nearest'});
}
function ctyClose(box, restore) {
  const ul = $('.ctyl', box), q = $('.ctyq', box), h = $('input[type=hidden]', box);
  if (ul) ul.hidden = true;
  if (q) { q.setAttribute('aria-expanded', 'false'); q.removeAttribute('aria-activedescendant'); }
  if (restore && q && h) q.value = h.value ? (ctyValid(h.value) ? ctyName(ctyCode(h.value)) : h.value) : '';
}
function ctyPick(box, code) {
  const h = $('input[type=hidden]', box), q = $('.ctyq', box);
  h.value = code; q.value = ctyName(code);
  box.classList.remove('bad'); $('.ctybad', box)?.remove();
  ctyClose(box);
  h.dispatchEvent(new Event('input', {bubbles: true})); h.dispatchEvent(new Event('change', {bubbles: true}));
}
document.addEventListener('focusin', e => { if (e.target.classList?.contains('ctyq')) { e.target.select?.(); ctyOpen(e.target, false); } });
document.addEventListener('input', e => { if (e.target.classList?.contains('ctyq')) { e.stopPropagation(); ctyOpen(e.target, true); } }, true);
document.addEventListener('mousedown', e => { const li = e.target.closest?.('.ctyl li[data-code]'); if (li) e.preventDefault(); });  // keep the focus
document.addEventListener('click', e => {
  const li = e.target.closest?.('.ctyl li[data-code]');
  if (li) { ctyPick(li.closest('[data-cty]'), li.dataset.code); return; }
});
document.addEventListener('focusout', e => {
  const q = e.target; if (!q.classList?.contains('ctyq')) return;
  const box = q.closest('[data-cty]');
  setTimeout(() => {
    if (box.contains(document.activeElement)) return;
    if (!q.value.trim()) { const h = $('input[type=hidden]', box); if (h.value) { h.value = ''; box.classList.remove('bad'); $('.ctybad', box)?.remove(); h.dispatchEvent(new Event('input', {bubbles: true})); h.dispatchEvent(new Event('change', {bubbles: true})); } ctyClose(box); return; }
    const one = ctyList(q.value);  // a typed code or a unique name counts as the choice
    if (one.length === 1 || (one[0] && one[0] === ctyCode(q.value))) { if (one[0] !== ctyCode($('input[type=hidden]', box).value)) ctyPick(box, one[0]); else ctyClose(box, true); return; }
    ctyClose(box, true);
  }, 120);
});
document.addEventListener('keydown', e => {
  const q = e.target; if (!q.classList?.contains('ctyq')) return;
  const box = q.closest('[data-cty]'), ul = $('.ctyl', box);
  if (e.key === 'Escape' && !ul.hidden) { e.preventDefault(); e.stopPropagation(); ctyClose(box, true); return; }
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Enter') return;
  if (ul.hidden) { if (e.key !== 'Enter') { e.preventDefault(); ctyOpen(q, false); } return; }
  const opts = [...ul.querySelectorAll('li[data-code]')]; if (!opts.length) return;
  let i = opts.findIndex(li => li.classList.contains('act'));
  if (e.key === 'Enter') { e.preventDefault(); ctyPick(box, (opts[i] || opts[0]).dataset.code); return; }
  e.preventDefault();
  i = e.key === 'ArrowDown' ? Math.min(opts.length - 1, i + 1) : Math.max(0, i - 1);
  opts.forEach(li => li.classList.remove('act')); opts[i].classList.add('act');
  q.setAttribute('aria-activedescendant', opts[i].id); opts[i].scrollIntoView?.({block: 'nearest'});
});
