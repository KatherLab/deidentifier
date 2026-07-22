"""German-oriented rule-based recognizers for structured identifiers.

Context-aware where possible: a bare number never becomes an identifier unless
it appears near an appropriate label. All offsets are code points into the
unmodified source text.
"""

import re
from dataclasses import dataclass, field

from ..schemas.entities import EntitySpan, EntityType
from .detection import DetectionOutcome


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pattern: re.Pattern[str]
    entity_type: EntityType
    confidence: float
    group: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


_DAY = r"(?:0?[1-9]|[12]\d|3[01])"
_MONTH_NUM = r"(?:0?[1-9]|1[0-2])"
_MONTH_NAME = (
    r"(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)"
)
_YEAR = r"(?:19|20)\d{2}"
_NUMERIC_DATE = rf"{_DAY}\.\s?{_MONTH_NUM}\.(?:{_YEAR}|\d{{2}})"
_ISO_DATE = r"(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
_WRITTEN_DATE = rf"{_DAY}\.\s?{_MONTH_NAME}\s{_YEAR}"
_ANY_DATE = rf"(?:{_NUMERIC_DATE}|{_ISO_DATE}|{_WRITTEN_DATE})"

_DOB_LABEL = r"(?:Geburtsdatum|Geb\.\s?-?\s?Dat(?:um|\.)?|geboren(?:\s+am)?|geb\.)"
_PHONE_LABEL = r"(?:Telefon|Telefax|Tel\.?|Fax|Mobil|Handy)"
_ID_LABEL = (
    r"(?:Pat\.\s?-?\s?Nr\.?|Patientennummer|Patienten-?ID|Fallnummer|Fall-?Nr\.?"
    r"|Aufnahmenummer|Aufnahme-?Nr\.?|Versichertennummer|Versicherten-?Nr\.?|KV-?Nummer"
    r"|Befundnummer|Befund-?Nr\.?|Proben-?ID|Auftragsnummer|Auftrags-?Nr\.?|Aktenzeichen)"
)
# Identifier values must start and end alphanumeric so trailing punctuation is excluded.
_ID_VALUE = r"([A-Za-z0-9](?:[A-Za-z0-9\-/.]{0,23}[A-Za-z0-9])?)"
_STREET_SUFFIX = (
    r"(?:[Ss]traße|[Ss]trasse|[Ss]tr\.|[Ww]eg|[Pp]latz|[Aa]llee|[Gg]asse|[Rr]ing|[Dd]amm|[Uu]fer)"
)

RULES: list[Rule] = [
    Rule(
        "de.email.v1",
        re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
        EntityType.EMAIL,
        0.99,
    ),
    Rule(
        "de.url.v1",
        re.compile(r"\bhttps?://[^\s<>\"']+|\bwww\.[^\s<>\"']+", re.IGNORECASE),
        EntityType.URL,
        0.95,
    ),
    Rule(
        "de.iban.v1",
        re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?\b"),
        EntityType.ID_NUMBER,
        0.95,
        metadata={"subtype": "iban"},
    ),
    Rule(
        "de.phone.labelled.v1",
        re.compile(
            r"\b" + _PHONE_LABEL + r"\s*[:.]?\s*(\+?[\d(][\d\s()/\-]{4,20}\d)", re.IGNORECASE
        ),
        EntityType.PHONE,
        0.95,
        group=1,
    ),
    Rule(
        "de.phone.intl.v1",
        re.compile(r"\+49[\d\s/\-()]{5,16}\d"),
        EntityType.PHONE,
        0.90,
    ),
    Rule(
        "de.dob.labelled.v1",
        re.compile(_DOB_LABEL + r"\s*:?\s*(" + _ANY_DATE + r")", re.IGNORECASE),
        EntityType.DATE_OF_BIRTH,
        0.97,
        group=1,
    ),
    Rule("de.date.numeric.v1", re.compile(rf"\b{_NUMERIC_DATE}\b"), EntityType.OTHER_DATE, 0.90),
    Rule("de.date.iso.v1", re.compile(rf"\b{_ISO_DATE}\b"), EntityType.OTHER_DATE, 0.90),
    Rule("de.date.written.v1", re.compile(rf"\b{_WRITTEN_DATE}\b"), EntityType.OTHER_DATE, 0.90),
    Rule(
        "de.id.labelled.v1",
        re.compile(_ID_LABEL + r"\s*:?\s*" + _ID_VALUE, re.IGNORECASE),
        EntityType.ID_NUMBER,
        0.95,
        group=1,
    ),
    Rule(
        "de.id.pattern.v1",
        re.compile(r"\b[A-Z]{2,5}-\d{4,10}\b"),
        EntityType.ID_NUMBER,
        0.80,
    ),
    Rule(
        "de.address.street.v1",
        re.compile(
            rf"\b(?:[A-ZÄÖÜ][\wäöüß\-]*\s+){{0,2}}[\wäöüß\-]*{_STREET_SUFFIX}\s+\d{{1,4}}(?:\s?[a-hA-H])?\b"
        ),
        EntityType.ADDRESS,
        0.90,
        metadata={"subtype": "street"},
    ),
    Rule(
        "de.address.plz_city.v1",
        re.compile(r"\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+(?:[\s\-][A-ZÄÖÜ][a-zäöüß]+)*"),
        EntityType.ADDRESS,
        0.85,
        metadata={"subtype": "plz_city"},
    ),
]


class RuleBasedDetector:
    name = "rules"
    version = "1.0"

    async def detect(self, text: str) -> DetectionOutcome:
        spans: list[EntitySpan] = []
        for rule in RULES:
            for match in rule.pattern.finditer(text):
                start, end = match.span(rule.group)
                if start == end:
                    continue
                spans.append(
                    EntitySpan(
                        start=start,
                        end=end,
                        text=text[start:end],
                        entity_type=rule.entity_type,
                        confidence=rule.confidence,
                        detector=self.name,
                        metadata={"rule_id": rule.rule_id, **rule.metadata},
                    )
                )
        return DetectionOutcome(spans=spans)
