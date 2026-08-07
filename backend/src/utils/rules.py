"""German-oriented rule-based recognizers for structured identifiers.

Context-aware where possible: a bare number never becomes an identifier unless
it appears near an appropriate label. All offsets are code points into the
unmodified source text.
"""

import re
from dataclasses import dataclass, field

from ..schemas.entities import EntitySpan, EntityType
from .detector_base import DetectionOutcome


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pattern: re.Pattern[str]
    entity_type: EntityType
    confidence: float
    group: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


# Horizontal whitespace only. A field never runs past the end of its line: with
# plain `\s` a multi-word city swallows the first word of the line below
# ("01307 Dresden\nPat"), and a wrapped phone number swallows the digits after
# the break. Not `[ \t]` — text extracted from PDFs is full of non-breaking
# spaces, and those do separate words.
_HSPACE = r"[^\S\r\n]"
# The same idea for use INSIDE another character class, where `_HSPACE` cannot
# go — a negated class does not nest, it would silently degrade into literals.
# Spelled out rather than derived: space, tab, and the non-breaking space that
# PDF extraction and typeset phone numbers are full of.
_HSPACE_CHARS = r" \t\xa0"

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

# Organizational units of a hospital. They carry no proper name of their own
# ("Klinik für Kardiologie"), so an LLM easily reads them as generic nouns —
# yet in a letterhead they sit right in the address block and narrow the
# institution down as much as its name does.
_ORG_UNIT = (
    r"(?:Klinik(?:[ \t]+und[ \t]+Poliklinik)?|Poliklinik|Tagesklinik|Abteilung"
    r"|Institut|Zentrum|Sektion|Ambulanz)"
)
_ORG_UNIT_BARE = r"(?:Poliklinik|Tagesklinik|Abteilung|Institut|Zentrum|Sektion|Ambulanz)"
# The adjective that makes a bare unit noun a named one: "Medizinische Klinik".
# Defined below the stop words, which keep articles out of it ("Die Klinik").
_ORG_ADJECTIVE_BODY = r"[A-ZÄÖÜ][a-zäöüß]+e"
# Words that end a unit name rather than belong to it — without them the
# specialty would run on into the next sentence or into a physician's title.
_ORG_STOP = (
    r"(?:Prof|Dr|Herr|Frau|Sehr|Tel|Fax|Chefarzt|Chefärztin|Oberarzt|Oberärztin"
    r"|Der|Die|Das|Dem|Den|Ein|Eine|Es|Wir|Am|Im|In|Bei|Nach|Von|Vom|Zur|Zum"
    r"|Unsere|Unserer|Diese|Dieser|Seine|Ihre|Jede|Alle|Keine"
    # German capitalizes every noun, so a unit name would otherwise run on into
    # the date that so often follows it ("… Ende März").
    r"|Ende|Anfang|Mitte|Uhr|Datum|Januar|Februar|März|April|Mai|Juni|Juli"
    r"|August|September|Oktober|November|Dezember)\b"
)
# A specialty word, optionally left half of a compound ("Viszeral-, Thorax- und
# Gefäßchirurgie"). Separators stay on the line: a newline ends the unit name.
_ORG_WORD = rf"(?!{_ORG_STOP})[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]*-?"
# A comma continues the name only inside such a compound enumeration; anywhere
# else it ends the field ("… und Dermatologie, Station K1").
_ORG_SEP = r"(?:(?<=-),[ \t]*|[ \t]+und[ \t]+|[ \t]+)"
_ORG_SPECIALTY = rf"{_ORG_WORD}(?:{_ORG_SEP}{_ORG_WORD}){{0,5}}"
_ORG_ADJECTIVE = rf"(?!{_ORG_STOP}){_ORG_ADJECTIVE_BODY}"

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
        re.compile(
            rf"\b[A-Z]{{2}}\d{{2}}(?:{_HSPACE}?[A-Z0-9]{{4}}){{3,7}}(?:{_HSPACE}?[A-Z0-9]{{1,3}})?\b"
        ),
        EntityType.ID_NUMBER,
        0.95,
        metadata={"subtype": "iban"},
    ),
    Rule(
        "de.phone.labelled.v1",
        re.compile(
            rf"\b{_PHONE_LABEL}\s*[:.]?\s*(\+?[\d(][\d{_HSPACE_CHARS}()/\-]{{4,20}}\d)",
            re.IGNORECASE,
        ),
        EntityType.PHONE,
        0.95,
        group=1,
    ),
    Rule(
        "de.phone.intl.v1",
        re.compile(rf"\+49[\d{_HSPACE_CHARS}/\-()]{{5,16}}\d"),
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
            rf"\b(?:[A-ZÄÖÜ][\wäöüß\-]*{_HSPACE}+){{0,2}}[\wäöüß\-]*{_STREET_SUFFIX}"
            rf"{_HSPACE}+\d{{1,4}}(?:{_HSPACE}?[a-hA-H])?\b"
        ),
        EntityType.ADDRESS,
        0.90,
        metadata={"subtype": "street"},
    ),
    Rule(
        "de.address.plz_city.v1",
        re.compile(rf"\b\d{{5}}{_HSPACE}+[A-ZÄÖÜ][a-zäöüß]+(?:(?:{_HSPACE}|-)[A-ZÄÖÜ][a-zäöüß]+)*"),
        EntityType.ADDRESS,
        0.85,
        metadata={"subtype": "plz_city"},
    ),
    Rule(
        "de.org.department.v1",
        re.compile(
            rf"\b(?:{_ORG_ADJECTIVE}[ \t]+)?{_ORG_UNIT}[ \t]+für[ \t]+{_ORG_SPECIALTY}",
        ),
        EntityType.ORGANIZATION,
        0.85,
        metadata={"subtype": "department"},
    ),
    Rule(
        # A named unit without the "für <Fach>" tail: "Medizinische Klinik I",
        # "Sektion Rheumatologie". The second branch omits "Klinik", which is
        # too often a bare noun in running text ("in unserer Klinik Ende März").
        "de.org.unit.v1",
        re.compile(
            rf"\b(?:{_ORG_ADJECTIVE}[ \t]+{_ORG_UNIT}(?:[ \t]+(?:[IVX]{{1,4}}|\d{{1,2}})\b)?"
            rf"|{_ORG_UNIT_BARE}[ \t]+{_ORG_WORD}(?:{_ORG_SEP}{_ORG_WORD})?)"
        ),
        EntityType.ORGANIZATION,
        0.75,
        metadata={"subtype": "department"},
    ),
    Rule(
        "de.org.ward.v1",
        re.compile(r"\b(?:Station|Haus)[ \t]+[A-Z0-9][A-Za-z0-9ÄÖÜäöüß\-/]{0,15}\b"),
        EntityType.ORGANIZATION,
        0.75,
        metadata={"subtype": "ward"},
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
