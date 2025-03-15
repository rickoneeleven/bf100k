#!/bin/bash
# Script to check for required dashboard files and their permissions

# Base directory - CORRECTED PATH
WEB_DIR="/home/loopnova/domains/bf100k/public_html/web"
cd "$WEB_DIR" || { echo "Cannot access web directory at $WEB_DIR!"; exit 1; }

echo "===== Dashboard Files Check ====="
echo "Current directory: $(pwd)"
echo ""

# Check dashboard files
echo "Checking dashboard files:"
for file in dashboard.html dashboard.css dashboard.js; do
    if [ -f "$file" ]; then
        echo "✓ $file exists ($(stat -c '%s bytes, permissions: %a' "$file"))"
    else
        echo "✗ $file is missing!"
    fi
done

echo ""
echo "Checking data directory structure:"
# Check data directory
if [ -d "data" ]; then
    echo "✓ data/ directory exists (permissions: $(stat -c '%a' data/))"
    
    # Check betting directory
    if [ -d "data/betting" ]; then
        echo "  ✓ data/betting/ directory exists (permissions: $(stat -c '%a' data/betting/))"
        
        # Check required JSON files
        echo ""
        echo "  Checking JSON files in data/betting/:"
        for file in betting_state.json active_bet.json bet_history.json; do
            if [ -f "data/betting/$file" ]; then
                size=$(stat -c '%s' "data/betting/$file")
                if [ "$size" -gt 2 ]; then
                    echo "    ✓ $file exists ($size bytes, permissions: $(stat -c '%a' "data/betting/$file"))"
                    echo "      First 100 chars: $(head -c 100 "data/betting/$file" | tr -d '\n')..."
                else
                    echo "    ⚠ $file exists but may be empty or invalid ($size bytes)"
                fi
            else
                echo "    ✗ $file is missing!"
            fi
        done
    else
        echo "  ✗ data/betting/ directory is missing!"
    fi
else
    echo "✗ data/ directory is missing!"
fi

echo ""
echo "Checking config directory:"
# Check config directory
if [ -d "config" ]; then
    echo "✓ config/ directory exists (permissions: $(stat -c '%a' config/))"
    
    # Check betting_config.json
    if [ -f "config/betting_config.json" ]; then
        size=$(stat -c '%s' "config/betting_config.json")
        if [ "$size" -gt 2 ]; then
            echo "  ✓ betting_config.json exists ($size bytes, permissions: $(stat -c '%a' "config/betting_config.json"))"
            echo "    First 100 chars: $(head -c 100 "config/betting_config.json" | tr -d '\n')..."
        else
            echo "  ⚠ betting_config.json exists but may be empty or invalid ($size bytes)"
        fi
    else
        echo "  ✗ betting_config.json is missing!"
    fi
else
    echo "✗ config/ directory is missing!"
fi

echo ""
echo "Checking logs directory:"
# Check logs directory
if [ -d "logs" ]; then
    echo "✓ logs/ directory exists (permissions: $(stat -c '%a' logs/))"
    
    # Check system.log
    if [ -f "logs/system.log" ]; then
        echo "  ✓ system.log exists ($(stat -c '%s bytes, permissions: %a' "logs/system.log"))"
    else
        echo "  ✗ system.log is missing!"
    fi
else
    echo "✗ logs/ directory is missing!"
fi

echo ""
echo "===== End of Check ====="
