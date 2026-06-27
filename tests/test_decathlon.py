"""Tests for the decathlon module's pure bits (no network)."""

import argparse

from order_scrapers import decathlon as dec


def test_order_manager_for():
    assert dec.order_manager_for({"isWorkshopOrder": True}) == "workshop"
    assert dec.order_manager_for({"isOneOm": True}) == "oneOm"
    assert dec.order_manager_for({"isStoreOrder": True}) == "cube"
    assert dec.order_manager_for({}) == "cube"


def _args(**kw):
    defaults = {"no_details": False, "order_manager": None}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_build_record_injects_key_and_detail_source(monkeypatch):
    monkeypatch.setattr(dec, "get_json", lambda s, u, params=None: {"foo": "bar"})
    rec = dec.build_record(None, {"associationId": "A1", "orderNumber": "N1"}, _args())
    assert rec["associationId"] == "A1"  # dedup key always survives
    assert rec["_source"] == "detail"
    assert rec["foo"] == "bar"


def test_build_record_falls_back_to_list_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(dec, "get_json", boom)
    rec = dec.build_record(None, {"associationId": "A1", "orderNumber": "N1"}, _args())
    assert rec["_source"] == "list"
    assert rec["associationId"] == "A1"


def test_no_details_skips_fetch():
    rec = dec.build_record(None, {"associationId": "A1"}, _args(no_details=True))
    assert rec["_source"] == "list"
    assert rec["associationId"] == "A1"
