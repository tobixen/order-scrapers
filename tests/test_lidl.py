"""Tests for the lidl ingester, against a small synthetic fixture (no PII)."""

import json

from conftest import FIXTURES

from order_scrapers import lidl


def _records():
    data = json.loads((FIXTURES / "lidl-receipts-sample.json").read_text(encoding="utf-8"))
    return {r["receipt_id"]: r for r in lidl.parse_receipts(data)}


def test_dedupes_on_receipt_id():
    recs = _records()
    assert set(recs) == {"R1", "R2"}  # the duplicate R2 is dropped


def test_normalizes_receipt_fields():
    r = _records()["R1"]
    assert r["purchase_date"] == "2026-03-27"
    assert r["total"] == 12.50
    assert r["saved_amount"] == 1.20
    assert r["store_locality"] == "Teststad"
    assert r["store_postal_code"] == "9000"
    assert r["currency"] is None  # not present in the source
    assert len(r["line_items"]) == 2
    first = r["line_items"][0]
    assert first["name"] == "TEST MILK"
    assert first["price"] == 1.25
    assert first["quantity"] == 2.0
    assert first["unit"] == "stk"


def test_total_falls_back_to_total_price():
    # R2 has no total_price_no_saving, so total comes from total_price.
    assert _records()["R2"]["total"] == 5.0


def test_eu_number():
    assert lidl.eu_number("1.234,56") == 1234.56
    assert lidl.eu_number("50,39") == 50.39
    assert lidl.eu_number(None) is None
    assert lidl.eu_number("") is None
