#!/bin/bash
# Verify that scheduled jobs are running (runs at 7:10 AM, 10 min after start)
# This is independent of launchd, so it catches launchd failures
# Auto-repairs jobs that failed to start
# Usage: crontab -e, then add line for this script

LOG_FILE="/Users/gautambiswas/Claude Code/.run_log"
TODAY=$(date +%Y-%m-%d)
ALERT_EMAIL="gautambiswas2004@icloud.com"
REPAIRS=()
IN_PROGRESS=()
FAILED=()

echo "=== Job Status Check at 7:10 AM ($(date)) ==="

# Function to check if a process is running
is_process_running() {
    local script_name=$1
    ps aux | grep -E "bash.*$script_name" | grep -v grep > /dev/null
}

# Function to repair a failed job
repair_job() {
    local job_name=$1
    local plist_path=$2
    local run_script=$3

    echo "Attempting to repair $job_name..."
    REPAIRS+=("$job_name")

    # Reload the launchd job
    launchctl unload "$plist_path" 2>/dev/null
    launchctl load "$plist_path"
    if [ $? -ne 0 ]; then
        echo "❌ Failed to reload $job_name"
        return 1
    fi

    # Manually trigger the job
    if [ -n "$run_script" ] && [ -f "$run_script" ]; then
        bash "$run_script" >> "$LOG_FILE" 2>&1 &
        echo "✓ Reloaded and triggered $job_name"
    else
        echo "✓ Reloaded $job_name (script not available for manual trigger)"
    fi
    return 0
}

# Check nyt-digest (runs at 7:00 AM)
if grep -q "$TODAY.*nyt-digest.*OK" "$LOG_FILE"; then
    echo "✓ NY Times digest completed"
elif is_process_running "nyt_digest.py"; then
    echo "⏳ NY Times digest still running"
    IN_PROGRESS+=("nyt-digest")
else
    echo "❌ NY Times digest failed to run"
    FAILED+=("nyt-digest")
    repair_job "nyt-digest" \
        "$HOME/Library/LaunchAgents/com.gautambiswas.nyt-digest.plist" \
        ""
fi

# Check listings-refresh (runs at 7:00, 9:00, 11:00 AM)
if grep -q "$TODAY.*listings-refresh.*OK" "$LOG_FILE"; then
    echo "✓ Listings refresh completed"
elif is_process_running "daily_refresh.py\|run_daily_refresh.sh"; then
    echo "⏳ Listings refresh still running"
    IN_PROGRESS+=("listings-refresh")
else
    echo "❌ Listings refresh failed to run"
    FAILED+=("listings-refresh")
    repair_job "listings-refresh" \
        "$HOME/Library/LaunchAgents/com.gautambiswas.listings-refresh.plist" \
        "/Users/gautambiswas/Claude Code/run_daily_refresh.sh"
fi

# Send alerts based on status
{
    alert_sent=0

    # Alert if jobs are still running (normal, just informational)
    if [ ${#IN_PROGRESS[@]} -gt 0 ]; then
        echo "Status Report: $TODAY at $(date '+%H:%M')"
        echo ""
        echo "Jobs still running (started at 7:00 AM):"
        for job in "${IN_PROGRESS[@]}"; do
            echo "  ⏳ $job"
        done
        echo ""
        echo "Expected completion: within a few minutes"
        alert_sent=1
    fi

    # Alert if auto-repairs were made
    if [ ${#REPAIRS[@]} -gt 0 ]; then
        if [ $alert_sent -eq 1 ]; then
            echo "---"
            echo ""
        fi
        echo "Auto-repaired jobs that failed to start:"
        for job in "${REPAIRS[@]}"; do
            echo "  ✓ $job"
        done
        echo ""
        echo "The jobs have been reloaded and manually triggered."
        echo "Check the run log for details: tail -20 /Users/gautambiswas/Claude\ Code/.run_log"
        alert_sent=1
    fi

    # Only send email if there's something to report
    if [ $alert_sent -eq 1 ]; then
        if [ ${#IN_PROGRESS[@]} -gt 0 ] && [ ${#REPAIRS[@]} -eq 0 ]; then
            # Only in-progress, no repairs needed
            mail -s "ℹ️ Job Status: Still Running" "$ALERT_EMAIL"
        elif [ ${#REPAIRS[@]} -gt 0 ]; then
            # Repairs were made
            mail -s "✓ Auto-Repaired Failed Jobs" "$ALERT_EMAIL"
        fi
    fi
} | {
    # Read the entire output and pipe to mail if needed
    cat_output=$(cat)
    if [ ! -z "$cat_output" ]; then
        if [ ${#IN_PROGRESS[@]} -gt 0 ] && [ ${#REPAIRS[@]} -eq 0 ]; then
            echo "$cat_output" | mail -s "ℹ️ Job Status: Still Running at 7:10 AM" "$ALERT_EMAIL"
        elif [ ${#REPAIRS[@]} -gt 0 ]; then
            echo "$cat_output" | mail -s "✓ Auto-Repaired Failed Jobs on $TODAY" "$ALERT_EMAIL"
        fi
    fi
}

echo "Done."
