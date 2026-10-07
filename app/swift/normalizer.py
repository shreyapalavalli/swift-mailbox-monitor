"""OCR/homoglyph cleanup for SWIFT email bodies."""

import re
import unicodedata

_HOMOGLYPHS = str.maketrans(
    "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ" "АВЕКМНОРСТХ" "аеорсх",
    "ABEZHIKMNOPTYX" "ABEKMHOPCTX" "aeopcx",
)
_BLANK_RUNS = re.compile(r"[ \t]*\n(?:[ \t]*\n)*[ \t]*")
_AMOUNT_32B = re.compile(r"(:32B:[A-Za-z]{3})([0-9O,.]+)")


def normalize_text(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw).translate(_HOMOGLYPHS)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _BLANK_RUNS.sub("\n", text).strip()
    text = text.replace("MpGPSMai1", "MpGPSMail")
    text = text.replace(":130:", ":13C:").replace(":328:", ":32B:")
    return _AMOUNT_32B.sub(lambda m: m.group(1) + m.group(2).replace("O", "0"), text)
