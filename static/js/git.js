/* Kalmido web client: Git integration of project lists: repositories, pull requests + CI, agents' merge requests.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- 2.2.0 (#271): Git integration. The list dialog of a project list connects GitHub / Gitea / Forgejo repositories
// (owner + list admins); the task panel shows the linked pull requests (state, CI) and commits ("Code", before the
// comments), rows a chip with the newest pull request; #339: an agent's "ready to merge" comment with Approve / Reject
const PR_ST = {open: N_('open|pr'), merged: N_('merged'), closed: N_('closed|pr')};
const CI_ST = {success: [N_('CI passed'), 'check'], failure: [N_('CI failed'), 'x'], pending: [N_('CI running'), 'clock']};
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
// 2.151.0 A (#2558): a commit's mark: its first version, else its branch when it is not in the default branch
function commitMark(t, m) {
  const v = gitVer(m.tag); if (v) return `<span class="gmark gm-rel" title="${esc(tr('In version {0}', v))}">${esc(v)}</span>`;
  const dflt = listRepos(t.list_id).find(r => r.full_name === m.repo)?.default_branch;
  return m.branch && dflt && m.branch !== dflt ? `<span class="gmark" title="${esc(tr('Branch {0}', m.branch))}">${esc(m.branch)}</span>` : '';
}
const gitVer = n => { const s = String(n || '').trim(); return /^[vV]?\d/.test(s) ? s.replace(/^[vV]/, '') : ''; };
function commitRow(m, t) {
  const u = httpUrl(m.url), inner = `${ic('commit', 's')}<code>${esc(m.short)}</code><span class="gtt">${esc(m.message)}</span>${t ? commitMark(t, m) : ''}<span class="muted gmeta">${esc(m.author || '')}</span>`;
  return u ? `<a class="gitrow" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${inner}</a>` : `<div class="gitrow">${inner}</div>`;
}
// 2.4.2 (#387): the Code section only where it helps: the list has a repository AND the task has linked pull requests /
// commits, is a bug or a feature, or an agent is assigned (it reports its branch / pull request here); otherwise the
// task's "…" menu offers "Link code…" (copies the branch name)
function codeShown(t) {
  if (!(t?.id > 0) || t.context || !listRepos(t.list_id).length) return false;
  const c = t.code || {};
  return !!(c.prs?.length || c.commits?.length || c.build) || t.ttype === 'bug' || t.ttype === 'feature' || (!!t.assignee_id && isAgentUser(t.assignee_id));
}
function codeHtml(t) {
  if (!codeShown(t)) return '';
  const repos = listRepos(t.list_id), c = t.code || {prs: [], commits: []};
  const a = agentOnIt(t);
  const prs = (c.prs || []).map(prRow).join(''), cms = (c.commits || []).map(m => commitRow(m, t)).join('');
  const hint = !prs && !cms && !c.build ? `<div class="muted ghint">${esc(tr('Nothing linked yet: mention #{0} in a commit or pull request, or name the branch {1}.', t.id, `kalmido-${t.id}`))}</div>` : '';
  return `<div class="dsec gitsec" id="d-code"><h5>${tr('Code')}${repos.length ? ` <span class="muted h5note">${esc(repos.map(r => r.full_name).join(', '))}</span>` : ''}${repos.length ? `<button class="iconbtn gref" data-act="git-refresh" data-lid="${t.list_id}" title="${esc(tr('Check the repository now'))}" aria-label="${esc(tr('Check the repository now'))}">${ic('sync', 's')}</button>` : ''}</h5>
    ${buildHtml(t)}${a ? `<div class="gitagent" role="status">${ic('bot', 's')}<span>${esc(tr('{0} is working on it', a.name))}</span>${a.status_text && a.status_task === t.id ? `<span class="muted">· ${esc(a.status_text)}</span>` : ''}</div>` : ''}${prs ? `<div class="gitl">${prs}</div>` : ''}${cms ? `<div class="gitl">${cms}</div>` : ''}${hint}${repos.length ? `<div class="gcopy"><button class="linkbtn gbranch" data-act="git-branch" data-id="${t.id}" title="${esc(tr('Copy a branch name for this task'))}" aria-label="${esc(tr('Copy the branch name {0}', gitBranch(t)))}">${ic('copy', 's')}<code>${esc(gitBranch(t))}</code></button><button class="linkbtn gbranch" data-act="git-ref" data-id="${t.id}" title="${esc(tr('Copy a commit reference: “fixes #{0}” completes the task when the pull request is merged', t.id))}" aria-label="${esc(tr('Copy the commit reference {0}', gitRef(t)))}">${ic('copy', 's')}<code>${esc(gitRef(t))}</code></button></div>` : ''}</div>`;
}
// 2.151.0 A (#2558): the build state on top of the Code section: released / in the default branch / only on a branch, and a
// hint when the package (or the code) is released but the task is still open
function buildText(t) {
  const b = t.code?.build; if (!b) return '';
  const dflt = listRepos(t.list_id)[0]?.default_branch || 'main';
  return b.state === 'released' ? (b.version ? tr('In version {0}', b.version) : tr('In an earlier version'))
    : b.state === 'main' ? tr('In {0}, not released yet', dflt)
    : b.state === 'branch' ? tr('Built, not in {0} yet', dflt) : '';
}
function staleText(t) {
  const b = t.code?.build; if (!b?.stale) return '';
  return b.package?.released ? tr('Package {0} is already released, but the task is still open.', b.package.value)
    : b.version ? tr('Its code is in version {0}, but the task is still open.', b.version) : tr('Its code is already released, but the task is still open.');
}
function buildHtml(t) {
  const b = t.code?.build; if (!b) return '';
  const txt = buildText(t), st = staleText(t);
  const brs = (b.branches || []).map(x => { const u = httpUrl(x.url), lbl = `${ic('git', 's')}<code>${esc(x.name)}</code><span class="muted gmeta">${esc(trn('{0} commit ahead', '{0} commits ahead', x.ahead))}</span>`;
    return u ? `<a class="gitrow gbr" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${lbl}</a>` : `<div class="gitrow gbr">${lbl}</div>`; }).join('');
  const pk = b.package && !b.package.released && b.package.value ? `<span class="muted gbpk">${esc(tr('{0}: {1}', b.package.field, b.package.value))}</span>` : '';
  return (txt || pk ? `<div class="gbuild gb-${esc(b.state)}" role="status">${ic(b.state === 'released' ? 'rocket' : b.state === 'branch' ? 'pr' : 'git', 's')}<span>${esc(txt || tr('Not built yet'))}</span>${pk}</div>` : '')
    + (st ? `<div class="gstale" role="status">${ic('alert', 's')}<span>${esc(st)}</span></div>` : '')
    + (brs ? `<div class="gitl">${brs}</div>` : '');
}
// in the task row only what needs a look: stale, or built on a branch that is not in the default branch (calm otherwise)
function buildRowHint(t) {
  const b = t.code?.build; if (!b || !(t.id > 0)) return '';
  const tip = b.stale ? staleText(t) : b.state === 'branch' && b.branches?.length ? buildText(t) + ': ' + b.branches.map(x => x.name).join(', ') : '';
  return tip ? `<span class="gbrow${b.stale ? ' stale' : ''}" title="${esc(tip)}" aria-label="${esc(tip)}">${ic(b.stale ? 'alert' : 'pr', 's')}</span>` : '';
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
  return `<div class="sug mr ${esc(s.state || 'open')}"><div class="sugh">${ic('pr', 's')}<b>${tr('Ready to merge')}</b>${st ? `<span class="muted">· ${s.state === 'approved' ? thumbIc(true) : thumbIc(false)} ${st}</span>` : ''}</div>
    <div class="gitl">${prRow(p)}</div>${s.summary ? `<div class="mrsum">${esc(s.summary).replace(/\n/g, '<br>')}</div>` : ''}
    ${may ? `<div class="sugb"><button class="btn sm pri" data-act="mr-ok" data-cid="${c.id}">${thumbIc(true)} ${tr('Approve')}</button><button class="btn sm" data-act="mr-no" data-cid="${c.id}">${thumbIc(false)} ${tr('Reject')}</button><span class="muted">${tr('The agent merges only after your approval')}</span></div>` : ''}</div>`;
}
// 2.26.0 (#949): an agent's "ready to integrate" / "ready to deploy" request without a pull request: what goes where, the
// evidence it attached, for deploy the approved integrations + the checklist (open tasks tagged deploy); approvers decide.
// A deploy with open checklist items: 👍 alone does not approve, "Approve anyway" does (and records the skipped tasks).
function gateHtml(c, s, ro) {
  const st = s.state === 'approved' ? tr('approved') : s.state === 'rejected' ? tr('rejected') : '';
  const may = s.state === 'open' && !ro && S.tl.approver, dep = s.kind === 'deploy', left = (s.checklist || []).length;
  const li = x => `<li><button type="button" class="linkbtn" data-act="open-id" data-id="${x.id}">#${x.id}</button> ${esc(x.title || '')}</li>`;
  return `<div class="sug mr gate ${esc(s.state || 'open')}"><div class="sugh">${ic(dep ? 'send' : 'pr', 's')}<b>${dep ? tr('Ready to deploy') : tr('Ready to integrate')}</b>${st ? `<span class="muted">· ${s.state === 'approved' ? thumbIc(true) : thumbIc(false)} ${st}</span>` : ''}</div>
    ${dep ? '' : `<div class="gref"><code>${esc(s.source || '')}</code> → <code>${esc(s.target || 'main')}</code></div>`}
    ${s.summary ? `<div class="mrsum">${esc(s.summary).replace(/\n/g, '<br>')}</div>` : ''}
    ${s.evidence ? `<details class="gev"><summary>${tr('Evidence')}</summary><pre>${esc(s.evidence)}</pre></details>` : ''}
    ${dep && (s.integrations || []).length ? `<div class="gint"><span class="muted">${tr('Integrations')}:</span> ${s.integrations.map(x => `<code>${esc(x.source || '')}</code>`).join(', ')}</div>` : ''}
    ${dep ? `<div class="gchk"><b>${left ? trn('{0} open deploy task', '{0} open deploy tasks', left) : tr('Checklist complete')}</b>${left ? `<ul>${s.checklist.map(li).join('')}</ul>` : ''}${(s.skipped || []).length ? `<div class="muted">${tr('Approved although open')}: ${s.skipped.map(x => '#' + x.id).join(', ')}</div>` : ''}</div>` : ''}
    ${may ? `<div class="sugb">${dep && left ? `<button class="btn sm" data-act="gate-skip" data-cid="${c.id}">${thumbIc(true)} ${tr('Approve anyway')}</button>` : `<button class="btn sm pri" data-act="gate-ok" data-cid="${c.id}">${thumbIc(true)} ${tr('Approve')}</button>`}<button class="btn sm" data-act="mr-no" data-cid="${c.id}">${thumbIc(false)} ${tr('Reject')}</button><span class="muted">${dep ? tr('The agent deploys only after your approval') : tr('The agent integrates only after your approval')}</span></div>` : ''}</div>`;
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
// 2.149.0 F (#2518): the repository editor (repoWire, folderRepoModal) is in gitrepo.js, loaded when a dialog opens it
// ================================================================== 2.17.0 package B "Communication"

// ---- 2.35.0 (#1095): code snippets of a task: plain code (no Markdown) with a language (picked or recognised), an
// optional file path + line, highlighted like the code blocks of a description (hlCode), a Copy button, a monospace
// editor with Tab indentation. Shown in lists of the software project type, elsewhere from the task menu ("Add code
// snippet"); agents read / write them as `snippets` (API, MCP add_snippet, task events)
const SNIP_MAX = 20, SNIP_CODE_MAX = 20000;
const SNIP_LANGS = [['', N_('Automatic|language')], ['text', N_('Plain text')], ['py', 'Python'], ['js', 'JavaScript'], ['ts', 'TypeScript'],
  ['sh', 'Shell'], ['sql', 'SQL'], ['json', 'JSON'], ['yaml', 'YAML'], ['html', 'HTML / XML'], ['css', 'CSS'], ['diff', 'Diff'],
  ['go', 'Go'], ['rust', 'Rust'], ['java', 'Java / Kotlin'], ['c', 'C / C++ / C#']];
const snipLangName = k => { const x = SNIP_LANGS.find(l => l[0] === k); return x ? (k ? x[1] : tr(x[1])) : k; };
// a quick guess of the language from the code itself ('' = none: shown without highlighting)
function snipGuess(code) {
  const s = String(code || '').slice(0, 4000), ls = s.split('\n').filter(l => l.trim());
  if (!ls.length) return '';
  if (/^(diff --git|--- |\+\+\+ |@@ )/m.test(s) && ls.filter(l => /^[+\-@ ]/.test(l)).length >= ls.length * 0.8) return 'diff';
  if (/^\s*[[{]/.test(s)) { try { JSON.parse(s); return 'json'; } catch { /* not JSON */ } }
  if (/^\s*<(!doctype|html|\?xml|[a-z][\w-]*[\s>])/i.test(s)) return 'html';
  if (/^#!.*\b(ba|z)?sh\b|^\s*\$ \S/m.test(s)) return 'sh';
  if (/^\s*(def |class \w+(\(.*\))?:|from [\w.]+ import |import \w+$|if __name__ == )/m.test(s)) return 'py';
  if (/^\s*(select|insert into|update \w+ set|create (table|index)|delete from|with \w+ as)\b/im.test(s)) return 'sql';
  if (/^\s*package \w+|^\s*func \w*\(/m.test(s)) return 'go';
  if (/^\s*(fn |let mut |use \w+::|impl )/m.test(s)) return 'rust';
  if (/^\s*#include\b|^\s*(int|void) main\s*\(/m.test(s)) return 'c';
  if (/^\s*(public |private )?(class|interface) \w+.*\{|System\.out\.|^\s*fun \w+\(/m.test(s)) return 'java';
  if (/^\s*(interface \w+|type \w+ = )|:\s*(string|number|boolean)\b/m.test(s)) return 'ts';
  if (/\b(const|let|function|=>|require\(|console\.|export (default|const|function))\b/.test(s)) return 'js';
  if (/^[\s.#\w-]+\{[^}]*:[^}]*;/m.test(s)) return 'css';
  if (/^\w[\w.-]*:(\s|$)/m.test(s) && !/[{};]/.test(s)) return 'yaml';
  return '';
}
const snipLang = s => s.lang === 'text' ? '' : s.lang || snipGuess(s.code);
// 2.35.0 review (M4): lists and the state carry only the number (snippets_n); the snippets come with the task itself
// (GET /api/tasks/<id>, the answer of a change), kept per task while its updated_at stays the same
S.snipC = {}; S.snipLd = new Set();
const snipCount = t => Array.isArray(t?.snippets) ? t.snippets.length : t?.snippets_n || 0;
const snipLoaded = t => !snipCount(t) || Array.isArray(t.snippets) || S.snipC[t.id]?.at === t.updated_at;
function snipList(t) {
  if (!t) return [];
  if (Array.isArray(t.snippets)) return t.snippets;
  const c = S.snipC[t.id]; return c && c.at === t.updated_at ? c.list : [];
}
async function snipLoad(t) {
  if (snipLoaded(t)) return snipList(t);
  const j = await rawFetch('GET', '/api/tasks/' + t.id);
  const cur = taskById(t.id) || t;  // keyed by the version on screen (the server's newest list; the next sync refreshes it)
  S.snipC[t.id] = {at: cur.updated_at, list: j.snippets || []};
  return S.snipC[t.id].list;
}
function snipLoadShow(t) {  // the panel shows "Loading…" and draws again once they are there
  if (S.snipLd.has(t.id)) return;
  S.snipLd.add(t.id);
  snipLoad(t).catch(() => { S.snipC[t.id] = {at: t.updated_at, list: [], err: true}; }).finally(() => { S.snipLd.delete(t.id); if (S.sel === t.id) renderDetail(); });
}
// shown: there are snippets; or a software project list / opened from the task menu, for someone who may change the task
function snipShown(t) {
  if (!(t?.id > 0) || t.context) return false;
  if (snipCount(t) || S.snip?.tid === t.id) return true;
  return listById(t.list_id)?.ptype === 'software' && canEdit(t);
}
function snipFileUrl(t, s) {  // the file in the list's repository (as file:line links of a description), else null
  if (!s.path) return null;
  const keep = MD_REPO;
  MD_REPO = listRepos(t.list_id).find(r => httpUrl(r.web_url)) || null;
  try { return MD_REPO ? mdFileUrl(s.path + (s.line ? ':' + s.line : '')) : null; } catch { return null; } finally { MD_REPO = keep; }
}
function snipHtml(t, ro) {
  if (!snipShown(t)) return '';
  if (!snipLoaded(t)) { snipLoadShow(t); return `<div class="dsec snipsec" id="d-snips"><h5>${tr('Code snippets')} <span class="muted h5note">${snipCount(t)}</span></h5><div class="muted">${tr('Loading…')}</div></div>`; }
  const ed = S.snip?.tid === t.id ? S.snip : null, list = snipList(t);
  const one = s => {
    if (ed && ed.sid === s.id && !ro) return snipEditHtml(ed);
    const lg = snipLang(s), where = s.path ? s.path + (s.line ? ':' + s.line : '') : '', fu = where && snipFileUrl(t, s);
    const who = s.by && s.by !== S.me?.id ? personNameAny(s.by) : '';
    return `<div class="snip" data-sid="${esc(s.id)}">
      <div class="sniphead"><span class="sniplang" title="${esc(s.lang ? tr('Language') : tr('Language (recognised automatically)'))}">${esc(lg ? snipLangName(lg) : tr('Plain text'))}</span>${where ? (fu ? `<a class="snippath" href="${esc(fu)}" target="_blank" rel="noopener noreferrer" title="${esc(tr('Open the file in the repository'))}"><code>${esc(where)}</code></a>` : `<code class="snippath">${esc(where)}</code>`) : ''}${who ? `<span class="muted snipby">${esc(who)}</span>` : ''}<span class="spacer"></span>
        <button type="button" class="iconbtn" data-act="snip-copy" data-sid="${esc(s.id)}" title="${esc(tr('Copy code'))}" aria-label="${esc(tr('Copy code'))}">${ic('copy', 's')}</button>${ro ? '' : `<button type="button" class="iconbtn" data-act="snip-edit" data-sid="${esc(s.id)}" title="${esc(tr('Edit code snippet'))}" aria-label="${esc(tr('Edit code snippet'))}">${ic('edit', 's')}</button><button type="button" class="iconbtn" data-act="snip-rm" data-sid="${esc(s.id)}" title="${esc(tr('Remove code snippet'))}" aria-label="${esc(tr('Remove code snippet'))}">${ic('trash', 's')}</button>`}</div>
      <pre class="mdpre snipcode"${lg ? ` data-lang="${esc(lg)}"` : ''}><code>${hlCode(s.code, lg)}</code></pre></div>`;
  };
  const add = !ro && list.length < SNIP_MAX && !(ed && ed.sid === 'new') ? `<button type="button" class="attadd" data-act="snip-new" data-id="${t.id}">${ic('plus', 's')}<span>${tr('Add code snippet')}</span></button>` : '';
  return `<div class="dsec snipsec" id="d-snips"><h5>${tr('Code snippets')}${list.length ? ` <span class="muted h5note">${list.length}</span>` : ''}</h5>
    ${list.map(one).join('')}${ed && ed.sid === 'new' && !ro ? snipEditHtml(ed) : ''}${add}</div>`;
}
function snipEditHtml(ed) {
  const n = (ed.code || '').length;
  return `<div class="snip snipedit" data-sid="${esc(ed.sid)}">
    <div class="snipedrow"><label class="sr" for="snip-lang">${tr('Language')}</label><select id="snip-lang">${SNIP_LANGS.map(([k, nm]) => `<option value="${k}" ${(ed.lang || '') === k ? 'selected' : ''}>${esc(k ? nm : tr(nm) + (snipGuess(ed.code) ? ` (${snipLangName(snipGuess(ed.code))})` : ''))}</option>`).join('')}</select>
      <input id="snip-path" value="${esc(ed.path || '')}" maxlength="300" placeholder="${esc(tr('File path (optional)'))}" aria-label="${esc(tr('File path (optional)'))}" autocapitalize="off" autocorrect="off" spellcheck="false">
      <input id="snip-line" value="${ed.line || ''}" inputmode="numeric" maxlength="8" placeholder="${esc(tr('Line'))}" aria-label="${esc(tr('Line (optional)'))}"></div>
    <textarea id="snip-code" class="snipta" rows="${Math.min(18, Math.max(5, (ed.code || '').split('\n').length + 1))}" maxlength="${SNIP_CODE_MAX}" wrap="off" spellcheck="false" autocapitalize="off" autocorrect="off" aria-label="${esc(tr('Code'))}" aria-describedby="snip-hint" placeholder="${esc(tr('Paste or type code, an error message or a log'))}">${esc(ed.code || '')}</textarea>
    <div class="snipfoot"><button type="button" class="btn sm pri" data-act="snip-save">${tr('Save')}</button><button type="button" class="btn sm" data-act="snip-cancel">${tr('Cancel')}</button><span class="muted sniphint" id="snip-hint">${esc(tr('Tab indents, Esc then Tab leaves the field'))} · <span id="snip-n">${n} / ${SNIP_CODE_MAX}</span></span></div></div>`;
}
async function snipOpen(tid, sid, code) {  // sid: a snippet's id or 'new'; code: prefilled (pasted into the description)
  let t = taskById(tid); if (!t || !canEdit(t)) return;
  if (!snipLoaded(t)) { try { await snipLoad(t); } catch { toast(tr('Code snippets are only available online.')); return; } t = taskById(tid) || t; }
  const s = sid === 'new' ? {lang: '', path: '', line: null, code: code || ''} : snipList(t).find(x => x.id === sid);
  if (!s) return;
  S.snip = {tid, sid, lang: s.lang || '', path: s.path || '', line: s.line || '', code: s.code || ''};
  if (S.sel !== tid) openDetail(tid); else renderDetail();
  requestAnimationFrame(() => { const a = $('#snip-code'); if (a) { a.focus({preventScroll: true}); a.closest('.snip')?.scrollIntoView({block: 'nearest'}); } });
}
function snipDraft() {  // the editor's fields -> S.snip (a re-render of the panel keeps them)
  if (!S.snip) return;
  const v = id => $(id)?.value;
  if ($('#snip-code')) Object.assign(S.snip, {code: v('#snip-code'), lang: v('#snip-lang') || '', path: v('#snip-path') || '', line: v('#snip-line') || ''});
}
async function snipPut(t, list, msg) {  // one undoable step (the whole list, like the API)
  const before = {...snapTask(t), snippets: snipList(t)};  // the full list (the task may only carry snippets_n)
  const r = await patchTask(t.id, {snippets: list}, true);
  if (r) S.snipC[t.id] = {at: r.updated_at, list: r.snippets || []};
  const e = before && histFields(msg, [[before, {...snapTask(S.tasks.get(t.id) || r), snippets: r?.snippets || []}, ['snippets']]], {res: r});
  if (e) offerUndo(msg, e); else toast(msg);
  return r;
}
async function snipSave() {
  snipDraft();
  const ed = S.snip, t = ed && taskById(ed.tid); if (!t) return;
  const line = String(ed.line || '').trim();
  if (line && !/^\d{1,8}$/.test(line)) { toast(tr('The line is a number')); $('#snip-line')?.focus(); return; }
  if (!ed.code.trim()) { toast(tr('The code snippet is empty')); $('#snip-code')?.focus(); return; }
  const s = {lang: ed.lang, path: ed.path.trim() || null, line: line ? +line : null, code: ed.code};
  const list = snipList(t).map(x => ({...x}));
  if (ed.sid === 'new') list.push(s); else { const i = list.findIndex(x => x.id === ed.sid); if (i < 0) list.push(s); else list[i] = {...list[i], ...s}; }
  try { S.snip = null; await snipPut(t, list, ed.sid === 'new' ? tr('Code snippet added') : tr('Code snippet saved')); }
  catch (e) { S.snip = ed; renderDetail(); toast(e.message || tr('Error')); }
}
function snipCancel() { S.snip = null; renderDetail(); }
async function snipRm(sid) {
  const t = taskById(S.sel); if (!t) return;
  try { await snipPut(t, snipList(t).filter(x => x.id !== sid), tr('Code snippet removed')); } catch (e) { toast(e.message || tr('Error')); }
}
async function snipCopy(sid) {
  const s = snipList(taskById(S.sel)).find(x => x.id === sid); if (!s) return;
  try { await navigator.clipboard.writeText(s.code); toast(tr('Code copied')); } catch { toast(tr('Copying is not allowed here: select the code and copy it')); }
}
// Tab / Shift+Tab indent / outdent the line(s) of the selection by 4 spaces; Esc gives Tab back to the page (the next
// Tab leaves the field, keyboard users are never trapped)
function snipKey(e) {
  const a = e.target;
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); snipSave(); return; }
  if (e.key === 'Escape') { if (a.dataset.tabfree) return; a.dataset.tabfree = '1'; e.stopPropagation(); return; }  // a second Esc leaves as usual
  if (e.key !== 'Tab' || e.ctrlKey || e.metaKey || e.altKey) { if (e.key !== 'Shift') delete a.dataset.tabfree; return; }
  if (a.dataset.tabfree) { delete a.dataset.tabfree; return; }
  e.preventDefault();
  const v = a.value, s = a.selectionStart, en = a.selectionEnd, ls = v.lastIndexOf('\n', s - 1) + 1;
  if (!e.shiftKey && s === en) { a.setRangeText('    ', s, en, 'end'); }
  else {
    const le = v.indexOf('\n', en - (en > s && v[en - 1] === '\n' ? 1 : 0)), end = le < 0 ? v.length : le;
    const block = v.slice(ls, end), out = block.split('\n').map(l => e.shiftKey ? l.replace(/^( {1,4}|\t)/, '') : '    ' + l).join('\n');
    a.setRangeText(out, ls, end, 'select');
  }
  a.dispatchEvent(new Event('input', {bubbles: true}));
}
// pasting code into the description (several lines that look like code): the toast offers the code snippets instead
function snipPasteHint(e, t) {
  const txt = e.clipboardData?.getData('text/plain') || '';
  if (!t || !canEdit(t) || txt.split('\n').length < 3 || txt.length > SNIP_CODE_MAX || /^\s*```/.test(txt) || !snipGuess(txt) || snipCount(t) >= SNIP_MAX) return;
  toast(tr('This looks like code. Put it into a code snippet instead?'), () => {
    const a = $('#d-content'), i = a ? a.value.lastIndexOf(txt) : -1;
    if (a && i >= 0) { a.value = a.value.slice(0, i) + a.value.slice(i + txt.length); a.dispatchEvent(new Event('input', {bubbles: true})); }
    snipOpen(t.id, 'new', txt);
  }, 8000, tr('Code snippet'));
}
document.addEventListener('keydown', e => { if (e.target.id === 'snip-code') snipKey(e); }, true);
document.addEventListener('input', e => {
  if (!S.snip || !e.target.closest?.('.snipedit')) return;
  snipDraft();
  const n = $('#snip-n'); if (n) n.textContent = `${(S.snip.code || '').length} / ${SNIP_CODE_MAX}`;
});
document.addEventListener('paste', e => { if (e.target.id === 'd-content') snipPasteHint(e, taskById(S.sel)); });
document.addEventListener('click', e => {
  const a = e.target.closest('[data-act^="snip-"]'); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  const sid = a.dataset.sid;
  switch (a.dataset.act) {
    case 'snip-new': snipOpen(+a.dataset.id || S.sel, 'new'); break;
    case 'snip-edit': snipOpen(S.sel, sid); break;
    case 'snip-save': snipSave(); break;
    case 'snip-cancel': snipCancel(); break;
    case 'snip-rm': snipRm(sid); break;
    case 'snip-copy': snipCopy(sid); break;
  }
}, true);
