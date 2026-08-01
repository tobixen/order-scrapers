"""Tests for the lidl ingester, against a small synthetic fixture (no PII)."""

import json
from pathlib import Path

import pytest
from conftest import FIXTURES

from order_scrapers import lidl, store


def _records():
    data = json.loads((FIXTURES / "lidl-receipts-sample.json").read_text(encoding="utf-8"))
    return {r["receipt_id"]: r for r in lidl.parse_receipts(data)}


def test_dedupes_on_receipt_id():
    recs = _records()
    assert set(recs) == {"R1", "R2"}  # the duplicate R2 is dropped


def test_normalizes_receipt_fields():
    r = _records()["R1"]
    assert r["purchase_date"] == "2026-03-27"
    assert r["total"] == 12.50
    assert r["saved_amount"] == 1.20
    assert r["store_locality"] == "Teststad"
    assert r["store_postal_code"] == "9000"
    assert r["currency"] is None  # not present in the source
    assert len(r["line_items"]) == 2
    first = r["line_items"][0]
    assert first["name"] == "TEST MILK"
    assert first["price"] == 1.25
    assert first["quantity"] == 2.0
    assert first["unit"] == "stk"


def test_total_falls_back_to_total_price():
    # R2 has no total_price_no_saving, so total comes from total_price.
    assert _records()["R2"]["total"] == 5.0


def test_eu_number():
    assert lidl.eu_number("1.234,56") == 1234.56
    assert lidl.eu_number("50,39") == 50.39
    assert lidl.eu_number(None) is None
    assert lidl.eu_number("") is None


# --------------------------------------------------------------------------- #
# --fetch: driving shopping-analyzer's downloader
# --------------------------------------------------------------------------- #
def _raw(rid, date="2026.04.05", total="10,00", **extra):
    return {"id": rid, "purchase_date": date, "total_price": total, "items": [], **extra}


@pytest.fixture
def analyzer(tmp_path):
    """A stand-in shopping-analyzer checkout: only get_data.py has to be there."""
    d = tmp_path / "shopping-analyzer"
    d.mkdir()
    (d / "get_data.py").write_text("# stand-in\n", encoding="utf-8")
    return d


@pytest.fixture
def receipts(tmp_path):
    path = tmp_path / "lidl_receipts.json"
    path.write_text(json.dumps([_raw("R1"), _raw("R2")]), encoding="utf-8")
    return path


def test_fetch_gives_the_downloader_what_is_already_stored(analyzer, receipts):
    """``get_data.py update`` decides what to fetch from the file in its working
    directory; without it, every trip is downloaded again."""
    seen = {}

    def runner(cmd, cwd):
        seen["existing"] = json.loads((cwd / "lidl_receipts.json").read_text(encoding="utf-8"))
        seen["cmd"] = cmd
        (cwd / "lidl_receipts.json").write_text(json.dumps([*seen["existing"], _raw("R3")]), encoding="utf-8")
        return 0

    fetched = lidl.fetch_receipts(analyzer, receipts, browser="chromium", country="bg", runner=runner)
    assert [r["id"] for r in seen["existing"]] == ["R1", "R2"]
    assert [r["id"] for r in fetched] == ["R1", "R2", "R3"]
    assert "update" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--country") + 1] == "bg"


def test_fetch_runs_on_a_copy(analyzer, receipts):
    """The downloader rewrites its file as it goes; the stored one must survive
    a crashed run untouched."""
    before = receipts.read_text(encoding="utf-8")

    def runner(cmd, cwd):
        (cwd / "lidl_receipts.json").write_text("[]", encoding="utf-8")
        return 1

    with pytest.raises(lidl.DownloaderError):
        lidl.fetch_receipts(analyzer, receipts, browser="chromium", country="bg", runner=runner)
    assert receipts.read_text(encoding="utf-8") == before


def test_fetch_refuses_a_result_that_lost_receipts(analyzer, receipts):
    """A short answer merges cleanly and invisibly, because merging only adds."""

    def runner(cmd, cwd):
        (cwd / "lidl_receipts.json").write_text("[]", encoding="utf-8")
        return 0

    with pytest.raises(lidl.DownloaderError, match="2"):
        lidl.fetch_receipts(analyzer, receipts, browser="chromium", country="bg", runner=runner)


def test_fetch_needs_a_get_data_py(tmp_path, receipts):
    with pytest.raises(lidl.DownloaderError, match="get_data.py"):
        lidl.fetch_receipts(tmp_path / "nowhere", receipts, browser="chromium", country="bg", runner=lambda c, w: 0)


def test_fetch_resolves_a_relative_analyzer_path(analyzer, receipts, monkeypatch):
    """The child runs in a scratch directory, where a path relative to this
    process's working directory points at nothing."""
    monkeypatch.chdir(analyzer.parent)
    seen = {}

    def runner(cmd, cwd):
        seen["script"] = cmd[1]
        return 0

    lidl.fetch_receipts(Path("shopping-analyzer"), receipts, browser="chromium", country="bg", runner=runner)
    assert seen["script"] == str(analyzer / "get_data.py")


def test_merge_appends_new_receipts_and_stamps_them():
    merged, added, changed = lidl.merge_receipts([_raw("R1")], [_raw("R1"), _raw("R2")], fetched_at="2026-08-01")
    assert [r["id"] for r in merged] == ["R1", "R2"]
    assert added == ["R2"]
    assert changed == []
    assert merged[1]["_source"] == lidl.SOURCE
    assert merged[1]["_fetchedAt"] == "2026-08-01"
    assert "_fetchedAt" not in merged[0]  # an untouched receipt is left exactly as it was


def test_merge_does_not_rewrite_a_stored_receipt():
    """It may have been corrected by hand; --update-all is how you ask for that."""
    merged, added, changed = lidl.merge_receipts(
        [_raw("R1", total="41,33")], [_raw("R1", total="99,99")], fetched_at="2026-08-01"
    )
    assert merged[0]["total_price"] == "41,33"
    assert changed == ["R1"]
    assert added == []


def test_merge_update_all_takes_the_fetched_copy():
    merged, _, changed = lidl.merge_receipts(
        [_raw("R1", total="41,33")], [_raw("R1", total="99,99")], fetched_at="2026-08-01", update_all=True
    )
    assert merged[0]["total_price"] == "99,99"
    assert changed == ["R1"]


def test_merge_keeps_the_stored_order():
    merged, _, _ = lidl.merge_receipts([_raw("R2"), _raw("R1")], [_raw("R3")], fetched_at="2026-08-01")
    assert [r["id"] for r in merged] == ["R2", "R1", "R3"]


def test_merge_refuses_a_receipt_without_an_id():
    with pytest.raises(ValueError, match="id"):
        lidl.merge_receipts([], [{"purchase_date": "2026.04.05"}], fetched_at="2026-08-01")


# --------------------------------------------------------------------------- #
# lidl-history --fetch, end to end through main()
# --------------------------------------------------------------------------- #
@pytest.fixture
def run_main(analyzer, receipts, tmp_path, monkeypatch):
    """Run ``lidl-history --fetch`` with a stand-in downloader.

    ``downloader`` gets the scratch copy of the receipts file and rewrites it,
    the way get_data.py does.
    """
    monkeypatch.setattr(lidl, "shop_config", lambda shop: {})
    output = tmp_path / "lidl-history.jsonl"

    def run(downloader, *extra):
        def runner(cmd, cwd):
            downloader(cwd / lidl.DOWNLOADER_OUTPUT)
            return 0

        monkeypatch.setattr(lidl, "_subprocess_runner", runner)
        argv = ["lidl-history", "--fetch", "--analyzer", str(analyzer), "-i", str(receipts), "-o", str(output)]
        monkeypatch.setattr("sys.argv", [*argv, *extra])
        return lidl.main()

    run.output = output
    return run


def _adds(*raws):
    def downloader(target):
        target.write_text(json.dumps([*json.loads(target.read_text(encoding="utf-8")), *raws]), encoding="utf-8")

    return downloader


def test_main_fetch_needs_a_country(run_main):
    with pytest.raises(SystemExit, match="--country"):
        run_main(_adds())


def test_main_fetch_writes_new_receipts_and_ingests_them(run_main, receipts):
    assert run_main(_adds(_raw("R3")), "--country", "bg") == 0
    assert [r["id"] for r in json.loads(receipts.read_text(encoding="utf-8"))] == ["R1", "R2", "R3"]
    assert [r["receipt_id"] for r in store.read_records(run_main.output)] == ["R1", "R2", "R3"]


def test_main_fetch_dry_run_previews_the_fetched_receipts(run_main, receipts, capsys):
    before = receipts.read_text(encoding="utf-8")
    assert run_main(_adds(_raw("R3", date="2026.05.01")), "--country", "bg", "--dry-run") == 0
    assert receipts.read_text(encoding="utf-8") == before
    assert not run_main.output.exists()
    assert "would append 3 record(s)" in capsys.readouterr().out


def test_main_fetch_leaves_a_stored_receipt_alone(run_main, receipts):
    def downloader(target):
        target.write_text(json.dumps([_raw("R1", total="99,00"), _raw("R2")]), encoding="utf-8")

    before = receipts.read_text(encoding="utf-8")
    run_main(downloader, "--country", "bg")
    assert receipts.read_text(encoding="utf-8") == before


def test_main_fetch_update_all_rewrites_the_raw_file(run_main, receipts):
    def downloader(target):
        target.write_text(json.dumps([_raw("R1", total="99,00"), _raw("R2")]), encoding="utf-8")

    run_main(downloader, "--country", "bg", "--update-all")
    stored = {r["id"]: r for r in json.loads(receipts.read_text(encoding="utf-8"))}
    assert stored["R1"]["total_price"] == "99,00"
    assert "_updatedAt" in stored["R1"]


def test_main_fetch_an_interrupted_write_keeps_the_stored_receipts(run_main, receipts, monkeypatch):
    def replace(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", replace)
    before = receipts.read_text(encoding="utf-8")
    with pytest.raises(OSError, match="disk full"):
        run_main(_adds(_raw("R3")), "--country", "bg")
    assert receipts.read_text(encoding="utf-8") == before


def test_main_fetch_reports_unreadable_downloader_output(run_main):
    def downloader(target):
        target.write_text("{not json", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        run_main(downloader, "--country", "bg")
    message = str(exc.value.code)
    assert message.startswith("error: get_data.py")
    assert "Run shopping-analyzer" not in message


def test_main_fetch_reports_a_receipt_without_an_id(run_main):
    with pytest.raises(SystemExit, match="^error: .*no id"):
        run_main(_adds({"purchase_date": "2026.04.05"}), "--country", "bg")
