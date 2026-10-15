// 2.44.0 (#1517): set up an agent on a computer with one command. Settings > Agents > (agent) > "Set up on a computer":
// pick Mac / Windows / Linux and the project folder, Kalmido makes a one-time code (15 minutes, works once) and shows ONE
// command to copy; the computers the agent runs on are listed below (green dot = connected), each with "Remove computer"
// (revokes that computer's token). base = /api/my/agents/<id> (own agent) or /api/admin/agents/<id> (an admin).
const AINS_OS = [['mac', N_('Mac')], ['windows', N_('Windows')], ['linux', N_('Linux')]];
const ains_osGuess = () => /Mac|iPhone|iPad/.test(navigator.userAgent) ? 'mac' : /Win/.test(navigator.userAgent) ? 'windows' : 'linux';
const ains_q = s => `'${String(s).replace(/'/g, "'\\''")}'`;   // POSIX shell single quotes
const ains_pq = s => `'${String(s).replace(/'/g, "''")}'`;     // PowerShell single quotes
// 2.46.6 (#1713): the language of the account goes along (--lang / -Lang): the script speaks German or English, anything else = English
const ains_lang = () => (LS.get('lang') || S.settings?.lang || 'en').slice(0, 2).toLowerCase() === 'de' ? 'de' : 'en';
function ains_command(os, url, code, folder) {
  if (os === 'windows') return `& ([scriptblock]::Create((irm ${ains_pq(url + '/agent-setup.ps1')}))) -Url ${ains_pq(url)} -Code ${code} -Dir ${ains_pq(folder)} -Lang ${ains_lang()}`;
  return `curl -fsSL ${ains_q(url + '/agent-setup.sh')} | bash -s -- --url ${ains_q(url)} --code ${code} --dir ${ains_q(folder)} --lang ${ains_lang()}`;
}
const ains_folderHint = os => os === 'windows' ? '~\\projects\\website' : '~/projects/website';
const ains_osName = os => tr((AINS_OS.find(x => x[0] === os) || ['', ''])[1]) || '';
function ains_machinesHtml(ms) {
  if (!ms.length) return `<div class="muted mhint">${tr('No computer yet.')}</div>`;
  return ms.map(m => `<div class="mrow ainsm" data-ainsm="${m.id}">${hdot(m.connected ? 'ready' : 'offline')}<span class="n"><b>${esc(m.host || tr('Unknown computer'))}</b>
      <small class="muted">${esc([m.connected ? tr('connected') : m.last_used_at ? tr('last contact {0}', relTime(m.last_used_at)) : tr('never connected'), ains_osName(m.os), m.folder].filter(Boolean).join(' · '))}</small></span>
      <button class="btn sm danger" data-m="ains-del" aria-label="${esc(tr('Remove computer {0}', m.host || m.prefix))}">${ic('trash', 's')} ${tr('Remove computer')}</button></div>`).join('');
}
function ains_setupModal(a, base) {
  let os = LS.get('ainsOs') || ains_osGuess(), exp = 0, timer = 0;
  const md = modal(`<h3>${esc(tr('Set up {0} on a computer', a.name))}</h3>
    <div class="shint keep">${tr('One command installs the agent on your Mac, Windows PC or Linux computer and starts it at every login. Needed there: Python 3.9 or newer and Claude Code, logged in once.')}</div>
    <div class="row"><label>${tr('Computer')}</label><div class="seg" role="tablist" id="ains-os">${AINS_OS.map(([v, n]) => `<button type="button" role="tab" data-ainsos="${v}" aria-selected="${v === os}" class="${v === os ? 'on' : ''}">${tr(n)}</button>`).join('')}</div></div>
    <div class="row"><label for="ains-dir">${tr('Project folder')}</label><input id="ains-dir" maxlength="300" autocapitalize="off" autocomplete="off" spellcheck="false" placeholder="${esc(ains_folderHint(os))}"></div>
    <div class="row"><label></label><button class="btn pri" data-m="ains-make">${ic('key', 's')} ${tr('Create command')}</button></div>
    <div id="ains-out" hidden>
      <div class="shint keep" id="ains-how"></div>
      <textarea id="ains-cmd" class="ainscmd" readonly rows="4" spellcheck="false" aria-label="${esc(tr('Command'))}"></textarea>
      <div class="row ainsbar"><button class="btn sm pri" data-m="ains-copy">${ic('copy', 's')} ${tr('Copy')}</button><span class="muted" id="ains-exp" role="status"></span><span class="spacer"></span><button class="btn sm" data-m="ains-make">${ic('sync', 's')} ${tr('New code')}</button></div>
    </div>
    <div class="calerr" role="alert" id="ains-err" hidden></div>
    <h4>${tr('Computers')}</h4>
    <div id="ains-ms"><div class="muted mhint">${tr('Loading…')}</div></div>
    ${a.status === 'error' && a.status_text ? `<div class="shint keep warn">${esc(tr('Last error of the agent: {0}', a.status_text))}</div>` : ''}
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Done')}</button></div>`);
  const show = m => { const e = $('#ains-err', md); e.textContent = m || ''; e.hidden = !m; };
  const ms = async () => { try { const j = await api('GET', base + '/machines'); $('#ains-ms', md).innerHTML = ains_machinesHtml(j.machines || []); md._ms = j.machines || []; } catch (x) { $('#ains-ms', md).innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; } };
  const tick = () => {
    if (!md.isConnected) { clearInterval(timer); return; }
    const left = Math.ceil((exp - Date.now()) / 60000), el = $('#ains-exp', md);
    if (!el || !exp) return;
    if (left <= 0) { el.textContent = tr('The code has expired: create a new one.'); $('#ains-cmd', md).classList.add('off'); clearInterval(timer); ms(); return; }
    el.textContent = trn('Valid for {0} more minute, works once', 'Valid for {0} more minutes, works once', left);
    if (left % 2 === 0) ms();  // the new computer shows up while the dialog is open
  };
  md.addEventListener('click', async e => {
    const o = e.target.closest('[data-ainsos]');
    if (o) {
      os = o.dataset.ainsos; LS.set('ainsOs', os);
      $$('[data-ainsos]', md).forEach(b => { const on = b === o; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); });
      $('#ains-dir', md).placeholder = ains_folderHint(os); $('#ains-out', md).hidden = true;
      return;
    }
    const b = e.target.closest('button[data-m]'); if (!b) return;
    const m = b.dataset.m;
    if (m === 'close') { clearInterval(timer); md.remove(); return; }
    if (m === 'ains-make') {
      const dir = $('#ains-dir', md).value.trim(); if (!dir) { need($('#ains-dir', md)); return; }
      b.disabled = true; show('');
      try {
        const r = await api('POST', base + '/setup-code', {os, folder: dir});
        $('#ains-cmd', md).value = ains_command(os, location.origin, r.code, dir); $('#ains-cmd', md).classList.remove('off');
        $('#ains-how', md).textContent = os === 'windows' ? tr('Open PowerShell on the computer, paste the command and press Enter.') : tr('Open the Terminal on the computer, paste the command and press Enter.');
        $('#ains-out', md).hidden = false;
        exp = new Date(r.expires_at).getTime(); clearInterval(timer); timer = setInterval(tick, 30000); tick();
      } catch (x) { show(x.message); } finally { b.disabled = false; }
      return;
    }
    if (m === 'ains-copy') {
      const ok = await clipCopy($('#ains-cmd', md).value);
      if (ok) toast(tr('Copied')); else { $('#ains-cmd', md).select(); toast(tr('Copy failed, select the text by hand')); }
      return;
    }
    if (m === 'ains-del') {
      const mc = (md._ms || []).find(x => x.id === +b.closest('[data-ainsm]').dataset.ainsm); if (!mc) return;
      if (!await askConfirm(tr('Remove computer {0}?', mc.host || mc.prefix), tr('Its token stops working at once and the agent there can no longer reach Kalmido. This cannot be undone: to use the computer again, set it up anew.'), {ok: tr('Remove computer'), danger: true})) return;
      try { const j = await api('DELETE', `${base}/machines/${mc.id}`); $('#ains-ms', md).innerHTML = ains_machinesHtml(j.machines || []); md._ms = j.machines || []; toast(tr('Computer removed')); } catch (x) { show(x.message); }
    }
  });
  ms();
  setTimeout(() => $('#ains-dir', md)?.focus(), 0);
  return md;
}
