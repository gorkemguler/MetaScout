from __future__ import annotations

import re
from dataclasses import dataclass

try:
    import phonenumbers
    PHONENUMBERS_AVAILABLE = True
except ImportError:  # optional dependency, see pyproject.toml [content-scan]
    phonenumbers = None  # type: ignore[assignment]
    PHONENUMBERS_AVAILABLE = False


@dataclass
class RawMatch:
    category: str
    raw: str
    masked: str
    start: int
    end: int


def _mask_middle(s: str, keep_start: int, keep_end: int) -> str:
    if len(s) <= keep_start + keep_end:
        return "*" * len(s)
    return s[:keep_start] + "*" * (len(s) - keep_start - keep_end) + s[-keep_end:]


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# 11 digits not glued to other digits — checksum-validated below, which is
# what actually keeps the false-positive rate down (most random 11-digit
# runs, e.g. phone/order numbers, fail the checksum).
_TC_CANDIDATE_RE = re.compile(r"(?<!\d)\d{11}(?!\d)")

# ISO 13616 IBAN shape: 2 letters + 2 check digits + up to 30 alphanumerics,
# optionally space-grouped. Checksum-validated below (mod-97), which works
# for every IBAN country, not just Turkey.
_IBAN_CANDIDATE_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{3,4}){2,7}\b")

# Digit runs (13-19 digits, common separators allowed) — Luhn-validated
# below, which is how every major card network's PAN is checksummed.
_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")

# Weak/heuristic signals — useful as a "worth a manual look" hint, not proof.
_DOB_RE = re.compile(
    r"(?:date of birth|birth date|born(?: on)?|d\.?o\.?b\.?|do[gğ]um tarihi)\s*[:\-]?\s*"
    r"(\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4})",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(
    r"\b\d{1,5}[^\n,]{0,40}?\b(sokak|sok\.?|cadde|cad\.?|mahalle(?:si)?|mah\.?|street|st\.?|avenue|ave\.?|road|rd\.?)\b",
    re.IGNORECASE,
)

# Multilingual (TR/EN) signature hints — presence only, not a claim that the
# document is actually validly signed. Kept lowercase to match the lowered
# search text below.
SIGNATURE_KEYWORDS = [
    "imza", "imzalayan", "ıslak imza", "e-imza", "elektronik imza",
    "signature", "signed by", "wet signature", "digitally signed", "digital signature",
]

_IBAN_LETTERS = {chr(65 + i): str(10 + i) for i in range(26)}


def _valid_tc_kimlik(s: str) -> bool:
    if len(s) != 11 or s[0] == "0":
        return False
    digits = [int(c) for c in s]
    odd_sum = sum(digits[0:9:2])
    even_sum = sum(digits[1:8:2])
    d10 = ((odd_sum * 7) - even_sum) % 10
    d11 = sum(digits[:10]) % 10
    return digits[9] == d10 and digits[10] == d11


def _valid_iban(raw: str) -> bool:
    s = raw.replace(" ", "").upper()
    if not (15 <= len(s) <= 34) or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    rearranged = s[4:] + s[:4]
    numeric = "".join(_IBAN_LETTERS.get(c, c) for c in rearranged)
    if not numeric.isdigit():
        return False
    return int(numeric) % 97 == 1


def _valid_luhn(digits: str) -> bool:
    nums = [int(d) for d in digits]
    odd = nums[-1::-2]
    even = nums[-2::-2]
    checksum = sum(odd) + sum(sum(divmod(d * 2, 10)) for d in even)
    return checksum % 10 == 0


def find_emails(text: str) -> list[RawMatch]:
    return [RawMatch("email", m.group(), m.group(), m.start(), m.end()) for m in EMAIL_RE.finditer(text)]


def find_phones(text: str) -> list[RawMatch]:
    """Uses Google's libphonenumber (via the `phonenumbers` package) rather
    than a hand-rolled regex — actual international phone number formats
    vary too much for a regex to cover without a very high false-positive
    rate. Runs once with no default region (catches explicit +country-code
    numbers worldwide) and once assuming Turkey (catches local-format
    Turkish numbers with no country code), deduped by E.164 form.
    """
    if not PHONENUMBERS_AVAILABLE:
        return []
    out: list[RawMatch] = []
    seen: set[str] = set()
    for region in (None, "TR"):
        try:
            matches = phonenumbers.PhoneNumberMatcher(text, region)
        except Exception:
            continue
        for m in matches:
            e164 = phonenumbers.format_number(m.number, phonenumbers.PhoneNumberFormat.E164)
            if e164 in seen:
                continue
            seen.add(e164)
            out.append(RawMatch("phone", m.raw_string, e164, m.start, m.end))
    return out


def find_tc_kimlik(text: str) -> list[RawMatch]:
    out = []
    for m in _TC_CANDIDATE_RE.finditer(text):
        val = m.group()
        if _valid_tc_kimlik(val):
            out.append(RawMatch("tc_kimlik", val, _mask_middle(val, 3, 2), m.start(), m.end()))
    return out


def find_ibans(text: str) -> list[RawMatch]:
    out = []
    for m in _IBAN_CANDIDATE_RE.finditer(text):
        val = m.group()
        if _valid_iban(val):
            compact = val.replace(" ", "")
            out.append(RawMatch("iban", val, _mask_middle(compact, 4, 4), m.start(), m.end()))
    return out


def find_credit_cards(text: str) -> list[RawMatch]:
    out = []
    for m in _CARD_CANDIDATE_RE.finditer(text):
        digits = re.sub(r"[ -]", "", m.group())
        if 13 <= len(digits) <= 19 and _valid_luhn(digits):
            out.append(RawMatch("credit_card", digits, _mask_middle(digits, 0, 4), m.start(), m.end()))
    return out


def find_dob_hints(text: str) -> list[RawMatch]:
    out = []
    for m in _DOB_RE.finditer(text):
        val = m.group(1)
        out.append(RawMatch("dob", val, val, m.start(1), m.end(1)))
    return out


def find_address_hints(text: str) -> list[RawMatch]:
    out = []
    for m in _ADDRESS_RE.finditer(text):
        val = m.group().strip()
        out.append(RawMatch("address", val, val, m.start(), m.end()))
    return out


def find_signature_keywords(text: str) -> list[RawMatch]:
    # Python's str.lower() maps Turkish "İ" (dotted capital I, U+0130) to
    # "i̇" (i + a combining dot above, U+0307) rather than plain "i" — so
    # "İmzalayan" would otherwise never match the "imzalayan" keyword below.
    # This is the classic "Turkish I problem"; normalize İ->i first.
    lowered = text.replace("İ", "i").lower()
    out = []
    for kw in SIGNATURE_KEYWORDS:
        idx = lowered.find(kw)
        if idx != -1:
            out.append(RawMatch("signature", kw, kw, idx, idx + len(kw)))
    return out
