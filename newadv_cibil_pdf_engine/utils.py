"""Small, dependency-free formatting/lookup helpers shared by the parser
and the Jinja2 templates.

Nothing in this module ever raises on bad/missing input - every function
degrades to a safe placeholder (``None``, ``""`` or ``"-"``) instead, so a
malformed or partially-populated report never crashes rendering.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Mapping

PLACEHOLDER = "-"


def safe_get(obj: Any, *path: str, default: Any = None) -> Any:
    """Walk ``path`` through nested dicts/lists, returning ``default`` the
    moment anything is missing, ``None``, or not a dict.
    """
    cur = obj
    for key in path:
        if isinstance(cur, Mapping):
            cur = cur.get(key)
        else:
            return default
        if cur is None:
            return default
    return cur


def _numeric_text(value: Any) -> Any:
    """Strip the decorations bureau feeds put on amounts - thousands
    separators (``"1,400"``), a rupee sign, surrounding whitespace - so the
    remainder can go through ``float()``. Non-strings pass through as-is.
    """
    if isinstance(value, str):
        return value.replace(",", "").replace("₹", "").strip()
    return value


def as_int(value: Any) -> int | None:
    value = _numeric_text(value)
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def as_float(value: Any) -> float | None:
    value = _numeric_text(value)
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


_DATE_PATTERNS = (
    # YYYYMMDD (raw ICRS subject shape)
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), ("%Y", "%m", "%d")),
    # YYYY-MM-DD(+TZ) (normalised TrueLinkCreditReport shape)
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})"), ("%Y", "%m", "%d")),
    # DD-MM-YYYY / DD/MM/YYYY (B2C-REPORT shape)
    (re.compile(r"^(\d{2})[-/](\d{2})[-/](\d{4})$"), ("%d", "%m", "%Y")),
)


def parse_bureau_date(value: Any) -> _dt.date | None:
    """Parse the date shapes seen in bureau JSON: ``"20240111"``,
    ``"2024-01-11+05:30"`` and ``"11-01-2024"``. Returns ``None`` for anything else instead of
    raising, so a malformed date never breaks rendering.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for pattern, order in _DATE_PATTERNS:
        m = pattern.match(text)
        if m:
            parts = dict(zip(order, (int(g) for g in m.groups())))
            try:
                return _dt.date(parts["%Y"], parts["%m"], parts["%d"])
            except ValueError:
                return None
    return None


_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1
)}
_MONTH_YEAR_RE = re.compile(r"^([A-Za-z]{3})[A-Za-z]*[:\-/ ](\d{4})$")


def parse_month_year(value: Any) -> tuple[int, int] | None:
    """Parse a payment-history month label such as ``"Jan:2026"`` into
    ``(year, month)``. Returns ``None`` for anything unrecognisable.
    """
    m = _MONTH_YEAR_RE.match(clean_text(value))
    if not m:
        return None
    month = _MONTHS.get(m.group(1).lower())
    return (int(m.group(2)), month) if month else None


def split_pipe(value: Any) -> list[str]:
    """Split a ``|``-delimited bureau list (``"a|b|c|"``). The trailing
    delimiter the feed always appends is dropped; interior empty entries
    are kept so positions stay aligned with a sibling list.
    """
    if not isinstance(value, str) or not value:
        return []
    items = value.split("|")
    if items and items[-1] == "":
        items.pop()
    return [i.strip() for i in items]


def format_date(value: Any, fmt: str = "%d/%m/%Y") -> str:
    """Format a bureau date value the way the reference PDF does
    (``DD/MM/YYYY``), or ``"-"`` if it can't be parsed/is absent.
    """
    d = parse_bureau_date(value) if not isinstance(value, _dt.date) else value
    if d is None:
        return PLACEHOLDER
    return d.strftime(fmt)


def format_datetime_now(fmt: str = "%d/%m/%Y %H:%M") -> str:
    return _dt.datetime.now().strftime(fmt)


_INDIAN_GROUP_RE = re.compile(r"(\d+)(\d{3})$")


def format_indian_number(value: Any) -> str:
    """Group an integer using the Indian numbering system (lakh/crore):
    ``4000000`` -> ``"40,00,000"``. Negative numbers keep their sign.
    """
    n = as_int(value)
    if n is None:
        return PLACEHOLDER
    sign = "-" if n < 0 else ""
    n = abs(n)
    s = str(n)
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + ",".join(parts) + "," + tail


def format_currency(value: Any, symbol: str = "₹") -> str:
    """Render a bureau amount the way the reference PDF does: Indian
    grouping with a rupee sign, or ``"-"`` for missing/sentinel (negative)
    values - the bureau feed uses ``-1`` to mean "not applicable", which
    the reference PDF renders as a blank dash, not "-1" or "-₹1".
    """
    n = as_int(value)
    if n is None or n < 0:
        return PLACEHOLDER
    return f"{symbol}{format_indian_number(n)}"


def format_optional_number(value: Any) -> str:
    n = as_int(value)
    if n is None or n < 0:
        return PLACEHOLDER
    return format_indian_number(n)


def format_percent(value: Any) -> str:
    f = as_float(value)
    if f is None or f < 0:
        return PLACEHOLDER
    # Bureau rates are already percentages (e.g. 13.0 == 13%), trim
    # trailing zeros for a cleaner look (13.0 -> "13", 12.05 -> "12.05").
    text = f"{f:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def mask_account_number(number: Any, visible: int = 4) -> str:
    """Mask all but the last ``visible`` characters of an account number,
    preserving its length (``0000004501140095X`` style feeds keep looking
    like an account number, not a fixed-width placeholder).
    """
    if number is None:
        return PLACEHOLDER
    text = str(number)
    if len(text) <= visible:
        return text
    return ("X" * (len(text) - visible)) + text[-visible:]


def coded_label(
    coded: Any,
    table: Mapping[str, str] | None = None,
    *,
    raw_label: str = "",
    default: str = PLACEHOLDER,
) -> str:
    """Resolve a bureau "coded field" to a human label.

    Handles both JSON shapes:
    * ``{"symbol": "05", "description": "Personal Loan", ...}`` - prefers
      ``description``, then ``abbreviation``, then looks ``symbol`` up in
      ``table``, then falls back to the raw symbol.
    * a bare string/number code (``"05"``) - looks it up in ``table``
      directly, falling back to the raw code.

    If nothing at all can be resolved, returns ``default`` (unless the raw
    code itself is shown, per ``raw_label``).
    """
    table = table or {}
    if isinstance(coded, Mapping):
        description = (coded.get("description") or "").strip()
        if description:
            return description
        abbreviation = (coded.get("abbreviation") or "").strip()
        if abbreviation:
            return abbreviation
        symbol = coded.get("symbol")
        code = str(symbol).strip() if symbol not in (None, "") else ""
    elif coded is None or coded == "":
        code = ""
    else:
        code = str(coded).strip()

    if not code:
        return default
    if code in table:
        return table[code]
    return f"{raw_label} {code}".strip() if raw_label else code


def ensure_list(value: Any) -> list:
    """Normalise a field that is documented as "a list of dict entries".

    Some upstream JSON producers collapse a repeated element down to a
    bare object instead of a one-element array when it occurs exactly
    once (seen in practice for ``Borrower.IdentifierPartition.Identifier``,
    ``BorrowerAddress``, ``BorrowerTelephone``, ``EmailAddress`` and
    ``TradeLinePartition`` in real TransUnion TLCR feeds - iterating such a
    bare dict directly yields its *keys* as strings, not the record itself,
    which is what used to crash the parser). Treat that shape as a
    one-element list. Anything else that isn't already a list becomes an
    empty list rather than raising.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        return [value]
    return []


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def has_meaningful_value(value: Any) -> bool:
    """True unless ``value`` is one of the "nothing here" shapes: ``None``,
    an empty/whitespace-only string, or an empty dict/list/tuple/set.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return True


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def join_nonblank(parts: list[Any], sep: str = ", ") -> str:
    return sep.join(clean_text(p) for p in parts if not is_blank(p))


def format_payment_status(raw: Any, adverse_classes: set[str] | frozenset[str] = frozenset()) -> str | None:
    """Normalise one payment-history cell to the short code the reference
    PDF prints (legend: STD/SUB/DBT/LSS/SMA/XXX, ``###`` = days past due).

    Accepts the B2C ``"DPD/CLASS"`` pair (``"000/STD"``, ``"030/SUB"``,
    ``"XXX/XXX"``) as well as a bare DPD count or bare class code:

    * numeric DPD with a neutral class (STD / XXX / blank) -> the DPD count
      without zero padding (``"000/STD"`` -> ``"0"``, ``"045/STD"`` -> ``"45"``)
    * numeric DPD with an adverse class (``adverse_classes``) -> both parts,
      so the classification is not lost (``"000/SUB"`` -> ``"0/SUB"``)
    * non-numeric DPD (``"XXX"``, ``"DDD"``, ...) -> the class if one is
      reported, else the DPD code itself
    * blank -> ``None`` (an empty cell - "no data this month")

    Unknown codes are passed through verbatim, never reinterpreted.
    """
    text = clean_text(raw)
    if not text:
        return None
    dpd, _, cls = text.partition("/")
    dpd, cls = dpd.strip(), cls.strip().upper()
    if dpd.isdigit():
        count = str(int(dpd))
        if cls in adverse_classes:
            return f"{count}/{cls}"
        return count
    if cls:
        return cls
    return dpd.upper() or None
