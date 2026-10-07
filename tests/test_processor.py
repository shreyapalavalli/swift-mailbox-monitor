import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.db.repository import SwiftRepository
from app.graph.auth_service import SignInRequiredError
from app.models.email_message import EmailMessage
from app.services.processor import SwiftProcessor

CST = "shreyapalavalli@gmail.com"
_SUBJECT = "SWIFT Incoming Funds Transfer message-08/09/26-04.00.00MpGPSMail-7001-000001"
_MX_SUBJECT = "SWIFT Incoming MX message-08/09/26-04.00.00MpBroadcastEMX-7002-000001"

FORWARD_COMMENT = "Auto-routed by SWIFT Mailbox Monitor: reference {ref} belongs to the CST team."
REPLY_TEXT = (
    "Dear Sir/Madam,\n\n"
    "We acknowledge your callback request regarding reference {ref}. SGNY Operations will contact "
    "you by telephone to complete the verification.\n\n"
    "Regards,\nSGNY Payments Operations"
)


class FakeMail:
    """Records Graph calls; `fail_once[method] = message_id` makes that call raise once."""

    def __init__(self, folders: dict[str, list[EmailMessage]]):
        self.folders = folders
        self.forwards: list[tuple[str, str]] = []
        self.forward_comments: list[str] = []
        self.marked_read: list[str] = []
        self.replies: list[tuple[str, str]] = []
        self.fail_once: dict[str, str] = {}

    def _maybe_fail(self, method: str, message_id: str) -> None:
        if self.fail_once.get(method) == message_id:
            del self.fail_once[method]
            request = httpx.Request("POST", f"https://graph.example/{message_id}")
            raise httpx.HTTPStatusError(
                "503 Service Unavailable", request=request,
                response=httpx.Response(503, request=request))

    async def fetch_unread_messages(self, folder: str, top: int = 50) -> list[EmailMessage]:
        return list(self.folders.get(folder, []))

    async def mark_as_read(self, message_id: str) -> None:
        self._maybe_fail("mark_as_read", message_id)
        self.marked_read.append(message_id)

    async def forward_message(self, message_id: str, to_address: str, comment: str) -> None:
        self._maybe_fail("forward_message", message_id)
        self.forwards.append((message_id, to_address))
        self.forward_comments.append(comment)

    async def reply_all(self, message_id: str, comment: str) -> None:
        self._maybe_fail("reply_all", message_id)
        self.replies.append((message_id, comment))


def _msg(msg_id: str, subject: str, body: str, folder: str = "inbox") -> EmailMessage:
    return EmailMessage(id=msg_id, subject=subject, sender="vishnuprakash156@gmail.com",
                        received_date_time=datetime(2026, 9, 8, 7, 0, tzinfo=timezone.utc),
                        body=body, folder=folder)


def _from_fixture(load_fixture, msg_id: str, name: str) -> EmailMessage:
    f = load_fixture(name)
    return _msg(msg_id, f["subject"], f["body"])


@pytest.fixture
def setup(tmp_path, load_fixture):
    def _make(messages: list[EmailMessage]):
        fake = FakeMail({"inbox": messages})
        repo = SwiftRepository(str(tmp_path / "proc.db"))
        proc = SwiftProcessor(fake, repo, ["inbox"], CST, ["camt.056"])
        return fake, repo, proc

    return _make


@pytest.fixture
def fixture_inbox(load_fixture):
    return [
        _from_fixture(load_fixture, "id-sgu", "mt199_sgu_related_ref"),
        _from_fixture(load_fixture, "id-cancel", "mt199_return_funds_cancellation"),
        _from_fixture(load_fixture, "id-298", "mt298_cls_schedule"),
        _from_fixture(load_fixture, "id-nonswift", "non_swift_ms_signin"),
    ]


def test_run_once_routes_real_fixtures(setup, fixture_inbox):
    fake, repo, proc = setup(fixture_inbox)
    summary = asyncio.run(proc.run_once())
    assert fake.forwards == [("id-sgu", CST)]
    assert fake.forward_comments == [FORWARD_COMMENT.format(ref="SGU260903-000033")]
    assert set(fake.marked_read) == {"id-sgu", "id-cancel"}           # non-SWIFT and MT298 untouched
    assert fake.replies == []
    assert repo.get_action("RPIS20260908")["status"] == "ACTION_REQUIRED"
    assert summary == {
        "fetched": 4, "processed": 4, "skipped": 0, "failed": 0,
        "by_action": {"FORWARD_TO_CST": 1, "MARK_READ": 1, "STORE_FOR_ANALYST": 1, "IGNORE": 1},
    }
    sgu = repo.get_processed("id-sgu")
    assert (sgu["outcome"], sgu["completed_steps"], sgu["error"]) == ("DONE", "FORWARDED,MARKED_READ", None)
    assert sgu["action"] == "FORWARD_TO_CST" and sgu["status"] == "ROUTED_CST" and sgu["is_swift"] == 1
    ignored = repo.get_processed("id-nonswift")
    assert (ignored["outcome"], ignored["action"], ignored["is_swift"]) == ("DONE", "IGNORE", 0)


def test_run_once_twice_acts_once(setup, fixture_inbox):
    fake, repo, proc = setup(fixture_inbox)
    asyncio.run(proc.run_once())
    summary = asyncio.run(proc.run_once())
    assert summary["processed"] == 0 and summary["skipped"] == 4 and summary["by_action"] == {}
    assert len(fake.forwards) == 1 and fake.replies == []
    assert sorted(fake.marked_read) == ["id-cancel", "id-sgu"]
    assert repo.get_processed("id-sgu")["attempts"] == 1


def test_partial_failure_retry_skips_completed_steps(setup, fixture_inbox):
    fake, repo, proc = setup(fixture_inbox)
    fake.fail_once["mark_as_read"] = "id-sgu"
    first = asyncio.run(proc.run_once())
    row = repo.get_processed("id-sgu")
    assert first["failed"] == 1 and first["processed"] == 4
    assert (row["outcome"], row["completed_steps"]) == ("FAILED", "FORWARDED")
    assert "503" in row["error"]

    second = asyncio.run(proc.run_once())
    row = repo.get_processed("id-sgu")
    assert (row["outcome"], row["completed_steps"], row["error"]) == ("DONE", "FORWARDED,MARKED_READ", None)
    assert len(fake.forwards) == 1
    assert row["attempts"] == 2
    assert second == {"fetched": 4, "processed": 1, "skipped": 3, "failed": 0,
                      "by_action": {"FORWARD_TO_CST": 1}}


def test_callback_ft_replies_and_stores_responded(setup):
    body = ("Swift Output: FIN 199 Free Format Message\nSender : WFBIUS6SXXX\n"
            "20: Transaction Reference Number\nCBK260908-0001\n"
            "79: Narrative\nPLS CALL BACK TO CONFIRM FT26090811223 USD 1,250.00\nMessage Trailer")
    fake, repo, proc = setup([_msg("id-cb", _SUBJECT, body)])
    summary = asyncio.run(proc.run_once())
    assert fake.replies == [("id-cb", REPLY_TEXT.format(ref="FT26090811223"))]
    assert fake.marked_read == ["id-cb"]
    action = repo.get_action("CBK260908-0001")
    assert action["status"] == "RESPONDED" and action["category"] == "CALLBACK"
    assert action["amount"] == "1250.00" and action["currency"] == "USD"
    assert action["received_at"] == "2026-09-08T07:00:00+00:00"
    assert isinstance(json.loads(action["matched_terms"]), list) and json.loads(action["matched_terms"])
    assert repo.get_processed("id-cb")["completed_steps"] == "REPLIED,STORED,MARKED_READ"
    assert summary["by_action"] == {"AUTO_REPLY": 1}


def test_camt056_left_unread_and_stored_high(setup):
    body = ("MX Output: camt.056.001.08 CBPRPlus-camt.056.001.08_FIToFIPaymentCancellationRequest"
            "SWIFT Reference: swi04003-2026-09-08T07:00:00.1ZSWIFT Request Reference: SNL1"
            "Request to cancel payment, please return funds")
    fake, repo, proc = setup([_msg("id-056", _MX_SUBJECT, body)])
    asyncio.run(proc.run_once())
    assert fake.marked_read == [] and fake.forwards == [] and fake.replies == []
    action = repo.get_action("swi04003-2026-09-08T07:00:00.1Z")
    assert (action["status"], action["priority"], action["category"]) == ("ACTION_REQUIRED", "HIGH", "CANCELLATION")
    assert action["message_type"] == "camt.056.001.08" and action["format"] == "MX"
    assert repo.get_processed("id-056")["completed_steps"] == "STORED"


def test_reference_falls_back_to_message_id(setup):
    fake, repo, proc = setup([_msg("id-noref", "Hello", "Swift Output: something unparseable")])
    asyncio.run(proc.run_once())
    assert repo.get_action("id-noref")["category"] == "OTHER"


def test_auth_error_propagates_without_failed_row(setup, fixture_inbox):
    fake, repo, proc = setup(fixture_inbox)

    async def boom(message_id, to_address, comment):
        raise SignInRequiredError("Microsoft sign-in required. Visit /auth/login first.")

    fake.forward_message = boom
    with pytest.raises(SignInRequiredError, match="sign-in required"):
        asyncio.run(proc.run_once())
    assert repo.get_processed("id-sgu") is None


def test_plain_runtime_error_is_contained_per_message(setup, fixture_inbox):
    fake, repo, proc = setup(fixture_inbox)

    async def boom(message_id, to_address, comment):
        raise RuntimeError("unexpected")

    fake.forward_message = boom
    summary = asyncio.run(proc.run_once())
    row = repo.get_processed("id-sgu")
    assert (row["outcome"], row["completed_steps"]) == ("FAILED", "")
    assert "unexpected" in row["error"]
    assert summary["failed"] == 1 and summary["processed"] == 4
    assert "id-cancel" in fake.marked_read


def test_polls_every_configured_folder(tmp_path, load_fixture):
    junk = _from_fixture(load_fixture, "id-junk", "mt199_return_funds_cancellation")
    fake = FakeMail({"inbox": [], "junkemail": [junk]})
    repo = SwiftRepository(str(tmp_path / "f.db"))
    proc = SwiftProcessor(fake, repo, ["inbox", "junkemail"], CST, ["camt.056"])
    summary = asyncio.run(proc.run_once())
    assert summary["fetched"] == 1 and fake.marked_read == ["id-junk"]


class _StubProcessor:
    def __init__(self, result):
        self.result = result

    async def run_once(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_cli_run_once_prints_summary(monkeypatch, capsys):
    import app.dependencies
    from app.cli import main

    summary = {"fetched": 0, "processed": 0, "skipped": 0, "failed": 0, "by_action": {}}
    monkeypatch.setattr(app.dependencies, "processor", _StubProcessor(summary))
    assert main(["run-once"]) == 0
    assert json.loads(capsys.readouterr().out) == summary


def test_cli_run_once_not_signed_in(monkeypatch, capsys):
    import app.dependencies
    from app.cli import main

    monkeypatch.setattr(app.dependencies, "processor", _StubProcessor(
        SignInRequiredError("Microsoft sign-in required. Visit /auth/login first.")))
    assert main(["run-once"]) == 1
    assert "sign-in required" in capsys.readouterr().err


def test_routes_share_dependency_singletons():
    import app.dependencies
    from app.api import mail_routes

    assert mail_routes.mail_service is app.dependencies.mail_service
    assert app.dependencies.processor.mail is app.dependencies.mail_service
    assert app.dependencies.mail_service.graph_client.auth_service is app.dependencies.auth_service


_CALLBACK_BODY = ("Swift Output: FIN 199 Free Format Message\nSender : WFBIUS6SXXX\n"
                  "20: Transaction Reference Number\nCBK260908-0001\n"
                  "79: Narrative\nPLS CALL BACK TO CONFIRM FT26090811223\nMessage Trailer")


def test_store_crash_after_reply_is_recorded_and_not_replied_again(setup, monkeypatch):
    fake, repo, proc = setup([_msg("id-cb", _SUBJECT, _CALLBACK_BODY)])
    real_upsert = repo.upsert_action
    calls = {"n": 0}

    def flaky_upsert(row):
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyError("boom")
        real_upsert(row)

    monkeypatch.setattr(repo, "upsert_action", flaky_upsert)
    first = asyncio.run(proc.run_once())
    row = repo.get_processed("id-cb")
    assert first["failed"] == 1
    assert (row["outcome"], row["completed_steps"]) == ("FAILED", "REPLIED")
    assert "KeyError" in row["error"]
    assert fake.marked_read == []

    asyncio.run(proc.run_once())
    row = repo.get_processed("id-cb")
    assert (row["outcome"], row["completed_steps"]) == ("DONE", "REPLIED,STORED,MARKED_READ")
    assert len(fake.replies) == 1 and fake.marked_read == ["id-cb"]
    assert repo.get_action("CBK260908-0001")["status"] == "RESPONDED"


def test_sign_in_error_after_forward_persists_progress(setup, fixture_inbox):
    fake, repo, proc = setup(fixture_inbox)
    real_mark = fake.mark_as_read

    async def signed_out(message_id):
        raise SignInRequiredError("Microsoft sign-in required. Visit /auth/login first.")

    fake.mark_as_read = signed_out
    with pytest.raises(SignInRequiredError, match="sign-in required"):
        asyncio.run(proc.run_once())
    row = repo.get_processed("id-sgu")
    assert (row["outcome"], row["completed_steps"]) == ("FAILED", "FORWARDED")

    fake.mark_as_read = real_mark
    asyncio.run(proc.run_once())
    row = repo.get_processed("id-sgu")
    assert (row["outcome"], row["completed_steps"]) == ("DONE", "FORWARDED,MARKED_READ")
    assert fake.forwards == [("id-sgu", CST)]
    assert "id-sgu" in fake.marked_read


def test_poison_message_is_recorded_and_others_still_processed(tmp_path, load_fixture, monkeypatch):
    import app.services.processor as processor_module

    real_parse = processor_module.parse_swift

    def parse(subject, body):
        if body == "POISON":
            raise ValueError("cannot parse")
        return real_parse(subject, body)

    monkeypatch.setattr(processor_module, "parse_swift", parse)
    inbox = [_msg("id-poison", _SUBJECT, "POISON"),
             _from_fixture(load_fixture, "id-sgu", "mt199_sgu_related_ref")]
    junk = [_from_fixture(load_fixture, "id-cancel", "mt199_return_funds_cancellation")]
    fake = FakeMail({"inbox": inbox, "junkemail": junk})
    repo = SwiftRepository(str(tmp_path / "p.db"))
    proc = SwiftProcessor(fake, repo, ["inbox", "junkemail"], CST, ["camt.056"])

    summary = asyncio.run(proc.run_once())
    row = repo.get_processed("id-poison")
    assert (row["outcome"], row["completed_steps"]) == ("FAILED", "")
    assert "cannot parse" in row["error"]
    assert summary["failed"] == 1 and summary["processed"] == 3
    assert fake.forwards == [("id-sgu", CST)]
    assert set(fake.marked_read) == {"id-sgu", "id-cancel"}


def test_overlapping_runs_forward_once(setup, load_fixture):
    fake, repo, proc = setup([_from_fixture(load_fixture, "id-sgu", "mt199_sgu_related_ref")])
    gate = asyncio.Event()
    entered = asyncio.Event()
    real_forward = fake.forward_message

    async def slow_forward(message_id, to_address, comment):
        entered.set()
        await gate.wait()
        await real_forward(message_id, to_address, comment)

    fake.forward_message = slow_forward

    async def go():
        first = asyncio.create_task(proc.run_once())
        await entered.wait()
        assert proc.is_running is True
        second = asyncio.create_task(proc.run_once())
        await asyncio.sleep(0.01)
        gate.set()
        return await asyncio.gather(first, second)

    first, second = asyncio.run(go())
    assert fake.forwards == [("id-sgu", CST)]
    assert first["processed"] == 1 and second["skipped"] == 1
    assert proc.is_running is False


def test_mark_read_timeout_after_reply_keeps_responded_row(setup):
    fake, repo, proc = setup([_msg("id-cb", _SUBJECT, _CALLBACK_BODY)])
    fake.fail_once["mark_as_read"] = "id-cb"
    first = asyncio.run(proc.run_once())
    row = repo.get_processed("id-cb")
    assert first["failed"] == 1
    assert (row["outcome"], row["completed_steps"]) == ("FAILED", "REPLIED,STORED")
    assert repo.get_action("CBK260908-0001")["status"] == "RESPONDED"

    asyncio.run(proc.run_once())
    row = repo.get_processed("id-cb")
    assert (row["outcome"], row["completed_steps"]) == ("DONE", "REPLIED,STORED,MARKED_READ")
    assert len(fake.replies) == 1 and fake.marked_read == ["id-cb"]
