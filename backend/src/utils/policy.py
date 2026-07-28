"""The built-in default policy (recall-first) and its replacement labels.

v1 has exactly one policy; per-entity adjustments happen as explicit overrides
from the review UI (Milestone 2), never by editing output text.
"""

from ..schemas.entities import EntityType, TransformationType

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

TYPE_MASK_LABELS: dict[EntityType, str] = {
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
}

REDACTED_LABEL = "[GESCHWÄRZT]"


def merge_policy(
    partial: dict[EntityType, TransformationType] | None,
) -> dict[EntityType, TransformationType]:
    """A request-level policy overlays the defaults (advanced settings in the
    UI); omitted types keep their default transformation."""
    if not partial:
        return DEFAULT_POLICY
    return {**DEFAULT_POLICY, **partial}
