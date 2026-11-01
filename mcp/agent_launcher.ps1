<#
agent_launcher.ps1 -- the PowerShell port of agent_launcher.sh (Windows; also runs with PowerShell 7 on macOS / Linux).
A reference launcher for an agent host (Claude Code) that follows Kalmido's runtime settings (2.4.1; event mode 2.35.0).

Kalmido never runs an agent. An admin only chooses runtime settings in Settings > Agents > (agent) > Runtime and Kalmido
hands them to the agent: GET /api/v1/agent -> "runtime" {model, autocompact, autocompact_pct, nightly_reset, reset_seq,
timezone}. This script runs on the agent's host and applies them:
  - starts the agent command, ALWAYS in a fresh session (never pass --continue / --resume here)
  - model:         appends `--model <model>` (empty = the command's own default)
  - auto-compact:  on + percentage -> CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=<pct>; off -> DISABLE_AUTO_COMPACT=1
  - restarts it (fresh session) when the model / auto-compact settings change, when an admin presses "Reset now"
    (reset_seq goes up), once a night at nightly_reset (HH:MM in runtime.timezone), and whenever the command exits by
    itself (after KALMIDO_RESTART_DELAY seconds)
  - git author (2.396.0, #3386): GIT_AUTHOR_NAME / _EMAIL and GIT_COMMITTER_NAME / _EMAIL from runtime.git_author (a
    project with a repository may name its own: data.repo.git_author of a task), KALMIDO_GIT_COAUTHOR=1 when the agent
    should append a Co-Authored-By line; an older server without git_author: nothing is set
  - interim summary (2.233.0, #3189: rotate_size / rotate_runs / rotate_idle_min, sent as rotate_tokens etc.): applied per chat
    conversation by mcp/agent_run.py in --events mode; without --events the command runs one session (not applicable)
It polls GET /api/v1/agent every KALMIDO_POLL seconds (default 60): one small request, no events are consumed.

usage: pwsh -File agent_launcher.ps1 [-e ENV_FILE] [--once] [-- COMMAND ...]
  -e ENV_FILE    default .\kalmido-agent.env (readable only by the agent's account), lines KEY=VALUE:
                   KALMIDO_URL=https://tasks.example.com
                   KALMIDO_TOKEN=abk_...          the agent's API token (Settings > Agents)
                 every variable in it is passed to the command too (the MCP server mcp/kalmido_mcp.py reads the same two)
  COMMAND        what to start (default: claude). Example:
                   pwsh -File agent_launcher.ps1 -e $HOME\.config\kalmido\agent.env -- claude -p "Work through your Kalmido events"
  --once         print the command line and environment it would use, then exit (a dry run; the token is never printed)
  --events       event mode (2.35.0, recommended for Claude Code): starts mcp/agent_run.py (Python 3), which waits for the
                 agent's events and runs COMMAND once per event, headless with stream-json: steps, model, permission
                 mode, typing / status, plan usage ring, reply reference, approval cards; the final text of a chat run
                 is posted as the answer. COMMAND is then the plain agent command without -p. Same as KALMIDO_EVENTS=1.
                 Optional keys there: KALMIDO_PROMPT_FILE (text in front of every event), KALMIDO_USAGE_LIMIT (pause new
                 runs at this % of the week), KALMIDO_USAGE_FILE (a status line file {at, rate_limits}), KALMIDO_STATE_DIR
                 (event cursor), KALMIDO_APPROVAL_CHECK=0 (2.40.0: no check of chat answers that ask to decide without an
                 approval block), KALMIDO_NOTICE_COMPACTED (2.41.0: the notice in the chat when a run compacts its
                 conversation, {0} = the time). Without --events: the command runs as it is.
  -EnvFile, -Once, -Events  the same as -e, --once, --events (PowerShell spelling, this script only)
  KALMIDO_HOST   the computer name shown in Kalmido (2.44.0; default: the computer name), sent once at start
  KALMIDO_PYTHON the Python to use (default: python3 / py / python on PATH)
Exit codes: 0 stopped (TERM / INT end the command with everything it started, KILL after 30 s; Windows: taskkill /T, /F after
30 s), 1 Kalmido not reachable at the start, 2 a wrong start (no env file, KALMIDO_URL / KALMIDO_TOKEN missing, no event runner).
Needs: Windows PowerShell 5.1 or PowerShell 7+. See docs/AGENTS.md "Set up an agent" for a scheduled task.
#>
# arguments by hand (no param block): everything after "--" (or the first unknown word) is the command, as in the .sh
$OnWindows = ($env:OS -eq 'Windows_NT')
# 2.443.0 (#2940): a run from the scheduled task writes with *>> into agent.log, which never sees [Console]::Error: there the
# line goes to the information stream (Write-Output would land in the return value of the functions that log)
function Log([string]$m) {
  $l = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') agent_launcher: $m"
  if ([Console]::IsErrorRedirected) { [Console]::Error.WriteLine($l) } else { Write-Information -MessageData $l -InformationAction Continue }
}
$EnvFile = '.\kalmido-agent.env'; $Once = $false; $Events = $false; $Command = @()
for ($i = 0; $i -lt $args.Count; $i++) {
  $a = [string]$args[$i]
  if ($a -in @('-e', '--env', '-EnvFile')) { $i++; if ($i -ge $args.Count) { Log '-e needs a file'; exit 2 }; $EnvFile = [string]$args[$i] }
  elseif ($a -in @('--once', '-Once')) { $Once = $true }
  elseif ($a -in @('--events', '-Events')) { $Events = $true }
  elseif ($a -in @('-h', '--help')) { $h = @(Get-Content -LiteralPath $PSCommandPath); $h[1..([array]::IndexOf($h, '#>') - 1)]; exit 0 }
  elseif ($a -eq '--') { $Command = @($args | Select-Object -Skip ($i + 1) | ForEach-Object { [string]$_ }); break }
  else { $Command = @($args | Select-Object -Skip $i | ForEach-Object { [string]$_ }); break }
}
$ErrorActionPreference = 'Stop'
if ($Command.Count -eq 0) { $Command = @('claude') }
$Agent0 = $Command[0]  # the agent command itself (event mode puts Python + agent_run.py in front)

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) { Log "cannot read $EnvFile"; exit 2 }
# the env file: KEY=VALUE per line (an optional "export ", quotes around the value), # comments (2.443.0, #2940: also behind
# a value, after a space, as in the shell); all go into this process's environment, so the command inherits them
foreach ($raw in Get-Content -LiteralPath $EnvFile) {
  $l = $raw.Trim()
  if (-not $l -or $l.StartsWith('#')) { continue }
  if ($l -match '^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
    $k = $Matches[1]; $v = $Matches[2].Trim()
    if ($v -match '^"([^"]*)"(\s+#.*)?$' -or $v -match "^'([^']*)'(\s+#.*)?$") { $v = $Matches[1] }
    else { $v = $v -replace '\s+#.*$', '' }
    [Environment]::SetEnvironmentVariable($k, $v, 'Process')
  }
}
if (-not $env:KALMIDO_URL) { Log "KALMIDO_URL missing in $EnvFile"; exit 2 }
if (-not $env:KALMIDO_TOKEN) { Log "KALMIDO_TOKEN missing in $EnvFile"; exit 2 }
if ($env:KALMIDO_EVENTS -eq '1') { $Events = $true }
# kalmido-capability: steps, model, permission_mode, quota, reply_ref, status_typing, approval, old_server, proposals, message_edited, playbook, approval_check, notice, comment_answer, comment_blocks
# kalmido-capability: outbox, jobs, event_bundling (2.44.0: mcp/agent_extras.py and mcp/agent_job.py, loaded by agent_run.py)
# kalmido-capability: approval_closed, perm_relay, approval_lifecycle, session_resume, robust_runs
# kalmido-capability: team_listen (2.46.1: team chat messages of lists the agent listens in on, in mcp/agent_run.py)
# kalmido-capability: team_thread (2.139.0: a team chat message in a thread is answered in that thread, in mcp/agent_run.py)
# kalmido-capability: rules_block (2.46.6: the fixed rules of mcp/agent_rules.md in front of every prompt, in mcp/agent_run.py)
# kalmido-capability: control_rules (2.235.0: the control level, goal and one-way steps in the rules block, in mcp/agent_run.py)
# kalmido-capability: workflow_file (2.46.6: WORKFLOW-KALMIDO.md, asked for once, in mcp/agent_run.py)
# kalmido-capability: job_wake (2.46.6: a wake run after a job, a lost job continued once; mcp/agent_run.py + agent_job.py)
# kalmido-capability: job_names (2.59.0: a name per job, part jobs name their leader; mcp/agent_job.py)
# kalmido-capability: job_msg (2.96.0: a job's result posts job_msg result / error; mcp/agent_job.py)
# kalmido-capability: layout_answer (2.55.0: the answer to an arrangement proposal, in mcp/agent_run.py)
# kalmido-capability: chat_pinned (2.62.0: a pinned / unpinned chat message is information only, no run; in mcp/agent_run.py)
# kalmido-capability: data_lock_info (2.235.0: data_lock_changed is information only, no run; Kalmido enforces the lock itself; in mcp/agent_run.py)
# kalmido-capability: job_message (2.56.0: a message to a job from its card, in mcp/agent_run.py)
# kalmido-capability: job_chat (2.153.0: a message typed in a job's own chat is answered there, in mcp/agent_run.py)
# kalmido-capability: customer_comment (2.63.0: a customer's comment / public answers of a customer report, in mcp/agent_run.py)
# kalmido-capability: meeting_images (2.70.0: the photos of a meeting request, looked at with get_attachment, in mcp/agent_run.py)
# kalmido-capability: merge_proposal (2.70.0: duplicate contacts as a proposal, in mcp/agent_run.py)
# kalmido-capability: text_proposal (2.126.1: an office text, a document summary, a client report as a proposal, in mcp/agent_run.py)
# kalmido-capability: ideas_proposal (2.156.0: ideas for a branch of the mind map as a proposal, in mcp/agent_run.py)
# kalmido-capability: receipt_read (2.299.0: a receipt read by the agent from the file itself as a proposal, in mcp/agent_run.py)
# kalmido-capability: card_statement_read (2.469.0: a credit card statement read by the agent from the PDF itself as a proposal, in mcp/agent_run.py)
# kalmido-capability: dispatcher (2.481.0, #3662: the list worked off mechanically when switched on, in mcp/agent_run.py + mcp/agent_dispatch.py)
# kalmido-capability: abort (2.144.0: Stop in the chat ends the running command and confirms it, in mcp/agent_run.py)
# kalmido-capability: contract_notice (2.70.0: a contract's notice deadline -> ONE propose_contract_notice, in mcp/agent_run.py)
# kalmido-capability: perm_user_choice (2.312.0, #3266: the person for permission questions chosen in Kalmido before KALMIDO_PERM_USER, in mcp/agent_run.py)
# kalmido-capability: letter_draft (2.153.0: a request to draft an answer to a document -> ONE create_letter_draft, in mcp/agent_run.py)
# (2.44.0: agent_run.py; perm_relay and session_resume only when COMMAND is Claude Code)
# (2.126.0: perm_relay asks only the agent's operator: owner, KALMIDO_PERM_USER, KALMIDO_OWNER_IDS)
# kalmido-capability: usage_hook (2.306.0, #2927: claude_usage_hook.py as Stop / SubagentStop hook in the run settings, in mcp/agent_run.py)
# (2.126.0: playbook names the authors of a foreign Playbook; texts marked untrusted are framed as data)
# (event mode: mcp/agent_run.py does them for both launchers, so .sh and .ps1 cannot drift apart)
if ($Events) {
  $Runner = Join-Path $PSScriptRoot 'agent_run.py'
  if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) { Log "$Runner missing (event mode)"; exit 2 }
  $Py = $env:KALMIDO_PYTHON
  $order = if ($OnWindows) { @('py', 'python', 'python3') } else { @('python3', 'python') }  # Windows: python3 may be the Store stub
  if (-not $Py) { foreach ($n in $order) { if (Get-Command $n -CommandType Application -ErrorAction SilentlyContinue) { $Py = $n; break } } }
  if (-not $Py) { Log 'event mode needs Python 3 (KALMIDO_PYTHON or python3 / py / python on PATH)'; exit 2 }
  $pre = @($Py); if ($Py -eq 'py') { $pre += '-3' }
  $Command = @($pre + @($Runner, '--') + $Command)
}
$Poll = if ($env:KALMIDO_POLL) { [int]$env:KALMIDO_POLL } else { 60 }
$RestartDelay = if ($env:KALMIDO_RESTART_DELAY) { [int]$env:KALMIDO_RESTART_DELAY } else { 10 }
$Url = $env:KALMIDO_URL.TrimEnd('/') + '/api/v1/agent'

# 2.443.0 (#2940): TERM / INT clean up like the trap of the .sh. PowerShell on Unix runs no finally on SIGTERM and a script
# block cannot be a signal handler (no runspace on that thread), so a small C# handler sets a flag that Nap asks every 250 ms.
# Windows has no such signals: the finally around everything below is what cleans up there (PowerShell 7.2+ on Unix only).
$script:Watch = $false
if (-not $OnWindows -and -not $Once) {
  try {
    Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public static class KalmidoStop {
  public static volatile bool Asked;
  static PosixSignalRegistration term, intr;
  public static void Watch() {
    term = PosixSignalRegistration.Create(PosixSignal.SIGTERM, c => { c.Cancel = true; Asked = true; });
    intr = PosixSignalRegistration.Create(PosixSignal.SIGINT, c => { c.Cancel = true; Asked = true; });
  }
}
'@
    [KalmidoStop]::Watch()
    $script:Watch = $true
  } catch { Log "no clean stop on TERM / INT here (PowerShell 7.2+ needed): $($_.Exception.Message)" }
}
function Nap([int]$sec) {  # Start-Sleep that a TERM / INT ends; then the command is stopped and the launcher exits 0
  $end = (Get-Date).AddSeconds($sec)
  do {
    if ($script:Watch -and [KalmidoStop]::Asked) { Stop-Agent; exit 0 }
    Start-Sleep -Milliseconds 250
  } while ((Get-Date) -lt $end)
  if ($script:Watch -and [KalmidoStop]::Asked) { Stop-Agent; exit 0 }
}

# GET /api/v1/agent -> a settings object (2.236.0: working / resumes = the work window of the work style). A paused agent's token is refused (403): enabled = $false. $null: Kalmido not
# reachable (or another error). 2.157.0 (#1517): a revoked token (401) -> revoked = $true. The token only goes into the request header.
function Fetch {
  $h = @{ Authorization = "Bearer $($env:KALMIDO_TOKEN)" }
  try {
    $r = Invoke-WebRequest -Uri $Url -Headers $h -TimeoutSec 20 -UseBasicParsing
    $a = $r.Content | ConvertFrom-Json
  } catch {
    $code = $null
    try { $code = [int]$_.Exception.Response.StatusCode } catch { }
    if ($code -eq 403) { return [pscustomobject]@{model = '-'; ac = '-'; pct = '-'; nightly = '-'; seq = $script:Seq; tz = 'UTC'; enabled = $false; working = $true; resumes = '-'; gname = '-'; gmail = '-'; gco = '0'} }
    if ($code -eq 401) { return [pscustomobject]@{revoked = $true} }
    if ($code) { Log "GET /api/v1/agent: HTTP $code" } else { Log "GET /api/v1/agent: $($_.Exception.Message)" }
    return $null
  }
  $rt = $a.runtime
  $model = if ($rt -and $rt.model) { [string]$rt.model } else { '-' }
  $ac = if ($rt -and $null -ne $rt.autocompact -and -not $rt.autocompact) { '0' } else { '1' }
  $pct = if ($rt -and $rt.autocompact_pct) { [string]$rt.autocompact_pct } else { '-' }
  $nightly = if ($rt -and $rt.nightly_reset) { [string]$rt.nightly_reset } else { '-' }
  $seq = if ($rt -and $rt.reset_seq) { [int]$rt.reset_seq } else { 0 }
  $tz = if ($rt -and $rt.timezone) { [string]$rt.timezone } else { 'UTC' }
  $en = if ($null -ne $a.enabled) { [bool]$a.enabled } else { $true }
  $ws = if ($a.work_style -and $a.work_style.state) { $a.work_style.state } else { $null }
  $wk = -not ($ws -and $ws.working -eq $false)
  $res = if ($ws -and $ws.work_resumes_at) { if ($ws.work_resumes_at -is [datetime]) { $ws.work_resumes_at.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') } else { [string]$ws.work_resumes_at } } else { '-' }
  $gname = '-'; $gmail = '-'  # 2.396.0 (#3386): the git author, '-' = not sent (an older server)
  if ($rt -and $rt.git_author -and ([string]$rt.git_author -match '^([^<>\t\n]+) <([^<>\s]+)>$')) { $gname = $Matches[1].Trim(); $gmail = $Matches[2] }
  $gco = if ($rt -and $rt.git_coauthor) { '1' } else { '0' }
  return [pscustomobject]@{model = $model; ac = $ac; pct = $pct; nightly = $nightly; seq = $seq; tz = $tz; enabled = $en; working = $wk; resumes = $res; gname = $gname; gmail = $gmail; gco = $gco}
}

# kalmido-capability: host_name
# 2.44.0 (#1517): which computer this is (PUT /api/v1/agent/status {status: idle, host}); a missing agent command is
# reported as the agent's error. Older servers refuse the field (400): nothing happens.
function Report-Host {
  $h = if ($env:KALMIDO_HOST) { $env:KALMIDO_HOST } else { [Environment]::MachineName }
  $h = ($h -split '\.')[0]
  $st = 'idle'; $txt = ''
  if (-not (Get-Command $Agent0 -ErrorAction SilentlyContinue)) { $st = 'error'; $txt = "agent command not found on ${h}: $Agent0"; Log $txt }
  $b = @{ status = $st; text = $txt; host = $(if ($h.Length -gt 80) { $h.Substring(0, 80) } else { $h }) } | ConvertTo-Json -Compress
  try {
    Invoke-WebRequest -Uri ($env:KALMIDO_URL.TrimEnd('/') + '/api/v1/agent/status') -Method Put -Body $b -ContentType 'application/json' `
      -Headers @{ Authorization = "Bearer $($env:KALMIDO_TOKEN)" } -TimeoutSec 20 -UseBasicParsing | Out-Null
  } catch { }
}

function Quote([string]$s) {  # one argument for a Windows / .NET command line
  if ($s -eq '') { return '""' }
  if ($s -notmatch '[\s"]') { return $s }
  return '"' + ($s -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

$script:Proc = $null
$script:Started = Get-Date
# kalmido-capability: runtime (model, auto-compact, fresh session, restart on change / reset / nightly, pause)
function Start-Agent($s) {
  $cmdArgs = @($Command)
  if ($s.model -ne '-') { $cmdArgs += @('--model', $s.model) }
  $envs = @()
  if ($s.ac -eq '0') { $envs += 'DISABLE_AUTO_COMPACT=1' } elseif ($s.pct -ne '-') { $envs += "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=$($s.pct)" }
  # kalmido-capability: git_author (2.396.0, #3386): the agent's commits carry the git author set in Kalmido
  if ($s.gname -and $s.gname -ne '-' -and $s.gmail -and $s.gmail -ne '-') {
    $envs += @("GIT_AUTHOR_NAME=$($s.gname)", "GIT_AUTHOR_EMAIL=$($s.gmail)", "GIT_COMMITTER_NAME=$($s.gname)", "GIT_COMMITTER_EMAIL=$($s.gmail)", "KALMIDO_GIT_COAUTHOR=$($s.gco)")
  }
  if ($Once) { Write-Output ("env $($envs -join ' ') $($cmdArgs -join ' ')"); return }
  $acs = if ($s.ac -eq '1') { if ($s.pct -ne '-') { "on at $($s.pct)%" } else { 'on at the default %' } } else { 'off' }
  $mn = if ($s.model -eq '-') { 'default' } else { $s.model }
  Log "starting (fresh session): $($cmdArgs[0]), model $mn, auto-compact $acs"
  $env:KALMIDO_LAUNCHER_PID = "$PID"  # 2.443.0 (#2940): as in the .sh, the event runner ends when this launcher was killed hard
  Remove-Item Env:DISABLE_AUTO_COMPACT, Env:CLAUDE_AUTOCOMPACT_PCT_OVERRIDE, Env:KALMIDO_GIT_COAUTHOR, Env:GIT_AUTHOR_NAME, Env:GIT_AUTHOR_EMAIL, Env:GIT_COMMITTER_NAME, Env:GIT_COMMITTER_EMAIL -ErrorAction SilentlyContinue
  foreach ($e in $envs) { $k, $v = $e -split '=', 2; [Environment]::SetEnvironmentVariable($k, $v, 'Process') }
  # resolve the program (claude is claude.cmd / claude.ps1 on Windows): a .ps1 runs through PowerShell, a .cmd / .bat
  # through cmd.exe
  $exe = $cmdArgs[0]; $rest = @($cmdArgs | Select-Object -Skip 1)
  $found = Get-Command $exe -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($found -and $found.Source) { $exe = $found.Source }
  if ($exe -match '\.ps1$') { $rest = @('-NoProfile', '-File', $exe) + $rest; $exe = (Get-Process -Id $PID).Path }
  elseif ($exe -match '\.(cmd|bat)$') { $rest = @('/d', '/c', $exe) + $rest; $exe = $env:ComSpec }
  # 2.443.0 (#2940): on Unix an own session as in the .sh (same pid, so "kill -- -PID" ends all of it); Windows: taskkill /T
  if (-not $OnWindows) {
    if (-not $found) { throw "command not found: $exe" }  # 2.445.0 (#3748): else setsid starts fine and only then fails, unlogged
    $ss = Get-Command setsid -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($ss) { $rest = @($exe) + $rest; $exe = $ss.Source }
    else {
      $ss = Get-Command $(if ($env:KALMIDO_PYTHON) { $env:KALMIDO_PYTHON } else { 'python3' }) -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($ss) { $rest = @('-c', 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])', $exe) + $rest; $exe = $ss.Source }
    }
  }
  $p = @{FilePath = $exe; PassThru = $true; NoNewWindow = $true}
  if ($rest.Count) { $p.ArgumentList = ($rest | ForEach-Object { Quote $_ }) -join ' ' }
  $script:Proc = Start-Process @p
  $script:Started = Get-Date
}
function Signal-Agent([string]$sig, [int]$id) {  # Unix: its process group, else the program (the program, not the alias)
  $b = Get-Command bash -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($b) { & $b.Source -c "kill -$sig -- -$id 2>/dev/null || kill -$sig $id 2>/dev/null"; return }
  $k = Get-Command kill -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($k) { & $k.Source "-$sig" $id 2>$null } else { Stop-Process -Id $id -Force:($sig -eq 'KILL') -ErrorAction SilentlyContinue }
}
function Stop-Agent {
  if (-not $script:Proc) { return }
  $id = $script:Proc.Id
  if ($OnWindows) {
    if (-not $script:Proc.HasExited) {
      & taskkill.exe /T /PID $id 2>$null | Out-Null  # the whole tree, politely first
      for ($i = 0; $i -lt 30 -and -not $script:Proc.HasExited; $i++) { Start-Sleep -Seconds 1 }
      if (-not $script:Proc.HasExited) { & taskkill.exe /T /F /PID $id 2>$null | Out-Null }
    }
  } else {  # 2.443.0 (#2940): as in the .sh the whole group, and the KILL also reaches what outlived the command itself
    Signal-Agent 'TERM' $id
    for ($i = 0; $i -lt 30 -and -not $script:Proc.HasExited; $i++) { Start-Sleep -Seconds 1 }
    Signal-Agent 'KILL' $id
  }
  $script:Proc = $null
}
# 2.443.0 (#2940): a command that cannot start ends nothing: as in the .sh the launcher goes on and tries again
function Start-Safe($s) {
  try { Start-Agent $s }
  catch { Log "the command did not start ($($_.Exception.Message)); restarting in ${RestartDelay}s"; Nap $RestartDelay }
}

# 2.443.0 (#2940): Windows PowerShell 5.1 knows only Windows zone ids: the usual IANA names per Windows id
$WinZones = @{
  'UTC' = 'UTC Etc/UTC Etc/GMT'
  'W. Europe Standard Time' = 'Europe/Berlin Europe/Amsterdam Europe/Andorra Europe/Luxembourg Europe/Malta Europe/Monaco Europe/Oslo Europe/Rome Europe/Stockholm Europe/Vaduz Europe/Vienna Europe/Zurich'
  'Romance Standard Time' = 'Europe/Brussels Europe/Copenhagen Europe/Madrid Europe/Paris'
  'Central Europe Standard Time' = 'Europe/Belgrade Europe/Bratislava Europe/Budapest Europe/Ljubljana Europe/Prague'
  'Central European Standard Time' = 'Europe/Sarajevo Europe/Skopje Europe/Warsaw Europe/Zagreb'
  'GMT Standard Time' = 'Europe/Dublin Europe/Lisbon Europe/London'
  'Greenwich Standard Time' = 'Atlantic/Reykjavik'
  'GTB Standard Time' = 'Europe/Athens Europe/Bucharest'
  'FLE Standard Time' = 'Europe/Helsinki Europe/Kiev Europe/Kyiv Europe/Riga Europe/Sofia Europe/Tallinn Europe/Vilnius'
  'Turkey Standard Time' = 'Europe/Istanbul'
  'Russian Standard Time' = 'Europe/Moscow'
  'Eastern Standard Time' = 'America/New_York America/Toronto'
  'Central Standard Time' = 'America/Chicago America/Winnipeg'
  'Mountain Standard Time' = 'America/Denver America/Edmonton'
  'US Mountain Standard Time' = 'America/Phoenix'
  'Pacific Standard Time' = 'America/Los_Angeles America/Vancouver'
  'Alaskan Standard Time' = 'America/Anchorage'
  'Hawaiian Standard Time' = 'Pacific/Honolulu'
  'Central Standard Time (Mexico)' = 'America/Mexico_City'
  'SA Pacific Standard Time' = 'America/Bogota America/Lima'
  'E. South America Standard Time' = 'America/Sao_Paulo'
  'Argentina Standard Time' = 'America/Argentina/Buenos_Aires America/Buenos_Aires'
  'Arabian Standard Time' = 'Asia/Dubai'
  'India Standard Time' = 'Asia/Calcutta Asia/Kolkata'
  'SE Asia Standard Time' = 'Asia/Bangkok Asia/Ho_Chi_Minh Asia/Jakarta'
  'Singapore Standard Time' = 'Asia/Singapore'
  'China Standard Time' = 'Asia/Hong_Kong Asia/Shanghai'
  'Tokyo Standard Time' = 'Asia/Tokyo'
  'Korea Standard Time' = 'Asia/Seoul'
  'Israel Standard Time' = 'Asia/Jerusalem'
  'AUS Eastern Standard Time' = 'Australia/Melbourne Australia/Sydney'
  'E. Australia Standard Time' = 'Australia/Brisbane'
  'W. Australia Standard Time' = 'Australia/Perth'
  'New Zealand Standard Time' = 'Pacific/Auckland'
  'South Africa Standard Time' = 'Africa/Johannesburg'
  'Egypt Standard Time' = 'Africa/Cairo'
  'E. Africa Standard Time' = 'Africa/Nairobi'
  'W. Central Africa Standard Time' = 'Africa/Lagos'
}
function Now-In([string]$tz) {  # the current time in an IANA zone (.NET 6+ also on Windows); unknown -> local time
  $win = $WinZones.Keys | Where-Object { ($WinZones[$_] -split ' ') -contains $tz } | Select-Object -First 1
  foreach ($id in @($tz, $win)) {
    if (-not $id) { continue }
    try { return [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Now, [TimeZoneInfo]::FindSystemTimeZoneById($id)) } catch { }
  }
  return [DateTimeOffset]::Now
}
$script:DoneDay = ''  # the day whose nightly restart is done (a start after that time counts)
function Nightly-Due($s) {
  if ($s.nightly -eq '-' -or $s.nightly -notmatch '^(\d{1,2}):(\d{2})(:\d{2})?$') { return $false }
  $hh = [int]$Matches[1]; $mm = [int]$Matches[2]
  if ($hh -gt 23 -or $mm -gt 59) { return $false }  # 2.443.0 (#2940): no such time (25:00): no restart, as in the .sh
  $now = Now-In $s.tz
  $day = $now.ToString('yyyy-MM-dd')
  if ($script:DoneDay -eq $day) { return $false }
  $at = New-Object DateTimeOffset ($now.Year, $now.Month, $now.Day, $hh, $mm, 0, $now.Offset)
  if ($now -lt $at) { return $false }
  $script:DoneDay = $day
  return ([DateTimeOffset]$script:Started -lt $at)  # started before tonight's time -> restart now
}

# kalmido-capability: revoked_stop (2.157.0, #1517): a revoked token stops the agent with ONE log line; the launcher stays and
# checks quietly (exiting would only make the scheduled task start it again and again)
$script:Revoked = $false
function Revoked {
  if (-not $script:Revoked) { Log "this computer's key no longer works (computer removed or agent deleted in Kalmido): the agent stays stopped; take it off this computer with the uninstall command that Kalmido shows" }
  $script:Revoked = $true
}
# 2.443.0 (#2940): everything from the first request on stands in this try: a stop in any phase ends the command
try {
  while ($true) {
    $s = Fetch
    if (-not $s -or ($s.revoked -and $Once)) { Log "cannot read the runtime settings from $($env:KALMIDO_URL)"; exit 1 }
    if (-not $s.revoked) { break }
    Revoked
    Nap $Poll
  }
  $script:Revoked = $false
  $script:Seq = $s.seq
  if ($Once) { Start-Agent $s; exit 0 }
  $sig = "$($s.model)|$($s.ac)|$($s.pct)|$($s.gname)|$($s.gmail)|$($s.gco)"
  # kalmido-capability: standing_rules (2.235.0, #2903: the active standing rules under the rules block, in mcp/agent_run.py)
  # kalmido-capability: lang_texts (2.450.0, #3769: the texts by the agent's language, in mcp/agent_run.py)
  # kalmido-capability: work_window (2.236.0, #2905): outside the work window of the work style (work_style.state.working
  # false) no new session starts until work_resumes_at; the events wait in Kalmido (event mode: mcp/agent_run.py holds its queue)
  $script:Closed = $false
  function Closed($s) {
    if ($s.working) { if ($script:Closed) { Log 'work window open again' }; $script:Closed = $false; return $false }
    if (-not $script:Closed) { $r = if ($s.resumes -ne '-') { $s.resumes } else { 'the window opens' }; Log "outside the work window of its work style: no new session until $r" }
    $script:Closed = $true
    return $true
  }
  if ($s.enabled) { Report-Host; if (-not (Closed $s)) { Start-Safe $s } } else { Log 'the agent is paused in Kalmido; waiting' }
  [void](Nightly-Due $s)  # a start after tonight's time already counts as the nightly restart
  while ($true) {
    Nap $Poll
    try {  # 2.443.0 (#2940): an error in one round ends nothing, as in the .sh: the next round goes on after the restart delay
      if ($script:Proc -and $script:Proc.HasExited) {
        $script:Proc = $null
        Log "the command ended; restarting in ${RestartDelay}s"; Nap $RestartDelay
      }
      $n = Fetch
      if (-not $n) { Log 'Kalmido not reachable; keeping the agent as it is'; continue }
      if ($n.revoked) { Revoked; Stop-Agent; continue }
      $script:Revoked = $false
      $why = ''
      if ($n.seq -ne $script:Seq) { $why = "reset now ($($script:Seq) -> $($n.seq))" }
      if (-not $why -and "$($n.model)|$($n.ac)|$($n.pct)|$($n.gname)|$($n.gmail)|$($n.gco)" -ne $sig) { $why = 'runtime settings changed' }
      if (-not $why -and (Nightly-Due $n)) { $why = "nightly fresh restart ($($n.nightly) $($n.tz))" }
      $script:Seq = $n.seq; $sig = "$($n.model)|$($n.ac)|$($n.pct)|$($n.gname)|$($n.gmail)|$($n.gco)"
      if (-not $n.enabled) {
        if ($script:Proc) { Log 'paused in Kalmido: stopping'; Stop-Agent }
        continue
      }
      if ($why -and $script:Proc) { Log "restart: $why"; Stop-Agent }
      if (-not $script:Proc -and -not (Closed $n)) { Start-Safe $n }
    } catch { Log "error: $($_.Exception.Message); going on in ${RestartDelay}s"; Nap $RestartDelay }
  }
} finally { Stop-Agent }
