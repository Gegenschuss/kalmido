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
  -DryRun       only show what would happen: no code is redeemed, nothing is written, no task is registered
  -Uninstall    stop and remove the autostart, revoke this computer's token in Kalmido, delete the instance folder
Files: %LOCALAPPDATA%\Kalmido\agents\<folder name>-<hash>\ (starter files, kalmido-agent.env, mcp.json, agent.log).
#>
param([string]$Url = '', [string]$Code = '', [string]$Dir = '', [string]$Cmd = 'claude', [string]$From = '',
      [switch]$NoAutostart, [switch]$DryRun, [switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is slow with the progress bar in 5.1
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

function Say([string]$m) { Write-Host $m }
function Step([string]$m) { Write-Host ''; Write-Host "== $m" }
$script:Redeemed = $false
function Die([string]$m) {
  [Console]::Error.WriteLine("agent-setup: $m")
  if ($script:Redeemed) { Revoke; Remove-Item -LiteralPath $Inst -Recurse -Force -ErrorAction SilentlyContinue; [Console]::Error.WriteLine('agent-setup: undone (the token is revoked again)') }
  exit 1
}
$OnWindows = ($env:OS -eq 'Windows_NT')
if (-not $OnWindows -and -not $DryRun) { Die 'this script is for Windows; on macOS and Linux use agent-setup.sh (Kalmido shows that command when you pick Mac or Linux)' }

# kalmido-setup-step: prereq
Step 'Checking what is needed'
$missing = @()
$Py = $null; $PyArgs = @()
foreach ($n in @('py', 'python', 'python3')) {  # python3 may be the Microsoft Store stub: the version check sorts it out
  $c = Get-Command $n -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $c) { continue }
  $pa = @(); if ($n -eq 'py') { $pa = @('-3') }
  try { & $c.Source @pa -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>$null; if ($LASTEXITCODE -eq 0) { $Py = $c.Source; $PyArgs = $pa; break } } catch { }
}
if (-not $Py) { $missing += '  - Python 3.9 or newer: winget install Python.Python.3.12  (then open a new PowerShell window)' }
$Agent = $null
if (-not $Uninstall) {
  $c = Get-Command $Cmd -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) { $Agent = $c.Source }
  foreach ($p in @("$env:USERPROFILE\.local\bin\$Cmd.exe", "$env:USERPROFILE\.claude\local\$Cmd.exe")) { if (-not $Agent -and (Test-Path -LiteralPath $p)) { $Agent = $p } }
  if (-not $Agent) {
    if ($Cmd -eq 'claude') { $missing += '  - Claude Code: irm https://claude.ai/install.ps1 | iex  and then  claude  once to log in' }
    else { $missing += "  - the agent command $Cmd" }
  }
}
if ($missing.Count) {
  [Console]::Error.WriteLine("agent-setup: missing on this computer:`n$($missing -join "`n")`nInstall it and run the same command again (make a new code in Kalmido if 15 minutes have passed).")
  if (-not $DryRun) { exit 1 }
}
if ($Agent) { Say "  agent command: $Agent" }
if ($Cmd -eq 'claude' -and $Agent -and -not (Test-Path -LiteralPath "$env:USERPROFILE\.claude")) { Say '  note: Claude Code seems not logged in yet; run  claude  once and log in' }

# kalmido-setup-step: instance
if (-not $Dir) { Die '-Dir FOLDER is missing (the project folder the agent works in)' }
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
Say "  project folder: $Dir"
Say "  instance: $Inst"

# revoke: this computer's token is revoked in Kalmido (POST /api/agent-setup/remove with the token itself)
function Revoke {
  if (-not (Test-Path -LiteralPath $EnvF)) { return }
  $e = @{}
  foreach ($l in Get-Content -LiteralPath $EnvF) { if ($l -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $e[$Matches[1]] = $Matches[2] } }
  try {
    Invoke-RestMethod -Method Post -Uri ($e['KALMIDO_URL'].TrimEnd('/') + '/api/agent-setup/remove') -Body '{}' -ContentType 'application/json' `
      -Headers @{ Authorization = "Bearer $($e['KALMIDO_TOKEN'])"; 'X-Requested-With' = 'kalmido' } -TimeoutSec 20 | Out-Null
    Say '  this computer is removed in Kalmido (its token no longer works)'
  } catch { Say '  Kalmido did not answer: remove the computer in Settings > Agents if it is still listed' }
}

# kalmido-setup-step: autostart_stop
function Stop-Autostart {
  if ($DryRun) { Say "  (dry run) stop and remove the task '$TaskName' and $StartupCmd"; return }
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
  Step "Removing the agent of $Dir from this computer"
  Stop-Autostart
  if ($DryRun) { Say "  (dry run) revoke this computer's token in Kalmido and delete $Inst" }
  else { Revoke; if (Test-Path -LiteralPath $Inst) { Remove-Item -LiteralPath $Inst -Recurse -Force } }
  Say 'Done. The project folder itself stays as it is.'
  exit 0
}

if (-not $Url) { Die '-Url is missing (your Kalmido address)' }
if (-not $Code -and -not $DryRun) { Die '-Code is missing (the one-time code from Kalmido)' }
$Url = $Url.TrimEnd('/')

# kalmido-setup-step: redeem
Step 'Connecting to Kalmido'
$HostN = ([Environment]::MachineName -split '\.')[0]
$StarterBase = ''
if ($DryRun) { Say "  (dry run) trade the code for the agent's token at $Url/api/agent-setup/redeem (computer $HostN)" }
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
    Die "Kalmido refused the code or is not reachable: $(if ($msg) { $msg } else { $_.Exception.Message }) (nothing was installed)"
  }
  $lines = @("# Kalmido agent $($r.agent.name) ($($r.agent.username)), set up by agent-setup.ps1 -- keep this file private",
             "KALMIDO_URL=$Url", "KALMIDO_TOKEN=$($r.token)", 'KALMIDO_EVENTS=1')
  [IO.File]::WriteAllLines($EnvF, $lines)
  $script:Redeemed = $true
  $StarterBase = [string]$r.starter_base
  Say "  agent: $($r.agent.name), token stored in $EnvF (only readable for you)"
}

# kalmido-setup-step: starter_files
Step 'Fetching the starter files'
$Required = @('agent_launcher.ps1', 'agent_run.py', 'kalmido_mcp.py')
function Fetch([string]$name, [string]$dest) {
  if ($From) { $src = Join-Path $From $name; if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $dest -Force; return $true }; return $false }
  try { Invoke-WebRequest -Uri ($StarterBase + $name) -OutFile $dest -UseBasicParsing -TimeoutSec 60; return $true } catch { return $false }
}
if ($DryRun) { Say "  (dry run) the files of $(if ($From) { $From } else { 'the starter' })/starter_files.txt into $Inst" }
else {
  if (-not $From -and -not $StarterBase) { Die 'Kalmido sent no address for the starter files; use -From DIR' }
  $list = Join-Path $Inst 'starter_files.txt'
  if (-not (Fetch 'starter_files.txt' $list)) {
    if ($From) { Die "no starter_files.txt in $From" }
    $StarterBase = $StarterBase -replace '/v[0-9][^/]*/mcp/$', '/main/mcp/'
    Say "  this version's files are not published yet; trying $StarterBase"
    if (-not (Fetch 'starter_files.txt' $list)) { Die "cannot fetch the starter file list (${StarterBase}starter_files.txt)" }
  }
  foreach ($raw in Get-Content -LiteralPath $list) {
    $f = ($raw -replace '#.*$', '').Trim()
    if (-not $f) { continue }
    if ($f.Contains('/') -or $f.Contains('\') -or $f.StartsWith('..')) { Say "  skipped $f (no paths allowed)"; continue }
    if (Fetch $f (Join-Path $Inst $f)) { Say "  $f" }
    elseif ($Required -contains $f) { Die "cannot fetch $f" }
    else { Say "  $f not available (skipped)" }
  }
}

# kalmido-setup-step: mcp_config
# the agent command gets the MCP server with --mcp-config (works headless without a trust prompt); the token comes from the
# launcher's environment, so it is in no config file but the env file
$McpJ = Join-Path $Inst 'mcp.json'
$pyArgsJ = @($PyArgs + @((Join-Path $Inst 'kalmido_mcp.py')))
if ($DryRun) { Say "  (dry run) write $McpJ (MCP server kalmido: $Py $($pyArgsJ -join ' '))" }
else {
  $mcp = @{ mcpServers = @{ kalmido = @{ command = $Py; args = $pyArgsJ } } } | ConvertTo-Json -Depth 5
  [IO.File]::WriteAllText($McpJ, $mcp)
}
if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $Dir | Out-Null }

# kalmido-setup-step: autostart
Step 'Starting it at every login'
function Q([string]$s) { "'" + $s.Replace("'", "''") + "'" }
$PsExe = (Get-Process -Id $PID).Path
$Log = Join-Path $Inst 'agent.log'
$Inner = "Set-Location -LiteralPath $(Q $Dir); & $(Q (Join-Path $Inst 'agent_launcher.ps1')) -e $(Q $EnvF) --events -- $(Q $(if ($Agent) { $Agent } else { $Cmd })) --mcp-config $(Q $McpJ) *>> $(Q $Log)"
$PsArgs = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$Inner`""
if ($NoAutostart) { Say '  skipped (-NoAutostart); start it with:'; Say "  $Inner" }
else {
  Stop-Autostart
  if ($DryRun) { Say "  (dry run) task '\Kalmido\$TaskName' at logon of $env:USERNAME, hidden: $PsExe $PsArgs" }
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
      Say "  task '\Kalmido\$TaskName' (starts at login, hidden, restarts after a crash; log: $Log)"
    } catch { Say "  the Task Scheduler refused ($($_.Exception.Message)); using your Startup folder instead" }
    if (-not $done) {
      New-Item -ItemType Directory -Force -Path $StartupDir | Out-Null
      [IO.File]::WriteAllLines($StartupCmd, @('@echo off', "start `"`" /min `"$PsExe`" $PsArgs"))
      Start-Process -FilePath $PsExe -ArgumentList $PsArgs -WindowStyle Hidden
      Say "  Startup folder entry $StartupCmd (starts at login; log: $Log)"
    }
  }
}

# kalmido-setup-step: done
Step 'Done'
Say 'Kalmido shows the computer under Settings > Agents within a minute (green dot = connected).'
Say "Remove it again:  & ([scriptblock]::Create((irm $Url/agent-setup.ps1))) -Uninstall -Dir $(Q $Dir)"
