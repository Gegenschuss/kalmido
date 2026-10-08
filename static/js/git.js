/* Kalmido web client: Git integration of project lists: repositories, pull requests + CI, agents' merge requests.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- 2.2.0 (#271): Git integration. The list dialog of a project list connects GitHub / Gitea / Forgejo repositories
// (owner + list admins); the task panel shows the linked pull requests (state, CI) and commits ("Code", before the
// comments), rows a chip with the newest pull request; #339: an agent's "ready to merge" comment with Approve / Reject
const PR_ST = {open: N_('open|pr'), merged: N_('merged'), closed: N_('closed|pr')};
const CI_ST = {success: [N_('CI passed'), 'check'], failure: [N_('CI failed'), 'x'], pending: [N_('CI running'), 'clock']};
const GIT_PROV = [['github', 'GitHub'], ['gitlab', 'GitLab'], ['gitea', 'Gitea / Forgejo'], ['bitbucket', 'Bitbucket Cloud']];  // 2.18.0 (#408): + GitLab, Bitbucket
// 2.18.0: the provider of an address on a cloud host is unambiguous (other hosts: the select)
const gitHostProv = u => { const m = /^https?:\/\/(?:www\.)?(github\.com|gitlab\.com|bitbucket\.org)\//i.exec(String(u || '').trim()); return m ? {'github.com': 'github', 'gitlab.com': 'gitlab', 'bitbucket.org': 'bitbucket'}[m[1].toLowerCase()] : ''; };
const GIT_BASE_PH = {github: N_('empty = github.com'), gitlab: N_('empty = gitlab.com'), bitbucket: N_('empty = bitbucket.org')};
const GIT_TOK_PH = {gitlab: N_('read_api is enough; empty for a public project'), bitbucket: N_('access token, or user:app password; empty for a public repository')};
const listRepos = lid => listById(lid)?.repos || [];
const httpUrl = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '';
function ciIcon(ci) {
  const x = CI_ST[ci]; if (!x) return '';
  return `<span class="ci ci-${ci}" title="${esc(tr(x[0]))}" aria-label="${esc(tr(x[0]))}">${ic(x[1], 's')}</span>`;
}
function codeChip(t) {
  const p = t.code?.prs?.[0]; if (!p) return '';
  const tip = tr('Pull request #{0}: {1}', p.n, tr(PR_ST[p.state] || p.state)) + (CI_ST[p.ci] ? ' · ' + tr(CI_ST[p.ci][0]) : '');
  return `<span class="gitc pr-${esc(p.state)}" title="${esc(tip)}" aria-label="${esc(tip)}">${ic('pr', 's')}#${p.n}${ciIcon(p.ci)}</span>`;
}
// "Agent working on it": the assignee is an agent that reports "working" on this task
function agentOnIt(t) {
  const a = t && t.assignee_id && agentById(t.assignee_id);
  return a && a.enabled && a.status === 'working' && (a.status_task === t.id || (a.job_tasks || []).includes(t.id)) ? a : null;
}
function prRow(p) {
  const u = httpUrl(p.url), inner = `${ic('pr', 's')}<span class="gst pr-${esc(p.state)}">${esc(tr(PR_ST[p.state] || p.state))}</span><span class="gtt">${esc(p.title || '#' + p.n)}</span><span class="muted gmeta">#${p.n}${p.author ? ' · ' + esc(p.author) : ''}</span>${ciIcon(p.ci)}`;
  return u ? `<a class="gitrow" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${inner}</a>` : `<div class="gitrow">${inner}</div>`;
}
function commitRow(m) {
  const u = httpUrl(m.url), inner = `${ic('commit', 's')}<code>${esc(m.short)}</code><span class="gtt">${esc(m.message)}</span><span class="muted gmeta">${esc(m.author || '')}</span>`;
  return u ? `<a class="gitrow" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${inner}</a>` : `<div class="gitrow">${inner}</div>`;
}
// 2.4.2 (#387): the Code section only where it helps: the list has a repository AND the task has linked pull requests /
// commits, is a bug or a feature, or an agent is assigned (it reports its branch / pull request here); otherwise the
// task's "…" menu offers "Link code…" (copies the branch name)
function codeShown(t) {
  if (!(t?.id > 0) || t.context || !listRepos(t.list_id).length) return false;
  const c = t.code || {};
  return !!(c.prs?.length || c.commits?.length) || t.ttype === 'bug' || t.ttype === 'feature' || (!!t.assignee_id && isAgentUser(t.assignee_id));
}
function codeHtml(t) {
  if (!codeShown(t)) return '';
  const repos = listRepos(t.list_id), c = t.code || {prs: [], commits: []};
  const a = agentOnIt(t);
  const prs = c.prs.map(prRow).join(''), cms = c.commits.map(commitRow).join('');
  const hint = !prs && !cms ? `<div class="muted ghint">${esc(tr('Nothing linked yet: mention #{0} in a commit or pull request, or name the branch {1}.', t.id, `kalmido-${t.id}`))}</div>` : '';
  return `<div class="dsec gitsec" id="d-code"><h5>${tr('Code')}${repos.length ? ` <span class="muted h5note">${esc(repos.map(r => r.full_name).join(', '))}</span>` : ''}${repos.length ? `<button class="iconbtn gref" data-act="git-refresh" data-lid="${t.list_id}" title="${esc(tr('Check the repository now'))}" aria-label="${esc(tr('Check the repository now'))}">${ic('sync', 's')}</button>` : ''}</h5>
    ${a ? `<div class="gitagent" role="status">${ic('bot', 's')}<span>${esc(tr('{0} is working on it', a.name))}</span>${a.status_text && a.status_task === t.id ? `<span class="muted">· ${esc(a.status_text)}</span>` : ''}</div>` : ''}${prs ? `<div class="gitl">${prs}</div>` : ''}${cms ? `<div class="gitl">${cms}</div>` : ''}${hint}${repos.length ? `<div class="gcopy"><button class="linkbtn gbranch" data-act="git-branch" data-id="${t.id}" title="${esc(tr('Copy a branch name for this task'))}" aria-label="${esc(tr('Copy the branch name {0}', gitBranch(t)))}">${ic('copy', 's')}<code>${esc(gitBranch(t))}</code></button><button class="linkbtn gbranch" data-act="git-ref" data-id="${t.id}" title="${esc(tr('Copy a commit reference: “fixes #{0}” completes the task when the pull request is merged', t.id))}" aria-label="${esc(tr('Copy the commit reference {0}', gitRef(t)))}">${ic('copy', 's')}<code>${esc(gitRef(t))}</code></button></div>` : ''}</div>`;
}
const gitRef = t => `fixes #${t.id}`;  // 2.18.0 (#408): the commit / pull request reference that completes the ticket on merge
const gitBranch = t => `kalmido-${t.id}`;  // 2.5.1 (#396): the id only, no title part (old <prefix>-<id>-slug branches still match)
async function copyText(x) {  // 2.18.0: clipboard + "Copied" toast (shows the text when the clipboard is blocked)
  try { await navigator.clipboard.writeText(x); toast(tr('Copied: {0}', x)); } catch { toast(x); }
}
async function gitCopyBranch(t) {
  try { await navigator.clipboard.writeText(gitBranch(t)); toast(tr('Copied: {0}', gitBranch(t))); } catch { toast(gitBranch(t)); }
}
async function gitRefresh(lid) {
  const rs = listRepos(lid); if (!rs.length) return;
  try { for (const r of rs) await api('POST', `/api/repos/${r.id}/refresh`); } catch { return; }
  toast(tr('Checking the repository …'));
  setTimeout(async () => { await load(); render(); }, 4000);
}
async function gitUndo(tid) {
  try { await api('POST', `/api/tasks/${tid}/git-undo`); } catch { return; }
  toast(tr('Reopened')); await load(); render(); if (S.sel === tid) loadTimeline(tid);
}
function gitActText(a, d, q) {
  const pr = q(`#${d.n} ${d.title || ''}`.trim()), repo = q(d.repo || '');
  if (a.kind === 'git_pr') return d.state === 'merged' ? tr('Pull request {0} was merged in {1}', pr, repo)
    : d.state === 'closed' ? tr('Pull request {0} was closed in {1}', pr, repo) : tr('Pull request {0} was opened in {1}', pr, repo);
  const t = taskById(S.tl.id), undo = t && t.status !== 0 && canEdit(t) && a.id === Math.max(...(S.tl.activity || []).filter(x => x.kind === 'git_done').map(x => x.id))
    ? ` <button class="linkbtn" data-act="git-undo" data-id="${t.id}">${tr('Undo')}</button>` : '';
  return (d.kind === 'pr' ? tr('Completed by the pull request {0} in {1}', q(d.title || ''), repo)
    : d.kind === 'tag' ? tr('Milestone reached: tag {0} in {1}', q(d.ref || ''), repo)  // 2.18.0 (#408)
      : tr('Completed by the commit {0} in {1}', q(d.title || ''), repo)) + undo;
}
// #339: an agent's "ready to merge" comment: the pull request with state + CI, the summary, Approve / Reject (approvers)
function mrHtml(c, s, ro) {
  const t = taskById(S.sel), p = (t?.code?.prs || []).find(x => x.n === s.number && x.repo === s.repo) || {n: s.number, url: s.pr_url, state: 'open', title: ''};
  const st = s.state === 'approved' ? tr('approved') : s.state === 'rejected' ? tr('rejected') : '';
  const may = s.state === 'open' && !ro && S.tl.approver;
  return `<div class="sug mr ${esc(s.state || 'open')}"><div class="sugh">${ic('pr', 's')}<b>${tr('Ready to merge')}</b>${st ? `<span class="muted">· ${st}</span>` : ''}</div>
    <div class="gitl">${prRow(p)}</div>${s.summary ? `<div class="mrsum">${esc(s.summary).replace(/\n/g, '<br>')}</div>` : ''}
    ${may ? `<div class="sugb"><button class="btn sm pri" data-act="mr-ok" data-cid="${c.id}">${ic('check', 's')} ${tr('Approve')}</button><button class="btn sm" data-act="mr-no" data-cid="${c.id}">${ic('x', 's')} ${tr('Reject')}</button><span class="muted">${tr('The agent merges only after your approval')}</span></div>` : ''}</div>`;
}
// 2.26.0 (#949): an agent's "ready to integrate" / "ready to deploy" request without a pull request: what goes where, the
// evidence it attached, for deploy the approved integrations + the checklist (open tasks tagged deploy); approvers decide.
// A deploy with open checklist items: 👍 alone does not approve, "Approve anyway" does (and records the skipped tasks).
function gateHtml(c, s, ro) {
  const st = s.state === 'approved' ? tr('approved') : s.state === 'rejected' ? tr('rejected') : '';
  const may = s.state === 'open' && !ro && S.tl.approver, dep = s.kind === 'deploy', left = (s.checklist || []).length;
  const li = x => `<li><button type="button" class="linkbtn" data-act="open-id" data-id="${x.id}">#${x.id}</button> ${esc(x.title || '')}</li>`;
  return `<div class="sug mr gate ${esc(s.state || 'open')}"><div class="sugh">${ic(dep ? 'send' : 'pr', 's')}<b>${dep ? tr('Ready to deploy') : tr('Ready to integrate')}</b>${st ? `<span class="muted">· ${st}</span>` : ''}</div>
    ${dep ? '' : `<div class="gref"><code>${esc(s.source || '')}</code> → <code>${esc(s.target || 'main')}</code></div>`}
    ${s.summary ? `<div class="mrsum">${esc(s.summary).replace(/\n/g, '<br>')}</div>` : ''}
    ${s.evidence ? `<details class="gev"><summary>${tr('Evidence')}</summary><pre>${esc(s.evidence)}</pre></details>` : ''}
    ${dep && (s.integrations || []).length ? `<div class="gint"><span class="muted">${tr('Integrations')}:</span> ${s.integrations.map(x => `<code>${esc(x.source || '')}</code>`).join(', ')}</div>` : ''}
    ${dep ? `<div class="gchk"><b>${left ? trn('{0} open deploy task', '{0} open deploy tasks', left) : tr('Checklist complete')}</b>${left ? `<ul>${s.checklist.map(li).join('')}</ul>` : ''}${(s.skipped || []).length ? `<div class="muted">${tr('Approved although open')}: ${s.skipped.map(x => '#' + x.id).join(', ')}</div>` : ''}</div>` : ''}
    ${may ? `<div class="sugb">${dep && left ? `<button class="btn sm" data-act="gate-skip" data-cid="${c.id}">${ic('check', 's')} ${tr('Approve anyway')}</button>` : `<button class="btn sm pri" data-act="gate-ok" data-cid="${c.id}">${ic('check', 's')} ${tr('Approve')}</button>`}<button class="btn sm" data-act="mr-no" data-cid="${c.id}">${ic('x', 's')} ${tr('Reject')}</button><span class="muted">${dep ? tr('The agent deploys only after your approval') : tr('The agent integrates only after your approval')}</span></div>` : ''}</div>`;
}
async function gateDecide(cid, skip) {
  let j; try { j = await api('POST', `/api/comments/${cid}/decide`, {decision: 'approve', skip_checklist: !!skip}); } catch { return; }
  const c = tlComment(cid); if (c) { c.suggestion = j.suggestion; drawTimeline(); }
  toast(j.state === 'blocked' ? tr('Open deploy tasks first, or approve anyway') : tr('Approved'));
}
// list dialog > Repository
function repoBoxHtml(l) {
  return `<h4 id="l-repos-h">${tr('Repository')}</h4><div class="shint lhint">${tr('Pull requests, commits and CI at the tasks of this list: mention #123 (the task number) in a commit or pull request, or name a branch kalmido-123-…. “fixes #123” in a merged pull request completes the task.')}</div><div class="members" id="l-repos"><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
function repoWire(md, lid) {
  const box = $('#l-repos', md); if (!box) return;
  let j = null, edit = null, secret = null, errUrl = null;
  const provSel = `<select id="rp-prov" aria-label="${esc(tr('Provider'))}">${GIT_PROV.map(([k, n]) => `<option value="${k}">${n}</option>`).join('')}</select>`;
  const draw = () => {
    if (!md.isConnected) return;
    if (!j) { box.innerHTML = `<div class="muted mhint">${tr('Loading…')}</div>`; return; }
    const rows = j.repos.map(r => `<div class="mrow reporow" data-rid="${r.id}">${ic('git', 's')}<span class="n"><a href="${esc(httpUrl(r.web_url))}" target="_blank" rel="noopener noreferrer">${esc(r.full_name)}</a>
        <span class="muted rpm">${esc(GIT_PROV.find(x => x[0] === r.provider)?.[1] || r.provider)}${r.default_branch ? ' · ' + esc(r.default_branch) : ''}${j.may ? ' · ' + esc(r.token ? tr('Token set') : tr('No token')) + (r.hook ? ' · ' + esc(tr('Webhook on')) : '') : ''}</span>
        <span class="rst rst-${esc(r.status)}">${esc(r.status === 'error' ? r.error : r.status === 'new' ? tr('Waiting for the first check') : tr('Checked {0}', relTime(r.polled_at)))}</span></span>
        <button class="iconbtn" data-rp="refresh" title="${esc(tr('Check the repository now'))}" aria-label="${esc(tr('Check the repository now'))}">${ic('sync', 's')}</button>
        ${j.may ? `<button class="iconbtn" data-rp="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots', 's')}</button>` : ''}</div>
      ${edit === r.id ? `<div class="mrow repoedit"><input id="rp-tok2" type="password" autocomplete="off" placeholder="${esc(tr('New access token (empty = remove)'))}" aria-label="${esc(tr('Access token'))}"><button class="btn sm" data-rp="tok-save">${tr('Save')}</button></div>` : ''}
      ${secret && secret.id === r.id ? `<div class="shint lhint rpsec">${esc(tr('Webhook: payload URL {0}, content type JSON, secret (shown only now):', r.hook_url))} <code>${esc(secret.s)}</code></div>` : ''}`).join('');
    const add = j.may && j.repos.length < j.max ? `<div class="repoadd">
        <div class="row"><label for="rp-prov">${tr('Provider')}</label>${provSel}</div>
        <div class="shint lhint" id="rp-phint" hidden></div>
        <div class="row"><label for="rp-base">${tr('Server')}</label><input id="rp-base" type="url" inputmode="url" autocomplete="off" placeholder="${esc(tr('empty = github.com'))}"></div>
        <div class="row"><label for="rp-name">${tr('Repository')}</label><input id="rp-name" autocomplete="off" aria-describedby="rp-cerr" placeholder="${esc(tr('owner/name or its web address'))}"></div>
        <div class="shint keep lhint rpself" id="rp-self" hidden>${esc(tr('This looks like a self-hosted server: pick its provider (GitLab, Gitea / Forgejo or Bitbucket) above.'))}</div>
        <div class="row"><label for="rp-tok">${tr('Access token')}</label><input id="rp-tok" type="password" autocomplete="off" placeholder="${esc(tr('read-only is enough; empty for a public repository'))}" ${j.key ? '' : 'disabled'}></div>
        ${j.key ? '' : `<div class="shint keep lhint">${esc(tr('Set KALMIDO_SECRET_KEY on the server to store repository tokens (32 random bytes, base64)'))}</div>`}
        <div class="rpcerr" id="rp-cerr" role="alert"></div>
        <div class="row rprow"><span class="spacer"></span><button class="btn sm pri" data-rp="add">${ic('plus', 's')} ${tr('Connect')}</button></div></div>` : '';
    box.innerHTML = rows + (listById(lid)?.kind === 'project' ? add : `<div class="muted mhint">${tr('Make this list a project to connect a repository')}</div>`)
      + (!j.may && !j.repos.length && listById(lid)?.kind === 'project' ? `<div class="muted mhint">${tr('The list owner and list admins connect repositories.')}</div>` : '')
      + errHookHtml();
  };
  // 2.18.0 (#408 "Software 2" F): error reports -> bug tickets (a secret webhook URL, shown once; owner / list admins)
  const errHookHtml = () => {
    const eh = j.errors; if (!eh || listById(lid)?.kind !== 'project' || (!eh.may && !eh.on)) return '';
    const st = eh.on ? [tr('On'), tr('{0} received', eh.received || 0), eh.open ? trn('{0} open ticket', '{0} open tickets', eh.open) : '', eh.last_at ? tr('last {0}', relTime(eh.last_at)) : ''].filter(Boolean).join(' · ') : tr('Off');
    const ctl = !eh.may ? '' : eh.on ? `<button class="iconbtn" data-rp="err-menu" title="${esc(tr('Error reports'))}: ${esc(tr('More'))}" aria-label="${esc(tr('Error reports'))}: ${esc(tr('More'))}">${ic('dots', 's')}</button>`
      : `<button class="btn sm" data-rp="err-on">${tr('Turn on')}</button>`;
    return `<div class="errhook" id="rp-err"><div class="mrow reporow errrow">${ic('bug', 's')}<span class="n"><b>${tr('Error reports')}</b><span class="muted rpm">${esc(st)}</span></span>${ctl}</div>
      <div class="shint lhint">${tr('Sentry or any service that sends JSON: a new error becomes a bug ticket, the same error again only counts up at its open ticket.')}</div>
      ${errUrl ? `<div class="shint lhint rpsec" role="status">${esc(tr('Webhook URL (shown only now, keep it secret):'))} <code>${esc(errUrl)}</code> <button class="linkbtn" data-rp="err-copy">${ic('copy', 's')} ${tr('Copy')}</button></div>` : ''}</div>`;
  };
  const errSet = async state => {
    let x; try { x = await api('PATCH', `/api/lists/${lid}/error-hook`, {state}); } catch { return; }
    errUrl = x.url || null; j.errors = x; draw();
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
  const reload = async () => { try { j = await api('GET', `/api/lists/${lid}/repos`); } catch { j = {repos: [], may: false, key: true, project: false, max: 0}; } draw(); };
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
      try { await rawFetch('POST', `/api/lists/${lid}/repos`, body); toast(tr('Repository connected')); }
      catch (er) {
        b.disabled = false; if (!md.isConnected) return;
        ce.textContent = er instanceof Offline ? tr('Offline: only works again with a connection') : er.message === 'auth' ? '' : er.message;
        nm.setAttribute('aria-invalid', 'true'); nm.focus();
        return;
      }
      await reload(); await load(); render();
    } else if (k === 'err-on') {
      await errSet('on');
    } else if (k === 'err-copy') {
      try { await navigator.clipboard.writeText(errUrl || ''); toast(tr('Copied')); } catch { toast(errUrl || ''); }
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
  box.addEventListener('change', e => { if (e.target.id === 'rp-prov') { provHint(); selfHint(); } });
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

// ================================================================== 2.17.0 package B "Communication"
