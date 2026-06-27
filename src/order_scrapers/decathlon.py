"""Decathlon (decathlon.bg) purchase history.

Reads the logged-in session cookies from the local browser (browser_cookie3) and
replays the requests the browser makes:

  1. GET /web-engage/ajax/myPurchase  -> list of orders (associationId etc.)
  2. GET /web-engage/ajax/order       -> full detail per order

Plain runs are cheap: orders already stored are skipped before any detail
request. ``--update-all`` re-fetches every order in the window and rewrites
changed records.

Cookies are short-lived (Cloudflare); run with a fresh, logged-in browser
session. No secrets are embedded.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import browser_cookie3
import requests

from . import store
from .cli import add_store_args, base_parser
from .config import cfg_path, shop_config

BASE = "https://www.decathlon.bg/web-engage/ajax"
LIST_URL = f"{BASE}/myPurchase"
DETAIL_URL = f"{BASE}/order"
COOKIE_DOMAIN = "decathlon.bg"
DEFAULT_OUTPUT = Path.home() / "regnskap" / "decathlon-history.jsonl"

# Replicated verbatim from a working browser request; the UA and sec-ch-ua-*
# set must stay mutually consistent or Cloudflare may reject the request.
HEADERS = {
    "accept": "*/*",
    "accept-language": "bg",
    "cache-control": "no-cache",
    "content-type": "application/json",
    "dkt-ecom-country": "BG",
    "dkt-ecom-origin": "one-shop",
    "pragma": "no-cache",
    "priority": "u=1, i",
    "referer": "https://www.decathlon.bg/account/myPurchase",
    "sec-ch-ua": '"Not/A)Brand";v="99", "Chromium";v="148"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36"
    ),
}

BROWSERS = {
    "chromium": browser_cookie3.chromium,
    "chrome": browser_cookie3.chrome,
    "brave": browser_cookie3.brave,
    "firefox": browser_cookie3.firefox,
}


def order_manager_for(item: dict) -> str:
    """Pick the orderManager query value for a list item, from its flags."""
    if item.get("isWorkshopOrder"):
        return "workshop"
    if item.get("isOneOm"):
        return "oneOm"
    return "cube"  # store orders and the safe default


def load_cookies(browser: str) -> requests.cookies.RequestsCookieJar:
    loader = BROWSERS[browser]
    try:
        return loader(domain_name=COOKIE_DOMAIN)
    except Exception as exc:  # browser_cookie3 raises a grab-bag of errors
        sys.exit(
            f"error: could not read {browser} cookies for {COOKIE_DOMAIN}: {exc}\n"
            "Is the browser installed and have you logged in to decathlon.bg?"
        )


def get_json(session: requests.Session, url: str, params: dict | None = None) -> dict:
    resp = session.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} from {resp.url}\n{resp.text[:300]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise RuntimeError(f"non-JSON response from {resp.url} (Cloudflare challenge?)\n{resp.text[:300]}") from exc


def build_record(session: requests.Session, item: dict, args: argparse.Namespace) -> dict:
    """Return a stored record for a list item, enriched with detail if possible."""
    record = item
    source = "list"
    if not args.no_details:
        manager = args.order_manager or order_manager_for(item)
        try:
            record = get_json(
                session,
                DETAIL_URL,
                params={"associationId": item["associationId"], "orderManager": manager},
            )
            source = "detail"
        except RuntimeError as exc:
            sys.stderr.write(
                f"warning: detail fetch failed for order {item.get('orderNumber')} "
                f"({item['associationId']}); storing list data. {exc}\n"
            )
    # Guarantee the dedup key survives onto the stored record.
    return {**record, "associationId": item["associationId"], "_source": source}


def _describe(rec: dict) -> str:
    return f"{rec.get('orderNumber')} ({rec.get('_source')})  {rec.get('orderDate', '')}"


def parse_args() -> argparse.Namespace:
    cfg = shop_config("decathlon")
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "-b",
        "--browser",
        choices=sorted(BROWSERS),
        default=cfg.get("browser", "chromium"),
        help="browser whose cookies to use (default: chromium)",
    )
    parser.add_argument(
        "--size", type=int, default=cfg.get("size", 50), help="number of orders to request from the list endpoint"
    )
    parser.add_argument(
        "--no-details", action="store_true", help="store the list-level order summary only; skip per-order detail"
    )
    parser.add_argument(
        "--order-manager", default=cfg.get("order_manager"), help="force the orderManager value for detail requests"
    )
    add_store_args(parser, cfg_path(cfg, "output", DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cookies = load_cookies(args.browser)
    if not len(cookies):
        sys.exit(
            f"error: no cookies found for {COOKIE_DOMAIN} in {args.browser}. "
            "Log in to decathlon.bg in that browser first."
        )

    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.update(cookies)

    try:
        listing = get_json(session, LIST_URL, params={"size": args.size, "pending": "true"})
    except RuntimeError as exc:
        sys.exit(f"error: failed to fetch order list: {exc}")

    items = listing.get("items", [])
    hits = listing.get("hits")
    if isinstance(hits, int) and hits > len(items):
        sys.stderr.write(
            f"warning: server reports {hits} orders but only {len(items)} returned; "
            f"raise --size (currently {args.size}).\n"
        )
    # Oldest first, so newly-appended orders end up roughly chronological.
    items = [i for i in reversed(items) if i.get("associationId")]

    existing_ids = {r.get("associationId") for r in store.read_records(args.output)}
    records = []
    for item in items:
        if not args.update_all and item["associationId"] in existing_ids:
            continue
        records.append(build_record(session, item, args))

    return store.sync(
        records,
        args.output,
        key="associationId",
        source="detail",
        update_all=args.update_all,
        dry_run=args.dry_run,
        describe=_describe,
    )


if __name__ == "__main__":
    raise SystemExit(main())
