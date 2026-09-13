# Deployment Target: Homelab Linux VM Only

## CRITICAL INVARIANT: ALWAYS DEPLOY TO HOMELAB LINUX VM, NEVER WINDOWS

1. **Production Host**:
   - **Homelab Server**: Linux QEMU-VM on Tailscale at `100.103.11.109` (LAN `192.168.1.168`).
   - **SSH User**: `eric-mcneel@100.103.11.109`
   - **Remote Directory**: `~/fitness-tracker/`
   - **Production URL**: `https://100.103.11.109/` (ports 80/443 via Nginx proxy container, backend in Docker container `fitness-tracker`).

2. **Windows Machine Role**:
   - The Windows workstation is strictly a **development, testing, and GPU worker environment** (provides Ollama GPU inference for the homelab container via `extra_hosts: [gpu-worker:100.102.124.29]`).
   - **DO NOT** deploy user updates to the local Windows machine or report the Windows scheduled task (`FitnessTracker`) as the production deployment. The user accesses the app exclusively from their phones and mobile devices via `https://100.103.11.109/`.

3. **Standard Deployment Steps**:
   Whenever deploying code changes:
   ```bash
   # 1. Sync updated code and static assets
   scp -r app static requirements.txt eric-mcneel@100.103.11.109:~/fitness-tracker/

   # 2. Set file permissions, rebuild container, and restart tracker service
   ssh eric-mcneel@100.103.11.109 "chmod -R a+rX ~/fitness-tracker/app ~/fitness-tracker/static && cd ~/fitness-tracker && docker compose build tracker && docker compose up -d tracker"
   ```
