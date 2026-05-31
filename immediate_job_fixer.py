#!/usr/bin/env python3
"""
Real-time job failure detector and immediate fixer.
- Checks for failures and long-running processes
- Attempts immediate fixes
- Sends real-time alerts for failures (not waiting for end-of-day report)
"""
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

# Load environment
env_file = Path.home() / "Claude Code" / ".env"
load_dotenv(env_file)

today = datetime.now().strftime("%Y-%m-%d")
run_log = Path.home() / "Claude Code" / ".run_log"
remediation_log = Path.home() / ".local/share/job-logs/remediation_log.json"
remediation_log.parent.mkdir(parents=True, exist_ok=True)
recipient = "gautambiswas2004@icloud.com"

# Read today's jobs
jobs = []
try:
    with open(run_log) as f:
        for line in f:
            if today in line:
                jobs.append(line.strip())
except FileNotFoundError:
    sys.exit(0)

# Check for long-running processes
long_running = []
for script_name, display_name in [
    ("run_daily_refresh.sh", "listings-refresh"),
    ("run_nyt_digest.sh", "nyt-digest"),
    ("backup_dbs.sh", "backup-dbs")
]:
    try:
        result = subprocess.run(
            ["pgrep", "-f", script_name],
            capture_output=True,
            text=True
        )
        if result.stdout:
            # Process is running, get its start time
            pid = result.stdout.strip().split()[0]
            try:
                ps_result = subprocess.run(
                    ["ps", "-p", pid, "-o", "etime="],
                    capture_output=True,
                    text=True
                )
                elapsed = ps_result.stdout.strip()
                long_running.append({
                    "name": display_name,
                    "script": script_name,
                    "pid": pid,
                    "elapsed": elapsed
                })
            except:
                pass
    except:
        pass

# Find failed jobs
failed_jobs = {}
for job in jobs:
    if "❌ ERROR" in job or "⚠ PARTIAL" in job:
        parts = job.split()
        time_str = f"{parts[0]} {parts[1]}"
        job_name = parts[2]
        status = "ERROR" if "❌" in job else "PARTIAL"

        if job_name not in failed_jobs:
            failed_jobs[job_name] = {"time": time_str, "status": status, "fixed": False, "error": ""}

# If there are failures, attempt immediate fixes
if failed_jobs:
    scripts = {
        "listings-refresh": "/Users/gautambiswas/Claude Code/run_daily_refresh.sh",
        "nyt-digest": "/Users/gautambiswas/Claude Code/run_nyt_digest.sh",
        "backup-dbs": "/Users/gautambiswas/Claude Code/backup_dbs.sh",
    }

    for job_name, details in failed_jobs.items():
        script = None
        for job_key, script_path in scripts.items():
            if job_key in job_name.lower():
                script = script_path
                break

        if not script or not Path(script).exists():
            details["error"] = "Script not found"
            continue

        try:
            result = subprocess.run(
                ["bash", script],
                capture_output=True,
                text=True,
                timeout=600
            )

            if result.returncode == 0:
                details["fixed"] = True
            else:
                stderr = result.stderr[:200] if result.stderr else "Unknown error"
                details["error"] = stderr

        except subprocess.TimeoutExpired:
            details["error"] = "Timeout (exceeded 10 minutes)"
        except Exception as e:
            details["error"] = str(e)[:200]

    # Save remediation log
    with open(remediation_log, "w") as f:
        json.dump({
            "date": today,
            "timestamp": datetime.now().isoformat(),
            "failures": failed_jobs
        }, f, indent=2)

    # Send immediate alert for unfixed failures
    unfixed = {k: v for k, v in failed_jobs.items() if not v["fixed"]}
    if unfixed:
        alert_html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #fff3cd; }}
        .container {{ background: white; padding: 30px; border-radius: 8px; max-width: 600px; margin: 0 auto; border: 2px solid #dc3545; }}
        h1 {{ color: #dc3545; margin-bottom: 20px; }}
        .failure {{ background: #f8d7da; border-left: 4px solid #dc3545; padding: 15px; margin: 15px 0; border-radius: 4px; }}
        .failure-name {{ font-weight: bold; color: #721c24; }}
        .failure-error {{ color: #721c24; font-family: monospace; font-size: 12px; margin-top: 5px; }}
        .timestamp {{ color: #666; font-size: 12px; margin-top: 15px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔴 Job Failure Alert</h1>
        <p>The following job(s) failed and could not be auto-fixed:</p>
"""
        for job_name, details in unfixed.items():
            alert_html += f"""
        <div class="failure">
            <div class="failure-name">{job_name}</div>
            <div class="failure-error">{details.get('error', 'Unknown error')}</div>
        </div>
"""
        alert_html += f"""
        <p class="timestamp">Detected: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
    </div>
</body>
</html>
"""

        gmail_password = os.getenv("GMAIL_APP_PASSWORD")
        if gmail_password:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = f"🔴 JOB FAILURE ALERT — {today}"
                msg["From"] = "gautambiswas2004@icloud.com"
                msg["To"] = recipient
                msg.attach(MIMEText(alert_html, "html"))

                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
                    server.login("gautambiswas2004@icloud.com", gmail_password)
                    server.sendmail("gautambiswas2004@icloud.com", [recipient], msg.as_string())
            except:
                pass

# Alert if processes are running too long (> 10 minutes)
if long_running:
    for proc in long_running:
        # Parse elapsed time (format: HH:MM:SS or MM:SS)
        try:
            parts = proc["elapsed"].split(":")
            if len(parts) == 3:
                minutes = int(parts[1])
            else:
                minutes = int(parts[0])

            if minutes > 10:
                alert_html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #fff3cd; }}
        .container {{ background: white; padding: 30px; border-radius: 8px; max-width: 600px; margin: 0 auto; border: 2px solid #ffc107; }}
        h1 {{ color: #ff6c00; margin-bottom: 20px; }}
        .warning {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 15px 0; border-radius: 4px; }}
        .job-name {{ font-weight: bold; color: #856404; }}
        .job-details {{ color: #856404; margin-top: 5px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>⚠ Long-Running Job Alert</h1>
        <div class="warning">
            <div class="job-name">{proc['name']}</div>
            <div class="job-details">Running for {proc['elapsed']} (PID: {proc['pid']})</div>
        </div>
        <p>This job is taking longer than expected. Monitor it.</p>
    </div>
</body>
</html>
"""

                gmail_password = os.getenv("GMAIL_APP_PASSWORD")
                if gmail_password:
                    try:
                        msg = MIMEMultipart("alternative")
                        msg["Subject"] = f"⚠ LONG-RUNNING JOB — {proc['name']}"
                        msg["From"] = "gautambiswas2004@icloud.com"
                        msg["To"] = recipient
                        msg.attach(MIMEText(alert_html, "html"))

                        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
                            server.login("gautambiswas2004@icloud.com", gmail_password)
                            server.sendmail("gautambiswas2004@icloud.com", [recipient], msg.as_string())
                    except:
                        pass
        except:
            pass
