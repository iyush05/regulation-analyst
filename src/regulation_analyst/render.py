"""Markdown rendering of verified results. Every number shown comes from a canonical fact or a
recomputed calculation; changes between years are computed here in Decimal, never by a model."""

from decimal import Decimal, localcontext

from .numbers import PRECISION, display, indian

TRUST_NOTE = {"automated": "automated extraction", "llm_resolved": "LLM-resolved"}


def value_text(value, unit: str) -> str:
    amount = Decimal(value)
    if unit == "percent":
        return f"{display(amount)}%"
    if unit == "percentage_points":
        return f"{display(amount)} pp"
    if unit == "basis_points":
        return f"{display(amount)} bps"
    if unit == "times":
        return f"{display(amount)}x"
    if unit == "INR_per_share":
        return f"₹{display(amount)}/share"
    return f"₹{indian(amount)} cr"


def change_text(first, last, unit: str) -> str:
    """Change from the first to the last year shown, in the measure's natural terms."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        a, b = Decimal(first), Decimal(last)
        if unit == "percent":
            return signed(display(b - a)) + " pp"
        if unit == "times":
            return signed(display(b - a)) + "x"
        if a == 0:
            return "n/a"
        return signed(display((b / a - 1) * 100)) + "%"


def signed(text: str) -> str:
    return text if text.startswith("-") or text.strip("0.") == "" else "+" + text


class Sources:
    """Numbered citations, one per source page, in order of first use."""

    def __init__(self):
        self.items: dict[str, tuple[int, dict]] = {}

    def cite(self, source: dict) -> str:
        key = source["url"]
        if key not in self.items:
            self.items[key] = (len(self.items) + 1, source)
        return f"[{self.items[key][0]}]"

    def cite_all(self, sources) -> str:
        return "".join(dict.fromkeys(self.cite(s) for s in sources))

    def lines(self) -> list[str]:
        out = []
        for number, source in self.items.values():
            note = TRUST_NOTE.get(source.get("trust"))
            out.append(
                f"[{number}] [{source['title']}, {source['location']}]({source['url']})"
                + (f" — unreviewed: {note}" if note else "")
            )
        return out


def pivot(items, key_of, year_of):
    """Group items by key with one value per fiscal year, keeping first-seen order."""
    table: dict[tuple, dict[int, dict]] = {}
    for item in items:
        table.setdefault(key_of(item), {})[year_of(item)] = item
    return table


def year_table(title, rows, years, sources: Sources, with_change: bool) -> list[str]:
    """rows: {(company, label, unit): {year: (value, [sources])}}."""
    if not rows:
        return []
    header = ["Company", title, *(f"FY{y % 100:02d}" for y in years)]
    if with_change and len(years) > 1:
        header.append(f"Change FY{years[0] % 100:02d}→FY{years[-1] % 100:02d}")
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * 2 + "---:|" * (len(header) - 2)]
    for (company, label, unit), by_year in rows.items():
        cells = [company, label]
        for year in years:
            if year in by_year:
                value, cited = by_year[year]
                cells.append(f"{value_text(value, unit)} {sources.cite_all(cited)}")
            else:
                cells.append("—")
        if with_change and len(years) > 1:
            ends = [by_year.get(years[0]), by_year.get(years[-1])]
            cells.append(change_text(ends[0][0], ends[1][0], unit) if all(ends) else "—")
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def name(metric: str) -> str:
    return metric.removesuffix(".v1").replace("_", " ")


def assemble(sections: list[tuple[str, list[str]]], sources: Sources) -> str:
    parts = []
    for heading, body in sections:
        if body:
            parts.append((f"**{heading}**\n\n" if heading else "") + "\n".join(body))
    if sources.items:
        parts.append("**Sources**\n\n" + "\n".join(sources.lines()))
    return "\n\n".join(parts)


def bullets(texts) -> list[str]:
    return [f"- {text}" for text in dict.fromkeys(texts)]
