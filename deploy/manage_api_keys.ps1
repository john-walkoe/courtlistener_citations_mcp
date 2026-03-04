#Requires -Version 5.1
<#
.SYNOPSIS
    Manage CourtListener API token storage.

.DESCRIPTION
    View, test, or delete the stored CourtListener API token.
    Supports both Windows Credential Manager (primary) and file-based DPAPI (fallback).

.PARAMETER Action
    Action to perform: check, test, delete, migrate

.EXAMPLE
    .\manage_api_keys.ps1 -Action check
    .\manage_api_keys.ps1 -Action test
    .\manage_api_keys.ps1 -Action delete
    .\manage_api_keys.ps1 -Action migrate
#>

param(
    [ValidateSet("check", "test", "delete", "migrate")]
    [string]$Action = "check"
)

Add-Type -AssemblyName System.Security

$StoragePath = Join-Path $env:USERPROFILE ".courtlistener_api_token"
$EntropyBytes = 32
$CredentialTarget = "CourtListener MCP:API_TOKEN"

# ============================================================================
# Windows Credential Manager Functions (PRIMARY)
# ============================================================================

function Get-TokenFromCredentialManager {
    try {
        $cred = cmdkey /list:$CredentialTarget 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }

        # Try using CredentialManager module if available
        if (Get-Module -ListAvailable -Name CredentialManager) {
            Import-Module CredentialManager -ErrorAction SilentlyContinue
            $storedCred = Get-StoredCredential -Target $CredentialTarget -ErrorAction SilentlyContinue
            if ($storedCred) {
                return $storedCred.GetNetworkCredential().Password
            }
        }

        # Fallback: Use cmdkey (less reliable but always available)
        Write-Host "Note: Install CredentialManager module for full support: Install-Module CredentialManager" -ForegroundColor Yellow
        return $null
    }
    catch {
        return $null
    }
}

function Set-TokenInCredentialManager {
    param([string]$Token)

    try {
        if (Get-Module -ListAvailable -Name CredentialManager) {
            Import-Module CredentialManager -ErrorAction SilentlyContinue
            $secureToken = ConvertTo-SecureString $Token -AsPlainText -Force
            $cred = New-Object System.Management.Automation.PSCredential("API_TOKEN", $secureToken)
            New-StoredCredential -Target $CredentialTarget -Credentials $cred -Type Generic -Persist LocalMachine | Out-Null
            return $true
        }
        else {
            Write-Host "CredentialManager module required. Install with: Install-Module CredentialManager" -ForegroundColor Red
            return $false
        }
    }
    catch {
        Write-Host "Failed to store in Credential Manager: $_" -ForegroundColor Red
        return $false
    }
}

function Remove-TokenFromCredentialManager {
    try {
        cmdkey /delete:$CredentialTarget 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

# ============================================================================
# File-based DPAPI Functions (FALLBACK)
# ============================================================================

function Get-TokenFromFile {
    if (-not (Test-Path $StoragePath)) {
        return $null
    }

    try {
        $rawData = [System.IO.File]::ReadAllBytes($StoragePath)
        if ($rawData.Length -le $EntropyBytes) {
            Write-Host "Storage file is corrupt (too small)" -ForegroundColor Red
            return $null
        }

        $entropy = $rawData[0..($EntropyBytes - 1)]
        $encrypted = $rawData[$EntropyBytes..($rawData.Length - 1)]

        $decrypted = [System.Security.Cryptography.ProtectedData]::Unprotect(
            $encrypted,
            $entropy,
            [System.Security.Cryptography.DataProtectionScope]::CurrentUser
        )

        return [System.Text.Encoding]::UTF8.GetString($decrypted)
    }
    catch {
        Write-Host "Failed to decrypt file-based token: $_" -ForegroundColor Red
        return $null
    }
}

# ============================================================================
# Unified Token Access (tries both methods)
# ============================================================================

function Get-StoredToken {
    # Try Credential Manager first (primary)
    $token = Get-TokenFromCredentialManager
    if ($token) {
        return $token
    }

    # Fall back to file-based DPAPI
    return Get-TokenFromFile
}

# ============================================================================
# MAIN ACTIONS
# ============================================================================

switch ($Action) {
    "check" {
        Write-Host "Checking stored API token..." -ForegroundColor Cyan
        Write-Host ""

        # Check Credential Manager
        $credToken = Get-TokenFromCredentialManager
        if ($credToken) {
            Write-Host "[OK] Windows Credential Manager" -ForegroundColor Green
            $masked = $credToken.Substring(0, 4) + ("*" * ($credToken.Length - 8)) + $credToken.Substring($credToken.Length - 4)
            Write-Host "    Token: $masked" -ForegroundColor Gray
            Write-Host "    Location: $CredentialTarget" -ForegroundColor Gray
        } else {
            Write-Host "[--] Windows Credential Manager: No token" -ForegroundColor Yellow
        }

        Write-Host ""

        # Check file-based storage
        if (Test-Path $StoragePath) {
            $fileSize = (Get-Item $StoragePath).Length
            $fileToken = Get-TokenFromFile
            if ($fileToken) {
                Write-Host "[OK] File-based DPAPI (legacy)" -ForegroundColor Green
                $masked = $fileToken.Substring(0, 4) + ("*" * ($fileToken.Length - 8)) + $fileToken.Substring($fileToken.Length - 4)
                Write-Host "    Token: $masked" -ForegroundColor Gray
                Write-Host "    Location: $StoragePath" -ForegroundColor Gray
                Write-Host "    Size: $fileSize bytes" -ForegroundColor Gray
            } else {
                Write-Host "[!!] File-based DPAPI: Corrupt or invalid" -ForegroundColor Red
            }
        } else {
            Write-Host "[--] File-based DPAPI: No file" -ForegroundColor Yellow
        }

        Write-Host ""

        # Check environment variable
        if ($env:COURTLISTENER_API_TOKEN) {
            Write-Host "[OK] Environment Variable: COURTLISTENER_API_TOKEN set" -ForegroundColor Green
        } else {
            Write-Host "[--] Environment Variable: Not set" -ForegroundColor Yellow
        }
    }

    "test" {
        Write-Host "Testing API token against CourtListener..." -ForegroundColor Cyan
        $token = Get-StoredToken
        if (-not $token) {
            $token = $env:COURTLISTENER_API_TOKEN
        }
        if (-not $token) {
            Write-Host "No token available (stored or env var)" -ForegroundColor Red
            exit 1
        }

        try {
            $headers = @{
                "Authorization" = "Token $token"
                "User-Agent" = "CourtListener-MCP/1.0"
            }
            $response = Invoke-RestMethod -Uri "https://www.courtlistener.com/api/rest/v4/" -Headers $headers -Method Get
            Write-Host "[OK] API connection successful" -ForegroundColor Green
            Write-Host "     Available endpoints: $($response.PSObject.Properties.Count)" -ForegroundColor Gray
        }
        catch {
            Write-Host "[!!] API test failed: $_" -ForegroundColor Red
            exit 1
        }
    }

    "migrate" {
        Write-Host "Migrating token from file-based DPAPI to Credential Manager..." -ForegroundColor Cyan

        # Check if already in Credential Manager
        if (Get-TokenFromCredentialManager) {
            Write-Host "Token already exists in Credential Manager" -ForegroundColor Yellow
            exit 0
        }

        # Get token from file
        $token = Get-TokenFromFile
        if (-not $token) {
            Write-Host "No token found in file-based storage to migrate" -ForegroundColor Red
            exit 1
        }

        # Store in Credential Manager
        if (Set-TokenInCredentialManager -Token $token) {
            Write-Host "[OK] Token migrated to Credential Manager" -ForegroundColor Green
            Write-Host "     File-based token retained as backup" -ForegroundColor Gray
        } else {
            Write-Host "[!!] Migration failed" -ForegroundColor Red
            exit 1
        }
    }

    "delete" {
        Write-Host "Deleting stored API token from all locations..." -ForegroundColor Cyan
        $deletedAny = $false

        # Delete from Credential Manager
        if (Remove-TokenFromCredentialManager) {
            Write-Host "[OK] Deleted from Windows Credential Manager" -ForegroundColor Green
            $deletedAny = $true
        }

        # Delete from file-based storage
        if (Test-Path $StoragePath) {
            Remove-Item $StoragePath -Force
            Write-Host "[OK] Deleted from file-based DPAPI storage" -ForegroundColor Green
            $deletedAny = $true
        }

        if ($deletedAny) {
            Write-Host "All stored tokens deleted" -ForegroundColor Green
        } else {
            Write-Host "No stored tokens found" -ForegroundColor Yellow
        }
    }
}
