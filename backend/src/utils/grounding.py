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
_MIN_NAME_PART_LENGTH = 3

# Salutations/titles that must not be grounded standalone as name parts.
_NAME_PART_STOPWORDS = {
    "herr",
    "herrn",
    "frau",
    "fräulein",
    "familie",
    "dr",
    "prof",
    "med",
    "phil",
    "dent",
    "rer",
    "nat",
    "dipl",
    "univ",
    "pd",
    "von",
    "van",
    "de",
    "zu",
    "der",
    "und",
}


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
            # OCR text and LLM output may disagree on umlaut spelling
            # ("Müller" vs "Mueller") or the text may be hyphenated across
            # line breaks ("Muster-\nmann").
            occurrences = _locate_fuzzy(text, needle)
            partial = bool(occurrences)
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
        if mention.entity_type != EntityType.PERSON_NAME:
            # Also cover case-variant occurrences ("Gender: Female" reported,
            # "a 48-year-old female" in prose). Names stay case-strict:
            # German surnames like Ernst/Frank/Weiß collide with common words.
            occurrences = occurrences + [
                span
                for span in _find_normalized(text, needle, ignore_case=True)
                if span not in occurrences and _word_bounded(text, *span)
            ]
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
            if mention.entity_type == EntityType.PERSON_NAME:
                metadata["tag_group"] = _person_tag_group(mention.text)
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

    spans.extend(_ground_name_parts(text, mentions, spans, seen))
    return spans, warnings


def _ground_name_parts(
    text: str,
    mentions: list[Mention],
    existing: list[EntitySpan],
    seen: set[tuple[int, int, EntityType]],
) -> list[EntitySpan]:
    """Ground individual tokens of multi-token person names.

    A letter that introduces "Elisabeth Bauer" often continues with just
    "Elisabeth" — the LLM reports the full name once, so standalone first or
    last names would slip through. Tokens are grounded word-bounded and only
    outside spans that are already covered (recall over precision)."""
    covered = [(span.start, span.end) for span in existing]
    extra: list[EntitySpan] = []
    for mention in mentions:
        if mention.entity_type != EntityType.PERSON_NAME:
            continue
        tokens = mention.text.split()
        if len(tokens) < 2:
            continue
        for token in tokens:
            cleaned = token.strip(".,;:()")
            if len(cleaned) < _MIN_NAME_PART_LENGTH:
                continue
            if cleaned.lower().strip(".") in _NAME_PART_STOPWORDS:
                continue
            for start, end in _find_exact(text, cleaned):
                if not _word_bounded(text, start, end):
                    continue
                if any(c_start <= start and end <= c_end for c_start, c_end in covered):
                    continue
                key = (start, end, EntityType.PERSON_NAME)
                if key in seen:
                    continue
                seen.add(key)
                covered.append((start, end))
                metadata: dict[str, str] = {
                    "grounding": "name_part",
                    # Parts inherit their parent mention's tag group so
                    # "Elisabeth" gets the same [PERSON_n] as "Elisabeth Bauer".
                    "tag_group": _person_tag_group(mention.text),
                }
                if mention.role:
                    metadata["role"] = mention.role
                extra.append(
                    EntitySpan(
                        start=start,
                        end=end,
                        text=text[start:end],
                        entity_type=EntityType.PERSON_NAME,
                        confidence=_LLM_CONFIDENCE,
                        detector="llm",
                        metadata=metadata,
                    )
                )
    return extra


def _person_tag_group(mention_text: str) -> str:
    """Canonical person key: the mention minus titles/salutations, casefolded.

    Makes "Dr. med. Anna Beispiel", "Anna Beispiel" and the name part "Anna"
    share one consistent [PERSON_n] tag across the whole document. Surname-only
    mentions still get their own group (no surname-alone coreference)."""
    tokens = [token.strip(".,;:()") for token in mention_text.split()]
    core = [t for t in tokens if t and t.lower().strip(".") not in _NAME_PART_STOPWORDS]
    joined = " ".join(core) if core else mention_text
    return re.sub(r"\s+", " ", joined).strip().casefold()


def _locate(text: str, needle: str) -> list[tuple[int, int]]:
    occurrences = _find_exact(text, needle)
    if not occurrences:
        occurrences = _find_normalized(text, needle, ignore_case=False)
    if not occurrences:
        occurrences = _find_normalized(text, needle, ignore_case=True)
    return occurrences


_UMLAUT_PAIRS = [
    ("ä", "ae"),
    ("ö", "oe"),
    ("ü", "ue"),
    ("Ä", "Ae"),
    ("Ö", "Oe"),
    ("Ü", "Ue"),
    ("ß", "ss"),
]


def _umlaut_variants(needle: str) -> list[str]:
    to_digraph = needle
    for umlaut, digraph in _UMLAUT_PAIRS:
        to_digraph = to_digraph.replace(umlaut, digraph)
    to_umlaut = needle
    for umlaut, digraph in _UMLAUT_PAIRS:
        to_umlaut = to_umlaut.replace(digraph, umlaut)
    return [variant for variant in (to_digraph, to_umlaut) if variant != needle]


def _find_dehyphenated(text: str, needle: str) -> list[tuple[int, int]]:
    """Match needles broken by soft hyphenation in the text ("Muster-\\nmann")."""
    tokens = needle.split()
    if not tokens:
        return []
    token_patterns = [r"(?:-\s*)?".join(re.escape(char) for char in token) for token in tokens]
    pattern = r"\s+".join(token_patterns)
    return [match.span() for match in re.finditer(pattern, text)]


def _locate_fuzzy(text: str, needle: str) -> list[tuple[int, int]]:
    for variant in _umlaut_variants(needle):
        occurrences = _locate(text, variant)
        if occurrences:
            return occurrences
    if len(needle) >= 5:
        occurrences = [
            span for span in _find_dehyphenated(text, needle) if _word_bounded(text, *span)
        ]
        if occurrences:
            return occurrences
    return []


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
