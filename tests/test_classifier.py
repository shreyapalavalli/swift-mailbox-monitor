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


@pytest.mark.parametrize("name", ["mt199_return_funds_cancellation", "mx_camt058_cancellation_notice"])
def test_real_cancellations_are_strong(load_fixture, name):
    c = classify(parse_swift(**subject_body(load_fixture(name))))
    assert c.category is Category.CANCELLATION and c.strong is True


def test_type_prior_alone_is_strong():
    body = ("Swift Output: FIN 192 Request for Cancellation\n20: Transaction Reference Number\nTEST0002\n"
            "79: Narrative\nREF OUR MT103\nMessage Trailer")
    assert classify(parse_swift(subject=_SUBJECT, body=body)).strong is True


@pytest.mark.parametrize("text", ["PLEASE REFUND OUR CHARGES FOR THIS TRANSFER",
                                  "HAS OUR PAYMENT BEEN CANCELLED? PLEASE ADVISE",
                                  "PLEASE RECALL DETAILS AND ADVISE"])
def test_single_weak_token_is_cancellation_but_not_strong(text):
    c = classify(parsed_from_narrative(text))
    assert c.category is Category.CANCELLATION and c.strong is False


def test_two_weak_tokens_reach_score_4_and_are_strong():
    c = classify(parsed_from_narrative("WE RECALL AND REVOKE OUR INSTRUCTION"))
    assert c.category is Category.CANCELLATION and c.strong is True


def test_cancellation_phrase_is_strong():
    c = classify(parsed_from_narrative("STOP PAYMENT ON OUR MT103"))
    assert c.category is Category.CANCELLATION and c.strong is True


@pytest.mark.parametrize("text", ["PLEASE DO NOT CANCEL THE PAYMENT",
                                  "PLS DON'T RECALL OUR TRANSFER, RETURN OF FUNDS NOT NEEDED",
                                  "WE ASKED YOU NOT TO REVOKE THE INSTRUCTION",
                                  "NO NEED TO RETURN THE FUNDS",
                                  "THIS IS NOT A CANCELLATION REQUEST"])
def test_negated_cancellation_wording_is_ignored(text):
    assert classify(parsed_from_narrative(text)).category is Category.OTHER


def test_negation_keeps_type_prior():
    body = ("Swift Output: FIN 192 Request for Cancellation\n20: Transaction Reference Number\nTEST0002\n"
            "79: Narrative\nDO NOT CANCEL THE OTHER PAYMENT\nMessage Trailer")
    c = classify(parse_swift(subject=_SUBJECT, body=body))
    assert c.category is Category.CANCELLATION and c.strong is True


def test_non_cancellation_categories_are_not_strong():
    assert classify(parsed_from_narrative("PLEASE AMEND FIELD 59 TO READ ACME LTD")).strong is False


@pytest.mark.parametrize("text,category", [
    ("WE ARE AMENDING FIELD 59", Category.AMENDMENT),
    ("MODIFICATION OF FIELD 59 REQUESTED", Category.AMENDMENT),
    ("KINDLY CHANGE BENEFICIARY NAME TO ACME LTD", Category.AMENDMENT),
    ("REQUEST TO CORRECT FIELD 59", Category.AMENDMENT),
    ("PLS CALL US BACK RE FT26090811223", Category.CALLBACK),
    ("PLEASE CONFIRM THE DETAILS BY PHONE", Category.CALLBACK),
    ("WE ARE CANCELLING OUR PAYMENT 123", Category.CANCELLATION),
    ("PAYMENT REVOKED BY ORDERING CUSTOMER", Category.CANCELLATION),
])
def test_inflected_forms_and_phrases(text, category):
    assert classify(parsed_from_narrative(text)).category is category


def test_stem_counts_once_per_category():
    c = classify(parsed_from_narrative("CANCELLATION: WE CANCELLED AND ARE CANCELLING"))
    assert c.category is Category.CANCELLATION
    assert c.matched_terms == ("CANCELLATION",)
    assert c.strong is False           # one stem = 2 points: analyst review


def test_amend_and_modif_stems_score_3_and_2():
    c = classify(parsed_from_narrative("AMENDMENT AND MODIFIED DETAILS"))
    assert c.matched_terms == ("AMENDMENT", "MODIFIED")
    assert c.confidence == 1.0


def test_revoked_matches_stem():
    c = classify(parsed_from_narrative("CUSTOMER REVOKES"))
    assert c.matched_terms == ("REVOKES",)


def test_token_used_by_a_stem_never_also_scores_a_term_of_that_category():
    from app.swift.classifier import _token_hits

    hits = _token_hits(stems=(("REVOK", 2),), terms=(("REVOKED", 2), ("RECALL", 2)),
                       tokens=["REVOKED", "RECALLED"])
    assert hits == [("REVOKED", 2), ("RECALL", 2)]     # RECALLED fuzzy-matches RECALL; REVOKED only once


def test_ocr_typo_on_exact_term_still_fuzzy():
    assert classify(parsed_from_narrative("PLS ARRANGE CALLBAK FOR FT26090811223")).category is Category.CALLBACK


@pytest.mark.parametrize("narrative,category", [
    ("PLEASE CHANGE THE\nBENEFICIARY NAME TO ACME", Category.AMENDMENT),
    ("REQUEST TO CORRECT\nFIELD 59", Category.AMENDMENT),
    ("PLS CONFIRM THE DETAILS\nBY PHONE", Category.CALLBACK),
])
def test_phrases_match_across_line_wraps(narrative, category):
    assert classify(parsed_from_narrative(narrative)).category is category


def test_mx_long_name_keeps_acronyms_together():
    body = ("MX Output: camt.056.001.08 CBPRPlus-camt.056.001.08_FIToFIPaymentCancellationRequest\n"
            "SWIFT Reference: swi00001-2026-10-07T10:00:00.00001.1234567Z")
    c = classify(parse_swift("SWIFT Incoming MX message-07/10/26-10.00.00MpBroadcastEMX-0001-000001", body))
    assert c.business_purpose == "FI To FI Payment Cancellation Request"
