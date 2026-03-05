<#
.SYNOPSIS
Unified API Key Validation Module for MCP Suite (PowerShell)

.DESCRIPTION
Provides validation functions for all API keys used across the MCP suite:
  CourtListener Citations MCP, Pinecone RAG MCP, Pinecone diff-RAG MCP,
  and future MCP endpoints sharing the same DPAPI key store.

Validators:
  Test-CourtListenerToken       - 40-char hex token (required for CL MCP)
  Test-PineconeApiKey           - pcsk_ prefix, 75 chars
  Test-OpenAiApiKey             - any OpenAI-compatible provider (lenient, optional)
  Test-RealOpenAiApiKey         - real OpenAI only (sk-proj- / sk-, strict)
  Test-CohereApiKey             - 40 alphanumeric chars
  Test-MistralApiKey            - 32 alphanumeric chars (optional)

Shared utilities:
  Test-PlaceholderPattern       - detect placeholder strings
  Test-PathSecurity             - validate directory paths
  New-SecureSecret              - generate cryptographic random secret
  Read-ApiKeySecure             - masked key input
  Hide-ApiKey                   - mask key for display
  Read-CourtListenerTokenWithValidation
  Read-OpenAiApiKeyWithValidation  (lenient, any provider, optional)
  Read-MistralApiKeyWithValidation
  Show-ApiKeyRequirements

.NOTES
Version: 2.0.0
Projects: CourtListener MCP, Pinecone RAG MCP, Pinecone diff-RAG MCP
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

function Test-PineconeApiKey {
    <#
    .SYNOPSIS
    Validates Pinecone API key format.

    .DESCRIPTION
    Pinecone API Key Format:
      - Prefix: pcsk_
      - Length: 75 characters total
      - Characters: Letters (a-z, A-Z), numbers (0-9), and underscores (_)
    #>
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ApiKey,

        [Parameter(Mandatory=$false)]
        [switch]$Silent
    )

    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        if (-not $Silent) { Write-Host "[ERROR] Pinecone API key is empty" -ForegroundColor Red }
        return $false
    }

    if (-not $ApiKey.StartsWith("pcsk_")) {
        if (-not $Silent) {
            Write-Host "[ERROR] Pinecone API key must start with 'pcsk_'" -ForegroundColor Red
            Write-Host "        Expected format: pcsk_XXXX... (75 chars total)" -ForegroundColor Yellow
        }
        return $false
    }

    if ($ApiKey.Length -ne 75) {
        if (-not $Silent) {
            Write-Host "[ERROR] Pinecone API key must be exactly 75 characters (got $($ApiKey.Length))" -ForegroundColor Red
            Write-Host "        Expected format: pcsk_ + 70 alphanumeric/underscore chars" -ForegroundColor Yellow
        }
        return $false
    }

    if ($ApiKey -notmatch '^pcsk_[a-zA-Z0-9_]{70}$') {
        if (-not $Silent) {
            Write-Host "[ERROR] Pinecone API key contains invalid characters" -ForegroundColor Red
            Write-Host "        Must be: pcsk_ followed by letters, numbers, and underscores" -ForegroundColor Yellow
        }
        return $false
    }

    if (Test-PlaceholderPattern -Value $ApiKey -KeyType "Pinecone" -Silent:$Silent) { return $false }

    if (-not $Silent) { Write-Host "[OK] Pinecone API key format validated (75 chars, pcsk_...)" -ForegroundColor Green }
    return $true
}

function Test-OpenAiApiKey {
    <#
    .SYNOPSIS
    Validates a chat endpoint API key (any OpenAI-compatible provider, lenient).

    .DESCRIPTION
    Accepts any non-placeholder key of at least 4 characters, or empty (optional).
    Use this for ~/.openai_compatible_api_key - the chat/analysis endpoint key.
    Covers all supported providers:
      - Real OpenAI    : sk-proj-XXXX... or sk-XXXX...
      - Inception Labs : sk_XXXX...       (underscore, not hyphen)
      - OpenRouter     : sk-or-XXXX...
      - Ollama         : "ollama"         (literal string)
      - Other local    : any non-empty, non-placeholder string

    For validating ~/.openai_api_key or ~/.embedding_api_key (real OpenAI
    only), use Test-RealOpenAiApiKey instead.

    Empty value is accepted (key is optional); returns $true with info message.
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
        if (-not $Silent) { Write-Host "[INFO] OpenAI-compatible API key is optional - skipping validation" -ForegroundColor Cyan }
        return $true
    }

    if ($ApiKey.Length -lt 4) {
        if (-not $Silent) {
            Write-Host "[ERROR] API key is too short (got $($ApiKey.Length) chars, minimum 4)" -ForegroundColor Red
        }
        return $false
    }

    if (Test-PlaceholderPattern -Value $ApiKey -KeyType "chat API" -Silent:$Silent) { return $false }

    if (-not $Silent) {
        $provider = if ($ApiKey.StartsWith("sk-proj-"))   { "OpenAI (new format)" } `
                    elseif ($ApiKey.StartsWith("sk-or-")) { "OpenRouter" } `
                    elseif ($ApiKey.StartsWith("sk-"))    { "OpenAI (legacy)" } `
                    elseif ($ApiKey.StartsWith("sk_"))    { "Inception Labs" } `
                    elseif ($ApiKey -eq "ollama")         { "Ollama" } `
                    else                                  { "custom/local endpoint" }
        Write-Host "[OK] API key accepted ($provider format)" -ForegroundColor Green
    }
    return $true
}

function Test-RealOpenAiApiKey {
    <#
    .SYNOPSIS
    Validates a REAL OpenAI API key (sk-proj-... or sk-..., strict).

    .DESCRIPTION
    Strictly validates keys issued by api.openai.com only.
    Rejects Inception Labs (sk_), OpenRouter (sk-or-), and non-OpenAI strings.

    Use this to validate keys stored in:
      ~/.openai_api_key     - shared real-OpenAI key (CourtListener, Pinecone, etc.)
      ~/.embedding_api_key  - when using OpenAI for embeddings

    Empty value is accepted (key is optional); returns $true with info message.
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
        if (-not $Silent) { Write-Host "[INFO] OpenAI API key is optional - skipping validation" -ForegroundColor Cyan }
        return $true
    }

    # Must start with sk-proj- (new format) or sk- (legacy) but NOT sk_ (Inception) or sk-or- (OpenRouter)
    if (-not ($ApiKey.StartsWith("sk-proj-") -or ($ApiKey.StartsWith("sk-") -and -not $ApiKey.StartsWith("sk-or-")))) {
        if (-not $Silent) {
            Write-Host "[ERROR] This must be a real OpenAI key (starts with 'sk-proj-' or 'sk-')" -ForegroundColor Red
            Write-Host "        Inception Labs keys start with 'sk_' (underscore). Use Test-OpenAiApiKey for any-provider validation." -ForegroundColor Yellow
            Write-Host "        OpenRouter keys start with 'sk-or-'. Not valid for real OpenAI key storage." -ForegroundColor Yellow
            Write-Host "        Get your key at: platform.openai.com/api-keys" -ForegroundColor Gray
        }
        return $false
    }

    if ($ApiKey.Length -lt 20) {
        if (-not $Silent) {
            Write-Host "[ERROR] OpenAI API key too short (got $($ApiKey.Length) chars)" -ForegroundColor Red
        }
        return $false
    }

    if (Test-PlaceholderPattern -Value $ApiKey -KeyType "OpenAI" -Silent:$Silent) { return $false }

    if (-not $Silent) {
        $fmt = if ($ApiKey.StartsWith("sk-proj-")) { "sk-proj-... (new format)" } else { "sk-... (legacy format)" }
        Write-Host "[OK] OpenAI API key accepted ($fmt)" -ForegroundColor Green
    }
    return $true
}

function Test-CohereApiKey {
    <#
    .SYNOPSIS
    Validates Cohere API key format.

    .DESCRIPTION
    Cohere API Key Format:
      - Length: 40 characters
      - Characters: Letters (a-z, A-Z) and numbers (0-9)
    #>
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ApiKey,

        [Parameter(Mandatory=$false)]
        [switch]$Silent
    )

    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        if (-not $Silent) { Write-Host "[ERROR] Cohere API key is empty" -ForegroundColor Red }
        return $false
    }

    if ($ApiKey.Length -ne 40) {
        if (-not $Silent) {
            Write-Host "[ERROR] Cohere API key must be exactly 40 characters (got $($ApiKey.Length))" -ForegroundColor Red
            Write-Host "        Expected format: 40 alphanumeric characters (a-z, A-Z, 0-9)" -ForegroundColor Yellow
        }
        return $false
    }

    if ($ApiKey -notmatch '^[a-zA-Z0-9]{40}$') {
        if (-not $Silent) {
            Write-Host "[ERROR] Cohere API key must contain only letters and numbers" -ForegroundColor Red
        }
        return $false
    }

    if (Test-PlaceholderPattern -Value $ApiKey -KeyType "Cohere" -Silent:$Silent) { return $false }

    if (-not $Silent) { Write-Host "[OK] Cohere API key format validated (40 chars, alphanumeric)" -ForegroundColor Green }
    return $true
}

function Test-MistralApiKey {
    <#
    .SYNOPSIS
    Validates Mistral API key format (optional key).

    .DESCRIPTION
    Mistral API Key Format:
      - Length: Exactly 32 characters
      - Characters: Letters (a-z, A-Z) and numbers (0-9)
      - Empty string is valid (Mistral is optional)

    Note: This validates keys stored in ~/.pinecone_mistral_api_key.
    The ~/.mistral_api_key file belongs to USPTO MCPs; do not use it here.
    #>
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory=$false)]
        [string]$ApiKey,

        [Parameter(Mandatory=$false)]
        [switch]$Silent
    )

    # Empty is OK (Mistral is optional)
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

    if (Test-PlaceholderPattern -Value $ApiKey -KeyType "Mistral" -Silent:$Silent) { return $false }

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
# Shared: Masked Input and Display
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
    Prompts for an OpenAI-compatible API key with validation retry loop (optional).

    .DESCRIPTION
    Accepts any supported provider key or press Enter to skip.
    Suitable for ~/.openai_compatible_api_key (any provider).
    For real OpenAI keys only (~/openai_api_key, ~/.embedding_api_key), prompt
    inline using Test-RealOpenAiApiKey.

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

    Write-Host "[INFO] API key is OPTIONAL - press Enter to skip" -ForegroundColor Cyan
    Write-Host "[INFO] Supported providers:" -ForegroundColor Cyan
    Write-Host "         Real OpenAI    : sk-proj-... or sk-..." -ForegroundColor Gray
    Write-Host "         Inception Labs : sk_..." -ForegroundColor Gray
    Write-Host "         OpenRouter     : sk-or-..." -ForegroundColor Gray
    Write-Host "         Ollama (local) : ollama" -ForegroundColor Gray
    Write-Host ""

    $attempt = 0

    while ($attempt -lt $MaxAttempts) {
        $attempt++
        $key = Read-ApiKeySecure -Prompt "Enter your API key (or press Enter to skip)"

        if ([string]::IsNullOrWhiteSpace($key)) {
            Write-Host "[INFO] Skipping API key" -ForegroundColor Yellow
            return ""
        }

        $key = $key.Trim()

        if (Test-OpenAiApiKey -ApiKey $key) {
            return $key
        }
        else {
            if ($attempt -lt $MaxAttempts) {
                Write-Host "[WARN] Attempt $attempt of $MaxAttempts - please try again" -ForegroundColor Yellow
            }
        }
    }

    Write-Host "[ERROR] Failed to provide valid API key after $MaxAttempts attempts" -ForegroundColor Red
    return $null
}

function Read-MistralApiKeyWithValidation {
    <#
    .SYNOPSIS
    Prompts for a Mistral API key with validation retry loop (optional).

    .DESCRIPTION
    Press Enter to skip - Mistral is optional.
    Validates keys stored in ~/.pinecone_mistral_api_key.

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
    Displays API key format requirements for the MCP suite.
    #>
    [CmdletBinding()]
    param()

    Write-Host ""
    Write-Host "API Key Requirements - MCP Suite" -ForegroundColor Cyan
    Write-Host "==================================" -ForegroundColor Cyan
    Write-Host ""

    Write-Host "CourtListener API Token  (~/.courtlistener_api_token):" -ForegroundColor White
    Write-Host "  Required:   YES (for CourtListener MCP)" -ForegroundColor Green
    Write-Host "  Length:     Exactly 40 characters"
    Write-Host "  Format:     Lowercase hex only (a-f, 0-9)"
    Write-Host "  Example:    a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
    Write-Host "  Storage:    Windows Credential Manager (primary) + DPAPI file (backup)"
    Write-Host ""

    Write-Host "Pinecone API Key  (~/.pinecone_api_key):" -ForegroundColor White
    Write-Host "  Required:   For Pinecone MCPs" -ForegroundColor Yellow
    Write-Host "  Length:     Exactly 75 characters"
    Write-Host "  Format:     pcsk_ + 70 alphanumeric/underscore chars"
    Write-Host "  Example:    pcsk_AbCdEfGh..."
    Write-Host "  Storage:    Windows Credential Manager + DPAPI file"
    Write-Host ""

    Write-Host "Real OpenAI API Key  (~/.openai_api_key, shared across MCPs):" -ForegroundColor White
    Write-Host "  Required:   NO (optional, for chat/completion with real OpenAI)" -ForegroundColor Yellow
    Write-Host "  Format:     sk-proj-... (new) or sk-... (legacy), OpenAI only"
    Write-Host "  Rejects:    Inception (sk_) and OpenRouter (sk-or-); use compatible key for those"
    Write-Host "  Storage:    DPAPI encrypted file"
    Write-Host ""

    Write-Host "Chat API Key  (~/.openai_compatible_api_key, any provider):" -ForegroundColor White
    Write-Host "  Required:   NO (optional)" -ForegroundColor Yellow
    Write-Host "  Providers:  OpenAI sk-proj-/sk-, Inception sk_, OpenRouter sk-or-, ollama"
    Write-Host "  Storage:    DPAPI encrypted file"
    Write-Host ""

    Write-Host "Embedding API Key  (~/.embedding_api_key):" -ForegroundColor White
    Write-Host "  Required:   NO (optional, usually real OpenAI)" -ForegroundColor Yellow
    Write-Host "  Format:     sk-proj-... or sk-... (real OpenAI key for embeddings)"
    Write-Host "  Storage:    DPAPI encrypted file"
    Write-Host ""

    Write-Host "Cohere API Key  (~/.cohere_api_key):" -ForegroundColor White
    Write-Host "  Required:   NO (optional, for reranking)" -ForegroundColor Yellow
    Write-Host "  Length:     Exactly 40 characters"
    Write-Host "  Format:     Alphanumeric (a-z, A-Z, 0-9)"
    Write-Host "  Storage:    DPAPI encrypted file"
    Write-Host ""

    Write-Host "Mistral OCR Key  (~/.pinecone_mistral_api_key):" -ForegroundColor White
    Write-Host "  Required:   NO (optional, for OCR on scanned documents)" -ForegroundColor Yellow
    Write-Host "  Length:     Exactly 32 characters"
    Write-Host "  Format:     Alphanumeric (a-z, A-Z, 0-9)"
    Write-Host "  Note:       ~/.mistral_api_key belongs to USPTO MCPs; do NOT use it here"
    Write-Host "  Storage:    DPAPI encrypted file"
    Write-Host ""

    Write-Host "Entropy Seed  (~/.uspto_internal_auth_secret):" -ForegroundColor White
    Write-Host "  Purpose:    Shared DPAPI entropy for all MCP suite key files"
    Write-Host "  Size:       32+ bytes (only first 32 used as entropy)"
    Write-Host "  Created:    Automatically on first key operation"
    Write-Host "  WARNING:    Deleting this makes all DPAPI key files unreadable" -ForegroundColor Red
    Write-Host ""
}

# ============================================
# Module Exports
# ============================================

Export-ModuleMember -Function @(
    'Test-CourtListenerToken',
    'Test-PineconeApiKey',
    'Test-OpenAiApiKey',
    'Test-RealOpenAiApiKey',
    'Test-CohereApiKey',
    'Test-MistralApiKey',
    'Test-PlaceholderPattern',
    'Test-PathSecurity',
    'New-SecureSecret',
    'Read-ApiKeySecure',
    'Hide-ApiKey',
    'Read-CourtListenerTokenWithValidation',
    'Read-OpenAiApiKeyWithValidation',
    'Read-MistralApiKeyWithValidation',
    'Show-ApiKeyRequirements'
)
