from decimal import Decimal

import pytest

from app.swift.parser import parse_swift
from tests.conftest import subject_body


@pytest.mark.parametrize("name,expected", [
    ("mt298_cls_schedule", dict(message_type="MT298", sub_message_type="211", transaction_reference="RPIS20260908",
        sender_bic="SOGEFRPPCLS", receiver_bic="SOGEUS33XXX", currency="USD", amount=Decimal("315071.79"),
        mail_id="MpGPSMail-5505-000001")),
    ("mt199_return_funds_cancellation", dict(message_type="MT199", transaction_reference="0435825000432026",
        related_reference="043586750036171H", sender_bic="SOGEFRPPXXX", references=())),
    ("mt199_sgu_related_ref", dict(transaction_reference="WFW260907-001017", related_reference="SGU260903-000033",
        sender_bic="WFBIUS6SXXX", references=("SGU260903-000033",))),
    ("mt199_sgu_in_narrative", dict(transaction_reference="0433924700132026", related_reference="04339674028730PU",
        currency="USD", amount=Decimal("9843.75"), references=("SGU260902-000054",))),
])
def test_parse_real_fixtures(load_fixture, name, expected):
    p = parse_swift(**subject_body(load_fixture(name)))
    assert p.is_swift is True
    assert p.format == "MT"
    for field, value in expected.items():
        assert getattr(p, field) == value, field
    assert p.reference == p.transaction_reference


def test_parse_mx_collapsed(load_fixture):
    p = parse_swift(**subject_body(load_fixture("mx_camt058_cancellation_notice")))
    assert (p.format, p.message_type, p.mx_family) == ("MX", "camt.058.001.08", "camt.058")
    assert p.swift_reference == "swi04003-2026-09-08T06:43:03.23847.2373755Z"
    assert p.reference == p.swift_reference


def test_non_swift_is_flagged(load_fixture):
    p = parse_swift(**subject_body(load_fixture("non_swift_ms_signin")))
    assert p.is_swift is False
    assert p.format == "UNKNOWN"
    assert p.message_type is None and p.references == ()


def test_narrative_is_79_text_for_mt(load_fixture):
    p = parse_swift(**subject_body(load_fixture("mt199_return_funds_cancellation")))
    assert p.narrative.startswith("HI, WE REFER TO OUR PAYMENT")
    assert p.narrative.endswith("CDS STD FLUX 1 LC")


def test_ft_inv_references_need_a_digit():
    body = ("Swift Output: FIN 199 Free Format Message\n20: Transaction Reference Number\nFT26090812345\n"
            "79: Narrative\nPLS CALL BACK ON INV-2026/0042 SWIFT INVESTIGATIONS FT26090812345\nMessage Trailer")
    p = parse_swift("SWIFT Incoming Funds Transfer message", body)
    assert p.references == ("FT26090812345", "INV-2026/0042")


def test_reference_falls_back_to_mail_id():
    p = parse_swift("SWIFT Incoming Funds Transfer message-08/09/26MpGPSMai1-5505-000009", "")
    assert p.is_swift is True
    assert p.reference == "MpGPSMail-5505-000009"


def test_none_inputs_do_not_raise():
    p = parse_swift(None, None)
    assert p.is_swift is False and p.reference is None and p.text == ""
