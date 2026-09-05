<#
.SYNOPSIS
    Register (or remove) the Fitness Tracker as a Windows scheduled task so it
    starts automatically and keeps running with no console window.

.DESCRIPTION
    Task Scheduler is used rather than a Startup-folder shortcut because it can
    start the app at boot, restart it if it dies, and run it without a visible
    terminal. The task invokes the venv's pythonw.exe by absolute path, so no
    environment ever has to be activated.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install_autostart.ps1
    powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    # AtStartup runs before anyone logs in but needs elevation to register.
    # AtLogon works without elevation, which suits a desktop that gets signed in.
    [ValidateSet('AtLogon', 'AtStartup')]
    [string]$Trigger = 'AtLogon',
    [int]$DelaySeconds = 20,
    # How often the watchdog re-checks that the app is still running.
    [int]$WatchdogMinutes = 5,
    # Also register a monthly task to renew the Tailscale/Let's Encrypt cert.
    [switch]$WithCertRenewal,
    [string]$CertDomain = 'datainmind.taila2c133.ts.net'
)

$ErrorActionPreference = 'Stop'
$TaskName = 'FitnessTracker'
$ProjectDir = $PSScriptRoot
$Pythonw = Join-Path $ProjectDir '.venv\Scripts\pythonw.exe'
$Entry = Join-Path $ProjectDir 'service.py'

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Yellow
    } else {
        Write-Host "No scheduled task named '$TaskName'." -ForegroundColor Yellow
    }
    return
}

# --- preflight -------------------------------------------------------------
if (-not (Test-Path $Pythonw)) {
    throw "Virtual environment missing. Run first:`n  python -m venv .venv`n  .venv\Scripts\python.exe -m pip install -r requirements.txt"
}
if (-not (Test-Path $Entry)) { throw "service.py not found in $ProjectDir" }

# Fail now, with a readable message, rather than at 3am on the next reboot.
# The probe uses python.exe, not pythonw.exe: pythonw is a GUI-subsystem binary,
# so PowerShell does not wait for it and $LASTEXITCODE never reflects its result.
$PythonExe = Join-Path $ProjectDir '.venv\Scripts\python.exe'
& $PythonExe -c "import fastapi, uvicorn, httpx, PIL, dotenv, multipart, tzdata"
if ($LASTEXITCODE -ne 0) {
    throw "The venv is missing dependencies. Run: .venv\Scripts\python.exe -m pip install -r requirements.txt"
}

# --- build the task --------------------------------------------------------
$action = New-ScheduledTaskAction -Execute $Pythonw -Argument "`"$Entry`"" -WorkingDirectory $ProjectDir

$delay = "PT$($DelaySeconds)S"
if ($Trigger -eq 'AtStartup') {
    $trg = New-ScheduledTaskTrigger -AtStartup
} else {
    $trg = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
}
# Ollama and Docker are also starting at this moment; a short delay keeps the
# first health check from racing them.
$trg.Delay = $delay

# Watchdog, registered as a SECOND trigger rather than a repetition on the first.
#
# Two things were tested and did not work:
#   * -RestartCount only fires when the action exits with a failure code, which a
#     hard kill does not reliably produce; the task went to Ready and stayed down.
#   * Adding a repetition to the logon trigger without a RepetitionDuration left
#     NextRunTime empty -- Windows scheduled no repeat at all, and a logon
#     trigger's repetition does not re-arm once the task has ended anyway.
#
# An independent Once trigger with an explicit indefinite duration does repeat
# forever and survives the task ending. With MultipleInstances=IgnoreNew below,
# a repeat while the app is healthy is a no-op; if it died it is restarted
# within $WatchdogMinutes.
# 10 years, not [TimeSpan]::MaxValue: MaxValue serialises to P99999999DT23H59M59S,
# which Task Scheduler rejects outright ("value ... incorrectly formatted or out
# of range"). P3650D is accepted and is indefinite for any practical purpose.
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $WatchdogMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$triggers = @($trg, $watchdog)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 3 `
    -ExecutionTimeLimit ([TimeSpan]::Zero)   # long-running service: never time it out

$principal = if ($Trigger -eq 'AtStartup') {
    # SYSTEM so it runs with no session; requires an elevated shell to register.
    New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
} else {
    New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
    -Settings $settings -Principal $principal `
    -Description 'Self-hosted calorie and body progress tracker' | Out-Null

Write-Host "Registered '$TaskName' ($Trigger, ${DelaySeconds}s delay, ${WatchdogMinutes}min watchdog)." -ForegroundColor Green
Write-Host "  python : $Pythonw"
Write-Host "  entry  : $Entry"
Write-Host "  logs   : $(Join-Path $ProjectDir 'logs\tracker.log')"
Write-Host ""
Write-Host "Starting it now..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 6
$state = (Get-ScheduledTask -TaskName $TaskName).State
Write-Host "Task state: $state"
Write-Host ""
Write-Host "Verify with:  Invoke-RestMethod http://localhost:8010/api/health | Format-List"
Write-Host "Stop with  :  Stop-ScheduledTask -TaskName $TaskName"
Write-Host "Remove with:  powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Uninstall"

# --- optional certificate renewal task ------------------------------------
if ($WithCertRenewal) {
    $RenewTask = 'FitnessTrackerCertRenew'
    $renewScript = Join-Path $ProjectDir 'renew_cert.ps1'
    if (-not (Test-Path $renewScript)) { throw "renew_cert.ps1 not found in $ProjectDir" }

    $rAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$renewScript`" -Domain $CertDomain" `
        -WorkingDirectory $ProjectDir
    # Weekly, not monthly: the script is a no-op until the cert is inside its
    # renewal window, and a weekly cadence means a missed run (machine off) does
    # not eat into the margin before the 90-day expiry.
    $rTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3am
    $rSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    $rPrincipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

    if (Get-ScheduledTask -TaskName $RenewTask -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $RenewTask -Confirm:$false
    }
    Register-ScheduledTask -TaskName $RenewTask -Action $rAction -Trigger $rTrigger `
        -Settings $rSettings -Principal $rPrincipal `
        -Description "Renew the Tailscale certificate for $CertDomain" | Out-Null

    Write-Host ""
    Write-Host "Registered '$RenewTask' (Sundays 03:00, renews within 30 days of expiry)." -ForegroundColor Green
    Write-Host "  log: $(Join-Path $ProjectDir 'logs\cert-renew.log')"
    Write-Host "  dry run: powershell -ExecutionPolicy Bypass -File renew_cert.ps1"
}
