// @ts-check
/* Kalmido web client: Settings > Account > Reset settings (2.593.0, #4590; server: POST /api/settings/reset in
   kalmido/accounts/settings.py). The dialog shows first what differs from the standard and goes back (the server's list of
   the account's settings plus what this device keeps for itself), resets only the look and comfort settings, and offers one
   undo: the server keeps the old values of the account, this device the ones it keeps locally (RS_UNDO). Afterwards the app
   loads again (every view, the sidebar and the appearance read the standard), the message with "Undo" follows the reload.
   Other devices take the account's standard at their next load. Classic script sharing the global scope (load order:
   lazyload.js, module settings). rawFetch, not api(): a reset never waits in the offline queue to run later. */
'use strict';

// the values this device keeps for itself (localStorage tasks.*): the appearance (LOOK_KEYS, dialogs.js) and the folds,
// view modes and remembered filters of this device; never the language, the sign-in, the cache or the offline queue
const RS_LOCAL = ['lookLocal', 'sideGroups', 'sideFold', 'sideOpenG', 'collapsed', 'sbbOpen', 'sbbFold', 'sbbUnfold', 'mdOpen', 'rings',
  'vmode', 'agband', 'tabbar', 'chatFloat', 'chatPos', 'calMode', 'tvMode', 'statsMode', 'timeScope', 'timePeriod', 'newsFilter',
  'newsKind', 'jobsFilter', 'favgripX'];  // 2.1150.0 (#6082): favgripX = the place of the favourites' grip on the tab bar
const RS_LOCAL_PRE = ['pw.', 'sort2.', 'lst.sort.', 'fcols.', 'lcw.'];
const RS_UNDO = 'tasks.rsUndoLocal', RS_TOAST = 'tasks.rsToast';

/** -> {localStorage key: raw value} of what this device keeps for itself and would go back */
function rs_localNow() {
  const ks = new Set([...LOOK_KEYS, ...RS_LOCAL].map(k => 'tasks.' + k));
  /** @type {Record<string, string>} */ const out = {};
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && (ks.has(k) || RS_LOCAL_PRE.some(p => k.startsWith('tasks.' + p)))) out[k] = /** @type {string} */ (localStorage.getItem(k));
    }
  } catch { /* private mode */ }
  return out;
}
// raw writes (not LS.set): the appearance is not sent to the account from here, the server holds its own copy
function rs_localPut(/** @type {Record<string, string | null>} */ vals) {
  try { for (const [k, v] of Object.entries(vals)) { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } } catch { /* private mode */ }
}

const rsHtml = () => S.me && !S.me.kid ? `<h4 id="s-rs-h">${tr('Reset settings')}</h4>
  <div class="shint">${tr('Puts the appearance, the sidebar, the views, notifications, modules and remembered filters back to the standard. Your data, account, sign-in, language and the organisation’s settings stay. You see the list first and can undo it once.')}</div>
  <div class="row"><button type="button" class="btn sm" data-act="reset-settings">${ic('undo', 's')} ${tr('Reset settings…')}</button></div>` : '';

function rs_listHtml(/** @type {any[]} */ items, /** @type {number} */ nLocal) {
  /** @type {Record<string, {label: string, rows: string[]}>} */ const by = {};
  for (const it of items) (by[it.group] ||= {label: it.group_label, rows: []}).rows.push(it.label);
  const groups = Object.values(by).map(g => `<li><b>${esc(g.label)}</b><ul>${g.rows.map(x => `<li>${esc(x)}</li>`).join('')}</ul></li>`);
  if (nLocal) groups.push(`<li><b>${esc(tr('This device'))}</b><ul><li>${esc(tr('Appearance, folds and filters kept on this device'))}</li></ul></li>`);
  return groups.length ? `<ul class="rslist" id="rs-list">${groups.join('')}</ul>` : `<div class="muted mhint" id="rs-list">${esc(tr('Everything is at the standard already.'))}</div>`;
}

async function rsOpen() {
  /** @type {any} */ let j;
  try { j = await rawFetch('POST', '/api/settings/reset', {dry_run: true}); } catch (/** @type {any} */ x) { toast(x?.message || tr('Only available online.')); return; }
  const loc = rs_localNow(), nLocal = Object.keys(loc).length, any = j.items.length > 0 || nLocal > 0;
  const md = /** @type {any} */ (modal(`<h3>${esc(tr('Reset settings?'))}</h3>
    <div class="shint keep">${esc(tr('These settings differ from the standard and go back:'))}</div>
    ${rs_listHtml(j.items, nLocal)}
    <div class="shint keep">${esc(tr('Stay as they are: your data, account, password, two-factor authentication, tokens and app passwords, the language and the settings of your organisations and office. Other devices take the standard when they load next time.'))}</div>
    <div class="aerr" role="alert" id="rs-err"></div>
    <div class="foot">${j.undo ? `<button type="button" class="btn" data-rs="undo" data-act="undo-the-last-reset">${ic('undo', 's')} ${tr('Undo the last reset')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-rs="go" data-act="reset" ${any ? '' : 'disabled'}>${tr('Reset')}</button></div>`));
  md.classList.add('rsdlg');
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('button[data-m], button[data-rs]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    b.disabled = true;
    try {
      if (b.dataset.rs === 'undo') await rs_undo(); else await rs_go(loc);
    } catch (/** @type {any} */ x) { $('#rs-err', md).textContent = x?.message || tr('Not possible'); b.disabled = false; }
  });
}

async function rs_go(/** @type {Record<string, string>} */ loc) {
  await flushSaves();  // a setting still on its way would land after the reset
  await rawFetch('POST', '/api/settings/reset', {});
  try { localStorage.setItem(RS_UNDO, JSON.stringify(loc)); } catch { /* private mode */ }
  rs_localPut(Object.fromEntries(Object.keys(loc).map(k => [k, null])));
  try { localStorage.setItem(RS_TOAST, JSON.stringify('reset')); } catch { /* private mode */ }
  location.reload();
}

async function rs_undo() {
  try { await rawFetch('POST', '/api/settings/reset', {undo: true}); } catch (/** @type {any} */ x) { if (x?.status !== 404) throw x; }
  /** @type {any} */ let loc = null;
  try { loc = JSON.parse(localStorage.getItem(RS_UNDO) || 'null'); } catch { loc = null; }
  if (loc && typeof loc === 'object') { rs_localPut(Object.fromEntries(Object.keys(rs_localNow()).map(k => [k, null]))); rs_localPut(loc); }
  try { localStorage.removeItem(RS_UNDO); localStorage.setItem(RS_TOAST, JSON.stringify('undo')); } catch { /* private mode */ }
  location.reload();
}

// after the reload (main.js): the message, with "Undo" right after a reset
function rs_after(/** @type {string} */ what) {
  if (what === 'undo') { toast(tr('Your previous settings are back')); return; }
  toast(tr('Settings reset to the standard'), () => { rs_undo().catch((/** @type {any} */ x) => toast(x?.message || tr('Not possible'))); }, 15000, tr('Undo'));
}

document.addEventListener('click', (/** @type {any} */ e) => {
  const b = e.target.closest?.('[data-act="reset-settings"]'); if (!b) return;
  rsOpen();
});
