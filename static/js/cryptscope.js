// 2.46.1 (#1641): Settings > Administration > Encryption (and an organisation's box): two short lists, what the server
// key encrypts and what is stored as it is. The server sends both lists (kalmido/core/orgcrypt.py PM_CRYPT_CATS), already
// in the user's language, so nothing is kept twice here.
function pm_cryptScopeHtml(sc) {
  if (!sc || !Array.isArray(sc.encrypted)) return '';
  const ul = (h, xs, cls) => `<div class="pmcs ${cls}"><b>${esc(h)}</b><ul>${xs.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
  return `<div class="pmcsw">${ul(tr('Encrypted'), sc.encrypted, 'on')}${ul(tr('Not encrypted'), sc.plain || [], 'off')}</div>`;
}
