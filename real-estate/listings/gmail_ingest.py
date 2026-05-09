"""Fetch and parse Redfin listing emails from Gmail."""

import base64
import json
import re
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from listings.db import (
    get_sync_state,
    set_sync_state,
    upsert_listing,
    get_listing_by_gmail_id,
    property_exists,
    get_listing_by_address,
)
from listings.utils import get_gmail_service, get_anthropic_client


def fetch_emails_by_query(service, query: str, since_timestamp: str) -> List[Dict]:
    """Fetch Gmail message ID list for given query since timestamp."""
    if since_timestamp != "0":
        try:
            dt = datetime.fromisoformat(since_timestamp)
            query += f' after:{dt.year}/{dt.month}/{dt.day}'
        except ValueError:
            pass

    messages = []
    page_token = None

    while True:
        try:
            results = service.users().messages().list(
                userId="me",
                q=query,
                pageToken=page_token,
                maxResults=100
            ).execute()

            messages.extend(results.get("messages", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
        except Exception as e:
            print(f"Error fetching Gmail messages: {e}")
            break

    return messages


def fetch_new_listing_emails(service, since_timestamp: str) -> List[Dict]:
    """Fetch Redfin listing emails since timestamp."""
    return fetch_emails_by_query(service, 'from:listings@redfin.com', since_timestamp)


def get_full_email(service, msg_id: str) -> Dict:
    """Get full email with headers and body."""
    try:
        msg = service.users().messages().get(
            userId="me",
            id=msg_id,
            format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}

        # Extract body
        plain_body = ""
        html_body = ""

        def extract_body(parts):
            nonlocal plain_body, html_body
            for part in parts:
                mime = part.get("mimeType", "")
                data = part.get("body", {}).get("data", "")

                if mime == "text/plain" and data:
                    plain_body += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                elif mime == "text/html" and data:
                    html_body += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                elif "parts" in part:
                    extract_body(part["parts"])

        payload = msg["payload"]
        if "parts" in payload:
            extract_body(payload["parts"])
        elif payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                plain_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif payload.get("mimeType") == "text/html":
            data = payload.get("body", {}).get("data", "")
            if data:
                html_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Use internalDate (ms since epoch) for reliable timestamp
        internal_ms = int(msg.get("internalDate", 0))
        if internal_ms:
            from datetime import timezone
            received_at = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc).isoformat()
        else:
            received_at = headers.get("Date", "")

        return {
            "id": msg_id,
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": received_at,
            "plain_body": plain_body,
            "html_body": html_body
        }
    except Exception as e:
        print(f"Error fetching email {msg_id}: {e}")
        return None


def parse_address_components(full_address: str) -> Dict[str, Optional[str]]:
    """
    Parse a full address string into components.
    Input: "123 Main St, Berkeley, CA 94701"
    Output: {'street': '123 Main St', 'city': 'Berkeley', 'state': 'CA', 'zip': '94701'}
    """
    if not full_address:
        return {'street': None, 'city': None, 'state': None, 'zip': None}

    # Pattern: "Number Street Type, City, State Zip"
    pattern = r'^(.*?),\s*([A-Za-z\s]+?),\s*(CA|California)\s*(\d{5})$'
    match = re.match(pattern, full_address.strip())

    if match:
        street = match.group(1).strip()
        city = match.group(2).strip()
        state = "CA"  # Normalize to CA
        zip_code = match.group(4)
        return {
            'street': street,
            'city': city,
            'state': state,
            'zip': zip_code
        }

    # Fallback: if parsing failed, return the full string as street
    return {
        'street': full_address.strip(),
        'city': None,
        'state': None,
        'zip': None
    }


def extract_properties_from_batch_email(html_body: str, subject: Optional[str] = None) -> List[Dict]:
    """
    Extract multiple properties from a batch email using BeautifulSoup.
    Redfin sends batch emails with multiple properties in one message.

    Uses cascade strategy:
    1. CSS class selectors for property cards
    2. Redfin anchor tags with address pattern
    3. Table rows containing price and address

    Args:
        html_body: HTML content of the email
        subject: Email subject line (used to extract city/neighborhood)

    Returns list of dicts with property info.
    """
    if not html_body:
        return []

    properties = []
    soup = BeautifulSoup(html_body, 'html.parser')

    # Decompose noise elements (including <address> which Redfin uses for their office footer)
    for tag in soup.find_all(['script', 'style', 'meta', 'link', 'nav', 'footer', 'noscript', 'address']):
        tag.decompose()

    # Strategy 1: Find cards by CSS class patterns
    cards = soup.select('[class*="property"], [class*="listing"], td.propertyCard')

    # Strategy 1b: Redfin recommendation emails use bordered <td> for each listing card
    if not cards:
        cards = soup.find_all('td', style=lambda s: s and 'border: 1px solid #D7D7D7' in s if s else False)

    # Strategy 2 (Priority): Find table rows with price and address patterns
    # This is more reliable than walking up parent chains
    if not cards:
        for row in soup.find_all('tr'):
            row_text = row.get_text()
            has_price = bool(re.search(r'\$[\d,]+', row_text))
            has_address = bool(re.search(r'\d+\s+[A-Za-z\s]+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pkwy)', row_text, re.IGNORECASE))
            # Also check for CA address pattern
            has_ca_address = bool(re.search(r'(?:CA|California)', row_text, re.IGNORECASE))
            if has_price and has_address and has_ca_address:
                cards.append(row)

    # Strategy 3: If still no cards, find by Redfin anchor tags and walk up to container
    if not cards:
        redfin_links = soup.find_all('a', href=re.compile(r'redfin\.com'))
        for link in redfin_links:
            link_text = link.get_text().strip()
            # Check if link text looks like an address
            if re.match(r'\d+\s+[A-Za-z\s]+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pkwy)', link_text, re.IGNORECASE):
                # Walk up parent chain (up to 3 levels) to find containing element
                parent = link.parent
                for _ in range(3):
                    if parent is None:
                        break
                    if parent.name in ('td', 'tr', 'div', 'section'):
                        cards.append(parent)
                        break
                    parent = parent.parent

    # Extract fields from each card found
    for card in cards:
        fields = _extract_card_fields(card, subject)
        # Only keep results with both address and price
        if fields.get('address') and fields.get('price'):
            # Ensure all expected fields are present (use None for missing)
            properties.append({
                'address': fields.get('address'),
                'city': fields.get('city'),
                'state': fields.get('state'),
                'price': fields.get('price'),
                'beds': fields.get('beds'),
                'baths': fields.get('baths'),
                'house_sqft': fields.get('house_sqft'),
                'lot_size_sqft': fields.get('lot_size_sqft'),
                'hoa_monthly': fields.get('hoa_monthly'),
                'garage_spots': fields.get('garage_spots'),
                'redfin_url': fields.get('redfin_url')
            })

    return properties




def extract_neighborhood_from_subject(subject: str) -> Optional[str]:
    """Extract neighborhood name from email subject line."""
    if not subject:
        return None

    # Clean up subject - remove "update on a/an" or "An/A update on a/an" prefix
    cleaned = re.sub(r'^(?:an?\s+)?update\s+on\s+(?:a|an)\s+', '', subject, flags=re.IGNORECASE).strip()

    # Filter out common non-neighborhood prefixes and adjectives
    excluded = {'new', 'great', 'beautiful', 'perfect', 'ideal', 'wonderful', 'modern', 'lovely', 'stunning', 'spacious', 'charming', 'bed', 'home', 'house', 'property', '3', '2', '4', '5'}

    # Pattern: "A {neighborhood} home for you" or "the {neighborhood} home for you"
    match = re.search(r'(?:A |An |the )?(\w+(?:\s+\w+)*)\s+(?:home|house|property)', cleaned, re.IGNORECASE)
    if match:
        neighborhood = match.group(1).strip()
        if neighborhood.lower() not in excluded:
            return neighborhood

    # Pattern: "Open House: {address}" or "{neighborhood} Open House"
    match = re.search(r'(\w+(?:\s+\w+)?)\s+Open House', cleaned, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Pattern: "{neighborhood} home for you at" (more flexible)
    match = re.search(r'(\w+(?:\s+\w+)*)\s+home\s+for\s+you', cleaned, re.IGNORECASE)
    if match:
        neighborhood = match.group(1).strip()
        if neighborhood.lower() not in excluded:
            return neighborhood

    # Pattern: "in {neighborhood} at $"
    match = re.search(r'in\s+(\w+(?:\s+\w+)*)\s+at\s+\$', cleaned, re.IGNORECASE)
    if match:
        neighborhood = match.group(1).strip()
        if neighborhood.lower() not in excluded:
            return neighborhood

    return None


def extract_address_from_subject(subject: str) -> Optional[str]:
    """Extract address from subject line like 'A home for you at 1645 Dwight Way'."""
    if not subject:
        return None

    # Pattern: "at {address}" or "at {street} {type}" where type is St/Ave/Rd/Dr/etc
    patterns = [
        r'at\s+(\d+\s+[A-Za-z\s]+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pkwy|Street|Avenue|Road|Boulevard|Drive|Lane|Court|Parkway)[.,]?(?:\s+[A-Za-z]+)?)',
        r'(\d+\s+[A-Za-z\s]+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pkwy|Street|Avenue|Road|Boulevard|Drive|Lane|Court|Parkway)[.,]?)',
    ]

    for pattern in patterns:
        match = re.search(pattern, subject, re.IGNORECASE)
        if match:
            addr = match.group(1).strip()
            # Clean up extra commas/periods
            addr = re.sub(r'[,.\s]+$', '', addr)
            return addr

    return None


def extract_price_from_subject(subject: str) -> Optional[int]:
    """Extract price from email subject line."""
    if not subject:
        return None

    # Pattern: "$1.4M", "$850K", "$499,999"
    match = re.search(r'\$\s*([\d.,]+)\s*([KMB])?', subject, re.IGNORECASE)
    if match:
        price_str = match.group(1).replace(",", "")
        suffix = match.group(2).upper() if match.group(2) else ""

        try:
            price = float(price_str)
            # Handle suffixes
            if suffix == 'K':
                price *= 1000
            elif suffix == 'M':
                price *= 1000000
            elif suffix == 'B':
                price *= 1000000000

            return int(price)
        except ValueError:
            pass
    return None


def is_rental_listing(listing: Dict, listing_url: Optional[str]) -> bool:
    """Detect if a listing is a rental vs. a sale property."""
    # Check price regardless of URL: sale prices are always >= $100K
    price = listing.get('price')
    if price and price < 100000:
        return True

    # Check URL for rental indicators
    if listing_url:
        url_lower = listing_url.lower()
        if '/rentals/' in url_lower or 'realtor.com/rentals' in url_lower:
            return True

    return False


def is_allowed_city(city: Optional[str]) -> bool:
    """Check if city is in the allowed list."""
    if not city:
        return False

    allowed_cities = {'Oakland', 'Berkeley', 'Albany', 'Piedmont', 'Kensington', 'El Cerrito'}
    return city in allowed_cities


def parse_html_native(html_body: str, subject: Optional[str] = None) -> Dict:
    """
    Parse listing details from HTML structure using BeautifulSoup.
    Primary method for structured email extraction.

    Returns dict with keys: address, city, state, price, beds, baths,
    house_sqft, lot_size_sqft, hoa_monthly, garage_spots, redfin_url
    (or null for missing fields).
    """
    if not html_body:
        return {}

    try:
        soup = BeautifulSoup(html_body, 'html.parser')

        # Decompose noise elements
        for tag in soup.find_all(['script', 'style', 'meta', 'link', 'nav', 'footer', 'noscript']):
            tag.decompose()

        # Try to find single property card via CSS selectors
        card = soup.select_one('[class*="property"], [class*="listing"]')

        # Fallback: find card via Redfin anchor tag
        if not card:
            redfin_link = soup.find('a', href=re.compile(r'redfin\.com'))
            if redfin_link:
                # Walk up parent chain to find containing block
                parent = redfin_link.parent
                for _ in range(3):
                    if parent is None or parent.name in ('body', 'html'):
                        break
                    if parent.name in ('td', 'tr', 'div', 'section', 'article'):
                        card = parent
                        break
                    parent = parent.parent

        # Extract fields from card if found
        if card:
            return _extract_card_fields(card, subject)

        # Fallback: flat-text regex on cleaned HTML (last resort before Claude)
        result = {}
        html_text = clean_html_for_parsing(html_body)

        # Extract price
        price = _parse_price(html_text)
        if price:
            result['price'] = price

        # Extract beds/baths/sqft from flat text
        beds_match = re.search(r'(\d+\.?\d*)\s*(?:bed|bd)s?', html_text, re.IGNORECASE)
        if beds_match:
            try:
                result['beds'] = float(beds_match.group(1))
            except ValueError:
                pass

        baths_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba)s?', html_text, re.IGNORECASE)
        if baths_match:
            try:
                result['baths'] = float(baths_match.group(1))
            except ValueError:
                pass

        sqft_match = re.search(r'([\d,]+)\s*(?:sqft|sq\.?\s*ft\.?)', html_text, re.IGNORECASE)
        if sqft_match:
            try:
                sqft_candidate = int(sqft_match.group(1).replace(',', ''))
                if 400 < sqft_candidate < 15000:
                    result['house_sqft'] = sqft_candidate
            except ValueError:
                pass

        # Extract address (full with city/state or just street)
        addr_match = re.search(
            r'(\d+\s+[A-Za-z\s]+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pkwy)[.,]?\s+[A-Za-z\s]+,\s*(?:CA|California)\s+\d{5})',
            html_text,
            re.IGNORECASE
        )
        if addr_match:
            full_addr = addr_match.group(1).strip()
            result['address'] = full_addr
            components = parse_address_components(full_addr)
            result['city'] = components.get('city')
            result['state'] = components.get('state') or 'CA'
        else:
            # Try without ZIP
            addr_match = re.search(
                r'(\d+\s+[A-Za-z\s]+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pkwy))',
                html_text,
                re.IGNORECASE
            )
            if addr_match:
                result['address'] = addr_match.group(1).strip()

        return result

    except Exception:
        return {}


def extract_house_sqft(text: str) -> Optional[int]:
    """Extract house square footage from plain or HTML-derived email text.

    Tries a primary pattern that anchors the sqft value between beds/baths
    markers, then falls back to scanning all "X,XXX Sq. Ft." occurrences and
    rejecting any that appear immediately next to the word "lot" (which would
    indicate lot size, not house size).

    Args:
        text: Plain text derived from an email body (plain or HTML-stripped).

    Returns:
        House square footage as an integer, or None if not found or out of the
        sanity range 400–15,000 sq ft.
    """
    if not text:
        return None

    # Look for the specific pattern: "Beds · Baths · X,XXX Sq. Ft."
    # This appears in Redfin emails as "4 Beds, 3 Baths, 2,500 Sq. Ft."
    pattern = r'(?:bed|bath)[s]?[,\.]?.*?(\d{1,2}(?:\.\d+)?)\s*(?:bed|bath).*?([\d,]+)\s*(?:sq\.?\s*ft\.?)'

    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        try:
            sqft_str = match.group(2).replace(",", "")
            sqft = int(sqft_str)
            # Sanity check: house sqft should be reasonable (500-10000 sq ft)
            if 400 < sqft < 15000:
                return sqft
        except (ValueError, IndexError):
            pass

    # Fallback: look for any "X,XXX Sq. Ft." that doesn't have "lot" text literally next to it
    matches = list(re.finditer(r'([\d,]+)\s*(?:sq\.?\s*ft\.?)', text, re.IGNORECASE))

    for match in matches:
        # Check 10 chars before and after for the word "lot"
        start = max(0, match.start() - 10)
        end = min(len(text), match.end() + 10)
        context = text[start:end].lower()

        # Skip if "lot" is in the immediate context
        if 'lot' not in context:
            try:
                sqft_str = match.group(1).replace(",", "")
                sqft = int(sqft_str)
                if 400 < sqft < 15000:
                    return sqft
            except ValueError:
                pass

    return None


def extract_lot_sizes_by_address(html_body: str) -> Dict[str, int]:
    """Extract a mapping of street addresses to lot sizes from email HTML.

    Iterates over every ``<tr>`` row in the parsed HTML and looks for a street
    address and a "X,XXX sq ft lot" pattern within the same row. Because Redfin
    batch emails place all properties in a single large ``<tr>``, this function
    is most reliable for single-property emails; callers should prefer the
    full-text regex approach for multi-property batch emails.

    Args:
        html_body: Raw HTML string of the email body.

    Returns:
        A dict mapping normalized street address strings (as parsed from the
        row text) to lot size in square feet. Returns an empty dict if
        ``html_body`` is falsy or parsing fails.
    """
    lot_size_map = {}

    if not html_body:
        return lot_size_map

    try:
        soup = BeautifulSoup(html_body, 'html.parser')

        # Find all property blocks (typically <tr> rows in a table)
        # Each block should contain address and lot size nearby
        for row in soup.find_all('tr'):
            row_text = row.get_text()

            # Try to extract address from the row
            address_match = re.search(r'(\d+\s+[A-Za-z\s]+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Street|Avenue|Road|Boulevard|Drive|Lane|Court))', row_text)

            # Try to extract lot size from the row
            lot_match = re.search(r'([\d,]+)\s*sq\.?\s*ft\.?\s*lot', row_text, re.IGNORECASE)

            # If we found both in the same row, map them
            if address_match and lot_match:
                address = address_match.group(1).strip()
                lot_str = lot_match.group(1).replace(",", "")
                try:
                    lot_size = int(lot_str)
                    lot_size_map[address] = lot_size
                except ValueError:
                    pass

        return lot_size_map
    except Exception:
        return {}


def parse_listing_email(plain_body: str, html_body: str, received_at: str = None, subject: Optional[str] = None) -> Dict:
    """Parse listing details from email body.

    Uses HTML-native parsing as PRIMARY method for all Jan 2025+ emails.
    Falls back to regex and Claude extraction if needed.
    """
    result = {}

    # Pre-extract lot sizes mapped by address for batch emails
    lot_size_map = extract_lot_sizes_by_address(html_body) if html_body else {}

    # Try HTML-native parsing first (PRIMARY method for all recent emails)
    if html_body:
        result = parse_html_native(html_body, subject)
        # If HTML-native extraction got enough fields, still try lot size extraction before returning
        fields_extracted = len([v for v in [result.get("price"), result.get("beds"),
                                            result.get("baths"), result.get("address")]
                               if v is not None])
        if fields_extracted >= 3:
            # Extract lot size even when HTML-native succeeds
            search_text = (plain_body or "") + " " + (html_body or "")

            # Try lot size extraction
            lot_match = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft\.?\s*lot|sq\.?\s*ft\.?\s*lot)', search_text, re.IGNORECASE)
            if lot_match:
                lot_str = lot_match.group(1).replace(",", "")
                try:
                    result["lot_size_sqft"] = int(lot_str)
                except ValueError:
                    pass

            # Try acres conversion if no lot size found
            if "lot_size_sqft" not in result:
                acres_match = re.search(r'([\d.]+)\s*acres?\s*(?:lot|property)', search_text, re.IGNORECASE)
                if acres_match:
                    try:
                        acres = float(acres_match.group(1))
                        result["lot_size_sqft"] = int(acres * 43560)
                    except ValueError:
                        pass

            return result
        # If HTML-native didn't work well, fall through to regex extraction

    # Regex-based extraction (fallback for incomplete HTML-native)
    # Try to extract price: $XXX,XXX
    price_match = re.search(r'\$[\d,]+', plain_body or "")
    if price_match:
        price_str = price_match.group(0).replace("$", "").replace(",", "")
        try:
            result["price"] = int(price_str)
        except ValueError:
            pass

    # Try to extract beds (e.g., "3 beds" or "3bd")
    beds_match = re.search(r'(\d+\.?\d*)\s*(?:bed|bd)s?', plain_body or "", re.IGNORECASE)
    if beds_match:
        try:
            result["beds"] = float(beds_match.group(1))
        except ValueError:
            pass

    # Try to extract baths (e.g., "2 baths" or "2ba")
    baths_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba)s?', plain_body or "", re.IGNORECASE)
    if baths_match:
        try:
            result["baths"] = float(baths_match.group(1))
        except ValueError:
            pass

    # Try to extract address (number + street name with street type)
    # Remove sqft patterns from body before matching to avoid including them in address
    addr_search_text = re.sub(r'(\d+)\s*(?:sqft|sq\.?\s*ft\.?)\s+', '', plain_body or "", flags=re.IGNORECASE)

    # First try full address with city/state
    address_match = re.search(r'\d+\s+[A-Za-z\s,]+(?:CA|California)(?:\s+\d+)?', addr_search_text, re.IGNORECASE)
    if address_match:
        result["address"] = address_match.group(0).strip()
    else:
        # Fallback: just number + street type
        address_match = re.search(r'(\d+\s+(?:[A-Za-z]+\s+)+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pkwy|Street|Avenue|Road|Boulevard|Drive|Lane|Court|Parkway))', addr_search_text, re.IGNORECASE)
        if address_match:
            result["address"] = address_match.group(1).strip()

    # Try to extract lot size: "X,XXX sq ft lot" or "X acres" format
    # First, check if we have this address in the pre-extracted lot_size_map (for batch emails)
    if result.get("address") and lot_size_map:
        # Try exact match
        if result["address"] in lot_size_map:
            result["lot_size_sqft"] = lot_size_map[result["address"]]
        else:
            # Try partial match (first part of address)
            address_prefix = result["address"].split(",")[0].strip()
            for mapped_addr, lot_size in lot_size_map.items():
                if address_prefix.lower() in mapped_addr.lower():
                    result["lot_size_sqft"] = lot_size
                    break

    # Check both plain text and HTML (HTML often has better formatting)
    search_text = (plain_body or "") + " " + (html_body or "")

    # Extract house square footage (if not already found)
    if "house_sqft" not in result:
        house_sqft = extract_house_sqft(search_text)
        if house_sqft:
            result["house_sqft"] = house_sqft

    # Look for "X,XXX sq ft lot" (Redfin format) - this is most common
    # Only if we didn't find it in the map
    if "lot_size_sqft" not in result:
        lot_match = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft\.?\s*lot|sq\.?\s*ft\.?\s*lot)', search_text, re.IGNORECASE)
        if lot_match:
            lot_str = lot_match.group(1).replace(",", "")
            try:
                result["lot_size_sqft"] = int(lot_str)
            except ValueError:
                pass

    # Fallback: try acres format and convert to sq ft (1 acre = 43,560 sq ft)
    if "lot_size_sqft" not in result:
        acres_match = re.search(r'([\d.]+)\s*acres?\s*(?:lot|property)', search_text, re.IGNORECASE)
        if acres_match:
            try:
                acres = float(acres_match.group(1))
                result["lot_size_sqft"] = int(acres * 43560)
            except ValueError:
                pass

    # Try to extract HOA: "$XXX/mo" or similar
    hoa_match = re.search(r'\$[\d,]+\s*(?:/month|\/mo|monthly)', plain_body or "", re.IGNORECASE)
    if hoa_match:
        hoa_str = hoa_match.group(0).split("$")[1].split("/")[0].replace(",", "")
        try:
            result["hoa_monthly"] = int(hoa_str)
        except ValueError:
            pass

    # Try to extract garage: "X car garage" or "X garage spots" (1-10 only)
    garage_match = re.search(r'\b([1-9]|10)\s*(?:car|garage)\b', plain_body or "", re.IGNORECASE)
    if garage_match:
        try:
            result["garage_spots"] = int(garage_match.group(1))
        except ValueError:
            pass

    return result


def clean_html_for_parsing(html_body: str) -> str:
    """Strip boilerplate HTML nodes and return a single clean text string.

    Uses BeautifulSoup to decompose non-content tags (``<script>``,
    ``<style>``, ``<nav>``, ``<footer>``, etc.) and any ``<div>`` or
    ``<section>`` whose ``class`` or ``id`` attribute contains ad/nav/footer
    marker keywords. The remaining tree is then collapsed to a single
    whitespace-normalised string via ``get_text(separator=' ')``.

    Args:
        html_body: Raw HTML string of the email body.

    Returns:
        A whitespace-normalised plain-text string containing only the main
        listing content, suitable for regex extraction.
    """
    soup = BeautifulSoup(html_body, 'html.parser')

    # Remove problematic tags
    for tag in soup.find_all(['script', 'style', 'meta', 'link', 'nav', 'footer', 'noscript']):
        tag.decompose()

    # Remove common ad/boilerplate sections
    for element in soup.find_all(['div', 'section']):
        class_str = element.get('class', [])
        id_str = element.get('id', '')

        # Check for ad/nav/footer markers
        for marker in ['ad', 'banner', 'sidebar', 'footer', 'nav', 'related', 'similar', 'trending', 'newsletter']:
            if marker in ' '.join(class_str).lower() or marker in id_str.lower():
                element.decompose()
                break

    # Get cleaned text
    text = soup.get_text(separator=' ', strip=True)

    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)

    return text


def _parse_price(text: str) -> Optional[int]:
    """Extract the first dollar-formatted price from a text string.

    Searches for a ``$X,XXX`` pattern and returns the numeric value. Prices
    below $1,000 are treated as fees or noise and discarded.

    Args:
        text: A plain-text string, typically the ``get_text()`` output of a
            BeautifulSoup tag.

    Returns:
        The parsed price as an integer, or None if no valid price is found.
    """
    if not text:
        return None

    match = re.search(r'\$\s*([\d,]+)', text)
    if not match:
        return None

    try:
        price = int(match.group(1).replace(',', ''))
        # Filter out very small amounts (likely fees, not prices)
        if price < 1000:
            return None
        return price
    except (ValueError, AttributeError):
        return None


def _parse_beds_baths_sqft(tag) -> Dict[str, Optional[int]]:
    """Extract beds, baths, and house square footage from a BeautifulSoup tag.

    Tries three patterns in order of specificity:
    1. Redfin middle-dot format: ``"X Beds · X Baths · X,XXX Sq. Ft."``
    2. Zillow pipe format: ``"X bd | X ba | X,XXX sqft"``
    3. Individual fallback regexes for each field independently.

    The sqft fallback applies a sanity range of 400–15,000 sq ft to avoid
    capturing lot sizes or other numeric noise.

    Args:
        tag: A BeautifulSoup ``Tag`` object representing a property card or
            any element whose text contains listing details.

    Returns:
        A dict with keys ``beds`` (float), ``baths`` (float), and
        ``house_sqft`` (int). Any field not found is set to None.
    """
    result = {'beds': None, 'baths': None, 'house_sqft': None}

    if not tag:
        return result

    tag_text = tag.get_text()

    # Try Redfin format first: "4 Beds · 2 Baths · 1,848 Sq. Ft."
    redfin_match = re.search(
        r'(\d+)\s*Beds?\s*·\s*(\d+)\s*Baths?\s*·\s*([\d,]+)\s*(?:Sq\.?\s*Ft\.?|sqft)',
        tag_text,
        re.IGNORECASE
    )

    if redfin_match:
        try:
            result['beds'] = float(redfin_match.group(1))
            result['baths'] = float(redfin_match.group(2))
            result['house_sqft'] = int(redfin_match.group(3).replace(',', ''))
            return result
        except (ValueError, IndexError):
            pass

    # Try Zillow compact format: "X bd | X ba | X,XXX sqft"
    compact_match = re.search(
        r'(\d+)\s*bd\s*\|\s*(\d+)\s*ba\s*\|\s*([\d,]+)\s*(?:sqft|sq\.?\s*ft\.?)',
        tag_text,
        re.IGNORECASE
    )

    if compact_match:
        try:
            result['beds'] = float(compact_match.group(1))
            result['baths'] = float(compact_match.group(2))
            result['house_sqft'] = int(compact_match.group(3).replace(',', ''))
            return result
        except (ValueError, IndexError):
            pass

    # Fallback: search for individual patterns within the tag
    beds_match = re.search(r'(\d+\.?\d*)\s*(?:bed|bd)s?', tag_text, re.IGNORECASE)
    if beds_match:
        try:
            result['beds'] = float(beds_match.group(1))
        except ValueError:
            pass

    baths_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba)s?', tag_text, re.IGNORECASE)
    if baths_match:
        try:
            result['baths'] = float(baths_match.group(1))
        except ValueError:
            pass

    sqft_match = re.search(r'([\d,]+)\s*(?:sqft|sq\.?\s*ft\.?)', tag_text, re.IGNORECASE)
    if sqft_match:
        try:
            sqft_candidate = int(sqft_match.group(1).replace(',', ''))
            # Sanity check: house sqft should be reasonable (400-15000 sq ft)
            if 400 < sqft_candidate < 15000:
                result['house_sqft'] = sqft_candidate
        except ValueError:
            pass

    return result


def _find_redfin_url(tag) -> Optional[str]:
    """Find the first Redfin property listing URL within a BeautifulSoup tag.

    Searches for ``<a>`` elements whose ``href`` matches the pattern
    ``redfin.com/CA/<City>/``, which identifies actual property pages and
    excludes generic Redfin links (e.g. ``/recommendations-feedback``,
    ``/myredfin``).

    Args:
        tag: A BeautifulSoup ``Tag`` to search within, typically a property
            card ``<td>`` or ``<tr>`` element.

    Returns:
        The ``href`` string of the first matching anchor, or None if no
        qualifying Redfin URL is found or ``tag`` is falsy.
    """
    if not tag:
        return None

    try:
        link = tag.find('a', href=re.compile(r'redfin\.com/CA/[^/]+/'))
        if link and link.get('href'):
            return link['href']
    except (AttributeError, TypeError):
        pass

    return None


def _extract_card_fields(card_tag, subject: Optional[str] = None) -> Dict:
    """Extract all structured fields from a single property card HTML element.

    Applies a layered extraction strategy within the scope of ``card_tag``:
    1. Price: first value in the $100K–$50M residential range from card text.
    2. Address: from a ``redfin.com/CA/<City>/`` anchor text; falls back to
       a street-type regex, then a full ``"number, city, CA zip"`` pattern.
    3. City: from full-address regex group 2; falls back to
       ``parse_address_components``, then a neighborhood→city keyword map
       checked against subject and card text, then the Redfin URL path segment.
    4. Beds/baths/sqft: delegated to ``_parse_beds_baths_sqft``.
    5. Lot size: ``"X,XXX sq ft lot"`` regex on card text.
    6. HOA: ``"$XXX/mo"`` regex on card text.
    7. Garage: ``"X car"`` / ``"X garage"`` bounded to 1–10 spots.

    Args:
        card_tag: A BeautifulSoup ``Tag`` representing one property card,
            typically a ``<td>``, ``<tr>``, or ``<div>`` containing all
            details for a single listing.
        subject: Optional email subject line used as a city-hint fallback
            when the card body contains no city information.

    Returns:
        A dict with keys: ``address``, ``city``, ``state``, ``price``,
        ``beds``, ``baths``, ``house_sqft``, ``lot_size_sqft``,
        ``hoa_monthly``, ``garage_spots``, ``redfin_url``. Any field not
        found is None.
    """
    result = {
        'address': None,
        'city': None,
        'state': None,
        'price': None,
        'beds': None,
        'baths': None,
        'house_sqft': None,
        'lot_size_sqft': None,
        'hoa_monthly': None,
        'garage_spots': None,
        'redfin_url': None
    }

    if not card_tag:
        return result

    card_text = card_tag.get_text()

    # Remove sqft patterns from text before extracting address to avoid including them
    # e.g. "312 sqft 6767 Skyview Dr" should extract as "6767 Skyview Dr" not "312 sqft 6767 Skyview Dr"
    card_text_clean = re.sub(r'(\d+)\s*(?:sqft|sq\.?\s*ft\.?)\s+', '', card_text, flags=re.IGNORECASE)

    # Extract price: first price in a reasonable residential range ($100K–$50M)
    price_matches = re.findall(r'\$\s*([\d,]+)', card_text)
    for p in price_matches:
        try:
            val = int(p.replace(',', ''))
            if 100_000 <= val <= 50_000_000:
                result['price'] = val
                break
        except (ValueError, AttributeError):
            pass

    # Extract address: find a property-specific Redfin URL (/CA/<City>/...)
    # Exclude generic pages like /recommendations-feedback, /myredfin, etc.
    redfin_link = card_tag.find('a', href=re.compile(r'redfin\.com/CA/[^/]+/'))
    if redfin_link:
        result['redfin_url'] = redfin_link.get('href')
        link_text = redfin_link.get_text().strip()
        if link_text:
            result['address'] = link_text

    # Fallback: find address via regex in cleaned card text (sqft removed)
    if not result['address']:
        addr_match = re.search(
            r'(\d+\s+[A-Za-z\s]+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pkwy|Street|Avenue|Road|Boulevard|Drive|Lane|Court))',
            card_text_clean,
            re.IGNORECASE
        )
        if addr_match:
            result['address'] = addr_match.group(1).strip()

    # Look for full address (with city/state) in cleaned card body text
    # Redfin cards show: "1068 Aileen St, Oakland, CA 94608"
    full_addr_match = re.search(
        r'(\d+\s+(?!Sq\.?\s*Ft)([A-Za-z][^,\n]+),\s*([A-Za-z][A-Za-z\s]+?),\s*CA\s*\d{5})',
        card_text_clean,
        re.IGNORECASE
    )
    if full_addr_match:
        if not result['address']:
            result['address'] = full_addr_match.group(1).split(',')[0].strip()
        result['city'] = full_addr_match.group(3).strip().title()
        result['state'] = 'CA'

    # Parse address components if city still not found
    if result['address'] and not result['city']:
        components = parse_address_components(result['address'])
        result['city'] = components.get('city')
        result['state'] = components.get('state') or 'CA'

    # If city not found from address, try to extract from subject line or card text
    # Redfin subjects often have neighborhood: "A MONTCLAIR home for you..." or "A PIEDMONT PINES home..."
    if not result['city']:
        # Map neighborhoods to cities
        neighborhood_to_city = {
            'oakland': 'Oakland',
            'montclair': 'Oakland',
            'piedmont pines': 'Oakland',
            'allendale': 'Oakland',
            'eastmont': 'Oakland',
            'glenview': 'Oakland',
            'ivy hill': 'Oakland',
            'maxwell park': 'Oakland',
            'oakmore': 'Oakland',
            'sheffield village': 'Oakland',
            'temescal': 'Oakland',
            'west oakland': 'Oakland',
            'piedmont': 'Piedmont',
            'berkeley': 'Berkeley',
            'north berkeley': 'Berkeley',
            'west berkeley': 'Berkeley',
            'albany': 'Albany',
            'el cerrito': 'El Cerrito',
            'emeryville': 'Emeryville',
        }

        # Try subject line first
        if subject:
            for neighborhood, city in neighborhood_to_city.items():
                if neighborhood.lower() in subject.lower():
                    result['city'] = city
                    break

        # If still no city, try card text for city keywords
        if not result['city']:
            for neighborhood, city in neighborhood_to_city.items():
                if neighborhood.lower() in card_text.lower():
                    result['city'] = city
                    break

        # Extract city from Redfin URL path: redfin.com/CA/<City>/...
        if not result['city'] and result.get('redfin_url'):
            url_city_match = re.search(r'redfin\.com/CA/([^/]+)/', result['redfin_url'])
            if url_city_match:
                result['city'] = url_city_match.group(1).replace('-', ' ').title()

    # Extract beds/baths/sqft
    bed_bath_sqft = _parse_beds_baths_sqft(card_tag)
    result['beds'] = bed_bath_sqft['beds']
    result['baths'] = bed_bath_sqft['baths']
    result['house_sqft'] = bed_bath_sqft['house_sqft']

    # Lot size: "X,XXX sq ft lot"
    lot_match = re.search(r'([\d,]+)\s*sq\.?\s*ft\.?\s*lot', card_text, re.IGNORECASE)
    if lot_match:
        try:
            result['lot_size_sqft'] = int(lot_match.group(1).replace(',', ''))
        except ValueError:
            pass

    # HOA: "$XXX/mo"
    hoa_match = re.search(r'\$\s*([\d,]+)\s*(?:/month|\/mo|monthly)', card_text, re.IGNORECASE)
    if hoa_match:
        try:
            result['hoa_monthly'] = int(hoa_match.group(1).replace(',', ''))
        except ValueError:
            pass

    # Garage: "X car garage" or "X garage spots" (1-10 only)
    garage_match = re.search(r'\b([1-9]|10)\s*(?:car|garage)\b', card_text, re.IGNORECASE)
    if garage_match:
        try:
            result['garage_spots'] = int(garage_match.group(1))
        except ValueError:
            pass

    return result


def is_valid_address(address: Optional[str]) -> bool:
    """Check if address looks valid (not garbage from regex extraction)."""
    if not address:
        return False

    # Reject if it's just numbers (e.g., "000", "30", "211")
    if re.match(r'^\d+$', address.strip()):
        return False

    # Reject if it's a URL
    if 'http' in address.lower() or 'redfin.com' in address.lower():
        return False

    # Reject if it's very short (less than 8 chars - typical min is "X St, YY")
    if len(address.strip()) < 8:
        return False

    # Reject if no street type is present AND address doesn't look like "number + plain name"
    # (e.g. "2010 Filbert" or "712 Masonic" are valid streets without type suffixes)
    street_types = ['st', 'ave', 'rd', 'blvd', 'dr', 'ln', 'ct', 'way', 'pkwy', 'street', 'avenue', 'road', 'boulevard', 'drive', 'lane', 'court', 'parkway']
    has_street_type = any(st in address.lower() for st in street_types)
    looks_like_address = bool(re.match(r'^\d+\s+[A-Za-z]', address.strip()))
    # Reject sqft-contaminated garbage like "393 Sq. Ft. 2010 Filbert"
    has_sqft_garbage = bool(re.search(r'Sq\.?\s*Ft', address, re.IGNORECASE))
    if not has_street_type and (not looks_like_address or has_sqft_garbage):
        return False

    return True


def fallback_parse_with_claude(plain_body: str, html_body: str) -> Dict:
    """Use Claude to parse listing details as fallback."""
    client = get_anthropic_client()

    # Prefer HTML since it has richer structure
    body_to_parse = html_body if html_body else plain_body

    prompt = f"""Extract the following information from this Redfin listing email:
- price (as integer, e.g., 500000)
- beds (as float)
- baths (as float)
- address (full street address with city and state)
- lot_size_sqft (as integer if present)
- hoa_monthly (as integer if present)
- garage_spots (as integer if present)

Return ONLY valid JSON with these keys. Omit keys that are not found.

Email body:
{body_to_parse[:8000]}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}]
        )

        text = response.content[0].text.strip()
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            # Convert string values to appropriate types
            if "price" in data:
                data["price"] = int(float(data["price"]))
            if "beds" in data:
                data["beds"] = float(data["beds"])
            if "baths" in data:
                data["baths"] = float(data["baths"])
            if "lot_size_sqft" in data:
                data["lot_size_sqft"] = int(float(data["lot_size_sqft"]))
            if "hoa_monthly" in data:
                data["hoa_monthly"] = int(float(data["hoa_monthly"]))
            if "garage_spots" in data:
                data["garage_spots"] = int(float(data["garage_spots"]))
            return data
    except Exception as e:
        print(f"Claude fallback parsing failed: {e}")

    return {}


def _validate_price_with_claude(search_text: str, extracted_price: int, address: str) -> Optional[int]:
    """Use Claude to validate suspicious prices by finding price closest to address."""
    try:
        # Find the context around the address (±500 chars)
        if address not in search_text:
            return extracted_price

        addr_idx = search_text.index(address)
        start = max(0, addr_idx - 500)
        end = min(len(search_text), addr_idx + 500)
        context = search_text[start:end]

        # Extract prices from the local context only
        context_prices = re.findall(r'\$[\d,]+', context)
        unique_prices = sorted(set(int(p.replace('$', '').replace(',', '')) for p in context_prices), reverse=True)

        # If extracted price is NOT in local context, use the first price from context
        if extracted_price not in unique_prices and unique_prices:
            context_price = unique_prices[0]  # Largest price in local context
            if context_price != extracted_price:
                print(f"  ⚠ Price corrected: ${extracted_price:,} → ${context_price:,} ({address})")
            return context_price

        # If only one price in context and it matches extracted, that's good
        if len(unique_prices) <= 1:
            return extracted_price

        # If extracted price is already in the local context, it's likely correct
        if extracted_price in unique_prices:
            return extracted_price

        # Ask Claude to pick the right price from local context only
        client = get_anthropic_client()

        prompt = f"""For this Zillow property, identify the correct listing price from the context.

Address: {address}
Extracted price: ${extracted_price:,}
Prices near this address: {', '.join(f'${p:,}' for p in unique_prices)}

Context around address:
{context}

Which is the listing price for {address}? Reply with ONLY the number, e.g. "995000" """

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}]
        )

        answer = response.content[0].text.strip()
        validated_price = int(''.join(filter(str.isdigit, answer)))

        if validated_price != extracted_price:
            print(f"  ⚠ Price corrected by Claude: ${extracted_price:,} → ${validated_price:,} ({address})")

        return validated_price
    except Exception as e:
        # On any error, return original price
        return extracted_price


def parse_zillow_open_houses(html_body: str, received_at: str) -> List[Dict]:
    """Parse Zillow 'Plan Your Weekend' open-house digest emails.

    These emails list multiple properties with upcoming open-house times.
    Each property sits in a <td> containing price, beds/baths/sqft, address,
    and open-house schedule.

    Args:
        html_body: Full HTML content of the email.
        received_at: ISO timestamp of when the email was received.

    Returns:
        List of property dicts with keys matching the listings schema.
        Only properties with both address and price are returned.
    """
    if not html_body:
        return []

    soup = BeautifulSoup(html_body, 'html.parser')
    for tag in soup.find_all(['script', 'style']):
        tag.decompose()

    properties = []
    seen_addresses = set()

    # Property cards are <td> elements that contain a price AND an address pattern.
    # We walk all tds and accept ones matching both criteria.
    for td in soup.find_all('td'):
        td_text = td.get_text(separator=' ', strip=True)
        has_price = bool(re.search(r'\$[\d,]{5,}', td_text))
        has_address = bool(re.search(
            r'\d+\s+[A-Z][a-zA-Z]+(?:\s+[A-Za-z]+)*\s+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pkwy|Pl|Ter)',
            td_text
        ))
        if not (has_price and has_address):
            continue

        fields = _extract_card_fields(td)
        if not fields.get('address') or not fields.get('price'):
            continue

        addr_key = fields['address'].lower()
        if addr_key in seen_addresses:
            continue
        seen_addresses.add(addr_key)

        fields.setdefault('state', 'CA')
        fields['lot_size_sqft'] = None
        fields['hoa_monthly'] = None
        fields['garage_spots'] = None
        properties.append(fields)

    return properties


def parse_zillow_digest(plain_body: str, html_body: str, received_at: str) -> List[Dict]:
    """
    Parse Zillow digest emails with multiple properties.
    Uses BeautifulSoup on HTML first, falls back to plain text parsing.

    Format: "X Results for 'search'" or "1 Result for 'search'"
    """
    properties = []

    # Try BeautifulSoup first on HTML
    if html_body:
        soup = BeautifulSoup(html_body, 'html.parser')

        # Decompose noise
        for tag in soup.find_all(['script', 'style']):
            tag.decompose()

        # Find all property cards: expanded selector patterns for Zillow variations
        cards = soup.select(
            '[class*="propertyCard"], [class*="listing"], [class*="result"], '
            '[class*="property"], [class*="card"], '
            'div[data-testid*="property"], li[class*="item"]'
        )

        # If found cards, extract from them
        if cards:
            for card in cards:
                fields = _extract_card_fields(card)
                # For Zillow, require address and price
                if fields.get('address') and fields.get('price'):
                    # Ensure state is set
                    fields['state'] = 'CA'
                    # Zillow doesn't include lot size/HOA/garage
                    fields['lot_size_sqft'] = None
                    fields['hoa_monthly'] = None
                    fields['garage_spots'] = None
                    properties.append(fields)

            return properties

    # Fallback: plain text parsing with improved robustness
    search_text = plain_body or ""
    if not search_text:
        return properties

    # Remove sqft patterns from text before extracting address to avoid including them
    # e.g. "312 sqft 6767 Skyview Dr" should extract as "6767 Skyview Dr"
    search_text = re.sub(r'(\d+)\s*(?:sqft|sq\.?\s*ft\.?)\s+', '', search_text, flags=re.IGNORECASE)

    # More flexible property block splitting:
    # Match "For sale." or "For sale\n" OR start of price pattern
    blocks = re.split(r'(?:For sale\.|\nFor sale\n|\$)', search_text)

    # If we split on "$", prepend it back to each block (except first)
    if len(blocks) > 1 and '\n' not in blocks[0][:10]:
        blocks = [blocks[0]] + ['$' + b for b in blocks[1:]]

    # First block is header, skip it
    for block in blocks[1:]:
        # Extract price: "$XXX,XXX" or from start of block if "$" was prepended
        price_match = re.search(r'\$[\s]*([\d,]+)', block)
        price = None
        if price_match:
            try:
                price = int(price_match.group(1).replace(',', ''))
            except ValueError:
                pass

        # Extract beds/baths/sqft: "X bd | X ba | X,XXX sqft"
        beds_baths_sqft_match = re.search(
            r'(\d+(?:\.\d)?)\s*bd\s*\|\s*(\d+(?:\.\d)?)\s*ba\s*\|\s*([\d,]+)\s*(?:sqft|sq\.?\s*ft\.?)',
            block,
            re.IGNORECASE
        )

        beds = None
        baths = None
        house_sqft = None

        if beds_baths_sqft_match:
            try:
                beds = float(beds_baths_sqft_match.group(1))
                baths = float(beds_baths_sqft_match.group(2))
                house_sqft = int(beds_baths_sqft_match.group(3).replace(',', ''))
            except (ValueError, IndexError):
                pass

        # Extract address with city - improved pattern for flexibility
        address = None
        city = None
        address_match = re.search(
            r'(\d+\s+[A-Za-z0-9\s]*?(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Parkway|Street|Avenue|Road|Boulevard|Drive|Lane|Court|Ter|Pl|Place|Terrace|Cir|Circle)(?:\s+(?:APT|Apt|apt|Unit|unit|#)\s*[A-Za-z0-9]+)?)\s*[,\n]\s*([A-Za-z\s]+?),\s*(?:CA|California)',
            block,
            re.IGNORECASE
        )

        if address_match:
            address = address_match.group(1).strip()
            city = address_match.group(2).strip()

        # Only add if address and price found
        if address and price:
            properties.append({
                "address": address,
                "city": city,
                "state": "CA",
                "price": price,
                "beds": beds,
                "baths": baths,
                "house_sqft": house_sqft,
                "lot_size_sqft": None,
                "hoa_monthly": None,
                "garage_spots": None,
                "redfin_url": None
            })

    # Also capture any recommendations section appended to digest emails
    properties.extend(_parse_zillow_recommendations(plain_body or ""))

    return properties


def parse_zillow_email(plain_body: str, html_body: str, received_at: str, subject: str = "") -> List[Dict]:
    """
    Parse Zillow emails. Handles both:
    1. Individual alerts (Price Cut, New Listing) - single property
    2. Digest emails (X Results for..., 1 Result for...) - multiple properties

    Uses BeautifulSoup first, falls back to regex.

    Args:
        plain_body: Plain text version of email
        html_body: HTML version of email
        received_at: Email received timestamp
        subject: Email subject line (used to detect digest emails)
    """
    properties = []
    search_text = (plain_body or "") + " " + (html_body or "")

    if not search_text:
        return properties

    # Detect "Plan Your Weekend" open-house digest
    is_open_house_digest = bool(re.search(r'plan your weekend|open house', subject or "", re.IGNORECASE))
    if is_open_house_digest:
        return parse_zillow_open_houses(html_body, received_at)

    # Detect if this is a digest email (check subject first, then body)
    is_digest = bool(re.search(r'\d+\s*Results? for', subject or "", re.IGNORECASE))
    if not is_digest:
        is_digest = bool(re.search(r'\d+\s*Results? for', search_text, re.IGNORECASE))

    if is_digest:
        return parse_zillow_digest(plain_body, html_body, received_at)

    # Parse as individual alert (Price Cut, New Listing, etc.)
    # For "New Listing" emails, extract from subject first (most reliable)
    is_new_listing = bool(re.search(r'New Listing', subject or "", re.IGNORECASE))

    address = None
    city = None

    if is_new_listing:
        # Extract from subject line: "New Listing: 2749 Parker Ave Oakland, CA ..."
        # Also handles "New Showcase Listing: 2100 94th Ave, Oakland, CA ..."
        subject_addr_match = re.search(
            r'New (?:Showcase )?Listing:\s*(.+?(?:Oakland|Berkeley|Albany|Piedmont|El Cerrito)),\s*CA',
            subject or "", re.IGNORECASE
        )
        if subject_addr_match:
            addr_with_city = subject_addr_match.group(1).strip()
            # City is the last word(s) matching allowed cities
            city_match = re.search(r'(Oakland|Berkeley|Albany|Piedmont|El Cerrito)$', addr_with_city, re.IGNORECASE)
            if city_match:
                city = city_match.group(1)
                address = addr_with_city[:city_match.start()].rstrip(', ').strip()

    # Try BeautifulSoup card extraction if subject extraction didn't work
    if not address:
        soup = BeautifulSoup(html_body or "", 'html.parser')

        # Decompose noise elements
        for tag in soup.find_all(['script', 'style']):
            tag.decompose()

        # Try to find property card via CSS selectors
        card = soup.select_one('[class*="propertyCard"], [class*="propertyCardSM"], [class*="listing"]')

        # Fallback: find all td elements filtered by content (dollar sign + address)
        if not card:
            for td in soup.find_all('td'):
                td_text = td.get_text()
                has_price = bool(re.search(r'\$[\d,]+', td_text))
                has_address = bool(re.search(r'\d+\s+[A-Za-z\s]+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Parkway)', td_text, re.IGNORECASE))
                if has_price and has_address:
                    card = td
                    break

        # Extract from card if found
        if card:
            fields = _extract_card_fields(card, subject)
            if fields.get('address') and (fields.get('price') or fields.get('beds') or fields.get('baths')):
                fields['state'] = 'CA'
                return [fields]

    # Fallback: regex-based extraction on plain text

    price = None
    if is_new_listing:
        # Extract first listing block: from "For sale" to next major section or "View this listing"
        block_match = re.search(r'For sale\..*?(?=View this listing|For sale\.|$)', search_text, re.IGNORECASE | re.DOTALL)
        if block_match:
            block = block_match.group(0)
            price_match = re.search(r'\$[\d,]+', block)
            if price_match:
                try:
                    price = int(price_match.group(0).replace('$', '').replace(',', ''))
                except ValueError:
                    pass

    # Fallback: general regex for price extraction
    if not price:
        price_match = re.search(r'\$[\d,]+\s*\|\s*Price', search_text, re.IGNORECASE)
        if price_match:
            price_str = price_match.group(0).replace('$', '').replace('|', '').split('Price')[0].strip().replace(',', '')
            try:
                price = int(price_str)
            except ValueError:
                pass

    # Last fallback: find "$XXX,XXX" near "For sale"
    if not price:
        for_sale_match = re.search(r'For sale\.\s+\$[\d,]+', search_text, re.IGNORECASE)
        if for_sale_match:
            price_part = re.search(r'\$([\d,]+)', for_sale_match.group(0))
            if price_part:
                try:
                    price = int(price_part.group(1).replace(',', ''))
                except ValueError:
                    pass

    # Extract beds/baths/sqft: "X bd | X ba | X,XXX sqft"
    beds_baths_sqft_match = re.search(
        r'(\d+)\s*bd\s*\|\s*(\d+)\s*ba\s*\|\s*([\d,]+)\s*(?:sqft|sq\.?\s*ft\.?)',
        search_text, re.IGNORECASE
    )

    beds = None
    baths = None
    house_sqft = None

    if beds_baths_sqft_match:
        try:
            beds = float(beds_baths_sqft_match.group(1))
            baths = float(beds_baths_sqft_match.group(2))
            house_sqft = int(beds_baths_sqft_match.group(3).replace(',', ''))
        except (ValueError, IndexError):
            pass

    # Fallback: if grouped pattern didn't work, try individual sqft match
    if not house_sqft:
        sqft_match = re.search(r'([\d,]+)\s*(?:sqft|sq\.?\s*ft\.?)', search_text, re.IGNORECASE)
        if sqft_match:
            try:
                sqft_candidate = int(sqft_match.group(1).replace(',', ''))
                if 300 < sqft_candidate < 20000:
                    house_sqft = sqft_candidate
            except ValueError:
                pass

    # Extract address with city from body text (if not already extracted from subject)
    if not address:
        # Use more specific pattern: number + street, then comma + city
        address_match = re.search(
            r'(\d+\s+[A-Za-z0-9\s]+?(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Parkway|Street|Avenue|Road|Boulevard|Drive|Lane|Court))(?:\s+(?:APT|Apt|apt|Unit|unit|#)\s*[A-Za-z0-9]+)?,\s*([A-Za-z\s]+?),\s*(?:CA|California)',
            search_text,
            re.IGNORECASE
        )

        if address_match:
            address = address_match.group(1).strip()
            city = address_match.group(2).strip()

    # Validate price if suspicious
    if price and address:
        all_prices = re.findall(r'\$[\d,]+', search_text)
        unique_prices = set(int(p.replace('$', '').replace(',', '')) for p in all_prices if p.replace('$', '').replace(',', '').isdigit())

        should_validate = len(unique_prices) > 1 or price < 75000
        if should_validate:
            price = _validate_price_with_claude(search_text, price, address)

    if address and (price or beds or baths):
        properties.append({
            "address": address,
            "city": city,
            "state": "CA",
            "price": price,
            "beds": beds,
            "baths": baths,
            "house_sqft": house_sqft,
            "lot_size_sqft": None,
            "hoa_monthly": None,
            "garage_spots": None,
            "redfin_url": None
        })

    # Also parse recommendations section (e.g. "Our recommendations for you")
    properties.extend(_parse_zillow_recommendations(plain_body or ""))

    return properties


def _parse_zillow_recommendations(plain_body: str) -> List[Dict]:
    """
    Parse the "Our recommendations for you" section of a Zillow "New Listing" email.

    Recommendation blocks in plain text follow the pattern:
        For sale

        $949,000
        3 bd | 3 ba | 1,588 sqft
        943 Glendome Cir, Oakland, CA

    Args:
        plain_body: Plain text body of the Zillow email.

    Returns:
        List of property dicts for each valid recommendation found.
    """
    # Isolate the recommendations section
    rec_match = re.search(
        r'Our recommendations for you.*?(?=See latest search results|Improve your recommendations|$)',
        plain_body,
        re.IGNORECASE | re.DOTALL
    )
    if not rec_match:
        return []

    rec_text = rec_match.group(0)

    # Split into individual "For sale" blocks (recommendations don't have "NEW." suffix)
    blocks = re.split(r'(?=For sale\s*\n)', rec_text, flags=re.IGNORECASE)

    properties = []
    for block in blocks:
        if not re.match(r'For sale\s*\n', block, re.IGNORECASE):
            continue

        # Skip the primary listing block which has "NEW" or a period
        if re.match(r'For sale\s*\.\s*(NEW\.?)?', block, re.IGNORECASE):
            continue

        # Extract price
        price = None
        price_match = re.search(r'\$([\d,]+)', block)
        if price_match:
            try:
                price = int(price_match.group(1).replace(',', ''))
            except ValueError:
                pass

        # Extract beds / baths / sqft
        beds = baths = house_sqft = None
        bbq = re.search(
            r'(\d+(?:\.\d+)?)\s*bd\s*\|\s*(\d+(?:\.\d+)?)\s*ba\s*\|\s*([\d,]+)\s*sqft',
            block, re.IGNORECASE
        )
        if bbq:
            try:
                beds = float(bbq.group(1))
                baths = float(bbq.group(2))
                house_sqft = int(bbq.group(3).replace(',', ''))
            except ValueError:
                pass

        # Extract address + city — restrict to a single line to avoid grabbing sqft text
        addr_match = re.search(
            r'^(\d+\s+[A-Za-z0-9][A-Za-z0-9 ]+?(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Cir|Circle|Pkwy|Parkway|Street|Avenue|Road|Boulevard|Drive|Lane|Court|Ter|Pl|Place|Terrace)(?:\s+(?:APT|Apt|Unit|#)\s*[A-Za-z0-9]+)?),\s*(Oakland|Berkeley|Albany|Piedmont|El Cerrito)',
            block, re.IGNORECASE | re.MULTILINE
        )
        if not addr_match:
            continue

        address = addr_match.group(1).strip()
        city = addr_match.group(2).strip()

        if address and (price or beds or baths):
            properties.append({
                "address": address,
                "city": city,
                "state": "CA",
                "price": price,
                "beds": beds,
                "baths": baths,
                "house_sqft": house_sqft,
                "lot_size_sqft": None,
                "hoa_monthly": None,
                "garage_spots": None,
                "redfin_url": None
            })

    return properties


def run_ingest(conn: sqlite3.Connection, service) -> int:
    """Run email ingestion pipeline."""
    last_ts = get_sync_state(conn, "last_email_timestamp") or "0"
    new_messages = fetch_new_listing_emails(service, last_ts)

    if not new_messages:
        print("No new emails found")
        return 0

    count = 0
    max_timestamp = last_ts

    for msg_info in new_messages:
        msg_id = msg_info["id"]

        email = get_full_email(service, msg_id)
        if not email:
            continue

        # Parse received date (same for all properties in batch)
        received_at = email["date"]
        try:
            # Gmail date format: "Thu, 15 Mar 2026 10:30:45 -0700"
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(received_at)
            received_at = dt.isoformat()
        except Exception:
            received_at = datetime.utcnow().isoformat()

        # Skip emails older than Jan 1, 2023
        try:
            dt = datetime.fromisoformat(received_at)
            # Handle timezone-aware datetimes
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            cutoff = datetime(2023, 1, 1)
            if dt < cutoff:
                print(f"  Skipping {msg_id} (email older than Jan 1, 2023)")
                continue
        except (ValueError, AttributeError):
            pass

        if received_at > max_timestamp:
            max_timestamp = received_at

        # Try batch parsing first (handles emails with multiple properties)
        batch_properties = extract_properties_from_batch_email(email["html_body"]) if email["html_body"] else []

        if batch_properties:
            # Fetch existing addresses for this email once (not per-property)
            cursor = conn.cursor()
            cursor.execute("SELECT address FROM listings WHERE gmail_message_id = ?", (msg_id,))
            existing_addresses = {row[0] for row in cursor.fetchall()}

            # Process each property found in batch email
            for prop in batch_properties:
                listing = {
                    "address": prop['address'],
                    "city": prop['city'],
                    "state": prop['state'],
                    "price": prop['price'],
                    "beds": prop['beds'],
                    "baths": prop['baths']
                }

                # Skip rental listings
                if is_rental_listing(listing, None):
                    continue

                # Skip listings not in allowed cities
                if not is_allowed_city(listing.get('city')):
                    continue

                # Skip if this specific property is already in database
                if prop['address'] in existing_addresses:
                    continue

                # Create unique ID for each property in batch
                prop_id = f"{msg_id}_{prop['address'].replace(' ', '_').replace(',', '')[:20]}"

                listing_record = {
                    "id": prop_id,
                    "gmail_message_id": msg_id,
                    "subject": email["subject"],
                    "received_at": received_at,
                    **listing
                }

                upsert_listing(conn, listing_record)
                count += 1
                price_str = f"(${prop['price']:,})" if prop['price'] else ""
                print(f"  Ingested: {prop['address']} {price_str}")
        else:
            # Fallback to single-property parsing
            # PRIORITY: Use plain text first (it's much cleaner than HTML)
            listing = {}

            # Step 1: Try plain text parsing with regex
            if email["plain_body"]:
                listing = parse_listing_email(email["plain_body"], "", received_at)

            # Step 2: If plain text didn't work, try Claude on plain text
            extracted_fields = {k for k in listing.keys() if listing[k] is not None}
            has_valid_address = is_valid_address(listing.get("address"))

            if email["plain_body"] and (len(extracted_fields) < 3 or not has_valid_address):
                print(f"  Parsing {msg_id} with Claude (plain text)...")
                fallback_data = fallback_parse_with_claude(
                    email["plain_body"],
                    ""  # Pass empty HTML to force plain text focus
                )
                listing.update(fallback_data)

            # Step 3: Only if no plain text, try HTML as last resort
            if not listing.get("address") and email["html_body"]:
                print(f"  Parsing {msg_id} with Claude (HTML - no plain text available)...")
                fallback_data = fallback_parse_with_claude(
                    "",
                    email["html_body"]
                )
                listing.update(fallback_data)

            # Extract address from subject if not found in body
            if not listing.get("address"):
                subject_address = extract_address_from_subject(email["subject"])
                if subject_address:
                    listing["address"] = subject_address

            # Extract neighborhood from subject if no address was found
            if not listing.get("address"):
                subject_neighborhood = extract_neighborhood_from_subject(email["subject"])
                if subject_neighborhood:
                    listing["neighborhood"] = subject_neighborhood

            # Extract price from subject if not found in body
            if not listing.get("price"):
                subject_price = extract_price_from_subject(email["subject"])
                if subject_price:
                    listing["price"] = subject_price

            # Skip rental listings - we only want properties for sale
            if is_rental_listing(listing, None):
                print(f"  Skipping {msg_id} (rental property)")
                continue

            # Skip listings not in allowed cities
            if not is_allowed_city(listing.get('city')):
                city = listing.get('city', 'Unknown')
                print(f"  Skipping {msg_id} ({city} not in allowed cities)")
                continue

            # Check if duplicate property already exists (by address only)
            existing = get_listing_by_address(conn, listing.get('address'))

            # Use existing ID if this is a re-listing, otherwise use Gmail ID
            record_id = existing["id"] if existing else msg_id

            # Upsert listing (updates if exists, inserts if new)
            listing_record = {
                "id": record_id,
                "gmail_message_id": msg_id,
                "subject": email["subject"],
                "received_at": received_at,
                **listing
            }

            upsert_listing(conn, listing_record)
            count += 1

            if existing:
                print(f"  Updated: {email['subject'][:60]} (re-listed)")
            else:
                print(f"  Ingested: {email['subject'][:60]}")

    # Update sync state
    if count > 0:
        set_sync_state(conn, "last_email_timestamp", max_timestamp)
        print(f"\nIngested {count} new listings")

    return count
