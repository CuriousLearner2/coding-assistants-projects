"""
Cleveland, OH listing ingest — University Circle neighborhood only.

Fetches Redfin alert emails for Cleveland, OH, filters to University Circle,
geocodes each listing, and calculates driving distance to Cleveland Clinic
and Case Western Reserve University via Google Maps API.
"""
import json
import os
import re
import sqlite3
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import googlemaps

from listings.gmail_ingest import (
    fetch_emails_by_query,
    get_full_email,
)
from listings.utils import get_anthropic_client
from listings.batch_ingest import (
    _normalize_email,
    _needs_claude,
    _build_batch_requests,
    _submit_and_poll_batch,
    _parse_batch_results,
    _coerce_property_types,
)
from listings.db import get_sync_state, set_sync_state

# Landmark addresses for driving distance
CLEVELAND_CLINIC_ADDR = "9500 Euclid Ave, Cleveland, OH 44195"
CWRU_ADDR = "10900 Euclid Ave, Cleveland, OH 44106"

# Only ingest listings in these neighborhoods (case-insensitive)
ALLOWED_NEIGHBORHOODS = {"university circle"}

# Only ingest listings in Cleveland, OH
ALLOWED_CITIES = {"cleveland"}


def _init_gmaps() -> Optional[googlemaps.Client]:
    """Initialize Google Maps client from env."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("  Warning: GOOGLE_MAPS_API_KEY not set — skipping distance calculation")
        return None
    return googlemaps.Client(key=api_key)


def _geocode_address(gmaps: googlemaps.Client, address: str) -> Optional[Tuple[float, float]]:
    """Geocode address string, return (lat, lng) or None."""
    try:
        results = gmaps.geocode(address)
        if results:
            loc = results[0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"  Geocode error for '{address}': {e}")
    return None


def _driving_distance_miles(
    gmaps: googlemaps.Client,
    origin: str,
    destination: str,
) -> Optional[float]:
    """Return driving distance in miles between origin and destination."""
    try:
        result = gmaps.distance_matrix(
            origins=[origin],
            destinations=[destination],
            mode="driving",
            units="imperial",
        )
        element = result["rows"][0]["elements"][0]
        if element["status"] == "OK":
            meters = element["distance"]["value"]
            return round(meters / 1609.344, 2)
    except Exception as e:
        print(f"  Distance error {origin} → {destination}: {e}")
    return None


def _fetch_cleveland_emails(service, last_ts: str) -> List[Dict]:
    """Fetch Redfin emails mentioning Cleveland, OH since last_ts from both Gmail and iCloud."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    import icloud_imap

    emails = []

    # Fetch from iCloud IMAP
    try:
        since_date = None
        if last_ts and last_ts != "0":
            try:
                since_date = datetime.fromisoformat(last_ts).strftime("%Y-%m-%d")
            except Exception:
                pass

        icloud_emails = icloud_imap.fetch_emails("redfin.com", since_date=since_date)
        for email in icloud_emails:
            # Filter for Cleveland mentions
            subject = (email.get("subject") or "").lower()
            body = ((email.get("plain_body") or "") + (email.get("html_body") or "")).lower()
            if "cleveland" in (subject + body) and "oh" in (subject + body):
                normalized = _normalize_email({
                    "subject": email.get("subject"),
                    "from": email.get("from"),
                    "received_at": email.get("received_at"),
                    "html_body": email.get("html_body"),
                    "plain_body": email.get("plain_body"),
                    "id": email.get("id"),
                    "source": "Redfin"
                })
                emails.append(normalized)
    except Exception as e:
        print(f"  ⚠ iCloud fetch failed: {e}")

    # Also fetch from Gmail for redundancy
    try:
        query = 'from:listings@redfin.com "Cleveland" "OH"'
        msgs = fetch_emails_by_query(service, query, last_ts)
        for msg_info in msgs:
            email = get_full_email(service, msg_info["id"])
            if email:
                email["source"] = "Redfin"
                emails.append(_normalize_email(email))
    except Exception as e:
        print(f"  ⚠ Gmail fetch failed: {e}")

    return emails


def _try_regex_parse_cleveland(email: Dict) -> List[Dict]:
    """Attempt regex extraction of Cleveland listings from Redfin email."""
    from listings.gmail_ingest import extract_properties_from_batch_email, parse_listing_email

    html_body = email.get("html_body", "")
    subject = email.get("subject", "")

    # Price decrease/change emails need Claude (different format than new listings)
    if any(phrase in subject.lower() for phrase in ["price", "decrease", "drop", "reduced"]):
        return []

    props = extract_properties_from_batch_email(html_body, subject)
    if props:
        return props

    result = parse_listing_email(
        email.get("plain_body", ""),
        html_body,
        email.get("received_at"),
        subject,
    )
    return [result] if result else []


def _call_claude_direct_cleveland(client, emails_needing_claude: Dict[str, Dict]) -> Dict[str, List[Dict]]:
    """Call Claude Haiku directly for Cleveland email extraction.

    Retries up to 4 times with exponential backoff (1s→2s→4s→8s) on transient
    errors (500, 429, connection errors, timeouts).
    """
    import anthropic as _anthropic
    import json, re, time as _time
    results = {}

    _TRANSIENT = (
        _anthropic.InternalServerError,
        _anthropic.RateLimitError,
        _anthropic.APIConnectionError,
        _anthropic.APITimeoutError,
    )

    for gmail_id, email in emails_needing_claude.items():
        body = (email.get("html_body") or email.get("plain_body", ""))[:32000]
        prompt = (
            "Extract all property listings from this Redfin email for Cleveland, OH.\n"
            "Return a JSON array. Each element must have:\n"
            "  address, city, state, price (int, sale price only), beds (float), "
            "baths (float), house_sqft (int), lot_size_sqft (int), hoa_monthly (int), "
            "garage_spots (int), redfin_url, neighborhood\n\n"
            "Rules:\n"
            "- Return [] if no listings found\n"
            "- Use list/sale price only, NOT price reductions\n"
            "- All numeric fields must be numbers, not strings\n"
            "- Return ONLY valid JSON array, no markdown\n"
            "- Optional/missing fields can be null\n\n"
            f"Email:\n{body}"
        )

        for attempt in range(4):
            try:
                resp = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = resp.content[0].text
                content = re.sub(r'^```(?:json)?\n', '', content, flags=re.MULTILINE)
                content = re.sub(r'\n```$', '', content, flags=re.MULTILINE)
                json_match = re.search(r'\[.*?\]|\{.*?\}', content, re.DOTALL)
                if not json_match:
                    results[gmail_id] = []
                    break
                data = json.loads(json_match.group(0))
                if isinstance(data, dict):
                    data = [data]
                elif not isinstance(data, list):
                    data = []
                results[gmail_id] = data
                break
            except _TRANSIENT as e:
                if attempt < 3:
                    wait = 2 ** attempt
                    print(f"  Transient error for {gmail_id} (attempt {attempt + 1}), retrying in {wait}s: {e}")
                    _time.sleep(wait)
                else:
                    print(f"  ⚠ Claude failed for {gmail_id} after 4 attempts")
                    results[gmail_id] = []
            except Exception as e:
                print(f"  ⚠ Claude failed for {gmail_id} (non-retryable): {e}")
                results[gmail_id] = []
                break

    return results


def _build_cleveland_batch_requests(emails_needing_claude: Dict[str, Dict]) -> List[Dict]:
    """Build Haiku batch requests specifically for Cleveland listing extraction."""
    requests = []
    for gmail_id, email in emails_needing_claude.items():
        body = (email.get("html_body") or email.get("plain_body", ""))[:32000]
        prompt = (
            "Extract all property listings from this Redfin email for Cleveland, OH.\n"
            "Return a JSON array. Each element must have:\n"
            "  address, city, state, price (int, sale price only), beds (float), "
            "baths (float), house_sqft (int), lot_size_sqft (int), hoa_monthly (int), "
            "garage_spots (int), redfin_url, neighborhood\n\n"
            "Rules:\n"
            "- Return [] if no listings found\n"
            "- Use list/sale price only, NOT price reductions\n"
            "- All numeric fields must be numbers, not strings\n"
            "- Return ONLY valid JSON array, no markdown\n"
            "- Optional/missing fields can be null\n\n"
            f"Email:\n{body}"
        )
        requests.append({
            "custom_id": gmail_id,
            "params": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
        })
    return requests


def _is_valid_address(address: str) -> bool:
    """Sanity check: reject obviously invalid addresses like 'Random Rd' or street names alone.

    Valid addresses should have a house number at the start, e.g. '1234 Main St' or '100 Oak Ave'.
    Rejects patterns like 'Random Rd' (no number) or obviously incomplete addresses.
    """
    if not address:
        return False
    # Must start with a number (house number)
    first_token = address.split()[0]
    if not first_token.isdigit():
        return False
    # Address should be at least 3 tokens (number, street, type) and <= 10 tokens
    tokens = address.split()
    if len(tokens) < 3 or len(tokens) > 10:
        return False
    return True


def _is_university_circle(prop: Dict) -> bool:
    """Return True if property is in University Circle, Cleveland OH."""
    address = (prop.get("address") or "").strip()

    # Sanity check: reject obviously invalid addresses
    if not _is_valid_address(address):
        return False

    neighborhood = (prop.get("neighborhood") or "").strip().lower()
    # Accept if neighborhood is University Circle (email already Cleveland-filtered)
    if neighborhood in ALLOWED_NEIGHBORHOODS:
        return True
    # Otherwise require explicit Cleveland city
    city = (prop.get("city") or "").strip().lower()
    return city == "cleveland" and neighborhood in ALLOWED_NEIGHBORHOODS


def _upsert_cleveland_listing(conn: sqlite3.Connection, listing: Dict) -> None:
    """Insert or update a Cleveland listing."""
    fields = [
        "id", "gmail_message_id", "subject", "received_at",
        "address", "price", "beds", "baths", "house_sqft",
        "lot_size_sqft", "hoa_monthly", "garage_spots", "redfin_url",
        "neighborhood", "city", "state", "zip_code",
        "latitude", "longitude", "geocoded_at", "source",
        "distance_to_clinic_miles", "distance_to_cwru_miles",
        "updated_at",
    ]
    values = [listing.get(f) for f in fields[:-1]] + [datetime.utcnow().isoformat()]
    placeholders = ", ".join("?" * len(fields))
    updates = ", ".join(f"{f} = excluded.{f}" for f in fields if f != "id")
    conn.execute(
        f"INSERT INTO cleveland_listings ({', '.join(fields)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def _already_ingested(conn: sqlite3.Connection, gmail_id: str, address: str) -> bool:
    """True if this address is already in the cleveland_listings table."""
    row = conn.execute(
        "SELECT id FROM cleveland_listings WHERE address = ?", (address,)
    ).fetchone()
    return row is not None


def run_cleveland_ingest(conn: sqlite3.Connection, service) -> int:
    """
    Orchestrate Cleveland University Circle ingest pipeline.

    Args:
        conn: SQLite connection
        service: Gmail API service

    Returns:
        Number of new listings ingested.
    """
    last_ts = get_sync_state(conn, "last_cleveland_email_timestamp") or "0"
    print(f"Fetching Cleveland emails since {last_ts}...")

    all_emails = _fetch_cleveland_emails(service, last_ts)
    if not all_emails:
        print("  No new Cleveland emails found")
        return 0

    print(f"  Fetched {len(all_emails)} Cleveland emails")

    # Regex parse pass
    regex_results: Dict[str, List[Dict]] = {}
    emails_needing_claude: Dict[str, Dict] = {}

    for email in all_emails:
        gmail_id = email["id"]
        try:
            props = _try_regex_parse_cleveland(email)
        except Exception as e:
            print(f"  ⚠ Regex parse failed for {gmail_id}: {e} — falling back to Claude")
            props = []
        if _needs_claude(props):
            emails_needing_claude[gmail_id] = email
        else:
            regex_results[gmail_id] = props

    # Warn on possible format change
    if len(all_emails) >= 3 and len(emails_needing_claude) / len(all_emails) > 0.7:
        print(f"  ⚠ Format change warning: {len(emails_needing_claude)}/{len(all_emails)} "
              f"Cleveland emails failed regex — email format may have changed")

    # Call Claude directly for emails that need it
    claude_results: Dict[str, List[Dict]] = {}
    if emails_needing_claude:
        print(f"  Calling Claude for {len(emails_needing_claude)} emails...")
        try:
            client = get_anthropic_client()
            claude_results = _call_claude_direct_cleveland(client, emails_needing_claude)
        except Exception as e:
            print(f"  ⚠ Claude failed: {e} — proceeding with regex-only results")

    # Geocoding + distance client
    gmaps = _init_gmaps()

    # Merge and upsert
    email_by_id = {e["id"]: e for e in all_emails}
    count = 0

    for gmail_id, email in email_by_id.items():
        props = claude_results.get(gmail_id) or regex_results.get(gmail_id, [])

        for prop in props:
            try:
                _coerce_property_types(prop)

                # Filter to University Circle, Cleveland only
                if not _is_university_circle(prop):
                    continue

                address = prop.get("address")
                if not address:
                    continue

                # Address-level dedup
                if _already_ingested(conn, gmail_id, address):
                    continue

                # Geocode
                lat, lng = None, None
                geocoded_at = None
                full_address = f"{address}, Cleveland, OH"
                if gmaps:
                    coords = _geocode_address(gmaps, full_address)
                    if coords:
                        lat, lng = coords
                        geocoded_at = datetime.utcnow().isoformat()

                # Driving distances
                dist_clinic = None
                dist_cwru = None
                if gmaps and lat is not None:
                    dist_clinic = _driving_distance_miles(gmaps, full_address, CLEVELAND_CLINIC_ADDR)
                    dist_cwru = _driving_distance_miles(gmaps, full_address, CWRU_ADDR)

                listing_id = f"{gmail_id}_{address.replace(' ', '_').replace(',', '')[:20]}"
                listing = {
                    "id": listing_id,
                    "gmail_message_id": gmail_id,
                    "subject": email.get("subject", ""),
                    "received_at": email.get("received_at"),
                    "source": email.get("source", "Redfin"),
                    "latitude": lat,
                    "longitude": lng,
                    "geocoded_at": geocoded_at,
                    "distance_to_clinic_miles": dist_clinic,
                    "distance_to_cwru_miles": dist_cwru,
                    **prop,
                }

                _upsert_cleveland_listing(conn, listing)
                count += 1

                clinic_str = f" | Clinic: {dist_clinic}mi" if dist_clinic else ""
                cwru_str = f" | CWRU: {dist_cwru}mi" if dist_cwru else ""
                price_str = f"(${prop.get('price'):,})" if prop.get("price") else ""
                print(f"  + {address}, Cleveland {price_str}{clinic_str}{cwru_str}")

            except Exception as e:
                print(f"  ⚠ Skipped property in {gmail_id}: {e}")

    # Update sync timestamp
    if all_emails:
        max_ts = max(e["received_at"] for e in all_emails)
        set_sync_state(conn, "last_cleveland_email_timestamp", max_ts)

    return count
