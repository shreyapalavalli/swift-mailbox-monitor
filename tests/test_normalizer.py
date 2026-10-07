import json
import re
from pathlib import Path

import pytest

from app.swift.normalizer import normalize_text

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "emails").glob("*.json"))


def test_greek_homoglyphs_become_latin():
    assert normalize_text("PAYMΕΝΤ Ν.Α.") == "PAYMENT N.A."


def test_ocr_mail_id_and_tags():
    out = normalize_text("MpGPSMai1-5505\r\n\r\n:130:/CLSTIME/1100\r\n:328:USDO,")
    assert out == "MpGPSMail-5505\n:13C:/CLSTIME/1100\n:32B:USD0,"


def test_letter_o_outside_amount_untouched():
    assert normalize_text("SOGEUS33XXX :32B:USD315071,79") == "SOGEUS33XXX :32B:USD315071,79"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_bodies_are_clean(path):
    out = normalize_text(json.loads(path.read_text(encoding="utf-8"))["body"])
    assert "\r" not in out
    assert not re.search(r"[\u0370-\u03ff\u0400-\u04ff]", out)
