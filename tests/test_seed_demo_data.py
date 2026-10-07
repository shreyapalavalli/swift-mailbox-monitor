import sqlite3

import pytest

from app.db.repository import SwiftRepository
from scripts import seed_demo_data
from scripts.swift_samples import KINDS


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(seed_demo_data.time, "sleep", sleeps.append)
    return sleeps


def _statuses(repo: SwiftRepository) -> set[str]:
    return {r["status"] for r in repo.list_actions(limit=1000)}


def test_seed_populates_every_state_the_dashboard_renders(tmp_path, no_sleep):
    db = tmp_path / "demo.db"
    assert seed_demo_data.main(["--db", str(db), "--count", "30"]) == 0
    repo = SwiftRepository(str(db))

    assert {"PRIORITY", "ACTION_REQUIRED", "RESPONDED", "IN_PROGRESS", "RESOLVED"} <= _statuses(repo)
    log = repo.list_processed(limit=1000)
    assert {"ROUTED_CST", "AUTO_CLOSED", "IGNORED"} <= {r["status"] for r in log}
    assert [r["outcome"] for r in log].count("FAILED") == 1
    assert any(r["is_swift"] == 0 for r in log)

    m = repo.metrics(log[0]["processed_at"][:10])
    assert m["open_priority"] >= 1 and m["failed_open"] == 1


def test_every_sample_kind_is_seeded_at_least_once(tmp_path, no_sleep):
    db = tmp_path / "demo.db"
    assert seed_demo_data.main(["--db", str(db), "--count", str(len(KINDS))]) == 0
    log = SwiftRepository(str(db)).list_processed(limit=1000)
    swift_rows = [r for r in log if r["is_swift"]]
    assert len(swift_rows) == len(KINDS)


def test_seed_is_deterministic_for_a_given_seed(tmp_path, no_sleep):
    refs = []
    for name in ("a.db", "b.db"):
        db = tmp_path / name
        assert seed_demo_data.main(["--db", str(db), "--count", "15", "--seed", "3"]) == 0
        refs.append(sorted(r["reference"] for r in SwiftRepository(str(db)).list_actions(limit=1000)))
    assert refs[0] == refs[1]


def test_refuses_database_with_real_mailbox_rows(tmp_path, capsys, no_sleep):
    db = tmp_path / "live.db"
    repo = SwiftRepository(str(db))
    repo.record_processed({"graph_message_id": "AQMkADAwATM3real", "is_swift": 1, "outcome": "DONE"})

    assert seed_demo_data.main(["--db", str(db)]) == 2
    assert "real mailbox" in capsys.readouterr().err
    assert len(repo.list_processed(limit=1000)) == 1

    assert seed_demo_data.main(["--db", str(db), "--force", "--count", "5"]) == 0
    assert len(repo.list_processed(limit=1000)) > 1


def test_reset_starts_from_an_empty_database(tmp_path, no_sleep):
    db = tmp_path / "demo.db"
    assert seed_demo_data.main(["--db", str(db), "--count", "12"]) == 0
    assert seed_demo_data.main(["--db", str(db), "--count", "12", "--reset"]) == 0
    with sqlite3.connect(db) as conn:
        swift = conn.execute("SELECT COUNT(*) FROM processed_messages WHERE is_swift = 1").fetchone()[0]
    assert swift == 12


def test_live_mode_keeps_adding_messages(tmp_path, no_sleep):
    db = tmp_path / "demo.db"
    assert seed_demo_data.main(["--db", str(db), "--count", "10", "--live", "--live-count", "3",
                                "--interval", "4"]) == 0
    log = SwiftRepository(str(db)).list_processed(limit=1000)
    assert sum(1 for r in log if r["is_swift"]) == 13
    assert no_sleep == [4.0, 4.0, 4.0]


def test_offline_mailbox_never_touches_the_network(tmp_path, no_sleep, monkeypatch):
    import httpx

    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    assert seed_demo_data.main(["--db", str(tmp_path / "demo.db"), "--count", "12"]) == 0


def test_reset_removes_wal_sidecar_files(tmp_path, no_sleep):
    db = tmp_path / "demo.db"
    assert seed_demo_data.main(["--db", str(db), "--count", "10"]) == 0
    for suffix in ("-wal", "-shm"):
        (tmp_path / f"demo.db{suffix}").write_bytes(b"stale")
    assert seed_demo_data.main(["--db", str(db), "--count", "10", "--reset"]) == 0
    for suffix in ("-wal", "-shm"):
        sidecar = tmp_path / f"demo.db{suffix}"
        assert not sidecar.exists() or sidecar.read_bytes() != b"stale"


def test_reset_while_database_is_locked_explains_how_to_fix(tmp_path, capsys, no_sleep, monkeypatch):
    db = tmp_path / "demo.db"
    assert seed_demo_data.main(["--db", str(db), "--count", "10"]) == 0

    def locked(path):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(seed_demo_data.os, "remove", locked)
    assert seed_demo_data.main(["--db", str(db), "--reset"]) == 2
    assert "stop the backend" in capsys.readouterr().err.lower()
