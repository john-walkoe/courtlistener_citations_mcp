#!/bin/bash
# Validation Helpers for CourtListener Citation Validation MCP
# Provides secure API token format validation and file permission utilities
# Compatible with Linux and macOS deployments

# ============================================
# API Token Format Validation
# ============================================

# Validate CourtListener API token format
# CourtListener tokens: 40 characters, hex string (a-f, 0-9)
validate_courtlistener_token() {
    local token="$1"

    # Check if empty
    if [ -z "$token" ]; then
        echo "ERROR: CourtListener API token cannot be empty"
        return 1
    fi

    # Check length (must be exactly 40 characters)
    if [ ${#token} -ne 40 ]; then
        echo "ERROR: CourtListener API token must be exactly 40 characters"
        echo "       Current length: ${#token}"
        echo "       Expected: 40 hex characters (a-f, 0-9)"
        return 1
    fi

    # Check format: hex only (lowercase a-f and digits 0-9)
    if ! echo "$token" | grep -qE '^[a-f0-9]{40}$'; then
        echo "ERROR: CourtListener API token must contain only hex characters (a-f, 0-9)"
        echo "       Format: 40 lowercase hex characters"
        return 1
    fi

    # Check for obvious placeholder patterns
    if echo "$token" | grep -qiE '(your|api|key|token|placeholder|insert|replace|changeme|put|add|enter|paste|fill)'; then
        echo "ERROR: API token looks like a placeholder - please use your actual token"
        return 1
    fi

    echo "OK: CourtListener API token format validated (40 hex characters)"
    return 0
}

# ============================================
# File/Directory Permission Utilities
# ============================================

# Set secure file permissions (Unix: chmod 600)
# Restricts file to owner read/write only
set_secure_file_permissions() {
    local file_path="$1"

    if [ ! -f "$file_path" ]; then
        echo "ERROR: File not found: $file_path"
        return 1
    fi

    if chmod 600 "$file_path" 2>/dev/null; then
        local actual_perms
        if [ "$(uname)" = "Darwin" ]; then
            actual_perms=$(stat -f %A "$file_path")
        else
            actual_perms=$(stat -c %a "$file_path")
        fi

        if [ "$actual_perms" = "600" ]; then
            echo "OK: Secured file permissions: $file_path (600)"
            return 0
        else
            echo "WARN: Permissions set but verification failed (expected 600, got $actual_perms)"
            echo "      File: $file_path"
            return 1
        fi
    else
        echo "ERROR: Failed to set file permissions: $file_path"
        echo "       Please manually run: chmod 600 $file_path"
        return 1
    fi
}

# Set secure directory permissions (Unix: chmod 700)
# Restricts directory to owner read/write/execute only
set_secure_directory_permissions() {
    local dir_path="$1"

    if [ ! -d "$dir_path" ]; then
        echo "ERROR: Directory not found: $dir_path"
        return 1
    fi

    if chmod 700 "$dir_path" 2>/dev/null; then
        local actual_perms
        if [ "$(uname)" = "Darwin" ]; then
            actual_perms=$(stat -f %A "$dir_path")
        else
            actual_perms=$(stat -c %a "$dir_path")
        fi

        if [ "$actual_perms" = "700" ]; then
            echo "OK: Secured directory permissions: $dir_path (700)"
            return 0
        else
            echo "WARN: Permissions set but verification failed (expected 700, got $actual_perms)"
            echo "      Directory: $dir_path"
            return 1
        fi
    else
        echo "ERROR: Failed to set directory permissions: $dir_path"
        echo "       Please manually run: chmod 700 $dir_path"
        return 1
    fi
}

# ============================================
# Display Helpers
# ============================================

# Mask API token for safe display (shows first 4 and last 4 characters)
mask_api_token() {
    local token="$1"

    if [ -z "$token" ]; then
        echo "Not set"
        return
    fi

    if [ ${#token} -le 8 ]; then
        echo "...[too short]..."
        return
    fi

    local first4="${token:0:4}"
    local last4="${token: -4}"
    echo "${first4}...(${#token} chars)...${last4}"
}

# ============================================
# Secure Input
# ============================================

# Securely read API token from user (hidden input)
read_api_token_secure() {
    local prompt="$1"
    local var_name="$2"
    local api_token=""

    # Read with hidden input (-s flag suppresses echo)
    read -r -s -p "$prompt: " api_token
    echo  # New line after hidden input

    # Return via nameref or eval (eval used for POSIX compatibility)
    eval "$var_name='$api_token'"
}

# ============================================
# Existing Token Detection
# ============================================

# Check if a CourtListener token file exists in the home directory
check_existing_token_file() {
    if [[ -f "$HOME/.courtlistener_api_token" ]]; then
        return 0  # Exists
    else
        return 1  # Does not exist
    fi
}

# Load and validate token from the file-based storage
# Returns the token via stdout if valid, exits with 1 if not
load_existing_token_file() {
    local token_file="$HOME/.courtlistener_api_token"

    if [ ! -f "$token_file" ]; then
        return 1
    fi

    # Read raw bytes, strip newlines
    local token
    token=$(cat "$token_file" 2>/dev/null | tr -d '\n' | tr -d '\r')

    if [ -z "$token" ]; then
        return 1
    fi

    # Validate format (40 hex chars)
    if echo "$token" | grep -qE '^[a-f0-9]{40}$'; then
        echo "$token"
        return 0
    else
        # File exists but content is not a plain-text token
        # (Could be DPAPI-encrypted binary on Windows migration — not loadable on Linux)
        return 1
    fi
}

# Ask user whether to reuse a detected existing token
prompt_use_existing_token() {
    local masked_token="$1"

    echo "" >&2
    echo "INFO: Detected existing CourtListener API token" >&2
    echo "      Token (masked): $masked_token" >&2
    echo "" >&2
    read -p "Would you like to use this existing token? (Y/n): " USE_EXISTING
    USE_EXISTING=${USE_EXISTING:-Y}

    if [[ "$USE_EXISTING" =~ ^[Yy]$ ]]; then
        return 0  # Use existing
    else
        return 1  # Enter a new one
    fi
}

# ============================================
# Main Prompt + Validation Loop
# ============================================

# Prompt for CourtListener token with validation, existing-token detection, and retry logic
prompt_and_validate_token() {
    local token=""
    local max_attempts=3
    local attempt=0

    # STEP 1: Check for existing token in file-based storage
    if check_existing_token_file; then
        echo "INFO: Checking existing CourtListener API token..." >&2
        local existing_token
        existing_token=$(load_existing_token_file)

        if [[ $? -eq 0 && -n "$existing_token" ]]; then
            local masked
            masked=$(mask_api_token "$existing_token")

            if prompt_use_existing_token "$masked"; then
                echo "INFO: Using existing token from secure storage" >&2
                echo "$existing_token"
                return 0
            else
                echo "INFO: You chose to enter a new token" >&2
                echo "WARN: This will OVERWRITE the existing token" >&2
                read -p "Are you sure? (y/N): " CONFIRM_OVERWRITE
                if [[ ! "$CONFIRM_OVERWRITE" =~ ^[Yy]$ ]]; then
                    echo "INFO: Keeping existing token" >&2
                    echo "$existing_token"
                    return 0
                fi
            fi
        else
            echo "WARN: Existing token file found but could not be loaded (may be encrypted or corrupted)" >&2
            echo "INFO: You will need to enter a new token" >&2
        fi
    fi

    # STEP 2: Prompt for new token
    echo "" >&2
    echo "INFO: Get your free API token at: https://www.courtlistener.com/sign-in/" >&2
    echo "INFO: CourtListener tokens are 40-character hex strings (a-f, 0-9)" >&2
    echo "" >&2

    while [[ $attempt -lt $max_attempts ]]; do
        ((attempt++))

        read_api_token_secure "Enter your CourtListener API token" token

        if [[ -z "$token" ]]; then
            echo "ERROR: API token cannot be empty" >&2
            if [[ $attempt -lt $max_attempts ]]; then
                echo "INFO: Attempt $attempt of $max_attempts" >&2
            fi
            continue
        fi

        # Strip accidental whitespace
        token=$(echo "$token" | tr -d '[:space:]')

        VALIDATION_RESULT=$(validate_courtlistener_token "$token" 2>&1)
        if [ $? -eq 0 ]; then
            echo "$token"
            return 0
        else
            echo "$VALIDATION_RESULT" >&2
            if [[ $attempt -lt $max_attempts ]]; then
                echo "WARN: Attempt $attempt of $max_attempts — please try again" >&2
                echo "INFO: Format: 40 lowercase hex characters (a-f, 0-9)" >&2
            fi
        fi
    done

    echo "ERROR: Failed to provide valid token after $max_attempts attempts" >&2
    return 1
}

# ============================================
# Exports
# ============================================

export -f validate_courtlistener_token
export -f set_secure_file_permissions
export -f set_secure_directory_permissions
export -f mask_api_token
export -f read_api_token_secure
export -f check_existing_token_file
export -f load_existing_token_file
export -f prompt_use_existing_token
export -f prompt_and_validate_token
