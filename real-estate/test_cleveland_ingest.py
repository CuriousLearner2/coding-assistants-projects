"""Tests for Cleveland listing ingest validation."""
import pytest
from listings.cleveland_ingest import _is_valid_address, _is_university_circle


class TestAddressValidation:
    """Test address sanity checks."""

    def test_valid_addresses(self):
        """Accept properly formatted addresses."""
        valid = [
            "1234 Main St",
            "100 Oak Ave",
            "5000 Euclid Ave",
            "6514 Magnolia Ln",
            "1099 Stewart St",
        ]
        for addr in valid:
            assert _is_valid_address(addr), f"Should accept: {addr}"

    def test_invalid_addresses(self):
        """Reject addresses without house numbers or obviously invalid."""
        invalid = [
            "Random Rd",  # No house number
            "Main Street",  # No house number
            "St Clair Ave",  # No house number
            "",  # Empty
            "1234",  # Just a number
        ]
        for addr in invalid:
            assert not _is_valid_address(addr), f"Should reject: {addr}"

    def test_valid_format_but_suspicious(self):
        """Note: '2067 Random Rd' has valid format but is hallucinated address.

        Our validation checks address FORMAT only (house number + street name + type).
        Actual existence in Cleveland is handled by geocoding, not this validation.
        """
        # This passes format validation (it looks like a real address)
        assert _is_valid_address("2067 Random Rd"), "Valid format even if street doesn't exist"
        # But would fail geocoding when Claude tries to geocode it in Cleveland

    def test_address_with_apartment(self):
        """Accept addresses with apartment numbers."""
        assert _is_valid_address("1234 Main St Apt 5B")
        assert _is_valid_address("5000 Euclid Ave Suite 200")


class TestUniversityCircleFilter:
    """Test University Circle filtering with validation."""

    def test_rejects_invalid_address(self):
        """Property with invalid address should be filtered out."""
        prop = {
            "address": "Random Rd",
            "neighborhood": "University Circle",
            "city": "Cleveland",
            "state": "OH",
            "price": 300000,
        }
        assert not _is_university_circle(prop), "Should reject Random Rd address"

    def test_accepts_valid_address_with_uc_neighborhood(self):
        """Property with valid address and UC neighborhood should pass."""
        prop = {
            "address": "1234 Magnolia Ln",
            "neighborhood": "University Circle",
            "city": "Cleveland",
            "state": "OH",
            "price": 300000,
        }
        assert _is_university_circle(prop), "Should accept valid address in UC"

    def test_accepts_valid_address_with_cleveland_city(self):
        """Property with valid address and Cleveland city should pass."""
        prop = {
            "address": "5000 Euclid Ave",
            "neighborhood": "University Circle",
            "city": "Cleveland",
            "state": "OH",
            "price": 400000,
        }
        assert _is_university_circle(prop), "Should accept valid Cleveland address"

    def test_rejects_missing_address(self):
        """Property without address should be filtered."""
        prop = {
            "neighborhood": "University Circle",
            "city": "Cleveland",
            "price": 300000,
        }
        assert not _is_university_circle(prop), "Should reject missing address"

    def test_rejects_empty_address(self):
        """Property with empty address should be filtered."""
        prop = {
            "address": "",
            "neighborhood": "University Circle",
            "city": "Cleveland",
            "price": 300000,
        }
        assert not _is_university_circle(prop), "Should reject empty address"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
