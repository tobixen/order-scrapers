"""Lidl purchase history, via shopping-analyzer's output.

The fetching/parsing of Lidl receipts is done by the separate AGPL project
``shopping-analyzer`` (https://github.com/tobixen/shopping-analyzer), which
writes a ``lidl_receipts.json``. This module *ingests* that file — it copies no
code from that project — normalizing each receipt into the shared JSONL history
store.

With ``--fetch`` it also *runs* that project first, so a Lidl update is one
command like the other shops', instead of the undocumented step it used to be::

    cd ~/regnskap && python ~/shopping-analyzer/get_data.py update \\
        --browser chromium --country bg

Running it is still spawning somebody else's program (no import, no copied
code): ``--analyzer`` points at the checkout, and its dependencies live wherever
``--python`` points. Like every other shop here, no credentials are stored — the
downloader lifts session cookies out of a logged-in browser profile, so log in
to Lidl+ in the browser first.

The fetch stays opt-in because it needs that separate project on disk; without
``--fetch`` this command behaves exactly as it always has and ingests whatever
``--input`` already holds.

Lidl receipts carry no currency field (it depends on the store's country), so
``currency`` is left null here; set it downstream if you need it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from . import store
from .cli import add_store_args, base_parser
from .config import cfg_path, shop_config

DEFAULT_INPUT = Path.home() / "shopping-analyzer" / "lidl_receipts.json"
DEFAULT_OUTPUT = Path.home() / "regnskap" / "lidl-history.jsonl"
DEFAULT_ANALYZER = Path.home() / "shopping-analyzer"
SOURCE = "shopping-analyzer"

#: The downloader writes this name, relative to its working directory — which is
#: why the manual step began with a ``cd``.
DOWNLOADER_OUTPUT = "lidl_receipts.json"

#: The downloader is a separate program with its own dependencies
#: (browser-cookie3, bs4, requests), installed against whichever interpreter you
#: run it with — not necessarily the one running this package.
DEFAULT_PYTHON = "python3"

Runner = Callable[[list[str], Path], int]


class DownloaderError(RuntimeError):
    """shopping-analyzer could not be run, or gave back something unusable."""


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
# Fetching (runs shopping-analyzer; imports nothing from it)
# --------------------------------------------------------------------------- #
def _subprocess_runner(cmd: list[str], cwd: Path) -> int:
    print(f"$ cd {cwd} && {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd).returncode


def fetch_receipts(
    analyzer: Path,
    receipts: Path,
    *,
    browser: str,
    country: str,
    python: str = DEFAULT_PYTHON,
    runner: Runner | None = None,
) -> list[dict]:
    """Run ``get_data.py update`` on a copy of *receipts*; return its result.

    The copy is the point. ``update`` decides what to download by reading the
    receipts file in its working directory, so it must see the stored history to
    fetch only new trips — but it rewrites that file as it goes, and the stored
    one is what everything downstream reads. On a copy, the real file is updated
    once, at the end, by :func:`merge_receipts`, or not at all.
    """
    # Absolute: the child runs in a scratch directory, where a path relative to
    # this process's working directory points at nothing.
    script = (analyzer / "get_data.py").resolve()
    if not script.is_file():
        raise DownloaderError(
            f"no get_data.py in {analyzer} — point --analyzer at a shopping-analyzer checkout: "
            "https://github.com/tobixen/shopping-analyzer"
        )
    run = runner or _subprocess_runner
    stored = load_receipts(receipts) if receipts.exists() else []

    with tempfile.TemporaryDirectory(prefix="lidl-fetch-") as tmp:
        work = Path(tmp)
        target = work / DOWNLOADER_OUTPUT
        if receipts.exists():
            shutil.copy(receipts, target)
        code = run([python, str(script), "update", "--browser", browser, "--country", country], work)
        if code != 0:
            raise DownloaderError(
                f"get_data.py failed (exit {code}). A stale session is the usual cause — log in to "
                "Lidl+ in the browser and run it again."
            )
        if not target.exists():
            raise DownloaderError("get_data.py exited cleanly but wrote nothing; that is not an empty history")
        try:
            fetched = read_receipts(target)
        except ValueError as exc:
            raise DownloaderError(f"get_data.py wrote an unusable {DOWNLOADER_OUTPUT}: {exc}") from exc

    # A short answer merges cleanly and invisibly, because merging only ever
    # adds — so losing receipts would go unnoticed. It is not a fetch outcome.
    if len(fetched) < len(stored):
        raise DownloaderError(
            f"get_data.py returned {len(fetched)} receipts but was given {len(stored)}; "
            "refusing a result that lost receipts"
        )
    return fetched


def merge_receipts(
    stored: list[dict],
    fetched: list[dict],
    *,
    fetched_at: str,
    update_all: bool = False,
) -> tuple[list[dict], list[str], list[str]]:
    """Merge a fetch into the stored raw receipts, by receipt id.

    Returns ``(merged, added_ids, changed_ids)``. New receipts are appended and
    stamped with ``_source``/``_fetchedAt``, the same bookkeeping keys
    :mod:`order_scrapers.store` writes on the JSONL side. A receipt already
    stored is left exactly as it is — it may carry hand corrections — and only
    reported; ``update_all`` (``--update-all``) is how you ask for the fetched
    copy instead. Stored order is never rearranged: it is by receipt id, which
    is not chronological, and consumers select by date.
    """
    merged = list(stored)
    index_of = {str(r["id"]): i for i, r in enumerate(merged) if r.get("id")}
    added: list[str] = []
    changed: list[str] = []

    for receipt in fetched:
        rid = receipt.get("id")
        if not rid:
            raise ValueError(f"fetched receipt has no id, so it cannot be de-duplicated: {receipt!r}")
        rid = str(rid)
        index = index_of.get(rid)
        if index is None:
            merged.append({**receipt, "_source": SOURCE, "_fetchedAt": fetched_at})
            index_of[rid] = len(merged) - 1
            added.append(rid)
            continue
        if store.content(merged[index]) == store.content(receipt):
            continue
        changed.append(rid)
        if update_all:
            merged[index] = {**receipt, "_source": SOURCE, "_fetchedAt": fetched_at, "_updatedAt": fetched_at}
    return merged, added, changed


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def read_receipts(path: Path) -> list[dict]:
    """Read a lidl_receipts.json array; ``ValueError`` if it is not one."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of receipts")
    return data


def load_receipts(path: Path) -> list[dict]:
    try:
        return read_receipts(path)
    except FileNotFoundError:
        sys.exit(
            f"error: lidl_receipts.json not found: {path}\n"
            "Run shopping-analyzer (https://github.com/tobixen/shopping-analyzer) "
            "first, or pass its output path with --input."
        )
    except ValueError as exc:
        sys.exit(f"error: {path}: {exc}")


def _describe(rec: dict) -> str:
    return (
        f"{rec['receipt_id']}  {rec['purchase_date']}  "
        f"{rec['store_name']}  {rec['total']}  ({len(rec['line_items'])} items)"
    )


def _fetch_into_input(args) -> list[dict]:
    """Refresh ``--input`` from Lidl before ingesting; return the receipts to ingest.

    Under ``--dry-run`` nothing is written, so the merged receipts are returned
    rather than left for the caller to re-read from the unchanged file.
    """
    if not args.country:
        sys.exit(
            "error: --fetch needs --country (or a [lidl] country in the config). shopping-analyzer "
            "defaults to Germany, and the wrong country's API answers 'no receipts' — which is "
            "exactly what a good fetch with nothing new looks like."
        )
    try:
        fetched = fetch_receipts(
            args.analyzer,
            args.input,
            browser=args.browser,
            country=args.country,
            python=args.python,
        )
    except DownloaderError as exc:
        sys.exit(f"error: {exc}")

    stored = load_receipts(args.input) if args.input.exists() else []
    try:
        merged, added, changed = merge_receipts(
            stored,
            fetched,
            fetched_at=datetime.now(UTC).isoformat(),
            update_all=args.update_all,
        )
    except ValueError as exc:
        sys.exit(f"error: {exc}")
    for rid in added:
        print(f"  + receipt {rid}")
    if changed:
        verb = "rewritten" if args.update_all else "left as they are"
        print(f"{len(changed)} stored receipt(s) came back different — {verb}: {', '.join(changed)}")
        if not args.update_all:
            print("  A stored receipt may carry hand corrections; pass --update-all to take the fetched copy.")
    if args.dry_run:
        print(f"dry-run: would write {len(merged)} receipt(s) to {args.input}")
        return merged
    if added or (changed and args.update_all):
        store.write_text_atomic(args.input, json.dumps(merged, ensure_ascii=False, indent=2))
        print(f"wrote {len(merged)} receipt(s) to {args.input}")
    else:
        print(f"no new receipts in {args.input}")
    return merged


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
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="run shopping-analyzer first to refresh --input (log in to Lidl+ in the browser beforehand)",
    )
    parser.add_argument(
        "--analyzer",
        type=Path,
        default=cfg_path(cfg, "analyzer", DEFAULT_ANALYZER),
        help=f"shopping-analyzer checkout to run with --fetch (default: {DEFAULT_ANALYZER})",
    )
    parser.add_argument(
        "--country",
        default=cfg.get("country"),
        help="two-letter country code of the Lidl account, e.g. bg (required with --fetch)",
    )
    parser.add_argument(
        "--browser",
        default=cfg.get("browser", "chromium"),
        help="browser profile shopping-analyzer takes Lidl+ session cookies from",
    )
    parser.add_argument(
        "--python",
        default=cfg.get("python", DEFAULT_PYTHON),
        help=f"interpreter shopping-analyzer's dependencies are installed for (default: {DEFAULT_PYTHON})",
    )
    add_store_args(parser, cfg_path(cfg, "output", DEFAULT_OUTPUT))
    args = parser.parse_args()

    raw = _fetch_into_input(args) if args.fetch else load_receipts(args.input)
    records = parse_receipts(raw)
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
