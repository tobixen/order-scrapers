"""AliExpress order history from a captured order-list API dump.

AliExpress can't be scraped headless (signed mtop gateway + anti-bot), so the
capture happens inside the logged-in browser: the ``order-api-capture``
userscript (see ``userscripts/``) hooks fetch/XHR on ``/p/order/*`` and downloads
the raw ``mtop.aliexpress.trade.buyer.order.list`` JSON responses to one file.
This module parses that file into clean per-order records.

The order-list API already carries each order's line items with per-line prices
and a real ``currencyCode``, so no order-detail fetch is needed. Old/expired
orders carry no order-level total, but their line items still do.

The pure parsers (``iter_order_fields`` / ``normalize_order``) are pinned by
tests/test_aliexpress.py against a captured fixture.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from . import store
from .cli import add_store_args, base_parser
from .config import cfg_path, shop_config

DEFAULT_CAPTURE = Path.home() / "Downloads" / "aliexpress-order-api-capture.json"
DEFAULT_OUTPUT = Path.home() / "regnskap" / "aliexpress-history.jsonl"
ORDER_LIST_API = "mtop.aliexpress.trade.buyer.order.list"
SOURCE = "order.list"


# --------------------------------------------------------------------------- #
# Pure parsers
# --------------------------------------------------------------------------- #
def iso_date(text: str | None) -> str | None:
    """'Jan 24, 2025' -> '2025-01-24' (None if it cannot be parsed)."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%b %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_amount(format_price_info: str | None, fallback_text: str | None = None) -> float | None:
    """Parse AliExpress' ``formatPriceInfo`` ('€48.88|48|88') to 48.88.

    The field is '<display>|<integer>|<fraction>', which sidesteps thousands/
    decimal-separator ambiguity. Falls back to digits in ``fallback_text``.
    """
    if format_price_info and "|" in format_price_info:
        parts = format_price_info.split("|")
        if len(parts) >= 3:
            whole = parts[-2].replace(",", "").replace(".", "").strip()
            frac = parts[-1].strip()
            try:
                return float(f"{whole}.{frac}")
            except ValueError:
                pass
    if fallback_text:
        digits = re.sub(r"[^\d.]", "", fallback_text.replace(",", ""))
        try:
            return float(digits)
        except ValueError:
            return None
    return None


def abs_url(href: str | None) -> str | None:
    """'//www.aliexpress.com/x' / '/x' -> absolute https URL (None if empty)."""
    if not href:
        return None
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://www.aliexpress.com" + href
    return href


def iter_order_fields(capture: list[dict]) -> Iterator[dict]:
    """Yield the raw ``pc_om_list_order`` field dicts from a capture file."""
    for entry in capture:
        if ORDER_LIST_API not in (entry.get("url") or ""):
            continue
        try:
            components = json.loads(entry["body"])["data"]["data"]
        except (KeyError, ValueError, TypeError):
            continue
        if not isinstance(components, dict):
            continue
        for comp in components.values():
            if isinstance(comp, dict) and comp.get("tag") == "pc_om_list_order":
                fields = comp.get("fields")
                if isinstance(fields, dict) and fields.get("orderId"):
                    yield fields


def normalize_line(line: dict) -> dict:
    """Clean one ``orderLines`` entry into a stored line item."""
    return {
        "title": line.get("itemTitle"),
        "price": parse_amount(line.get("formatPriceInfo"), line.get("itemPriceText")),
        "currency": line.get("currencyCode"),
        "quantity": line.get("quantity"),
        "sku_id": line.get("skuId"),
        "product_id": line.get("productId"),
        "order_line_id": line.get("orderLineId"),
        "item_url": abs_url(line.get("itemDetailUrl")),
        "image_url": line.get("itemImgUrl"),
    }


def normalize_order(fields: dict) -> dict:
    """Turn a raw ``pc_om_list_order`` field dict into a stored record.

    Old/expired orders carry no order-level total or currency, but their line
    items still do, so currency falls back to the first line's ``currencyCode``.
    """
    lines = [normalize_line(line) for line in fields.get("orderLines", []) if isinstance(line, dict)]
    currency = fields.get("currencyCode")
    if not currency and lines:
        currency = lines[0].get("currency")
    return {
        "order_id": fields.get("orderId"),
        "order_date": iso_date(fields.get("orderDateText")),
        "status": (fields.get("statusText") or "").strip() or None,
        "store_name": fields.get("storeName"),
        "store_url": abs_url(fields.get("storePageUrl")),
        "currency": currency,
        "total": parse_amount(fields.get("formatPriceInfo"), fields.get("totalPriceText")),
        "order_detail_url": fields.get("orderDetailUrl"),
        "line_items": lines,
    }


def parse_capture(capture: list[dict]) -> list[dict]:
    """Parse a capture file into normalized records, de-duped on order id."""
    records: list[dict] = []
    seen: set[str] = set()
    for fields in iter_order_fields(capture):
        order_id = fields.get("orderId")
        if order_id in seen:
            continue
        seen.add(order_id)
        records.append(normalize_order(fields))
    return records


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def load_capture(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(
            f"error: capture file not found: {path}\n"
            "Run the order-api-capture userscript on the AliExpress order page "
            "and download the JSON, or pass its path as an argument."
        )
    except ValueError as exc:
        sys.exit(f"error: capture file is not valid JSON: {path}\n{exc}")
    if not isinstance(data, list):
        sys.exit(f"error: capture file should be a JSON array of responses: {path}")
    return data


def _describe(rec: dict) -> str:
    n = len(rec["line_items"])
    return (
        f"{rec['order_id']}  {rec['order_date']}  {rec['status']}  "
        f"{rec['total']} {rec['currency'] or ''}  ({n} line{'s' if n != 1 else ''})"
    )


def main() -> int:
    cfg = shop_config("aliexpress")
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "capture",
        type=Path,
        nargs="?",
        default=cfg_path(cfg, "capture", DEFAULT_CAPTURE),
        help="order-api-capture JSON file from the userscript",
    )
    add_store_args(parser, cfg_path(cfg, "output", DEFAULT_OUTPUT))
    args = parser.parse_args()

    records = parse_capture(load_capture(args.capture))
    if not records:
        sys.exit(f"error: no orders found in {args.capture}. Does it contain {ORDER_LIST_API} responses?")
    return store.sync(
        records,
        args.output,
        key="order_id",
        source=SOURCE,
        update_all=args.update_all,
        dry_run=args.dry_run,
        describe=_describe,
    )


if __name__ == "__main__":
    raise SystemExit(main())
