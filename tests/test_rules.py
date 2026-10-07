from dataclasses import replace

import pytest

from app.swift.classifier import Category, Classification, classify
from app.swift.parser import parse_swift
from app.swift.rules import Action, Decision, decide
from tests.conftest import subject_body

ACTION_MX = ["camt.056"]


@pytest.fixture
def base(load_fixture):
    return parse_swift(**subject_body(load_fixture("mt298_cls_schedule")))


def cls(category: Category) -> Classification:
    return Classification(category=category, confidence=1.0, matched_terms=(), business_purpose=None)


def make(base, *, refs=(), mx=None, is_swift=True):
    return replace(base, references=tuple(refs), mx_family=mx, is_swift=is_swift)


def check(d: Decision, action, category, status, priority):
    assert (d.action, d.category, d.status, d.priority) == (action, category, status, priority)
    assert d.reason


def test_row1_not_swift(base):
    d = decide(make(base, is_swift=False), cls(Category.CANCELLATION), ACTION_MX)
    check(d, Action.IGNORE, "NOT_SWIFT", "IGNORED", "LOW")


def test_row2_sgu(base):
    d = decide(make(base, refs=["FT123", "sgu9"]), cls(Category.OTHER), ACTION_MX)
    check(d, Action.FORWARD_TO_CST, "CST", "ROUTED_CST", "NORMAL")


def test_row3_cancellation_action_mx(base):
    d = decide(make(base, mx="camt.056"), cls(Category.CANCELLATION), ACTION_MX)
    check(d, Action.STORE_FOR_ANALYST, "CANCELLATION", "ACTION_REQUIRED", "HIGH")
    assert "camt.056" in d.reason


def test_row3_case_insensitive(base):
    d = decide(make(base, mx="CAMT.056"), cls(Category.CANCELLATION), ["camt.056"])
    assert d.action is Action.STORE_FOR_ANALYST


def test_row4_cancellation(base):
    d = decide(make(base, mx="camt.058"), cls(Category.CANCELLATION), ACTION_MX)
    check(d, Action.MARK_READ, "CANCELLATION", "AUTO_CLOSED", "LOW")


def test_row4_mt_cancellation(base):
    d = decide(make(base), cls(Category.CANCELLATION), ACTION_MX)
    assert d.action is Action.MARK_READ


def test_row5_amendment(base):
    d = decide(make(base), cls(Category.AMENDMENT), ACTION_MX)
    check(d, Action.STORE_FOR_ANALYST, "AMENDMENT", "PRIORITY", "HIGH")


@pytest.mark.parametrize("ref", ["FT24001ABC", "INV-2024-1"])
def test_row6_callback_with_ft_inv(base, ref):
    d = decide(make(base, refs=[ref]), cls(Category.CALLBACK), ACTION_MX)
    check(d, Action.AUTO_REPLY, "CALLBACK", "RESPONDED", "NORMAL")


def test_row7_callback_without_ft_inv(base):
    d = decide(make(base, refs=["ABC123"]), cls(Category.CALLBACK), ACTION_MX)
    check(d, Action.STORE_FOR_ANALYST, "CALLBACK", "ACTION_REQUIRED", "NORMAL")


def test_row8_aba(base):
    d = decide(make(base), cls(Category.ABA_REQUEST), ACTION_MX)
    check(d, Action.STORE_FOR_ANALYST, "ABA_REQUEST", "ACTION_REQUIRED", "NORMAL")


def test_row9_other(base):
    d = decide(make(base), cls(Category.OTHER), ACTION_MX)
    check(d, Action.STORE_FOR_ANALYST, "OTHER", "ACTION_REQUIRED", "NORMAL")


@pytest.mark.parametrize("name,action", [
    ("mt298_cls_schedule", Action.STORE_FOR_ANALYST),
    ("mt199_return_funds_cancellation", Action.MARK_READ),
    ("mt199_sgu_related_ref", Action.FORWARD_TO_CST),
    ("mt199_sgu_in_narrative", Action.FORWARD_TO_CST),
    ("mx_camt058_cancellation_notice", Action.MARK_READ),
    ("non_swift_ms_signin", Action.IGNORE),
])
def test_real_fixture_actions(load_fixture, name, action):
    parsed = parse_swift(**subject_body(load_fixture(name)))
    assert decide(parsed, classify(parsed), ACTION_MX).action is action


def test_sgu_beats_cancellation(base):
    body = ("Swift Output: FIN 199 Free Format Message\n20: Transaction Reference Number\nSGU12345\n"
            "79: Narrative\nPLEASE CANCEL\nMessage Trailer")
    parsed = parse_swift(subject="SWIFT Incoming Funds Transfer message-07/10/26-09.30.00MpGPSMail-0001-000001",
                         body=body)
    c = classify(parsed)
    assert c.category is Category.CANCELLATION
    assert decide(parsed, c, ACTION_MX).action is Action.FORWARD_TO_CST


def test_camt058_becomes_analyst_when_configured(load_fixture):
    parsed = parse_swift(**subject_body(load_fixture("mx_camt058_cancellation_notice")))
    d = decide(parsed, classify(parsed), ["camt.056", "camt.058"])
    assert d.action is Action.STORE_FOR_ANALYST
