"""
Tests for duplicate listing detection and handling.
Ensures that duplicate addresses are updated (not inserted) and only the most recent version is kept.
Run with: pytest test_duplicate_handling.py -v
"""
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import pytest

from listings.db import upsert_listing, get_listing_by_address, init_db


@pytest.fixture
def temp_db():
    """Create a temporary test database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(str(db_path))  # init_db expects a path string
        conn = sqlite3.connect(str(db_path))
        yield conn
        conn.close()


class TestDuplicateDetection:
    """Test duplicate address detection and handling."""

    def test_get_listing_by_address_finds_existing(self, temp_db):
        """get_listing_by_address should find an existing listing by address only."""
        listing = {
            "id": "test_id_1",
            "gmail_message_id": "msg_1",
            "subject": "Test",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "address": "123 Main St",
            "price": 500000,
            "beds": 3.0,
            "baths": 2.0,
        }
        upsert_listing(temp_db, listing)

        # Now search for it by address only
        found = get_listing_by_address(temp_db, "123 Main St")
        assert found is not None
        assert found["id"] == "test_id_1"

    def test_duplicate_address_updates_existing(self, temp_db):
        """When same address comes in with different price, it should update (not insert)."""
        # First version: 500k
        listing_v1 = {
            "id": "test_id_1",
            "gmail_message_id": "msg_1",
            "subject": "Listing: 123 Main St",
            "received_at": "2026-05-01T10:00:00+00:00",
            "address": "123 Main St",
            "price": 500000,
            "beds": 3.0,
            "baths": 2.0,
        }
        upsert_listing(temp_db, listing_v1)

        # Verify first version was inserted
        cursor = temp_db.execute("SELECT COUNT(*) FROM listings WHERE address = ?", ("123 Main St",))
        assert cursor.fetchone()[0] == 1

        # Now same address with updated price (updated price from listing)
        listing_v2 = {
            "id": "test_id_1",  # Reuse same ID since duplicate
            "gmail_message_id": "msg_1",  # Same email
            "subject": "Price reduced: 123 Main St",
            "received_at": "2026-05-02T15:00:00+00:00",
            "address": "123 Main St",
            "price": 475000,  # Price updated
            "beds": 3.0,
            "baths": 2.0,
        }
        upsert_listing(temp_db, listing_v2)

        # Should still be 1 record (updated, not inserted)
        cursor = temp_db.execute("SELECT COUNT(*) FROM listings WHERE address = ?", ("123 Main St",))
        assert cursor.fetchone()[0] == 1

        # Verify the price was updated
        cursor = temp_db.execute("SELECT price FROM listings WHERE address = ?", ("123 Main St",))
        price = cursor.fetchone()[0]
        assert price == 475000

    def test_new_address_inserts_new_record(self, temp_db):
        """Different address should insert new record, not update."""
        listing1 = {
            "id": "id_1",
            "gmail_message_id": "msg_1",
            "subject": "Test 1",
            "received_at": "2026-05-01T10:00:00+00:00",
            "address": "123 Main St",
            "price": 500000,
            "beds": 3.0,
            "baths": 2.0,
        }
        upsert_listing(temp_db, listing1)

        listing2 = {
            "id": "id_2",
            "gmail_message_id": "msg_2",
            "subject": "Test 2",
            "received_at": "2026-05-01T11:00:00+00:00",
            "address": "456 Oak Ave",  # Different address
            "price": 600000,
            "beds": 4.0,
            "baths": 3.0,
        }
        upsert_listing(temp_db, listing2)

        # Should have 2 records
        cursor = temp_db.execute("SELECT COUNT(*) FROM listings")
        assert cursor.fetchone()[0] == 2

    def test_duplicate_detection_by_address_ignores_price_beds(self, temp_db):
        """Duplicate detection should match on ADDRESS only, not price/beds combo."""
        # First listing
        listing1 = {
            "id": "id_v1",
            "gmail_message_id": "msg_1",
            "subject": "Original listing",
            "received_at": "2026-05-01T10:00:00+00:00",
            "address": "789 Pine Rd",
            "price": 750000,
            "beds": 4.0,
            "baths": 2.5,
        }
        upsert_listing(temp_db, listing1)

        # Same address, but different price and beds (common on Zillow updates)
        listing1_updated = {
            "id": "id_v1",
            "gmail_message_id": "msg_1",
            "subject": "Updated listing: price reduced",
            "received_at": "2026-05-02T10:00:00+00:00",
            "address": "789 Pine Rd",  # SAME address
            "price": 725000,  # Price changed
            "beds": 3.5,  # Beds re-counted
            "baths": 2.5,
        }
        upsert_listing(temp_db, listing1_updated)

        # Should still be 1 record (not duplicated despite price/beds change)
        cursor = temp_db.execute("SELECT COUNT(*) FROM listings WHERE address = ?", ("789 Pine Rd",))
        assert cursor.fetchone()[0] == 1

        # Verify it's the updated version
        cursor = temp_db.execute("SELECT price, beds FROM listings WHERE address = ?", ("789 Pine Rd",))
        price, beds = cursor.fetchone()
        assert price == 725000
        assert beds == 3.5

    def test_get_listing_returns_most_recent(self, temp_db):
        """When duplicate exists, get_listing_by_address should return the most recent."""
        # Manually insert two versions (testing the lookup, not upsert)
        import sqlite3
        old_version = {
            "id": "old_id",
            "gmail_message_id": "msg_old",
            "subject": "Old version",
            "received_at": "2026-05-01T10:00:00+00:00",
            "address": "999 Elm St",
            "price": 400000,
            "beds": 2.0,
            "baths": 1.0,
            "city": "Oakland",
            "state": "CA",
        }
        new_version = {
            "id": "new_id",
            "gmail_message_id": "msg_new",
            "subject": "New version",
            "received_at": "2026-05-02T15:00:00+00:00",
            "address": "999 Elm St",
            "price": 425000,
            "beds": 2.0,
            "baths": 1.0,
            "city": "Oakland",
            "state": "CA",
        }

        # Insert both (bypassing normal upsert to simulate pre-existing duplicates)
        for v in [old_version, new_version]:
            temp_db.execute("""
                INSERT INTO listings (
                    id, gmail_message_id, subject, received_at, address, price, beds, baths, city, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (v["id"], v["gmail_message_id"], v["subject"], v["received_at"], v["address"],
                  v["price"], v["beds"], v["baths"], v["city"], v["state"]))
        temp_db.commit()

        # get_listing_by_address should return the newer one
        found = get_listing_by_address(temp_db, "999 Elm St")
        assert found["id"] == "new_id"  # Should be the newer version
