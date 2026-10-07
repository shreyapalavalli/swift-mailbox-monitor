"""Synthetic SWIFT emails in the same OCR'd layout as the real mailbox (see tests/fixtures/emails)."""

import random
import re
import uuid
from datetime import datetime

KINDS = ("cancellation_mt192", "cancellation_return_mt199", "camt056", "camt058", "amendment",
         "callback_ft", "callback_inv", "aba_request", "sgu_reply", "cls_mt298")

SEP = "\r\n\r\n"
NOISE_RATE = 0.30
GREEK_E = "\u0395"

RECEIVER = ("SOGEUS33XXX", "SOCIETE GENERALE NEW YORK, NY US")
SENDERS = (
    ("SOGEFRPPXXX", "SOCIETE GENERALE", "PUTEAUX FR"),
    ("WFBIUS6SXXX", "WELLS FARGO BANK, N.A.", "SAN FRANCISCO, CA US"),
    ("DEUTDEFFXXX", "DEUTSCHE BANK AG", "FRANKFURT AM MAIN DE"),
    ("BNPAFRPPXXX", "BNP PARIBAS", "PARIS FR"),
    ("CHASUS33XXX", "JPMORGAN CHASE BANK, N.A.", "NEW YORK, NY US"),
)
COMPANIES = ("SAMPLE LPG FRANCE", "SAMPLE TRADING LTD", "NORDIC SHIPPING AS", "ACME TRADING LLC", "BLUE HARBOR LOGISTICS",
             "SUNRISE TEXTILES PVT LTD", "ORION METALS GMBH", "GREENFIELD AGRO SA")
IBANS = ("FR7600000000000000000000000", "LV00BANK0000000000000", "DE89370400440532013000",
         "GB29NWBK60161331926819", "NL91ABNA0417164300")
TEAMS = ("CDS STD FLUX 1 LC", "SG CDS BDX FLUX INT2 GB", "PAYMENT INVESTIGATIONS TEAM", "GLOBAL TRADE OPS")
PURPOSES = ("CONSULTING SERVICES", "FREIGHT CHARGES", "SOFTWARE LICENSE FEES", "PURCHASE OF SPARE PARTS")

# Words that must never carry OCR noise: classifier lexicon words and common keyword parts.
_PROTECTED = {
    "AMEND", "AMENDMENT", "AMENDED", "MODIFY", "REVISED", "PLEASE", "CHANGE", "CORRECT", "BENEFICIARY",
    "SHOULD", "READ", "INSTEAD", "CANCEL", "CANCELLATION", "CANCELLED", "RECALL", "REVOKE", "REFUND",
    "RETURN", "THE", "FUNDS", "REQUEST", "STOP", "PAYMENT", "PAYER'S", "CALL", "BACK", "CALLBACK",
    "CONFIRM", "PHONE", "TELEPHONE", "VERIFY", "CONFIRMATION", "ROUTING", "NUMBER", "VALID", "ABA",
    "FEDWIRE",
}
_WORD = re.compile(r"(?<![\w'/-])([A-Z]+)(?![\w'/-])")


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def _alnum(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(n))


def _trn(rng: random.Random) -> str:
    return "04" + _digits(rng, 13) + rng.choice("0123456789HPU")


def _amount(rng: random.Random) -> str:
    return f"{rng.randint(1_000, 250_000) + rng.randint(0, 99) / 100:,.2f}"


def _sgu(rng: random.Random, now: datetime) -> str:
    return f"SGU{now:%y%m%d}-{_digits(rng, 6)}"


def _add_greek_e(rng: random.Random, narrative: str) -> str | None:
    words = [m for m in _WORD.finditer(narrative) if "E" in m.group(1) and m.group(1) not in _PROTECTED]
    if not words:
        return None
    m = rng.choice(words)
    word = m.group(1)
    pos = rng.choice([i for i, c in enumerate(word) if c == "E"])
    return narrative[:m.start()] + word[:pos] + GREEK_E + word[pos + 1:] + narrative[m.end():]


def _mt_message(rng: random.Random, now: datetime, mt: str, title: str, fields: list[tuple[str, str]],
                narrative_label: str, narrative: list[str]) -> tuple[str, str]:
    mail_id = f"MpGPSMail-{_digits(rng, 4)}-{rng.randint(1, 3):06d}"
    bic, bank, city = rng.choice(SENDERS)
    text = SEP.join(narrative)
    body_mail_id = mail_id
    if rng.random() < NOISE_RATE:
        mode = rng.choice(("mail_id", "greek", "both"))
        noisy = _add_greek_e(rng, text) if mode != "mail_id" else None
        if noisy:
            text = noisy
        if mode != "greek" or noisy is None:
            body_mail_id = mail_id.replace("MpGPSMail", "MpGPSMai1")

    lines = [
        f"{now:%d/%m/%y-%H:%M:%S}", body_mail_id, mail_id[-1],
        "Instance Type and Transmission", "Copy received from SWIFT", ": Normal", "Priority",
        f"Message Output Reference: {now:%H%M} {now:%y%m%d}{RECEIVER[0][:8]}A{RECEIVER[0][8:]}{_digits(rng, 10)}",
        f"Correspondent Input Reference: {now:%H%M} {now:%y%m%d}{bic[:8]}A{bic[8:]}{_digits(rng, 10)}",
        "Message Header", f"Swift Output: FIN {mt} {title}",
        f"Sender : {bic}", bank, city, f"Receiver: {RECEIVER[0]}", RECEIVER[1],
        f"MUR: COB{_digits(rng, 3)}T{_alnum(rng, 6)}",
        "Transaction Manager/Contingency Processing: Not applicable", "Message Text",
    ]
    for label, value in fields:
        lines += [label, value]
    lines += [narrative_label, text, f"{{CHK:{rng.getrandbits(48):012X}}}", "Message Trailer",
              "PKI Signature: MAC-Equivalent"]
    subject = f"SWIFT Incoming Funds Transfer message-{now:%d/%m/%y-%H.%M.%S}{mail_id}"
    return subject, SEP.join(lines) + "\r\n"


def _mt199(rng, now, narrative: list[str], related: str | None = None) -> tuple[str, str]:
    fields = [("20: Transaction Reference Number", _trn(rng)),
              ("21: Related Reference", related or _trn(rng))]
    return _mt_message(rng, now, "199", "Free Format Message", fields, "79: Narrative", narrative)


def _cancellation_mt192(rng, now):
    original = _trn(rng)
    fields = [("20: Transaction Reference Number", _trn(rng)), ("21: Related Reference", original),
              ("11S: MT and Date of the Original Message", f"103 {now:%y%m%d}")]
    narrative = [f"REQUEST FOR CANCELLATION OF OUR MT103 {original} FOR USD {_amount(rng)}",
                 "PLEASE CANCEL AND CONFIRM BY RETURN SWIFT.", "BEST REGARDS", rng.choice(TEAMS)]
    return _mt_message(rng, now, "192", "Request for Cancellation", fields, "79: Narrative", narrative)


def _cancellation_return_mt199(rng, now):
    original = _trn(rng)
    narrative = [f"HI, WE REFER TO OUR PAYMENT {original}", f"REMITTER:: {rng.choice(COMPANIES)}",
                 rng.choice(IBANS), f"BENEFICIARY: {rng.choice(IBANS)}", rng.choice(COMPANIES),
                 "CAN YOU RETURN THE FUNDS AT THE PAYER'S REQUEST?", "BEST REGARDS", rng.choice(TEAMS)]
    return _mt199(rng, now, narrative, related=original)


def _amendment(rng, now):
    original = _trn(rng)
    old, name = rng.sample(COMPANIES, 2)
    narrative = [f"PLEASE AMEND OUR PAYMENT {original} FOR USD {_amount(rng)}. FIELD 59 BENEFICIARY "
                 f"SHOULD READ {name} INSTEAD OF {old}.", "ALL OTHER DETAILS REMAIN UNCHANGED.",
                 "BEST REGARDS", rng.choice(TEAMS)]
    return _mt199(rng, now, narrative, related=original)


def _callback(rng, now, ref: str):
    narrative = [f"RE YOUR REF {ref}. PLS CALL BACK THE REMITTER TO CONFIRM PAYMENT DETAILS BEFORE RELEASE.",
                 "BEST REGARDS", rng.choice(TEAMS)]
    return _mt199(rng, now, narrative)


def _callback_ft(rng, now):
    return _callback(rng, now, f"FT{now:%y}{now.timetuple().tm_yday:03d}{_alnum(rng, 5)}")


def _callback_inv(rng, now):
    return _callback(rng, now, f"INV-{now:%Y}-{_digits(rng, 6)}")


def _aba_request(rng, now):
    original = _trn(rng)
    narrative = [f"RE OUR PAYMENT {original} FOR USD {_amount(rng)} IN FAVOUR OF {rng.choice(COMPANIES)}",
                 "THE BENEFICIARY BANK DETAILS ARE INCOMPLETE. PLEASE PROVIDE A VALID ABA ROUTING NUMBER "
                 "FOR THE BENEFICIARY BANK SO WE CAN APPLY THE FUNDS.", "BEST REGARDS", rng.choice(TEAMS)]
    return _mt199(rng, now, narrative, related=original)


def _sgu_reply(rng, now):
    sgu, original = _sgu(rng, now), _trn(rng)
    if rng.random() < 0.5:
        narrative = [f"RE YOUR INQUIRY REF {sgu} RELATIVE TO OUR PAYMENT TRN {original} FOR USD {_amount(rng)}",
                     "IN RESPONSE TO YOUR INQUIRY:",
                     f"1. DETAILED PURPOSE OF PAYMENT. {rng.choice(PURPOSES)}",
                     "2. COPIES OF INVOICES ATTACHED. THANKS IN ADVANCE. BEST REGARDS", rng.choice(TEAMS)]
        return _mt199(rng, now, narrative, related=original)
    narrative = [f"ATTN YR {sgu}, REGARDING YR INQUIRY DTD {now:%Y%m%d}",
                 "PLS BE ADV, WE ARE UNABLE TO LOCATE ORIGINAL PYMT WITH INFORMATION PROVIDED. NEED FULL "
                 "DETAILS OF PYMT, INCLUDING DATE, AMOUNT AND FIELD 20 REF OF ORIGINAL PYMT ORDER.", "REGARDS"]
    return _mt199(rng, now, narrative, related=sgu)


def _cls_mt298(rng, now):
    fields = [("20: Transaction Reference Number", f"RPIS{now:%Y%m%d}"), ("12: Sub-Message Type", "211")]
    narrative = [f":25:{_digits(rng, 8)}", f":30:{now:%y%m%d}", f":21:{_digits(rng, 5)}CBR{_digits(rng, 7)}A",
                 ":13C:/CLSTIME/0800", ":21:", f":32B:USD{rng.randint(10_000, 900_000)},{_digits(rng, 2)}"]
    for hour in ("0900", "1000", "1100", "1200"):
        narrative += [":21:", f":13C:/CLSTIME/{hour}", ":32B:USD0,"]
    return _mt_message(rng, now, "298", "Proprietary Message", fields, "77E: Proprietary Message", narrative)


def _mx(rng, now, message_type: str, name: str):
    iso = now.strftime("%Y-%m-%dT%H:%M:%S")
    mail_id = f"MpBroadcastEMX-{_digits(rng, 4)}-{rng.randint(1, 3):06d}"
    lines = [
        "SSAAPROD@appcet604.us.world.socgen",
        "To OPS USER A GbtoMarGpm; OPS USER B GbtoMarGpm; FUNDS-Transfer-Us-Swift/us/socgen",
        "--- Instance Type and Transmission", "Priority", "Original received from SWIFTNet", ": Normal",
        f"Message Output Reference: {now:%H%M} {now:%y%m%d}sogeus33_finplus{_digits(rng, 15)}",
        "Message Header", f"MX Output: {message_type} CBPRPlus-{message_type}_{name}",
        f"Requestor DN: ou=xxx,o={rng.choice(SENDERS)[0][:8].lower()},o=swift",
        "Responder DN: ou=xxx,o=sogeus33,o=swift", "Service Name: swift.finplus",
        f"SWIFT Reference: swi{_digits(rng, 5)}-{iso}.{_digits(rng, 5)}.{_digits(rng, 7)}Z",
        f"SWIFT Request Reference: SNL{_digits(rng, 5)}-{iso}.{_digits(rng, 5)}.{_digits(rng, 6)}Z",
        f"CBT Reference: {uuid.UUID(int=rng.getrandbits(128), version=4)}",
        f"Store-and-forward Input Time: {now:%H%M}:{iso}",
        "Primary Format : MX", "Secondary Format: Swift",
        "Translation Result: Translated with more field(s) available (Partial)",
        "Translation Result Details: TranslationInfo version 1.0.0.1",
    ]
    subject = f"SWIFT Incoming MX message-{now:%d/%m/%y-%H.%M.%S}{mail_id}"
    return subject, SEP.join(lines)


def _camt056(rng, now):
    return _mx(rng, now, "camt.056.001.08", "FIToFIPaymentCancellationRequest")


def _camt058(rng, now):
    return _mx(rng, now, "camt.058.001.08", "NotificationToReceiveCancellationAdvice")


_BUILDERS = {
    "cancellation_mt192": _cancellation_mt192, "cancellation_return_mt199": _cancellation_return_mt199,
    "camt056": _camt056, "camt058": _camt058, "amendment": _amendment, "callback_ft": _callback_ft,
    "callback_inv": _callback_inv, "aba_request": _aba_request, "sgu_reply": _sgu_reply,
    "cls_mt298": _cls_mt298,
}


def make_sample(kind: str, rng: random.Random, now: datetime) -> tuple[str, str]:
    """Return a realistic (subject, body) pair for one of KINDS."""
    if kind not in _BUILDERS:
        raise ValueError(f"unknown SWIFT sample kind: {kind!r}")
    return _BUILDERS[kind](rng, now)
