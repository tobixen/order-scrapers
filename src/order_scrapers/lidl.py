"""Lidl purchase history, ingested from shopping-analyzer's output.

The fetching/parsing of Lidl receipts is done by the separate AGPL project
``shopping-analyzer`` (https://github.com/tobixen/shopping-analyzer), which
writes a ``lidl_receipts.json``. This module only *ingests* that file — it
copies no code from that project — normalizing each receipt into the shared
JSONL history store.

Lidl receipts carry no currency field (it depends on the store's country), so
``currency`` is left null here; set it downstream if you need it.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from . import store
from .cli import add_store_args, base_parser
from .config import cfg_path, shop_config

DEFAULT_INPUT = Path.home() / "shopping-analyzer" / "lidl_receipts.json"
DEFAULT_OUTPUT = Path.home() / "regnskap" / "lidl-history.jsonl"
SOURCE = "shopping-analyzer"


# --------------------------------------------------------------------------- #
# Pure parsers
# --------------------------------------------------------------------------- #
def eu_number(text: str | None) -> float | None:
    """Parse a European-formatted number ('1.234,56' / '50,39') to float."""
    if text is None:
        return None
    t = str(text).strip().replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def iso_date(text: str | None) -> str | None:
    """'2026.03.27' -> '2026-03-27' (None if it cannot be parsed)."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%Y.%m.%d").date().isoformat()
    except ValueError:
        return None


def normalize_item(item: dict) -> dict:
    return {
        "art_id": item.get("art_id"),
        "name": item.get("name"),
        "price": eu_number(item.get("price")),
        "quantity": eu_number(item.get("quantity")),
        "unit": item.get("unit"),
    }


def normalize_receipt(receipt: dict) -> dict:
    """Normalize one shopping-analyzer receipt into a stored record."""
    details = receipt.get("store_details") or {}
    return {
        "receipt_id": receipt.get("id"),
        "purchase_date": iso_date(receipt.get("purchase_date")),
        "store_name": receipt.get("store"),
        "store_locality": details.get("locality"),
        "store_postal_code": details.get("postalCode"),
        "currency": None,  # not present in the source data
        "total": eu_number(receipt.get("total_price_no_saving") or receipt.get("total_price")),
        "saved_amount": eu_number(receipt.get("saved_amount")),
        "line_items": [normalize_item(i) for i in receipt.get("items", []) if isinstance(i, dict)],
    }


def parse_receipts(data: list[dict]) -> list[dict]:
    """Normalize a lidl_receipts.json array, de-duped on receipt id."""
    records: list[dict] = []
    seen: set[str] = set()
    for receipt in data:
        rid = receipt.get("id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        records.append(normalize_receipt(receipt))
    return records


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def load_receipts(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(
            f"error: lidl_receipts.json not found: {path}\n"
            "Run shopping-analyzer (https://github.com/tobixen/shopping-analyzer) "
            "first, or pass its output path with --input."
        )
    except ValueError as exc:
        sys.exit(f"error: not valid JSON: {path}\n{exc}")
    if not isinstance(data, list):
        sys.exit(f"error: expected a JSON array of receipts: {path}")
    return data


def _describe(rec: dict) -> str:
    return (
        f"{rec['receipt_id']}  {rec['purchase_date']}  "
        f"{rec['store_name']}  {rec['total']}  ({len(rec['line_items'])} items)"
    )


def main() -> int:
    cfg = shop_config("lidl")
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=cfg_path(cfg, "input", DEFAULT_INPUT),
        help="shopping-analyzer lidl_receipts.json to ingest",
    )
    add_store_args(parser, cfg_path(cfg, "output", DEFAULT_OUTPUT))
    args = parser.parse_args()

    records = parse_receipts(load_receipts(args.input))
    if not records:
        sys.exit(f"error: no receipts found in {args.input}")
    return store.sync(
        records,
        args.output,
        key="receipt_id",
        source=SOURCE,
        update_all=args.update_all,
        dry_run=args.dry_run,
        describe=_describe,
    )


if __name__ == "__main__":
    raise SystemExit(main())
