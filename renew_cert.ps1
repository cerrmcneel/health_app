<#
.SYNOPSIS
    Renew the Tailscale (Let's Encrypt) certificate and restart the tracker.

.DESCRIPTION
    Certificates issued with `tailscale cert` last 90 days and are NOT renewed
    automatically -- that is the part `tailscale serve` would have handled. This
    script re-issues and restarts the service only when the certificate is close
    to expiry, so it is safe to run on a schedule.

    Registered as its own scheduled task by install_autostart.ps1 -WithCertRenewal.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File renew_cert.ps1
    powershell -ExecutionPolicy Bypass -File renew_cert.ps1 -Force
#>
[CmdletBinding()]
param(
    [string]$Domain = 'datainmind.taila2c133.ts.net',
    # Renew this many days before expiry. 30 gives three monthly attempts inside
    # the 90-day life before anything actually breaks.
    [int]$RenewWithinDays = 30,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProjectDir = $PSScriptRoot
$CertDir = Join-Path $ProjectDir 'certs'
$CertFile = Join-Path $CertDir "$($Domain.Split('.')[0]).crt"
$KeyFile = Join-Path $CertDir "$($Domain.Split('.')[0]).key"
$LogFile = Join-Path $ProjectDir 'logs\cert-renew.log'
$Tailscale = 'C:\Program Files\Tailscale\tailscale.exe'
$TaskName = 'FitnessTracker'

New-Item -ItemType Directory -Force -Path (Split-Path $LogFile), $CertDir | Out-Null

function Write-Log($msg) {
    $line = "{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $msg
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    Write-Host $line
}

try {
    if (-not (Test-Path $Tailscale)) { throw "tailscale.exe not found at $Tailscale" }

    $daysLeft = $null
    if (Test-Path $CertFile) {
        $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($CertFile)
        $daysLeft = [math]::Round(($cert.NotAfter - (Get-Date)).TotalDays)
        Write-Log "current cert expires $($cert.NotAfter) ($daysLeft days left)"
    } else {
        Write-Log "no certificate at $CertFile"
    }

    if (-not $Force -and $null -ne $daysLeft -and $daysLeft -gt $RenewWithinDays) {
        Write-Log "more than $RenewWithinDays days remain; nothing to do"
        exit 0
    }

    Write-Log "renewing certificate for $Domain"
    & $Tailscale cert --cert-file $CertFile --key-file $KeyFile $Domain 2>&1 | ForEach-Object { Write-Log "  tailscale: $_" }
    if ($LASTEXITCODE -ne 0) { throw "tailscale cert failed with exit code $LASTEXITCODE" }

    $new = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($CertFile)
    Write-Log "new cert expires $($new.NotAfter)"

    # uvicorn reads the certificate once at startup, so a renewed file on disk
    # does nothing until the process restarts.
    Write-Log "restarting $TaskName to pick up the new certificate"
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5
    Get-Process pythonw -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -like "$ProjectDir*" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 15

    $url = "https://$Domain`:8010/api/health"
    try {
        $h = Invoke-RestMethod $url -TimeoutSec 20
        Write-Log "verified: $url responded (model_ready=$($h.model_ready))"
    } catch {
        Write-Log "WARNING: could not verify $url after restart: $_"
        exit 1
    }
    Write-Log "renewal complete"
    exit 0
} catch {
    Write-Log "ERROR: $_"
    exit 1
}
