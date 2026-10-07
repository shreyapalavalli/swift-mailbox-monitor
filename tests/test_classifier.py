import pytest

from app.swift.classifier import Category, classify
from app.swift.parser import parse_swift
from tests.conftest import subject_body

_SUBJECT = "SWIFT Incoming Funds Transfer message-07/10/26-09.30.00MpGPSMail-0001-000001"


def parsed_from_narrative(text: str):
    body = ("Swift Output: FIN 199 Free Format Message\n20: Transaction Reference Number\nTEST0001\n"
            "79: Narrative\n" + text + "\nMessage Trailer")
    return parse_swift(subject=_SUBJECT, body=body)


@pytest.mark.parametrize("name,category", [
    ("mt199_return_funds_cancellation", Category.CANCELLATION),
    ("mx_camt058_cancellation_notice", Category.CANCELLATION),
    ("mt298_cls_schedule", Category.OTHER),
    ("mt199_sgu_related_ref", Category.OTHER),     # SGU is handled by rules, not the classifier
])
def test_real_fixture_categories(load_fixture, name, category):
    assert classify(parse_swift(**subject_body(load_fixture(name)))).category is category


def test_ocr_typo_still_cancellation():
    assert classify(parsed_from_narrative("PLS PROCESS CANCELATION OF OUR PAYMNT")).category is Category.CANCELLATION


def test_amendment_phrase():
    assert classify(parsed_from_narrative("PLEASE AMEND FIELD 59 TO READ ACME LTD")).category is Category.AMENDMENT


def test_callback_phrase():
    assert classify(parsed_from_narrative("PLS CALL BACK TO CONFIRM FT26090811223")).category is Category.CALLBACK


def test_business_purpose_extracted(load_fixture):
    c = classify(parse_swift(**subject_body(load_fixture("mt199_sgu_in_narrative"))))
    assert c.business_purpose.startswith("CONSULTING")


def test_confirm_credited_is_not_callback():   # wording from the real mt199_sgu_in_narrative fixture
    assert classify(parsed_from_narrative("PLEASE CONFIRM US IF FUNDS ARE CREDITED")).category is Category.OTHER


def test_cancellation_matched_terms_and_confidence(load_fixture):
    c = classify(parse_swift(**subject_body(load_fixture("mt199_return_funds_cancellation"))))
    assert c.matched_terms == ("RETURN THE FUNDS", "PAYER'S REQUEST")
    assert c.confidence == 1.0


def test_mx_business_purpose_is_long_name(load_fixture):
    c = classify(parse_swift(**subject_body(load_fixture("mx_camt058_cancellation_notice"))))
    assert c.business_purpose == "Notification To Receive Cancellation Advice"


def test_mt192_type_prior_alone_is_cancellation():
    body = ("Swift Output: FIN 192 Request for Cancellation\n20: Transaction Reference Number\nTEST0002\n"
            "79: Narrative\nREF OUR MT103\nMessage Trailer")
    assert classify(parse_swift(subject=_SUBJECT, body=body)).category is Category.CANCELLATION


def test_amend_variants_count_once_each():
    c = classify(parsed_from_narrative("PAYMENT AMENDED. AMENDED DETAILS FOLLOW"))
    assert c.category is Category.AMENDMENT
    assert c.matched_terms == ("AMENDED",)


def test_aba_request():
    c = classify(parsed_from_narrative("PLS PROVIDE VALID ABA ROUTING NUMBER FOR BENEFICIARY BANK"))
    assert c.category is Category.ABA_REQUEST
    assert c.matched_terms == ("ROUTING NUMBER", "VALID ABA", "ABA")


def test_empty_narrative_is_other_with_zero_confidence():
    c = classify(parsed_from_narrative(""))
    assert (c.category, c.confidence, c.matched_terms) == (Category.OTHER, 0.0, ())
