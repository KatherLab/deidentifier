"""Deterministic grounding of LLM-reported entity mentions to source offsets.

LLMs are unreliable at character offsets, so the LLM detector only returns
mention strings. This module locates every occurrence of each mention in the
immutable source text: exact match first, then a whitespace-normalized match,
then case-insensitive as a last resort. Mentions that cannot be located become
warnings (without their content — it must not leak into logs or responses in
unexpected places; the type name is enough for the user to review).
"""

import re
from dataclasses import dataclass

from ..schemas.entities import EntitySpan, EntityType

_LLM_CONFIDENCE = 0.9
_MIN_MENTION_LENGTH = 2
_MIN_TRIMMED_LENGTH = 4


@dataclass(frozen=True)
class Mention:
    text: str
    entity_type: EntityType
    role: str = ""


def ground_mentions(text: str, mentions: list[Mention]) -> tuple[list[EntitySpan], list[str]]:
    spans: list[EntitySpan] = []
    warnings: list[str] = []
    seen: set[tuple[int, int, EntityType]] = set()

    for mention in mentions:
        needle = mention.text.strip()
        if len(needle) < _MIN_MENTION_LENGTH:
            continue
        occurrences = _locate(text, needle)
        partial = False
        if not occurrences:
            # The LLM may have normalized inflected German prefixes ("Herrn" →
            # "Herr") or added a salutation not present in the text. Drop
            # leading tokens one by one and retry, requiring word boundaries so
            # a shortened needle cannot match inside another word.
            tokens = needle.split()
            while len(tokens) > 1 and not occurrences:
                tokens = tokens[1:]
                trimmed = " ".join(tokens)
                if len(trimmed) < _MIN_TRIMMED_LENGTH:
                    break
                occurrences = [
                    span for span in _locate(text, trimmed) if _word_bounded(text, *span)
                ]
            partial = bool(occurrences)
        if not occurrences:
            warnings.append(
                f"The LLM reported a {mention.entity_type} mention that could not be "
                "located in the source text; please review the document manually."
            )
            continue
        for start, end in occurrences:
            key = (start, end, mention.entity_type)
            if key in seen:
                continue
            seen.add(key)
            metadata: dict[str, str] = {}
            if mention.role:
                metadata["role"] = mention.role
            if partial:
                metadata["grounding"] = "partial"
            spans.append(
                EntitySpan(
                    start=start,
                    end=end,
                    text=text[start:end],
                    entity_type=mention.entity_type,
                    confidence=_LLM_CONFIDENCE,
                    detector="llm",
                    metadata=metadata,
                )
            )
    return spans, warnings


def _locate(text: str, needle: str) -> list[tuple[int, int]]:
    occurrences = _find_exact(text, needle)
    if not occurrences:
        occurrences = _find_normalized(text, needle, ignore_case=False)
    if not occurrences:
        occurrences = _find_normalized(text, needle, ignore_case=True)
    return occurrences


def _word_bounded(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else " "
    after = text[end] if end < len(text) else " "
    return not (before.isalnum() or after.isalnum())


def _find_exact(text: str, needle: str) -> list[tuple[int, int]]:
    occurrences: list[tuple[int, int]] = []
    index = text.find(needle)
    while index != -1:
        occurrences.append((index, index + len(needle)))
        index = text.find(needle, index + 1)
    return occurrences


def _find_normalized(text: str, needle: str, *, ignore_case: bool) -> list[tuple[int, int]]:
    """Match with flexible whitespace (the LLM may collapse line breaks)."""
    tokens = needle.split()
    if not tokens:
        return []
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    flags = re.IGNORECASE if ignore_case else 0
    return [match.span() for match in re.finditer(pattern, text, flags)]
