/* Kalmido web client: moving data between the private space and an organisation (2.96.0, #1941).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.96.0 (#1941): "Move to another workspace…" -- ONE dialog for every kind of data that moves between the private space and an
// organisation, both ways (files and folders, wiki pages, tables ...). It names the source and the target in words, lets the
// person pick the target workspace and a place inside it, shows what the server's dry run found (duplicates, storage, shares
// and links that end, things that stay behind) and moves only after "Move". The caller passes:
//   what:  the things in words ("3 files", "“Plan”"), from: the source org_id (null = private),
//   places(to): async -> [{id, label}] the containers in workspace `to` (org_id | null); optional, '' = the top level,
//   check(to, place): async -> {notes: [text …], block: text | null} (the server's dry run: POST … {dry: 1}),
//   run(to, place): async -> the result of the move (the caller reloads and offers the undo: the same move back).
//   option: {label} (optional, 2.97.0 C #2049) -- one tick box; its state is the third argument of check and run.
// Resolves the result of run, or null when cancelled. Without an organisation there is no other workspace: callers show the
// action only when smv_can() (a person without an organisation never sees it; their private space is the only one).
const smv_can = from => wsOn() && wsOptions().filter(w => w !== 'all' && w !== wsOf({org_id: from})).length > 0;
const smv_ws = org => org ? 'org:' + org : 'private';
function smv_open({what, from = null, places = null, check, run, option = null}) {
  const tos = wsOptions().filter(w => w !== 'all' && w !== smv_ws(from));
  if (!tos.length) { toast(tr('There is no other workspace')); return Promise.resolve(null); }
  return new Promise(res => {
    let done = false, to = tos[0], place = '', seq = 0, blocked = true, opt = false;
    const toOrg = () => to === 'private' ? null : +to.slice(4);
    const md = modal(`<form class="smv" novalidate><h3 id="smv-t">${esc(tr('Move to another workspace'))}</h3>
      <p class="smv-what">${esc(what)}</p>
      <div class="smv-row"><span class="smv-l">${esc(tr('From|workspace'))}</span><span class="smv-from">${wsIcon(smv_ws(from))}<b>${esc(wsName(smv_ws(from)))}</b></span></div>
      <label class="smv-row"><span class="smv-l">${esc(tr('To|workspace'))}</span><select id="smv-to">${tos.map(w => `<option value="${w}">${esc(wsName(w))}</option>`).join('')}</select></label>
      ${places ? `<label class="smv-row"><span class="smv-l">${esc(tr('Into|place'))}</span><select id="smv-place"><option value="">${esc(tr('Top level'))}</option></select></label>` : ''}
      ${option ? `<label class="smv-row smv-opt chkl"><input type="checkbox" id="smv-opt"> ${esc(option.label)}</label>` : ''}
      <div class="smv-notes" aria-live="polite"></div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-smv="no">${esc(tr('Cancel'))}</button><button type="submit" class="btn pri" data-smv="yes" disabled>${esc(tr('Move'))}</button></div></form>`);
    md.classList.add('smv-dlg');
    md.setAttribute('aria-labelledby', 'smv-t');
    const fin = v => { if (done) return; done = true; res(v); if (md.isConnected) md.remove(); };
    const ok = $('[data-smv="yes"]', md), notes = $('.smv-notes', md);
    const dry = async () => {
      const n = ++seq; ok.disabled = true; blocked = true;
      notes.innerHTML = `<p class="muted">${esc(tr('Checking…'))}</p>`;
      let r; try { r = await check(toOrg(), place, opt); } catch { r = {block: tr('The check failed. Please try again.')}; }
      if (n !== seq || done) return;
      const ls = (r && r.notes) || [];
      notes.innerHTML = (r && r.block ? `<p class="smv-block">${ic('alert', 's')} ${esc(r.block)}</p>` : '')
        + (ls.length ? `<ul>${ls.map(t => `<li>${esc(t)}</li>`).join('')}</ul>` : '');
      blocked = !!(r && r.block); ok.disabled = blocked;
    };
    const fill = async () => {
      const sel = $('#smv-place', md); if (!sel) return dry();
      place = ''; sel.innerHTML = `<option value="">${esc(tr('Top level'))}</option>`;
      let ps = []; try { ps = await places(toOrg()); } catch { /* top level only */ }
      if (done) return;
      sel.insertAdjacentHTML('beforeend', (ps || []).slice(0, 300).map(p => `<option value="${esc(String(p.id))}">${esc(p.label)}</option>`).join(''));
      return dry();
    };
    $('#smv-to', md).addEventListener('change', e => { to = e.target.value; fill(); });
    $('#smv-place', md)?.addEventListener('change', e => { place = e.target.value; dry(); });
    $('#smv-opt', md)?.addEventListener('change', e => { opt = e.target.checked; dry(); });
    md.addEventListener('click', e => { if (e.target.closest('[data-smv="no"]')) fin(null); });
    $('form', md).addEventListener('submit', async e => {
      e.preventDefault(); if (blocked) return;
      ok.disabled = true;
      let r; try { r = await run(toOrg(), place, opt); } catch { ok.disabled = false; return; }
      fin(r || true);
    });
    onRemove(md, () => fin(null));
    fill();
  });
}
