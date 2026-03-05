#Requires -Version 5.1
<#
.SYNOPSIS
    Unified API key management for the MCP suite (CourtListener + shared keys).

.DESCRIPTION
    Manage all API keys used by CourtListener MCP and shared across the suite:
      - CourtListener API token     (required, 40-char hex)
      - Pinecone API key            (optional, for future Pinecone endpoint use)
      - Real OpenAI API key         (optional, shared with Pinecone MCPs)
      - Chat API key                (optional, any provider)
      - Embedding API key           (optional, real OpenAI)
      - Cohere API key              (optional, reranking)
      - Mistral OCR API key         (optional, stored in ~/.pinecone_mistral_api_key)

    Storage:
      - CourtListener: Windows Credential Manager (primary) -> DPAPI file fallback
      - All others:    DPAPI encrypted file, shared entropy from ~/.uspto_internal_auth_secret

    Note: ~/.mistral_api_key belongs to USPTO MCPs. This script uses
          ~/.pinecone_mistral_api_key to avoid collision.

.EXAMPLE
    .\manage_api_keys.ps1
#>

Add-Type -AssemblyName System.Security

# Import validation helpers
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Import-Module "$ScriptDir\Validation-Helpers.psm1" -Force

# ============================================================================
# Storage Configuration
# ============================================================================

$CL_CREDENTIAL_TARGET       = "CourtListener MCP:API_TOKEN"
$CL_TOKEN_PATH              = Join-Path $env:USERPROFILE ".courtlistener_api_token"
$PINECONE_KEY_PATH          = Join-Path $env:USERPROFILE ".pinecone_api_key"
$OPENAI_KEY_PATH            = Join-Path $env:USERPROFILE ".openai_api_key"             # real OpenAI only (sk-proj-)
$OPENAI_COMPATIBLE_KEY_PATH = Join-Path $env:USERPROFILE ".openai_compatible_api_key"  # chat key, any provider
$EMBEDDING_KEY_PATH         = Join-Path $env:USERPROFILE ".embedding_api_key"          # embedding endpoint key
$COHERE_KEY_PATH            = Join-Path $env:USERPROFILE ".cohere_api_key"
$PINECONE_MISTRAL_KEY_PATH  = Join-Path $env:USERPROFILE ".pinecone_mistral_api_key"   # NOT ~/.mistral_api_key (USPTO)
$SHARED_ENTROPY_PATH        = Join-Path $env:USERPROFILE ".uspto_internal_auth_secret"
$SHARED_ENTROPY_BYTES       = 32   # 256-bit entropy seed

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
        if ($bytes.Length -ge $SHARED_ENTROPY_BYTES) {
            # File may be larger than 32 bytes (USPTO Python format) - use only first 32 bytes as entropy
            if ($bytes.Length -gt $SHARED_ENTROPY_BYTES) {
                $seed = New-Object byte[] $SHARED_ENTROPY_BYTES
                [System.Array]::Copy($bytes, $seed, $SHARED_ENTROPY_BYTES)
                return $seed
            }
            return $bytes
        }
        Write-Host "[WARN] Entropy file too small ($($bytes.Length) bytes, need $SHARED_ENTROPY_BYTES) - recreating" -ForegroundColor Yellow
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
# DPAPI File Storage
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
# Generic DPAPI Key Updater
# ============================================================================

function Update-DpapiKey {
    <#
    .SYNOPSIS
    Prompt for a key value, validate it, and write to a DPAPI key file.
    Supports up to 3 attempts. ValidatorName is the name of a Test-* function
    exported from Validation-Helpers.psm1.
    #>
    param(
        [string]$Label,
        [string]$FilePath,
        [string]$ValidatorName,
        [string]$Hint
    )

    Write-Host ""
    Write-Host "  $Label" -ForegroundColor Cyan
    if ($Hint) { Write-Host "  Format: $Hint" -ForegroundColor Gray }

    $maxAttempts = 3; $attempt = 0
    while ($attempt -lt $maxAttempts) {
        $attempt++
        $key = Read-ApiKeySecure -Prompt "  New key (leave blank to cancel)"
        if ([string]::IsNullOrWhiteSpace($key)) { Write-Host "[INFO] Cancelled" -ForegroundColor Yellow; return }

        $key = $key.Trim()
        $valid = $true
        if ($ValidatorName -and (Get-Command $ValidatorName -ErrorAction SilentlyContinue)) {
            $valid = & $ValidatorName -ApiKey $key
        }
        if ($valid) {
            if (Set-DpapiKeyToFile -FilePath $FilePath -KeyValue $key) {
                Write-Host "[OK] $Label stored" -ForegroundColor Green
                Write-Host "     File: $FilePath (DPAPI encrypted)" -ForegroundColor Gray
            }
            return
        }
        Write-Host "[ERROR] Invalid format (attempt $attempt/$maxAttempts)" -ForegroundColor Red
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
# Status Check - all keys
# ============================================================================

function Show-DpapiKeyStatus {
    param([string]$Label, [string]$FilePath, [switch]$Optional)

    $fileExists = Test-Path $FilePath
    $value = Get-DpapiKeyFromFile -FilePath $FilePath -Silent

    if ($value) {
        $masked = Hide-ApiKey -ApiKey $value
        Write-Host "[OK] $Label`: $masked" -ForegroundColor Green
        Write-Host "     File: $FilePath" -ForegroundColor Gray
    }
    elseif ($fileExists) {
        Write-Host "[!!] $Label`: File exists but cannot be decrypted" -ForegroundColor Red
        Write-Host "     Re-enter the key to overwrite the file" -ForegroundColor Yellow
    }
    elseif ($Optional) {
        Write-Host "[--] $Label`: Not set  (optional)" -ForegroundColor Yellow
    }
    else {
        Write-Host "[!!] $Label`: Not set  [REQUIRED]" -ForegroundColor Red
    }
}

function Show-KeyStatus {
    Write-Host ""
    Write-Host "Current Key Status" -ForegroundColor Cyan
    Write-Host "==================" -ForegroundColor Cyan
    Write-Host ""

    # Entropy seed
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
    }
    else {
        Write-Host "[!!] CourtListener Token: Not set  [REQUIRED]" -ForegroundColor Red
    }
    if (Test-Path $CL_TOKEN_PATH) {
        $sz = (Get-Item $CL_TOKEN_PATH).Length
        Write-Host "     DPAPI file: $CL_TOKEN_PATH ($sz bytes)" -ForegroundColor Gray
    }
    Write-Host ""

    # Shared keys
    Show-DpapiKeyStatus -Label "Real OpenAI key     (~/.openai_api_key)" `
                        -FilePath $OPENAI_KEY_PATH -Optional
    Write-Host ""
    Show-DpapiKeyStatus -Label "Chat API key        (~/.openai_compatible_api_key)" `
                        -FilePath $OPENAI_COMPATIBLE_KEY_PATH -Optional
    Write-Host ""
    Show-DpapiKeyStatus -Label "Embedding key       (~/.embedding_api_key)" `
                        -FilePath $EMBEDDING_KEY_PATH -Optional
    Write-Host ""
    Show-DpapiKeyStatus -Label "Pinecone key        (~/.pinecone_api_key)" `
                        -FilePath $PINECONE_KEY_PATH -Optional
    Write-Host ""
    Show-DpapiKeyStatus -Label "Cohere key          (~/.cohere_api_key)" `
                        -FilePath $COHERE_KEY_PATH -Optional
    Write-Host ""
    Show-DpapiKeyStatus -Label "Mistral OCR key     (~/.pinecone_mistral_api_key)" `
                        -FilePath $PINECONE_MISTRAL_KEY_PATH -Optional
    Write-Host ""
}

# ============================================================================
# Live API Test - CourtListener connection
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

# ============================================================================
# Delete helpers
# ============================================================================

function Remove-DpapiKey {
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

    $pythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $pythonExe)) {
        Write-Host "[ERROR] Virtual environment not found. Run windows_setup.ps1 first." -ForegroundColor Red
        return
    }

    $pythonCode = @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
try:
    from courtlistener_mcp.shared.secure_storage import migrate_to_credential_manager
    success = migrate_to_credential_manager()
    print('SUCCESS' if success else 'SKIPPED')
except AttributeError:
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
        Write-Host "  CourtListener:" -ForegroundColor Gray
        Write-Host "    [1] Update CourtListener API token"
        Write-Host "    [2] Test CourtListener connection"
        Write-Host ""
        Write-Host "  Shared OpenAI keys:" -ForegroundColor Gray
        Write-Host "    [3] Update real OpenAI key       (~/.openai_api_key, shared with Pinecone)"
        Write-Host "    [4] Update chat API key          (~/.openai_compatible_api_key, any provider)"
        Write-Host "    [5] Update embedding API key     (~/.embedding_api_key)"
        Write-Host ""
        Write-Host "  Optional keys:" -ForegroundColor Gray
        Write-Host "    [6] Update Pinecone key          (~/.pinecone_api_key)"
        Write-Host "    [7] Update Cohere key            (~/.cohere_api_key)"
        Write-Host "    [8] Update Mistral OCR key       (~/.pinecone_mistral_api_key)"
        Write-Host ""
        Write-Host "  Management:" -ForegroundColor Gray
        Write-Host "    [9] Remove key(s)"
        Write-Host "    [M] Migrate CourtListener token (DPAPI file -> Credential Manager)"
        Write-Host "    [R] Show key format requirements"
        Write-Host "    [0] Exit"
        Write-Host ""

        $choice = Read-Host "Enter choice"

        switch ($choice.ToUpper()) {

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
                Test-CourtListenerConnection
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "3" {
                Update-DpapiKey `
                    -Label "Real OpenAI key (~/.openai_api_key, shared with Pinecone)" `
                    -FilePath $OPENAI_KEY_PATH `
                    -ValidatorName "Test-RealOpenAiApiKey" `
                    -Hint "sk-proj-... or sk-... (must be a real OpenAI key, not Inception or OpenRouter)"
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "4" {
                Update-DpapiKey `
                    -Label "Chat API key (~/.openai_compatible_api_key, any provider)" `
                    -FilePath $OPENAI_COMPATIBLE_KEY_PATH `
                    -ValidatorName "Test-OpenAiApiKey" `
                    -Hint "sk-proj-... (OpenAI), sk_... (Inception), sk-or-... (OpenRouter), ollama"
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "5" {
                Update-DpapiKey `
                    -Label "Embedding API key (~/.embedding_api_key)" `
                    -FilePath $EMBEDDING_KEY_PATH `
                    -ValidatorName "Test-RealOpenAiApiKey" `
                    -Hint "sk-proj-... or sk-... (real OpenAI key for embeddings)"
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "6" {
                Update-DpapiKey `
                    -Label "Pinecone API key (~/.pinecone_api_key)" `
                    -FilePath $PINECONE_KEY_PATH `
                    -ValidatorName "Test-PineconeApiKey" `
                    -Hint "pcsk_ + 70 alphanumeric/underscore chars (75 total)"
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "7" {
                Update-DpapiKey `
                    -Label "Cohere reranking key (~/.cohere_api_key)" `
                    -FilePath $COHERE_KEY_PATH `
                    -ValidatorName "Test-CohereApiKey" `
                    -Hint "40 alphanumeric characters"
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "8" {
                Update-DpapiKey `
                    -Label "Mistral OCR key (~/.pinecone_mistral_api_key)" `
                    -FilePath $PINECONE_MISTRAL_KEY_PATH `
                    -ValidatorName "Test-MistralApiKey" `
                    -Hint "32 alphanumeric characters (optional)"
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "9" {
                Write-Host ""
                Write-Host "Remove API Key(s)" -ForegroundColor Cyan
                Write-Host "=================" -ForegroundColor Cyan
                Write-Host "  [1] Remove CourtListener token"
                Write-Host "  [2] Remove real OpenAI key"
                Write-Host "  [3] Remove chat API key"
                Write-Host "  [4] Remove embedding API key"
                Write-Host "  [5] Remove Pinecone key"
                Write-Host "  [6] Remove Cohere key"
                Write-Host "  [7] Remove Mistral OCR key"
                Write-Host "  [8] Remove ALL keys"
                Write-Host "  [9] Cancel"
                Write-Host ""

                $removeChoice = Read-Host "Enter choice (1-9)"

                switch ($removeChoice) {
                    "1" {
                        $confirm = Read-Host "Remove CourtListener token from ALL storage locations? (y/N)"
                        if ($confirm -eq 'y' -or $confirm -eq 'Y') { Remove-CourtListenerToken }
                        else { Write-Host "[INFO] Cancelled" -ForegroundColor Yellow }
                    }
                    "2" { Remove-DpapiKey -FilePath $OPENAI_KEY_PATH -KeyName "Real OpenAI" }
                    "3" { Remove-DpapiKey -FilePath $OPENAI_COMPATIBLE_KEY_PATH -KeyName "Chat API" }
                    "4" { Remove-DpapiKey -FilePath $EMBEDDING_KEY_PATH -KeyName "Embedding" }
                    "5" { Remove-DpapiKey -FilePath $PINECONE_KEY_PATH -KeyName "Pinecone" }
                    "6" { Remove-DpapiKey -FilePath $COHERE_KEY_PATH -KeyName "Cohere" }
                    "7" { Remove-DpapiKey -FilePath $PINECONE_MISTRAL_KEY_PATH -KeyName "Mistral OCR" }
                    "8" {
                        $confirm = Read-Host "Remove ALL API keys from ALL storage locations? (y/N)"
                        if ($confirm -eq 'y' -or $confirm -eq 'Y') {
                            Remove-CourtListenerToken
                            Remove-DpapiKey -FilePath $OPENAI_KEY_PATH -KeyName "Real OpenAI"
                            Remove-DpapiKey -FilePath $OPENAI_COMPATIBLE_KEY_PATH -KeyName "Chat API"
                            Remove-DpapiKey -FilePath $EMBEDDING_KEY_PATH -KeyName "Embedding"
                            Remove-DpapiKey -FilePath $PINECONE_KEY_PATH -KeyName "Pinecone"
                            Remove-DpapiKey -FilePath $COHERE_KEY_PATH -KeyName "Cohere"
                            Remove-DpapiKey -FilePath $PINECONE_MISTRAL_KEY_PATH -KeyName "Mistral OCR"
                        }
                        else { Write-Host "[INFO] Cancelled" -ForegroundColor Yellow }
                    }
                    "9" { Write-Host "[INFO] Cancelled" -ForegroundColor Yellow }
                    default { Write-Host "[ERROR] Invalid choice" -ForegroundColor Red }
                }

                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "M" {
                Invoke-MigrateCourtListenerToken
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "R" {
                Show-ApiKeyRequirements
                Write-Host ""
                Read-Host "Press Enter to continue"
            }

            "0" {
                Write-Host ""
                Write-Host "Goodbye!" -ForegroundColor Green
                exit 0
            }

            default {
                Write-Host ""
                Write-Host "[ERROR] Invalid choice." -ForegroundColor Red
                Start-Sleep -Seconds 2
            }
        }
    }
}

Main
