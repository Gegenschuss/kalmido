<#
agent-setup.ps1 -- set up a Kalmido project agent on Windows with one command (2.44.0, #1517).

Kalmido shows the command in Settings > Agents > (agent) > "Set up on a computer", e.g. (PowerShell):
  & ([scriptblock]::Create((irm https://tasks.example.com/agent-setup.ps1))) -Url https://tasks.example.com -Code ks_... -Dir "$HOME\projects\site"
It trades the one-time setup code for the agent's token (stored in a file only your Windows account can read, never
printed), fetches the starter files (mcp/starter_files.txt) and starts the agent in event mode at every login, hidden, with
the Task Scheduler (no admin rights; when the Task Scheduler refuses, a hidden entry in your Startup folder). One instance
per project folder. Needs: Windows PowerShell 5.1 or PowerShell 7, Python 3.9+, the agent command (default: claude).

  -Url          your Kalmido address
  -Code         the one-time setup code (15 minutes, works once; make a new one in Kalmido when it expired)
  -Dir          the project folder the agent works in (created when missing)
  -Cmd          the agent command (default claude); it gets --mcp-config with the Kalmido MCP server
  -From DIR     take the starter files from a local copy of mcp\ instead of downloading them
  -NoAutostart  install everything but the autostart
  -Lang         language of the messages: de or en (Kalmido adds the language of your account; anything else = en)
  -DryRun       only show what would happen: no code is redeemed, nothing is written, no task is registered
  -Uninstall    stop and remove the autostart, revoke this computer's token in Kalmido, delete the instance folder
Files: %LOCALAPPDATA%\Kalmido\agents\<folder name>-<hash>\ (starter files, kalmido-agent.env, mcp.json, agent.log).
#>
param([string]$Url = '', [string]$Code = '', [string]$Dir = '', [string]$Cmd = 'claude', [string]$From = '',
      [switch]$NoAutostart, [switch]$DryRun, [switch]$Uninstall, [string]$Lang = 'en')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is slow with the progress bar in 5.1
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

# 2.46.6 (#1713): messages in German or English (-Lang); anything else = English. M 'key' args... formats with -f.
$script:LangDe = ($Lang.ToLowerInvariant() -like 'de*')
$MsgEn = @{
  wrongos = 'this script is for Windows; on macOS and Linux use agent-setup.sh (Kalmido shows that command when you pick Mac or Linux)'
  undone = 'undone (the token is revoked again)'
  s_prereq = 'Checking what is needed'
  py = '  - Python 3.9 or newer: winget install Python.Python.3.12  (then open a new PowerShell window)'
  claude = '  - Claude Code: irm https://claude.ai/install.ps1 | iex  and then  claude  once to log in'
  cmd = '  - the agent command {0}'
  missing = 'missing on this computer:\n{0}\nInstall it and run the same command again (make a new code in Kalmido if 15 minutes have passed).'
  agentcmd = '  agent command: {0}'
  notlogged = '  note: Claude Code seems not logged in yet; run  claude  once and log in'
  nodir = '-Dir FOLDER is missing (the project folder the agent works in)'
  folder = '  project folder: {0}'
  instance = '  instance: {0}'
  rev_ok = '  this computer is removed in Kalmido (its token no longer works)'
  rev_fail = '  Kalmido did not answer: remove the computer in Settings > Agents if it is still listed'
  dry_stop = '  (dry run) stop and remove the task ''{0}'' and {1}'
  s_uninstall = 'Removing the agent of {0} from this computer'
  dry_revoke = '  (dry run) revoke this computer''s token in Kalmido and delete {0}'
  uninstalled = 'Done. The project folder itself stays as it is.'
  nourl = '-Url is missing (your Kalmido address)'
  nocode = '-Code is missing (the one-time code from Kalmido)'
  s_connect = 'Connecting to Kalmido'
  dry_redeem = '  (dry run) trade the code for the agent''s token at {0}/api/agent-setup/redeem (computer {1})'
  refused = 'Kalmido refused the code or is not reachable: {0} (nothing was installed)'
  agent = '  agent: {0}, token stored in {1} (only readable for you)'
  s_starter = 'Fetching the starter files'
  dry_files = '  (dry run) the files of {0}/starter_files.txt into {1}'
  nobase = 'Kalmido sent no address for the starter files; use -From DIR'
  nolist = 'no starter_files.txt in {0}'
  nolistfetch = 'cannot fetch the starter file list ({0}starter_files.txt); this version may not be published yet - try again later or use -From DIR'
  skippath = '  skipped {0} (no paths allowed)'
  nofetch = 'cannot fetch {0}'
  skipfile = '  {0} not available (skipped)'
  dry_mcp = '  (dry run) write {0} (MCP server kalmido: {1} {2})'
  s_auto = 'Starting it at every login'
  noauto = '  skipped (-NoAutostart); start it with:'
  dry_task = '  (dry run) task ''\Kalmido\{0}'' at logon of {1}, hidden: {2} {3}'
  taskok = '  task ''\Kalmido\{0}'' (starts at login, hidden, restarts after a crash; log: {1})'
  taskfail = '  the Task Scheduler refused ({0}); using your Startup folder instead'
  startupok = '  Startup folder entry {0} (starts at login; log: {1})'
  s_done = 'Done'
  done1 = 'Kalmido shows the computer under Settings > Agents within a minute (green dot = connected).'
  done2 = 'Remove it again:  & ([scriptblock]::Create((irm {0}/agent-setup.ps1))) -Uninstall -Dir {1}'
}
$MsgDe = @{
  wrongos = 'dieses Skript ist für Windows; unter macOS und Linux nimm agent-setup.sh (Kalmido zeigt den Befehl, wenn du Mac oder Linux wählst)'
  undone = 'rückgängig gemacht (das Token ist wieder gesperrt)'
  s_prereq = 'Prüfe, was gebraucht wird'
  py = '  - Python 3.9 oder neuer: winget install Python.Python.3.12  (danach ein neues PowerShell-Fenster öffnen)'
  claude = '  - Claude Code: irm https://claude.ai/install.ps1 | iex  und danach einmal  claude  zum Anmelden'
  cmd = '  - der Agent-Befehl {0}'
  missing = 'auf diesem Computer fehlt noch:\n{0}\nInstalliere es und führe denselben Befehl noch einmal aus (erzeuge in Kalmido einen neuen Code, wenn 15 Minuten vorbei sind).'
  agentcmd = '  Agent-Befehl: {0}'
  notlogged = '  Hinweis: Claude Code scheint noch nicht angemeldet zu sein; führe  claude  einmal aus und melde dich an'
  nodir = '-Dir ORDNER fehlt (der Projektordner, in dem der Agent arbeitet)'
  folder = '  Projektordner: {0}'
  instance = '  Instanz: {0}'
  rev_ok = '  dieser Computer ist in Kalmido entfernt (sein Token funktioniert nicht mehr)'
  rev_fail = '  Kalmido hat nicht geantwortet: entferne den Computer unter Einstellungen > Agenten, falls er noch aufgelistet ist'
  dry_stop = '  (Probelauf) die Aufgabe ''{0}'' und {1} stoppen und entfernen'
  s_uninstall = 'Entferne den Agenten von {0} von diesem Computer'
  dry_revoke = '  (Probelauf) das Token dieses Computers in Kalmido sperren und {0} löschen'
  uninstalled = 'Fertig. Der Projektordner selbst bleibt unverändert.'
  nourl = '-Url fehlt (deine Kalmido-Adresse)'
  nocode = '-Code fehlt (der einmalige Code aus Kalmido)'
  s_connect = 'Verbinde mit Kalmido'
  dry_redeem = '  (Probelauf) den Code gegen das Token des Agenten tauschen unter {0}/api/agent-setup/redeem (Computer {1})'
  refused = 'Kalmido hat den Code abgelehnt oder ist nicht erreichbar: {0} (es wurde nichts installiert)'
  agent = '  Agent: {0}, Token gespeichert in {1} (nur für dich lesbar)'
  s_starter = 'Lade die Starter-Dateien'
  dry_files = '  (Probelauf) die Dateien aus {0}/starter_files.txt nach {1}'
  nobase = 'Kalmido hat keine Adresse für die Starter-Dateien geschickt; nimm -From ORDNER'
  nolist = 'keine starter_files.txt in {0}'
  nolistfetch = 'die Liste der Starter-Dateien ({0}starter_files.txt) kann nicht geladen werden; diese Version ist vielleicht noch nicht veröffentlicht – versuche es später noch einmal oder nimm -From ORDNER'
  skippath = '  {0} übersprungen (keine Pfade erlaubt)'
  nofetch = '{0} kann nicht geladen werden'
  skipfile = '  {0} nicht verfügbar (übersprungen)'
  dry_mcp = '  (Probelauf) {0} schreiben (MCP-Server kalmido: {1} {2})'
  s_auto = 'Starte bei jeder Anmeldung'
  noauto = '  übersprungen (-NoAutostart); starte es mit:'
  dry_task = '  (Probelauf) Aufgabe ''\Kalmido\{0}'' bei der Anmeldung von {1}, unsichtbar: {2} {3}'
  taskok = '  Aufgabe ''\Kalmido\{0}'' (startet bei der Anmeldung, unsichtbar, startet nach einem Absturz neu; Protokoll: {1})'
  taskfail = '  die Aufgabenplanung hat abgelehnt ({0}); nehme stattdessen deinen Autostart-Ordner'
  startupok = '  Eintrag im Autostart-Ordner {0} (startet bei der Anmeldung; Protokoll: {1})'
  s_done = 'Fertig'
  done1 = 'Kalmido zeigt den Computer innerhalb einer Minute unter Einstellungen > Agenten (grüner Punkt = verbunden).'
  done2 = 'Wieder entfernen:  & ([scriptblock]::Create((irm {0}/agent-setup.ps1))) -Uninstall -Dir {1}'
}
function M([string]$k, [object[]]$a = @()) { $t = if ($script:LangDe -and $MsgDe.ContainsKey($k)) { $MsgDe[$k] } else { $MsgEn[$k] }; $t = $t.Replace('\n', "`n"); if ($a.Count) { $t -f $a } else { $t } }
function Say([string]$m) { Write-Host $m }
function Step([string]$m) { Write-Host ''; Write-Host "== $m" }
$script:Redeemed = $false
function Die([string]$m) {
  [Console]::Error.WriteLine("agent-setup: $m")
  if ($script:Redeemed) { Revoke; Remove-Item -LiteralPath $Inst -Recurse -Force -ErrorAction SilentlyContinue; [Console]::Error.WriteLine('agent-setup: ' + (M 'undone')) }
  exit 1
}
$OnWindows = ($env:OS -eq 'Windows_NT')
if (-not $OnWindows -and -not $DryRun) { Die (M 'wrongos') }

# kalmido-setup-step: prereq
Step (M 's_prereq')
$missing = @()
$Py = $null; $PyArgs = @()
foreach ($n in @('py', 'python', 'python3')) {  # python3 may be the Microsoft Store stub: the version check sorts it out
  $c = Get-Command $n -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $c) { continue }
  $pa = @(); if ($n -eq 'py') { $pa = @('-3') }
  try { & $c.Source @pa -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>$null; if ($LASTEXITCODE -eq 0) { $Py = $c.Source; $PyArgs = $pa; break } } catch { }
}
if (-not $Py) { $missing += (M 'py') }
$Agent = $null
if (-not $Uninstall) {
  $c = Get-Command $Cmd -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) { $Agent = $c.Source }
  foreach ($p in @("$env:USERPROFILE\.local\bin\$Cmd.exe", "$env:USERPROFILE\.claude\local\$Cmd.exe")) { if (-not $Agent -and (Test-Path -LiteralPath $p)) { $Agent = $p } }
  if (-not $Agent) {
    if ($Cmd -eq 'claude') { $missing += (M 'claude') }
    else { $missing += (M 'cmd' @($Cmd)) }
  }
}
if ($missing.Count) {
  [Console]::Error.WriteLine('agent-setup: ' + (M 'missing' @($missing -join "`n")))
  if (-not $DryRun) { exit 1 }
}
if ($Agent) { Say (M 'agentcmd' @($Agent)) }
if ($Cmd -eq 'claude' -and $Agent -and -not (Test-Path -LiteralPath "$env:USERPROFILE\.claude")) { Say (M 'notlogged') }

# kalmido-setup-step: instance
if (-not $Dir) { Die (M 'nodir') }
$Dir = $Dir -replace '^(\$HOME|\$env:USERPROFILE|%USERPROFILE%)(?=$|[\\/])', '~'  # 2.44.0 (review): a typed $HOME is no literal folder name
if ($Dir -eq '~' -or $Dir.StartsWith('~\') -or $Dir.StartsWith('~/')) { $Dir = $HOME + $Dir.Substring(1) }
$Dir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Dir).TrimEnd('\', '/')  # relative to the PowerShell location (5.1: GetFullPath would use the process directory)
$leaf = ([IO.Path]::GetFileName($Dir) -replace '[^A-Za-z0-9_.-]', '-'); if ($leaf.Length -gt 40) { $leaf = $leaf.Substring(0, 40) }
$sha = [Security.Cryptography.SHA1]::Create()
$hash = (($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Dir.ToLowerInvariant())) | Select-Object -First 4 | ForEach-Object { $_.ToString('x2') }) -join '')
$Slug = "$leaf-$hash"
$LocalBase = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME '.kalmido' }
$Inst = Join-Path (Join-Path (Join-Path $LocalBase 'Kalmido') 'agents') $Slug
$TaskName = "Kalmido agent $Slug"
$StartupDir = if ($env:APPDATA) { Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup' } else { Join-Path $HOME 'Startup' }
$StartupCmd = Join-Path $StartupDir "kalmido-agent-$Slug.cmd"
$EnvF = Join-Path $Inst 'kalmido-agent.env'
Say (M 'folder' @($Dir))
Say (M 'instance' @($Inst))

# revoke: this computer's token is revoked in Kalmido (POST /api/agent-setup/remove with the token itself)
function Revoke {
  if (-not (Test-Path -LiteralPath $EnvF)) { return }
  $e = @{}
  foreach ($l in Get-Content -LiteralPath $EnvF) { if ($l -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $e[$Matches[1]] = $Matches[2] } }
  try {
    Invoke-RestMethod -Method Post -Uri ($e['KALMIDO_URL'].TrimEnd('/') + '/api/agent-setup/remove') -Body '{}' -ContentType 'application/json' `
      -Headers @{ Authorization = "Bearer $($e['KALMIDO_TOKEN'])"; 'X-Requested-With' = 'kalmido' } -TimeoutSec 20 | Out-Null
    Say (M 'rev_ok')
  } catch { Say (M 'rev_fail') }
}

# kalmido-setup-step: autostart_stop
function Stop-Autostart {
  if ($DryRun) { Say (M 'dry_stop' @($TaskName, $StartupCmd)); return }
  if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
    $t = Get-ScheduledTask -TaskPath '\Kalmido\' -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($t) { Stop-ScheduledTask -InputObject $t -ErrorAction SilentlyContinue; Unregister-ScheduledTask -InputObject $t -Confirm:$false }
  }
  if (Test-Path -LiteralPath $StartupCmd) { Remove-Item -LiteralPath $StartupCmd -Force }
  # the launcher of an earlier setup of this folder (its command line names the instance folder)
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($Inst) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

if ($Uninstall) {
  # kalmido-setup-step: uninstall
  Step (M 's_uninstall' @($Dir))
  Stop-Autostart
  if ($DryRun) { Say (M 'dry_revoke' @($Inst)) }
  else { Revoke; if (Test-Path -LiteralPath $Inst) { Remove-Item -LiteralPath $Inst -Recurse -Force } }
  Say (M 'uninstalled')
  exit 0
}

if (-not $Url) { Die (M 'nourl') }
if (-not $Code -and -not $DryRun) { Die (M 'nocode') }
$Url = $Url.TrimEnd('/')

# kalmido-setup-step: redeem
Step (M 's_connect')
$HostN = ([Environment]::MachineName -split '\.')[0]
$StarterBase = ''
if ($DryRun) { Say (M 'dry_redeem' @($Url, $HostN)) }
else {
  New-Item -ItemType Directory -Force -Path $Inst | Out-Null
  # only this Windows account may read the instance folder (inheritance off, one rule for the current user)
  $acl = Get-Acl -LiteralPath $Inst
  $acl.SetAccessRuleProtection($true, $false)
  foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRule($rule) }
  $me = [Security.Principal.WindowsIdentity]::GetCurrent().User
  $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($me, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
  Set-Acl -LiteralPath $Inst -AclObject $acl
  $body = @{ code = $Code.Trim(); host = $HostN; folder = $Dir; os = 'windows' } | ConvertTo-Json -Compress
  try {
    $r = Invoke-RestMethod -Method Post -Uri "$Url/api/agent-setup/redeem" -Body $body -ContentType 'application/json' -Headers @{ 'X-Requested-With' = 'kalmido' } -TimeoutSec 30
  } catch {
    $msg = ''; try { $msg = ($_.ErrorDetails.Message | ConvertFrom-Json).error } catch { }
    Die (M 'refused' @($(if ($msg) { $msg } else { $_.Exception.Message })))
  }
  $lines = @("# Kalmido agent $($r.agent.name) ($($r.agent.username)), set up by agent-setup.ps1 -- keep this file private",
             "KALMIDO_URL=$Url", "KALMIDO_TOKEN=$($r.token)", 'KALMIDO_EVENTS=1',
             "KALMIDO_STATE_DIR=$(Join-Path $Inst 'state')")  # one state folder per instance (cursor, approvals, lock)
  [IO.File]::WriteAllLines($EnvF, $lines)
  $script:Redeemed = $true
  $StarterBase = [string]$r.starter_base
  Say (M 'agent' @($r.agent.name, $EnvF))
}

# kalmido-setup-step: starter_files
Step (M 's_starter')
$Required = @('agent_launcher.ps1', 'agent_run.py', 'kalmido_mcp.py')
function Fetch([string]$name, [string]$dest) {
  if ($From) { $src = Join-Path $From $name; if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $dest -Force; return $true }; return $false }
  try { Invoke-WebRequest -Uri ($StarterBase + $name) -OutFile $dest -UseBasicParsing -TimeoutSec 60; return $true } catch { return $false }
}
if ($DryRun) { Say (M 'dry_files' @($(if ($From) { $From } else { 'starter' }), $Inst)) }
else {
  if (-not $From -and -not $StarterBase) { Die (M 'nobase') }
  $list = Join-Path $Inst 'starter_files.txt'
  if (-not (Fetch 'starter_files.txt' $list)) {
    if ($From) { Die (M 'nolist' @($From)) }
    # 2.44.0 (review): no fallback to another branch -- the starter must match this instance's version
    Die (M 'nolistfetch' @($StarterBase))
  }
  foreach ($raw in Get-Content -LiteralPath $list) {
    $f = ($raw -replace '#.*$', '').Trim()
    if (-not $f) { continue }
    if ($f.Contains('/') -or $f.Contains('\') -or $f.StartsWith('..')) { Say (M 'skippath' @($f)); continue }
    if (Fetch $f (Join-Path $Inst $f)) { Say "  $f" }
    elseif ($Required -contains $f) { Die (M 'nofetch' @($f)) }
    else { Say (M 'skipfile' @($f)) }
  }
}

# kalmido-setup-step: mcp_config
# the agent command gets the MCP server with --mcp-config (works headless without a trust prompt); the token comes from the
# launcher's environment, so it is in no config file but the env file
$McpJ = Join-Path $Inst 'mcp.json'
$pyArgsJ = @($PyArgs + @((Join-Path $Inst 'kalmido_mcp.py')))
if ($DryRun) { Say (M 'dry_mcp' @($McpJ, $Py, ($pyArgsJ -join ' '))) }
else {
  $mcp = @{ mcpServers = @{ kalmido = @{ command = $Py; args = $pyArgsJ } } } | ConvertTo-Json -Depth 5
  [IO.File]::WriteAllText($McpJ, $mcp)
}
if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $Dir | Out-Null }

# kalmido-setup-step: autostart
Step (M 's_auto')
function Q([string]$s) { "'" + $s.Replace("'", "''") + "'" }
$PsExe = (Get-Process -Id $PID).Path
$Log = Join-Path $Inst 'agent.log'
$Inner = "Set-Location -LiteralPath $(Q $Dir); & $(Q (Join-Path $Inst 'agent_launcher.ps1')) -e $(Q $EnvF) --events -- $(Q $(if ($Agent) { $Agent } else { $Cmd })) --mcp-config $(Q $McpJ) *>> $(Q $Log)"
$PsArgs = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$Inner`""
if ($NoAutostart) { Say (M 'noauto'); Say "  $Inner" }
else {
  Stop-Autostart
  if ($DryRun) { Say (M 'dry_task' @($TaskName, $env:USERNAME, $PsExe, $PsArgs)) }
  else {
    $done = $false
    try {
      $user = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
      $action = New-ScheduledTaskAction -Execute $PsExe -Argument $PsArgs -WorkingDirectory $Dir
      $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
      $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -Hidden
      $prin = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
      Register-ScheduledTask -TaskPath '\Kalmido\' -TaskName $TaskName -Action $action -Trigger $trigger -Settings $set -Principal $prin -Force | Out-Null
      Start-ScheduledTask -TaskPath '\Kalmido\' -TaskName $TaskName
      $done = $true
      Say (M 'taskok' @($TaskName, $Log))
    } catch { Say (M 'taskfail' @($_.Exception.Message)) }
    if (-not $done) {
      New-Item -ItemType Directory -Force -Path $StartupDir | Out-Null
      [IO.File]::WriteAllLines($StartupCmd, @('@echo off', "start `"`" /min `"$PsExe`" $PsArgs"))
      Start-Process -FilePath $PsExe -ArgumentList $PsArgs -WindowStyle Hidden
      Say (M 'startupok' @($StartupCmd, $Log))
    }
  }
}

# kalmido-setup-step: done
Step (M 's_done')
Say (M 'done1')
Say (M 'done2' @($Url, (Q $Dir)))
