#!/bin/bash
# Script to check for required dashboard files and their permissions

# Base directory for the web files
# Adjust this path if your web root is different or the script is run from elsewhere
WEB_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
# Defaulting to script's directory, assuming it's in /web/

cd "$WEB_DIR" || { echo "Cannot access web directory at $WEB_DIR!"; exit 1; }

echo "===== Dashboard Files Check ====="
echo "Checking in directory: $(pwd)"
echo ""

# Helper function to check file
check_file() {
    local filepath="$1"
    local filename=$(basename "$filepath")
    local description="$2"

    if [ -f "$filepath" ]; then
        local size=$(stat -c '%s' "$filepath" 2>/dev/null || stat -f '%z' "$filepath") # Linux/macOS size
        local perms=$(stat -c '%a' "$filepath" 2>/dev/null || stat -f '%Lp' "$filepath") # Linux/macOS perms
        if [ "$size" -gt 2 ]; then
            echo "  ✓ $description ($filename) exists ($size bytes, permissions: $perms)"
            # echo "    First 100 chars: $(head -c 100 "$filepath" | tr -d '\n')..." # Can be verbose
        else
            echo "  ⚠️ $description ($filename) exists but may be empty or invalid ($size bytes, permissions: $perms)"
        fi
    else
        echo "  ✗ $description ($filename) is MISSING!"
    fi
}

# Helper function to check directory
check_dir() {
    local dirpath="$1"
    local description="$2"
    if [ -d "$dirpath" ]; then
         local perms=$(stat -c '%a' "$dirpath" 2>/dev/null || stat -f '%Lp' "$dirpath")
        echo "✓ $description ($(basename "$dirpath")/) directory exists (permissions: $perms)"
        return 0 # Success
    else
        echo "✗ $description ($(basename "$dirpath")/) directory is MISSING!"
        return 1 # Failure
    fi
}


# Check dashboard files
echo "--- Dashboard Files ---"
check_file "dashboard.html" "Dashboard HTML"
check_file "dashboard.css" "Dashboard CSS"
check_file "dashboard.js" "Dashboard JS"

# Check config directory and file
echo ""
echo "--- Configuration ---"
if check_dir "config" "Config"; then
    check_file "config/betting_config.json" "Betting Config"
fi

# Check data directory structure and files
echo ""
echo "--- Data Files ---"
if check_dir "data" "Data"; then
    if check_dir "data/betting" "Betting Data"; then
        check_file "data/betting/betting_state.json" "Betting State"
        check_file "data/betting/active_bet.json" "Active Bet"
        check_file "data/betting/bet_history.json" "Bet History"
    fi
fi

# Check logs directory and key log file
echo ""
echo "--- Logs ---"
if check_dir "logs" "Logs"; then
    check_file "logs/system.log" "System Log"
    # Add checks for other specific logs if needed, e.g.:
    # check_file "logs/BetfairClient.log" "Betfair Client Log"
fi


echo ""
echo "===== End of Check ====="
echo "Notes:"
echo "- Ensure the web server process (e.g., www-data, nginx, apache) has READ permissions for all checked files, especially in data/ and config/."
echo "- Ensure the Python application process has READ and WRITE permissions for files in data/betting/ and logs/."