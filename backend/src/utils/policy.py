"""The built-in default policy (recall-first) and its replacement labels.

v1 has exactly one policy; per-entity adjustments happen as explicit overrides
from the review UI (Milestone 2), never by editing output text.

Replacement labels exist once per `OutputLanguage`: the anonymized document is
written in the language the user picked for the run, so an English run yields
`[DATE_OF_BIRTH]` where a German one yields `[GEBURTSDATUM]`. Tokens are always
uppercase, bracket-delimited and free of diacritics and spaces — the leakage
validator, the LLM re-check and the PDF export all rely on "in square
brackets" as the marker of an intentional replacement.

The frontend mirrors these labels under `placeholders.*` in
`frontend/locales/*.json` (it shows them as examples in the policy editor);
`backend/tests/unit/test_placeholders.py` keeps the two in sync.
"""

from dataclasses import dataclass

from ..schemas.entities import EntityType, OutputLanguage, TransformationType

DEFAULT_POLICY: dict[EntityType, TransformationType] = {
    EntityType.PERSON_NAME: TransformationType.CONSISTENT_TAG,
    # Masked by default (user decision); switch to GENERALIZE to keep the
    # birth year, or PRESERVE ages, when a use case needs them.
    EntityType.DATE_OF_BIRTH: TransformationType.TYPE_MASK,
    EntityType.AGE: TransformationType.TYPE_MASK,
    EntityType.OTHER_DATE: TransformationType.PRESERVE,  # clinical timelines stay useful
    EntityType.ADDRESS: TransformationType.TYPE_MASK,
    EntityType.PHONE: TransformationType.TYPE_MASK,
    EntityType.EMAIL: TransformationType.TYPE_MASK,
    EntityType.URL: TransformationType.TYPE_MASK,
    EntityType.ID_NUMBER: TransformationType.TYPE_MASK,
    EntityType.ORGANIZATION: TransformationType.TYPE_MASK,
    EntityType.PROFESSION: TransformationType.TYPE_MASK,
    EntityType.OTHER_PII: TransformationType.TYPE_MASK,
}

DEFAULT_OUTPUT_LANGUAGE = OutputLanguage.DE


@dataclass(frozen=True)
class PlaceholderLabels:
    """Every string a run can write into the document."""

    #: TYPE_MASK (and the GENERALIZE fallback) replacement per entity type.
    type_mask: dict[EntityType, str]
    #: REMOVE replacement.
    redacted: str
    #: CONSISTENT_TAG stem — numbered per distinct person: "[PERSON_1]".
    person_tag: str

    def consistent_tag(self, number: int) -> str:
        return f"[{self.person_tag}_{number}]"


PLACEHOLDERS: dict[OutputLanguage, PlaceholderLabels] = {
    OutputLanguage.DE: PlaceholderLabels(
        type_mask={
            EntityType.PERSON_NAME: "[PERSON]",
            EntityType.DATE_OF_BIRTH: "[GEBURTSDATUM]",
            EntityType.OTHER_DATE: "[DATUM]",
            EntityType.AGE: "[ALTER]",
            EntityType.ADDRESS: "[ADRESSE]",
            EntityType.PHONE: "[TELEFON]",
            EntityType.EMAIL: "[E-MAIL]",
            EntityType.URL: "[URL]",
            EntityType.ID_NUMBER: "[ID]",
            EntityType.ORGANIZATION: "[ORGANISATION]",
            EntityType.PROFESSION: "[BERUF]",
            EntityType.OTHER_PII: "[PII]",
        },
        redacted="[GESCHWÄRZT]",
        person_tag="PERSON",
    ),
    OutputLanguage.EN: PlaceholderLabels(
        type_mask={
            EntityType.PERSON_NAME: "[PERSON]",
            EntityType.DATE_OF_BIRTH: "[DATE_OF_BIRTH]",
            EntityType.OTHER_DATE: "[DATE]",
            EntityType.AGE: "[AGE]",
            EntityType.ADDRESS: "[ADDRESS]",
            EntityType.PHONE: "[PHONE]",
            EntityType.EMAIL: "[E-MAIL]",
            EntityType.URL: "[URL]",
            EntityType.ID_NUMBER: "[ID]",
            EntityType.ORGANIZATION: "[ORGANIZATION]",
            EntityType.PROFESSION: "[PROFESSION]",
            EntityType.OTHER_PII: "[PII]",
        },
        redacted="[REDACTED]",
        person_tag="PERSON",
    ),
    OutputLanguage.FR: PlaceholderLabels(
        type_mask={
            EntityType.PERSON_NAME: "[PERSONNE]",
            EntityType.DATE_OF_BIRTH: "[DATE_DE_NAISSANCE]",
            EntityType.OTHER_DATE: "[DATE]",
            EntityType.AGE: "[AGE]",
            EntityType.ADDRESS: "[ADRESSE]",
            EntityType.PHONE: "[TELEPHONE]",
            EntityType.EMAIL: "[E-MAIL]",
            EntityType.URL: "[URL]",
            EntityType.ID_NUMBER: "[ID]",
            EntityType.ORGANIZATION: "[ORGANISATION]",
            EntityType.PROFESSION: "[PROFESSION]",
            EntityType.OTHER_PII: "[PII]",
        },
        redacted="[CAVIARDE]",
        person_tag="PERSONNE",
    ),
    OutputLanguage.ES: PlaceholderLabels(
        type_mask={
            EntityType.PERSON_NAME: "[PERSONA]",
            EntityType.DATE_OF_BIRTH: "[FECHA_DE_NACIMIENTO]",
            EntityType.OTHER_DATE: "[FECHA]",
            EntityType.AGE: "[EDAD]",
            EntityType.ADDRESS: "[DIRECCION]",
            EntityType.PHONE: "[TELEFONO]",
            EntityType.EMAIL: "[CORREO]",
            EntityType.URL: "[URL]",
            EntityType.ID_NUMBER: "[ID]",
            EntityType.ORGANIZATION: "[ORGANIZACION]",
            EntityType.PROFESSION: "[PROFESION]",
            EntityType.OTHER_PII: "[PII]",
        },
        redacted="[OCULTADO]",
        person_tag="PERSONA",
    ),
}

#: Default export file name (without extension) per output language. Mirrors
#: `result.export.filename` in the catalogs — the UI names its own downloads,
#: this is what a direct API consumer gets in Content-Disposition.
EXPORT_FILENAMES: dict[OutputLanguage, str] = {
    OutputLanguage.DE: "anonymisiert",
    OutputLanguage.EN: "anonymized",
    OutputLanguage.FR: "anonymise",
    OutputLanguage.ES: "anonimizado",
}

#: English names of the output languages, for the LLM re-check prompt.
LANGUAGE_NAMES: dict[OutputLanguage, str] = {
    OutputLanguage.DE: "German",
    OutputLanguage.EN: "English",
    OutputLanguage.FR: "French",
    OutputLanguage.ES: "Spanish",
}


def resolve_output_language(language: OutputLanguage | str | None) -> OutputLanguage:
    """Normalize a request-level output language; unknown values fall back to
    the default rather than failing a run over a cosmetic setting."""
    if isinstance(language, OutputLanguage):
        return language
    try:
        return OutputLanguage(str(language))
    except ValueError:
        return DEFAULT_OUTPUT_LANGUAGE


def placeholders_for(language: OutputLanguage | str | None) -> PlaceholderLabels:
    """The replacement labels of a run."""
    return PLACEHOLDERS[resolve_output_language(language)]


def merge_policy(
    partial: dict[EntityType, TransformationType] | None,
) -> dict[EntityType, TransformationType]:
    """A request-level policy overlays the defaults (advanced settings in the
    UI); omitted types keep their default transformation."""
    if not partial:
        return DEFAULT_POLICY
    return {**DEFAULT_POLICY, **partial}
