"""svb24.com order history.

Reads the logged-in session cookies from the local browser (browser_cookie3) and
replays the requests the browser makes:

  1. GET /user/orders                   -> HTML list of orders
  2. GET /user/ajax-order-details       -> HTML detail per order (line items, no prices)
  3. GET /user/show-invoice/<id>/<hash> -> invoice PDF (prices, totals, VAT)

The per-order record stores the structured line items enriched with per-line
prices parsed from the invoice PDF. svb24 sits behind Cloudflare, so this uses
``curl_cffi`` with Chrome TLS impersonation; cookies are short-lived (run with a
fresh, logged-in browser session). Invoice prices are extracted with
``pdftotext -layout`` (poppler), which must be on PATH. No secrets are embedded.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import browser_cookie3
from bs4 import BeautifulSoup
from curl_cffi import requests

from . import store
from .cli import add_store_args, base_parser
from .config import cfg_path, shop_config

BASE = "https://www.svb24.com"
ORDERS_URL = f"{BASE}/user/orders"
DETAIL_URL = f"{BASE}/user/ajax-order-details"
COOKIE_DOMAIN = "svb24.com"
IMPERSONATE = "chrome"
DEFAULT_OUTPUT = Path.home() / "regnskap" / "svb24-history.jsonl"

BROWSERS = {
    "chromium": browser_cookie3.chromium,
    "chrome": browser_cookie3.chrome,
    "brave": browser_cookie3.brave,
    "firefox": browser_cookie3.firefox,
}


# --------------------------------------------------------------------------- #
# Number / date helpers
# --------------------------------------------------------------------------- #
def _eu_number(text: str | None) -> float | None:
    """Parse a German-formatted number ('1.234,56' / '42,30') to float."""
    if not text:
        return None
    t = text.strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _web_number(text: str | None) -> float | None:
    """Parse a web price like '€567.86' or '€1,234.56' to float."""
    if not text:
        return None
    t = re.sub(r"[^\d.,]", "", text)
    if not t:
        return None
    if "," in t and "." in t:  # comma is the thousands separator
        t = t.replace(",", "")
    elif "," in t:  # lone comma is the decimal separator
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _iso_from_us(text: str) -> str:
    """'Jun 25, 2026' -> '2026-06-25' (unchanged if it cannot be parsed)."""
    try:
        return datetime.strptime(text.strip(), "%b %d, %Y").date().isoformat()
    except ValueError:
        return text.strip()


def _iso_from_de(text: str) -> str:
    """'03.06.2025' -> '2025-06-03' (unchanged if it cannot be parsed)."""
    try:
        return datetime.strptime(text.strip(), "%d.%m.%Y").date().isoformat()
    except ValueError:
        return text.strip()


# --------------------------------------------------------------------------- #
# Parsers (pure; covered by tests/test_svb24.py)
# --------------------------------------------------------------------------- #
def parse_orders_list(html: str) -> list[dict]:
    """Return the orders shown on /user/orders, newest first."""
    soup = BeautifulSoup(html, "lxml")
    orders: list[dict] = []
    for head in soup.select("div.panel-heading[data-full-route]"):
        query = parse_qs(urlsplit(head["data-full-route"]).query)
        labels: dict[str, str] = {}
        for block in head.select(".mysvb-header-info > div"):
            label = block.find("strong")
            value = block.find("span", class_="header-detail")
            if label and value:
                labels[label.get_text(strip=True).rstrip(":")] = value.get_text(strip=True)
        status_el = head.select_one(".mysvb-header-status .order-status")
        orders.append(
            {
                "orderId": (query.get("orderId") or [""])[0],
                "orderType": (query.get("orderType") or [""])[0],
                "date": _iso_from_us(labels.get("Date", "")),
                "status": status_el.get_text(strip=True) if status_el else None,
                "total": _web_number(labels.get("Total")),
            }
        )
    return orders


def _li_value(container, label: str) -> str | None:
    """First article-details <li> whose text starts with '<label>:'."""
    for li in container.select("ul.article-details li"):
        text = li.get_text(" ", strip=True)
        if text.lower().startswith(label.lower() + ":"):
            return text.split(":", 1)[1].strip()
    return None


def parse_order_detail(html: str) -> dict:
    """Parse an ajax-order-details fragment into summary + line items."""
    soup = BeautifulSoup(html, "lxml")
    detail: dict = {
        "payment": None,
        "payment_status": None,
        "dispatch_type": None,
        "delivery_address": None,
        "billing_address": None,
        "invoice_path": None,
        "line_items": [],
    }

    field_map = {
        "payment": "payment",
        "payment status": "payment_status",
        "dispatch type": "dispatch_type",
        "delivery address": "delivery_address",
        "billing address": "billing_address",
    }
    info = soup.select_one(".order-info-container")
    if info:
        for ul in info.find_all("ul"):
            values = [li.get_text(" ", strip=True) for li in ul.find_all("li")]
            values = [v for v in values if v]
            if len(values) < 2:
                continue
            key = field_map.get(values[0].lower())
            if not key:
                continue
            detail[key] = "\n".join(values[1:]) if "address" in key else values[1]

    invoice_link = soup.find("a", href=lambda h: h and "show-invoice" in h)
    if invoice_link:
        detail["invoice_path"] = invoice_link["href"]

    for art in soup.select(".article-container"):
        qty_el = art.select_one(".image-quantity")
        qty_match = re.search(r"\d+", qty_el.get_text() if qty_el else "")
        brand_el = art.select_one(".article-brand")
        name_el = art.select_one(".article-name")
        link_el = art.select_one(".article-image-container a")
        img_el = art.select_one(".article-image-container img")
        detail["line_items"].append(
            {
                "quantity": int(qty_match.group()) if qty_match else None,
                "brand": unescape(brand_el.get_text(strip=True)) if brand_el else None,
                "name": unescape(name_el.get_text(strip=True)) if name_el else None,
                "item_number": _li_value(art, "Item number"),
                "model_number": _li_value(art, "Model number"),
                "ean": _li_value(art, "EAN"),
                "product_path": link_el["href"] if link_el and link_el.has_attr("href") else None,
                "image_url": img_el["src"] if img_el and img_el.has_attr("src") else None,
            }
        )
    return detail


_HEADER_PATTERNS = {
    "invoice_no": r"Invoice No\.\s*:\s*(\S+)",
    "customer_no": r"Customer No\.\s*:\s*(\S+)",
}


def parse_invoice_text(text: str) -> dict:
    """Parse the ``pdftotext -layout`` output of an svb24 invoice PDF."""
    invoice: dict = {
        "invoice_no": None,
        "invoice_date": None,
        "order_date": None,
        "customer_no": None,
        "currency": "EUR",
        "subtotal": None,
        "total": None,
        "vat": {},
        "positions": [],
    }

    for key, pattern in _HEADER_PATTERNS.items():
        m = re.search(pattern, text)
        if m:
            invoice[key] = m.group(1)

    m = re.search(r"Iv-/Delivery Date\s*:\s*(\d{2}\.\d{2}\.\d{4})", text)
    if m:
        invoice["invoice_date"] = _iso_from_de(m.group(1))
    m = re.search(r"Date of Order\s*:\s*(\d{2}\.\d{2}\.\d{4})", text)
    if m:
        invoice["order_date"] = _iso_from_de(m.group(1))
    m = re.search(r"Total\s+([A-Z]{3})\s+incl", text)
    if m:
        invoice["currency"] = m.group(1)

    m = re.search(r"Subtotal\s+([\d.]+,\d+)", text)
    if m:
        invoice["subtotal"] = _eu_number(m.group(1))
    m = re.search(r"Total\s+[A-Z]{3}\s+incl\. VAT\s+([\d.]+,\d+)", text)
    if m:
        invoice["total"] = _eu_number(m.group(1))
    for rate, amount in re.findall(r"VAT\s+([\d.,]+)\s*%\s+([\d.]+,\d+)", text):
        invoice["vat"][str(_eu_number(rate))] = _eu_number(amount)

    invoice["positions"] = _parse_invoice_positions(text)
    return invoice


_EU_TOKEN = re.compile(r"[\d.]+,\d+")
_POS_LINE = re.compile(r"^(\d+)\s+(\S+)\s+(.*)$")


def _parse_invoice_positions(text: str) -> list[dict]:
    """Extract the line-item table (between the 'Pos' header and 'Subtotal')."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("Pos")), None)
    if start is None:
        return []

    positions: list[dict] = []
    for raw in lines[start + 1 :]:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("Subtotal"):
            break
        m = _POS_LINE.match(line.strip())
        if not m:  # wrapped description line -> append to the previous position
            if positions:
                positions[-1]["description"] += " " + line.strip()
            continue
        pos, item_no, rest = m.groups()
        money = _EU_TOKEN.findall(rest)
        description = _EU_TOKEN.sub("", rest).strip(" .")
        unit_price = quantity = amount = None
        if len(money) >= 3:  # unit price, ordered qty, amount
            unit_price = _eu_number(money[-3])
            quantity = _eu_number(money[-2])
            amount = _eu_number(money[-1])
        elif len(money) == 1:  # free item: only the ordered quantity
            quantity = _eu_number(money[-1])
        positions.append(
            {
                "pos": int(pos),
                "item_number": item_no,
                "description": description,
                "unit_price": unit_price,
                "quantity": quantity,
                "amount": amount,
            }
        )
    return positions


def merge_invoice(detail: dict, invoice: dict) -> None:
    """Attach the parsed invoice and copy per-line prices onto line items."""
    by_item = {p["item_number"]: p for p in invoice.get("positions", [])}
    for item in detail.get("line_items", []):
        pos = by_item.get(item.get("item_number"))
        if pos:
            item["unit_price"] = pos["unit_price"]
            item["amount"] = pos["amount"]
    detail["invoice"] = invoice


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def load_cookies(browser: str) -> dict[str, str]:
    loader = BROWSERS[browser]
    try:
        jar = loader(domain_name=COOKIE_DOMAIN)
    except Exception as exc:  # browser_cookie3 raises a grab-bag of errors
        sys.exit(
            f"error: could not read {browser} cookies for {COOKIE_DOMAIN}: {exc}\n"
            "Is the browser installed and have you logged in to svb24.com?"
        )
    return {c.name: c.value for c in jar if c.name}


def make_session(browser: str) -> requests.Session:
    cookies = load_cookies(browser)
    if not cookies:
        sys.exit(
            f"error: no cookies found for {COOKIE_DOMAIN} in {browser}. Log in to svb24.com in that browser first."
        )
    session = requests.Session(impersonate=IMPERSONATE)
    session.cookies.update(cookies)
    session.headers.update({"accept": "*/*", "accept-language": "en-US,en;q=0.9", "referer": ORDERS_URL})
    return session


def get_text(session: requests.Session, url: str, params: dict | None = None) -> str:
    resp = session.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(
            f"HTTP {resp.status_code} from {resp.url} (expired cookies / Cloudflare?)\n{resp.text[:300]}"
        )
    if "Just a moment" in resp.text[:1000]:
        raise RuntimeError(
            f"Cloudflare challenge on {resp.url}; cookies likely stale. Reload svb24.com in the browser and retry."
        )
    return resp.text


def fetch_invoice_text(session: requests.Session, path: str) -> str | None:
    """Download an invoice PDF and return its 'pdftotext -layout' output."""
    resp = session.get(f"{BASE}{path}", timeout=30)
    if resp.status_code != 200 or "pdf" not in resp.headers.get("content-type", ""):
        sys.stderr.write(f"warning: invoice fetch failed for {path} (HTTP {resp.status_code})\n")
        return None
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=resp.content,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        sys.stderr.write(f"warning: pdftotext failed for {path}: {exc}\n")
        return None
    return out.stdout.decode("utf-8", "replace")


def build_record(session: requests.Session, order: dict) -> dict:
    """Fetch detail + invoice for one list order and assemble the record."""
    record: dict = {
        "order_id": order["orderId"],
        "order_type": order["orderType"],
        "order_date": order["date"],
        "status": order["status"],
        "list_total": order["total"],
    }
    source = "list"
    try:
        detail = parse_order_detail(
            get_text(
                session,
                DETAIL_URL,
                params={"orderType": order["orderType"], "orderId": order["orderId"]},
            )
        )
        source = "detail"
        if detail.get("invoice_path"):
            text = fetch_invoice_text(session, detail["invoice_path"])
            if text:
                merge_invoice(detail, parse_invoice_text(text))
                source = "invoice"
        record.update(detail)
    except RuntimeError as exc:
        sys.stderr.write(f"warning: detail fetch failed for order {order['orderId']}; storing list data. {exc}\n")
    record["_source"] = source
    return record


def _describe(rec: dict) -> str:
    return f"{rec['order_id']} ({rec['_source']})  {rec['order_date']}  {rec['status']}"


def main() -> int:
    cfg = shop_config("svb24")
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "-b",
        "--browser",
        choices=sorted(BROWSERS),
        default=cfg.get("browser", "chromium"),
        help="browser whose cookies to use (default: chromium)",
    )
    add_store_args(parser, cfg_path(cfg, "output", DEFAULT_OUTPUT))
    args = parser.parse_args()

    session = make_session(args.browser)
    try:
        orders = parse_orders_list(get_text(session, ORDERS_URL))
    except RuntimeError as exc:
        sys.exit(f"error: failed to fetch order list: {exc}")
    if not orders:
        sys.exit("error: no orders found on /user/orders (logged in? cookies fresh?)")

    fetched_at = datetime.now(UTC).isoformat()
    existing_ids = {r.get("order_id") for r in store.read_records(args.output)}
    records = []
    for order in orders:
        if not args.update_all and order["orderId"] in existing_ids:
            continue
        records.append(build_record(session, order))

    return store.sync(
        records,
        args.output,
        key="order_id",
        source="list",
        update_all=args.update_all,
        dry_run=args.dry_run,
        fetched_at=fetched_at,
        describe=_describe,
    )


if __name__ == "__main__":
    raise SystemExit(main())
