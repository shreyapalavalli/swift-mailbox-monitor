import random
import smtplib
import re
from datetime import datetime

import pytest

from app.swift.classifier import classify
from app.swift.parser import parse_swift
from app.swift.rules import Action, decide
from scripts import generate_swifts
from scripts.swift_samples import KINDS, make_sample

NOW = datetime(2026, 10, 7, 9, 30)

EXPECTED = {"cancellation_mt192": Action.MARK_READ, "cancellation_return_mt199": Action.MARK_READ,
            "camt056": Action.STORE_FOR_ANALYST, "camt058": Action.MARK_READ, "amendment": Action.STORE_FOR_ANALYST,
            "callback_ft": Action.AUTO_REPLY, "callback_inv": Action.AUTO_REPLY, "aba_request": Action.STORE_FOR_ANALYST,
            "sgu_reply": Action.FORWARD_TO_CST, "cls_mt298": Action.STORE_FOR_ANALYST}

EXPECTED_CATEGORY = {"cancellation_mt192": "CANCELLATION", "cancellation_return_mt199": "CANCELLATION",
                     "camt056": "CANCELLATION", "camt058": "CANCELLATION", "amendment": "AMENDMENT",
                     "callback_ft": "CALLBACK", "callback_inv": "CALLBACK", "aba_request": "ABA_REQUEST",
                     "sgu_reply": "CST", "cls_mt298": "OTHER"}

MT_SUBJECT = re.compile(r"^SWIFT Incoming Funds Transfer message-\d{2}/\d{2}/\d{2}-\d{2}\.\d{2}\.\d{2}"
                        r"MpGPSMail-\d{4}-\d{6}$")
MX_SUBJECT = re.compile(r"^SWIFT Incoming MX message-\d{2}/\d{2}/\d{2}-\d{2}\.\d{2}\.\d{2}"
                        r"MpBroadcastEMX-\d{4}-\d{6}$")


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("kind", KINDS)
def test_sample_round_trips(kind, seed):
    subject, body = make_sample(kind, random.Random(seed), datetime(2026, 10, 7, 9, 30))
    p = parse_swift(subject, body); d = decide(p, classify(p), ["camt.056"])
    assert p.is_swift and p.reference and d.action is EXPECTED[kind]
    assert d.category == EXPECTED_CATEGORY[kind]


@pytest.mark.parametrize("kind", KINDS)
def test_sample_layout_matches_real_mailbox(kind):
    subject, body = make_sample(kind, random.Random(1), NOW)
    if kind.startswith("camt"):
        assert MX_SUBJECT.match(subject)
        assert "MX Output: camt.0" in body and "SWIFT Reference: swi" in body
    else:
        assert MT_SUBJECT.match(subject)
        for line in ("Copy received from SWIFT", "Message Output Reference: ", "Swift Output: FIN ",
                     "Sender : ", "20: Transaction Reference Number", "Message Trailer",
                     "PKI Signature: MAC-Equivalent"):
            assert line in body
        assert re.search(r"\{CHK:[0-9A-F]{12}\}", body)
    assert "\r\n\r\n" in body
    assert subject.startswith("SWIFT Incoming") and "07/10/26-09.30.00" in subject


def test_mt_types_are_correct():
    types = {kind: parse_swift(*make_sample(kind, random.Random(3), NOW)).message_type for kind in KINDS}
    assert types["cancellation_mt192"] == "MT192"
    assert types["cls_mt298"] == "MT298"
    assert types["amendment"] == "MT199"
    assert types["camt056"] == "camt.056.001.08"
    assert types["camt058"] == "camt.058.001.08"


def test_callback_references_start_with_ft_or_inv():
    ft = parse_swift(*make_sample("callback_ft", random.Random(5), NOW))
    inv = parse_swift(*make_sample("callback_inv", random.Random(5), NOW))
    assert any(r.startswith("FT") for r in ft.references)
    assert any(r.startswith("INV") for r in inv.references)


def test_amendment_status_priority():
    p = parse_swift(*make_sample("amendment", random.Random(7), NOW))
    d = decide(p, classify(p), ["camt.056"])
    assert d.status == "PRIORITY" and d.priority == "HIGH"
    assert "PLEASE AMEND" in p.narrative and "SHOULD READ" in p.narrative


def test_ocr_noise_applied_to_some_samples_and_repaired():
    bodies = [make_sample(kind, random.Random(seed), NOW)[1] for kind in KINDS for seed in range(20)]
    noisy = [b for b in bodies if "MpGPSMai1" in b or "Ε" in b]
    assert 0.15 * len(bodies) < len(noisy) < 0.45 * len(bodies)
    assert any("MpGPSMai1" in b for b in bodies) and any("Ε" in b for b in bodies)


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        make_sample("nope", random.Random(0), NOW)


def test_kind_weights_cover_all_kinds():
    assert set(generate_swifts.KIND_WEIGHTS) == set(KINDS)
    assert sum(generate_swifts.KIND_WEIGHTS.values()) == pytest.approx(100)


# --- generate_swifts CLI (never opens a network connection) ---

class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, *args, **kwargs):
        self.host, self.port, self.calls, self.sent = host, port, [], []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, *args, **kwargs):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.sent.append(msg)


def _no_smtp(*args, **kwargs):
    raise AssertionError("SMTP must not be used")


@pytest.fixture
def cli_env(monkeypatch):
    monkeypatch.setattr(generate_swifts, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(generate_swifts.time, "sleep", lambda s: None)
    for var in ("GMAIL_APP_PASSWORD", "GENERATOR_SENDER", "GENERATOR_RECIPIENT"):
        monkeypatch.delenv(var, raising=False)
    FakeSMTP.instances = []
    return monkeypatch


def test_dry_run_sends_nothing(cli_env, capsys):
    cli_env.setattr(generate_swifts.smtplib, "SMTP", _no_smtp)
    assert generate_swifts.main(["--dry-run", "--count", "2", "--interval", "0"]) == 0
    out = capsys.readouterr().out
    assert len(re.findall(r"^Subject: SWIFT Incoming", out, re.M)) == 2


def test_dry_run_respects_kinds(cli_env, capsys):
    cli_env.setattr(generate_swifts.smtplib, "SMTP", _no_smtp)
    assert generate_swifts.main(["--dry-run", "--count", "5", "--interval", "0", "--kinds", "camt056"]) == 0
    out = capsys.readouterr().out
    assert len(re.findall(r"^Subject: SWIFT Incoming MX message", out, re.M)) == 5


def test_unknown_kind_exits_2(cli_env, capsys):
    cli_env.setattr(generate_swifts.smtplib, "SMTP", _no_smtp)
    assert generate_swifts.main(["--dry-run", "--count", "1", "--kinds", "amendment,bogus"]) == 2
    assert "bogus" in capsys.readouterr().err


def test_missing_password_exits_2(cli_env, capsys):
    cli_env.setattr(generate_swifts.smtplib, "SMTP", _no_smtp)
    assert generate_swifts.main(["--count", "1"]) == 2
    assert "GMAIL_APP_PASSWORD" in capsys.readouterr().err


def test_sends_over_gmail_smtp_without_printing_secret(cli_env, capsys):
    cli_env.setenv("GMAIL_APP_PASSWORD", "s3cret-app-pw")
    cli_env.setattr(generate_swifts.smtplib, "SMTP", FakeSMTP)
    assert generate_swifts.main(["--count", "2", "--interval", "0", "--kinds", "amendment"]) == 0
    assert len(FakeSMTP.instances) == 2
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.gmail.com", 587)
    assert smtp.calls == ["starttls", ("login", "vishnuprakash156@gmail.com", "s3cret-app-pw")]
    msg = smtp.sent[0]
    assert msg["From"] == "vishnuprakash156@gmail.com"
    assert msg["To"] == "MTheadsYI@outlook.com"
    assert msg["Subject"].startswith("SWIFT Incoming Funds Transfer message-")
    assert "PLEASE AMEND" in msg.get_content()
    captured = capsys.readouterr()
    assert "s3cret-app-pw" not in captured.out + captured.err


def test_ctrl_c_exits_cleanly(cli_env, capsys):
    cli_env.setattr(generate_swifts.smtplib, "SMTP", _no_smtp)

    def interrupt(seconds):
        raise KeyboardInterrupt

    cli_env.setattr(generate_swifts.time, "sleep", interrupt)
    assert generate_swifts.main(["--dry-run", "--interval", "1"]) == 0
    assert "Stopped" in capsys.readouterr().out


class FlakySMTP(FakeSMTP):
    """Fails send_message for the first `failures` attempts (class-wide), then succeeds."""
    failures = 0
    error: Exception = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    def send_message(self, msg):
        if FlakySMTP.failures:
            FlakySMTP.failures -= 1
            raise FlakySMTP.error
        super().send_message(msg)


def test_transient_error_backs_off_and_retries(cli_env, capsys):
    sleeps = []
    cli_env.setattr(generate_swifts.time, "sleep", sleeps.append)
    cli_env.setenv("GMAIL_APP_PASSWORD", "s3cret-app-pw")
    FlakySMTP.failures, FlakySMTP.error = 1, smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    cli_env.setattr(generate_swifts.smtplib, "SMTP", FlakySMTP)
    assert generate_swifts.main(["--count", "1", "--interval", "0", "--kinds", "amendment"]) == 0
    assert len(FakeSMTP.instances) == 2                       # 2 attempts
    assert sum(len(s.sent) for s in FakeSMTP.instances) == 1
    assert sleeps == [2]                                      # min(300, 2**1)
    captured = capsys.readouterr()
    assert "SMTPServerDisconnected" in captured.err and "s3cret-app-pw" not in captured.out + captured.err


def test_backoff_doubles_caps_at_300_and_resets_after_success(cli_env):
    sleeps = []
    cli_env.setattr(generate_swifts.time, "sleep", sleeps.append)
    cli_env.setenv("GMAIL_APP_PASSWORD", "pw")
    FlakySMTP.failures, FlakySMTP.error = 9, OSError("network down")
    cli_env.setattr(generate_swifts.smtplib, "SMTP", FlakySMTP)
    assert generate_swifts.main(["--count", "2", "--interval", "7", "--kinds", "amendment"]) == 0
    assert sleeps == [2, 4, 8, 16, 32, 64, 128, 256, 300, 7]  # then interval; counter reset on success


def test_auth_error_exits_2_immediately(cli_env, capsys):
    sleeps = []
    cli_env.setattr(generate_swifts.time, "sleep", sleeps.append)
    cli_env.setenv("GMAIL_APP_PASSWORD", "s3cret-app-pw")
    FlakySMTP.failures, FlakySMTP.error = 5, smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
    cli_env.setattr(generate_swifts.smtplib, "SMTP", FlakySMTP)
    assert generate_swifts.main(["--count", "3", "--interval", "0"]) == 2
    assert len(FakeSMTP.instances) == 1 and sleeps == []
    captured = capsys.readouterr()
    assert "GMAIL_APP_PASSWORD" in captured.err and "s3cret-app-pw" not in captured.out + captured.err


@pytest.mark.parametrize("argv", [["--interval", "-1", "--count", "1"], ["--count", "0"], ["--count", "-3"]])
def test_invalid_interval_or_count_is_an_argparse_error(cli_env, capsys, argv):
    cli_env.setattr(generate_swifts.smtplib, "SMTP", _no_smtp)
    with pytest.raises(SystemExit) as exc:
        generate_swifts.main(["--dry-run", *argv])
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err


# --- demo scenario mode ---

DEMO_ORDER = ["amendment", "sgu_reply", "cancellation_mt192", "camt056", "callback_ft", "aba_request"]


def _sent_kinds(out: str) -> list[str]:
    return re.findall(r"^--- \[dry-run\] (\S+) ---$", out, re.M)


def test_demo_scenario_sends_fixed_sequence_in_order(cli_env, capsys):
    cli_env.setattr(generate_swifts.smtplib, "SMTP", _no_smtp)
    assert generate_swifts.main(["--scenario", "demo", "--auto", "--interval", "0", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert _sent_kinds(out) == DEMO_ORDER
    assert "[1/6]" in out and "PRIORITY" in out and "[6/6]" in out


def test_demo_scenario_waits_for_enter_before_each_step(cli_env, capsys):
    cli_env.setattr(generate_swifts.smtplib, "SMTP", _no_smtp)
    prompts = []
    cli_env.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "")
    sleeps = []
    cli_env.setattr(generate_swifts.time, "sleep", sleeps.append)
    assert generate_swifts.main(["--scenario", "demo", "--dry-run"]) == 0
    assert len(prompts) == 6 and "Enter" in prompts[0]
    assert sleeps == []


def test_demo_scenario_auto_sleeps_interval_between_steps(cli_env):
    cli_env.setattr(generate_swifts.smtplib, "SMTP", _no_smtp)
    sleeps = []
    cli_env.setattr(generate_swifts.time, "sleep", sleeps.append)
    assert generate_swifts.main(["--scenario", "demo", "--auto", "--interval", "7", "--dry-run"]) == 0
    assert sleeps == [7.0] * 5


def test_demo_scenario_retries_same_step_after_transient_error(cli_env, capsys):
    cli_env.setenv("GMAIL_APP_PASSWORD", "app-pw")
    calls = {"n": 0}

    class FlakySMTP(FakeSMTP):
        def send_message(self, msg):
            calls["n"] += 1
            if calls["n"] == 1:
                raise smtplib.SMTPServerDisconnected("boom")
            super().send_message(msg)

    cli_env.setattr(generate_swifts.smtplib, "SMTP", FlakySMTP)
    assert generate_swifts.main(["--scenario", "demo", "--auto", "--interval", "0"]) == 0
    sent = [m for s in FakeSMTP.instances for m in s.sent]
    assert len(sent) == 6
    assert re.findall(r"^sent (\S+):", capsys.readouterr().out, re.M) == DEMO_ORDER


def test_demo_scenario_stops_cleanly_when_stdin_closes(cli_env, capsys):
    cli_env.setattr(generate_swifts.smtplib, "SMTP", _no_smtp)

    def closed(prompt=""):
        raise EOFError

    cli_env.setattr("builtins.input", closed)
    assert generate_swifts.main(["--scenario", "demo", "--dry-run"]) == 0
    assert _sent_kinds(capsys.readouterr().out) == []


@pytest.mark.parametrize("extra", [["--kinds", "amendment"], ["--count", "2"]])
def test_scenario_rejects_kinds_and_count(cli_env, capsys, extra):
    assert generate_swifts.main(["--scenario", "demo", "--dry-run", *extra]) == 2
    assert "--scenario" in capsys.readouterr().err


def test_auto_without_scenario_is_rejected(cli_env, capsys):
    assert generate_swifts.main(["--auto", "--dry-run", "--count", "1"]) == 2
