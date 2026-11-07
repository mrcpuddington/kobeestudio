"""Small, deterministic parser for KiCad-style vector text runs."""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class TextRun:
    text: str
    scale: float = 1.0
    baseline: float = 0.0
    overline: bool = False
    underline: bool = False


def formatted_runs(text: str) -> Tuple[TextRun, ...]:
    """Parse ^{superscript}, _{subscript}, ~{overline}, !{underline}.

    Baselines are fractions of the parent em, with positive y down. Literal
    formatting characters can be escaped with a backslash. Plain braces and
    markers without braces remain ordinary text.
    """
    result = []

    def parse(index, style, depth=0):
        if depth > 8:
            raise ValueError("Text formatting supports at most eight nested groups")
        pending = []

        def flush():
            if pending:
                result.append(TextRun("".join(pending), *style))
                pending.clear()

        while index < len(text):
            char = text[index]
            if char == "\\" and index + 1 < len(text) and text[index + 1] in "_^~!{}\\":
                pending.append(text[index + 1])
                index += 2
                continue
            if char == "}" and depth:
                flush()
                return index + 1
            if char in "_^~!" and text[index + 1:index + 2] == "{":
                flush()
                scale, baseline, overline, underline = style
                if char in "_^":
                    baseline += scale * (0.25 if char == "_" else -0.45)
                    scale *= 0.65
                elif char == "~":
                    overline = True
                else:
                    underline = True
                index = parse(index + 2, (scale, baseline, overline, underline), depth + 1)
            else:
                pending.append(char)
                index += 1
        if depth:
            raise ValueError("Close each text formatting group with }. Example: D_{0} or ~{RESET}")
        flush()
        return index

    parse(0, (1.0, 0.0, False, False))
    return tuple(result)
