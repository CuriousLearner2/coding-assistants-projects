#!/usr/bin/env python3
"""
Clean up duplicate listings from the database.
Keeps the most recent version of each address (by received_at).
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "listings" / "listings.db"


def deduplicate_listings():
    """Remove duplicate listings, keeping the most recent version."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("🔍 Analyzing duplicates...")

    # Get count of addresses with duplicates
    cursor.execute("""
        SELECT COUNT(*) FROM (
            SELECT address, COUNT(*) as cnt FROM listings
            GROUP BY address HAVING cnt > 1
        )
    """)
    duplicate_count = cursor.fetchone()[0]
    print(f"  Found {duplicate_count} addresses with duplicates")

    # Get total duplicate records to be deleted
    cursor.execute("""
        SELECT COUNT(*) FROM listings WHERE id NOT IN (
            SELECT id FROM (
                SELECT id FROM listings
                WHERE (address, received_at) IN (
                    SELECT address, MAX(received_at)
                    FROM listings
                    GROUP BY address
                )
            )
        )
    """)
    total_to_delete = cursor.fetchone()[0]
    print(f"  Will delete {total_to_delete} duplicate records")

    if total_to_delete == 0:
        print("✅ No duplicates to clean up")
        conn.close()
        return 0

    # Show some examples of duplicates before deletion
    print("\n📋 Examples of duplicates (keeping most recent):")
    cursor.execute("""
        SELECT address, COUNT(*) as cnt,
               MIN(received_at) as oldest,
               MAX(received_at) as newest
        FROM listings
        GROUP BY address HAVING cnt > 1
        ORDER BY cnt DESC
        LIMIT 5
    """)
    for row in cursor.fetchall():
        address, cnt, oldest, newest = row
        print(f"  {address}")
        print(f"    Duplicates: {cnt} | Oldest: {oldest} | Newest: {newest}")

    # Delete duplicates, keeping the most recent (use id as tiebreaker for same timestamp)
    print("\n🗑️  Deleting duplicates...")
    cursor.execute("""
        DELETE FROM listings WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY address ORDER BY received_at DESC, id DESC
                ) as rn
                FROM listings
            )
            WHERE rn > 1
        )
    """)
    conn.commit()
    deleted = cursor.rowcount

    # Verify cleanup
    cursor.execute("""
        SELECT COUNT(*) FROM (
            SELECT address, COUNT(*) as cnt FROM listings
            GROUP BY address HAVING cnt > 1
        )
    """)
    remaining_duplicates = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM listings")
    total_listings = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT address) FROM listings")
    unique_addresses = cursor.fetchone()[0]

    print(f"✅ Deleted {deleted} duplicate records")
    print(f"\n📊 After cleanup:")
    print(f"  Total listings: {total_listings}")
    print(f"  Unique addresses: {unique_addresses}")
    print(f"  Remaining duplicates: {remaining_duplicates}")

    if remaining_duplicates > 0:
        print(f"⚠️  Warning: {remaining_duplicates} addresses still have duplicates!")
        return 1

    conn.close()
    return 0


if __name__ == "__main__":
    try:
        result = deduplicate_listings()
        sys.exit(result)
    except Exception as e:
        print(f"❌ Error during deduplication: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
