#Requires -Version 5.1
<#
.SYNOPSIS
    Start CourtListener MCP server with a dev tunnel for CoPilot Studio / Claude.ai access.

.DESCRIPTION
    Starts the MCP HTTP server locally and creates a Microsoft Dev Tunnel to expose it
    publicly. The tunnel URL can be used as an MCP endpoint in CoPilot Studio or Claude.ai.

    Prerequisites:
    - devtunnel.exe (included or install from https://aka.ms/devtunnels)
    - Logged into devtunnel: devtunnel user login
    - CourtListener MCP installed (run windows_setup.ps1 first)

.PARAMETER Port
    Local HTTP port for the MCP server (default: 8000)

.PARAMETER Persistent
    Create a persistent named tunnel instead of a temporary one

.PARAMETER TunnelName
    Name for persistent tunnel (default: courtlistener-mcp)

.PARAMETER AllowAnonymous
    Allow anonymous access to the tunnel (default: true for CoPilot compatibility)

.EXAMPLE
    .\start_devtunnel.ps1
    # Starts server on port 8000 with a temporary anonymous tunnel

.EXAMPLE
    .\start_devtunnel.ps1 -Port 8889
    # Starts server on custom port

.EXAMPLE
    .\start_devtunnel.ps1 -Persistent
    # Creates a reusable named tunnel (URL stays the same across restarts)
#>

param(
    [int]$Port = 8000,
    [switch]$Persistent,
    [string]$TunnelName = "courtlistener-mcp",
    [bool]$AllowAnonymous = $true
)

# ============================================================================
# Parameter Validation
# ============================================================================

if ($Port -lt 1 -or $Port -gt 65535) {
    Write-Host "[ERROR] Port must be between 1 and 65535 (got: $Port)" -ForegroundColor Red
    exit 1
}

if ($TunnelName -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_-]*$') {
    Write-Host "[ERROR] TunnelName must start with a letter or digit and contain only letters, digits, hyphens, or underscores (got: $TunnelName)" -ForegroundColor Red
    exit 1
}

# ============================================================================
# Configuration
# ============================================================================

$ProjectDir = Split-Path -Parent $PSScriptRoot
$PythonExe = "$ProjectDir\.venv\Scripts\python.exe"

Write-Host ""
Write-Host "=== CourtListener MCP - Dev Tunnel Launcher ===" -ForegroundColor Green
Write-Host ""

# ============================================================================
# Preflight Checks
# ============================================================================

# Find devtunnel.exe - check multiple locations
$DevTunnelExe = $null
$LocalDevTunnel = "$ProjectDir\devtunnel.exe"
# Search PATH manually to avoid PowerShell's "not in path" suggestion noise from Get-Command
$devtunnelFromPath = ($env:PATH -split ';') |
    Where-Object { $_ -and $_ -ne $ProjectDir -and (Test-Path (Join-Path $_ 'devtunnel.exe')) } |
    ForEach-Object { Join-Path $_ 'devtunnel.exe' } |
    Select-Object -First 1

$searchPaths = @(
    # Project root first (gitignored local copy)
    $LocalDevTunnel,
    # System PATH (excluding CWD)
    $devtunnelFromPath,
    # Common install locations
    "$env:LOCALAPPDATA\Microsoft\DevTunnel\devtunnel.exe",
    "$env:USERPROFILE\.devtunnels\devtunnel.exe",
    "$env:USERPROFILE\devtunnel.exe"
)

foreach ($path in $searchPaths) {
    if ($path -and (Test-Path $path)) {
        $DevTunnelExe = $path
        break
    }
}

if (-not $DevTunnelExe) {
    Write-Host "[INFO] devtunnel.exe not found. Downloading..." -ForegroundColor Yellow

    $downloadUrl = "https://aka.ms/TunnelsCliDownload/win-x64"

    try {
        # Download to project root (gitignored)
        Invoke-WebRequest -Uri $downloadUrl -OutFile $LocalDevTunnel -UseBasicParsing
        if (Test-Path $LocalDevTunnel) {
            $DevTunnelExe = $LocalDevTunnel
            Write-Host "[OK] Downloaded devtunnel.exe to project root (gitignored)" -ForegroundColor Green
        } else {
            throw "Download produced no file"
        }
    } catch {
        Write-Host "[ERROR] Failed to download devtunnel.exe: $_" -ForegroundColor Red
        Write-Host "" -ForegroundColor Yellow
        Write-Host "  Download manually from:" -ForegroundColor Yellow
        Write-Host "    https://aka.ms/TunnelsCliDownload/win-x64" -ForegroundColor White
        Write-Host "  Place devtunnel.exe in: $ProjectDir" -ForegroundColor Yellow
        Write-Host "" -ForegroundColor Yellow
        Write-Host "  Or install with winget:" -ForegroundColor Yellow
        Write-Host "    winget install Microsoft.devtunnel" -ForegroundColor White
        exit 1
    }
}
Write-Host "[OK] devtunnel: $DevTunnelExe" -ForegroundColor Green

# Check Windows Firewall - ensure devtunnel.exe has outbound access
$fwRuleExists = Get-NetFirewallApplicationFilter -Program $DevTunnelExe -ErrorAction SilentlyContinue
if (-not $fwRuleExists) {
    Write-Host "[INFO] No Windows Firewall rule found for devtunnel.exe - adding outbound rule..." -ForegroundColor Yellow
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) {
        New-NetFirewallRule -DisplayName "DevTunnel MCP (Outbound)" `
            -Direction Outbound `
            -Program $DevTunnelExe `
            -Action Allow `
            -Profile Any `
            -ErrorAction SilentlyContinue | Out-Null
        New-NetFirewallRule -DisplayName "DevTunnel MCP (Inbound)" `
            -Direction Inbound `
            -Program $DevTunnelExe `
            -Action Allow `
            -Profile Any `
            -ErrorAction SilentlyContinue | Out-Null
        Write-Host "[OK] Firewall rules added for devtunnel.exe" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Not running as Administrator - cannot add firewall rule automatically." -ForegroundColor Yellow
        Write-Host "       If the tunnel fails to connect, re-run PowerShell as Administrator:" -ForegroundColor Yellow
        Write-Host "       Start-Process powershell -Verb RunAs -ArgumentList '-File .\deploy\start_devtunnel.ps1'" -ForegroundColor White
    }
} else {
    Write-Host "[OK] Firewall rule exists for devtunnel.exe" -ForegroundColor Green
}

# Check login status
$loginStatus = & $DevTunnelExe user show 2>&1
if ($loginStatus -match "not logged in" -or $LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Not logged into devtunnel" -ForegroundColor Red
    Write-Host "        Run: devtunnel user login" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] $loginStatus" -ForegroundColor Green

# ============================================================================
# Ask: Docker or local Python? And which port?
# ============================================================================

Write-Host "How is the MCP server running?" -ForegroundColor Cyan
Write-Host "  [1] Docker (already running via 'docker compose up -d')" -ForegroundColor White
Write-Host "  [2] Local Python (start it now via uv/venv)" -ForegroundColor White
Write-Host ""
$modeChoice = Read-Host "Enter choice (1 or 2, default is 1)"
if ($modeChoice -eq "") { $modeChoice = "1" }

$useDocker = ($modeChoice -eq "1")

Write-Host ""
$portInput = Read-Host "Port the server is/will run on (default: $Port)"
if ($portInput -ne "") { $Port = [int]$portInput }
Write-Host ""

# ============================================================================
# Server startup / validation
# ============================================================================

$serverProcess = $null

if ($useDocker) {
    # Docker mode - just verify the container is already healthy on the target port
    Write-Host "[INFO] Docker mode - checking container health on port $Port..." -ForegroundColor Yellow

    $maxWait = 10
    $waited = 0
    $serverReady = $false

    while ($waited -lt $maxWait) {
        try {
            $health = Invoke-RestMethod -Uri "http://localhost:$Port/health" -TimeoutSec 2 -ErrorAction Stop
            if ($health.status -eq "healthy") {
                $serverReady = $true
                break
            }
        } catch {
            $waited++
            if ($waited -lt $maxWait) {
                Write-Host "  Waiting for Docker container... ($waited/$maxWait)" -ForegroundColor Gray
                Start-Sleep -Seconds 1
            }
        }
    }

    if (-not $serverReady) {
        Write-Host "[ERROR] No healthy server found at http://localhost:$Port/health" -ForegroundColor Red
        Write-Host "        Make sure the container is running: docker compose up -d" -ForegroundColor Yellow
        exit 1
    }

    Write-Host "[OK] Docker container healthy at http://localhost:$Port" -ForegroundColor Green
    Write-Host "     Health: http://localhost:$Port/health" -ForegroundColor Gray
    Write-Host "     MCP:    http://localhost:$Port/mcp" -ForegroundColor Gray
    Write-Host ""

} else {
    # Local Python mode - check venv and token, then start the process

    if (-not (Test-Path $PythonExe)) {
        Write-Host "[ERROR] Virtual environment not found at $ProjectDir\.venv" -ForegroundColor Red
        Write-Host "        Run .\deploy\windows_setup.ps1 first" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[OK] Python venv: $PythonExe" -ForegroundColor Green

    Set-Location $ProjectDir
    $pyScript = "import sys`nfrom pathlib import Path`nsys.path.insert(0, str(Path('src')))`nfrom courtlistener_mcp.shared.secure_storage import get_api_token`ntoken = get_api_token()`nprint('YES' if token and len(token) >= 20 else 'NO')"
    $tokenCheck = & $PythonExe -c $pyScript 2>$null

    if ($tokenCheck -ne "YES") {
        if ($env:COURTLISTENER_API_TOKEN) {
            Write-Host "[OK] API token: from environment variable" -ForegroundColor Green
        } else {
            Write-Host "[WARN] No API token found in secure storage or env var" -ForegroundColor Yellow
            Write-Host "       Set COURTLISTENER_API_TOKEN or run windows_setup.ps1" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[OK] API token: stored in DPAPI secure storage" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "[INFO] Starting MCP server on port $Port..." -ForegroundColor Yellow

    $env:TRANSPORT = "http"
    $env:PORT = "$Port"
    $env:HOST = "0.0.0.0"

    $serverProcess = Start-Process -FilePath $PythonExe `
        -ArgumentList "-m", "courtlistener_mcp.main" `
        -WorkingDirectory $ProjectDir `
        -PassThru `
        -NoNewWindow

    $maxWait = 15
    $waited = 0
    $serverReady = $false

    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds 1
        $waited++

        if ($serverProcess.HasExited) {
            Write-Host "[ERROR] MCP server process exited unexpectedly (exit code: $($serverProcess.ExitCode))" -ForegroundColor Red
            exit 1
        }

        try {
            $health = Invoke-RestMethod -Uri "http://localhost:$Port/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($health.status -eq "healthy") {
                $serverReady = $true
                break
            }
        } catch {
            Write-Host "  Waiting for server... ($waited/$maxWait)" -ForegroundColor Gray
        }
    }

    if (-not $serverReady) {
        Write-Host "[ERROR] MCP server failed to start within $maxWait seconds" -ForegroundColor Red
        Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
        exit 1
    }

    Write-Host "[OK] MCP server running on http://localhost:$Port (PID: $($serverProcess.Id))" -ForegroundColor Green
    Write-Host "     Health: http://localhost:$Port/health" -ForegroundColor Gray
    Write-Host "     MCP:    http://localhost:$Port/mcp" -ForegroundColor Gray
    Write-Host ""
}

# ============================================================================
# Start Dev Tunnel
# ============================================================================

if ($Persistent) {
    Write-Host "[INFO] Setting up persistent tunnel: $TunnelName" -ForegroundColor Yellow

    # Check if tunnel already exists
    $existingTunnel = & $DevTunnelExe show $TunnelName 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[INFO] Creating persistent tunnel..." -ForegroundColor Yellow
        & $DevTunnelExe create $TunnelName -d "CourtListener MCP Server"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to create tunnel" -ForegroundColor Red
            Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
            exit 1
        }

        # Add port
        & $DevTunnelExe port create $TunnelName -p $Port --protocol http
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to add port to tunnel" -ForegroundColor Red
            Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
            exit 1
        }

        # Set anonymous access if requested
        if ($AllowAnonymous) {
            & $DevTunnelExe access create $TunnelName --anonymous
        }

        Write-Host "[OK] Persistent tunnel created: $TunnelName" -ForegroundColor Green
    } else {
        Write-Host "[OK] Using existing tunnel: $TunnelName" -ForegroundColor Green
    }

    Write-Host "[INFO] Hosting tunnel..." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host " Tunnel is starting..." -ForegroundColor Cyan
    Write-Host " Look for the URL below (*.devtunnels.ms)" -ForegroundColor Cyan
    Write-Host " Your MCP endpoint will be:" -ForegroundColor Cyan
    Write-Host "   <tunnel-url>/mcp" -ForegroundColor White
    Write-Host "" -ForegroundColor Cyan
    Write-Host " For CoPilot Studio or Claude.ai, use:" -ForegroundColor Cyan
    Write-Host "   https://<tunnel-subdomain>.devtunnels.ms/mcp" -ForegroundColor White
    Write-Host "" -ForegroundColor Cyan
    Write-Host " Press Ctrl+C to stop tunnel (Docker container stays running)" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    try {
        & $DevTunnelExe host $TunnelName
    } finally {
        Write-Host ""
        if ($serverProcess) {
            Write-Host "[INFO] Stopping MCP server (PID: $($serverProcess.Id))..." -ForegroundColor Yellow
            Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
        } else {
            Write-Host ""
            $stopDocker = Read-Host "Stop Docker container now? (y/N, default N)"
            if ($stopDocker -match '^[Yy]') {
                Write-Host "[INFO] Running docker compose down..." -ForegroundColor Yellow
                Set-Location $ProjectDir
                docker compose down
            } else {
                Write-Host "[INFO] Docker container left running - stop with: docker compose down" -ForegroundColor Yellow
            }
        }
        Write-Host "[OK] Cleaned up" -ForegroundColor Green
    }

} else {
    # Temporary tunnel
    Write-Host "[INFO] Starting temporary dev tunnel on port $Port..." -ForegroundColor Yellow

    $anonFlag = if ($AllowAnonymous) { "--allow-anonymous" } else { "" }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host " Tunnel is starting..." -ForegroundColor Cyan
    Write-Host " Look for the URL below (*.devtunnels.ms)" -ForegroundColor Cyan
    Write-Host " Your MCP endpoint will be:" -ForegroundColor Cyan
    Write-Host "   <tunnel-url>/mcp" -ForegroundColor White
    Write-Host "" -ForegroundColor Cyan
    Write-Host " For CoPilot Studio or Claude.ai, use:" -ForegroundColor Cyan
    Write-Host "   https://<tunnel-subdomain>.devtunnels.ms/mcp" -ForegroundColor White
    Write-Host "" -ForegroundColor Cyan
    Write-Host " Press Ctrl+C to stop tunnel (Docker container stays running)" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    try {
        if ($AllowAnonymous) {
            & $DevTunnelExe host -p $Port --allow-anonymous
        } else {
            & $DevTunnelExe host -p $Port
        }
    } finally {
        Write-Host ""
        if ($serverProcess) {
            Write-Host "[INFO] Stopping MCP server (PID: $($serverProcess.Id))..." -ForegroundColor Yellow
            Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
        } else {
            Write-Host ""
            $stopDocker = Read-Host "Stop Docker container now? (y/N, default N)"
            if ($stopDocker -match '^[Yy]') {
                Write-Host "[INFO] Running docker compose down..." -ForegroundColor Yellow
                Set-Location $ProjectDir
                docker compose down
            } else {
                Write-Host "[INFO] Docker container left running - stop with: docker compose down" -ForegroundColor Yellow
            }
        }
        Write-Host "[OK] Cleaned up" -ForegroundColor Green
    }
}
