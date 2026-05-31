#!/usr/bin/env python3
"""
Nightly refresh + audit pipeline with email summary.
Runs: refresh_db → audit_ingest → send summary email.
Triggered by launchd at 11 PM; email arrives when audit batch completes (~11:10 PM).
"""
import base64
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Add current directory to path so imports work from any location
sys.path.insert(0, str(Path(__file__).parent))

RECIPIENT = "gautambiswas2004@icloud.com"
DB_PATH = "listings/listings.db"
RUN_LOG = Path.home() / "Claude Code" / ".run_log"


def _write_run_log(name: str, status: str):
    """Append a timestamped run record to the shared run log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        with open(RUN_LOG, "a") as f:
            f.write(f"{ts}  {name:<30}  {status}\n")
        print(f"  ✓ Wrote to run log: {ts}  {name:<30}  {status}")
    except Exception as e:
        print(f"  ✗ Error writing run log to {RUN_LOG}: {e}")


def _already_ran_today() -> bool:
    """Check if listings-refresh already ran successfully today (deduplication for redundant jobs)."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(RUN_LOG, "r") as f:
            for line in f:
                if today in line and "listings-refresh" in line and "✓ OK" in line:
                    return True
    except FileNotFoundError:
        pass
    return False


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


def _get_last_timestamp():
    """Get last ingest timestamp from DB."""
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT value FROM sync_state WHERE key = 'last_email_timestamp'"
        ).fetchone()
        conn.close()
        return row[0] if row else "2020-01-01T00:00:00"
    except Exception:
        return "2020-01-01T00:00:00"


def _run_script(cmd: list) -> tuple[int, str]:
    """Run a script, streaming output to stdout while also capturing it."""
    buf = []
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd="/Users/gautambiswas/Claude Code/real-estate",
    )
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        buf.append(line)
    proc.wait()
    return proc.returncode, "".join(buf)


def _parse_refresh_output(output: str) -> dict:
    """Extract key stats from refresh_db output."""
    stats = {
        "east_bay_emails": 0,
        "east_bay_listings": 0,
        "cleveland_listings": 0,
    }
    m = re.search(r"Fetched (\d+) new emails", output)
    if m:
        stats["east_bay_emails"] = int(m.group(1))

    m = re.search(r"Successfully ingested (\d+) new listings", output)
    if m:
        stats["east_bay_listings"] = int(m.group(1))

    m = re.search(r"Successfully ingested (\d+) new Cleveland listings", output)
    if m:
        stats["cleveland_listings"] = int(m.group(1))

    return stats


def _parse_audit_output(output: str) -> dict:
    """Extract key stats from audit_ingest output."""
    stats = {
        "emails_audited": 0,
        "recovered": 0,
        "needs_review": 0,
    }
    m = re.search(r"Large-scale audit: (\d+) emails", output)
    if m:
        stats["emails_audited"] = int(m.group(1))

    m = re.search(r"New listings recovered via visual: (\d+)", output)
    if m:
        stats["recovered"] = int(m.group(1))

    m = re.search(r"Flagged but no genuine miss \(needs_review\): (\d+)", output)
    if m:
        stats["needs_review"] = int(m.group(1))

    return stats


def _get_new_listings(since_ts: str) -> list:
    """Fetch newly ingested listings since timestamp for email body."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT address, city, neighborhood, price, beds, baths, house_sqft
            FROM listings
            WHERE received_at > ?
            ORDER BY received_at DESC
            LIMIT 20
        """, (since_ts,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _get_cleveland_new_listings(since_ts: str) -> list:
    """Fetch newly ingested Cleveland listings since timestamp."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT address, price, beds, baths, house_sqft,
                   distance_to_clinic_miles, distance_to_cwru_miles
            FROM cleveland_listings
            WHERE received_at > ?
            ORDER BY received_at DESC
            LIMIT 20
        """, (since_ts,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _build_email_html(
    refresh_stats: dict,
    audit_stats: dict,
    new_listings: list,
    cleveland_listings: list,
    since_ts: str,
    refresh_ok: bool,
    audit_ok: bool,
) -> str:
    """Build HTML email body."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status = "✅ Success" if (refresh_ok and audit_ok) else "⚠️ Partial failure"

    rows_html = ""
    for l in new_listings:
        price = f"${l['price']:,}" if l.get("price") else "—"
        sqft = f"{l['house_sqft']:,}" if l.get("house_sqft") else "—"
        beds = l.get("beds") or "—"
        baths = l.get("baths") or "—"
        neighborhood = l.get("neighborhood") or "—"
        rows_html += (
            f"<tr><td>{l['address']}</td><td>{l.get('city','')}</td>"
            f"<td>{neighborhood}</td>"
            f"<td>{price}</td><td>{beds}bd/{baths}ba</td><td>{sqft}</td></tr>"
        )

    clev_rows_html = ""
    for l in cleveland_listings:
        price = f"${l['price']:,}" if l.get("price") else "—"
        sqft = f"{l['house_sqft']:,}" if l.get("house_sqft") else "—"
        beds = l.get("beds") or "—"
        baths = l.get("baths") or "—"
        clinic = f"{l['distance_to_clinic_miles']}mi" if l.get("distance_to_clinic_miles") else "—"
        cwru = f"{l['distance_to_cwru_miles']}mi" if l.get("distance_to_cwru_miles") else "—"
        clev_rows_html += (
            f"<tr><td>{l['address']}</td><td>{price}</td>"
            f"<td>{beds}bd/{baths}ba</td><td>{sqft}</td>"
            f"<td>{clinic}</td><td>{cwru}</td></tr>"
        )

    cleveland_section = ""
    if clev_rows_html:
        cleveland_section = f"""
        <h3 style="color:#2c5282;">🏙️ Cleveland University Circle</h3>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:13px;">
          <tr style="background:#ebf8ff;">
            <th>Address</th><th>Price</th><th>Beds/Baths</th>
            <th>Sqft</th><th>→ Clinic</th><th>→ CWRU</th>
          </tr>
          {clev_rows_html}
        </table>
        """
    elif refresh_stats.get("cleveland_listings", 0) == 0:
        cleveland_section = "<p style='color:#718096;'>No new Cleveland listings today.</p>"

    listings_section = ""
    if rows_html:
        listings_section = f"""
        <h3 style="color:#2c5282;">🏠 East Bay New Listings</h3>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:13px;">
          <tr style="background:#f0fff4;">
            <th>Address</th><th>City</th><th>Neighborhood</th><th>Price</th><th>Beds/Baths</th><th>Sqft</th>
          </tr>
          {rows_html}
        </table>
        """
    else:
        listings_section = "<p style='color:#718096;'>No new East Bay listings today.</p>"

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:20px;">
      <h2 style="color:#1a365d;">Daily Listings Refresh — {now}</h2>
      <p style="font-size:16px;">{status}</p>

      <table style="width:100%;margin-bottom:20px;font-size:14px;">
        <tr>
          <td><b>East Bay emails fetched:</b></td><td>{refresh_stats['east_bay_emails']}</td>
          <td><b>New East Bay listings:</b></td><td>{refresh_stats['east_bay_listings']}</td>
        </tr>
        <tr>
          <td><b>Emails audited:</b></td><td>{audit_stats['emails_audited']}</td>
          <td><b>Recovered by visual:</b></td><td>{audit_stats['recovered']}</td>
        </tr>
        <tr>
          <td><b>New Cleveland listings:</b></td><td>{refresh_stats['cleveland_listings']}</td>
          <td></td><td></td>
        </tr>
      </table>

      {listings_section}
      {cleveland_section}

      <p style="color:#a0aec0;font-size:11px;margin-top:30px;">
        Automated daily refresh · Since {since_ts[:10]}
      </p>
    </body></html>
    """


def _send_email(subject: str, html_body: str):
    """Send email via SMTP with app password (never expires)."""
    import smtplib

    msg = MIMEMultipart("alternative")
    msg["To"] = RECIPIENT
    msg["From"] = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not app_password:
        raise ValueError("GMAIL_APP_PASSWORD not set in environment")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(RECIPIENT, app_password)
        server.send_message(msg)


def _send_error_email(error_title: str, error_details: str, remedy: str):
    """Send error report email with remediation steps."""
    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:20px;">
      <h2 style="color:#c53030;">❌ Listings Refresh Error — {error_title}</h2>
      <p style="font-size:16px;color:#742a2a;background:#fed7d7;padding:10px;border-radius:5px;">
        <b>Error:</b> {error_details}
      </p>
      <p><b>How to fix:</b></p>
      <pre style="background:#f5f5f5;padding:10px;border-radius:5px;overflow:auto;">{remedy}</pre>
      <p style="color:#a0aec0;font-size:11px;margin-top:30px;">
        Automated daily refresh · {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
      </p>
    </body></html>
    """
    _send_email(f"🚨 Listings Refresh Error: {error_title}", html)


def _run_refresh_pipeline(since_ts):
    """Execute refresh_db and audit_ingest. Raises exception on failure."""
    import time
    python = sys.executable

    # Step 1: refresh_db
    print("Step 1: Running refresh_db.py...")
    rc1, out1 = _run_script([python, "-u", "refresh_db.py"])
    refresh_ok = rc1 == 0
    print(out1)
    refresh_stats = _parse_refresh_output(out1)

    # Step 2: audit_ingest
    print("Step 2: Running audit_ingest.py...")
    rc2, out2 = _run_script([python, "-u", "audit_ingest.py", "--since", since_ts])
    audit_ok = rc2 == 0
    print(out2)
    audit_stats = _parse_audit_output(out2)

    # Step 3: prepare email data
    print("Step 3: Preparing summary email...")
    new_listings = _get_new_listings(since_ts)
    cleveland_listings = _get_cleveland_new_listings(since_ts)

    # Use actual listing counts from database, not parsed output
    refresh_stats["east_bay_listings"] = len(new_listings)
    refresh_stats["cleveland_listings"] = len(cleveland_listings)

    # Check for silent failures
    if "Fetched" in out1 and "Cleveland" in out1:
        # Check if Cleveland emails were fetched but produced zero listings
        if "Fetched" in out1 and refresh_stats["cleveland_listings"] == 0:
            # Check if this looks like an anomaly (emails were fetched but nothing ingested)
            if "Fetched" in out1 and "No new Cleveland listings found" in out1:
                # This might be OK if there are genuinely no Cleveland listings
                # But we should check if iCloud credentials are working
                if "iCloud fetch failed" in out1 or "LOGIN command error" in out1:
                    _send_error_email(
                        "iCloud Authentication Failed",
                        "Cleveland ingest failed to connect to iCloud IMAP.",
                        "Fix: Verify iCloud app password in ~/.zshrc\n"
                        "  export ICLOUD_APP_PASSWORD='your-app-password'\n"
                        "  Then run: source ~/.zshrc"
                    )
                    print(f"  ✓ Error email sent to {RECIPIENT}")

    if not (refresh_ok and audit_ok):
        raise Exception(f"Pipeline failed: refresh_ok={refresh_ok}, audit_ok={audit_ok}")

    return refresh_ok, audit_ok, refresh_stats, audit_stats, new_listings, cleveland_listings, out1, out2


def main():
    """Run daily refresh pipeline with exponential backoff retries."""
    _load_env()

    print(f"=== Daily Refresh — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    # Outer try-except to guarantee email and logging even on fatal errors
    refresh_ok = False
    audit_ok = False
    refresh_stats = {}
    audit_stats = {}
    new_listings = []
    cleveland_listings = []
    since_ts = None
    exception_occurred = None
    out1 = ""
    out2 = ""
    all_retries_failed = False

    try:
        import time
        since_ts_raw = _get_last_timestamp()
        # Subtract 1 hour to catch emails whose received_at is slightly before the
        # stored checkpoint (e.g. clock skew or batch of emails arriving mid-sync).
        # already_audited in audit_ingest prevents double-processing.
        try:
            since_dt = datetime.fromisoformat(since_ts_raw) - timedelta(hours=1)
            since_ts = since_dt.isoformat()
        except Exception:
            since_ts = since_ts_raw

        # Run with exponential backoff retries (2 retries after primary failure)
        max_attempts = 3
        backoff_seconds = [0, 2, 4]  # Primary (no wait), retry 1 (2s), retry 2 (4s)

        for attempt in range(max_attempts):
            try:
                if attempt > 0:
                    wait_time = backoff_seconds[attempt]
                    print(f"\n⏳ Attempt {attempt + 1}/{max_attempts} — waiting {wait_time}s before retry...\n")
                    time.sleep(wait_time)

                print(f"📋 Attempt {attempt + 1}/{max_attempts}")
                refresh_ok, audit_ok, refresh_stats, audit_stats, new_listings, cleveland_listings, out1, out2 = _run_refresh_pipeline(since_ts)
                break  # Success, exit retry loop
            except Exception as e:
                print(f"  ❌ Attempt {attempt + 1} failed: {e}")
                if attempt == max_attempts - 1:
                    # All retries exhausted
                    all_retries_failed = True
                    raise
                # Otherwise continue to next retry

    except Exception as e:
        exception_occurred = e
        print(f"  ⚠ Unexpected error during job execution: {e}")
        import traceback
        traceback.print_exc()

    # Send emails (with deduplication for redundant jobs)
    try:
        if exception_occurred:
            # Always send error emails (no deduplication, errors need immediate attention)
            import traceback
            tb_str = traceback.format_exc()
            if all_retries_failed:
                subject = "❌ All 3 Retry Attempts Failed — Listings Refresh"
                body = (
                    "The listings refresh pipeline failed on all 3 retry attempts:\n"
                    f"  • Attempt 1: Failed immediately\n"
                    f"  • Attempt 2: Failed after 2s wait\n"
                    f"  • Attempt 3: Failed after 4s wait\n\n"
                    f"Error: {str(exception_occurred)}\n\n"
                    f"Last pipeline output:\n"
                    f"{'='*60}\n"
                    f"{out1}\n{out2}\n"
                    f"{'='*60}\n\n"
                    f"Stack trace:\n{tb_str}\n\n"
                    f"Action: Next scheduled run at the next hour (09:00 or 11:00) will retry.\n"
                    f"If still failing, check:\n"
                    f"  1. iCloud IMAP credentials in ~/.zshrc\n"
                    f"  2. Gmail API token validity\n"
                    f"  3. Database connection and permissions\n"
                    f"  4. Disk space on machine"
                )
            else:
                subject = "Job Execution Error"
                body = f"Unexpected error: {str(exception_occurred)}\n\nOutput:\n{out1}\n{out2}\n\nStack trace:\n{tb_str}"
            _send_error_email(subject, body, "" if all_retries_failed else tb_str)
            print(f"  ✓ Error email sent to {RECIPIENT}")
        elif not _already_ran_today():
            # Send normal status email only once per day (deduplication for redundant jobs at 07:00, 09:00, 11:00)
            total = refresh_stats.get("east_bay_listings", 0) + refresh_stats.get("cleveland_listings", 0)
            # Use the most recent listing date (not the run date)
            all_listings = new_listings + cleveland_listings
            if all_listings:
                listing_dates = [l.get("received_at") for l in all_listings if l.get("received_at")]
                if listing_dates:
                    latest_date = max(listing_dates)
                    listing_date_str = datetime.fromisoformat(latest_date).strftime('%b %-d')
                else:
                    listing_date_str = datetime.now().strftime('%b %-d')
            else:
                listing_date_str = datetime.now().strftime('%b %-d')
            subject = f"Listings Refresh: {total} new listing{'s' if total != 1 else ''} — {listing_date_str}"

            html = _build_email_html(
                refresh_stats, audit_stats,
                new_listings, cleveland_listings,
                since_ts or "1970-01-01", refresh_ok, audit_ok,
            )
            _send_email(subject, html)
            print(f"  ✓ Summary email sent to {RECIPIENT}")
        else:
            print(f"  ℹ Refresh already ran today — skipping duplicate email")
    except Exception as e:
        print(f"  ⚠ Failed to send status email: {e}")
        import traceback
        traceback.print_exc()

    # ALWAYS write to run log (so timeout_monitor can detect completion)
    try:
        rc = 0 if (refresh_ok and audit_ok and not exception_occurred) else 1
        status = "✓ OK" if rc == 0 else "⚠ PARTIAL FAILURE"
        if exception_occurred:
            status = "❌ ERROR"
        _write_run_log("listings-refresh", status)
    except Exception as e:
        print(f"  ⚠ Failed to write run log: {e}")

    # Try to push DB backups and code to git
    try:
        import subprocess as _sp
        # Add listings DB backup
        _sp.run(
            ["/usr/bin/git", "add", "listings/listings.db", "listings/database.db"],
            cwd="/Users/gautambiswas/Claude Code/real-estate", check=True
        )
        # Add NYT recipe DB and code (from parent directory)
        _sp.run(
            ["/usr/bin/git", "add", "../nyt/nyt.db", "../nyt/nyt_recipe_ingest.py", "../nyt/nyt_digest.py"],
            cwd="/Users/gautambiswas/Claude Code/real-estate", check=True
        )
        _sp.run(
            ["/usr/bin/git", "commit", "-m", f"chore: DB backup and code updates {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
            cwd="/Users/gautambiswas/Claude Code/real-estate", check=True
        )
        # Pull before push to avoid conflicts
        _sp.run(
            ["/usr/bin/git", "pull", "origin", "main", "--rebase"],
            cwd="/Users/gautambiswas/Claude Code/real-estate", check=False
        )
        _sp.run(
            ["/usr/bin/git", "push", "origin", "main"],
            cwd="/Users/gautambiswas/Claude Code/real-estate", check=True
        )
        print("  ✓ Listings & recipe DBs + code pushed to git")
    except Exception as e:
        print(f"  ⚠ Git push failed: {e}")

    return rc if not exception_occurred else 1


if __name__ == "__main__":
    sys.exit(main())
