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
//   total: (optional, 2.147.1 B #2230) how many items run moves; from SMV_BAR on the dialog shows "x of n moved" as a bar and
//   passes onStep(done, total) as run's fourth argument (smv_post below moves in batches and calls it). While run works the
//   dialog always shows "Moving…" on the button (aria-busy, nothing else clickable).
// Resolves the result of run, or null when cancelled. Without an organisation there is no other workspace: callers show the
// action only when smv_can() (a person without an organisation never sees it; their private space is the only one).
const smv_can = from => wsOn() && wsOptions().filter(w => w !== 'all' && w !== wsOf({org_id: from})).length > 0;
// 2.147.1 B (#2230): move id lists in batches of SMV_CHUNK so the dialog can show the progress. Posts b with b[key] (ids | items)
// split up, returns the merged answer ({moved, org_was, to, count, shares}). A later batch that fails keeps what moved so far:
// the answer then has failed = the error text (api() already toasted it) and the caller offers the undo for the moved part.
const SMV_CHUNK = 20, SMV_BAR = 20;
async function smv_post(url, b, key, onStep) {
  const all = b[key] || [], out = {moved: [], count: 0, shares: 0};
  for (let i = 0; i < all.length || !i; i += SMV_CHUNK) {
    let r;
    try { r = await api('POST', url, {...b, [key]: all.slice(i, i + SMV_CHUNK)}); }
    catch (x) { if (!out.moved.length) throw x; out.failed = x.message || 'error'; break; }
    out.moved.push(...(r.moved || [])); out.org_was = r.org_was; out.to = r.to;
    out.count += r.count || 0; out.shares += +r.shares || 0;
    if (onStep) onStep(Math.min(i + SMV_CHUNK, all.length), all.length);
  }
  return out;
}
// the undo label of a move: "Moved to X", or how far a failed one got
const smv_label = (r, total) => r.failed ? tr('Only {0} of {1} moved to {2}', r.moved.length, total, wsName(r.to)) : tr('Moved to {0}', wsName(r.to));
const smv_ws = org => org ? 'org:' + org : 'private';
// 2.361.2 (#2923): a member asks the admins of an organisation for something they brought in or made ({org, kind, id} from the
// server's 403 / dry run); an admin releases it with one click, then the usual move takes it into the private space
async function oor_ask(req) {
  if (!req?.org) return false;
  try {
    const r = await api('POST', `/api/orgs/${req.org}/out-requests`, {kind: req.kind, id: req.id});
    toast(r.again ? (r.state === 'approved' ? tr('Already released: move it into your private space now') : tr('Already asked: the admins have not decided yet'))
      : tr('Asked: the admins of the organisation decide. You hear about it in the News.'), null, 6000);
    return true;
  } catch { return false; /* api() showed it */ }
}
function smv_open({what, from = null, places = null, check, run, option = null, total = 0, only = null}) {
  const tos = wsOptions().filter(w => w !== 'all' && w !== smv_ws(from) && (!only || only.includes(w)));  // 2.356.0 A (#2926): only = allowed targets
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
      ${total >= SMV_BAR ? `<div class="smv-prog" hidden><div class="smv-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${total}" aria-valuenow="0" aria-label="${esc(tr('Progress'))}"><i></i></div><p class="smv-pt" aria-live="polite"></p></div>` : ''}
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-smv="no">${esc(tr('Cancel'))}</button><button type="submit" class="btn pri" data-smv="yes" disabled>${esc(tr('Move'))}</button></div></form>`);
    md.classList.add('smv-dlg');
    md.setAttribute('aria-labelledby', 'smv-t');
    const fin = v => { if (done) return; done = true; res(v); if (md.isConnected) md.remove(); };
    const ok = $('[data-smv="yes"]', md), notes = $('.smv-notes', md);
    const dry = async () => {
      const n = ++seq; ok.disabled = true; blocked = true;
      notes.innerHTML = `<p class="muted">${esc(tr('Checking…'))}</p>`;
      let r; try { r = await check(toOrg(), place, opt); } catch (x) { r = {block: x?.data?.out_request ? x.message : tr('The check failed. Please try again.'), out_request: x?.data?.out_request}; }  // 2.361.2 (#2923)
      if (n !== seq || done) return;
      const ls = (r && r.notes) || [];
      notes.innerHTML = (r && r.block ? `<p class="smv-block">${ic('alert', 's')} ${esc(r.block)}</p>` : '')
        + (r && r.block && r.out_request ? `<p class="smv-ask"><button type="button" class="btn sm" data-smv="ask">${esc(tr('Ask an admin to release it'))}</button></p>` : '')  // 2.361.2 (#2923)
        + (ls.length ? `<ul>${ls.map(t => `<li>${esc(t)}</li>`).join('')}</ul>` : '');
      const ask = $('[data-smv="ask"]', notes);
      if (ask) ask.onclick = async () => { ask.disabled = true; if (await oor_ask(r.out_request)) fin(null); else ask.disabled = false; };
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
      ok.disabled = true; blocked = true;
      const label = ok.textContent, no = $('[data-smv="no"]', md), prog = $('.smv-prog', md), bar = $('.smv-bar', md);
      ok.textContent = tr('Moving…'); ok.setAttribute('aria-busy', 'true'); no.disabled = true;
      const step = (n, t) => {
        if (!prog) return;
        prog.hidden = false; bar.setAttribute('aria-valuenow', String(n)); $('i', bar).style.transform = `scaleX(${t ? n / t : 0})`;
        $('.smv-pt', prog).textContent = tr('{0} of {1} moved', n, t);
      };
      step(0, total);
      let r; try { r = await run(toOrg(), place, opt, step); } catch { ok.textContent = label; ok.removeAttribute('aria-busy'); no.disabled = false; ok.disabled = false; blocked = false; if (prog) prog.hidden = true; return; }
      fin(r || true);
    });
    onRemove(md, () => fin(null));
    fill();
  });
}
