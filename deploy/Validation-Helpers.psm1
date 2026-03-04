<#
.SYNOPSIS
API Key and Input Validation Module for CourtListener Citation MCP (PowerShell)

.DESCRIPTION
Provides validation functions for:
  - CourtListener API token  (40-char hex string, required)
  - OpenAI API key           (sk- prefix, variable length, optional)
  - Mistral API key          (32-char alphanumeric, optional)

Also provides shared utilities: placeholder detection, path security,
secure secret generation, masked input, and display masking.

Security: Prevents deployment with invalid or placeholder keys.

.NOTES
Version: 1.0.0
Project: CourtListener Citation Validation MCP

.EXAMPLE
Import-Module .\Validation-Helpers.psm1
Test-CourtListenerToken -Token $myToken
#>

# ============================================
# API Key Format Validation
# ============================================

function Test-CourtListenerToken {
    <#
    .SYNOPSIS
    Validates a CourtListener API token format.

    .DESCRIPTION
    CourtListener API Token Format:
      - Length: Exactly 40 characters
      - Characters: Lowercase hex only (a-f, 0-9)
      - Example: a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2

    .PARAMETER Token
    The token to validate.

    .PARAMETER Silent
    If specified, suppress output and return only boolean.

    .OUTPUTS
    Boolean - $true if valid, $false if invalid.
    #>
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Token,

        [Parameter(Mandatory=$false)]
        [switch]$Silent
    )

    if ([string]::IsNullOrWhiteSpace($Token)) {
        if (-not $Silent) { Write-Host "[ERROR] CourtListener API token is empty" -ForegroundColor Red }
        return $false
    }

    if ($Token.Length -ne 40) {
        if (-not $Silent) {
            Write-Host "[ERROR] CourtListener API token must be exactly 40 characters (got $($Token.Length))" -ForegroundColor Red
            Write-Host "        Expected format: 40 lowercase hex characters (a-f, 0-9)" -ForegroundColor Yellow
        }
        return $false
    }

    if ($Token -notmatch '^[a-f0-9]{40}$') {
        if (-not $Silent) {
            Write-Host "[ERROR] CourtListener API token must contain only lowercase hex characters (a-f, 0-9)" -ForegroundColor Red
            Write-Host "        Invalid characters detected in token" -ForegroundColor Yellow
        }
        return $false
    }

    if (Test-PlaceholderPattern -Value $Token -KeyType "CourtListener" -Silent:$Silent) {
        return $false
    }

    if (-not $Silent) {
        Write-Host "[OK] CourtListener API token format validated (40 hex chars)" -ForegroundColor Green
    }
    return $true
}

function Test-OpenAiApiKey {
    <#
    .SYNOPSIS
    Validates an OpenAI API key format (optional key).

    .DESCRIPTION
    OpenAI API Key Format:
      - Prefix: Starts with "sk-" (classic) or "sk-proj-" (project keys)
      - Length: Minimum 20 characters
      - Characters: Alphanumeric, hyphens, underscores

    Ollama local endpoint: The value "ollama" (or "ollama:<model>") is also
    accepted, since Ollama's OpenAI-compatible endpoint ignores the key value.

    Empty value is accepted (OpenAI/Ollama is optional for this MCP).

    .PARAMETER ApiKey
    The API key to validate. May be empty (optional).

    .PARAMETER Silent
    If specified, suppress output and return only boolean.

    .OUTPUTS
    Boolean - $true if valid or empty, $false if provided but invalid.
    #>
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory=$false)]
        [string]$ApiKey,

        [Parameter(Mandatory=$false)]
        [switch]$Silent
    )

    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        if (-not $Silent) { Write-Host "[INFO] OpenAI/Ollama API key is optional - skipping validation" -ForegroundColor Cyan }
        return $true
    }

    # Accept Ollama local endpoint key values - Ollama ignores the key entirely
    # Matches: "ollama", "ollama:modelname", "OLLAMA", etc.
    if ($ApiKey -match '^ollama(:[a-zA-Z0-9._/-]+)?$') {
        if (-not $Silent) {
            Write-Host "[OK] Ollama local endpoint key accepted ('$ApiKey')" -ForegroundColor Green
            Write-Host "     Note: Ollama ignores API key values on its OpenAI-compatible endpoint" -ForegroundColor Gray
        }
        return $true
    }

    if ($ApiKey.Length -lt 20) {
        if (-not $Silent) {
            Write-Host "[ERROR] OpenAI API key is too short ($($ApiKey.Length) chars, minimum 20)" -ForegroundColor Red
            Write-Host "        Expected format: sk-... or sk-proj-... (alphanumeric, hyphens, underscores)" -ForegroundColor Yellow
            Write-Host "        For local Ollama use, enter: ollama" -ForegroundColor Yellow
        }
        return $false
    }

    if ($ApiKey -notmatch '^sk-[a-zA-Z0-9_-]+$') {
        if (-not $Silent) {
            Write-Host "[ERROR] OpenAI API key must start with 'sk-' and contain only letters, numbers, hyphens, underscores" -ForegroundColor Red
            Write-Host "        Invalid format detected" -ForegroundColor Yellow
            Write-Host "        For local Ollama use, enter: ollama" -ForegroundColor Yellow
        }
        return $false
    }

    if (Test-PlaceholderPattern -Value $ApiKey -KeyType "OpenAI" -Silent:$Silent) {
        return $false
    }

    if (-not $Silent) {
        Write-Host "[OK] OpenAI API key format validated (sk- prefix, $($ApiKey.Length) chars)" -ForegroundColor Green
    }
    return $true
}

function Test-MistralApiKey {
    <#
    .SYNOPSIS
    Validates a Mistral API key format (optional key).

    .DESCRIPTION
    Mistral API Key Format:
      - Length: Exactly 32 characters
      - Characters: Alphanumeric (a-z, A-Z, 0-9)
      - Example: AbCdEfGh1234567890IjKlMnOp1234

    Empty value is accepted (Mistral is optional for this MCP).

    .PARAMETER ApiKey
    The API key to validate. May be empty (optional).

    .PARAMETER Silent
    If specified, suppress output and return only boolean.

    .OUTPUTS
    Boolean - $true if valid or empty, $false if provided but invalid.
    #>
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory=$false)]
        [string]$ApiKey,

        [Parameter(Mandatory=$false)]
        [switch]$Silent
    )

    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        if (-not $Silent) { Write-Host "[INFO] Mistral API key is optional - skipping validation" -ForegroundColor Cyan }
        return $true
    }

    if ($ApiKey.Length -ne 32) {
        if (-not $Silent) {
            Write-Host "[ERROR] Mistral API key must be exactly 32 characters (got $($ApiKey.Length))" -ForegroundColor Red
            Write-Host "        Expected format: 32 alphanumeric characters (a-z, A-Z, 0-9)" -ForegroundColor Yellow
        }
        return $false
    }

    if ($ApiKey -notmatch '^[a-zA-Z0-9]{32}$') {
        if (-not $Silent) {
            Write-Host "[ERROR] Mistral API key must contain only letters (a-z, A-Z) and numbers (0-9)" -ForegroundColor Red
            Write-Host "        Invalid characters detected" -ForegroundColor Yellow
        }
        return $false
    }

    if (Test-PlaceholderPattern -Value $ApiKey -KeyType "Mistral" -Silent:$Silent) {
        return $false
    }

    if (-not $Silent) {
        Write-Host "[OK] Mistral API key format validated (32 chars, alphanumeric)" -ForegroundColor Green
    }
    return $true
}

# ============================================
# Shared: Placeholder Pattern Detection
# ============================================

function Test-PlaceholderPattern {
    <#
    .SYNOPSIS
    Detects common placeholder strings in API key values.

    .PARAMETER Value
    The value to check.

    .PARAMETER KeyType
    Key type name used in error messages.

    .PARAMETER Silent
    If specified, suppress output and return only boolean.

    .OUTPUTS
    Boolean - $true if placeholder detected (invalid), $false if clean.
    #>
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory=$true)]  [string]$Value,
        [Parameter(Mandatory=$true)]  [string]$KeyType,
        [Parameter(Mandatory=$false)] [switch]$Silent
    )

    $placeholderPatterns = @(
        'your.*key', 'your.*api', 'your.*token',
        'api.*key.*here', 'token.*here',
        'placeholder', 'insert.*key', 'insert.*api',
        'replace.*me', 'replace.*key', 'changeme', 'change.*me',
        'put.*key.*here', 'add.*key.*here',
        'enter.*key', 'paste.*key', 'fill.*in'
    )

    foreach ($pattern in $placeholderPatterns) {
        if ($Value -match $pattern) {
            if (-not $Silent) {
                Write-Host "[ERROR] Detected placeholder pattern in $KeyType key: '$pattern'" -ForegroundColor Red
                Write-Host "        Please use your actual key, not a placeholder" -ForegroundColor Yellow
            }
            return $true  # Placeholder found - caller should treat as invalid
        }
    }

    return $false  # Clean
}

# ============================================
# Shared: Path Security
# ============================================

function Test-PathSecurity {
    <#
    .SYNOPSIS
    Validates a directory path for security risks.

    .DESCRIPTION
    Checks for path traversal (..), warns on relative paths, and
    warns when targeting sensitive system directories.

    .PARAMETER Path
    The path to validate.

    .PARAMETER PathName
    Friendly name for the path (used in messages).

    .PARAMETER Silent
    If specified, suppress output and return only boolean.

    .OUTPUTS
    Boolean - $true if safe, $false if rejected.
    #>
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory=$true)]  [string]$Path,
        [Parameter(Mandatory=$true)]  [string]$PathName,
        [Parameter(Mandatory=$false)] [switch]$Silent
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        if (-not $Silent) { Write-Host "[ERROR] $PathName cannot be empty" -ForegroundColor Red }
        return $false
    }

    if ($Path -match '\.\.') {
        if (-not $Silent) {
            Write-Host "[ERROR] $PathName contains path traversal (..): $Path" -ForegroundColor Red
            Write-Host "        Path traversal is a security risk - rejected" -ForegroundColor Red
        }
        return $false
    }

    if (-not ($Path -match '^[A-Za-z]:\\' -or $Path -match '^\\\\')) {
        if (-not $Silent) {
            Write-Host "[WARN] $PathName should be an absolute path" -ForegroundColor Yellow
            Write-Host "       Got: $Path" -ForegroundColor Yellow
            $confirm = Read-Host "Continue anyway? (y/N)"
            if ($confirm -ne 'y' -and $confirm -ne 'Y') {
                Write-Host "[INFO] Path validation rejected by user" -ForegroundColor Yellow
                return $false
            }
        }
    }

    $systemDirs = @('C:\Windows', 'C:\Program Files', 'C:\Program Files (x86)', 'C:\ProgramData')
    foreach ($sysDir in $systemDirs) {
        if ($Path -like "$sysDir*") {
            if (-not $Silent) {
                Write-Host "[WARN] $PathName targets system directory: $Path" -ForegroundColor Yellow
                Write-Host "       This may require administrator privileges" -ForegroundColor Yellow
            }
            break
        }
    }

    if (-not $Silent) { Write-Host "[OK] $PathName validated: $Path" -ForegroundColor Green }
    return $true
}

# ============================================
# Shared: Secure Secret Generation
# ============================================

function New-SecureSecret {
    <#
    .SYNOPSIS
    Generates a cryptographically secure random secret (base64-encoded).

    .PARAMETER Length
    Number of random bytes (default 32, yields a 44-char base64 string).

    .OUTPUTS
    String - Base64-encoded secure random secret.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory=$false)]
        [int]$Length = 32
    )

    try {
        $bytes = New-Object byte[] $Length
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($bytes)
        $rng.Dispose()
        return [System.Convert]::ToBase64String($bytes)
    }
    catch {
        Write-Host "[ERROR] Failed to generate secure secret: $_" -ForegroundColor Red
        return $null
    }
}

# ============================================
# Shared: Masked Input
# ============================================

function Read-ApiKeySecure {
    <#
    .SYNOPSIS
    Prompts the user for an API key with hidden input (no echo).

    .PARAMETER Prompt
    The prompt text to display.

    .OUTPUTS
    String - The entered key in plaintext.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Prompt
    )

    $secureString = Read-Host -Prompt $Prompt -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureString)
    $key = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    return $key
}

# ============================================
# Validated Prompt Loops
# ============================================

function Read-CourtListenerTokenWithValidation {
    <#
    .SYNOPSIS
    Prompts for a CourtListener API token with validation retry loop.

    .PARAMETER MaxAttempts
    Maximum number of attempts before giving up (default 3).

    .OUTPUTS
    String - Valid token, or $null if all attempts failed.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory=$false)]
        [int]$MaxAttempts = 3
    )

    $attempt = 0

    while ($attempt -lt $MaxAttempts) {
        $attempt++
        $token = Read-ApiKeySecure -Prompt "Enter your CourtListener API token"

        if ([string]::IsNullOrWhiteSpace($token)) {
            Write-Host "[ERROR] CourtListener API token cannot be empty" -ForegroundColor Red
            if ($attempt -lt $MaxAttempts) { Write-Host "[INFO] Attempt $attempt of $MaxAttempts" -ForegroundColor Yellow }
            continue
        }

        $token = $token.Trim()

        if (Test-CourtListenerToken -Token $token) {
            return $token
        }
        else {
            if ($attempt -lt $MaxAttempts) {
                Write-Host "[WARN] Attempt $attempt of $MaxAttempts - please try again" -ForegroundColor Yellow
                Write-Host "[INFO] Format: 40 lowercase hex characters (a-f, 0-9)" -ForegroundColor Cyan
            }
        }
    }

    Write-Host "[ERROR] Failed to provide valid CourtListener token after $MaxAttempts attempts" -ForegroundColor Red
    return $null
}

function Read-OpenAiApiKeyWithValidation {
    <#
    .SYNOPSIS
    Prompts for an OpenAI API key with validation retry loop (optional key).

    .DESCRIPTION
    Press Enter to skip - OpenAI is optional for this MCP.

    .PARAMETER MaxAttempts
    Maximum number of attempts before giving up (default 3).

    .OUTPUTS
    String - Valid key, empty string if skipped, or $null if all attempts failed.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory=$false)]
        [int]$MaxAttempts = 3
    )

    Write-Host "[INFO] OpenAI/Ollama API key is OPTIONAL (for OCR / Chat endpoint use)" -ForegroundColor Cyan
    Write-Host "[INFO] Press Enter to skip, enter your OpenAI key (sk-...), or enter 'ollama' for a local Ollama endpoint" -ForegroundColor Cyan
    Write-Host ""

    $attempt = 0

    while ($attempt -lt $MaxAttempts) {
        $attempt++
        $key = Read-ApiKeySecure -Prompt "Enter your OpenAI API key (or press Enter to skip)"

        if ([string]::IsNullOrWhiteSpace($key)) {
            Write-Host "[INFO] Skipping OpenAI API key" -ForegroundColor Yellow
            return ""
        }

        $key = $key.Trim()

        if (Test-OpenAiApiKey -ApiKey $key) {
            return $key
        }
        else {
            if ($attempt -lt $MaxAttempts) {
                Write-Host "[WARN] Attempt $attempt of $MaxAttempts - please try again" -ForegroundColor Yellow
                Write-Host "[INFO] Format: starts with 'sk-' (OpenAI) or enter 'ollama' for local Ollama endpoint" -ForegroundColor Cyan
            }
        }
    }

    Write-Host "[ERROR] Failed to provide valid OpenAI API key after $MaxAttempts attempts" -ForegroundColor Red
    return $null
}

function Read-MistralApiKeyWithValidation {
    <#
    .SYNOPSIS
    Prompts for a Mistral API key with validation retry loop (optional key).

    .DESCRIPTION
    Press Enter to skip - Mistral is optional for this MCP.

    .PARAMETER MaxAttempts
    Maximum number of attempts before giving up (default 3).

    .OUTPUTS
    String - Valid key, empty string if skipped, or $null if all attempts failed.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory=$false)]
        [int]$MaxAttempts = 3
    )

    Write-Host "[INFO] Mistral API key is OPTIONAL (for OCR on scanned documents)" -ForegroundColor Cyan
    Write-Host "[INFO] Press Enter to skip, or enter your 32-character Mistral API key" -ForegroundColor Cyan
    Write-Host ""

    $attempt = 0

    while ($attempt -lt $MaxAttempts) {
        $attempt++
        $key = Read-ApiKeySecure -Prompt "Enter your Mistral API key (or press Enter to skip)"

        if ([string]::IsNullOrWhiteSpace($key)) {
            Write-Host "[INFO] Skipping Mistral API key" -ForegroundColor Yellow
            return ""
        }

        $key = $key.Trim()

        if (Test-MistralApiKey -ApiKey $key) {
            return $key
        }
        else {
            if ($attempt -lt $MaxAttempts) {
                Write-Host "[WARN] Attempt $attempt of $MaxAttempts - please try again" -ForegroundColor Yellow
                Write-Host "[INFO] Format: 32 alphanumeric characters (a-z, A-Z, 0-9)" -ForegroundColor Cyan
            }
        }
    }

    Write-Host "[ERROR] Failed to provide valid Mistral API key after $MaxAttempts attempts" -ForegroundColor Red
    return $null
}

# ============================================
# Display Utilities
# ============================================

function Show-ApiKeyRequirements {
    <#
    .SYNOPSIS
    Displays API key format requirements for this MCP.
    #>
    [CmdletBinding()]
    param()

    Write-Host ""
    Write-Host "API Key Requirements - CourtListener Citation Validation MCP" -ForegroundColor Cyan
    Write-Host "==============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "CourtListener API Token:" -ForegroundColor White
    Write-Host "  - Required: YES" -ForegroundColor Green
    Write-Host "  - Length:   Exactly 40 characters"
    Write-Host "  - Format:   Lowercase hex only (a-f, 0-9)"
    Write-Host "  - Example:  a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
    Write-Host "  - Get from: https://www.courtlistener.com/sign-in/" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "OpenAI / Ollama API Key:" -ForegroundColor White
    Write-Host "  - Required: NO (optional, for OCR / Chat endpoint)" -ForegroundColor Yellow
    Write-Host "  - OpenAI:   Starts with 'sk-', alphanumeric + hyphens/underscores"
    Write-Host "  - Example:  sk-proj-AbCdEfGh..."
    Write-Host "  - Get from: https://platform.openai.com/api-keys" -ForegroundColor Yellow
    Write-Host "  - Ollama:   Enter 'ollama' (or 'ollama:modelname') for a local Ollama endpoint"
    Write-Host "              Ollama's OpenAI-compatible endpoint ignores the key value" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Mistral API Key:" -ForegroundColor White
    Write-Host "  - Required: NO (optional, for OCR on scanned documents)" -ForegroundColor Yellow
    Write-Host "  - Length:   Exactly 32 characters"
    Write-Host "  - Format:   Alphanumeric (a-z, A-Z, 0-9)"
    Write-Host "  - Example:  AbCdEfGh1234567890IjKlMnOp1234"
    Write-Host "  - Get from: https://console.mistral.ai/" -ForegroundColor Yellow
    Write-Host ""
}

function Hide-ApiKey {
    <#
    .SYNOPSIS
    Masks an API key for safe display, showing only the last N characters.

    .PARAMETER ApiKey
    The key to mask.

    .PARAMETER VisibleChars
    Number of characters to show at the end (default 5).

    .OUTPUTS
    String - Masked key, e.g. "***...abcde".
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ApiKey,

        [Parameter(Mandatory=$false)]
        [int]$VisibleChars = 5
    )

    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        return "[Not set]"
    }
    elseif ($ApiKey.Length -le $VisibleChars) {
        return "***"
    }
    else {
        $asterisks = '*' * ($ApiKey.Length - $VisibleChars)
        $visible   = $ApiKey.Substring($ApiKey.Length - $VisibleChars)
        return "$asterisks$visible"
    }
}

# ============================================
# Module Exports
# ============================================

Export-ModuleMember -Function @(
    'Test-CourtListenerToken',
    'Test-OpenAiApiKey',
    'Test-MistralApiKey',
    'Test-PlaceholderPattern',
    'Test-PathSecurity',
    'New-SecureSecret',
    'Read-ApiKeySecure',
    'Read-CourtListenerTokenWithValidation',
    'Read-OpenAiApiKeyWithValidation',
    'Read-MistralApiKeyWithValidation',
    'Show-ApiKeyRequirements',
    'Hide-ApiKey'
)
