"""
Three-phase extraction audit: BS4 count vs visual count, with automated recovery.

Phase 1 — Count check (every email): render full email, ask Claude for card count.
Phase 2 — Address list (flagged only): ask Claude for all in-geo addresses.
Phase 3 — Full extraction (missed cards only): crop + ingest missed listings.
"""

import base64
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

PROJECT_DIR = Path("/Users/gautambiswas/Claude Code/real-estate")
DB_PATH = PROJECT_DIR / "listings" / "listings.db"
sys.path.insert(0, str(PROJECT_DIR))


# ─── DB helpers ──────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_bs4_listings_for_email(conn, email_id: str) -> List[Dict]:
    rows = conn.execute(
        "SELECT address, price, beds, baths FROM listings WHERE gmail_message_id = ?",
        (email_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def address_in_db(conn, address: str) -> bool:
    """Check if a normalized address exists anywhere in DB."""
    norm = norm_address(address)
    if not norm:
        return False
    rows = conn.execute("SELECT address FROM listings").fetchall()
    for r in rows:
        if norm_address(r["address"] or "").startswith(norm[:12]) or \
           norm.startswith(norm_address(r["address"] or "")[:12]):
            return True
    return False


def insert_audit_row(conn, row: Dict) -> int:
    cur = conn.execute("""
        INSERT INTO extraction_audit
            (email_id, subject, source, checked_at, bs4_count, visual_count,
             bs4_addresses, visual_addresses, missed_addresses, status, resolution_note)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        row["email_id"], row.get("subject"), row.get("source"),
        datetime.now(timezone.utc).isoformat(),
        row.get("bs4_count"), row.get("visual_count"),
        json.dumps(row.get("bs4_addresses", [])),
        json.dumps(row.get("visual_addresses")) if row.get("visual_addresses") is not None else None,
        json.dumps(row.get("missed_addresses")) if row.get("missed_addresses") is not None else None,
        row.get("status", "pending"),
        row.get("resolution_note"),
    ))
    conn.commit()
    return cur.lastrowid


def update_audit_row(conn, row_id: int, updates: Dict):
    fields = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [row_id]
    conn.execute(f"UPDATE extraction_audit SET {fields} WHERE id = ?", values)
    conn.commit()


# ─── Normalization ────────────────────────────────────────────────────────────

def norm_address(addr: Optional[str]) -> str:
    if not addr:
        return ""
    # Strip unit/apt suffix for matching
    addr = re.sub(r'\s+(APT|UNIT|#)\s*\S+', '', addr, flags=re.IGNORECASE)
    return re.sub(r'[^A-Z0-9 ]', '', addr.upper().strip())


def addresses_match(a: str, b: str) -> bool:
    na, nb = norm_address(a), norm_address(b)
    if not na or not nb:
        return False
    # Prefix match on first 12 chars to handle minor truncation differences
    return na[:14] == nb[:14]


# ─── Image helpers ───────────────────────────────────────────────────────────

def render_full_email(html_body: str, tmpdir: str, email_id: str) -> Optional[str]:
    """Render full email as a single PNG resized to 400px wide."""
    from playwright.sync_api import sync_playwright
    from PIL import Image

    path = f"{tmpdir}/{email_id}_full.png"
    resized = f"{tmpdir}/{email_id}_full_400.png"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 1200})
        page.set_content(html_body, wait_until="networkidle")
        page.screenshot(path=path, full_page=True)
        browser.close()

    img = Image.open(path)
    w, h = img.size
    new_w = 400
    new_h = int(h * new_w / w)
    img.resized = img.resize((new_w, new_h), Image.LANCZOS)
    img.resized.save(resized)
    return resized


def image_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


# ─── Claude vision calls ─────────────────────────────────────────────────────

def _call_with_retry(client, **kwargs) -> object:
    """Call client.messages.create with exponential backoff on overload."""
    for attempt in range(3):
        try:
            return client.messages.create(**kwargs)
        except Exception as e:
            if "overloaded" in str(e).lower() and attempt < 2:
                wait = 5 * (2 ** attempt)
                print(f"    API overloaded, retrying in {wait}s (attempt {attempt+1}/3)...")
                time.sleep(wait)
            else:
                raise


def visual_count(client, image_path: str) -> Optional[int]:
    """Phase 1: ask Claude for card count from full-page image."""
    b64 = image_to_b64(image_path)
    resp = _call_with_retry(
        client,
        model="claude-haiku-4-5-20251001",
        max_tokens=32,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": (
                    "How many distinct property listing cards are visible in this email image? "
                    "Count only cards that show a specific property (address, price, beds/baths). "
                    "Return only a JSON integer, nothing else."
                )}
            ]
        }]
    )
    text = resp.content[0].text.strip()
    try:
        return int(re.search(r'\d+', text).group())
    except Exception:
        return None


def html_addresses(client, html_body: str) -> List[str]:
    """Phase 2: extract in-geo addresses from HTML email body (text, no OCR)."""
    from bs4 import BeautifulSoup as _BS
    soup = _BS(html_body, 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    text = soup.get_text(separator='\n', strip=True)[:8000]

    resp = _call_with_retry(
        client,
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": (
                "List every distinct property listing address in this email text. "
                "Only include addresses in Berkeley CA, Oakland CA, Albany CA, or El Cerrito CA."
                "Return only a JSON array of street address strings (no city/state), "
                'e.g. ["123 Main St", "456 Oak Ave"]. '
                "Return [] if none found. Nothing else.\n\n"
                f"{text}"
            )
        }]
    )
    text = resp.content[0].text.strip()
    text = re.sub(r'^```(?:json)?\n?', '', text)
    text = re.sub(r'\n?```$', '', text)
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except Exception:
        m = re.search(r'\[.*?\]', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return []


def visual_extract_card(client, card_image_path: str) -> Optional[Dict]:
    """Phase 3: full field extraction from a cropped card image."""
    b64 = image_to_b64(card_image_path)
    resp = _call_with_retry(
        client,
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": (
                    "Extract the property listing data from this card image. "
                    "Return only valid JSON:\n"
                    '{"address": "street only", "city": "city", "state": "CA", '
                    '"price": 0, "beds": 0, "baths": 0, "house_sqft": 0, '
                    '"lot_size_sqft": null, "garage_spots": null}\n'
                    "Use null for missing fields. price/sqft as integers, beds/baths as floats. "
                    "Return null if this is not a property listing card."
                )}
            ]
        }]
    )
    text = resp.content[0].text.strip()
    if text.lower() == "null":
        return None
    text = re.sub(r'^```(?:json)?\n?', '', text)
    text = re.sub(r'\n?```$', '', text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


# ─── Card cropping for Phase 3 ───────────────────────────────────────────────

STREET_SUFFIXES = {
    'AVE', 'ST', 'DR', 'RD', 'BLVD', 'LN', 'CT', 'WAY', 'PKWY',
    'CIR', 'PL', 'TER', 'HWY', 'STREET', 'AVENUE', 'ROAD', 'DRIVE',
    'LANE', 'COURT', 'PLACE', 'TERRACE', 'VE', 'WY'
}


def street_tokens(address: str) -> List[str]:
    """
    Extract unique street name tokens — strip house number and common suffixes.
    e.g. '1004 Craigmont Ave' -> ['CRAIGMONT']
    Requires tokens >= 4 chars to avoid noise matching.
    """
    words = re.sub(r'[^A-Z0-9 ]', '', address.upper()).split()
    # Drop leading house number
    if words and words[0].isdigit():
        words = words[1:]
    # Keep only substantive tokens (not suffixes, not very short)
    return [w for w in words if len(w) >= 4 and w not in STREET_SUFFIXES]


def card_matches_address(card_text: str, address: str) -> bool:
    """
    Fuzzy match: check if card_text contains enough street tokens from address.
    Handles OCR errors (Craigmont vs Cragmont) by requiring 2+ token matches
    on a 5-char prefix.
    """
    tokens = street_tokens(address)
    if not tokens:
        return False
    card_upper = card_text.upper()
    matched = sum(1 for t in tokens if t[:5] in card_upper)
    # Need majority of tokens to match
    return matched >= max(1, len(tokens) // 2)


def crop_cards_for_addresses(
    html_body: str, tmpdir: str, email_id: str, missed_addresses: List[str]
) -> List[tuple]:
    """
    Crop only the card elements that contain a missed address.

    Instead of extracting every card in the email (expensive), this finds
    only the cards whose text matches one of the missed addresses and crops
    those. For a Zillow email with 9 cards and 1 missed address this saves
    ~8 unnecessary Phase 3 vision calls.

    Args:
        html_body: Raw HTML of the email.
        tmpdir: Directory to write cropped images into.
        email_id: Gmail message ID (used in filenames).
        missed_addresses: Normalized address strings from Phase 2 that were
            not found in the BS4 results or the DB.

    Returns:
        List of (resized_image_path, matched_address) tuples — one entry per
        missed address that was located in a card. Addresses with no matching
        card are silently skipped (will remain in still_missed).
    """
    from playwright.sync_api import sync_playwright
    from PIL import Image

    results = []  # (path, address)
    already_cropped: set = set()  # avoid cropping same card for two addresses

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 4000})
        page.set_content(html_body, wait_until="networkidle")

        # Collect candidate card elements (same heuristics as before)
        candidates = []

        # Strategy 1: Redfin bordered <td> cards
        for el in page.query_selector_all("td"):
            try:
                style = el.get_attribute("style") or ""
                if "border: 1px solid #D7D7D7" in style:
                    text = el.inner_text()
                    if re.search(r'\$[\d,]+', text):
                        box = el.bounding_box()
                        if box and box["width"] > 100 and box["height"] > 60:
                            candidates.append((el, text))
            except Exception:
                pass

        # Strategy 2: price-containing td/div elements (Zillow)
        if not candidates:
            for el in page.query_selector_all("td, div"):
                try:
                    text = el.inner_text()
                    if re.search(r'\$[\d,]+', text) and 80 < len(text) < 1500:
                        box = el.bounding_box()
                        if box and box["width"] > 150 and box["height"] > 80:
                            candidates.append((el, text))
                except Exception:
                    pass

        # Match each missed address to the best card
        for addr in missed_addresses:
            best_el = None
            best_idx = None
            for idx, (el, text) in enumerate(candidates):
                if idx in already_cropped:
                    continue
                if card_matches_address(text, addr):
                    best_el = el
                    best_idx = idx
                    break  # take the first match

            if best_el is None:
                continue  # no card found; address stays in still_missed

            slot = len(results)
            raw = f"{tmpdir}/{email_id}_tgt_{slot:02d}.png"
            resized = f"{tmpdir}/{email_id}_tgt_{slot:02d}_r.png"
            try:
                best_el.screenshot(path=raw)
                img = Image.open(raw)
                w, h = img.size
                if w > 600:
                    img = img.resize((600, int(h * 600 / w)), Image.LANCZOS)
                img.save(resized)
                if os.path.getsize(resized) > 500:
                    results.append((resized, addr))
                    already_cropped.add(best_idx)
            except Exception:
                pass

        browser.close()

    return results


# ─── Ingest helper ────────────────────────────────────────────────────────────

def ingest_listing(conn, prop: Dict, email_id: str, subject: str, source: str, received_at: str):
    from listings.gmail_ingest import is_rental_listing, is_allowed_city
    from listings.db import upsert_listing, get_listing_by_address

    if not prop or not prop.get("address"):
        return False
    if is_rental_listing(prop, None):
        return False
    if not is_allowed_city(prop.get("city")):
        return "out_of_area"

    existing = get_listing_by_address(conn, prop["address"])
    if existing:
        prop["id"] = existing["id"]
    else:
        prop["id"] = f"audit_{email_id}_{prop['address'].replace(' ','_')[:20]}"

    listing = {
        "id": prop["id"],
        "gmail_message_id": email_id,
        "subject": subject,
        "received_at": received_at,
        "source": source,
        **prop,
    }
    upsert_listing(conn, listing)
    return True


# ─── Main audit loop ─────────────────────────────────────────────────────────

def run_audit(email_ids: List[str]):
    from listings.utils import get_anthropic_client
    import sys
    sys.path.insert(0, str(Path.cwd().parent))
    import icloud_imap

    conn = get_conn()
    client = get_anthropic_client()

    print(f"\nRunning extraction audit on {len(email_ids)} emails\n{'='*60}")

    # pending_phase3: list of dicts to process in the batch
    #   {audit_row, missed, card_paths, email_meta}
    pending_phase3 = []

    with tempfile.TemporaryDirectory() as tmpdir:

        # ── Pass 1: Phase 1 + Phase 2 for every email ──────────────────────
        for email_id in email_ids:
            print(f"\n── {email_id} ──")

            # Look up email metadata from DB
            row = conn.execute(
                "SELECT subject, received_at FROM listings WHERE gmail_message_id = ? LIMIT 1",
                (email_id,)
            ).fetchone()
            if not row:
                print("  ERROR: email not in database")
                continue

            subject, received_at = row
            email = icloud_imap.fetch_email_by_subject_date(subject, received_at)
            if not email or not email.get("html_body"):
                print("  ERROR: could not fetch email")
                continue

            subject = email.get("subject", "")
            source = "Redfin" if "redfin" in email.get("from", "").lower() else "Zillow"
            received_at = email.get("date", "")
            print(f"  {source}: {subject[:65]}")

            bs4_listings = get_bs4_listings_for_email(conn, email_id)
            bs4_count = len(bs4_listings)
            bs4_addresses = [r["address"] for r in bs4_listings if r.get("address")]
            print(f"  BS4 stored: {bs4_count} — {bs4_addresses}")

            # Phase 2 — address list from HTML text (no rendering needed)
            print("  Phase 2: extracting address list from HTML...")
            v_addresses = html_addresses(client, email["html_body"])
            v_count = len(v_addresses)
            print(f"  Found: {v_addresses}")

            audit_row = {
                "email_id": email_id, "subject": subject, "source": source,
                "bs4_count": bs4_count, "visual_count": v_count,
                "bs4_addresses": bs4_addresses,
            }

            missed, needs_review = [], []
            for va in v_addresses:
                if not va or len(va) < 5:
                    continue
                if any(addresses_match(va, ba) for ba in bs4_addresses):
                    continue
                if address_in_db(conn, va):
                    print(f"    '{va}' → already in DB")
                    continue
                if not re.match(r'^\d+\s+\w+', va.strip()):
                    needs_review.append(va)
                    print(f"    '{va}' → ambiguous, needs review")
                else:
                    missed.append(va)
                    print(f"    '{va}' → MISSED")

            audit_row["visual_addresses"] = v_addresses

            if not missed and not needs_review:
                audit_row["status"] = "resolved"
                audit_row["resolution_note"] = "all visual addresses already in DB"
                audit_row["missed_addresses"] = []
                insert_audit_row(conn, audit_row)
                print("  RESOLVED: no genuinely missed listings")
                continue

            if needs_review and not missed:
                audit_row["status"] = "needs_review"
                audit_row["missed_addresses"] = needs_review
                audit_row["resolution_note"] = "ambiguous addresses"
                insert_audit_row(conn, audit_row)
                print(f"  NEEDS REVIEW: {needs_review}")
                continue

            # Phase 3 prep — crop only cards matching missed addresses
            print(f"  Phase 3 prep: cropping targeted cards...")
            matched = crop_cards_for_addresses(email["html_body"], tmpdir, email_id, missed)
            card_paths = [cp for cp, _ in matched]
            print(f"    {len(card_paths)} cards cropped")

            pending_phase3.append({
                "audit_row": audit_row,
                "missed": missed,
                "needs_review": needs_review,
                "card_paths": card_paths,
                "email_meta": {
                    "email_id": email_id, "subject": subject,
                    "source": source, "received_at": received_at,
                },
            })

        # ── Pass 2: Phase 3 via batch API ──────────────────────────────────
        if not pending_phase3:
            print("\nNo emails need Phase 3.")
        else:
            total_cards = sum(len(p["card_paths"]) for p in pending_phase3)
            print(f"\n{'='*60}")
            print(f"Phase 3: submitting batch for {total_cards} cards "
                  f"across {len(pending_phase3)} flagged emails...")

            # Build work items — {custom_id: (card_path, b64)}
            work_items = {}
            for item in pending_phase3:
                eid = item["email_meta"]["email_id"]
                for i, cp in enumerate(item["card_paths"]):
                    work_items[f"{eid}__{i:03d}"] = cp

            PROMPT_TEXT = (
                "Extract the property listing data from this card image. "
                "Return only valid JSON:\n"
                '{"address": "street only, no city/state", '
                '"city": "city", "state": "CA", '
                '"price": 0, "beds": 0.0, "baths": 0.0, '
                '"house_sqft": 0, "lot_size_sqft": null, '
                '"garage_spots": null}\n'
                "Use null for missing fields. "
                "Return null if not a property listing card."
            )

            def _call_one(cid_path):
                cid, card_path = cid_path
                b64 = image_to_b64(card_path)
                resp = _call_with_retry(
                    client,
                    model="claude-haiku-4-5-20251001",
                    max_tokens=512,
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": "image/png", "data": b64,
                        }},
                        {"type": "text", "text": PROMPT_TEXT},
                    ]}],
                )
                return cid, resp.content[0].text

            print(f"  Calling API directly for {len(work_items)} cards (parallel)...")
            parsed = {}
            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = {pool.submit(_call_one, item): item[0] for item in work_items.items()}
                for fut in as_completed(futures):
                    cid = futures[fut]
                    try:
                        _, text = fut.result()
                        text = re.sub(r'^```(?:json)?\n?', '', text.strip())
                        text = re.sub(r'\n?```$', '', text)
                        if text.strip().lower() == "null":
                            parsed[cid] = None
                        else:
                            prop = json.loads(text)
                            parsed[cid] = prop if isinstance(prop, dict) else None
                    except Exception as e:
                        print(f"  WARNING: card {cid} failed: {e}")
                        parsed[cid] = None
            print(f"  Phase 3 complete: {sum(1 for v in parsed.values() if v)} cards extracted.")

            # Process results per flagged email
            for item in pending_phase3:
                eid = item["email_meta"]["email_id"]
                missed = item["missed"]
                needs_review = item["needs_review"]
                audit_row = item["audit_row"]
                meta = item["email_meta"]

                ingested, still_missed = [], list(missed)

                for i in range(len(item["card_paths"])):
                    cid = f"{eid}__{i:03d}"
                    prop = parsed.get(cid)
                    if not prop or not prop.get("address"):
                        continue

                    extracted_addr = prop["address"]
                    is_missed = any(
                        card_matches_address(extracted_addr, m) or
                        card_matches_address(m, extracted_addr)
                        for m in missed
                    )
                    if not is_missed:
                        continue

                    if address_in_db(conn, extracted_addr):
                        print(f"    '{extracted_addr}' already in DB, skip")
                        # Clear the OCR-corrupted phase-2 address from still_missed
                        still_missed = [
                            m for m in still_missed
                            if not (card_matches_address(extracted_addr, m) or
                                    card_matches_address(m, extracted_addr))
                        ]
                        continue

                    print(f"    Extracted: {extracted_addr} ${prop.get('price')} "
                          f"{prop.get('beds')}bd {prop.get('baths')}ba "
                          f"{prop.get('house_sqft')}sqft")

                    ok = ingest_listing(
                        conn, prop,
                        meta["email_id"], meta["subject"],
                        meta["source"], meta["received_at"],
                    )
                    if ok == "out_of_area":
                        still_missed = [
                            m for m in still_missed
                            if not (card_matches_address(extracted_addr, m) or
                                    card_matches_address(m, extracted_addr))
                        ]
                        print(f"    Filtered (out-of-area): {extracted_addr}")
                    elif ok:
                        ingested.append(extracted_addr)
                        still_missed = [
                            m for m in still_missed
                            if not (card_matches_address(extracted_addr, m) or
                                    card_matches_address(m, extracted_addr))
                        ]
                        print(f"    + Ingested: {extracted_addr}")
                    else:
                        print(f"    Filtered (rental): {extracted_addr}")

                all_unresolved = still_missed + needs_review
                if all_unresolved:
                    audit_row["status"] = "needs_review"
                    audit_row["missed_addresses"] = all_unresolved
                    audit_row["resolution_note"] = (
                        f"ingested {len(ingested)}: {ingested}; "
                        f"unresolved: {all_unresolved}"
                    )
                else:
                    audit_row["status"] = "resolved"
                    audit_row["missed_addresses"] = missed
                    audit_row["resolution_note"] = (
                        f"ingested {len(ingested)} missed listings: {ingested}"
                    )

                insert_audit_row(conn, audit_row)

    # ── Summary ──
    print(f"\n{'='*60}")
    print("AUDIT SUMMARY")
    rows = conn.execute("""
        SELECT email_id, source, bs4_count, visual_count, status, resolution_note
        FROM extraction_audit
        WHERE email_id IN ({})
        ORDER BY rowid DESC
    """.format(",".join("?" * len(email_ids))), email_ids).fetchall()

    for r in rows:
        flag = "✓" if r["status"] == "resolved" else "⚠"
        print(f"  {flag} {r['source']:6} bs4={r['bs4_count']} visual={r['visual_count']} "
              f"[{r['status']}] {(r['resolution_note'] or '')[:70]}")

    conn.close()


# ─── Batch request builders ───────────────────────────────────────────────────

def _b64_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _poll_batch_to_completion(client, batch_id: str) -> List[Dict]:
    """Poll an already-submitted batch until it ends, then return results."""
    import time as _time
    print(f"Resuming poll for batch {batch_id}...")
    max_wait = 7200  # 2 hours max — nightly batches poll every 10 min
    start = _time.time()
    while True:
        if _time.time() - start > max_wait:
            raise TimeoutError(f"Batch {batch_id} still not done after {max_wait}s")
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            print(f"Batch {batch_id} complete: "
                  f"{batch.request_counts.succeeded} succeeded, "
                  f"{batch.request_counts.errored} errored")
            return list(client.messages.batches.results(batch_id))
        print(f"  Batch status: {batch.processing_status} "
              f"({batch.request_counts.processing} processing, "
              f"{batch.request_counts.succeeded} done)")
        _time.sleep(600)  # poll every 10 min — batch runs overnight


def _submit_batch_with_retry(client, requests, max_attempts: int = 4):
    """Submit a batch, retrying on transient network/server errors.
    On TimeoutError, resumes polling the original batch rather than
    re-submitting (avoids wasting tokens on a duplicate batch).
    """
    from listings.batch_ingest import _submit_and_poll_batch
    import re as _re
    for attempt in range(max_attempts):
        try:
            return _submit_and_poll_batch(client, requests)
        except TimeoutError as exc:
            # Extract batch_id from the timeout message and resume polling
            m = _re.search(r"msgbatch_\S+", str(exc))
            if m:
                print(f"  Batch timed out locally; resuming poll for {m.group()}...")
                return _poll_batch_to_completion(client, m.group())
            raise
        except Exception as exc:
            if attempt < max_attempts - 1:
                wait = 30 * (2 ** attempt)
                print(f"  Batch error ({exc}); retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def _build_count_request(email_id: str, img_path: str) -> Dict:
    return {
        "custom_id": email_id,
        "params": {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 16,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png",
                        "data": _b64_image(img_path),
                    }},
                    {"type": "text", "text": (
                        "How many distinct property listing cards are visible in this email? "
                        "Count only cards showing a specific property (address, price, beds/baths). "
                        "Return only a JSON integer."
                    )},
                ],
            }],
        },
    }


def _build_address_request(email_id: str, img_path: str) -> Dict:
    return {
        "custom_id": email_id,
        "params": {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 512,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png",
                        "data": _b64_image(img_path),
                    }},
                    {"type": "text", "text": (
                        "List every distinct property listing address visible in this email. "
                        "Only include addresses in Berkeley CA, Oakland CA, Albany CA, or El Cerrito CA."
                        'Return only a JSON array of street address strings, e.g. ["123 Main St"]. '
                        "Return [] if none. Nothing else."
                    )},
                ],
            }],
        },
    }


def _build_address_request_text(email_id: str, html_body: str) -> Dict:
    """Phase 2 batch request using HTML text extraction instead of image OCR."""
    from bs4 import BeautifulSoup as _BS
    soup = _BS(html_body, 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    text = soup.get_text(separator='\n', strip=True)[:8000]

    return {
        "custom_id": email_id,
        "params": {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 512,
            "messages": [{
                "role": "user",
                "content": (
                    "List every distinct property listing address in this email text. "
                    "Only include addresses in Berkeley CA, Oakland CA, Albany CA, or El Cerrito CA."
                    'Return only a JSON array of street address strings (no city/state), '
                    'e.g. ["123 Main St", "456 Oak Ave"]. '
                    "Return [] if none found. Nothing else.\n\n"
                    f"{text}"
                )
            }],
        },
    }


def _build_card_request(custom_id: str, card_path: str) -> Dict:
    return {
        "custom_id": custom_id,
        "params": {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 512,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png",
                        "data": _b64_image(card_path),
                    }},
                    {"type": "text", "text": (
                        "Extract the property listing from this card. "
                        "Return only valid JSON:\n"
                        '{"address":"street only","city":"city","state":"CA",'
                        '"price":0,"beds":0.0,"baths":0.0,"house_sqft":0,'
                        '"lot_size_sqft":null,"garage_spots":null}\n'
                        "null for missing fields. Return null if not a listing card."
                    )},
                ],
            }],
        },
    }


def _parse_batch_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\n?', '', text)
    text = re.sub(r'\n?```$', '', text)
    return text.strip()


def _extract_batch_text(result) -> Optional[str]:
    result_obj = result.result if hasattr(result, "result") else result.get("result", {})
    result_type = result_obj.type if hasattr(result_obj, "type") else result_obj.get("type")
    if result_type != "succeeded":
        return None
    message = result_obj.message if hasattr(result_obj, "message") else result_obj.get("message", {})
    content_list = message.content if hasattr(message, "content") else message.get("content", [])
    if not content_list:
        return None
    return content_list[0].text if hasattr(content_list[0], "text") else content_list[0].get("text", "")


# ─── Large-scale fully-batched audit ─────────────────────────────────────────

def run_audit_large_scale(since_date: str = "2023-01-01", resume_tmpdir: str = None):
    """
    Fully-batched audit pipeline for all emails since since_date.
    Three batch round trips: Phase 1 (count) → Phase 2 (addresses) → Phase 3 (cards).
    Skips emails already in extraction_audit.

    Args:
        since_date: ISO date string; only emails on/after this date are audited.
        resume_tmpdir: If set, skip rendering and reuse pre-rendered files from
            this directory (use after a crash mid-Phase-3).
    """
    from listings.utils import get_anthropic_client
    import sys
    sys.path.insert(0, str(Path.cwd().parent))
    import icloud_imap

    conn = get_conn()
    client = get_anthropic_client()

    # ── Load email IDs from DB, skip already audited ──────────────────────────
    rows = conn.execute("""
        SELECT DISTINCT gmail_message_id, source, subject, received_at,
               COUNT(*) as bs4_count
        FROM listings
        WHERE received_at >= ?
        GROUP BY gmail_message_id
        ORDER BY received_at ASC
    """, (since_date,)).fetchall()

    already_audited = {
        r[0] for r in conn.execute(
            "SELECT email_id FROM extraction_audit"
        ).fetchall()
    }

    emails_to_audit = [dict(r) for r in rows
                       if r["gmail_message_id"] not in already_audited]

    total = len(emails_to_audit)
    print(f"\nLarge-scale audit: {total} emails since {since_date} "
          f"({len(already_audited)} already audited, skipped)")
    print(f"{'='*60}")

    if not emails_to_audit:
        print("Nothing to do.")
        conn.close()
        return

    # ── Fetch all emails (or reuse existing tmpdir) ───────────────────────────
    email_meta = {}    # email_id → {subject, source, received_at, bs4_count, bs4_addresses}

    if resume_tmpdir:
        tmpdir = resume_tmpdir
        print(f"\nStep 1: Resuming from existing tmpdir {tmpdir}...")
        for row in emails_to_audit:
            eid = row["gmail_message_id"]
            html_path = f"{tmpdir}/{eid}.html"
            if not os.path.exists(html_path):
                continue
            bs4_rows = get_bs4_listings_for_email(conn, eid)
            email_meta[eid] = {
                "subject": row["subject"],
                "source": row["source"],
                "received_at": row["received_at"],
                "bs4_count": row["bs4_count"],
                "bs4_addresses": [r["address"] for r in bs4_rows if r.get("address")],
            }
    else:
        # Use a named temp dir that survives across batch polling waits
        tmpdir = tempfile.mkdtemp(prefix="audit_large_")
        print(f"\nStep 1: Fetching {total} emails (parallel) → {tmpdir}")

        def _fetch_one(row):
            eid = row["gmail_message_id"]
            subject = row["subject"]
            received_at = row["received_at"]
            email = icloud_imap.fetch_email_by_subject_date(subject, received_at)
            return eid, row, email

        fetch_failed = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_fetch_one, row): row for row in emails_to_audit}
            done = 0
            for fut in as_completed(futures):
                eid, row, email = fut.result()
                done += 1
                if done % 50 == 0 or done == total:
                    print(f"  [{done}/{total}] fetched...")
                if not email or not email.get("html_body"):
                    fetch_failed.append((eid, row))
                    continue
                bs4_rows = get_bs4_listings_for_email(conn, eid)
                email_meta[eid] = {
                    "subject": email.get("subject", row["subject"]),
                    "source": row["source"],
                    "received_at": email.get("date", row["received_at"]),
                    "bs4_count": row["bs4_count"],
                    "bs4_addresses": [r["address"] for r in bs4_rows if r.get("address")],
                }
                html_path = f"{tmpdir}/{eid}.html"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(email["html_body"])

        for eid, row in fetch_failed:
            insert_audit_row(conn, {
                "email_id": eid,
                "subject": row["subject"],
                "source": row["source"],
                "bs4_count": row["bs4_count"],
                "visual_count": None,
                "bs4_addresses": [],
                "status": "needs_review",
                "resolution_note": "email fetch failed",
            })

    fetched = list(email_meta.keys())
    print(f"  Fetched: {len(fetched)}  Failed: {total - len(fetched)}")

    # ── Phase 2 — HTML text address extraction (parallel) ────────────────────
    print(f"\nStep 2: Phase 2 — extracting addresses from {len(fetched)} emails (parallel)...")
    phase3_work = []

    def _extract_addresses(eid):
        html_path = f"{tmpdir}/{eid}.html"
        with open(html_path, encoding="utf-8") as f:
            html_body = f.read()
        return eid, html_addresses(client, html_body)

    phase2_results = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_extract_addresses, eid): eid for eid in fetched}
        done = 0
        for fut in as_completed(futures):
            eid, v_addresses = fut.result()
            done += 1
            if done % 50 == 0 or done == len(fetched):
                print(f"  [{done}/{len(fetched)}] extracted...")
            phase2_results[eid] = v_addresses

    for eid in fetched:
        v_addresses = phase2_results.get(eid, [])
        meta = email_meta[eid]
        bs4_addresses = meta["bs4_addresses"]
        v_count = len(v_addresses)
        missed, needs_review = [], []

        for va in v_addresses:
            if not va or len(va) < 5:
                continue
            if any(addresses_match(va, ba) for ba in bs4_addresses):
                continue
            if address_in_db(conn, va):
                continue
            if not re.match(r'^\d+\s+\w+', va.strip()):
                needs_review.append(va)
            else:
                missed.append(va)

        if not missed and not needs_review:
            insert_audit_row(conn, {
                "email_id": eid,
                "subject": meta["subject"],
                "source": meta["source"],
                "bs4_count": meta["bs4_count"],
                "visual_count": v_count,
                "bs4_addresses": bs4_addresses,
                "visual_addresses": v_addresses,
                "missed_addresses": [],
                "status": "resolved",
                "resolution_note": "all visual addresses already in DB",
            })
            continue

        phase3_work.append({
            "eid": eid,
            "v_addresses": v_addresses,
            "missed": missed,
            "needs_review": needs_review,
        })

    emails_with_missed = [w for w in phase3_work if w["missed"]]
    emails_no_missed = [w for w in phase3_work if not w["missed"]]

    print(f"  Confirmed missed listings in: {len(emails_with_missed)} emails")
    print(f"  Flagged but no genuine miss (needs_review): {len(emails_no_missed)} emails")

    # Resolve flagged emails with no genuine missed listings
    for w in emails_no_missed:
        eid = w["eid"]
        meta = email_meta[eid]
        insert_audit_row(conn, {
            "email_id": eid,
            "subject": meta["subject"],
            "source": meta["source"],
            "bs4_count": meta["bs4_count"],
            "visual_count": len(w["v_addresses"]),
            "bs4_addresses": meta["bs4_addresses"],
            "visual_addresses": w["v_addresses"],
            "missed_addresses": w["needs_review"] or [],
            "status": "needs_review" if w["needs_review"] else "resolved",
            "resolution_note": (
                f"ambiguous: {w['needs_review']}"
                if w["needs_review"]
                else "all visual addresses already in DB"
            ),
        })

    if not emails_with_missed:
        print("No genuine missed listings found. Audit complete.")
        _print_large_scale_summary(conn, since_date)
        conn.close()
        return

    # ── Batch 3: Phase 3 — crop only matched cards, extract missed listings ──────
    total_missed = sum(len(w["missed"]) for w in emails_with_missed)
    print(f"\nStep 4: Cropping targeted cards for {total_missed} missed addresses "
          f"across {len(emails_with_missed)} emails...")

    # Crop only the card(s) matching each missed address (not all cards)
    card_index = {}   # custom_id → {eid, matched_address}
    p3_requests = []

    for w in emails_with_missed:
        eid = w["eid"]
        html_path = f"{tmpdir}/{eid}.html"
        if not os.path.exists(html_path):
            continue
        with open(html_path, encoding="utf-8") as f:
            html_body = f.read()

        matched = crop_cards_for_addresses(html_body, tmpdir, eid, w["missed"])
        for cp, addr in matched:
            cid = f"{eid}__{len(p3_requests):04d}"
            card_index[cid] = {"eid": eid, "missed": [addr]}
            p3_requests.append(_build_card_request(cid, cp))

    print(f"  Total card requests: {len(p3_requests)}")
    print(f"\nStep 5: Phase 3 — extracting {len(p3_requests)} cards (parallel direct API)...")

    def _call_card_request(req):
        cid = req["custom_id"]
        params = req["params"]
        resp = _call_with_retry(client, **params)
        return cid, resp.content[0].text

    card_props = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_call_card_request, req): req["custom_id"] for req in p3_requests}
        for fut in as_completed(futures):
            cid = futures[fut]
            try:
                _, text = fut.result()
                text = _parse_batch_text(text)
                if text.lower() == "null":
                    card_props[cid] = None
                else:
                    try:
                        prop = json.loads(text)
                        card_props[cid] = prop if isinstance(prop, dict) else None
                    except Exception:
                        try:
                            m = re.search(r'\{.*?\}', text, re.DOTALL)
                            card_props[cid] = json.loads(m.group(0)) if m else None
                        except Exception:
                            card_props[cid] = None
            except Exception as e:
                print(f"  WARNING: card {cid} failed: {e}")
                card_props[cid] = None
    print(f"  Phase 3 complete: {sum(1 for v in card_props.values() if v)} cards extracted.")

    # Process per email — ingest missed, write audit rows
    print(f"\nStep 6: Ingesting recovered listings...")
    for w in emails_with_missed:
        eid = w["eid"]
        meta = email_meta[eid]
        missed = w["missed"]
        ingested, still_missed = [], list(missed)

        for cid, info in card_index.items():
            if info["eid"] != eid:
                continue
            prop = card_props.get(cid)
            if not prop or not prop.get("address"):
                continue

            extracted_addr = prop["address"]
            is_missed = any(
                card_matches_address(extracted_addr, m) or
                card_matches_address(m, extracted_addr)
                for m in missed
            )
            if not is_missed:
                continue

            if address_in_db(conn, extracted_addr):
                still_missed = [
                    m for m in still_missed
                    if not (card_matches_address(extracted_addr, m) or
                            card_matches_address(m, extracted_addr))
                ]
                continue

            ok = ingest_listing(
                conn, prop, eid,
                meta["subject"], meta["source"], meta["received_at"],
            )
            if ok == "out_of_area":
                # Card extracted successfully but filtered — not a genuine miss
                still_missed = [
                    m for m in still_missed
                    if not (card_matches_address(extracted_addr, m) or
                            card_matches_address(m, extracted_addr))
                ]
            elif ok:
                ingested.append(extracted_addr)
                still_missed = [
                    m for m in still_missed
                    if not (card_matches_address(extracted_addr, m) or
                            card_matches_address(m, extracted_addr))
                ]
                print(f"  + {extracted_addr}  (${prop.get('price'):,})"
                      if prop.get("price") else f"  + {extracted_addr}")

        all_unresolved = still_missed + w["needs_review"]
        insert_audit_row(conn, {
            "email_id": eid,
            "subject": meta["subject"],
            "source": meta["source"],
            "bs4_count": meta["bs4_count"],
            "visual_count": len(w["v_addresses"]),
            "bs4_addresses": meta["bs4_addresses"],
            "visual_addresses": w["v_addresses"],
            "missed_addresses": all_unresolved if all_unresolved else missed,
            "status": "needs_review" if all_unresolved else "resolved",
            "resolution_note": (
                f"ingested {len(ingested)}: {ingested}; unresolved: {all_unresolved}"
                if all_unresolved
                else f"ingested {len(ingested)} missed listings: {ingested}"
            ),
        })

    # Cleanup temp dir
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    # Phase 4: hi-res re-audit for any emails still in needs_review
    nr_count = conn.execute(
        "SELECT COUNT(*) FROM extraction_audit WHERE status = 'needs_review'"
    ).fetchone()[0]
    if nr_count > 0:
        print(f"\nPhase 4: hi-res re-audit for {nr_count} needs_review emails...")
        conn.close()
        for src in ("Redfin", "Zillow"):
            reaudit_needs_review_hires(source_filter=src)
        conn = get_conn()
    else:
        conn.close()
        conn = get_conn()

    _print_large_scale_summary(conn, since_date)
    conn.close()


def reaudit_needs_review_hires(tmpdir: str = None, source_filter: str = "Redfin"):
    """
    Re-run Phase 2 (addresses) on needs_review emails at 800px resolution.
    If tmpdir is provided and contains pre-rendered _full.png files they are
    reused; otherwise emails are re-fetched from Gmail and rendered fresh.
    Compares 800px results to the original garbled 400px addresses; confirms
    genuine misses and runs targeted Phase 3 card extraction for those.

    Args:
        tmpdir: Optional directory with pre-rendered files. If None or the
            files are absent, emails are re-fetched and rendered.
        source_filter: Only re-audit rows from this source (default: Redfin).
    """
    import shutil
    from playwright.sync_api import sync_playwright
    from PIL import Image
    from listings.utils import get_anthropic_client, get_gmail_service
    from listings.gmail_ingest import get_full_email

    conn = get_conn()
    client = get_anthropic_client()
    service = get_gmail_service()

    rows = conn.execute("""
        SELECT id, email_id, subject, source, bs4_count, bs4_addresses,
               visual_count, missed_addresses
        FROM extraction_audit
        WHERE status = 'needs_review'
          AND source = ?
        ORDER BY id
    """, (source_filter,)).fetchall()

    print(f"\nHi-res re-audit: {len(rows)} {source_filter} needs_review emails")
    print("=" * 60)

    work_tmpdir = tmpdir or tempfile.mkdtemp(prefix="audit_hires_")
    cleanup_tmpdir = tmpdir is None  # only delete if we created it
    print(f"Working in: {work_tmpdir}")

    # Render each email at 800px (reuse existing file if already there)
    hires_img_paths = {}   # email_id → 800px image path
    html_cache = {}        # email_id → html path (for Phase 3)

    for i, row in enumerate(rows, 1):
        eid = row["email_id"]
        hires_800 = f"{work_tmpdir}/{eid}_hires_800.png"
        html_path = f"{work_tmpdir}/{eid}.html"

        if i % 25 == 0 or i == 1 or i == len(rows):
            print(f"  [{i}/{len(rows)}] fetching/rendering...")

        # Reuse if already rendered
        if os.path.exists(hires_800) and os.path.exists(html_path):
            hires_img_paths[eid] = hires_800
            html_cache[eid] = html_path
            continue

        # Fetch from Gmail
        email = get_full_email(service, eid)
        if not email or not email.get("html_body"):
            continue

        html_body = email["html_body"]
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_body)
        html_cache[eid] = html_path

        # Render at 400px viewport with 2x device_scale_factor → 800px effective resolution
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(
                    viewport={"width": 400, "height": 1200},
                    device_scale_factor=2,
                )
                page.set_content(html_body, wait_until="networkidle")
                page.screenshot(path=hires_800, full_page=True)
                browser.close()
            hires_img_paths[eid] = hires_800
        except Exception as e:
            print(f"  Render failed for {eid}: {e}")

    print(f"  Ready: {len(hires_img_paths)} images")

    # Phase 2 batch at 800px
    p2_requests = [
        _build_address_request(eid, path)
        for eid, path in hires_img_paths.items()
    ]
    print(f"\nPhase 2 (hi-res addresses): {len(p2_requests)} requests...")
    if not p2_requests:
        print("  No hi-res renders to process.")
        return
    def _call_p2_request(req):
        eid = req["custom_id"]
        resp = _call_with_retry(client, **req["params"])
        return eid, resp.content[0].text

    p2_raw = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_call_p2_request, req): req["custom_id"] for req in p2_requests}
        for fut in as_completed(futures):
            eid, text = fut.result()
            p2_raw[eid] = text

    # Parse results and find new genuine misses
    row_map = {r["email_id"]: dict(r) for r in rows}
    emails_with_new_misses = []

    for eid in p2_raw:
        text = p2_raw[eid]
        v_addresses = []
        if text:
            text = _parse_batch_text(text)
            try:
                v_addresses = json.loads(text)
                if not isinstance(v_addresses, list):
                    v_addresses = []
            except Exception:
                m = re.search(r'\[.*?\]', text, re.DOTALL)
                if m:
                    try:
                        v_addresses = json.loads(m.group(0))
                    except Exception:
                        pass

        row = row_map.get(eid)
        if not row:
            continue
        bs4_addresses = json.loads(row["bs4_addresses"] or "[]")

        missed, needs_review = [], []
        for va in v_addresses:
            if not va or len(va) < 5:
                continue
            if any(addresses_match(va, ba) for ba in bs4_addresses):
                continue
            if address_in_db(conn, va):
                continue
            if not re.match(r'^\d+\s+\w+', va.strip()):
                needs_review.append(va)
            else:
                missed.append(va)

        old_missed = json.loads(row["missed_addresses"] or "[]")
        print(f"\n{eid[:16]}  bs4={row['bs4_count']} visual={row['visual_count']}")
        print(f"  Old (400px): {old_missed[:4]}{'...' if len(old_missed)>4 else ''}")
        print(f"  New (800px): missed={missed[:4]}{'...' if len(missed)>4 else ''} "
              f"ambiguous={needs_review[:2]}{'...' if len(needs_review)>2 else ''}")

        if missed:
            emails_with_new_misses.append({
                "eid": eid,
                "missed": missed,
                "needs_review": needs_review,
                "v_addresses": v_addresses,
                "row_id": row["id"],
                "meta": {
                    "subject": row["subject"],
                    "source": row["source"],
                    "bs4_count": row["bs4_count"],
                    "bs4_addresses": bs4_addresses,
                    "received_at": None,
                },
            })
        else:
            # No genuine misses at 800px — resolve the row
            new_status = "needs_review" if needs_review else "resolved"
            new_note = (f"800px re-audit: ambiguous {needs_review}"
                        if needs_review else "800px re-audit: no genuine misses (OCR noise confirmed)")
            conn.execute(
                "UPDATE extraction_audit SET status=?, resolution_note=?, "
                "visual_addresses=?, missed_addresses=? WHERE id=?",
                (new_status, new_note,
                 json.dumps(v_addresses),
                 json.dumps(needs_review) if needs_review else "[]",
                 row["id"])
            )
            conn.commit()

    print(f"\n{len(emails_with_new_misses)} emails have genuine misses at 800px")

    if not emails_with_new_misses:
        print("Done — all needs_review were OCR noise at 400px.")
        if cleanup_tmpdir:
            shutil.rmtree(work_tmpdir, ignore_errors=True)
        conn.close()
        return

    # Phase 3: targeted card crop + extraction for confirmed misses
    card_index = {}
    p3_requests = []
    for w in emails_with_new_misses:
        eid = w["eid"]
        html_path = html_cache.get(eid, f"{work_tmpdir}/{eid}.html")
        if not os.path.exists(html_path):
            continue
        with open(html_path, encoding="utf-8") as f:
            html_body = f.read()
        matched = crop_cards_for_addresses(html_body, work_tmpdir, eid, w["missed"])
        for cp, addr in matched:
            cid = f"{eid}__{len(p3_requests):04d}"
            card_index[cid] = {"eid": eid, "missed": [addr]}
            p3_requests.append(_build_card_request(cid, cp))

    print(f"Phase 3: {len(p3_requests)} targeted card requests (parallel direct API)...")
    card_props = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_call_card_request, req): req["custom_id"] for req in p3_requests}
        for fut in as_completed(futures):
            cid = futures[fut]
            try:
                _, text = fut.result()
                text = _parse_batch_text(text)
                if text.lower() == "null":
                    card_props[cid] = None
                else:
                    try:
                        prop = json.loads(text)
                        card_props[cid] = prop if isinstance(prop, dict) else None
                    except Exception:
                        try:
                            m = re.search(r'\{.*?\}', text, re.DOTALL)
                            card_props[cid] = json.loads(m.group(0)) if m else None
                        except Exception:
                            card_props[cid] = None
            except Exception as e:
                print(f"  WARNING: card {cid} failed: {e}")
                card_props[cid] = None

    # Ingest and update audit rows
    total_ingested = 0
    for w in emails_with_new_misses:
        eid = w["eid"]
        meta = w["meta"]
        missed = w["missed"]
        ingested, still_missed = [], list(missed)

        for cid, info in card_index.items():
            if info["eid"] != eid:
                continue
            prop = card_props.get(cid)
            if not prop or not prop.get("address"):
                continue
            extracted_addr = prop["address"]
            is_missed = any(
                card_matches_address(extracted_addr, m) or
                card_matches_address(m, extracted_addr)
                for m in missed
            )
            if not is_missed:
                continue
            if address_in_db(conn, extracted_addr):
                still_missed = [m for m in still_missed
                                if not (card_matches_address(extracted_addr, m) or
                                        card_matches_address(m, extracted_addr))]
                continue

            # Fetch received_at from listings table
            lr = conn.execute(
                "SELECT received_at FROM listings WHERE gmail_message_id=? LIMIT 1", (eid,)
            ).fetchone()
            meta["received_at"] = lr["received_at"] if lr else None

            ok = ingest_listing(conn, prop, eid, meta["subject"], meta["source"], meta["received_at"])
            if ok == "out_of_area":
                still_missed = [m for m in still_missed
                                if not (card_matches_address(extracted_addr, m) or
                                        card_matches_address(m, extracted_addr))]
            elif ok:
                ingested.append(extracted_addr)
                still_missed = [m for m in still_missed
                                if not (card_matches_address(extracted_addr, m) or
                                        card_matches_address(m, extracted_addr))]
                print(f"  + {extracted_addr}  (${prop.get('price'):,})" if prop.get("price")
                      else f"  + {extracted_addr}")
                total_ingested += 1

        all_unresolved = still_missed + w["needs_review"]
        new_status = "needs_review" if all_unresolved else "resolved"
        new_note = (f"800px re-audit ingested {len(ingested)}; unresolved: {all_unresolved}"
                    if all_unresolved
                    else f"800px re-audit ingested {len(ingested)}: {ingested}")
        conn.execute(
            "UPDATE extraction_audit SET status=?, resolution_note=?, "
            "visual_addresses=?, missed_addresses=? WHERE id=?",
            (new_status, new_note,
             json.dumps(w["v_addresses"]),
             json.dumps(all_unresolved) if all_unresolved else "[]",
             w["row_id"])
        )
        conn.commit()

    print(f"\nHi-res re-audit complete. Total new listings ingested: {total_ingested}")
    if cleanup_tmpdir:
        shutil.rmtree(work_tmpdir, ignore_errors=True)
    conn.close()


def _print_large_scale_summary(conn, since_date: str):
    rows = conn.execute("""
        SELECT status, COUNT(*) as n
        FROM extraction_audit
        WHERE checked_at >= ?
        GROUP BY status
    """, (since_date,)).fetchall()

    ingested = conn.execute("""
        SELECT COUNT(*) FROM extraction_audit
        WHERE resolution_note LIKE 'ingested%'
        AND status = 'resolved'
        AND resolution_note NOT LIKE 'ingested 0%'
        AND checked_at >= ?
    """, (since_date,)).fetchone()[0]

    print(f"\n{'='*60}")
    print(f"LARGE-SCALE AUDIT SUMMARY (since {since_date})")
    for r in rows:
        print(f"  {r['status']:15} {r['n']:4} emails")
    print(f"  New listings recovered via visual: {ingested}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default=None,
                        help="Run large-scale audit since YYYY-MM-DD")
    parser.add_argument("--tmpdir", default=None,
                        help="Reuse pre-rendered tmpdir from a crashed run")
    parser.add_argument("--reaudit-hires", action="store_true", default=False,
                        help="Re-run Phase 2 at 800px on Redfin needs_review emails")
    parser.add_argument("--small", action="store_true",
                        help="Run small 6-email test")
    args = parser.parse_args()

    if args.reaudit_hires:
        reaudit_needs_review_hires()
    elif args.since:
        run_audit_large_scale(since_date=args.since, resume_tmpdir=args.tmpdir)
    elif args.small:
        REDFIN_IDS = [
            "19d745d5f5614d8e",  # "A PIEDMONT PINES home for you at $1.3M, and 11 other updates"
            "194f4be385ea58bd",  # "Thousand Oaks Open House: 483 Boynton Ave"
        ]
        ZILLOW_IDS = [
            "19d71e76fd8c4a42",  # "10 Results for 'oakland ca berkeley ca'"
            "19d4e91d11c61448",  # "New Showcase Listing: 2632 Warring St APT 2, Berkeley"
        ]
        run_audit(REDFIN_IDS + ZILLOW_IDS)
    else:
        parser.print_help()
