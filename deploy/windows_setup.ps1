# Windows Deployment Script for CourtListener Citation Validation MCP
# PowerShell version - Full setup with uv, venv, API key, and Claude Desktop

#Requires -Version 5.1

# Import validation helpers (format validation, secure input, retry loops)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Import-Module "$ScriptDir\Validation-Helpers.psm1" -Force

Write-Host ""
Write-Host "=== CourtListener MCP - Windows Setup ===" -ForegroundColor Green
Write-Host ""

# Get project directory
$ProjectDir = (Get-Location).Path

# ============================================================================
# SECTION 1: Check/Install uv
# ============================================================================

Write-Host "[INFO] Python NOT required - uv will manage Python automatically" -ForegroundColor Cyan
Write-Host ""
try {
    $uvVersion = uv --version 2>$null
    Write-Host "[OK] uv found: $uvVersion" -ForegroundColor Green
} catch {
    Write-Host "[INFO] uv not found. Installing uv..." -ForegroundColor Yellow

    # Try winget first (preferred method)
    try {
        winget install --id=astral-sh.uv -e
        Write-Host "[OK] uv installed via winget" -ForegroundColor Green
    } catch {
        Write-Host "[INFO] winget failed, trying PowerShell install method..." -ForegroundColor Yellow
        try {
            powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
            Write-Host "[OK] uv installed via PowerShell script" -ForegroundColor Green
        } catch {
            Write-Host "[ERROR] Failed to install uv. Please install manually:" -ForegroundColor Red
            Write-Host "   winget install --id=astral-sh.uv -e" -ForegroundColor Yellow
            Write-Host "   OR visit: https://docs.astral.sh/uv/getting-started/installation/" -ForegroundColor Yellow
            exit 1
        }
    }

    # Refresh PATH for current session
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")

    # Add uv's typical installation paths if not already in PATH
    $uvPaths = @(
        "$env:USERPROFILE\.cargo\bin",
        "$env:LOCALAPPDATA\Programs\uv\bin",
        "$env:APPDATA\uv\bin"
    )

    foreach ($uvPath in $uvPaths) {
        if (Test-Path $uvPath) {
            if ($env:PATH -notlike "*$uvPath*") {
                $env:PATH = "$uvPath;$env:PATH"
                Write-Host "[INFO] Added $uvPath to PATH" -ForegroundColor Yellow
            }
        }
    }

    # Verify uv is now accessible
    try {
        $uvVersion = uv --version 2>$null
        Write-Host "[OK] uv is now accessible: $uvVersion" -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] uv installed but not accessible. Please restart PowerShell and run script again." -ForegroundColor Red
        exit 1
    }
}

# ============================================================================
# SECTION 2: Create venv + Install dependencies
# ============================================================================

Write-Host ""
Write-Host "[INFO] Setting up virtual environment and dependencies..." -ForegroundColor Yellow

# Create virtual environment if it doesn't exist or is incomplete
$pythonExePath = ".venv/Scripts/python.exe"
if (-not (Test-Path $pythonExePath)) {
    Write-Host "[INFO] Creating virtual environment..." -ForegroundColor Yellow
    # Remove incomplete .venv if it exists
    if (Test-Path ".venv") {
        Write-Host "[INFO] Removing incomplete virtual environment..." -ForegroundColor Yellow
        Remove-Item -Path ".venv" -Recurse -Force
    }
    try {
        uv venv .venv --python 3.12
        Write-Host "[OK] Virtual environment created at .venv" -ForegroundColor Green

        # Fix: Ensure pyvenv.cfg exists (required for secure storage on older uv versions)
        $pyvenvCfgPath = ".venv\pyvenv.cfg"
        if (-not (Test-Path $pyvenvCfgPath)) {
            Write-Host "[INFO] Creating missing pyvenv.cfg file (older uv version)..." -ForegroundColor Yellow
            try {
                $uvPythonInfo = uv python list --only-managed 2>$null | Select-String "cpython-3\.1[2-4].*-windows" | Select-Object -First 1
                if ($uvPythonInfo) {
                    $pythonVersion = ($uvPythonInfo.Line -split '\s+')[1]
                    $pythonPath = ($uvPythonInfo.Line -split '\s+')[2]

                    $pyvenvContent = @"
home = $pythonPath
implementation = CPython
uv = 0.9.11
version_info = $pythonVersion
include-system-site-packages = false
prompt = courtlistener-mcp
"@
                    Set-Content -Path $pyvenvCfgPath -Value $pyvenvContent -Encoding UTF8
                    Write-Host "[OK] Created pyvenv.cfg file" -ForegroundColor Green
                } else {
                    $fallbackContent = @"
implementation = CPython
version_info = 3.12.8
include-system-site-packages = false
prompt = courtlistener-mcp
"@
                    Set-Content -Path $pyvenvCfgPath -Value $fallbackContent -Encoding UTF8
                    Write-Host "[OK] Created minimal pyvenv.cfg file" -ForegroundColor Green
                }
            } catch {
                Write-Host "[WARN] Could not create pyvenv.cfg, but continuing..." -ForegroundColor Yellow
            }
        } else {
            Write-Host "[OK] pyvenv.cfg already exists" -ForegroundColor Green
        }
    } catch {
        Write-Host "[ERROR] Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[OK] Virtual environment already exists at .venv" -ForegroundColor Green
}

# Install dependencies
Write-Host "[INFO] Installing dependencies with uv (Python 3.12)..." -ForegroundColor Yellow

try {
    uv sync --python 3.12
    Write-Host "[OK] Dependencies installed" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Failed to install dependencies" -ForegroundColor Red
    exit 1
}

# Verify MCP server command
Write-Host "[INFO] Verifying installation..." -ForegroundColor Yellow
try {
    $commandCheck = Get-Command courtlistener-mcp -ErrorAction SilentlyContinue
    if ($commandCheck) {
        Write-Host "[OK] Command available: $($commandCheck.Source)" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Command verification failed - check PATH" -ForegroundColor Yellow
        Write-Host "[INFO] You can run the server with: uv run courtlistener-mcp" -ForegroundColor Yellow
    }
} catch {
    Write-Host "[WARN] Command verification failed - check PATH" -ForegroundColor Yellow
    Write-Host "[INFO] You can run the server with: uv run courtlistener-mcp" -ForegroundColor Yellow
}

# ============================================================================
# SECTION 3: API Token Management
# ============================================================================

Write-Host ""
Write-Host "API Token Configuration" -ForegroundColor Cyan
Write-Host ""
Write-Host "[INFO] Token storage priority: Windows Credential Manager -> File-based DPAPI" -ForegroundColor Yellow
Write-Host ""

# Load DPAPI assembly (for fallback PowerShell storage)
Add-Type -AssemblyName System.Security

$StoragePath = Join-Path $env:USERPROFILE ".courtlistener_api_token"
$EntropyBytes = 32

# Flags for tracking configuration path
$usingPreexistingDPAPI = $false
$newTokenStored = $false
$storedToken = ""

# Check for existing token via Python secure storage
function Test-ExistingToken {
    try {
        Set-Location $ProjectDir
        $pythonCode = @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
from courtlistener_mcp.shared.secure_storage import get_api_token
token = get_api_token()
if token and len(token) >= 20:
    print('YES')
    print(token[:4] + '*' * (len(token) - 8) + token[-4:])
else:
    print('NO')
'@
        $result = uv run python -c $pythonCode 2>$null | Out-String
        $lines = $result -split "`n" | Where-Object { $_.Trim() -ne "" }

        if ($lines.Count -ge 1 -and $lines[0].Trim() -eq "YES") {
            return @{
                "Found" = $true
                "Masked" = if ($lines.Count -ge 2) { $lines[1].Trim() } else { "****" }
            }
        }
        return @{ "Found" = $false; "Masked" = "" }
    }
    catch {
        return @{ "Found" = $false; "Masked" = "" }
    }
}

# Store token via Python secure storage
function Set-TokenViaPython {
    param([string]$Token)

    try {
        Set-Location $ProjectDir
        # Pass token via environment variable to avoid command injection
        $env:_CL_TOKEN_TEMP = $Token
        $pythonCode = @'
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
from courtlistener_mcp.shared.secure_storage import store_api_token
token = os.environ.get('_CL_TOKEN_TEMP', '')
success = store_api_token(token)
print('SUCCESS' if success else 'FAILED')
'@
        $result = uv run python -c $pythonCode 2>$null | Out-String
        Remove-Item Env:\_CL_TOKEN_TEMP -ErrorAction SilentlyContinue

        if (([string]$result).Trim() -match "SUCCESS") {
            Write-Host "[OK] API token stored securely" -ForegroundColor Green
            Write-Host "     Primary: Windows Credential Manager" -ForegroundColor Yellow
            Write-Host "     Backup: ~/.courtlistener_api_token (DPAPI encrypted)" -ForegroundColor Yellow
            return $true
        } else {
            Write-Host "[WARN] Python storage failed, using PowerShell fallback..." -ForegroundColor Yellow
            return $false
        }
    }
    catch {
        Remove-Item Env:\_CL_TOKEN_TEMP -ErrorAction SilentlyContinue
        Write-Host "[WARN] Python storage failed: $_, using PowerShell fallback..." -ForegroundColor Yellow
        return $false
    }
}

# PowerShell fallback for token storage
function Set-TokenViaPS {
    param([string]$Token)

    try {
        $entropy = New-Object byte[] $EntropyBytes
        $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
        $rng.GetBytes($entropy)
        $rng.Dispose()

        $tokenBytes = [System.Text.Encoding]::UTF8.GetBytes($Token)
        $encrypted = [System.Security.Cryptography.ProtectedData]::Protect(
            $tokenBytes,
            $entropy,
            [System.Security.Cryptography.DataProtectionScope]::CurrentUser
        )

        $combined = $entropy + $encrypted
        [System.IO.File]::WriteAllBytes($StoragePath, $combined)

        Write-Host "[OK] API token stored via PowerShell DPAPI" -ForegroundColor Green
        Write-Host "     Location: $StoragePath (encrypted)" -ForegroundColor Yellow
        return $true
    }
    catch {
        Write-Host "[ERROR] Failed to store token: $_" -ForegroundColor Red
        return $false
    }
}

# Check existing token
Write-Host "[INFO] Checking for existing API token..." -ForegroundColor Yellow
$existingToken = Test-ExistingToken

if ($existingToken.Found) {
    Write-Host "[OK] API token found in secure storage: $($existingToken.Masked)" -ForegroundColor Green
    Write-Host ""
    Write-Host "[INFO] Configuration: [1] Use existing token [2] Update token" -ForegroundColor Cyan
    $tokenChoice = Read-Host "Enter choice (1 or 2, default is 1)"

    if ($tokenChoice -eq "2") {
        $updateToken = $true
    } else {
        $updateToken = $false
        $usingPreexistingDPAPI = $true
        Write-Host "[OK] Using existing API token" -ForegroundColor Green
    }
} else {
    Write-Host "[INFO] No API token found in secure storage" -ForegroundColor Yellow
    $updateToken = $true
}

# Collect and store token if needed
if ($updateToken) {
    # Collect and validate token using module (3-attempt retry, hidden input, strict hex format)
    $token = Read-CourtListenerTokenWithValidation
    if (-not $token) {
        Write-Host "[ERROR] No valid token provided. Exiting." -ForegroundColor Red
        exit 1
    }

    # Store via Python first, PowerShell fallback
    $stored = Set-TokenViaPython -Token $token
    if (-not $stored) {
        $stored = Set-TokenViaPS -Token $token
    }

    if ($stored) {
        $newTokenStored = $true
        $storedToken = $token
    } else {
        Write-Host "[ERROR] Failed to store API token" -ForegroundColor Red
        exit 1
    }
}

# ============================================================================
# SECTION 4: Transport Mode Selection
# ============================================================================

Write-Host ""
Write-Host "Transport Mode" -ForegroundColor Cyan
Write-Host ""
Write-Host "  [1] STDIO (recommended) - Direct process communication (Claude Desktop/Code)" -ForegroundColor White
Write-Host "  [2] HTTP - Streamable HTTP server on localhost (Docker, CoPilot Studio, remote)" -ForegroundColor White
Write-Host ""
$transportChoice = Read-Host "Enter choice (1 or 2, default is 1)"

$useHttpTransport = $false
$httpPort = "8000"

if ($transportChoice -eq "2") {
    $useHttpTransport = $true
    $portInput = Read-Host "HTTP port (default: 8000)"
    if (-not [string]::IsNullOrWhiteSpace($portInput)) {
        $httpPort = $portInput.Trim()
    }
    Write-Host "[OK] Transport: HTTP on port $httpPort" -ForegroundColor Green
    Write-Host "     MCP endpoint: http://localhost:$httpPort/mcp" -ForegroundColor Yellow
} else {
    Write-Host "[OK] Transport: STDIO (default)" -ForegroundColor Green
}

# ============================================================================
# SECTION 5: Claude Desktop Configuration
# ============================================================================

Write-Host ""
Write-Host "Claude Desktop Configuration" -ForegroundColor Cyan
Write-Host ""

$configureClaudeDesktop = Read-Host "Would you like to configure Claude Desktop integration? (Y/n)"
if ($configureClaudeDesktop -eq "" -or $configureClaudeDesktop -eq "Y" -or $configureClaudeDesktop -eq "y") {

    # Get current directory with forward slashes for JSON
    $CurrentDir = $ProjectDir -replace "\\","/"

    # Determine token configuration method (only relevant for STDIO mode)
    $useSecureStorage = $false
    $configToken = ""
    $finalConfigMethod = "none"

    if (-not $useHttpTransport) {
        # STDIO mode - need to decide how to pass token
        if ($usingPreexistingDPAPI -and -not $newTokenStored) {
            Write-Host ""
            Write-Host "[OK] Using secure storage (no API token in config file)" -ForegroundColor Green
            Write-Host "     Token loaded automatically from ~/.courtlistener_api_token at runtime" -ForegroundColor Yellow
            Write-Host ""
            $useSecureStorage = $true
            $finalConfigMethod = "dpapi"
        } elseif ($newTokenStored) {
            Write-Host ""
            Write-Host "Claude Desktop Configuration Method:" -ForegroundColor Cyan
            Write-Host "  [1] Secure DPAPI (recommended) - Token loaded from secure storage at runtime" -ForegroundColor White
            Write-Host "  [2] Traditional - Token stored in Claude Desktop config file" -ForegroundColor White
            Write-Host ""
            $configChoice = Read-Host "Enter choice (1 or 2, default is 1)"

            if ($configChoice -eq "2") {
                Write-Host "[INFO] Using traditional method (token in config file)" -ForegroundColor Yellow
                $useSecureStorage = $false
                $finalConfigMethod = "traditional"
                $configToken = $storedToken
            } else {
                Write-Host "[OK] Using secure storage (no API token in config file)" -ForegroundColor Green
                $useSecureStorage = $true
                $finalConfigMethod = "dpapi"
            }
        } else {
            Write-Host ""
            Write-Host "[OK] Using secure storage mode (no API token in config file)" -ForegroundColor Green
            Write-Host ""
            $useSecureStorage = $true
            $finalConfigMethod = "dpapi"
        }
    } else {
        # HTTP mode - token is managed server-side (DPAPI or env var on the server)
        Write-Host ""
        Write-Host "[OK] HTTP mode - token managed server-side (DPAPI or env var)" -ForegroundColor Green
        Write-Host "     Claude Desktop connects via mcp-remote to http://localhost:$httpPort/mcp" -ForegroundColor Yellow
        Write-Host ""
        $useSecureStorage = $true
        $finalConfigMethod = "http"
    }

    # Generate server JSON entry based on transport mode
    function Get-ServerJson {
        param($indent = "    ")

        if ($useHttpTransport) {
            # HTTP mode: use npx mcp-remote pointing to localhost
            return @"
$indent"courtlistener_citations": {
$indent  "command": "npx",
$indent  "args": [
$indent    "mcp-remote",
$indent    "http://localhost:$httpPort/mcp/"
$indent  ]
$indent}
"@
        } else {
            # STDIO mode: direct Python process
            $envItems = @()
            if (-not $useSecureStorage -and $configToken) {
                $envItems += "      `"COURTLISTENER_API_TOKEN`": `"$configToken`""
            }
            $envSection = $envItems -join ",`n"

            if ($envSection) {
                return @"
$indent"courtlistener_citations": {
$indent  "command": "$CurrentDir/.venv/Scripts/python.exe",
$indent  "args": [
$indent    "-m",
$indent    "courtlistener_mcp.main"
$indent  ],
$indent  "cwd": "$CurrentDir",
$indent  "env": {
$envSection
$indent  }
$indent}
"@
            } else {
                return @"
$indent"courtlistener_citations": {
$indent  "command": "$CurrentDir/.venv/Scripts/python.exe",
$indent  "args": [
$indent    "-m",
$indent    "courtlistener_mcp.main"
$indent  ],
$indent  "cwd": "$CurrentDir"
$indent}
"@
            }
        }
    }

    # Claude Desktop config location
    $ClaudeConfigDir = "$env:APPDATA\Claude"
    $ClaudeConfigFile = "$ClaudeConfigDir\claude_desktop_config.json"

    Write-Host "[INFO] Claude Desktop config location: $ClaudeConfigFile" -ForegroundColor Yellow

    if (Test-Path $ClaudeConfigFile) {
        Write-Host "[INFO] Existing Claude Desktop config found" -ForegroundColor Yellow
        Write-Host "[INFO] Merging CourtListener MCP configuration..." -ForegroundColor Yellow

        try {
            $existingJsonText = Get-Content $ClaudeConfigFile -Raw

            # Backup the original file
            $backupFile = "$ClaudeConfigFile.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
            Copy-Item $ClaudeConfigFile $backupFile
            Write-Host "[INFO] Backup created: $backupFile" -ForegroundColor Yellow

            # Parse JSON
            try {
                $existingConfig = $existingJsonText | ConvertFrom-Json
            } catch {
                Write-Host "[ERROR] Existing Claude Desktop config has JSON syntax errors" -ForegroundColor Red
                Write-Host "[ERROR] Common issue: Missing comma between MCP server sections" -ForegroundColor Red
                Write-Host "[INFO] Please fix the JSON syntax and run the setup script again" -ForegroundColor Yellow
                Write-Host "[INFO] Your backup is saved at: $backupFile" -ForegroundColor Yellow
                exit 1
            }

            if (-not $existingConfig.mcpServers) {
                # No mcpServers section - add it
                $existingConfig | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue (New-Object PSObject) -Force
            }

            # Build merged mcpServers: preserve existing (except courtlistener), add courtlistener
            $clJson = Get-ServerJson

            $existingServers = @()
            if ($existingConfig.mcpServers.PSObject.Properties) {
                $existingServers = $existingConfig.mcpServers.PSObject.Properties.Name
            }
            $serverEntries = @()

            foreach ($serverName in $existingServers) {
                if ($serverName -ne "courtlistener_citations") {
                    $serverJson = $existingConfig.mcpServers.$serverName | ConvertTo-Json -Depth 10
                    $jsonLines = $serverJson -split "`n"

                    $formattedEntry = "    `"$serverName`": $($jsonLines[0])"
                    for ($i = 1; $i -lt $jsonLines.Length; $i++) {
                        $formattedEntry += "`n    $($jsonLines[$i])"
                    }
                    $serverEntries += $formattedEntry
                }
            }

            # Add courtlistener
            $serverEntries += $clJson.TrimEnd()
            $allServers = $serverEntries -join ",`n"

            # Build mcpServers block
            $mcpServersBlock = @"
  "mcpServers": {
$allServers
  }
"@

            # Preserve all other top-level keys (preferences, etc.)
            $otherBlocks = @()
            foreach ($prop in $existingConfig.PSObject.Properties) {
                if ($prop.Name -ne "mcpServers") {
                    $propJson = $prop.Value | ConvertTo-Json -Depth 10
                    $propLines = $propJson -split "`n"

                    $formattedProp = "  `"$($prop.Name)`": $($propLines[0])"
                    for ($i = 1; $i -lt $propLines.Length; $i++) {
                        $formattedProp += "`n  $($propLines[$i])"
                    }
                    $otherBlocks += $formattedProp
                }
            }

            # Combine mcpServers + other top-level keys
            $allBlocks = @($mcpServersBlock) + $otherBlocks
            $jsonConfig = "{`n" + ($allBlocks -join ",`n") + "`n}"

            # Write with UTF8 without BOM
            $utf8NoBom = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllText($ClaudeConfigFile, $jsonConfig, $utf8NoBom)

            Write-Host "[OK] Successfully merged CourtListener MCP configuration!" -ForegroundColor Green
            Write-Host "[OK] Your existing MCP servers have been preserved" -ForegroundColor Green
            Write-Host "[INFO] Configuration backup: $backupFile" -ForegroundColor Yellow

        } catch {
            Write-Host "[ERROR] Failed to merge configuration: $_" -ForegroundColor Red
            Write-Host ""
            Write-Host "Please manually add this to your mcpServers in: $ClaudeConfigFile" -ForegroundColor Yellow
            $manualJson = Get-ServerJson -indent ""
            Write-Host $manualJson -ForegroundColor Cyan
            if (Test-Path $backupFile) {
                Write-Host "Your backup is saved at: $backupFile" -ForegroundColor Yellow
            }
            exit 1
        }

    } else {
        # Create new config file
        Write-Host "[INFO] Creating new Claude Desktop config..." -ForegroundColor Yellow

        if (-not (Test-Path $ClaudeConfigDir)) {
            New-Item -ItemType Directory -Path $ClaudeConfigDir -Force | Out-Null
        }

        $serverJson = Get-ServerJson
        $jsonConfig = @"
{
  "mcpServers": {
$serverJson
  }
}
"@
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($ClaudeConfigFile, $jsonConfig, $utf8NoBom)

        Write-Host "[OK] Created new Claude Desktop config" -ForegroundColor Green
    }

    Write-Host "[OK] Claude Desktop configuration complete!" -ForegroundColor Green
}

# ============================================================================
# SECTION 6: Final Summary
# ============================================================================

Write-Host ""
Write-Host "Windows setup complete!" -ForegroundColor Green
Write-Host "Please restart Claude Desktop to load the MCP server" -ForegroundColor Yellow
Write-Host ""
Write-Host "Configuration Summary:" -ForegroundColor Cyan

# Check final token status
$finalToken = Test-ExistingToken
if ($finalToken.Found) {
    Write-Host "  [OK] API Token: Stored in secure storage ($($finalToken.Masked))" -ForegroundColor Green
    Write-Host "       Primary: Windows Credential Manager (CourtListener MCP)" -ForegroundColor Yellow
    Write-Host "       Backup:  ~/.courtlistener_api_token (DPAPI encrypted)" -ForegroundColor Yellow
} else {
    Write-Host "  [WARN] API Token: Not found (set COURTLISTENER_API_TOKEN env var)" -ForegroundColor Yellow
}

Write-Host "  [OK] Installation Directory: $ProjectDir" -ForegroundColor Green

# Transport mode summary
if ($useHttpTransport) {
    Write-Host "  [OK] Transport: HTTP (Streamable HTTP)" -ForegroundColor Green
    Write-Host "       MCP Endpoint: http://localhost:$httpPort/mcp" -ForegroundColor Yellow
    Write-Host "       Start server: set TRANSPORT=http && set PORT=$httpPort && courtlistener-mcp" -ForegroundColor Yellow
} else {
    Write-Host "  [OK] Transport: STDIO (direct process)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Available Tools (6):" -ForegroundColor Cyan
Write-Host "  Citation Validation:" -ForegroundColor White
Write-Host "    - validate_citations (primary - extract & validate from text)" -ForegroundColor White
Write-Host "    - search_cases (fallback - search by case name)" -ForegroundColor White
Write-Host "    - lookup_citation (last resort - direct citation lookup)" -ForegroundColor White
Write-Host "  Case Details:" -ForegroundColor White
Write-Host "    - get_cluster (full case details & CourtListener URLs)" -ForegroundColor White
Write-Host "    - search_clusters (filtered opinion cluster search)" -ForegroundColor White
Write-Host "  Guidance:" -ForegroundColor White
Write-Host "    - get_guidance (workflow help & risk assessment)" -ForegroundColor White
Write-Host ""
Write-Host "Key Management:" -ForegroundColor Cyan
Write-Host "  Manage token: .\deploy\manage_api_keys.ps1 -Action check|test|delete" -ForegroundColor Yellow
Write-Host "  Get token:    https://www.courtlistener.com/sign-in/" -ForegroundColor White
Write-Host ""
Write-Host "Test with: validate_citations" -ForegroundColor Yellow
Write-Host "Learn workflows: get_guidance(section='overview')" -ForegroundColor Yellow
Write-Host ""
