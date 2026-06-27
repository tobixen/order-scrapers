"""Tests for the shared JSONL store: append/dedup/update-all/dry-run."""

from order_scrapers import store


def test_append_new_records_stamps_bookkeeping(tmp_path):
    out = tmp_path / "h.jsonl"
    store.sync([{"id": "1", "v": 1}, {"id": "2", "v": 2}], out, key="id", source="t")
    got = store.read_records(out)
    assert [r["id"] for r in got] == ["1", "2"]
    assert all(r["_source"] == "t" and "_fetchedAt" in r for r in got)


def test_append_skips_existing_without_updating(tmp_path):
    out = tmp_path / "h.jsonl"
    store.sync([{"id": "1", "v": 1}], out, key="id", source="t")
    store.sync([{"id": "1", "v": 99}, {"id": "2", "v": 2}], out, key="id", source="t")
    got = {r["id"]: r for r in store.read_records(out)}
    assert set(got) == {"1", "2"}
    assert got["1"]["v"] == 1  # append mode never rewrites an existing record


def test_update_all_rewrites_changed_and_adds_new(tmp_path):
    out = tmp_path / "h.jsonl"
    store.sync([{"id": "1", "v": 1}, {"id": "2", "v": 2}], out, key="id", source="t")
    store.sync([{"id": "1", "v": 9}, {"id": "3", "v": 3}], out, key="id", source="t", update_all=True)
    got = {r["id"]: r for r in store.read_records(out)}
    assert got["1"]["v"] == 9  # changed record rewritten
    assert "_updatedAt" in got["1"]
    assert got["2"]["v"] == 2  # outside the fresh window, untouched
    assert "_updatedAt" not in got["2"]
    assert got["3"]["v"] == 3  # newly added


def test_preserves_per_record_source(tmp_path):
    out = tmp_path / "h.jsonl"
    store.sync([{"id": "1", "_source": "invoice"}], out, key="id", source="default")
    assert store.read_records(out)[0]["_source"] == "invoice"


def test_dry_run_writes_nothing(tmp_path):
    out = tmp_path / "h.jsonl"
    store.sync([{"id": "1"}], out, key="id", source="t", dry_run=True)
    assert not out.exists()


def test_content_strips_bookkeeping_keys():
    rec = {"id": "1", "v": 2, "_source": "t", "_fetchedAt": "x"}
    assert store.content(rec) == {"id": "1", "v": 2}
