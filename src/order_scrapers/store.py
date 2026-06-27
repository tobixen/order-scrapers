"""Shared append-only JSONL store for the shop history builders.

Every shop normalizes its data into a list of plain ``dict`` records, each
carrying a stable identity key (the order/receipt id). This module owns reading,
writing (atomic), de-duplication and the ``--update-all`` rewrite — the logic
that was previously copy-pasted across the standalone scripts.

Records gain bookkeeping keys when stored:
    _source    : where the record came from (shop-specific label)
    _fetchedAt : ISO timestamp of when it was (last) fetched/ingested
    _updatedAt : ISO timestamp, only on records changed by --update-all
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path


def read_records(path: Path) -> list[dict]:
    """Read an existing history file as an ordered list of records."""
    records: list[dict] = []
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue  # tolerate a partially-written trailing line
    return records


def content(rec: dict) -> dict:
    """The substantive payload of a record, minus the _* bookkeeping keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def write_records(path: Path, records: Iterable[dict]) -> None:
    """Atomically (re)write the whole history file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(path)  # atomic rewrite


def sync(
    records: list[dict],
    output: Path,
    *,
    key: str,
    source: str,
    update_all: bool = False,
    dry_run: bool = False,
    fetched_at: str | None = None,
    describe: Callable[[dict], str] | None = None,
) -> int:
    """Merge freshly-collected ``records`` into the history file at ``output``.

    ``key`` names the identity field (e.g. ``"order_id"``). Plain runs append
    only records whose key isn't already stored; ``update_all`` re-examines every
    stored record and rewrites those whose :func:`content` changed. Returns a
    process exit code (always 0 here, for ``raise SystemExit(sync(...))``).
    """
    fetched_at = fetched_at or datetime.now(UTC).isoformat()
    describe = describe or (lambda r: str(r.get(key)))
    if update_all:
        return _update_all(
            records, output, key=key, source=source, fetched_at=fetched_at, dry_run=dry_run, describe=describe
        )
    return _append(records, output, key=key, source=source, fetched_at=fetched_at, dry_run=dry_run, describe=describe)


def _stamp(rec: dict, *, source: str, fetched_at: str, updated: bool = False) -> dict:
    # Respect a per-record _source if the shop set one (e.g. svb24's
    # "list"/"detail"/"invoice" enrichment level); otherwise use the default.
    rec = {**rec}
    rec.setdefault("_source", source)
    rec["_fetchedAt"] = fetched_at
    if updated:
        rec["_updatedAt"] = fetched_at
    return rec


def _append(records, output, *, key, source, fetched_at, dry_run, describe) -> int:
    existing = read_records(output)
    seen = {r.get(key) for r in existing}
    new_records = []
    for rec in records:
        if rec.get(key) in seen:
            continue
        new_records.append(_stamp(rec, source=source, fetched_at=fetched_at))
        print(f"  + {describe(rec)}")

    if not new_records:
        print(f"no new records ({len(records)} collected, all already in {output})")
        return 0
    if dry_run:
        print(f"dry-run: would append {len(new_records)} record(s) to {output}")
        return 0
    write_records(output, existing + new_records)
    print(f"appended {len(new_records)} record(s) to {output}")
    return 0


def _update_all(records, output, *, key, source, fetched_at, dry_run, describe) -> int:
    existing = read_records(output)
    existing_ids = {r.get(key) for r in existing}
    fresh = {r.get(key): r for r in records}

    result: list[dict] = []
    changed = added = 0
    for old in existing:
        new = fresh.get(old.get(key))
        if new is None or content(new) == content(old):
            result.append(old)
            continue
        result.append(_stamp(new, source=source, fetched_at=fetched_at, updated=True))
        changed += 1
        print(f"  ~ {describe(new)}")

    for rec in records:
        if rec.get(key) in existing_ids:
            continue
        result.append(_stamp(rec, source=source, fetched_at=fetched_at))
        added += 1
        print(f"  + {describe(rec)}")

    if not changed and not added:
        print(f"up to date: no changes across {len(existing)} record(s) in {output}")
        return 0
    if dry_run:
        print(f"dry-run: would update {changed} and add {added} record(s) in {output}")
        return 0
    write_records(output, result)
    print(f"updated {changed} and added {added} record(s) in {output}")
    return 0
