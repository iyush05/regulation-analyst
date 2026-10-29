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
    if unit not in SCALES:
        raise ResearchError("invalid_request", f"Unsupported monetary unit: {unit}")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return parse_number(raw) * SCALES[unit]


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
