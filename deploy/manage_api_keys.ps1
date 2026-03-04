#Requires -Version 5.1
<#
.SYNOPSIS
    Interactive API key management for CourtListener Citation Validation MCP.

.DESCRIPTION
    Manage all API keys used by this MCP:
      - CourtListener API token  (required, 40-char hex)
      - OpenAI API key           (optional, sk-... format)
      - Mistral API key          (optional, 32-char alphanumeric)

    Storage:
      - CourtListener: Windows Credential Manager (primary) -> DPAPI file fallback (~/.courtlistener_api_token)
      - OpenAI:        DPAPI encrypted file (~/.openai_api_key)
      - Mistral:       DPAPI encrypted file (~/.mistral_api_key)

.EXAMPLE
    .\manage_api_keys.ps1
#>

#Requires -Version 5.1

Add-Type -AssemblyName System.Security

# Import validation helpers
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Import-Module "$ScriptDir\Validation-Helpers.psm1" -Force

# ============================================================================
# Storage Configuration
# ============================================================================

$CL_CREDENTIAL_TARGET  = "CourtListener MCP:API_TOKEN"
$CL_TOKEN_PATH         = Join-Path $env:USERPROFILE ".courtlistener_api_token"
$OPENAI_KEY_PATH       = Join-Path $env:USERPROFILE ".openai_api_key"
$MISTRAL_KEY_PATH      = Join-Path $env:USERPROFILE ".mistral_api_key"
$SHARED_ENTROPY_PATH   = Join-Path $env:USERPROFILE ".uspto_internal_auth_secret"
$SHARED_ENTROPY_BYTES  = 32   # 256-bit entropy seed

$ProjectDir = Split-Path -Parent $ScriptDir

# ============================================================================
# Shared Entropy Seed (used by all MCPs in the suite)
# ============================================================================
# ~/.uspto_internal_auth_secret is a raw 32-byte binary file.
# It is the entropy seed for all DPAPI file-based key storage across the MCP suite.
# "First MCP wins" pattern: whoever runs setup first generates it;
# all subsequent MCPs reuse the same file.

function Get-SharedEntropy {
    if (Test-Path $SHARED_ENTROPY_PATH) {
        $bytes = [System.IO.File]::ReadAllBytes($SHARED_ENTROPY_PATH)
        if ($bytes.Length -eq $SHARED_ENTROPY_BYTES) {
            return $bytes
        }
        Write-Host "[WARN] Entropy file has unexpected size ($($bytes.Length) bytes) - recreating" -ForegroundColor Yellow
    }

    # Create new entropy file
    Write-Host "[INFO] Creating shared entropy seed: $SHARED_ENTROPY_PATH" -ForegroundColor Cyan
    $entropy = New-Object byte[] $SHARED_ENTROPY_BYTES
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($entropy)
    $rng.Dispose()

    [System.IO.File]::WriteAllBytes($SHARED_ENTROPY_PATH, $entropy)

    # Restrict to current user only
    try {
        $acl = Get-Acl $SHARED_ENTROPY_PATH
        $acl.SetAccessRuleProtection($true, $false)
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $identity, "FullControl",
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $acl.SetAccessRule($rule)
        Set-Acl $SHARED_ENTROPY_PATH $acl
    }
    catch {
        Write-Host "[WARN] Could not set file permissions on entropy file: $_" -ForegroundColor Yellow
    }

    Write-Host "[OK] Shared entropy seed created: $SHARED_ENTROPY_PATH" -ForegroundColor Green
    return $entropy
}

# ============================================================================
# DPAPI File Storage (used for OpenAI and Mistral)
# ============================================================================
# File format: raw DPAPI-encrypted blob only.
# Entropy is loaded from ~/.uspto_internal_auth_secret (not embedded in the file).

function Get-DpapiKeyFromFile {
    param([string]$FilePath, [switch]$Silent)

    if (-not (Test-Path $FilePath)) { return $null }

    try {
        $entropy   = Get-SharedEntropy
        $encrypted = [System.IO.File]::ReadAllBytes($FilePath)

        $decrypted = [System.Security.Cryptography.ProtectedData]::Unprotect(
            $encrypted, $entropy,
            [System.Security.Cryptography.DataProtectionScope]::CurrentUser
        )

        return [System.Text.Encoding]::UTF8.GetString($decrypted)
    }
    catch {
        if (-not $Silent) { Write-Host "[WARN] Failed to decrypt key file ($FilePath): $_" -ForegroundColor Yellow }
        return $null
    }
}

function Set-DpapiKeyToFile {
    param([string]$FilePath, [string]$KeyValue)

    try {
        $entropy   = Get-SharedEntropy
        $keyBytes  = [System.Text.Encoding]::UTF8.GetBytes($KeyValue)
        $encrypted = [System.Security.Cryptography.ProtectedData]::Protect(
            $keyBytes, $entropy,
            [System.Security.Cryptography.DataProtectionScope]::CurrentUser
        )

        [System.IO.File]::WriteAllBytes($FilePath, $encrypted)
        return $true
    }
    catch {
        Write-Host "[ERROR] Failed to encrypt/write key file ($FilePath): $_" -ForegroundColor Red
        return $false
    }
}

# ============================================================================
# CourtListener Token - Python-backed secure storage
# ============================================================================

function Get-CourtListenerToken {
    <# Tries Python secure_storage first, then falls back to Credential Manager cmdkey check. #>
    try {
        $pythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
        if (-not (Test-Path $pythonExe)) { return $null }

        $pythonCode = @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
try:
    from courtlistener_mcp.shared.secure_storage import get_api_token
    token = get_api_token()
    print('TOKEN:' + token if token else 'TOKEN:')
except Exception as e:
    print('ERROR:' + str(e))
'@
        Push-Location $ProjectDir
        $result = & $pythonExe -c $pythonCode 2>$null | Out-String
        Pop-Location
        if ($result -match "^TOKEN:(.*)") {
            $token = $matches[1].Trim()
            if ($token) { return $token } else { return $null }
        }
    }
    catch { Pop-Location }
    return $null
}

function Set-CourtListenerToken {
    param([string]$Token)

    try {
        $pythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
        if (-not (Test-Path $pythonExe)) {
            Write-Host "[ERROR] Virtual environment not found. Run windows_setup.ps1 first." -ForegroundColor Red
            return $false
        }

        $env:_CL_MGR_TOKEN = $Token
        $pythonCode = @'
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
try:
    from courtlistener_mcp.shared.secure_storage import store_api_token
    token = os.environ.get('_CL_MGR_TOKEN', '')
    success = store_api_token(token)
    print('SUCCESS' if success else 'FAILED')
except Exception as e:
    print('ERROR:' + str(e))
'@
        Push-Location $ProjectDir
        $result = & $pythonExe -c $pythonCode 2>$null | Out-String
        Pop-Location
        Remove-Item Env:\_CL_MGR_TOKEN -ErrorAction SilentlyContinue

        if ($result -match "SUCCESS") {
            Write-Host "[OK] CourtListener token stored (Credential Manager + DPAPI backup)" -ForegroundColor Green
            return $true
        }
        else {
            Write-Host "[WARN] Python storage failed: $result" -ForegroundColor Yellow
            return $false
        }
    }
    catch {
        Remove-Item Env:\_CL_MGR_TOKEN -ErrorAction SilentlyContinue
        Write-Host "[WARN] Python storage error: $_" -ForegroundColor Yellow
        return $false
    }
}

function Remove-CourtListenerToken {
    $deleted = $false

    # Remove from Credential Manager via cmdkey
    cmdkey /delete:$CL_CREDENTIAL_TARGET 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Deleted from Windows Credential Manager" -ForegroundColor Green
        $deleted = $true
    }

    # Remove DPAPI file
    if (Test-Path $CL_TOKEN_PATH) {
        Remove-Item $CL_TOKEN_PATH -Force
        Write-Host "[OK] Deleted DPAPI backup file: $CL_TOKEN_PATH" -ForegroundColor Green
        $deleted = $true
    }

    if (-not $deleted) {
        Write-Host "[INFO] No stored CourtListener token found" -ForegroundColor Yellow
    }
}

# ============================================================================
# Status Check - all three keys
# ============================================================================

function Show-KeyStatus {
    Write-Host ""
    Write-Host "Current Key Status" -ForegroundColor Cyan
    Write-Host "==================" -ForegroundColor Cyan
    Write-Host ""

    # Entropy seed status
    if (Test-Path $SHARED_ENTROPY_PATH) {
        $entropySize = (Get-Item $SHARED_ENTROPY_PATH).Length
        Write-Host "[OK] Entropy seed:        $SHARED_ENTROPY_PATH ($entropySize bytes)" -ForegroundColor Green
    }
    else {
        Write-Host "[--] Entropy seed:        Not found - will be created on first key operation" -ForegroundColor Yellow
        Write-Host "     Path: $SHARED_ENTROPY_PATH" -ForegroundColor Gray
    }
    Write-Host ""

    # CourtListener token
    $clToken = Get-CourtListenerToken
    $clEnv   = $env:COURTLISTENER_API_TOKEN

    if ($clToken) {
        $masked = Hide-ApiKey -ApiKey $clToken
        Write-Host "[OK] CourtListener Token: $masked" -ForegroundColor Green
        Write-Host "     Storage: Credential Manager / DPAPI" -ForegroundColor Gray
    }
    elseif ($clEnv) {
        $masked = Hide-ApiKey -ApiKey $clEnv
        Write-Host "[OK] CourtListener Token: $masked (env var only)" -ForegroundColor Yellow
        Write-Host "     Storage: COURTLISTENER_API_TOKEN environment variable" -ForegroundColor Gray
    }
    else {
        Write-Host "[!!] CourtListener Token: Not set  [REQUIRED]" -ForegroundColor Red
    }

    # Also show storage file status for CL
    if (Test-Path $CL_TOKEN_PATH) {
        $fileSize = (Get-Item $CL_TOKEN_PATH).Length
        Write-Host "     DPAPI file: $CL_TOKEN_PATH ($fileSize bytes)" -ForegroundColor Gray
    }
    Write-Host ""

    # OpenAI key
    $oaiFileExists = Test-Path $OPENAI_KEY_PATH
    $oaiKey = Get-DpapiKeyFromFile -FilePath $OPENAI_KEY_PATH -Silent
    if ($oaiKey) {
        $masked = Hide-ApiKey -ApiKey $oaiKey
        Write-Host "[OK] OpenAI API Key:      $masked" -ForegroundColor Green
        Write-Host "     Storage: $OPENAI_KEY_PATH (DPAPI)" -ForegroundColor Gray
    }
    elseif ($env:OPENAI_API_KEY) {
        $masked = Hide-ApiKey -ApiKey $env:OPENAI_API_KEY
        Write-Host "[OK] OpenAI API Key:      $masked (env var only)" -ForegroundColor Yellow
    }
    elseif ($oaiFileExists) {
        Write-Host "[!!] OpenAI API Key:      File exists but cannot be decrypted (incompatible format)" -ForegroundColor Red
        Write-Host "     Use option [2] to re-enter your key and overwrite the file" -ForegroundColor Yellow
    }
    else {
        Write-Host "[--] OpenAI API Key:      Not set  (optional)" -ForegroundColor Yellow
    }
    Write-Host ""

    # Mistral key
    $mistralFileExists = Test-Path $MISTRAL_KEY_PATH
    $mistralKey = Get-DpapiKeyFromFile -FilePath $MISTRAL_KEY_PATH -Silent
    if ($mistralKey) {
        $masked = Hide-ApiKey -ApiKey $mistralKey
        Write-Host "[OK] Mistral API Key:     $masked" -ForegroundColor Green
        Write-Host "     Storage: $MISTRAL_KEY_PATH (DPAPI)" -ForegroundColor Gray
    }
    elseif ($env:MISTRAL_API_KEY) {
        $masked = Hide-ApiKey -ApiKey $env:MISTRAL_API_KEY
        Write-Host "[OK] Mistral API Key:     $masked (env var only)" -ForegroundColor Yellow
    }
    elseif ($mistralFileExists) {
        Write-Host "[!!] Mistral API Key:     File exists but cannot be decrypted (incompatible format)" -ForegroundColor Red
        Write-Host "     Use option [3] to re-enter your key and overwrite the file" -ForegroundColor Yellow
    }
    else {
        Write-Host "[--] Mistral API Key:     Not set  (optional)" -ForegroundColor Yellow
    }
    Write-Host ""
}

# ============================================================================
# Live API Test - CourtListener only (others are validated by format only)
# ============================================================================

function Test-CourtListenerConnection {
    Write-Host ""
    Write-Host "Testing CourtListener API connection..." -ForegroundColor Cyan

    $token = Get-CourtListenerToken
    if (-not $token) { $token = $env:COURTLISTENER_API_TOKEN }
    if (-not $token) {
        Write-Host "[ERROR] No CourtListener token available to test" -ForegroundColor Red
        return
    }

    try {
        $headers  = @{
            "Authorization" = "Token $token"
            "User-Agent"    = "CourtListener-MCP/1.0 (manage_api_keys.ps1)"
        }
        $response = Invoke-RestMethod -Uri "https://www.courtlistener.com/api/rest/v4/" `
                        -Headers $headers -Method Get -ErrorAction Stop

        Write-Host "[OK] CourtListener API connection successful" -ForegroundColor Green
        Write-Host "     Available endpoints: $($response.PSObject.Properties.Count)" -ForegroundColor Gray
    }
    catch {
        $statusCode = $_.Exception.Response.StatusCode.Value__
        if ($statusCode -eq 401) {
            Write-Host "[ERROR] API returned 401 Unauthorized - token may be invalid or expired" -ForegroundColor Red
        }
        elseif ($statusCode) {
            Write-Host "[ERROR] API returned HTTP $statusCode" -ForegroundColor Red
        }
        else {
            Write-Host "[ERROR] Connection failed: $_" -ForegroundColor Red
        }
    }
}

function Test-OpenAiKeyFormat {
    $key = Get-DpapiKeyFromFile -FilePath $OPENAI_KEY_PATH
    if (-not $key) { $key = $env:OPENAI_API_KEY }
    if (-not $key) {
        Write-Host "[--] OpenAI API Key: Not configured (optional)" -ForegroundColor Yellow
        return
    }
    if (Test-OpenAiApiKey -ApiKey $key -Silent) {
        Write-Host "[OK] OpenAI API key format valid" -ForegroundColor Green
    }
    else {
        Write-Host "[!!] OpenAI API key format INVALID - please update it" -ForegroundColor Red
    }
}

function Test-MistralKeyFormat {
    $key = Get-DpapiKeyFromFile -FilePath $MISTRAL_KEY_PATH
    if (-not $key) { $key = $env:MISTRAL_API_KEY }
    if (-not $key) {
        Write-Host "[--] Mistral API Key: Not configured (optional)" -ForegroundColor Yellow
        return
    }
    if (Test-MistralApiKey -ApiKey $key -Silent) {
        Write-Host "[OK] Mistral API key format valid (32 chars, alphanumeric)" -ForegroundColor Green
    }
    else {
        Write-Host "[!!] Mistral API key format INVALID - please update it" -ForegroundColor Red
    }
}

# ============================================================================
# Delete helpers
# ============================================================================

function Remove-OptionalKey {
    param([string]$FilePath, [string]$KeyName)

    if (Test-Path $FilePath) {
        Remove-Item $FilePath -Force
        Write-Host "[OK] Deleted $KeyName key file: $FilePath" -ForegroundColor Green
    }
    else {
        Write-Host "[INFO] No $KeyName key file found" -ForegroundColor Yellow
    }
}

# ============================================================================
# Migrate CourtListener token from DPAPI file -> Credential Manager
# ============================================================================

function Invoke-MigrateCourtListenerToken {
    Write-Host ""
    Write-Host "Migrating CourtListener token from DPAPI file to Credential Manager..." -ForegroundColor Cyan

    # Already in Credential Manager?
    $existing = Get-CourtListenerToken
    if ($existing) {
        Write-Host "[OK] Token already present in Credential Manager - nothing to migrate" -ForegroundColor Green
        return
    }

    if (-not (Test-Path $CL_TOKEN_PATH)) {
        Write-Host "[INFO] No DPAPI file found at $CL_TOKEN_PATH - nothing to migrate" -ForegroundColor Yellow
        return
    }

    # Read and decrypt the DPAPI file using the courtlistener_mcp module
    $pythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $pythonExe)) {
        Write-Host "[ERROR] Virtual environment not found. Run windows_setup.ps1 first." -ForegroundColor Red
        return
    }

    # store_api_token reads the file automatically during migration
    $pythonCode = @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
try:
    from courtlistener_mcp.shared.secure_storage import migrate_to_credential_manager
    success = migrate_to_credential_manager()
    print('SUCCESS' if success else 'SKIPPED')
except AttributeError:
    # Function may not exist in older versions - call store_api_token with file content
    from courtlistener_mcp.shared.secure_storage import get_api_token, store_api_token
    token = get_api_token()
    if token:
        success = store_api_token(token)
        print('SUCCESS' if success else 'FAILED')
    else:
        print('NO_TOKEN')
except Exception as e:
    print('ERROR:' + str(e))
'@

    Push-Location $ProjectDir
    $result = & $pythonExe -c $pythonCode 2>$null | Out-String
    Pop-Location
    if ($result -match "SUCCESS") {
        Write-Host "[OK] Migration successful - token now in Credential Manager" -ForegroundColor Green
        Write-Host "     DPAPI file retained as backup: $CL_TOKEN_PATH" -ForegroundColor Gray
    }
    elseif ($result -match "SKIPPED") {
        Write-Host "[OK] Token already in Credential Manager" -ForegroundColor Green
    }
    elseif ($result -match "NO_TOKEN") {
        Write-Host "[ERROR] Could not read token from DPAPI file - file may be corrupted" -ForegroundColor Red
    }
    else {
        Write-Host "[ERROR] Migration failed: $result" -ForegroundColor Red
    }
}

# ============================================================================
# Main interactive menu
# ============================================================================

function Main {
    while ($true) {
        Clear-Host
        Write-Host "CourtListener Citation MCP - API Key Management" -ForegroundColor Cyan
        Write-Host "================================================" -ForegroundColor Cyan

        Show-KeyStatus

        Write-Host "Actions:" -ForegroundColor White
        Write-Host "  [1] Update CourtListener API token"
        Write-Host "  [2] Update OpenAI API key"
        Write-Host "  [3] Update Mistral API key"
        Write-Host "  [4] Test all keys"
        Write-Host "  [5] Remove key(s)"
        Write-Host "  [6] Migrate CourtListener token (DPAPI file -> Credential Manager)"
        Write-Host "  [7] Show key format requirements"
        Write-Host "  [8] Exit"
        Write-Host ""

        $choice = Read-Host "Enter choice (1-8)"

        switch ($choice) {

            "1" {
                Write-Host ""
                Write-Host "Update CourtListener API Token" -ForegroundColor Cyan
                Write-Host "==============================" -ForegroundColor Cyan
                Write-Host ""
                Write-Host "[INFO] Get your free token at: https://www.courtlistener.com/sign-in/" -ForegroundColor Yellow
                Write-Host ""

                $newToken = Read-CourtListenerTokenWithValidation

                if ($newToken) {
                    Set-CourtListenerToken -Token $newToken | Out-Null
                }
                else {
                    Write-Host "[INFO] Operation cancelled - no valid token provided" -ForegroundColor Yellow
                }

                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "2" {
                Write-Host ""
                Write-Host "Update OpenAI API Key" -ForegroundColor Cyan
                Write-Host "=====================" -ForegroundColor Cyan
                Write-Host ""

                $newKey = Read-OpenAiApiKeyWithValidation

                if ($newKey -and $newKey -ne "") {
                    if (Set-DpapiKeyToFile -FilePath $OPENAI_KEY_PATH -KeyValue $newKey) {
                        Write-Host "[OK] OpenAI API key stored: $OPENAI_KEY_PATH (DPAPI encrypted)" -ForegroundColor Green
                    }
                }
                elseif ($null -eq $newKey) {
                    Write-Host "[ERROR] Validation failed after maximum attempts" -ForegroundColor Red
                }
                else {
                    Write-Host "[INFO] Operation cancelled - no key provided" -ForegroundColor Yellow
                }

                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "3" {
                Write-Host ""
                Write-Host "Update Mistral API Key" -ForegroundColor Cyan
                Write-Host "======================" -ForegroundColor Cyan
                Write-Host ""

                $newKey = Read-MistralApiKeyWithValidation

                if ($newKey -and $newKey -ne "") {
                    if (Set-DpapiKeyToFile -FilePath $MISTRAL_KEY_PATH -KeyValue $newKey) {
                        Write-Host "[OK] Mistral API key stored: $MISTRAL_KEY_PATH (DPAPI encrypted)" -ForegroundColor Green
                    }
                }
                elseif ($null -eq $newKey) {
                    Write-Host "[ERROR] Validation failed after maximum attempts" -ForegroundColor Red
                }
                else {
                    Write-Host "[INFO] Operation cancelled - no key provided" -ForegroundColor Yellow
                }

                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "4" {
                Write-Host ""
                Write-Host "Key Validation" -ForegroundColor Cyan
                Write-Host "==============" -ForegroundColor Cyan
                Test-CourtListenerConnection
                Write-Host ""
                Test-OpenAiKeyFormat
                Test-MistralKeyFormat
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "5" {
                Write-Host ""
                Write-Host "Remove API Key(s)" -ForegroundColor Cyan
                Write-Host "=================" -ForegroundColor Cyan
                Write-Host "  [1] Remove CourtListener token"
                Write-Host "  [2] Remove OpenAI API key"
                Write-Host "  [3] Remove Mistral API key"
                Write-Host "  [4] Remove ALL keys"
                Write-Host "  [5] Cancel"
                Write-Host ""

                $removeChoice = Read-Host "Enter choice (1-5)"

                switch ($removeChoice) {
                    "1" {
                        $confirm = Read-Host "Remove CourtListener token from ALL storage locations? (y/N)"
                        if ($confirm -eq 'y' -or $confirm -eq 'Y') {
                            Remove-CourtListenerToken
                        }
                        else { Write-Host "[INFO] Cancelled" -ForegroundColor Yellow }
                    }
                    "2" { Remove-OptionalKey -FilePath $OPENAI_KEY_PATH -KeyName "OpenAI" }
                    "3" { Remove-OptionalKey -FilePath $MISTRAL_KEY_PATH -KeyName "Mistral" }
                    "4" {
                        $confirm = Read-Host "Remove ALL API keys from ALL storage locations? (y/N)"
                        if ($confirm -eq 'y' -or $confirm -eq 'Y') {
                            Remove-CourtListenerToken
                            Remove-OptionalKey -FilePath $OPENAI_KEY_PATH -KeyName "OpenAI"
                            Remove-OptionalKey -FilePath $MISTRAL_KEY_PATH -KeyName "Mistral"
                        }
                        else { Write-Host "[INFO] Cancelled" -ForegroundColor Yellow }
                    }
                    "5" { Write-Host "[INFO] Cancelled" -ForegroundColor Yellow }
                    default { Write-Host "[ERROR] Invalid choice" -ForegroundColor Red }
                }

                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "6" {
                Invoke-MigrateCourtListenerToken
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "7" {
                Show-ApiKeyRequirements
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "8" {
                Write-Host ""
                Write-Host "Goodbye!" -ForegroundColor Green
                exit 0
            }

            default {
                Write-Host ""
                Write-Host "[ERROR] Invalid choice. Please enter 1-8." -ForegroundColor Red
                Start-Sleep -Seconds 2
            }
        }
    }
}

Main
