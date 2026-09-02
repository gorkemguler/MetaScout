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
    # s[-0:] is the whole string, not "nothing" (there's no negative zero in
    # Python indexing) — keep_end=0 has to be handled explicitly, or a
    # "masked" value silently comes back with the raw secret appended at
    # the end, undoing the masking entirely.
    tail = s[-keep_end:] if keep_end > 0 else ""
    return s[:keep_start] + "*" * (len(s) - keep_start - keep_end) + tail


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

# Cloud storage / file-sharing links pasted into a document's body — a real
# recon finding when the bucket/share turns out to be misconfigured (public,
# no auth). Shown unmasked, unlike the secrets above: the URL itself is the
# finding, not something dangerous to display.
_CLOUD_STORAGE_RE = re.compile(
    r"\bhttps?://(?:"
    r"[a-z0-9.\-]+\.s3(?:[.\-][a-z0-9\-]+)?\.amazonaws\.com(?:/[^\s\"'<>]*)?"
    r"|s3(?:[.\-][a-z0-9\-]+)?\.amazonaws\.com/[a-z0-9.\-]+(?:/[^\s\"'<>]*)?"
    r"|storage\.googleapis\.com/[a-z0-9._\-]+(?:/[^\s\"'<>]*)?"
    r"|[a-z0-9.\-]+\.blob\.core\.windows\.net(?:/[^\s\"'<>]*)?"
    r"|drive\.google\.com/(?:file/d/|drive/folders/|open\?id=)[A-Za-z0-9_\-]+"
    r"|www\.dropbox\.com/scl?/[^\s\"'<>]+"
    r"|[a-z0-9.\-]+\.sharepoint\.com/[^\s\"'<>]+"
    r"|onedrive\.live\.com/[^\s\"'<>]+"
    r")",
    re.IGNORECASE,
)
_CLOUD_URI_RE = re.compile(r"\b(?:s3|gs)://[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9](?:/[^\s\"'<>]*)?", re.IGNORECASE)

# RFC 1918 private ranges + loopback — leaked internal network topology.
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_PRIVATE_IP_RE = re.compile(
    rf"\b(?:10\.{_OCTET}\.{_OCTET}\.{_OCTET}"
    rf"|172\.(?:1[6-9]|2\d|3[01])\.{_OCTET}\.{_OCTET}"
    rf"|192\.168\.{_OCTET}\.{_OCTET}"
    rf"|127\.{_OCTET}\.{_OCTET}\.{_OCTET})\b"
)
# Hostnames ending in a non-public-DNS TLD-like suffix — a classic sign of
# leaked internal infrastructure naming (e.g. a hostname pasted into a
# "how to connect" doc that was never meant to leave the company).
_INTERNAL_HOSTNAME_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.){1,}"
    r"(?:local|internal|corp|lan|intranet|home\.arpa)\b",
    re.IGNORECASE,
)

# Multilingual (TR/EN) signature hints — presence only, not a claim that the
# document is actually validly signed. Kept lowercase to match the lowered
# search text below.
SIGNATURE_KEYWORDS = [
    "imza", "imzalayan", "ıslak imza", "e-imza", "elektronik imza",
    "signature", "signed by", "wet signature", "digitally signed", "digital signature",
]

# Leaked credentials/secrets accidentally left in a document's body text —
# e.g. a config snippet pasted into a "setup notes" doc, or a screenshot's
# OCR'd text. Each entry is (label, compiled pattern, chars to keep visible
# from the start when masking). Deliberately prefix/format-specific (no
# generic "any 40-char base64 string" patterns, no entropy scoring) to keep
# the false-positive rate low — the tradeoff is these only catch well-known
# credential formats, not custom/homegrown ones.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    ("AWS Access Key ID", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 4),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"), 4),
    ("GitHub Personal Access Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b"), 4),
    ("GitHub Fine-Grained Token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), 11),
    ("Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,72}\b"), 5),
    ("Stripe API Key", re.compile(r"\b[sp]k_live_[0-9A-Za-z]{16,}\b"), 8),
    ("Private Key Block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"), 0),
    (
        "Database Connection String",
        re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s:/@'\"]+:[^\s@'\"]+@[^\s/'\"]+"),
        0,
    ),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{10,}\b"), 12),
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


def find_cloud_links(text: str) -> list[RawMatch]:
    """Cloud storage / file-sharing links pasted into a document — flags the
    bucket/share for a manual check (is it actually public?), doesn't try
    to determine that itself. Shown unmasked: the URL is the finding.
    """
    out = []
    for m in _CLOUD_STORAGE_RE.finditer(text):
        val = m.group()
        out.append(RawMatch("cloud_storage", val, val, m.start(), m.end()))
    for m in _CLOUD_URI_RE.finditer(text):
        val = m.group()
        out.append(RawMatch("cloud_storage", val, val, m.start(), m.end()))
    return out


def find_internal_hosts(text: str) -> list[RawMatch]:
    """Private IPs and internal-looking hostnames (.local/.internal/.corp/
    .lan/...) leaked into document text — internal network topology that
    shouldn't be in a publicly reachable document. Shown unmasked: the
    value itself (not sensitive on its own) is the finding.
    """
    out = []
    for m in _PRIVATE_IP_RE.finditer(text):
        val = m.group()
        out.append(RawMatch("internal_host", val, val, m.start(), m.end()))
    for m in _INTERNAL_HOSTNAME_RE.finditer(text):
        val = m.group()
        out.append(RawMatch("internal_host", val, val, m.start(), m.end()))
    return out


def find_secrets(text: str) -> list[RawMatch]:
    """Scans for well-known credential/secret formats leaked into a
    document's body text (a config snippet pasted into a notes doc,
    OCR'd screenshot text, ...). Each hit is masked before it's ever
    returned — the raw secret value never leaves this function.
    """
    out: list[RawMatch] = []
    for label, pattern, keep_start in _SECRET_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group()
            if label == "Private Key Block":
                masked = "-----BEGIN PRIVATE KEY----- (contents not shown)"
            elif label == "Database Connection String":
                scheme, _, rest = raw.partition("://")
                user, _, host_part = rest.partition(":")
                _, _, host = host_part.partition("@")
                masked = f"{scheme}://{user}:****@{host}"
            else:
                masked = _mask_middle(raw, keep_start, 0)
            out.append(RawMatch(f"secret:{label}", raw, masked, m.start(), m.end()))
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
