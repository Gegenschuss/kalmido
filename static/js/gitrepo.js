// @ts-check
/* Kalmido web client: the repository editor of a project list / folder (2.2.0 #271, 2.33.0 #934), moved out of git.js and
   loaded when the list dialog or the folder settings open it (2.149.0 F, #2518; lazyload.js module gitrepo, stand-ins
   repoWire / folderRepoModal). What the task rows, the task panel and the chat draw stays in git.js (loaded at start).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const GIT_PROV = [['github', 'GitHub'], ['gitlab', 'GitLab'], ['gitea', 'Gitea / Forgejo'], ['bitbucket', 'Bitbucket Cloud']];  // 2.18.0 (#408): + GitLab, Bitbucket
// 2.18.0: the provider of an address on a cloud host is unambiguous (other hosts: the select)
const gitHostProv = u => { const m = /^https?:\/\/(?:www\.)?(github\.com|gitlab\.com|bitbucket\.org)\//i.exec(String(u || '').trim()); return m ? {'github.com': 'github', 'gitlab.com': 'gitlab', 'bitbucket.org': 'bitbucket'}[m[1].toLowerCase()] : ''; };
const GIT_BASE_PH = {github: N_('empty = github.com'), gitlab: N_('empty = gitlab.com'), bitbucket: N_('empty = bitbucket.org')};
const GIT_TOK_PH = {gitlab: N_('read_api is enough; empty for a public project'), bitbucket: N_('access token, or user:app password; empty for a public repository')};
// 2.33.0 (#934): folder = the folder dialog's "Repository" (GET / POST /api/folders/repos); a list shows the repositories it
// takes from its folder below its own ones, with "Switch off for this list" / "Use it again" (list owner / admins)
function repoWire(md, lid, folder) {
  const box = $('#l-repos', md); if (!box) return;
  const isProj = () => !!folder || listById(lid)?.kind === 'project';
  let j = null, edit = null, secret = null, errUrl = null, errHdr = null;
  const provSel = `<select id="rp-prov" aria-label="${esc(tr('Provider'))}">${GIT_PROV.map(([k, n]) => `<option value="${k}">${n}</option>`).join('')}</select>`;
  const draw = () => {
    if (!md.isConnected) return;
    if (!j) { box.innerHTML = `<div class="muted mhint">${tr('Loading…')}</div>`; return; }
    const rows = j.repos.map(r => `<div class="mrow reporow" data-rid="${r.id}">${ic('git', 's')}<span class="n"><a href="${esc(httpUrl(r.web_url))}" target="_blank" rel="noopener noreferrer">${esc(r.full_name)}</a>
        <span class="muted rpm">${esc(GIT_PROV.find(x => x[0] === r.provider)?.[1] || r.provider)}${r.default_branch ? ' · ' + esc(r.default_branch) : ''}${j.may ? ' · ' + esc(r.token ? tr('Token set') : tr('No token')) + (r.hook ? ' · ' + esc(tr('Webhook on')) : '') : ''}</span>
        <span class="rst rst-${esc(r.status)}">${esc(r.status === 'error' ? r.error : r.status === 'new' ? tr('Waiting for the first check') : tr('Checked {0}', relTime(r.polled_at)))}</span></span>
        <button class="iconbtn" data-rp="refresh" title="${esc(tr('Check the repository now'))}" aria-label="${esc(tr('Check the repository now'))}">${ic('sync', 's')}</button>
        ${j.may ? `<button class="iconbtn" data-rp="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots', 's')}</button>` : ''}</div>
      ${edit === r.id ? `<div class="mrow repoedit"><input id="rp-tok2" type="password" autocomplete="new-password" placeholder="${esc(tr('New access token (empty = remove)'))}" aria-label="${esc(tr('Access token'))}"><button class="btn sm" data-rp="tok-save">${tr('Save')}</button></div>` : ''}
      ${secret && secret.id === r.id ? `<div class="shint lhint rpsec">${esc(tr('Webhook: payload URL {0}, content type JSON, secret (shown only now):', r.hook_url))} <code>${esc(secret.s)}</code></div>` : ''}`).join('');
    const add = j.may && j.repos.length < j.max ? `<div class="repoadd">
        <div class="row"><label for="rp-prov">${tr('Provider')}</label>${provSel}</div>
        <div class="shint lhint" id="rp-phint" hidden></div>
        <div class="row"><label for="rp-base">${tr('Server')}</label><input id="rp-base" type="url" inputmode="url" autocomplete="off" placeholder="${esc(tr('empty = github.com'))}"></div>
        <div class="row"><label for="rp-name">${tr('Repository')}</label><input id="rp-name" autocomplete="off" aria-describedby="rp-cerr" placeholder="${esc(tr('owner/name or its web address'))}"></div>
        <div class="shint keep lhint rpself" id="rp-self" hidden>${esc(tr('This looks like a self-hosted server: pick its provider (GitLab, Gitea / Forgejo or Bitbucket) above.'))}</div>
        <div class="row"><label for="rp-tok">${tr('Access token')}</label><input id="rp-tok" type="password" autocomplete="new-password" placeholder="${esc(tr('read-only is enough; empty for a public repository'))}" ${j.key ? '' : 'disabled'}></div>
        ${j.key ? '' : `<div class="shint keep lhint">${esc(tr('Set KALMIDO_SECRET_KEY on the server to store repository tokens (32 random bytes, base64)'))}</div>`}
        <div class="rpcerr" id="rp-cerr" role="alert"></div>
        <div class="row rprow"><span class="spacer"></span><button class="btn sm pri" data-rp="add">${ic('plus', 's')} ${tr('Connect')}</button></div></div>` : '';
    box.innerHTML = rows + (isProj() ? add : `<div class="muted mhint">${tr('Switch on progress and status for this project to connect a repository')}</div>`)
      + (!folder && !j.may && !j.repos.length && isProj() ? `<div class="muted mhint">${tr('The project owner and project admins connect repositories.')}</div>` : '')
      + (folder ? folderSumHtml() : foldHtml() + verHtml() + errHookHtml());
  };
  // 2.151.0 A (#2558): which field holds the package / target version (compared with the repository's version tags)
  const verHtml = () => {
    const v = j.version_field; if (!v || listById(lid)?.kind !== 'project' || !(j.repos.length || j.folder_repos?.length)) return '';
    const cur = v.setting === 'auto' ? 'auto' : v.setting === 'off' ? 'off' : String(v.setting);
    const autoLbl = v.setting === 'auto' && v.field ? tr('Automatic ({0})', v.field.name) : tr('Automatic');
    const ctl = j.may ? `<select id="rp-ver" aria-label="${esc(tr('Version field'))}"><option value="auto"${cur === 'auto' ? ' selected' : ''}>${esc(autoLbl)}</option><option value="off"${cur === 'off' ? ' selected' : ''}>${esc(tr('Off'))}</option>${v.fields.map(f => `<option value="${f.id}"${cur === String(f.id) ? ' selected' : ''}>${esc(f.name)}</option>`).join('')}</select>`
      : `<span class="muted">${esc(v.field ? v.field.name : tr('Off'))}</span>`;
    return `<div class="row rpver"><label for="rp-ver">${tr('Version field')}</label>${ctl}</div><div class="shint lhint">${esc(tr('A task whose version is already released but which is still open gets a hint. Automatic: a text field named Package, Version or Release.'))}</div>`;
  };
  // 2.33.0 (#934): the repositories this list takes from its folder
  const repoNames = rs => rs.map(r => r.full_name).join(', ');
  const foldHtml = () => {
    const fs = j.folder, rs = j.folder_repos || []; if (!fs?.inherited || !rs.length || listById(lid)?.kind !== 'project') return '';
    const st = fs.own ? tr('Not used: this project has its own repository') : fs.off ? tr('Switched off for this project') : tr('Used by this project');
    const ctl = !j.may || fs.own ? '' : `<button class="btn sm" data-rp="fold-use" data-use="${fs.off ? 1 : 0}">${esc(fs.off ? tr('Use it again') : tr('Switch off for this project'))}</button>`;
    return `<div class="mrow reporow repofold">${ic('folder', 's')}<span class="n"><b>${esc(fs.folder ? tr('From the folder “{0}”', fDisp(fs.folder)) : tr('From its folder'))}</b><span class="muted rpm">${esc(repoNames(rs))}</span><span class="rst">${esc(st)}</span></span>${ctl}</div>`;
  };
  const folderSumHtml = () => {
    const ls = (j.lists || []).filter(l => l.project), use = ls.filter(l => l.uses && l.via === folder), inh = j.inherited;
    const why = l => l.own ? tr('has its own repository') : l.off ? tr('switched off') : l.via && l.via !== folder ? tr('uses the subfolder “{0}”', fDisp(l.via)) : '';
    const not = ls.filter(l => !(l.uses && l.via === folder) && (j.repos.length || inh));
    return (inh && !j.repos.length ? `<div class="mrow reporow repofold">${ic('folder', 's')}<span class="n"><b>${esc(tr('From the folder “{0}”', fDisp(inh.folder)))}</b><span class="muted rpm">${esc(repoNames(inh.repos))}</span></span></div>` : '')
      + (j.repos.length ? `<div class="shint keep lhint" role="status">${esc(tr('Used by {0} of {1} projects with progress and status in this folder, also by new ones.', use.length, ls.length))}</div>` : '')
      + (j.repos.length && not.length ? `<ul class="rpnot muted">${not.map(l => `<li>${esc(l.name)}${why(l) ? ': ' + esc(why(l)) : ''}</li>`).join('')}</ul>` : '')
      + (!ls.length ? `<div class="muted mhint">${tr('No projects with progress and status in this folder yet: projects that switch it on use it.')}</div>` : '');
  };
  // 2.18.0 (#408 "Software 2" F): error reports -> bug tickets (a secret webhook URL, shown once; owner / list admins)
  const errHookHtml = () => {
    const eh = j.errors; if (!eh || listById(lid)?.kind !== 'project' || (!eh.may && !eh.on)) return '';
    const st = eh.on ? [tr('On'), tr('{0} received', eh.received || 0), eh.open ? trn('{0} open ticket', '{0} open tickets', eh.open) : '', eh.last_at ? tr('last {0}', relTime(eh.last_at)) : ''].filter(Boolean).join(' · ') : tr('Off');
    const ctl = !eh.may ? '' : eh.on ? `<button class="iconbtn" data-rp="err-menu" title="${esc(tr('Error reports'))}: ${esc(tr('More'))}" aria-label="${esc(tr('Error reports'))}: ${esc(tr('More'))}">${ic('dots', 's')}</button>`
      : `<button class="btn sm" data-rp="err-on">${tr('Turn on')}</button>`;
    return `<div class="errhook" id="rp-err"><div class="mrow reporow errrow">${ic('bug', 's')}<span class="n"><b>${tr('Error reports')}</b><span class="muted rpm">${esc(st)}</span></span>${ctl}</div>
      <div class="shint lhint">${tr('Sentry or any service that sends JSON: a new error becomes a bug ticket, the same error again only counts up at its open ticket.')}</div>
      ${errUrl && errHdr ? `<div class="shint lhint rpsec" role="status">${esc(tr('Webhook URL:'))} <code>${esc(errHdr.hook_url)}</code><br>${esc(tr('Header (shown only now, keep it secret):'))} <code>${esc('Authorization: Bearer ' + errHdr.token)}</code> <button class="linkbtn" data-rp="err-copy" data-v="h">${ic('copy', 's')} ${tr('Copy')}</button></div>
      <div class="shint lhint" role="status">${esc(tr('Services that cannot send a header (Sentry): this URL with the token works as before:'))} <code>${esc(errUrl)}</code> <button class="linkbtn" data-rp="err-copy">${ic('copy', 's')} ${tr('Copy')}</button></div>`
      : errUrl ? `<div class="shint lhint rpsec" role="status">${esc(tr('Webhook URL (shown only now, keep it secret):'))} <code>${esc(errUrl)}</code> <button class="linkbtn" data-rp="err-copy">${ic('copy', 's')} ${tr('Copy')}</button></div>` : ''}</div>`;  // 2.138.4 C (#2381): the header form first
  };
  const errSet = async state => {
    let x; try { x = await api('PATCH', `/api/lists/${lid}/error-hook`, {state}); } catch { return; }
    errUrl = x.url || null; errHdr = x.hook_url && x.token ? {hook_url: x.hook_url, token: x.token} : null; j.errors = x; draw();
    (errUrl ? $('#rp-err [data-rp="err-copy"]', box) : $('#rp-err [data-rp="err-on"]', box))?.focus();
  };
  const provHint = () => {
    const pv = $('#rp-prov', box)?.value || 'github', h = $('#rp-phint', box);
    const base = $('#rp-base', box), tok = $('#rp-tok', box);
    if (base) base.placeholder = GIT_BASE_PH[pv] ? tr(GIT_BASE_PH[pv]) : 'https://git.example.com';
    if (tok && j?.key) tok.placeholder = tr(GIT_TOK_PH[pv] || N_('read-only is enough; empty for a public repository'));
    const txt = pv === 'bitbucket' ? tr('Bitbucket Cloud only: Bitbucket Server / Data Center is not supported.')
      : pv === 'gitlab' ? tr('gitlab.com or your own GitLab server; groups with subgroups work (group/sub/project).') : '';
    if (h) { h.textContent = txt; h.hidden = !txt; }
  };
  const reload = async () => {
    try { j = await api('GET', folder ? '/api/folders/repos?folder=' + encodeURIComponent(folder) : `/api/lists/${lid}/repos`); if (folder) j.may = true; }
    catch { j = {repos: [], may: false, key: true, project: false, max: 0}; }
    draw();
  };
  box.addEventListener('click', async e => {
    const b = e.target.closest('[data-rp]'); if (!b) return;
    const rid = +(b.closest('[data-rid]')?.dataset.rid || b.closest('.repoedit')?.previousElementSibling?.dataset.rid || edit || 0);
    const k = b.dataset.rp;
    if (k === 'add') {
      const body = {provider: $('#rp-prov', box).value, base_url: $('#rp-base', box).value.trim(), repo: $('#rp-name', box).value.trim(), token: $('#rp-tok', box).value.trim()};
      if (!body.repo) { need($('#rp-name', box)); return; }
      b.disabled = true;
      // 2.18.0 review (R11): a failed connect says why next to the fields (not only in a toast that is gone in seconds)
      const ce = $('#rp-cerr', box), nm = $('#rp-name', box);
      ce.textContent = ''; nm.removeAttribute('aria-invalid');
      try { await rawFetch('POST', folder ? '/api/folders/repos' : `/api/lists/${lid}/repos`, folder ? {...body, folder} : body); toast(tr('Repository connected')); }
      catch (er) {
        b.disabled = false; if (!md.isConnected) return;
        ce.textContent = er instanceof Offline ? tr('Offline: only works again with a connection') : er.message === 'auth' ? '' : er.message;
        nm.setAttribute('aria-invalid', 'true'); nm.focus();
        return;
      }
      await reload(); await load(); render();
    } else if (k === 'fold-use') {
      try { await api('PUT', `/api/lists/${lid}/folder-repo`, {use: b.dataset.use === '1'}); } catch { return; }
      toast(b.dataset.use === '1' ? tr('The project uses the folder’s repository again') : tr('Switched off for this project'));
      await reload(); await load(); render(); $('#l-repos [data-rp="fold-use"]', md)?.focus();
    } else if (k === 'err-on') {
      await errSet('on');
    } else if (k === 'err-copy') {
      const v = b.dataset.v === 'h' && errHdr ? 'Authorization: Bearer ' + errHdr.token : errUrl || '';  // 2.138.4 C (#2381)
      try { await navigator.clipboard.writeText(v); toast(tr('Copied')); } catch { toast(v); }
    } else if (k === 'err-menu') {
      menu(b, [{label: tr('New URL (the old one stops working)'), icon: 'sync', fn: () => errSet('rotate')},
        '-', {label: tr('Turn error reports off'), icon: 'x', cls: 'flag-5', fn: () => errSet('off')}]);
    } else if (k === 'refresh') {
      try { await api('POST', `/api/repos/${rid}/refresh`); toast(tr('Checking the repository …')); } catch { /* shown */ }
      setTimeout(reload, 4000);
    } else if (k === 'tok-save') {
      try { await api('PATCH', `/api/repos/${edit}`, {token: $('#rp-tok2', box).value.trim()}); toast(tr('Saved')); } catch { return; }
      edit = null; await reload();
    } else if (k === 'menu') {
      const r = j.repos.find(x => x.id === rid); if (!r) return;
      menu(b, [{label: tr('Change access token'), icon: 'lock', fn: () => { edit = rid; secret = null; draw(); $('#rp-tok2', box)?.focus(); }},
        r.hook ? {label: tr('Turn the webhook off'), icon: 'x', fn: async () => { try { await api('PATCH', `/api/repos/${rid}`, {hook: 'off'}); } catch { return; } secret = null; await reload(); }}
          : {label: tr('Turn the webhook on (optional)'), icon: 'zap', title: tr('Only when the Git server can reach this server: it then triggers a check at once'), fn: async () => { let x; try { x = await api('PATCH', `/api/repos/${rid}`, {hook: 'on'}); } catch { return; } secret = {id: rid, s: x.hook_secret}; await reload(); }},
        '-', {label: tr('Remove the repository'), icon: 'trash', cls: 'flag-5', fn: async () => {
          if (!await askConfirm(tr('Remove {0}?', r.full_name), tr('The links to pull requests and commits disappear from the tasks. Completed tasks stay completed.'), {ok: tr('Remove'), danger: true})) return;
          try { await api('DELETE', `/api/repos/${rid}`); } catch { return; }
          await reload(); await load(); render(); }}]);
    }
  });
  // 2.18.0 review (R11): an address on another server while the provider is still GitHub (the default) -> a hint to pick
  // the provider of the self-hosted server (GitHub Enterprise keeps working: the hint never blocks)
  const selfHint = () => {
    const h = $('#rp-self', box); if (!h) return;
    const host = v => { const m = /^https?:\/\/([^/\s]+)/i.exec(String(v || '').trim()); return m ? m[1].toLowerCase().replace(/^www\./, '') : ''; };
    const hs = [host($('#rp-name', box)?.value), host($('#rp-base', box)?.value)].filter(Boolean);
    h.hidden = !(($('#rp-prov', box)?.value || 'github') === 'github' && hs.some(x => !/^(github\.com|gitlab\.com|bitbucket\.org)$/.test(x)));
  };
  box.addEventListener('change', async e => {
    if (e.target.id === 'rp-prov') { provHint(); selfHint(); }
    if (e.target.id === 'rp-ver') {  // 2.151.0 A (#2558)
      const v = e.target.value;
      try { j.version_field = await api('PUT', `/api/lists/${lid}/repos/version-field`, {field: /^\d+$/.test(v) ? +v : v}); toast(tr('Saved')); } catch { /* shown */ }
      draw(); $('#rp-ver', box)?.focus(); await load(); render();
    }
  });
  box.addEventListener('input', e => {  // 2.18.0: a cloud address picks its provider
    if (e.target.id === 'rp-name' || e.target.id === 'rp-base') { const ce = $('#rp-cerr', box); if (ce?.textContent) { ce.textContent = ''; $('#rp-name', box)?.removeAttribute('aria-invalid'); } }
    if (e.target.id === 'rp-base') { selfHint(); return; }
    if (e.target.id !== 'rp-name') return;
    const pv = gitHostProv(e.target.value), sel = $('#rp-prov', box);
    if (pv && sel && sel.value !== pv) { sel.value = pv; provHint(); }
    selfHint();
  });
  reload();
}
// 2.33.0 (#934): folder settings > Repository: one connection for every project list in the folder (only its owner)
function folderRepoModal(f, opt = {}) {  // 2.37.0 (#1158): opt.back = a sub-dialog of the folder settings (returns it)
  const md = modal(`<h3>${ic('git', 's')} ${esc(tr('Repository of the folder “{0}”', fDisp(f)))}</h3>
    <div class="shint lhint">${tr('Every project with progress and status in this folder and its subfolders uses it, also new ones: #123 and “fixes #123” in commits and pull requests find the tasks of all these projects. A project can switch it off or connect its own repository; a subfolder can have its own.')}</div>
    <div class="members" id="l-repos"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${opt.back ? ic('back', 's') + ' ' + tr('Back') : tr('Done')}</button></div>`);
  md.addEventListener('click', e => { if (/** @type {HTMLElement} */ (e.target).closest('[data-m="close"]')) md.remove(); });
  repoWire(md, 0, f);
  return md;
}

