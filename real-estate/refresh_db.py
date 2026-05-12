#!/usr/bin/env python3
"""
Database refresh with enrichment.
Runs ingest, then runs enrichment directly (no background hooks).
"""

import subprocess
import sqlite3
import time
import sys
import os
from datetime import datetime
from pathlib import Path

from listings.earthquake_hazard import assess_earthquake_risk
from listings.fire_hazard import get_fire_hazard_zone
from listings.geocoder import run_geocoder
from listings.bpn_enrichment import run_bpn_enrichment

DB_PATH = "listings/listings.db"

def run_enrichment(conn):
    """Run enrichment pipeline directly."""
    print("\nStarting enrichment pipeline...\n")

    cursor = conn.cursor()

    # Get last enrichment timestamp
    cursor.execute("SELECT value FROM sync_state WHERE key = 'last_enrichment_completed'")
    result = cursor.fetchone()
    last_enrichment = result[0] if result else "2020-01-01T00:00:00"
    enrichment_start_time = datetime.utcnow().isoformat()

    step_times = {}

    # Step 1: Assign neighborhoods
    print("Step 1: Assigning neighborhoods...")
    t = time.time()
    cursor.execute("""
        SELECT COUNT(*) FROM listings WHERE neighborhood IS NULL AND address IS NOT NULL
    """)
    unassigned = cursor.fetchone()[0]
    if unassigned > 0:
        cursor.execute("""
            SELECT id, city FROM listings WHERE neighborhood IS NULL AND address IS NOT NULL
        """)
        for listing_id, city in cursor.fetchall():
            neighborhood = city if city else None
            if neighborhood:
                cursor.execute("UPDATE listings SET neighborhood = ? WHERE id = ?", (neighborhood, listing_id))
        conn.commit()
        print(f"  ✓ Assigned {unassigned} neighborhoods")
    step_times['neighborhoods'] = time.time() - t

    # Step 2: Geocode
    print("Step 2: Geocoding addresses...")
    t = time.time()
    geocoded = run_geocoder(conn)
    print(f"  ✓ Geocoded {geocoded} listings")
    step_times['geocoding'] = time.time() - t

    # Step 3: Seismic and fire hazard
    print("Step 3: Enriching with seismic and fire hazard...")
    t = time.time()
    cursor.execute("""
        SELECT id, address, latitude, longitude
        FROM listings
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        AND (seismic_zone IS NULL OR fire_zone IS NULL)
        ORDER BY received_at DESC
    """)

    properties = cursor.fetchall()
    if properties:
        print(f"  Enriching {len(properties)} listings...")
        for i, (prop_id, address, lat, lon) in enumerate(properties):
            try:
                if (i + 1) % 25 == 0:
                    print(f"    [{i + 1}/{len(properties)}] processed...")

                seismic = assess_earthquake_risk(lat, lon)
                fire = get_fire_hazard_zone(lat, lon)
                fire_zone = fire.get('zone_name') if fire else None
                fire_score = fire.get('risk_score') if fire else None

                conn.execute("""
                    UPDATE listings
                    SET seismic_zone = ?, seismic_risk_score = ?, fire_zone = ?, fire_risk_score = ?
                    WHERE id = ?
                """, (seismic['seismic_zone'], seismic['risk_score'], fire_zone, fire_score, prop_id))
            except Exception as e:
                pass  # Skip on error

        conn.commit()
        print("  ✓ Risk enrichment complete")
    else:
        print("  ℹ No listings need risk enrichment")

    step_times['hazard'] = time.time() - t

    # Step 4: BPN enrichment (only new neighborhoods)
    print("Step 4: Enriching with BPN sentiment (new neighborhoods only)...")
    t = time.time()
    try:
        bpn_count = run_bpn_enrichment(conn, since_timestamp=last_enrichment)
        print(f"  ✓ Analyzed {bpn_count} neighborhoods")
    except Exception as e:
        print(f"  ⚠ BPN enrichment skipped: {e}")

    step_times['bpn'] = time.time() - t

    # Summary
    total_time = sum(step_times.values())
    print(f"\n{'='*40}")
    print("ENRICHMENT TIMING:")
    for step, elapsed in step_times.items():
        print(f"  {step:12s}: {elapsed:6.1f}s")
    print(f"  {'TOTAL':12s}: {total_time:6.1f}s")
    print(f"{'='*40}\n")

    # Update completion timestamp
    conn.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
        ("last_enrichment_completed", enrichment_start_time)
    )
    conn.commit()

    return True

def main():
    print("Starting database refresh...\n")

    # Source ~/.zshrc to load environment variables (GOOGLE_MAPS_API_KEY, ANTHROPIC_API_KEY, etc.)
    zshrc_path = Path.home() / ".zshrc"
    if zshrc_path.exists():
        with open(zshrc_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    # Parse export lines and set environment
                    assignment = line[7:]  # Remove "export "
                    if "=" in assignment:
                        key, value = assignment.split("=", 1)
                        key = key.strip()
                        value = value.strip()
                        # Remove quotes if present (handle both " and ')
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        if key and value:
                            os.environ[key] = value

    # Run ingest directly (skip shell script to avoid PATH issues)
    from listings.batch_ingest import run_batch_ingest
    from listings.cleveland_ingest import run_cleveland_ingest

    conn = sqlite3.connect(DB_PATH)
    try:
        # East Bay ingest
        ingest_count = run_batch_ingest(conn)
        if ingest_count > 0:
            print(f"\n✓ Successfully ingested {ingest_count} new listings")
        else:
            print("\nℹ No new East Bay listings found")

        # Cleveland / University Circle ingest
        print("\n--- Cleveland University Circle ---")
        cleveland_count = run_cleveland_ingest(conn)
        if cleveland_count > 0:
            print(f"✓ Successfully ingested {cleveland_count} new Cleveland listings")
        else:
            print("ℹ No new Cleveland listings found")

        conn.close()
    except Exception as e:
        print(f"\n✗ Ingest failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Run enrichment directly (no hook, no waiting)
    conn = sqlite3.connect(DB_PATH)
    try:
        if run_enrichment(conn):
            print("✓ Database refresh complete")
            return 0
        else:
            print("✗ Enrichment failed")
            return 1
    finally:
        conn.close()

if __name__ == "__main__":
    sys.exit(main())
