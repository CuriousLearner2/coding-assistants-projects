#!/usr/bin/env python3
"""
Timeout monitor (Layer 3) — sends alert email if jobs don't complete within 30 minutes.

Runs in parallel with daily_refresh.py and nyt_digest.py.
If neither job completes (indicated by .run_log timestamp), sends timeout alert.
"""
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


RECIPIENT = "gautambiswas2004@icloud.com"
RUN_LOG = Path.home() / "Claude Code" / ".run_log"
TIMEOUT_SECONDS = 30 * 60  # 30 minutes
CHECK_INTERVAL = 10  # seconds between checks


def _load_env():
    """Load environment variables from ~/.zshrc."""
    zshrc = Path.home() / ".zshrc"
    if not zshrc.exists():
        return
    for line in zshrc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            assignment = line[7:]
            if "=" in assignment:
                key, value = assignment.split("=", 1)
                key, value = key.strip(), value.strip()
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                if key and value:
                    os.environ[key] = value


def _get_last_log_timestamp() -> datetime:
    """Get timestamp of last .run_log entry."""
    if not RUN_LOG.exists():
        return datetime.now() - timedelta(hours=1)
    try:
        lines = RUN_LOG.read_text().strip().splitlines()
        if not lines:
            return datetime.now() - timedelta(hours=1)
        last_line = lines[-1]
        # Line format: "2026-04-23 14:30  listings-refresh       ✓ OK"
        time_str = ' '.join(last_line.split()[:2])
        return datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    except Exception:
        return datetime.now() - timedelta(hours=1)


def _send_timeout_email():
    """Send timeout alert email via SMTP."""
    try:
        import smtplib

        email_password = os.getenv("GMAIL_APP_PASSWORD")
        if not email_password:
            print("[timeout_monitor] GMAIL_APP_PASSWORD not set, cannot send timeout alert")
            return

        html = f"""
        <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:20px;">
          <h2 style="color:#c53030;">⏱️ Job Timeout Alert</h2>
          <p style="font-size:16px;color:#742a2a;background:#fed7d7;padding:10px;border-radius:5px;">
            <b>Status:</b> Scheduled jobs did not complete within 30 minutes of system wake
          </p>
          <p><b>What to check:</b></p>
          <ul>
            <li>Is daily_refresh.py still running? Check: <code>ps aux | grep daily_refresh</code></li>
            <li>Are there Gmail/iCloud authentication errors? Check the job logs</li>
            <li>Is the system under heavy load? Check Activity Monitor</li>
            <li>Did the system go back to sleep? Check pmset log</li>
          </ul>
          <p><b>How to recover:</b></p>
          <ol>
            <li>If jobs are still running, wait for them to complete (they'll send their own status email)</li>
            <li>If jobs are hung, kill them: <code>pkill -f daily_refresh</code></li>
            <li>Then manually run: <code>cd ~/Claude\ Code/real-estate && python3 daily_refresh.py</code></li>
          </ol>
          <p style="color:#a0aec0;font-size:11px;margin-top:30px;">
            Timeout detected at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
          </p>
        </body></html>
        """

        msg = MIMEMultipart("alternative")
        msg["To"] = RECIPIENT
        msg["From"] = RECIPIENT
        msg["Subject"] = "⏱️ Wake Job Timeout (30+ minutes)"
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(RECIPIENT, email_password)
            server.send_message(msg)

        print(f"[timeout_monitor] ✓ Timeout alert email sent")
    except Exception as e:
        print(f"[timeout_monitor] Failed to send timeout email: {e}")


def main():
    r"""Monitor for job timeout and send alert if needed."""
    _load_env()

    print(f"[timeout_monitor] Starting timeout monitor (will alert if jobs don't complete within {TIMEOUT_SECONDS}s)")

    start_time = time.time()
    timeout_sent = False

    while True:
        time.sleep(CHECK_INTERVAL)

        elapsed = time.time() - start_time

        # Check if a job has completed by looking at .run_log timestamp
        last_log_time = _get_last_log_timestamp()
        now = datetime.now()
        time_since_log = (now - last_log_time).total_seconds()

        # If a log entry was added recently (within last 30 seconds), jobs are completing
        if time_since_log < 30:
            print(f"[timeout_monitor] Job completed (log updated {time_since_log}s ago), exiting")
            return 0

        # If timeout exceeded and we haven't sent alert yet, send it
        if elapsed > TIMEOUT_SECONDS and not timeout_sent:
            print(f"[timeout_monitor] Timeout ({TIMEOUT_SECONDS}s) exceeded, sending alert")
            _send_timeout_email()
            timeout_sent = True

            # Continue monitoring for up to 1 more hour in case jobs are just slow
            if elapsed > TIMEOUT_SECONDS + 3600:
                print(f"[timeout_monitor] Giving up after 90 minutes")
                return 1

        # Log status every 5 minutes
        if int(elapsed) % 300 == 0:
            print(f"[timeout_monitor] Still monitoring ({int(elapsed/60)} min elapsed)...")


if __name__ == "__main__":
    sys.exit(main())
