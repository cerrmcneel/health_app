param(
    [string]$HostIP = "192.168.1.168",
    [string]$User = "eric-mcneel"
)

Write-Host "Checking connectivity to $HostIP..."
$lanOk = Test-Connection -ComputerName $HostIP -Count 1 -Quiet
if (-not $lanOk) {
    Write-Warning "Host $HostIP is not responding on LAN. Checking Tailscale (100.103.11.109)..."
    $tsOk = Test-Connection -ComputerName "100.103.11.109" -Count 1 -Quiet
    if ($tsOk) {
        $HostIP = "100.103.11.109"
        Write-Host "Connected via Tailscale: $HostIP"
    } else {
        Write-Error "Neither LAN ($HostIP) nor Tailscale (100.103.11.109) is reachable. Please ensure the TrueNAS host / VM 101 is powered on."
        exit 1
    }
}

Write-Host "Syncing app and static to $HostIP..."
scp -o BatchMode=yes -r app static "${User}@${HostIP}:~/fitness-tracker/"
if ($LASTEXITCODE -ne 0) {
    Write-Error "SCP failed."
    exit $LASTEXITCODE
}

Write-Host "Setting file permissions on $HostIP..."
ssh -o BatchMode=yes "${User}@${HostIP}" "chmod -R a+rX ~/fitness-tracker/app ~/fitness-tracker/static"

Write-Host "Rebuilding and restarting container on $HostIP..."
ssh -o BatchMode=yes "${User}@${HostIP}" "cd ~/fitness-tracker && docker compose build tracker && docker compose up -d tracker"

Write-Host "Deployment complete! Checking health..."
ssh -o BatchMode=yes "${User}@${HostIP}" "curl -k -s https://localhost/api/health"
