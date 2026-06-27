"""Parser tests for the aliexpress module, against a captured fixture.

The fragile part is the pure parser that walks the mtop order-list component
tree into clean per-order records; that is what these tests pin.
"""

import json

from conftest import FIXTURES

from order_scrapers import aliexpress as ali


def _capture():
    return json.loads((FIXTURES / "aliexpress-order-list.json").read_text(encoding="utf-8"))


def _records():
    return {r["order_id"]: r for r in ali.parse_capture(_capture())}


def test_parses_all_orders_and_ignores_recommend_response():
    recs = _records()
    assert set(recs) == {"3048963030691559", "3044264490251559", "100426841571559"}


def test_single_item_eur_order():
    r = _records()["3048963030691559"]
    assert r["order_date"] == "2025-01-24"
    assert r["status"] == "Completed"
    assert r["currency"] == "EUR"
    assert r["total"] == 48.88
    assert r["store_name"] == "IS Official Store"
    assert len(r["line_items"]) == 1
    item = r["line_items"][0]
    assert item["price"] == 26.52
    assert item["quantity"] == 1
    assert item["currency"] == "EUR"
    assert item["item_url"] == "https://www.aliexpress.com/item/1005005219149777.html"
    assert item["title"].startswith("Step Down Power Supply Module")


def test_multi_item_order_keeps_per_line_prices():
    r = _records()["3044264490251559"]
    assert len(r["line_items"]) == 2
    prices = sorted(li["price"] for li in r["line_items"])
    assert prices == [1.39, 2.42]


def test_expired_order_has_no_total_but_currency_falls_back_to_line():
    r = _records()["100426841571559"]
    assert r["order_date"] == "2019-04-08"
    assert r["status"] == "Expired"
    assert r["total"] is None
    assert r["currency"] == "USD"
    assert r["line_items"][0]["price"] == 18.04


def test_status_trailing_space_stripped():
    assert ali.normalize_order({"orderId": "x", "statusText": "Canceled "})["status"] == "Canceled"


def test_amount_parser_handles_format_price_info():
    assert ali.parse_amount("€48.88|48|88") == 48.88
    assert ali.parse_amount("US $8.86|8|86") == 8.86
    assert ali.parse_amount(None, "€26.52") == 26.52
    assert ali.parse_amount(None, None) is None
