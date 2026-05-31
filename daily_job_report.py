#!/usr/bin/env python3
"""
Daily job status report - only reports failures that couldn't be auto-fixed
"""
import os
import sys
import json
from datetime import datetime
from pathlib import Path
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
recipient = "gautambiswas2004@icloud.com"

# Read today's jobs
jobs = []
try:
    with open(run_log) as f:
        for line in f:
            if today in line:
                jobs.append(line.strip())
except FileNotFoundError:
    print("ERROR: Run log not found")
    sys.exit(1)

if not jobs:
    print("No jobs found for today")
    sys.exit(1)

# Read remediation log if it exists
remediation_data = {}
if remediation_log.exists():
    try:
        with open(remediation_log) as f:
            remediation_data = json.load(f)
    except:
        pass

# Count statuses
successful = sum(1 for j in jobs if "✓ OK" in j)
failures = sum(1 for j in jobs if "❌ ERROR" in j)
partial = sum(1 for j in jobs if "⚠ PARTIAL" in j)

# Find unfixed failures
unfixed_failures = {}
if "failures" in remediation_data:
    for job_name, details in remediation_data["failures"].items():
        if not details.get("fixed", False):
            unfixed_failures[job_name] = details

# Build HTML
job_rows = ""
for job in jobs:
    parts = job.split()
    time_str = f"{parts[0]} {parts[1]}"
    job_name = parts[2]
    status = " ".join(parts[3:]) if len(parts) > 3 else "UNKNOWN"

    status_color = "#28a745" if "✓" in status else "#dc3545" if "❌" in status else "#ffc107"
    job_rows += f'<tr><td style="color: #666;">{time_str}</td><td>{job_name}</td><td style="color: {status_color}; font-weight: bold;">{status}</td></tr>\n'

# Alert banner for unfixed failures only
alert_banner = ""
if unfixed_failures:
    count = len(unfixed_failures)
    alert_banner = f"""
    <div style="background: #f8d7da; border-left: 4px solid #dc3545; padding: 15px; margin: 20px 0; border-radius: 4px;">
        <strong style="color: #721c24;">🔴 Unfixed Failures ({count}):</strong>
        <p style="margin: 10px 0; color: #721c24;">The following job(s) failed and could not be auto-fixed. Manual intervention required.</p>
        <ul style="margin: 10px 0; color: #721c24;">
"""
    for job_name, details in unfixed_failures.items():
        alert_banner += f"<li><strong>{job_name}</strong>: {details.get('error', 'Unknown error')}</li>\n"
    alert_banner += "</ul></div>\n"

# Only show unfixed failures section if there are any
unfixed_section = ""
if unfixed_failures:
    unfixed_section = "<h2>Unfixed Failures — Action Required</h2>\n<ul style='color: #dc3545; font-weight: bold;'>\n"
    for job_name, details in unfixed_failures.items():
        unfixed_section += f"<li>{job_name}: {details.get('error', 'Unknown error')}</li>\n"
    unfixed_section += "</ul>\n"

html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f9f9f9; }}
        .container {{ background: white; padding: 30px; border-radius: 8px; max-width: 800px; margin: 0 auto; }}
        h1 {{ color: #333; margin-bottom: 20px; }}
        h2 {{ color: #333; margin-top: 30px; margin-bottom: 15px; font-size: 18px; }}
        .summary {{ display: flex; gap: 40px; margin: 30px 0; background: #f5f5f5; padding: 20px; border-radius: 5px; }}
        .stat {{ text-align: center; }}
        .stat-number {{ font-size: 32px; font-weight: bold; margin-bottom: 5px; }}
        .stat-label {{ color: #666; font-size: 14px; }}
        .ok {{ color: #28a745; }}
        .error {{ color: #dc3545; }}
        .warning {{ color: #ffc107; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #f8f9fa; padding: 12px; text-align: left; border-bottom: 2px solid #ddd; font-weight: bold; }}
        td {{ padding: 12px; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f9f9f9; }}
        ul {{ margin: 10px 0; padding-left: 20px; }}
        li {{ margin: 8px 0; color: #333; }}
        .footer {{ margin-top: 30px; color: #999; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Daily Job Status Report</h1>
        <p style="color: #666; margin-bottom: 20px;"><strong>Date:</strong> {today} (UTC)</p>

        {alert_banner}

        <div class="summary">
            <div class="stat">
                <div class="stat-number ok">{successful}</div>
                <div class="stat-label">Successful</div>
            </div>
            <div class="stat">
                <div class="stat-number error">{failures}</div>
                <div class="stat-label">Failures</div>
            </div>
            <div class="stat">
                <div class="stat-number warning">{partial}</div>
                <div class="stat-label">Partial</div>
            </div>
        </div>

        <h2>Job Execution Log</h2>
        <table>
            <tr>
                <th>Time (UTC)</th>
                <th>Job</th>
                <th>Status</th>
            </tr>
            {job_rows}
        </table>

        {unfixed_section}

        <div class="footer">
            <p>Automated report from LaunchD job monitoring system</p>
            <p>Failed jobs are automatically detected and fixed within 5 minutes. Only unfixed failures are shown above.</p>
            <p style="font-size: 11px; color: #999; margin-top: 15px;">
                <strong>Job Schedule:</strong> Listings-refresh & nyt-digest run daily at 7/9/11 AM PDT (cascading fallback).
                Backup-dbs runs at 1/9 AM UTC. Supabase-keepalive runs Mon/Wed/Fri at 11 PM PDT.
            </p>
        </div>
    </div>
</body>
</html>
"""

# Only send email if there are unfixed failures (or if you want daily summaries, remove this condition)
gmail_password = os.getenv("GMAIL_APP_PASSWORD")
if not gmail_password:
    print("ERROR: GMAIL_APP_PASSWORD not found in environment")
    sys.exit(1)

msg = MIMEMultipart("alternative")
if unfixed_failures:
    msg["Subject"] = f"Daily Job Report — {today} [UNFIXED FAILURES]"
else:
    msg["Subject"] = f"Daily Job Report — {today} [All Clear]"

msg["From"] = "gautambiswas2004@icloud.com"
msg["To"] = recipient
msg.attach(MIMEText(html, "html"))

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
        server.login("gautambiswas2004@icloud.com", gmail_password)
        server.sendmail("gautambiswas2004@icloud.com", [recipient], msg.as_string())

    if unfixed_failures:
        print(f"⚠ Report sent: {len(unfixed_failures)} unfixed failure(s)")
    else:
        print(f"✓ Report sent: All {successful} jobs successful, no failures")
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
