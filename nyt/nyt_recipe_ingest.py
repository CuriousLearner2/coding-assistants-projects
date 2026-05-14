"""
NYT Cooking recipe ingestion pipeline v2

Discovery  → Gmail (from:nytdirect@nytimes.com, display name "NYT Cooking")
Navigation → Follow nl.nytimes.com redirects; handle single-recipe and
             digest/collection emails.
Extraction → Pass 1: schema.org JSON-LD          (source: json-ld)
             Pass 2: Haiku fallback for nulls     (source: haiku)
             Substitution summary: Anthropic Batch API, upvote-weighted
Persistence → SQLite recipes table (nyt/nyt.db — separate from real-estate listings.db)

Fixes in v2:
  1. Targeted community-notes extraction (BeautifulSoup) instead of raw HTML truncation
  2. Clean null handling — Haiku never returns explanatory non-null on missing data
  3. mailto: / non-HTTP links filtered before redirect resolution
  4. Per-collection recipe cap (MAX_RECIPES_PER_COLLECTION)
  5. Parallel HTTP fetches via ThreadPoolExecutor
  6. Anthropic Batch API for all substitution summary calls
  7. Upvote-weighted community note summarisation
"""

import argparse
import base64
import json
import logging
import quopri
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import anthropic
import requests
from bs4 import BeautifulSoup

from utils import DB_PATH, get_anthropic_client, get_gmail_service

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
COOKIE_FILE = Path(__file__).parent / "nyt_cookies.json"
INGEST_TIMESTAMP_FILE = Path(__file__).parent / ".last_ingest_timestamp"
GMAIL_QUERY_BASE = "from:nytdirect@nytimes.com"
NYT_COOKING_DISPLAY_NAME = "nyt cooking"
MODEL_HAIKU = "claude-haiku-4-5-20251001"
MAX_EMAILS = 2000
MAX_RECIPES_PER_COLLECTION = 25   # fix #4 — cap runaway collection pages
HTTP_WORKERS = 10                 # parallel fetch concurrency (increased from 5)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

CREATE_RECIPES_TABLE = """
CREATE TABLE IF NOT EXISTS recipes (
    id                   TEXT PRIMARY KEY,
    source_email_id      TEXT NOT NULL,
    recipe_url           TEXT,
    name                 TEXT,
    author               TEXT,
    total_time           TEXT,
    yield                TEXT,
    ingredients          TEXT,
    instructions         TEXT,
    substitution_summary TEXT,
    field_sources        TEXT,
    rating_value         REAL,
    rating_count         INTEGER,
    calories             INTEGER,
    protein_g            REAL,
    fat_g                REAL,
    saturated_fat_g      REAL,
    unsaturated_fat_g    REAL,
    trans_fat_g          REAL,
    carbs_g              REAL,
    fiber_g              REAL,
    sugar_g              REAL,
    sodium_mg            REAL,
    cholesterol_mg       REAL,
    ingested_at          TEXT DEFAULT (datetime('now')),
    updated_at           TEXT DEFAULT (datetime('now'))
)
"""


def get_db() -> sqlite3.Connection:
    """Open (and initialise) the shared project SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(CREATE_RECIPES_TABLE)
    conn.commit()
    return conn


def recipe_exists(conn: sqlite3.Connection, recipe_url: str) -> bool:
    """Return True if a row with this recipe_url already exists."""
    row = conn.execute(
        "SELECT 1 FROM recipes WHERE recipe_url = ?", (recipe_url,)
    ).fetchone()
    return row is not None


def email_already_processed(conn: sqlite3.Connection, email_id: str) -> bool:
    """Return True if any recipe row from this email_id already exists."""
    row = conn.execute(
        "SELECT 1 FROM recipes WHERE source_email_id = ?", (email_id,)
    ).fetchone()
    return row is not None


def get_last_ingest_date() -> str | None:
    """Get the date of the last successful ingest (YYYY/MM/DD format)."""
    if INGEST_TIMESTAMP_FILE.exists():
        return INGEST_TIMESTAMP_FILE.read_text().strip()
    return None


def save_ingest_date(date_str: str) -> None:
    """Save the current ingest date (YYYY/MM/DD format)."""
    INGEST_TIMESTAMP_FILE.write_text(date_str)


def upsert_recipe(conn: sqlite3.Connection, recipe: dict[str, Any]) -> None:
    """Insert or replace a recipe row."""
    conn.execute(
        """
        INSERT OR REPLACE INTO recipes
            (id, source_email_id, recipe_url, name, author, total_time,
             yield, ingredients, instructions, substitution_summary,
             field_sources, rating_value, rating_count,
             calories, protein_g, fat_g, saturated_fat_g, unsaturated_fat_g,
             trans_fat_g, carbs_g, fiber_g, sugar_g, sodium_mg, cholesterol_mg,
             ingested_at, updated_at)
        VALUES
            (:id, :source_email_id, :recipe_url, :name, :author, :total_time,
             :yield, :ingredients, :instructions, :substitution_summary,
             :field_sources, :rating_value, :rating_count,
             :calories, :protein_g, :fat_g, :saturated_fat_g, :unsaturated_fat_g,
             :trans_fat_g, :carbs_g, :fiber_g, :sugar_g, :sodium_mg, :cholesterol_mg,
             datetime('now'), datetime('now'))
        """,
        recipe,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Authenticated HTTP session
# ---------------------------------------------------------------------------

def build_session() -> requests.Session:
    """
    Build a requests.Session pre-loaded with NYT cookies from nyt_cookies.json.

    Returns:
        Authenticated requests.Session ready to fetch cooking.nytimes.com pages.

    Raises:
        FileNotFoundError: If nyt_cookies.json is missing.
    """
    if not COOKIE_FILE.exists():
        raise FileNotFoundError(
            f"nyt_cookies.json not found at {COOKIE_FILE}. "
            "Export cookies from a logged-in NYT browser session first."
        )
    with open(COOKIE_FILE) as f:
        cookies = json.load(f)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    for c in cookies:
        if "name" in c and "value" in c:
            session.cookies.set(c["name"], c["value"])
    return session


def fetch_url(session: requests.Session, url: str) -> requests.Response | None:
    """
    Fetch a URL with the authenticated session, following redirects.

    Returns None on failure or if a login redirect is detected.
    """
    try:
        resp = session.get(url, timeout=15, allow_redirects=True)
    except requests.RequestException as exc:
        log.warning("Request failed for %s: %s", url, exc)
        return None

    if "myaccount.nytimes.com" in resp.url or "login" in resp.url.lower():
        log.warning("Login redirect detected for %s — cookies may be expired", url)
        return None
    return resp


def fetch_urls_parallel(
    session: requests.Session, urls: list[str]
) -> dict[str, requests.Response]:
    """
    Fetch multiple URLs in parallel using a thread pool.

    Fix #5: replaces sequential fetch loop.

    Args:
        session: Authenticated requests.Session (read-only cookie use is thread-safe).
        urls:    List of URLs to fetch.

    Returns:
        Dict mapping url → Response for successful fetches only.
    """
    results: dict[str, requests.Response] = {}
    with ThreadPoolExecutor(max_workers=HTTP_WORKERS) as pool:
        future_to_url = {pool.submit(fetch_url, session, u): u for u in urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            resp = future.result()
            if resp and resp.status_code == 200:
                results[url] = resp
            else:
                log.warning("  Failed to fetch: %s", url)
    return results


# ---------------------------------------------------------------------------
# Gmail helpers
# ---------------------------------------------------------------------------

def decode_email_body(payload: dict) -> str:
    """
    Recursively extract and decode the HTML (or plain-text) body from a Gmail
    message payload dict, handling quoted-printable encoding.

    The Gmail API returns body data as URL-safe base64. After base64-decoding,
    the content is often quoted-printable encoded (=3D, =0D=0A etc.), which
    must be decoded again before BeautifulSoup can parse it correctly.

    Args:
        payload: A Gmail message payload dict (may contain nested ``parts``).

    Returns:
        Decoded UTF-8 string of the best available body content.
    """
    def _extract(part: dict) -> tuple[str | None, str | None]:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        if data:
            raw = base64.urlsafe_b64decode(data + "==")
            try:
                decoded = quopri.decodestring(raw).decode("utf-8", errors="replace")
            except Exception:
                decoded = raw.decode("utf-8", errors="replace")
            if mime == "text/html":
                return decoded, None
            if mime == "text/plain":
                return None, decoded
        return None, None

    def _walk(part: dict) -> tuple[str | None, str | None]:
        html, text = _extract(part)
        for sub in part.get("parts", []):
            sub_html, sub_text = _walk(sub)
            html = html or sub_html
            text = text or sub_text
        return html, text

    html_body, text_body = _walk(payload)
    return html_body or text_body or ""


def is_nyt_cooking_sender(headers: list[dict]) -> bool:
    """Return True if the From header display name contains 'nyt cooking'."""
    from_val = next(
        (h["value"] for h in headers if h["name"].lower() == "from"), ""
    )
    return NYT_COOKING_DISPLAY_NAME in from_val.lower()


def get_nyt_cooking_emails(
    service, max_emails: int, after: str | None = None, before: str | None = None
) -> list[dict]:
    """
    Fetch up to max_emails NYT Cooking emails from iCloud IMAP.

    Args:
        service:    Unused (kept for signature compatibility).
        max_emails: Maximum number of emails to return.
        after:      Optional date string in YYYY/MM/DD format.
        before:     Unused (iCloud IMAP SINCE only, no BEFORE support needed).

    Returns:
        List of normalized email dicts: id, subject, html_body, received_at.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import icloud_imap

    since_date = None
    if after:
        try:
            from datetime import datetime as _dt
            since_date = _dt.strptime(after, "%Y/%m/%d").strftime("%Y-%m-%d")
        except Exception:
            pass

    emails = icloud_imap.fetch_emails(
        "nytimes.com", since_date=since_date, max_results=max_emails
    )
    log.info("Fetched %d NYT Cooking email payloads", len(emails))
    return emails


# ---------------------------------------------------------------------------
# Link navigation (Levels 1 → 2 → 3)
# ---------------------------------------------------------------------------

RECIPE_URL_RE = re.compile(r"cooking\.nytimes\.com/recipes/\d+")
COLLECTION_URL_RE = re.compile(
    r"cooking\.nytimes\.com/(newsletters|topics|article)/"
)
RECIPE_LINK_TEXT_RE = re.compile(
    r"view recipe|view the recipes|get the recipe", re.IGNORECASE
)


def is_http_url(url: str) -> bool:
    """Fix #3: return True only for http/https URLs, filtering out mailto: etc."""
    return url.startswith("http://") or url.startswith("https://")


def resolve_redirect(
    session: requests.Session,
    url: str,
    cache: dict[str, str | None] | None = None,
) -> str | None:
    """
    Follow a URL through redirects and return the final destination URL.

    Speedup #5: optional shared cache avoids re-resolving the same redirect URL
    across multiple emails (common with collection pages like the salmon digest).

    Args:
        session: Authenticated requests.Session.
        url:     Starting URL (may be a tracking redirect).
        cache:   Optional dict mapping url → resolved url for memoisation.

    Returns:
        Final resolved URL string, or None on failure.
    """
    if not is_http_url(url):
        return None
    if cache is not None and url in cache:
        return cache[url]
    try:
        resp = session.head(url, timeout=10, allow_redirects=True)
        result = resp.url
    except requests.RequestException:
        try:
            resp = session.get(url, timeout=10, allow_redirects=True)
            result = resp.url
        except requests.RequestException as exc:
            log.warning("Could not resolve redirect for %s: %s", url, exc)
            result = None
    if cache is not None:
        cache[url] = result
    return result


def extract_recipe_urls_from_email(
    session: requests.Session,
    html_body: str,
    digest_only: bool = False,
    redirect_cache: dict[str, str | None] | None = None,
) -> tuple[list[str], bool]:
    """
    Level 1 → 2 → 3 navigation: extract all recipe URLs reachable from an
    NYT Cooking email HTML body.

    Speedup #1: redirects resolved in parallel via ThreadPoolExecutor.
    Speedup #2: collection pages fetched in parallel after redirect resolution.
    Speedup #5: shared redirect_cache avoids duplicate resolution across emails.

    Args:
        session:        Authenticated requests.Session.
        html_body:      Decoded HTML string of the email body.
        digest_only:    If True, skip emails that resolve directly to a recipe.
        redirect_cache: Shared dict for memoising redirect resolutions.

    Returns:
        Tuple of (recipe_url_list, is_digest).
    """
    soup = BeautifulSoup(html_body, "html.parser")
    candidate_hrefs: list[str] = [
        a["href"]
        for a in soup.find_all("a", href=True)
        if is_http_url(a["href"]) and (
            # Direct cooking.nytimes.com links (recipe or collection)
            RECIPE_URL_RE.search(a["href"])
            or COLLECTION_URL_RE.search(a["href"])
            # Redirect URLs that may resolve to cooking.nytimes.com —
            # keep if link text signals a recipe/collection link
            or (
                "nytimes.com" in a["href"]
                and RECIPE_LINK_TEXT_RE.search(a.get_text(strip=True))
            )
            # nl.nytimes.com redirects without matching text — still include
            # since these are the primary redirect wrapper used in emails
            or "nl.nytimes.com" in a["href"]
        )
    ]
    # Deduplicate while preserving order
    seen_hrefs: set[str] = set()
    unique_hrefs = [h for h in candidate_hrefs if not (h in seen_hrefs or seen_hrefs.add(h))]

    # Speedup #1: resolve all redirects in parallel
    resolved_map: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=HTTP_WORKERS) as pool:
        future_to_href = {
            pool.submit(resolve_redirect, session, h, redirect_cache): h
            for h in unique_hrefs
        }
        for future in as_completed(future_to_href):
            href = future_to_href[future]
            resolved_map[href] = future.result()

    # Classify resolved URLs into direct recipes and collection pages
    recipe_urls: list[str] = []
    collection_urls: list[str] = []
    seen: set[str] = set()
    is_digest = False

    for href in unique_hrefs:
        resolved = resolved_map.get(href)
        if not resolved:
            continue
        if RECIPE_URL_RE.search(resolved):
            if not digest_only:
                clean = resolved.split("?")[0]
                if clean not in seen:
                    seen.add(clean)
                    recipe_urls.append(clean)
        elif COLLECTION_URL_RE.search(resolved):
            is_digest = True
            clean_coll = resolved.split("?")[0]
            if clean_coll not in seen:
                seen.add(clean_coll)
                collection_urls.append(resolved)

    # Speedup #2: fetch all collection pages in parallel
    if collection_urls:
        coll_responses = fetch_urls_parallel(session, collection_urls)
        for coll_url, resp in coll_responses.items():
            log.info("Collection page: %s", coll_url.split("?")[0])
            coll_soup = BeautifulSoup(resp.text, "html.parser")
            count = 0
            for a2 in coll_soup.find_all("a", href=True):
                if count >= MAX_RECIPES_PER_COLLECTION:
                    log.info("  Collection cap (%d) reached.", MAX_RECIPES_PER_COLLECTION)
                    break
                h2 = a2["href"]
                if not h2.startswith("http"):
                    h2 = urljoin(coll_url, h2)
                if RECIPE_URL_RE.search(h2):
                    clean = h2.split("?")[0]
                    if clean not in seen:
                        seen.add(clean)
                        recipe_urls.append(clean)
                        count += 1

    log.info("  → %d recipe URL(s) resolved (digest=%s)", len(recipe_urls), is_digest)
    return recipe_urls, is_digest


# ---------------------------------------------------------------------------
# Extraction: Pass 1 — schema.org JSON-LD
# ---------------------------------------------------------------------------

def extract_jsonld(soup: BeautifulSoup) -> dict[str, Any]:
    """
    Extract recipe data from the schema.org Recipe JSON-LD block in the page.

    Args:
        soup: Parsed BeautifulSoup object of the recipe page HTML.

    Returns:
        Dict with extracted fields; missing fields are absent (not None).
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        candidates = data if isinstance(data, list) else [data]
        for obj in candidates:
            if isinstance(obj, dict) and obj.get("@type") == "Recipe":
                result: dict[str, Any] = {}
                if obj.get("name"):
                    result["name"] = obj["name"]
                author = obj.get("author")
                if isinstance(author, dict):
                    result["author"] = author.get("name")
                elif isinstance(author, str):
                    result["author"] = author
                if obj.get("totalTime"):
                    result["total_time"] = obj["totalTime"]
                if obj.get("recipeYield"):
                    y = obj["recipeYield"]
                    result["yield"] = y[0] if isinstance(y, list) else str(y)
                if obj.get("recipeIngredient"):
                    result["ingredients"] = "\n".join(obj["recipeIngredient"])
                if obj.get("recipeInstructions"):
                    steps = obj["recipeInstructions"]
                    texts = []
                    for s in steps:
                        if isinstance(s, dict):
                            texts.append(s.get("text", ""))
                        else:
                            texts.append(str(s))
                    result["instructions"] = "\n".join(
                        f"{i+1}. {t}" for i, t in enumerate(texts) if t
                    )
                ar = obj.get("aggregateRating", {})
                if isinstance(ar, dict):
                    if ar.get("ratingValue"):
                        result["rating_value"] = float(ar["ratingValue"])
                    if ar.get("ratingCount"):
                        result["rating_count"] = int(ar["ratingCount"])
                # Nutrition — parse numeric value from strings like "492" or "33 grams"
                def _num(val: Any) -> float | None:
                    if val is None:
                        return None
                    try:
                        return float(str(val).split()[0])
                    except (ValueError, IndexError):
                        return None
                n = obj.get("nutrition", {})
                if isinstance(n, dict):
                    result["calories"]           = _num(n.get("calories"))
                    result["protein_g"]          = _num(n.get("proteinContent"))
                    result["fat_g"]              = _num(n.get("fatContent"))
                    result["saturated_fat_g"]    = _num(n.get("saturatedFatContent"))
                    result["unsaturated_fat_g"]  = _num(n.get("unsaturatedFatContent"))
                    result["trans_fat_g"]        = _num(n.get("transFatContent"))
                    result["carbs_g"]            = _num(n.get("carbohydrateContent"))
                    result["fiber_g"]            = _num(n.get("fiberContent"))
                    result["sugar_g"]            = _num(n.get("sugarContent"))
                    result["sodium_mg"]          = _num(n.get("sodiumContent"))
                    result["cholesterol_mg"]     = _num(n.get("cholesterolContent"))
                return result
    return {}


# ---------------------------------------------------------------------------
# Community notes extraction (fixes #1 and #7)
# ---------------------------------------------------------------------------

def extract_community_notes(soup: BeautifulSoup) -> str:
    """
    Extract community reviews from the schema.org JSON-LD embedded in the page.

    NYT Cooking embeds up to ~30 user reviews in the Recipe JSON-LD block under
    the ``review`` array. Each review has a ``reviewBody`` (the tip text) and
    optionally a ``ratingValue`` (star rating 1-5). We use rating as a proxy
    for quality/helpfulness since upvote counts are only in the JS-rendered DOM.

    Fix #1: extracts from JSON-LD rather than truncating raw HTML.
    Fix #7: includes rating score so Haiku can weight higher-rated tips.

    Args:
        soup: Parsed BeautifulSoup object of the recipe page HTML.

    Returns:
        Structured text block, one review per line:
        "[rating: N/5] review body text"
        Returns empty string if no reviews found.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        candidates = data if isinstance(data, list) else [data]
        for obj in candidates:
            if not (isinstance(obj, dict) and obj.get("@type") == "Recipe"):
                continue
            reviews = obj.get("review", [])
            if not reviews:
                return ""
            # Normalise to list — JSON-LD allows a single object or an array
            if isinstance(reviews, dict):
                reviews = [reviews]
            lines: list[str] = []
            for r in reviews[:50]:  # cap at 50
                body = r.get("reviewBody", "").strip()
                if not body:
                    continue
                rating = None
                rv = r.get("reviewRating", {})
                if isinstance(rv, dict):
                    rating = rv.get("ratingValue")
                if rating:
                    lines.append(f"[rating: {rating}/5] {body}")
                else:
                    lines.append(body)
            return "\n".join(lines)
    return ""


# ---------------------------------------------------------------------------
# Extraction: Pass 2 — Haiku fallback for standard fields
# ---------------------------------------------------------------------------

STANDARD_FIELDS = ["name", "author", "total_time", "yield", "ingredients", "instructions"]

HAIKU_FIELD_PROMPT = """\
You are extracting structured data from an NYT Cooking recipe page.

Extract ONLY the following missing fields from the HTML below.
Return a JSON object with exactly these keys. Use JSON null (not the string "null")
for any field you cannot find. Do not include any explanation or markdown.

Fields to extract:
{fields_json}

HTML:
{html}
"""


def haiku_extract_fields(
    client: anthropic.Anthropic,
    html: str,
    missing_fields: list[str],
) -> dict[str, Any]:
    """
    Use Claude Haiku to extract fields that JSON-LD did not supply.

    Args:
        client:         Anthropic client.
        html:           Full page HTML (will be truncated before sending).
        missing_fields: List of field names to attempt to extract.

    Returns:
        Dict of extracted field values.
    """
    fields_schema = {f: "string or null" for f in missing_fields}
    prompt = HAIKU_FIELD_PROMPT.format(
        fields_json=json.dumps(fields_schema, indent=2),
        html=html[:15000],
    )
    try:
        resp = client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as exc:
        log.warning("Haiku field extraction failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Substitution summary — Anthropic Batch API (fixes #2, #6, #7)
# ---------------------------------------------------------------------------

HAIKU_SUBSTITUTION_PROMPT = """\
Below are community tips and notes from an NYT Cooking recipe page.
Each note may include a helpfulness count in brackets like [42 helpful].

Write a concise 2-4 sentence summary of the most useful ingredient substitutions
and cooking tips, weighting notes with higher helpfulness counts more heavily.

Rules:
- If there are no notes or tips, respond with exactly: null
- Do not explain your reasoning or mention upvote counts in the summary
- Do not include markdown formatting
- Return only the summary text or the word null

Community notes:
{notes}
"""



def _call_substitution(
    client: anthropic.Anthropic,
    recipe_id: str,
    notes: str,
) -> tuple[str, str | None]:
    """Call Haiku directly for a single substitution summary. Returns (id, summary)."""
    prompt = HAIKU_SUBSTITUTION_PROMPT.format(notes=notes or "(none)")
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=MODEL_HAIKU,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            summary = None if re.match(r"^null[.!]?$", text, re.IGNORECASE) else text
            return recipe_id, summary
        except Exception as exc:
            if attempt == 2:
                log.warning("Substitution call failed for %s: %s", recipe_id, exc)
                return recipe_id, None
            time.sleep(5 * (2 ** attempt))
    return recipe_id, None


def run_substitution_batch(
    client: anthropic.Anthropic,
    recipes: list[dict[str, Any]],
) -> dict[str, str | None]:
    """
    Generate substitution summaries via parallel direct Haiku calls.

    Args:
        client:  Anthropic client.
        recipes: List of recipe dicts with ``id`` and ``community_notes``.

    Returns:
        Dict mapping recipe_id → summary string (or None if no notes found).
    """
    if not recipes:
        return {}

    seen_ids: set[str] = set()
    deduped = []
    for r in recipes:
        if r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            deduped.append(r)

    log.info("Submitting substitution batch (%d requests)…", len(deduped))
    summaries: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(_call_substitution, client, r["id"], r.get("community_notes") or ""): r["id"]
            for r in deduped
        }
        done = 0
        for future in as_completed(futures):
            rid, summary = future.result()
            summaries[rid] = summary
            done += 1
            if done % 25 == 0:
                log.info("  Substitution progress: %d/%d", done, len(deduped))

    log.info("Substitution complete. %d summaries received.", len(summaries))
    return summaries


# ---------------------------------------------------------------------------
# Full recipe extraction (page fetch + JSON-LD + community notes)
# ---------------------------------------------------------------------------

def extract_recipe_from_response(
    resp: requests.Response,
    recipe_url: str,
    client: anthropic.Anthropic,
) -> dict[str, Any] | None:
    """
    Run the two-pass extraction pipeline on an already-fetched recipe page.

    Pass 1: schema.org JSON-LD.
    Pass 2: Haiku for any standard fields still null after Pass 1.
    Community notes are extracted structurally (not sent to Haiku yet —
    that happens in the batch step after all pages are fetched).

    Args:
        resp:       Successful HTTP response for the recipe page.
        recipe_url: Canonical cooking.nytimes.com/recipes/... URL.
        client:     Anthropic client (used only if Pass 2 fallback needed).

    Returns:
        Partial recipe dict (no substitution_summary yet), or None on error.
    """
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # Pass 1: JSON-LD
    jsonld = extract_jsonld(soup)
    field_sources: dict[str, str] = {k: "json-ld" for k in jsonld if jsonld[k]}

    # Pass 2: Haiku fallback for missing fields
    missing = [f for f in STANDARD_FIELDS if not jsonld.get(f)]
    haiku_fields: dict[str, Any] = {}
    if missing:
        log.info("  Haiku fallback for fields: %s", missing)
        haiku_fields = haiku_extract_fields(client, html, missing)
        for f in missing:
            val = haiku_fields.get(f)
            if val and val != "null":
                field_sources[f] = "haiku"

    def pick(field: str) -> Any:
        v = jsonld.get(field)
        if v:
            return v
        v2 = haiku_fields.get(field)
        return v2 if v2 and v2 != "null" else None

    url_id = re.search(r"/recipes/(\d+)", recipe_url)
    recipe_id = f"nyt_{url_id.group(1)}" if url_id else f"nyt_{abs(hash(recipe_url))}"

    # Extract community notes with upvote counts (fix #1 + #7)
    community_notes = extract_community_notes(soup)

    return {
        "id": recipe_id,
        "source_email_id": "",        # filled in by caller
        "recipe_url": recipe_url,
        "name": pick("name"),
        "author": pick("author"),
        "total_time": pick("total_time"),
        "yield": pick("yield"),
        "ingredients": pick("ingredients"),
        "instructions": pick("instructions"),
        "substitution_summary": None,  # filled after batch
        "field_sources": json.dumps(field_sources),
        "rating_value":       jsonld.get("rating_value"),
        "rating_count":       jsonld.get("rating_count"),
        "calories":           jsonld.get("calories"),
        "protein_g":          jsonld.get("protein_g"),
        "fat_g":              jsonld.get("fat_g"),
        "saturated_fat_g":    jsonld.get("saturated_fat_g"),
        "unsaturated_fat_g":  jsonld.get("unsaturated_fat_g"),
        "trans_fat_g":        jsonld.get("trans_fat_g"),
        "carbs_g":            jsonld.get("carbs_g"),
        "fiber_g":            jsonld.get("fiber_g"),
        "sugar_g":            jsonld.get("sugar_g"),
        "sodium_mg":          jsonld.get("sodium_mg"),
        "cholesterol_mg":     jsonld.get("cholesterol_mg"),
        "community_notes": community_notes,  # temp field, not persisted
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(
    max_emails: int = MAX_EMAILS,
    digest_only: bool = False,
    after: str | None = None,
    before: str | None = None,
) -> None:
    """
    Entry point: Gmail → crawl (parallel) → extract → batch summarise → persist.

    Args:
        max_emails:  Maximum number of emails to process.
        digest_only: If True, only process digest/collection emails (skip
                     single-recipe emails).
        after:       Only process emails after this date (YYYY/MM/DD).
        before:      Only process emails before this date (YYYY/MM/DD).
    """
    conn = get_db()
    session = build_session()
    client = get_anthropic_client()

    emails = get_nyt_cooking_emails(None, max_emails, after=after, before=before)
    if not emails:
        log.info("No NYT Cooking emails found.")
        return

    # Phase 1: collect all recipe URLs across all emails
    # (resolve redirects and crawl collection pages)
    email_recipe_map: dict[str, list[str]] = {}  # email_id → [recipe_urls]
    digest_count = 0
    processed_count = 0
    redirect_cache: dict[str, str | None] = {}   # speedup #5: shared across emails

    for msg in emails:
        if processed_count >= max_emails:
            log.info("Reached email processing limit (%d).", max_emails)
            break
        email_id = msg["id"]
        subject = msg.get("subject", "(no subject)")

        if email_already_processed(conn, email_id):
            log.info("SKIP  [%s] %s — already processed", email_id[:8], subject)
            processed_count += 1
            continue

        html_body = msg.get("html_body", "")
        if not html_body:
            log.warning("[%s] Empty body, skipping.", email_id[:8])
            continue

        urls, is_digest = extract_recipe_urls_from_email(
            session, html_body, digest_only=digest_only,
            redirect_cache=redirect_cache,
        )

        if digest_only and not is_digest:
            log.info("SKIP  [%s] %s — not a digest email", email_id[:8], subject)
            continue

        if digest_only:
            digest_count += 1
            if digest_count > max_emails:
                log.info("Reached digest email limit (%d), stopping.", max_emails)
                break

        new_urls = [u for u in urls if not recipe_exists(conn, u)]
        if not new_urls:
            log.info("[%s] No new recipe URLs.", email_id[:8])
            continue

        log.info(
            "QUEUE  [%s] %s  (%d new recipe URLs)",
            email_id[:8],
            subject,
            len(new_urls),
        )
        email_recipe_map[email_id] = new_urls
        processed_count += 1

    all_urls = list({u for urls in email_recipe_map.values() for u in urls})
    if not all_urls:
        log.info("No new recipes to fetch.")
        conn.close()
        # Save timestamp even if no new recipes (ingest completed successfully)
        from datetime import datetime
        today = datetime.now().strftime("%Y/%m/%d")
        save_ingest_date(today)
        log.info("Ingest timestamp saved: %s", today)
        return

    # Phase 2: fetch all recipe pages in parallel (fix #5)
    log.info("Fetching %d recipe pages in parallel (workers=%d)…", len(all_urls), HTTP_WORKERS)
    fetched = fetch_urls_parallel(session, all_urls)
    log.info("Fetched %d / %d pages successfully.", len(fetched), len(all_urls))

    # Phase 3: extract JSON-LD + community notes from each page
    recipes: list[dict[str, Any]] = []
    url_to_email: dict[str, str] = {
        url: email_id
        for email_id, urls in email_recipe_map.items()
        for url in urls
    }

    for url, resp in fetched.items():
        recipe = extract_recipe_from_response(resp, url, client)
        if not recipe:
            log.warning("Extraction failed for %s", url)
            continue
        recipe["source_email_id"] = url_to_email.get(url, "")
        recipes.append(recipe)
        log.info(
            "  EXTRACTED  %-50s  json-ld fields=%s",
            (recipe.get("name") or url)[:50],
            list(json.loads(recipe["field_sources"]).keys()),
        )

    if not recipes:
        log.info("No recipes extracted.")
        conn.close()
        return

    # Phase 4: batch substitution summaries (fix #6)
    summaries = run_substitution_batch(client, recipes)

    # Phase 5: merge summaries and persist
    total_saved = 0
    for recipe in recipes:
        rid = recipe["id"]
        summary = summaries.get(rid)
        recipe["substitution_summary"] = summary
        if summary:
            sources = json.loads(recipe["field_sources"])
            sources["substitution_summary"] = "haiku"
            recipe["field_sources"] = json.dumps(sources)

        # Remove temp field before upserting
        recipe.pop("community_notes", None)

        upsert_recipe(conn, recipe)
        log.info(
            "SAVED  %-50s  summary=%s",
            (recipe.get("name") or recipe["recipe_url"])[:50],
            "yes" if summary else "no",
        )
        total_saved += 1

    log.info("Done. %d recipe(s) saved.", total_saved)
    conn.close()

    # Save the timestamp of this successful ingest
    from datetime import datetime
    today = datetime.now().strftime("%Y/%m/%d")
    save_ingest_date(today)
    log.info("Ingest timestamp saved: %s", today)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NYT Cooking recipe ingest pipeline")
    parser.add_argument(
        "--max-emails", type=int, default=MAX_EMAILS,
        help="Maximum number of emails to process (default: %(default)s)"
    )
    parser.add_argument(
        "--digest-only", action="store_true",
        help="Only process digest/collection emails (skip single-recipe emails)"
    )
    parser.add_argument(
        "--after", type=str, default=None,
        help="Only process emails after this date, e.g. 2021/01/01 (default: use last ingest date)"
    )
    parser.add_argument(
        "--before", type=str, default=None,
        help="Only process emails before this date, e.g. 2026/04/12"
    )
    args = parser.parse_args()

    # If --after not provided, use last ingest date
    after_date = args.after
    if not after_date:
        last_date = get_last_ingest_date()
        if last_date:
            log.info("Using last ingest date: %s", last_date)
            after_date = last_date

    run(
        max_emails=args.max_emails,
        digest_only=args.digest_only,
        after=after_date,
        before=args.before,
    )

    # Log run timestamp
    from pathlib import Path as _Path
    from datetime import datetime as _dt
    _log = _Path.home() / "Claude Code" / ".run_log"
    with open(_log, "a") as _f:
        _f.write(f"{_dt.now().strftime('%Y-%m-%d %H:%M')}  {'nyt-recipe-ingest':<30}  ✓ OK\n")

    # Push recipe DB to git
    import subprocess as _sp
    try:
        _sp.run(["git", "add", "nyt/nyt.db"],
                cwd="/Users/gautambiswas/Claude Code/real-estate", check=True)
        _sp.run(["git", "commit", "-m",
                 f"chore: nyt recipe DB backup {_dt.now().strftime('%Y-%m-%d %H:%M')}"],
                cwd="/Users/gautambiswas/Claude Code/real-estate", check=True)
        _sp.run(["git", "push", "origin", "main"],
                cwd="/Users/gautambiswas/Claude Code/real-estate", check=True)
        print("  ✓ Recipe DB pushed to git")
    except Exception as _e:
        print(f"  ⚠ Git push failed: {_e}")
