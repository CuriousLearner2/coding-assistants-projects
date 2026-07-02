#!/usr/bin/env python3
"""
Supabase keepalive script - prevents free-tier projects from being paused due to inactivity.
Runs three times a week to maintain activity on the Supabase project.
Includes retry logic and email alerts.
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# Load environment variables
load_dotenv()

# Setup logging
log_dir = Path.home() / ".local/share/job-logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "supabase-keepalive.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("supabase_keepalive")

RUN_LOG = Path.home() / "Claude Code" / ".run_log"
RECIPIENT = "gautambiswas2004@icloud.com"


def _write_run_log(status: str):
    """Log to the run log for visibility with other jobs."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(RUN_LOG, "a") as f:
        f.write(f"{ts}  supabase-keepalive        {status}\n")


def _send_email(subject: str, body: str):
    """Send email alert via SMTP (iCloud)."""
    try:
        import smtplib
        from email.mime.text import MIMEText

        # Use iCloud SMTP instead of Gmail API (more reliable)
        email_user = os.getenv("ICLOUD_EMAIL", "gautambiswas2004@icloud.com")
        email_password = os.getenv("ICLOUD_APP_PASSWORD")

        if not email_password:
            logger.warning("ICLOUD_APP_PASSWORD not set, skipping email")
            return

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = email_user
        msg["To"] = RECIPIENT

        # Use iCloud SMTP server
        with smtplib.SMTP("smtp.mail.me.com", 587) as server:
            server.starttls()
            server.login(email_user, email_password)
            server.sendmail(email_user, RECIPIENT, msg.as_string())

        logger.info(f"✓ Email sent: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((Exception,)),
    reraise=True
)
def send_keepalive():
    """Send a keepalive ping to Supabase to prevent project pause.

    Retries 3 times with exponential backoff (4s, 8s, 16s).
    """
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_ANON_KEY environment variables")

    logger.info("Connecting to Supabase...")
    supabase: Client = create_client(supabase_url, supabase_key)

    # Simple query to trigger activity - just count records in any table
    logger.info("Sending keepalive ping to Supabase...")
    response = supabase.table("whatsapp_sessions").select("*", count="exact").limit(1).execute()

    if not response:
        raise Exception("Keepalive query returned empty response")

    logger.info("✓ Keepalive successful - Supabase project is active")
    return True


if __name__ == "__main__":
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Starting Supabase keepalive at {timestamp}")

    try:
        send_keepalive()

        # Success
        logger.info("Keepalive completed successfully")
        _write_run_log("✓ OK")

        # Send success email
        body = f"""Supabase keepalive completed successfully.

Time: {timestamp}
Project: ctfxidycbwybpbixwskw
Status: Active

Your Supabase project is preventing pause due to inactivity."""
        _send_email("✓ Supabase Keepalive Successful", body)

        exit(0)

    except Exception as e:
        # Failure
        logger.error(f"Keepalive failed after 3 retries: {str(e)}")
        _write_run_log("❌ FAILED")

        # Send failure email
        body = f"""Supabase keepalive FAILED after 3 retry attempts.

Time: {timestamp}
Project: ctfxidycbwybpbixwskw
Status: ERROR
Error: {str(e)}

The Supabase project may be at risk of pausing due to inactivity.
Please check the credentials and logs:
tail -20 /Users/gautambiswas/.local/share/job-logs/supabase-keepalive.log"""
        _send_email("❌ Supabase Keepalive FAILED", body)

        exit(1)
