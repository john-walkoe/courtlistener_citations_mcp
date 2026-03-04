#Requires -Version 5.1
<#
.SYNOPSIS
    List and clean up dev tunnels.

.DESCRIPTION
    Finds all dev tunnels owned by the current user and optionally deletes them.
    Also finds and stops any running CourtListener MCP HTTP server processes.
    Useful for cleaning up leftover tunnels and servers from previous sessions.

.PARAMETER DeleteAll
    Delete all tunnels without prompting for each one.

.PARAMETER List
    List tunnels only, do not delete.

.EXAMPLE
    .\cleanup_devtunnels.ps1
    # Interactive: lists tunnels and asks to delete each one

.EXAMPLE
    .\cleanup_devtunnels.ps1 -List
    # List only, no deletion

.EXAMPLE
    .\cleanup_devtunnels.ps1 -DeleteAll
    # Delete all tunnels without prompting
#>

param(
    [switch]$DeleteAll,
    [switch]$List
)

$ProjectDir = Split-Path -Parent $PSScriptRoot

# ============================================================================
# Find devtunnel.exe
# ============================================================================

$DevTunnelExe = $null
$devtunnelFromPath = ($env:PATH -split ';') |
    Where-Object { $_ -and $_ -ne $ProjectDir -and (Test-Path (Join-Path $_ 'devtunnel.exe')) } |
    ForEach-Object { Join-Path $_ 'devtunnel.exe' } |
    Select-Object -First 1

$searchPaths = @(
    "$ProjectDir\devtunnel.exe",
    $devtunnelFromPath,
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
    Write-Host "[ERROR] devtunnel.exe not found" -ForegroundColor Red
    exit 1
}

# ============================================================================
# Check login
# ============================================================================

$loginStatus = & $DevTunnelExe user show 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Not logged into devtunnel. Run: devtunnel user login" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] $loginStatus" -ForegroundColor Green
Write-Host ""

# ============================================================================
# List tunnels
# ============================================================================

Write-Host "[INFO] Fetching tunnel list..." -ForegroundColor Yellow
$tunnelOutput = & $DevTunnelExe list 2>&1 | Out-String

if ($tunnelOutput -match "No tunnels found" -or [string]::IsNullOrWhiteSpace($tunnelOutput)) {
    Write-Host "[OK] No tunnels found. Nothing to clean up." -ForegroundColor Green
    exit 0
}

Write-Host $tunnelOutput

# ============================================================================
# Find running MCP server processes
# ============================================================================

$mcpProcesses = Get-WmiObject Win32_Process -Filter "Name = 'python.exe'" 2>$null |
    Where-Object { $_.CommandLine -match "courtlistener_mcp\.main" }

if ($mcpProcesses) {
    Write-Host "Running CourtListener MCP server processes:" -ForegroundColor Cyan
    foreach ($proc in $mcpProcesses) {
        Write-Host "  PID $($proc.ProcessId): $($proc.CommandLine)" -ForegroundColor White
    }
    Write-Host ""
} else {
    Write-Host "[OK] No running CourtListener MCP server processes found" -ForegroundColor Green
    Write-Host ""
}

if ($List) {
    exit 0
}

# ============================================================================
# Stop MCP server processes
# ============================================================================

if ($mcpProcesses) {
    $stopServers = $true
    if (-not $DeleteAll) {
        Write-Host "Stop running MCP server processes? (y/n)" -ForegroundColor Cyan
        $confirm = Read-Host
        $stopServers = ($confirm -eq "y" -or $confirm -eq "Y")
    }

    if ($stopServers) {
        foreach ($proc in $mcpProcesses) {
            try {
                Stop-Process -Id $proc.ProcessId -Force
                Write-Host "[OK] Stopped MCP server (PID: $($proc.ProcessId))" -ForegroundColor Green
            } catch {
                Write-Host "[WARN] Could not stop PID $($proc.ProcessId): $_" -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "[OK] MCP server processes left running" -ForegroundColor Yellow
    }
    Write-Host ""
}

# ============================================================================
# Delete tunnels
# ============================================================================

if ($DeleteAll) {
    Write-Host "[INFO] Deleting all tunnels..." -ForegroundColor Yellow
    & $DevTunnelExe delete-all --force 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] All tunnels deleted" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Failed to delete tunnels" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Delete all tunnels? (y/n)" -ForegroundColor Cyan
    $confirm = Read-Host
    if ($confirm -eq "y" -or $confirm -eq "Y") {
        & $DevTunnelExe delete-all --force 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] All tunnels deleted" -ForegroundColor Green
        } else {
            Write-Host "[ERROR] Failed to delete tunnels" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "[OK] No tunnels deleted" -ForegroundColor Yellow
    }
}
