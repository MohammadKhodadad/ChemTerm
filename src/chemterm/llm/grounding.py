"""Mechanical exact-span grounding for LLM-copied source text."""

from __future__ import annotations


class ExactSpanError(ValueError):
    """Raised when copied text is absent from its claimed source."""


def ground_exact_span(
    source_text: str,
    copied_text: str,
    *,
    hinted_start: int | None = None,
    hinted_end: int | None = None,
) -> tuple[int, int]:
    """Return an exact span, correcting unreliable model-generated offsets."""

    if (
        hinted_start is not None
        and hinted_end is not None
        and 0 <= hinted_start < hinted_end <= len(source_text)
        and source_text[hinted_start:hinted_end] == copied_text
    ):
        return hinted_start, hinted_end

    starts: list[int] = []
    search_from = 0
    while True:
        start = source_text.find(copied_text, search_from)
        if start < 0:
            break
        starts.append(start)
        search_from = start + 1

    if not starts:
        raise ExactSpanError(f"copied text {copied_text!r} is absent from source text")

    if hinted_start is None:
        start = starts[0]
    else:
        start = min(starts, key=lambda item: (abs(item - hinted_start), item))
    return start, start + len(copied_text)
