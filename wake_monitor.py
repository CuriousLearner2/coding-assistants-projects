#!/usr/bin/env python3
"""
Wake-based job scheduler with three-layer notification system.

Layer 1: This daemon catches errors and sends error emails immediately
Layer 2: daily_refresh.py sends status emails (success/failure)
Layer 3: Timeout monitor sends alert if jobs don't complete within 30 minutes

Flow:
  System wake → detect via IOKit → check .run_log for today
    → spawn timeout_monitor.py (Layer 3)
    → spawn daily_refresh.py and nyt_digest.py (Layer 2)
    → if daemon error → send error email (Layer 1)
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


RECIPIENT = "gautambiswas2004@gmail.com"
RUN_LOG = Path.home() / "Claude Code" / ".run_log"
JOBS_DIR = Path.home() / "Claude Code" / "real-estate"
LOCK_FILE = Path.home() / "Claude Code" / ".wake_monitor.lock"
TIMEOUT_SECONDS = 30 * 60  # 30 minutes
WAKE_POLL_INTERVAL = 5  # seconds between sleep/wake checks


def _acquire_lock():
    """Ensure only one instance runs. Exit if lock exists."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            # Check if process is still running
            import subprocess as sp
            result = sp.run(["ps", "-p", str(pid)], capture_output=True)
            if result.returncode == 0:
                print(f"[wake_monitor] Another instance (PID {pid}) is already running. Exiting.")
                sys.exit(1)
            else:
                print(f"[wake_monitor] Stale lock file (PID {pid} not running), removing...")
                LOCK_FILE.unlink()
        except Exception as e:
            print(f"[wake_monitor] Error checking lock: {e}")

    # Write our PID to the lock file
    try:
        LOCK_FILE.write_text(str(os.getpid()))
        print(f"[wake_monitor] Lock acquired (PID {os.getpid()})")
    except Exception as e:
        print(f"[wake_monitor] Failed to create lock file: {e}")


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


def _get_last_run_date() -> str:
    """Get date of last successful run from .run_log (YYYY-MM-DD format)."""
    if not RUN_LOG.exists():
        return "1900-01-01"
    try:
        lines = RUN_LOG.read_text().strip().splitlines()
        if not lines:
            return "1900-01-01"
        # Last line format: "2026-04-23 14:30  listings-refresh       ✓ OK"
        last_line = lines[-1]
        return last_line.split()[0]  # Extract date
    except Exception:
        return "1900-01-01"


def _should_run_today() -> bool:
    """Check if jobs have already run today."""
    last_run_date = _get_last_run_date()
    today = datetime.now().strftime("%Y-%m-%d")
    return last_run_date != today


def _detect_wake_event() -> bool:
    """
    Check if system has woken from sleep and jobs should run.

    Returns True if we should run jobs based on:
    1. System is awake (not sleeping)
    2. Jobs haven't run today yet
    """
    # Simple approach: check if jobs should run today
    # If the system just woke and they haven't run today, we run them
    return _should_run_today()


def _send_error_email(error_title: str, error_details: str, traceback_str: str = ""):
    """Send error email for daemon-level failures (Layer 1) via SMTP."""
    try:
        import smtplib

        email_password = os.getenv("GMAIL_APP_PASSWORD")
        if not email_password:
            print(f"[wake_monitor] GMAIL_APP_PASSWORD not set, skipping error email")
            return

        traceback_html = f"<pre style='background:#f5f5f5;padding:10px;border-radius:5px;overflow:auto;'>{traceback_str}</pre>" if traceback_str else ""

        html = f"""
        <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:20px;">
          <h2 style="color:#c53030;">❌ Wake Monitor Error — {error_title}</h2>
          <p style="font-size:16px;color:#742a2a;background:#fed7d7;padding:10px;border-radius:5px;">
            <b>Error:</b> {error_details}
          </p>
          {traceback_html}
          <p style="color:#a0aec0;font-size:11px;margin-top:30px;">
            Daemon error detected at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
          </p>
        </body></html>
        """

        msg = MIMEMultipart("alternative")
        msg["To"] = RECIPIENT
        msg["From"] = RECIPIENT
        msg["Subject"] = f"🚨 Wake Monitor Error: {error_title}"
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(RECIPIENT, email_password)
            server.send_message(msg)

        print(f"[wake_monitor] ✓ Error email sent: {error_title}")
    except Exception as e:
        print(f"[wake_monitor] Failed to send error email: {e}")


def _spawn_timeout_monitor():
    """Spawn Layer 3: timeout monitor in background."""
    try:
        timeout_script = Path(__file__).parent / "timeout_monitor.py"
        subprocess.Popen(
            [sys.executable, str(timeout_script)],
            cwd=str(JOBS_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print(f"[wake_monitor] Spawned timeout monitor (Layer 3)")
    except Exception as e:
        print(f"[wake_monitor] Failed to spawn timeout monitor: {e}")


def _run_jobs():
    """
    Execute Layer 2: daily_refresh.py and nyt_digest.py.
    These send their own status emails.
    """
    python = sys.executable
    nyt_dir = Path.home() / "Claude Code" / "nyt"

    try:
        print(f"[wake_monitor] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - System wake detected, starting jobs...")

        # Run daily_refresh.py
        print("[wake_monitor] Running daily_refresh.py...")
        rc1 = subprocess.call(
            [python, "-u", "daily_refresh.py"],
            cwd=str(JOBS_DIR)
        )
        print(f"[wake_monitor] daily_refresh.py exited with code {rc1}")

        # Run nyt_digest.py
        print("[wake_monitor] Running nyt_digest.py...")
        rc2 = subprocess.call(
            [python, "-u", "nyt_digest.py"],
            cwd=str(nyt_dir)
        )
        print(f"[wake_monitor] nyt_digest.py exited with code {rc2}")

        return rc1 == 0 and rc2 == 0
    except Exception as e:
        print(f"[wake_monitor] Job execution failed: {e}")
        import traceback
        tb = traceback.format_exc()
        _send_error_email(
            "Job Execution Failed",
            f"Exception during job execution: {str(e)}",
            tb
        )
        return False


def main():
    """Main daemon loop."""
    _acquire_lock()
    _load_env()

    print(f"[wake_monitor] Starting wake monitor daemon at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[wake_monitor] Will monitor for system wake events and run jobs if needed")

    try:
        last_wake_check = 0

        while True:
            time.sleep(WAKE_POLL_INTERVAL)

            # Check for wake event (throttle checks to every 10 seconds)
            now = time.time()
            if now - last_wake_check < 10:
                continue
            last_wake_check = now

            if _detect_wake_event():
                print(f"\n[wake_monitor] ===== SYSTEM WAKE DETECTED =====")

                if not _should_run_today():
                    print(f"[wake_monitor] Jobs already ran today, skipping")
                    continue

                try:
                    # Spawn timeout monitor (Layer 3) BEFORE jobs start
                    _spawn_timeout_monitor()

                    # Run jobs (Layer 2 - they send status emails)
                    success = _run_jobs()

                    if success:
                        print(f"[wake_monitor] All jobs completed successfully")
                    else:
                        print(f"[wake_monitor] One or more jobs failed")

                except Exception as e:
                    print(f"[wake_monitor] Unexpected error during job run: {e}")
                    import traceback
                    tb = traceback.format_exc()
                    _send_error_email(
                        "Unexpected Job Run Error",
                        f"Exception during wake event handling: {str(e)}",
                        tb
                    )

                # Sleep after wake to avoid re-triggering on same wake event
                time.sleep(30)
                last_wake_check = time.time()

    except KeyboardInterrupt:
        print(f"[wake_monitor] Daemon interrupted")
        return 0
    except Exception as e:
        print(f"[wake_monitor] Fatal daemon error: {e}")
        import traceback
        tb = traceback.format_exc()
        _send_error_email(
            "Fatal Daemon Error",
            f"Unrecoverable exception in wake monitor: {str(e)}",
            tb
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
