"""Shared iCloud IMAP email fetcher. Returns normalized email dicts compatible with both pipelines."""

import base64
import email
import hashlib
import imaplib
import re
from datetime import datetime, timezone
from email.header import decode_header as _decode_header
from typing import Optional

import os

IMAP_HOST = "imap.mail.me.com"
IMAP_PORT = 993
ICLOUD_EMAIL = os.environ.get("ICLOUD_EMAIL", "gautambiswas2004@icloud.com")
ICLOUD_APP_PASSWORD = os.environ.get("ICLOUD_APP_PASSWORD", "")


def _decode_str(raw) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw or ""


def _decode_header_value(value: str) -> str:
    parts = _decode_header(value or "")
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _extract_body(msg: email.message.Message) -> tuple[str, str]:
    """Return (plain_body, html_body) from a parsed email.message.Message."""
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cte = part.get("Content-Transfer-Encoding", "").lower()
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if ct == "text/plain" and not plain:
                plain = text
            elif ct == "text/html" and not html:
                html = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html = text
            else:
                plain = text
    return plain, html


def _stable_id(msg_id_header: str, subject: str) -> str:
    """Generate a stable unique ID from Message-ID header."""
    key = (msg_id_header or subject or "").encode()
    return hashlib.sha1(key).hexdigest()


def extract_original_from(plain_body: str) -> str:
    """Extract the original sender from a forwarded email's plain-text body.

    Gmail's forwarded message format:
        ---------- Forwarded message ---------
        From: Sender Name <sender@example.com>

    Returns the From line value, or empty string if not found.
    """
    match = re.search(
        r"[-]{5,}\s*Forwarded message\s*[-]{5,}.*?^From:\s*(.+)$",
        plain_body,
        re.MULTILINE | re.IGNORECASE | re.DOTALL,
    )
    if match:
        # Extract the first line after "From:" (may include name + address)
        from_block = match.group(1)
        return from_block.split("\n")[0].strip()
    return ""


def connect() -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(ICLOUD_EMAIL, ICLOUD_APP_PASSWORD)
    return mail


def fetch_emails(
    sender_filter: str,
    since_date: Optional[str] = None,
    max_results: int = 500,
    folder: str = "INBOX",
) -> list[dict]:
    """
    Fetch emails from iCloud IMAP matching sender and optional date filter.

    Args:
        sender_filter: Partial sender address to match (e.g. 'redfin.com').
        since_date:    ISO date string 'YYYY-MM-DD' or None for all.
        max_results:   Maximum number of emails to return.
        folder:        IMAP folder to search.

    Returns:
        List of normalized email dicts with keys:
            id, subject, from, received_at, html_body, plain_body
    """
    mail = connect()
    mail.select(folder)

    # Build IMAP search criteria
    criteria = ["ALL"]
    if since_date:
        try:
            dt = datetime.fromisoformat(since_date)
            imap_date = dt.strftime("%d-%b-%Y")
            criteria = [f'SINCE "{imap_date}"']
        except Exception:
            pass

    _, data = mail.search(None, *criteria)
    ids = data[0].split()
    if not ids:
        mail.logout()
        return []

    results = []
    for imap_id in reversed(ids):  # newest first
        if len(results) >= max_results:
            break
        _, msg_data = mail.fetch(imap_id, "(BODY[])")
        if not msg_data or not isinstance(msg_data[0], tuple):
            continue
        raw = msg_data[0][1]
        if not isinstance(raw, bytes):
            continue
        msg = email.message_from_bytes(raw)

        frm = _decode_header_value(msg.get("From", ""))
        subj = _decode_header_value(msg.get("Subject", ""))
        filter_lc = sender_filter.lower()
        brand = filter_lc.split(".")[0]  # "redfin", "zillow", "nytimes"

        plain_body, html_body = _extract_body(msg)
        orig_from = extract_original_from(plain_body)

        def _matches() -> bool:
            if not filter_lc:
                return True
            # Direct From header match
            if filter_lc in frm.lower():
                return True
            # Explicit forwarded/original headers
            for hdr in ("X-Original-From", "X-Forwarded-From", "Reply-To"):
                if filter_lc in _decode_header_value(msg.get(hdr, "")).lower():
                    return True
            # Original From extracted from forwarded message body (most reliable for Gmail fwds)
            if orig_from and filter_lc in orig_from.lower():
                return True
            # Subject contains brand (e.g. "Fwd: Redfin update") — only if no orig_from found
            if not orig_from and brand in subj.lower():
                return True
            # Last resort: body scan — only if no orig_from was extracted
            if not orig_from and filter_lc in (plain_body + html_body)[:10000].lower():
                return True
            return False

        if not _matches():
            continue

        msg_id_header = msg.get("Message-ID", "")
        stable_id = _stable_id(msg_id_header, subj)

        # Parse date
        date_str = msg.get("Date", "")
        try:
            from email.utils import parsedate_to_datetime
            received_at = parsedate_to_datetime(date_str).astimezone(timezone.utc).isoformat()
        except Exception:
            received_at = datetime.now(timezone.utc).isoformat()

        results.append({
            "id": stable_id,
            "subject": subj,
            "from": frm,
            "original_from": orig_from,
            "received_at": received_at,
            "html_body": html_body,
            "plain_body": plain_body,
        })

    mail.logout()
    return results


def fetch_email_by_subject_date(subject: str, received_at: str, folder: str = "INBOX") -> Optional[dict]:
    """Fetch a specific email by subject and date for audit/re-processing.

    Args:
        subject: Email subject line to match
        received_at: ISO 8601 timestamp of when email was received
        folder: IMAP folder to search

    Returns:
        Email dict with keys: subject, from, received_at, html_body, plain_body
        Or None if not found
    """
    try:
        mail = connect()
        mail.select(folder)

        # Parse the received_at date to get the date for IMAP search
        try:
            dt = datetime.fromisoformat(received_at)
            imap_date = dt.strftime("%d-%b-%Y")
            # Search for emails on that date with matching subject
            _, data = mail.search(None, f'SINCE "{imap_date}"', f'BEFORE "{dt.strftime("%d-%b-%Y")}"', f'SUBJECT "{subject}"')
        except Exception:
            # Fallback: just search by subject
            _, data = mail.search(None, f'SUBJECT "{subject}"')

        if not data or not data[0]:
            mail.logout()
            return None

        ids = data[0].split()
        if not ids:
            mail.logout()
            return None

        # Return the most recent match
        for imap_id in reversed(ids):
            _, msg_data = mail.fetch(imap_id, "(BODY[])")
            if not msg_data or not isinstance(msg_data[0], tuple):
                continue

            raw = msg_data[0][1]
            if not isinstance(raw, bytes):
                continue

            msg = email.message_from_bytes(raw)
            frm = _decode_header_value(msg.get("From", ""))
            subj = _decode_header_value(msg.get("Subject", ""))
            plain_body, html_body = _extract_body(msg)

            date_str = msg.get("Date", "")
            try:
                from email.utils import parsedate_to_datetime
                email_received_at = parsedate_to_datetime(date_str).astimezone(timezone.utc).isoformat()
            except Exception:
                email_received_at = received_at

            mail.logout()
            return {
                "subject": subj,
                "from": frm,
                "received_at": email_received_at,
                "html_body": html_body,
                "plain_body": plain_body,
            }

        mail.logout()
        return None
    except Exception as e:
        print(f"Error fetching email by subject/date: {e}")
        return None
