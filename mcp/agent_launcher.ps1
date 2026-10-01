<#
agent_launcher.ps1 -- the PowerShell port of agent_launcher.sh (Windows; also runs with PowerShell 7 on macOS / Linux).
A reference launcher for an agent host (Claude Code) that follows Kalmido's runtime settings (2.4.1).

Kalmido never runs an agent. An admin only chooses runtime settings in Settings > Agents > (agent) > Runtime and Kalmido
hands them to the agent: GET /api/v1/agent -> "runtime" {model, autocompact, autocompact_pct, nightly_reset, reset_seq,
timezone}. This script runs on the agent's host and applies them:
  - starts the agent command, ALWAYS in a fresh session (never pass --continue / --resume here)
  - model:         appends `--model <model>` (empty = the command's own default)
  - auto-compact:  on + percentage -> CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=<pct>; off -> DISABLE_AUTO_COMPACT=1
  - restarts it (fresh session) when the model / auto-compact settings change, when an admin presses "Reset now"
    (reset_seq goes up), once a night at nightly_reset (HH:MM in runtime.timezone), and whenever the command exits by
    itself (after KALMIDO_RESTART_DELAY seconds)
It polls GET /api/v1/agent every KALMIDO_POLL seconds (default 60): one small request, no events are consumed.

usage: pwsh -File agent_launcher.ps1 [-e ENV_FILE] [--once] [-- COMMAND ...]
  -e ENV_FILE    default .\kalmido-agent.env (readable only by the agent's account), lines KEY=VALUE:
                   KALMIDO_URL=https://tasks.example.com
                   KALMIDO_TOKEN=abk_...          the agent's API token (Settings > Agents)
                 every variable in it is passed to the command too (the MCP server mcp/kalmido_mcp.py reads the same two)
  COMMAND        what to start (default: claude). Example:
                   pwsh -File agent_launcher.ps1 -e $HOME\.config\kalmido\agent.env -- claude -p "Work through your Kalmido events"
  --once         print the command line and environment it would use, then exit (a dry run; the token is never printed)
Needs: Windows PowerShell 5.1 or PowerShell 7+. See docs/AGENTS.md "Set up an agent" for a scheduled task.
#>
# arguments by hand (no param block): everything after "--" (or the first unknown word) is the command, as in the .sh
$EnvFile = '.\kalmido-agent.env'; $Once = $false; $Command = @()
for ($i = 0; $i -lt $args.Count; $i++) {
  $a = [string]$args[$i]
  if ($a -in @('-e', '--env', '-EnvFile')) { $i++; if ($i -ge $args.Count) { [Console]::Error.WriteLine('agent_launcher: -e needs a file'); exit 2 }; $EnvFile = [string]$args[$i] }
  elseif ($a -in @('--once', '-Once')) { $Once = $true }
  elseif ($a -in @('-h', '--help')) { Get-Content -LiteralPath $PSCommandPath -TotalCount 22 | Select-Object -Skip 1; exit 0 }
  elseif ($a -eq '--') { $Command = @($args | Select-Object -Skip ($i + 1) | ForEach-Object { [string]$_ }); break }
  else { $Command = @($args | Select-Object -Skip $i | ForEach-Object { [string]$_ }); break }
}
$ErrorActionPreference = 'Stop'
if ($Command.Count -eq 0) { $Command = @('claude') }
$OnWindows = ($env:OS -eq 'Windows_NT')

function Log([string]$m) { [Console]::Error.WriteLine("$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') agent_launcher: $m") }

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) { Log "cannot read $EnvFile"; exit 2 }
# the env file: KEY=VALUE per line (an optional "export ", quotes around the value), # comments; all go into this
# process's environment, so the command inherits them
foreach ($raw in Get-Content -LiteralPath $EnvFile) {
  $l = $raw.Trim()
  if (-not $l -or $l.StartsWith('#')) { continue }
  if ($l -match '^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
    $v = $Matches[2].Trim()
    if ($v.Length -ge 2 -and (($v[0] -eq '"' -and $v[-1] -eq '"') -or ($v[0] -eq "'" -and $v[-1] -eq "'"))) { $v = $v.Substring(1, $v.Length - 2) }
    [Environment]::SetEnvironmentVariable($Matches[1], $v, 'Process')
  }
}
if (-not $env:KALMIDO_URL) { Log "KALMIDO_URL missing in $EnvFile"; exit 2 }
if (-not $env:KALMIDO_TOKEN) { Log "KALMIDO_TOKEN missing in $EnvFile"; exit 2 }
$Poll = if ($env:KALMIDO_POLL) { [int]$env:KALMIDO_POLL } else { 60 }
$RestartDelay = if ($env:KALMIDO_RESTART_DELAY) { [int]$env:KALMIDO_RESTART_DELAY } else { 10 }
$Url = $env:KALMIDO_URL.TrimEnd('/') + '/api/v1/agent'

# GET /api/v1/agent -> a settings object. A paused agent's token is refused (403): enabled = $false. $null: Kalmido not
# reachable (or another error). The token only goes into the request header.
function Fetch {
  $h = @{ Authorization = "Bearer $($env:KALMIDO_TOKEN)" }
  try {
    $r = Invoke-WebRequest -Uri $Url -Headers $h -TimeoutSec 20 -UseBasicParsing
    $a = $r.Content | ConvertFrom-Json
  } catch {
    $code = $null
    try { $code = [int]$_.Exception.Response.StatusCode } catch { }
    if ($code -eq 403) { return [pscustomobject]@{model = '-'; ac = '-'; pct = '-'; nightly = '-'; seq = $script:Seq; tz = 'UTC'; enabled = $false} }
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
  return [pscustomobject]@{model = $model; ac = $ac; pct = $pct; nightly = $nightly; seq = $seq; tz = $tz; enabled = $en}
}

function Quote([string]$s) {  # one argument for a Windows / .NET command line
  if ($s -eq '') { return '""' }
  if ($s -notmatch '[\s"]') { return $s }
  return '"' + ($s -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

$script:Proc = $null
$script:Started = Get-Date
function Start-Agent($s) {
  $cmdArgs = @($Command)
  if ($s.model -ne '-') { $cmdArgs += @('--model', $s.model) }
  $envs = @()
  if ($s.ac -eq '0') { $envs += 'DISABLE_AUTO_COMPACT=1' } elseif ($s.pct -ne '-') { $envs += "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=$($s.pct)" }
  if ($Once) { Write-Output ("env $($envs -join ' ') $($cmdArgs -join ' ')"); return }
  $acs = if ($s.ac -eq '1') { if ($s.pct -ne '-') { "on at $($s.pct)%" } else { 'on at the default %' } } else { 'off' }
  $mn = if ($s.model -eq '-') { 'default' } else { $s.model }
  Log "starting (fresh session): $($cmdArgs[0]), model $mn, auto-compact $acs"
  Remove-Item Env:DISABLE_AUTO_COMPACT, Env:CLAUDE_AUTOCOMPACT_PCT_OVERRIDE -ErrorAction SilentlyContinue
  foreach ($e in $envs) { $k, $v = $e -split '=', 2; [Environment]::SetEnvironmentVariable($k, $v, 'Process') }
  # resolve the program (claude is claude.cmd / claude.ps1 on Windows): a .ps1 runs through PowerShell, a .cmd / .bat
  # through cmd.exe
  $exe = $cmdArgs[0]; $rest = @($cmdArgs | Select-Object -Skip 1)
  $found = Get-Command $exe -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($found -and $found.Source) { $exe = $found.Source }
  if ($exe -match '\.ps1$') { $rest = @('-NoProfile', '-File', $exe) + $rest; $exe = (Get-Process -Id $PID).Path }
  elseif ($exe -match '\.(cmd|bat)$') { $rest = @('/d', '/c', $exe) + $rest; $exe = $env:ComSpec }
  $p = @{FilePath = $exe; PassThru = $true; NoNewWindow = $true}
  if ($rest.Count) { $p.ArgumentList = ($rest | ForEach-Object { Quote $_ }) -join ' ' }
  $script:Proc = Start-Process @p
  $script:Started = Get-Date
}
function Stop-Agent {
  if (-not $script:Proc) { return }
  $id = $script:Proc.Id
  if (-not $script:Proc.HasExited) {
    if ($OnWindows) { & taskkill.exe /T /PID $id 2>$null | Out-Null }  # the whole tree, politely first
    else { $k = Get-Command kill -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1; if ($k) { & $k.Source -TERM $id 2>$null } else { Stop-Process -Id $id -ErrorAction SilentlyContinue } }  # the program, not the alias
    for ($i = 0; $i -lt 30 -and -not $script:Proc.HasExited; $i++) { Start-Sleep -Seconds 1 }
    if (-not $script:Proc.HasExited) {
      if ($OnWindows) { & taskkill.exe /T /F /PID $id 2>$null | Out-Null } else { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
    }
  }
  $script:Proc = $null
}

function Now-In([string]$tz) {  # the current time in an IANA zone (.NET 6+ also on Windows); unknown -> local time
  try { return [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Now, [TimeZoneInfo]::FindSystemTimeZoneById($tz)) }
  catch { return [DateTimeOffset]::Now }
}
$script:DoneDay = ''  # the day whose nightly restart is done (a start after that time counts)
function Nightly-Due($s) {
  if ($s.nightly -eq '-' -or $s.nightly -notmatch '^(\d{1,2}):(\d{2})$') { return $false }
  $now = Now-In $s.tz
  $day = $now.ToString('yyyy-MM-dd')
  if ($script:DoneDay -eq $day) { return $false }
  $at = New-Object DateTimeOffset ($now.Year, $now.Month, $now.Day, [int]$Matches[1], [int]$Matches[2], 0, $now.Offset)
  if ($now -lt $at) { return $false }
  $script:DoneDay = $day
  return ([DateTimeOffset]$script:Started -lt $at)  # started before tonight's time -> restart now
}

$s = Fetch
if (-not $s) { Log "cannot read the runtime settings from $($env:KALMIDO_URL)"; exit 1 }
$script:Seq = $s.seq
if ($Once) { Start-Agent $s; exit 0 }
$sig = "$($s.model)|$($s.ac)|$($s.pct)"
if ($s.enabled) { Start-Agent $s } else { Log 'the agent is paused in Kalmido; waiting' }
[void](Nightly-Due $s)  # a start after tonight's time already counts as the nightly restart
try {
  while ($true) {
    Start-Sleep -Seconds $Poll
    if ($script:Proc -and $script:Proc.HasExited) {
      $script:Proc = $null
      Log "the command ended; restarting in ${RestartDelay}s"; Start-Sleep -Seconds $RestartDelay
    }
    $n = Fetch
    if (-not $n) { Log 'Kalmido not reachable; keeping the agent as it is'; continue }
    $why = ''
    if ($n.seq -ne $script:Seq) { $why = "reset now ($($script:Seq) -> $($n.seq))" }
    if (-not $why -and "$($n.model)|$($n.ac)|$($n.pct)" -ne $sig) { $why = 'runtime settings changed' }
    if (-not $why -and (Nightly-Due $n)) { $why = "nightly fresh restart ($($n.nightly) $($n.tz))" }
    $script:Seq = $n.seq; $sig = "$($n.model)|$($n.ac)|$($n.pct)"
    if (-not $n.enabled) {
      if ($script:Proc) { Log 'paused in Kalmido: stopping'; Stop-Agent }
      continue
    }
    if ($why -and $script:Proc) { Log "restart: $why"; Stop-Agent }
    if (-not $script:Proc) { Start-Agent $n }
  }
} finally { Stop-Agent }
