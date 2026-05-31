#!/usr/bin/env python3
"""Send a failure alert email via SMTP. Called by wrapper scripts on error."""
import os
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

RECIPIENT = "gautambiswas2004@icloud.com"


def send_alert(job: str, reason: str, log_path: str) -> None:
    """Send alert email via Gmail SMTP with app password."""
    try:
        email_password = os.getenv("GMAIL_APP_PASSWORD")
        if not email_password:
            print("WARNING: GMAIL_APP_PASSWORD not set, cannot send alert", file=sys.stderr)
            return

        log_tail = ""
        try:
            lines = Path(log_path).read_text().splitlines()
            log_tail = "\n".join(lines[-40:])
        except Exception:
            log_tail = "(log not readable)"

        body = (
            f"Job:    {job}\n"
            f"Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Reason: {reason}\n\n"
            f"--- Last 40 lines of {log_path} ---\n"
            f"{log_tail}\n"
        )
        msg = MIMEText(body, "plain")
        msg["To"] = RECIPIENT
        msg["From"] = RECIPIENT
        msg["Subject"] = f"[ALERT] {job} failed — {reason}"

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(RECIPIENT, email_password)
            server.send_message(msg)

        print(f"✓ Alert email sent to {RECIPIENT}")
    except Exception as e:
        print(f"WARNING: Could not send alert email: {e}", file=sys.stderr)


if __name__ == "__main__":
    # Usage: send_alert.py <job> <reason> <log_path>
    if len(sys.argv) != 4:
        print("Usage: send_alert.py <job> <reason> <log_path>", file=sys.stderr)
        sys.exit(1)
    send_alert(sys.argv[1], sys.argv[2], sys.argv[3])
