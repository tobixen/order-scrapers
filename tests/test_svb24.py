"""Parser tests for the svb24 module, against sanitized captured fixtures.

The fragile parts are the three pure parsers (orders-list HTML, order-detail
HTML, invoice PDF text) and the price merge. The fixtures have had personal
name/address data replaced with fake equivalents (see tests/fixtures).
"""

from conftest import FIXTURES

from order_scrapers import svb24 as svb


def _orders():
    return svb.parse_orders_list((FIXTURES / "orders.html").read_text(encoding="utf-8"))


def test_orders_list_finds_all_four_orders():
    orders = _orders()
    assert [o["orderId"] for o in orders] == ["3988629", "3912964", "3630868", "3451027"]
    assert {o["orderType"] for o in orders} == {"erp-order"}


def test_orders_list_dates_normalised_to_iso():
    by_id = {o["orderId"]: o for o in _orders()}
    assert by_id["3988629"]["date"] == "2026-06-25"
    assert by_id["3630868"]["date"] == "2025-06-02"
    assert by_id["3451027"]["date"] == "2024-11-18"


def test_orders_list_status_and_total():
    by_id = {o["orderId"]: o for o in _orders()}
    assert by_id["3988629"]["status"] == "Order is being packed"
    assert by_id["3988629"]["total"] == 567.86
    # Completed orders expose no total in the list heading.
    assert by_id["3630868"]["status"] == "Done"
    assert by_id["3630868"]["total"] is None


def _detail():
    html = (FIXTURES / "order-3630868-detail.html").read_text(encoding="utf-8")
    return svb.parse_order_detail(html)


def test_detail_summary_fields():
    d = _detail()
    assert d["payment"] == "Credit card"
    assert d["payment_status"] == "paid"
    assert d["dispatch_type"] == "UPS Standard"
    assert d["invoice_path"] == "/user/show-invoice/3630868/b1090251aff49bc5bce0fe0495868ec5"
    # Sanitized fixture: delivery city Teststad, billing city Musterstadt.
    assert "Teststad" in d["delivery_address"]
    assert "Musterstadt" in d["billing_address"]


def test_detail_line_items():
    items = _detail()["line_items"]
    assert len(items) == 5
    first = items[0]
    assert first["quantity"] == 1
    assert first["brand"] == "WHALE"
    assert first["name"] == "Service Kit for GULPER 220"
    assert first["item_number"] == "26611"
    assert first["model_number"] == "ak1550"
    assert first["ean"] == "0766478155009"
    assert first["product_path"] == "/en/whale-service-kit-for-gulper-220.html"
    assert [i["quantity"] for i in items] == [1, 4, 2, 1, 1]


def test_detail_decodes_html_entities_in_name():
    # The source double-encodes entities; CO&#8322; must become CO₂.
    names = [i["name"] for i in _detail()["line_items"]]
    assert any(n.startswith("CO₂") for n in names)
    assert not any("&#" in n for n in names)


def _invoice():
    text = (FIXTURES / "invoice-3630868.txt").read_text(encoding="utf-8")
    return svb.parse_invoice_text(text)


def test_invoice_header():
    inv = _invoice()
    assert inv["invoice_no"] == "25/3630868"
    assert inv["invoice_date"] == "2025-06-03"
    assert inv["order_date"] == "2025-06-02"
    assert inv["customer_no"] == "745986"
    assert inv["currency"] == "EUR"


def test_invoice_totals():
    inv = _invoice()
    assert inv["subtotal"] == 223.41
    assert inv["total"] == 268.09
    assert inv["vat"]["20.0"] == 44.68


def test_invoice_positions():
    pos = {p["item_number"]: p for p in _invoice()["positions"]}
    assert pos["26611"]["unit_price"] == 42.30
    assert pos["26611"]["quantity"] == 1.0
    assert pos["26611"]["amount"] == 42.30
    assert pos["53772"]["quantity"] == 4.0
    assert pos["53772"]["amount"] == 88.52
    assert pos["99901"]["amount"] is None  # free item
    assert pos["3"]["amount"] == 16.40  # shipping appears as a position


def test_merge_invoice_prices_into_line_items():
    detail = _detail()
    invoice = _invoice()
    svb.merge_invoice(detail, invoice)
    by_item = {i["item_number"]: i for i in detail["line_items"]}
    assert by_item["26611"]["unit_price"] == 42.30
    assert by_item["26611"]["amount"] == 42.30
    assert by_item["53772"]["amount"] == 88.52
    assert detail["invoice"]["total"] == 268.09
    assert "3" not in by_item  # shipping has no matching article
