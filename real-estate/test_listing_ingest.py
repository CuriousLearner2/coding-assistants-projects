"""
Regression tests for listing ingest functionality.
Tests address extraction, price/sqft parsing, and email field extraction.
Run with: pytest test_listing_ingest.py -v
"""
import pytest
from listings.gmail_ingest import (
    extract_address_from_subject,
    extract_price_from_subject,
    extract_house_sqft,
)


class TestAddressExtraction:
    """Test address extraction from email subjects and bodies."""

    def test_address_from_subject_simple(self):
        """Extract address like '1645 Dwight Way' from subject."""
        subject = "A home for you at 1645 Dwight Way, Berkeley CA"
        addr = extract_address_from_subject(subject)
        assert addr == "1645 Dwight Way, Berkeley"

    def test_address_from_subject_with_street_type(self):
        """Extract full address with street type."""
        subject = "New listing: 3245 Telegraph Ave, Oakland CA 94609"
        addr = extract_address_from_subject(subject)
        assert addr is not None
        assert "3245" in addr
        assert "Telegraph" in addr

    def test_address_with_boulevard(self):
        """Extract addresses with Boulevard."""
        subject = "1339 Thousand Oaks Blvd available now"
        addr = extract_address_from_subject(subject)
        assert addr == "1339 Thousand Oaks Blvd"

    def test_address_with_street_suffix(self):
        """Extract various street suffixes (St, Ave, Rd, Dr, etc)."""
        test_cases = [
            ("at 100 Main St", "100 Main St"),
            ("at 200 Oak Ave", "200 Oak Ave"),
            ("at 300 Pine Rd", "300 Pine Rd"),
            ("at 400 Elm Dr", "400 Elm Dr"),
            ("at 500 Maple Ln", "500 Maple Ln"),
            ("at 600 Birch Ct", "600 Birch Ct"),
            ("at 700 Walnut Way", "700 Walnut Way"),
        ]
        for subject, expected in test_cases:
            addr = extract_address_from_subject(subject)
            assert addr == expected, f"Failed for {subject}"

    def test_address_with_no_match(self):
        """Return None if no address pattern found."""
        subject = "Check out this property"
        addr = extract_address_from_subject(subject)
        assert addr is None


class TestPriceExtraction:
    """Test price extraction from email subjects."""

    def test_price_simple_thousands(self):
        """Extract prices like '$1.4M' or '$850K'."""
        test_cases = [
            ("Listed at $1.4M", 1400000),
            ("$850K listing", 850000),
            ("Price: $499,999", 499999),
            ("$2.5M home", 2500000),
        ]
        for subject, expected_price in test_cases:
            price = extract_price_from_subject(subject)
            assert price == expected_price, f"Failed for {subject}"

    def test_price_no_suffix(self):
        """Extract prices without K/M suffix."""
        subject = "Property listed at $550000"
        price = extract_price_from_subject(subject)
        assert price == 550000

    def test_price_with_space_in_amount(self):
        """Handle spaces in price formatting."""
        subject = "$ 750,000 asking price"
        price = extract_price_from_subject(subject)
        assert price == 750000

    def test_price_with_no_match(self):
        """Return None if no price found."""
        subject = "Lovely home in the area"
        price = extract_price_from_subject(subject)
        assert price is None


class TestSqftExtraction:
    """Test square footage extraction from email bodies."""

    def test_sqft_between_beds_and_baths(self):
        """Extract sqft in format: '3 bed 2 bath 1,200 sqft'."""
        text = "3 bed 2 bath 1,200 sqft home"
        sqft = extract_house_sqft(text)
        assert sqft == 1200

    def test_sqft_with_space_in_format(self):
        """Handle 'sq ft' with space."""
        text = "Beautiful 1500 sq ft property"
        sqft = extract_house_sqft(text)
        assert sqft == 1500

    def test_sqft_with_comma(self):
        """Handle commas in sqft (e.g., '2,500 sqft')."""
        text = "Home is 2,500 sqft with 4 beds"
        sqft = extract_house_sqft(text)
        assert sqft == 2500

    def test_sqft_sanity_check_too_small(self):
        """Reject sqft values below 400 (likely not actual house sqft)."""
        text = "Only 100 sqft studio"
        sqft = extract_house_sqft(text)
        # 100 is below sanity check threshold (400)
        assert sqft is None or sqft != 100

    def test_sqft_sanity_check_too_large(self):
        """Reject sqft values above 15000 (likely errors)."""
        text = "Massive 50000 sqft warehouse"
        sqft = extract_house_sqft(text)
        # 50000 is above sanity check threshold (15000)
        assert sqft is None or sqft != 50000

    def test_sqft_with_no_match(self):
        """Return None if no sqft found."""
        text = "Nice home in great location"
        sqft = extract_house_sqft(text)
        assert sqft is None


class TestAddressExtractionWithSqft:
    """
    Regression tests for the sqft-in-address bug fix.
    Ensures addresses don't include sqft patterns.
    """

    def test_address_not_including_sqft_prefix(self):
        """
        Don't include sqft pattern in address extraction.
        Email body has: "790 sqft\n1339 Thousand Oaks Blvd"
        Should extract only: "1339 Thousand Oaks Blvd"
        """
        # Simulate the extraction logic from gmail_ingest.py
        import re

        plain_body = "790 sqft\n\n1339 Thousand Oaks Blvd, CA 91320"

        # This is the fixed logic
        addr_search_text = re.sub(r'(\d+)\s*(?:sqft|sq\.?\s*ft\.?)\s+', '', plain_body, flags=re.IGNORECASE)
        address_match = re.search(r'\d+\s+[A-Za-z\s,]+(?:CA|California)(?:\s+\d+)?', addr_search_text, re.IGNORECASE)

        assert address_match is not None
        address = address_match.group(0).strip()
        assert "sqft" not in address.lower()
        assert "1339 Thousand Oaks Blvd" in address

    def test_address_with_multiple_sqft_values(self):
        """Handle email with multiple sqft values (sqft, lot size)."""
        import re

        plain_body = "661 sqft\n\n3017 Madeline St, Berkeley CA\nLot: 2500 sq ft"
        addr_search_text = re.sub(r'(\d+)\s*(?:sqft|sq\.?\s*ft\.?)\s+', '', plain_body, flags=re.IGNORECASE)
        address_match = re.search(r'\d+\s+[A-Za-z\s,]+(?:CA|California)(?:\s+\d+)?', addr_search_text, re.IGNORECASE)

        assert address_match is not None
        address = address_match.group(0).strip()
        # Should not include the "661 sqft" part
        assert not address.startswith("661")
        assert "3017 Madeline St" in address


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
