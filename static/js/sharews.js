// 2.46.4 (#1737): the Share dialogs of lists, folders, calendars and address books say which workspace the object belongs to
// ("Belongs to: <organisation> (organisation)" / "Private") and grey out the people the server would refuse (not in the
// organisation) with the reason, before anything is sent. The server check (ws_fit_problem) stays the truth.
const shWsOn = () => typeof wsOn === 'function' && wsOn();
const shWsFit = (u, org) => !org || (u.orgs || []).includes(org);
// the line + the sentence below it; `change` (anchor -> void) makes the "Change workspace" link, null leaves it out
function shWsHtml(org, change) {
  if (!shWsOn()) return '';
  return `<div class="shwsl"><span class="shwsn">${esc(org ? tr('Belongs to: {0} (organisation)', wsLabel(org)) : tr('Belongs to: {0}', wsLabel(null)))}</span>${change ? ` <button type="button" class="linkbtn" data-shws>${tr('Change workspace')}</button>` : ''}</div>
    <div class="shint lhint keep shwsh">${esc(org ? tr('Only members of the organisation can be invited. An agent of the organisation sees it only if it is shared with that agent.') : tr('Only people you explicitly invite see it.'))}</div>`;
}
// fills the box (an element with class shws) and wires the link
function shWsFill(box, org, change) {
  if (!box) return;
  box.innerHTML = shWsHtml(org, change);
  box._shws = change;
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-shws]'); if (!b) return;
  const box = b.closest('.shws'); if (box?._shws) { e.preventDefault(); box._shws(b); }
});
// <option>s of the people select: those who do not fit the workspace are disabled with the reason
function shWsOptions(users, org, taken = []) {
  return users.filter(u => !taken.some(m => m.user_id === u.id)).map(u => {
    const ok = shWsFit(u, org);
    return `<option value="${u.id}" ${ok ? '' : 'disabled'}>${esc(u.display_name)}${ok ? '' : ' · ' + esc(tr('Not in the organisation'))}</option>`;
  }).join('');
}
// the first selectable person (a disabled first option must not be what the Share button sends)
function shWsPick(sel) { if (sel && sel.selectedOptions[0]?.disabled) { const o = [...sel.options].find(x => !x.disabled); sel.value = o ? o.value : ''; } }
