#!/usr/bin/env python3
"""
Daily NYT digest — fetches top 5 articles from selected sections
and sends an HTML email summary.
"""
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Dict, Optional

import requests

# Add parent directory to path so imports work from any location
sys.path.insert(0, str(Path(__file__).parent.parent / "real-estate"))

RECIPIENT = "gautambiswas2004@icloud.com"
RUN_LOG = Path.home() / "Claude Code" / ".run_log"


def _write_run_log(name: str, status: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(RUN_LOG, "a") as f:
        f.write(f"{ts}  {name:<30}  {status}\n")


def _already_sent_today() -> bool:
    """Check if digest was already sent today (deduplication for redundant jobs)."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(RUN_LOG, "r") as f:
            for line in f:
                if today in line and "nyt-digest" in line and "✓ OK" in line:
                    return True
    except FileNotFoundError:
        pass
    return False

# Sections to fetch — maps display name to API endpoint
SECTIONS = {
    "Most Popular":  ("popular", "https://api.nytimes.com/svc/mostpopular/v2/viewed/1.json"),
    "Well":          ("top",     "https://api.nytimes.com/svc/topstories/v2/well.json"),
    "Business":      ("top",     "https://api.nytimes.com/svc/topstories/v2/business.json"),
    "Health":        ("top",     "https://api.nytimes.com/svc/topstories/v2/health.json"),
    "Science":       ("top",     "https://api.nytimes.com/svc/topstories/v2/science.json"),
    "Technology":    ("top",     "https://api.nytimes.com/svc/topstories/v2/technology.json"),
    "Upshot":        ("top",     "https://api.nytimes.com/svc/topstories/v2/upshot.json"),
}

TOP_N = 5


def _load_env():
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


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse NYT date strings to datetime."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str[:25])  # handles 2026-04-08T09:00:00-04:00
    except ValueError:
        pass
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        pass
    return None


def _fetch_section(api_type: str, url: str, api_key: str, name: str = "") -> List[Dict]:
    """Fetch top articles for a section.

    Most Popular: returns top N by popularity rank (no date filter — rank is the signal).
    Other sections: filtered to last 48h, falling back to most recent if sparse.
    """
    label = f"[{name}] " if name else ""
    try:
        for attempt in range(3):
            resp = requests.get(url, params={"api-key": api_key}, timeout=10)
            if resp.status_code == 429:
                wait = 12 * (attempt + 1)
                print(f"  ⏳ {label}Rate limited (429), retrying in {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            print(f"  ⚠ {label}Rate limit exceeded after 3 retries")
            return []
        data = resp.json()
        results = data.get("results", [])

        def _to_article(item):
            pub_date_str = item.get("published_date") or item.get("updated", "")
            return {
                "title":    item.get("title", ""),
                "abstract": item.get("abstract", ""),
                "url":      item.get("url", ""),
                "byline":   item.get("byline", ""),
                "date":     pub_date_str[:10] if pub_date_str else "",
                "_pub_date": _parse_date(pub_date_str),
            }

        all_articles = [_to_article(item) for item in results]

        # Most Popular: trust the rank, skip date filter
        if api_type == "popular":
            return [{k: v for k, v in a.items() if k != "_pub_date"}
                    for a in all_articles[:TOP_N]]

        # Other sections: prefer articles from last 48h
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=48)
        recent = [
            a for a in all_articles
            if a["_pub_date"] is None or
               a["_pub_date"].replace(tzinfo=None) >= cutoff.replace(tzinfo=None)
        ]
        pool = recent if recent else all_articles
        return [{k: v for k, v in a.items() if k != "_pub_date"}
                for a in pool[:TOP_N]]

    except Exception as e:
        print(f"  ⚠ {label}Failed to fetch {url}: {e}")
        return []


def _section_html(name: str, articles: List[Dict]) -> str:
    """Render one section as HTML."""
    color_map = {
        "Most Popular": "#c05621",
        "Well":         "#276749",
        "Business":     "#2c5282",
        "Health":       "#6b46c1",
        "Technology":   "#1e40af",
        "Upshot":       "#2d3748",
    }
    color = color_map.get(name, "#2d3748")

    if not articles:
        return f"""
        <div style="margin-bottom:28px;">
          <h2 style="color:{color};border-bottom:2px solid {color};padding-bottom:4px;font-family:Georgia,serif;">{name}</h2>
          <p style="color:#718096;font-size:13px;">No articles available.</p>
        </div>"""

    items_html = ""
    for i, a in enumerate(articles, 1):
        title = a.get("title", "")
        abstract = a.get("abstract", "")
        url = a.get("url", "#")
        byline = a.get("byline", "")
        date = a.get("date", "")
        meta_parts = [p for p in [byline, date] if p]
        meta_html = f'<div style="color:#718096;font-size:11px;margin-top:2px;">{" · ".join(meta_parts)}</div>' if meta_parts else ""

        items_html += f"""
        <div style="margin-bottom:14px;padding-left:10px;border-left:3px solid {color};">
          <div style="font-size:12px;color:{color};font-weight:bold;margin-bottom:2px;">{i}</div>
          <a href="{url}" style="color:#1a202c;font-size:15px;font-weight:bold;text-decoration:none;font-family:Georgia,serif;">{title}</a>
          {meta_html}
          <div style="color:#4a5568;font-size:13px;margin-top:4px;">{abstract}</div>
        </div>"""

    return f"""
    <div style="margin-bottom:32px;">
      <h2 style="color:{color};border-bottom:2px solid {color};padding-bottom:4px;font-family:Georgia,serif;">{name}</h2>
      {items_html}
    </div>"""


def _build_email_html(sections_data: Dict[str, List[Dict]]) -> str:
    now = datetime.now().strftime("%A, %B %-d, %Y")
    sections_html = "".join(
        _section_html(name, sections_data.get(name, []))
        for name in SECTIONS
    )
    return f"""
    <html>
    <body style="font-family:Arial,sans-serif;max-width:680px;margin:auto;padding:24px;background:#fff;">
      <div style="text-align:center;margin-bottom:28px;">
        <div style="font-size:28px;font-family:Georgia,serif;font-weight:bold;letter-spacing:1px;">
          The New York Times
        </div>
        <div style="color:#718096;font-size:14px;margin-top:4px;">Your Morning Digest · {now}</div>
      </div>
      {sections_html}
      <div style="border-top:1px solid #e2e8f0;margin-top:24px;padding-top:12px;color:#a0aec0;font-size:11px;text-align:center;">
        Top {TOP_N} articles per section · Powered by NYT API
      </div>
    </body>
    </html>"""


def _send_email(subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["To"] = RECIPIENT
    msg["From"] = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    app_password = os.environ.get("ICLOUD_APP_PASSWORD")
    if not app_password:
        raise ValueError("ICLOUD_APP_PASSWORD not set in environment")

    with smtplib.SMTP("smtp.mail.me.com", 587) as server:
        server.starttls()
        server.login(RECIPIENT, app_password)
        server.send_message(msg)


def main():
    _load_env()

    api_key = os.getenv("NYT_API_KEY")
    if not api_key:
        print("Error: NYT_API_KEY not set")
        return 1

    print(f"Fetching NYT digest — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    sections_data = {}
    for name, (api_type, url) in SECTIONS.items():
        print(f"  Fetching {name}...")
        sections_data[name] = _fetch_section(api_type, url, api_key, name)
        time.sleep(0.3)  # be polite to the API

    total = sum(len(v) for v in sections_data.values())
    print(f"  Fetched {total} articles across {len(SECTIONS)} sections")

    # Only send email if not already sent today (deduplication for redundant jobs at 14:00, 16:00, 18:00)
    if not _already_sent_today():
        html = _build_email_html(sections_data)
        subject = f"NYT Morning Digest · {datetime.now().strftime('%b %-d')}"
        _send_email(subject, html)
        print(f"  ✓ Email sent to {RECIPIENT}")
    else:
        print(f"  ℹ Digest already sent today — skipping duplicate email")
    _write_run_log("nyt-digest", "✓ OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
