"""Message Batches API integration for email ingest."""

import json
import re
import sqlite3
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from listings.db import (
    get_sync_state,
    set_sync_state,
    get_listing_by_gmail_id,
    upsert_listing,
    get_listing_by_property,
    get_listing_by_address,
)
from listings.gmail_ingest import (
    fetch_emails_by_query,
    get_full_email,
    extract_properties_from_batch_email,
    parse_listing_email,
    parse_zillow_email,
    is_rental_listing,
    is_allowed_city,
)
from listings.utils import get_anthropic_client


def run_batch_ingest(conn: sqlite3.Connection) -> int:
    """Entry point: orchestrate full batch ingest pipeline."""
    # Phase 1: Fetch Redfin + Zillow emails
    last_ts = get_sync_state(conn, "last_email_timestamp") or "0"
    all_emails = _fetch_all_emails(last_ts)

    if not all_emails:
        print("No new emails found")
        return 0

    print(f"Fetched {len(all_emails)} new emails (Redfin + Zillow)")

    # Phase 2: Try regex parsing on all
    regex_results = {}  # gmail_id -> List[Dict]
    emails_needing_claude = {}  # gmail_id -> raw_email

    for email in all_emails:
        gmail_id = email["id"]
        props = _try_regex_parse(email)

        if _needs_claude(props, email):
            emails_needing_claude[gmail_id] = email
        else:
            regex_results[gmail_id] = props

    # Warn if regex is failing on an unusual proportion of emails (possible format change)
    if len(all_emails) >= 3 and len(emails_needing_claude) / len(all_emails) > 0.7:
        print(f"  ⚠ Format change warning: {len(emails_needing_claude)}/{len(all_emails)} emails "
              f"failed regex and need Claude — Redfin/Zillow email format may have changed")

    # Phase 3-4: Call Claude directly for emails that need it
    claude_results = {}  # gmail_id -> List[Dict]
    if emails_needing_claude:
        print(f"Calling Claude for {len(emails_needing_claude)} emails...")
        try:
            client = get_anthropic_client()
            claude_results = _call_claude_direct(client, emails_needing_claude)
        except Exception as e:
            print(f"  ⚠ Claude failed: {e} — proceeding with regex-only results")

    # Phase 5: Merge and upsert
    count = _merge_and_upsert(
        conn,
        regex_results,
        claude_results,
        all_emails
    )

    # Always advance sync timestamp so failed emails aren't retried forever
    max_ts = max(
        (e["received_at"] for e in all_emails),
        default=last_ts
    )
    set_sync_state(conn, "last_email_timestamp", max_ts)

    return count


def _fetch_all_emails(last_ts: str) -> List[Dict]:
    """Phase 1: Fetch Redfin + Zillow emails from iCloud IMAP, return with source tagging.

    Deduplicates by (received_at, subject, sender) to handle cases where the same email
    appears multiple times with different Message-ID headers (can happen with iCloud IMAP).
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    import icloud_imap

    since_date = None
    if last_ts and last_ts != "0":
        try:
            since_date = datetime.fromisoformat(last_ts).strftime("%Y-%m-%d")
        except Exception:
            pass

    all_emails = []
    seen_ids = set()  # Dedup by Message-ID header
    seen_keys = set()  # Dedup by (received_at, subject, sender) tuple

    def _tag_source(em: dict, default_source: str) -> None:
        """Set source using original_from when available (handles forwarded emails)."""
        orig = em.get("original_from", "").lower()
        if "zillow" in orig:
            em["source"] = "Zillow"
        elif "redfin" in orig:
            em["source"] = "Redfin"
        else:
            em["source"] = default_source

    def _make_dedup_key(em: dict) -> str:
        """Create dedup key from received_at + subject + sender to catch duplicate emails."""
        received = em.get("received_at", "")
        subject = em.get("subject", "").strip()
        sender = em.get("from", "").strip()
        return f"{received}|{subject}|{sender}"

    # Fetch Redfin
    redfin_emails = icloud_imap.fetch_emails("redfin.com", since_date=since_date)
    for em in redfin_emails:
        subject = em.get("subject", "").lower()
        if "cleveland" in subject:
            continue
        _tag_source(em, "Redfin")

        # Deduplicate by both ID and content signature
        email_id = em["id"]
        dedup_key = _make_dedup_key(em)

        if email_id not in seen_ids and dedup_key not in seen_keys:
            seen_ids.add(email_id)
            seen_keys.add(dedup_key)
            all_emails.append(em)

    # Fetch Zillow
    zillow_emails = icloud_imap.fetch_emails("zillow.com", since_date=since_date)
    for em in zillow_emails:
        _tag_source(em, "Zillow")

        # Deduplicate by both ID and content signature
        email_id = em["id"]
        dedup_key = _make_dedup_key(em)

        if email_id not in seen_ids and dedup_key not in seen_keys:
            seen_ids.add(email_id)
            seen_keys.add(dedup_key)
            all_emails.append(em)

    return all_emails


def _normalize_email(email: Dict) -> Dict:
    """Parse date and add received_at timestamp."""
    received_at = email.get("date", "")
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(received_at)
        received_at = dt.isoformat()
    except Exception:
        received_at = datetime.utcnow().isoformat()

    email["received_at"] = received_at
    return email


def _try_regex_parse(email: Dict) -> List[Dict]:
    """Phase 2: Attempt regex parsing based on source.

    Always returns a list (possibly empty). Never raises — any exception means
    the email will fall through to Claude, which handles format changes gracefully.
    """
    source = email.get("source", "")
    gmail_id = email.get("id", "?")

    try:
        if source == "Redfin":
            # Try batch parser first (pass subject for city extraction from neighborhood)
            props = extract_properties_from_batch_email(
                email.get("html_body", ""),
                email.get("subject", "")
            )
            if props:
                return props

            # Fall back to single-property parser
            result = parse_listing_email(
                email.get("plain_body", ""),
                email.get("html_body", ""),
                email.get("received_at"),
                email.get("subject", "")
            )
            return [result] if result else []

        elif source == "Zillow":
            return parse_zillow_email(
                email.get("plain_body", ""),
                email.get("html_body", ""),
                email.get("received_at"),
                email.get("subject", "")
            )

    except Exception as e:
        print(f"  ⚠ Regex parse failed for {gmail_id} ({source}): {e} — falling back to Claude")

    return []


def _needs_claude(props: List[Dict], email: Dict | None = None) -> bool:
    """
    Check if parsed properties need Claude for validation/completion.
    For digest emails, use weaker criteria (< 3 properties found) to trigger Claude.
    """
    # Always need Claude if no results
    if not props:
        return True

    # Check if this is a digest email (from subject line)
    is_digest = False
    if email:
        subject = email.get("subject", "")
        is_digest = bool(re.search(r'\d+\s*Results? for', subject, re.IGNORECASE))

    # For digest emails: trigger Claude if we found very few properties (likely weak extraction)
    # or if any property is missing critical fields
    if is_digest and len(props) < 3:
        return True

    # Standard check: missing address or price
    for prop in props:
        if not prop.get("address") or prop.get("price") is None:
            return True

    return False


def _build_batch_requests(emails_needing_claude: Dict[str, Dict]) -> List[Dict]:
    """Phase 3: Build batch request list for Anthropic API."""
    requests = []

    for gmail_id, email in emails_needing_claude.items():
        source = email.get("source", "")
        # Redfin emails: plain_body is empty HTML scaffolding; use html_body which has all listings.
        # Zillow emails: plain_body is clean and smaller; prefer it.
        if source == "Zillow":
            body = email.get("plain_body") or email.get("html_body", "")
        else:
            body = email.get("html_body") or email.get("plain_body", "")

        # Truncate to 32000 chars to stay within reasonable limits
        body_truncated = body[:32000]

        # Adjust required fields based on source
        if source == "Zillow":
            required_fields = "address, city, state, price (int, sale price only), beds (float), baths (float), house_sqft (int)"
        else:  # Redfin
            required_fields = "address, city, state, price (int, sale price only), beds (float), baths (float), house_sqft (int), lot_size_sqft (int), hoa_monthly (int), garage_spots (int), redfin_url"

        prompt = f"""Extract all property listings from this email. The email is from {source}.
Return a JSON array. Each element must have:
  {required_fields}

Rules:
- Return [] if no listings found
- Use list/sale price only, NOT price reductions or price cuts
- All numeric fields must be numbers, not strings
- Return ONLY valid JSON array, no markdown code fences
- Optional/missing fields can be null

Email (truncated to 32000 chars):
{body_truncated}"""

        requests.append({
            "custom_id": gmail_id,
            "params": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}]
            }
        })

    return requests


def _call_claude_direct(client, emails_needing_claude: Dict[str, Dict]) -> Dict[str, List[Dict]]:
    """Call Claude Haiku directly (non-batch) for each email needing extraction.

    Retries up to 4 times with exponential backoff (1s→2s→4s→8s) on transient
    errors (500, 429, connection errors, timeouts). Non-transient errors (auth,
    bad request) fail immediately. One bad email never blocks the rest.
    """
    import anthropic as _anthropic
    results = {}

    _TRANSIENT = (
        _anthropic.InternalServerError,   # 500
        _anthropic.RateLimitError,         # 429
        _anthropic.APIConnectionError,
        _anthropic.APITimeoutError,
    )

    for gmail_id, email in emails_needing_claude.items():
        source = email.get("source", "")
        if source == "Zillow":
            body = email.get("plain_body") or email.get("html_body", "")
        else:
            body = email.get("html_body") or email.get("plain_body", "")
        body_truncated = body[:32000]

        if source == "Zillow":
            required_fields = ("address, city, state, price (int, sale price only), "
                               "beds (float), baths (float), house_sqft (int)")
        else:
            required_fields = ("address, city, state, price (int, sale price only), "
                               "beds (float), baths (float), house_sqft (int), "
                               "lot_size_sqft (int), hoa_monthly (int), garage_spots (int), redfin_url")

        prompt = (
            f"Extract all property listings from this email. The email is from {source}.\n"
            f"Return a JSON array. Each element must have:\n  {required_fields}\n\n"
            "Rules:\n"
            "- Return [] if no listings found\n"
            "- Use list/sale price only, NOT price reductions or price cuts\n"
            "- All numeric fields must be numbers, not strings\n"
            "- Return ONLY valid JSON array, no markdown code fences\n"
            "- Optional/missing fields can be null\n\n"
            f"Email (truncated to 32000 chars):\n{body_truncated}"
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
                for prop in data:
                    _coerce_property_types(prop)
                results[gmail_id] = data
                break
            except _TRANSIENT as e:
                if attempt < 3:
                    wait = 2 ** attempt  # 1s, 2s, 4s, 8s
                    print(f"  Transient error for {gmail_id} (attempt {attempt + 1}), retrying in {wait}s: {e}")
                    time.sleep(wait)
                else:
                    print(f"  ⚠ Claude failed for {gmail_id} after 4 attempts")
                    results[gmail_id] = []
            except Exception as e:
                print(f"  ⚠ Claude failed for {gmail_id} (non-retryable): {e}")
                results[gmail_id] = []
                break

    return results


def _submit_and_poll_batch(client, requests: List[Dict]) -> List[Dict]:
    """Phase 3-4: Submit batch and poll until complete. Retries on 500 errors."""
    import anthropic as _anthropic

    print(f"Submitting batch with {len(requests)} requests...")

    def _with_retry(fn, label):
        """Call fn(), retrying up to 4 times with exponential backoff on 500 errors."""
        max_retries = 4
        for attempt in range(max_retries):
            try:
                return fn()
            except _anthropic.InternalServerError:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s, 8s
                    print(f"  500 error on {label} (attempt {attempt + 1}), retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise

    batch = _with_retry(
        lambda: client.messages.batches.create(requests=requests),
        "submit"
    )
    batch_id = batch.id
    print(f"Batch {batch_id} submitted, polling for results...")

    start_time = time.time()
    max_wait = 7200  # 2 hours max — nightly batches poll every 10 min

    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait:
            raise TimeoutError(
                f"Batch {batch_id} did not complete within {max_wait}s. "
                f"Results available for 29 days at batch.messages.batches.retrieve('{batch_id}')"
            )

        batch = _with_retry(
            lambda: client.messages.batches.retrieve(batch_id),
            "poll"
        )

        if batch.processing_status == "ended":
            print(f"Batch {batch_id} complete: "
                  f"{batch.request_counts.succeeded} succeeded, "
                  f"{batch.request_counts.errored} errored")
            break

        print(f"  Batch status: {batch.processing_status} "
              f"({batch.request_counts.processing} processing, "
              f"{batch.request_counts.succeeded} done)")
        time.sleep(600)  # poll every 10 min — batch runs overnight

    # Retrieve results
    results = list(client.messages.batches.results(batch_id))
    return results


def _parse_batch_results(
    batch_results: List,
    emails_needing_claude: Dict[str, Dict]
) -> Dict[str, List[Dict]]:
    """Phase 4: Parse batch results and extract properties."""
    claude_results = {}

    for result in batch_results:
        # Handle Pydantic model objects from Anthropic SDK
        gmail_id = result.custom_id if hasattr(result, 'custom_id') else result.get("custom_id")
        email = emails_needing_claude.get(gmail_id)

        result_obj = result.result if hasattr(result, 'result') else result.get("result", {})
        result_type = result_obj.type if hasattr(result_obj, 'type') else result_obj.get("type")

        if result_type == "succeeded":
            try:
                message = result_obj.message if hasattr(result_obj, 'message') else result_obj.get("message", {})
                content_list = message.content if hasattr(message, 'content') else message.get("content", [])
                content_text = content_list[0].text if hasattr(content_list[0], 'text') else content_list[0].get("text", "")

                # Remove markdown code fences if present
                content = re.sub(r'^```(?:json)?\n', '', content_text, flags=re.MULTILINE)
                content = re.sub(r'\n```$', '', content, flags=re.MULTILINE)

                # Extract JSON from response (handles Claude returning text before/after JSON)
                json_match = re.search(r'\[.*?\]|\{.*?\}', content, re.DOTALL)
                if not json_match:
                    raise ValueError("No JSON found in response")

                json_str = json_match.group(0)

                # Parse JSON
                data = json.loads(json_str)

                # Normalize to list
                if isinstance(data, dict):
                    data = [data]
                elif not isinstance(data, list):
                    data = []

                # Coerce types
                for prop in data:
                    _coerce_property_types(prop)

                claude_results[gmail_id] = data

            except (json.JSONDecodeError, KeyError, IndexError, AttributeError) as e:
                print(f"  ⚠ Failed to parse batch result for {gmail_id}: {e}")
                claude_results[gmail_id] = []
        else:
            error_obj = result_obj.error if hasattr(result_obj, 'error') else result_obj.get("error", {})
            error_msg = error_obj.message if hasattr(error_obj, 'message') else error_obj.get("message", "unknown") if isinstance(error_obj, dict) else str(error_obj)
            print(f"  ⚠ Batch error for {gmail_id}: {error_msg}")
            claude_results[gmail_id] = []

    return claude_results


def _coerce_property_types(prop: Dict) -> None:
    """Utility: coerce property dict values to correct types."""
    if "price" in prop and prop["price"] is not None:
        prop["price"] = int(float(prop["price"]))

    if "beds" in prop and prop["beds"] is not None:
        prop["beds"] = float(prop["beds"])

    if "baths" in prop and prop["baths"] is not None:
        prop["baths"] = float(prop["baths"])

    if "house_sqft" in prop and prop["house_sqft"] is not None:
        prop["house_sqft"] = int(float(prop["house_sqft"]))

    if "lot_size_sqft" in prop and prop["lot_size_sqft"] is not None:
        prop["lot_size_sqft"] = int(float(prop["lot_size_sqft"]))

    if "hoa_monthly" in prop and prop["hoa_monthly"] is not None:
        prop["hoa_monthly"] = int(float(prop["hoa_monthly"]))

    if "garage_spots" in prop and prop["garage_spots"] is not None:
        val = int(float(prop["garage_spots"]))
        prop["garage_spots"] = val if 1 <= val <= 10 else None


def _merge_and_upsert(
    conn: sqlite3.Connection,
    regex_results: Dict[str, List[Dict]],
    claude_results: Dict[str, List[Dict]],
    all_emails: List[Dict]
) -> int:
    """Phase 5: Merge regex and Claude results, apply filters, upsert to DB."""

    # Build email lookup by ID
    email_by_id = {e["id"]: e for e in all_emails}

    count = 0

    # Process all emails
    for gmail_id, email in email_by_id.items():
        # Claude takes precedence over regex
        props = claude_results.get(gmail_id) or regex_results.get(gmail_id, [])

        # Skip if already in database
        if get_listing_by_gmail_id(conn, gmail_id):
            continue

        for prop in props:
            try:
                # Apply filters
                if is_rental_listing(prop, prop.get("redfin_url")):
                    continue

                if not is_allowed_city(prop.get("city")):
                    continue

                # Cross-source dedup for Zillow
                source = email.get("source", "")
                address = prop.get("address")

                # Skip properties without an address
                if not address:
                    continue

                # Require minimal set: city, beds, baths, sqft
                if not all([prop.get('beds'), prop.get('baths'), prop.get('house_sqft'), prop.get('city')]):
                    continue

                existing = get_listing_by_address(conn, address)
                if existing:
                    prop["id"] = existing["id"]
                    if existing.get("price") == prop.get("price"):
                        # Same price — only update if new record fills in previously null fields
                        nullable_fields = ("lot_size_sqft", "hoa_monthly", "garage_spots", "zip_code")
                        has_new_data = any(
                            prop.get(f) is not None and existing.get(f) is None
                            for f in nullable_fields
                        )
                        if not has_new_data:
                            continue
                        # Preserve existing non-null values for fields not in new record
                        for f in nullable_fields:
                            if prop.get(f) is None and existing.get(f) is not None:
                                prop[f] = existing[f]
                else:
                    # New address - create new ID
                    prop["id"] = f"{gmail_id}_{address.replace(' ', '_').replace(',', '')[:20]}"

                # When updating an address-matched listing, preserve original gmail_message_id
                # and source to avoid re-processing the original email on future refreshes
                effective_gmail_id = existing["gmail_message_id"] if existing else gmail_id
                effective_source = existing["source"] if existing else source

                # Construct listing with bookkeeping
                listing = {
                    "id": prop["id"],
                    "gmail_message_id": effective_gmail_id,
                    "subject": email.get("subject", ""),
                    "received_at": email.get("received_at"),
                    "source": effective_source,
                    **prop
                }

                upsert_listing(conn, listing)
                count += 1

                price_str = f"(${prop.get('price'):,})" if prop.get('price') else ""
                print(f"  + {address} {price_str}")

            except Exception as e:
                print(f"  ⚠ Skipped property in {gmail_id}: {e}")

    return count
