#!/bin/bash
# Linear Product Feedback Triage Automation
# This script is called by launchd to run the triage automation

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/triage.log"
ENV_FILE="$SCRIPT_DIR/.env"

# Log start time
echo "========================================" >> "$LOG_FILE"
echo "Triage run started at $(date)" >> "$LOG_FILE"

# Load environment variables from .env file
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
else
    echo "ERROR: .env file not found at $ENV_FILE" >> "$LOG_FILE"
    exit 1
fi

# Check required environment variables
if [ -z "$LINEAR_API_KEY" ] || [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: Missing API keys in .env file" >> "$LOG_FILE"
    exit 1
fi

# Run the triage automation script with --execute flag
cd "$SCRIPT_DIR"
/usr/bin/python3 "$SCRIPT_DIR/triage_automation.py" --execute >> "$LOG_FILE" 2>&1

EXIT_CODE=$?

# Log completion
echo "Triage run completed at $(date) with exit code $EXIT_CODE" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

exit $EXIT_CODE
