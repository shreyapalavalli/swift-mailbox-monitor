from app.db.repository import SwiftRepository


def action_row(**kw):
    row = {
        "reference": "R1", "graph_message_id": "G1", "received_at": "2026-10-07T09:00:00+00:00",
        "format": "MT", "message_type": "MT199", "related_reference": None,
        "category": "AMENDMENT", "status": "PRIORITY", "priority": "HIGH",
        "sender_bic": "AAAAUS33", "receiver_bic": "BBBBGB22", "currency": "USD",
        "amount": "100,00", "business_purpose": None, "narrative": "text",
        "matched_terms": "amend", "reason": "r",
    }
    row.update(kw)
    return row


def processed_row(**kw):
    row = {
        "graph_message_id": "G1", "folder": "inbox", "received_at": "2026-10-07T09:00:00+00:00",
        "subject": "s", "sender": "a@b.c", "is_swift": 1, "reference": "R1",
        "message_type": "MT199", "category": "CST", "action": "FORWARD", "status": "FORWARDED",
        "outcome": "DONE", "completed_steps": "FORWARDED", "processed_at": "2026-10-07T10:00:00+00:00",
    }
    row.update(kw)
    return row


def test_upsert_same_reference_updates(tmp_path):
    repo = SwiftRepository(str(tmp_path / "t.db"))
    repo.upsert_action(action_row(reference="R1", status="PRIORITY", category="AMENDMENT"))
    first = repo.get_action("R1")
    repo.upsert_action(action_row(reference="R1", status="ACTION_REQUIRED", category="CANCELLATION"))
    row = repo.get_action("R1")
    assert (row["status"], row["category"]) == ("ACTION_REQUIRED", "CANCELLATION")
    assert row["created_at"] == first["created_at"] and len(repo.list_actions()) == 1


def test_record_processed_increments_attempts(tmp_path):
    repo = SwiftRepository(str(tmp_path / "t.db"))
    assert repo.get_processed("G1") is None
    repo.record_processed(processed_row(outcome="FAILED", error="boom"))
    assert repo.get_processed("G1")["attempts"] == 1
    repo.record_processed(processed_row(outcome="DONE", error=None))
    row = repo.get_processed("G1")
    assert row["attempts"] == 2 and row["outcome"] == "DONE" and row["error"] is None


def test_list_actions_since_filters(tmp_path):
    repo = SwiftRepository(str(tmp_path / "t.db"))
    repo.upsert_action(action_row(reference="A", updated_at="2026-10-07T08:00:00+00:00"))
    repo.upsert_action(action_row(reference="B", updated_at="2026-10-07T09:00:00+00:00",
                                  status="ACTION_REQUIRED", category="OTHER"))
    assert [r["reference"] for r in repo.list_actions()] == ["B", "A"]
    assert [r["reference"] for r in repo.list_actions(since="2026-10-07T08:30:00+00:00")] == ["B"]
    assert [r["reference"] for r in repo.list_actions(status="PRIORITY")] == ["A"]
    assert [r["reference"] for r in repo.list_actions(category="OTHER")] == ["B"]
    assert len(repo.list_actions(limit=1)) == 1


def test_metrics_counts(tmp_path):
    repo = SwiftRepository(str(tmp_path / "t.db"))
    assert repo.metrics("2026-10-07")["last_processed_at"] is None
    repo.record_processed(processed_row(graph_message_id="1", category="CST", status="FORWARDED"))
    repo.record_processed(processed_row(graph_message_id="2", category="CANCELLATION", status="AUTO_CLOSED"))
    repo.record_processed(processed_row(graph_message_id="3", category="AMENDMENT", status="PRIORITY"))
    repo.record_processed(processed_row(graph_message_id="4", is_swift=0, category=None, status=None))
    repo.record_processed(processed_row(graph_message_id="5", outcome="FAILED",
                                        processed_at="2026-10-06T10:00:00+00:00"))
    repo.upsert_action(action_row(reference="P", status="PRIORITY"))
    repo.upsert_action(action_row(reference="X", status="ACTION_REQUIRED", category="OTHER"))
    m = repo.metrics("2026-10-07")
    assert m["processed_today"] == 4 and m["swift_today"] == 3
    assert m["by_category_today"] == {"CST": 1, "CANCELLATION": 1, "AMENDMENT": 1}
    assert m["by_status_today"] == {"FORWARDED": 1, "AUTO_CLOSED": 1, "PRIORITY": 1}
    assert m["open_priority"] == 1 and m["open_action_required"] == 1
    assert m["failed_open"] == 1
    assert m["last_processed_at"] == "2026-10-07T10:00:00+00:00"
    assert len(repo.list_processed(limit=2)) == 2


def test_update_status_unknown_reference_returns_false(tmp_path):
    repo = SwiftRepository(str(tmp_path / "t.db"))
    assert repo.update_action_status("NOPE", "RESPONDED") is False
    repo.upsert_action(action_row())
    assert repo.update_action_status("R1", "RESPONDED") is True
    assert repo.get_action("R1")["status"] == "RESPONDED"
    assert repo.get_action("NOPE") is None
