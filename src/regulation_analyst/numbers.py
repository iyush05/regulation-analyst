"""Parsing and dimension-preserving normalization; never infer a missing number."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from .errors import ResearchError

PRECISION = 34
SCALES = {
    "INR_crore": Decimal("1"),
    "INR_lakh": Decimal("0.01"),
    "INR_million": Decimal("0.1"),
    "INR": Decimal("0.0000001"),
}
# Per-share amounts keep their own dimension and are never scaled into crore.
UNSCALED = {"INR_per_share"}
_NUMBER = re.compile(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3})(?:\.\d+)?")


def parse_number(raw: str) -> Decimal:
    if not isinstance(raw, str):
        raise ValueError("Financial values must be decimal strings, never JSON floats")
    text = raw.strip().replace("\u2212", "-")
    if text.startswith("(") and text.endswith(")"):
        inner = text[1:-1].strip()
        if inner.startswith(("+", "-")):
            raise ValueError("Ambiguous accounting sign")
        text = "-" + inner
    if not _NUMBER.fullmatch(text):
        raise ValueError(f"Not an explicit financial number: {raw!r}")
    value = Decimal(text.replace(",", ""))
    if len(value.as_tuple().digits) > 24:
        raise ValueError("Financial input exceeds the supported 24 significant digits")
    return value


def normalize(raw: str, unit: str) -> Decimal:
    if unit in UNSCALED:
        return parse_number(raw)
    if unit not in SCALES:
        raise ResearchError("invalid_request", f"Unsupported monetary unit: {unit}")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return parse_number(raw) * SCALES[unit]


def normalized_unit(unit: str) -> str:
    return unit if unit in UNSCALED else "INR_crore"


def resolution(raw: str, unit: str) -> Decimal:
    """Half the smallest printed step, normalized: the rounding a printed amount may carry."""
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    scale = Decimal(1) if unit in UNSCALED else SCALES[unit]
    return Decimal(1).scaleb(-decimals) * scale / 2


def indian(value: Decimal, places: int | None = None) -> str:
    """Indian digit grouping, e.g. 4,39,695 or -3,851.64; whole numbers keep no decimals."""
    if places is None:
        places = 0 if value == value.to_integral_value() else 2
    text = display(value, places)
    sign, text = ("-", text[1:]) if text.startswith("-") else ("", text)
    whole, _, fraction = text.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join([head, *groups, tail] if head else [*groups, tail])
    return sign + whole + ("." + fraction if fraction else "")


def decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ResearchError("undefined", "Calculation produced a non-finite value")
    return format(value, "f")


def display(value: Decimal, places: int = 2) -> str:
    with localcontext() as ctx:
        ctx.prec = PRECISION
        try:
            return format(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), "f")
        except InvalidOperation as exc:
            raise ResearchError(
                "undefined", "Value cannot be represented at display precision"
            ) from exc
