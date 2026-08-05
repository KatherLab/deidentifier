"""The replacement placeholders are produced by the backend but previewed by
the policy editor, so both halves must agree — otherwise the UI advertises
"[ADRESSE]" for a run that writes "[ADDRESS]"."""

import json
from pathlib import Path

import pytest

from backend.src.schemas.entities import EntityType, OutputLanguage, TransformationType
from backend.src.utils.policy import (
    DEFAULT_OUTPUT_LANGUAGE,
    EXPORT_FILENAMES,
    PLACEHOLDERS,
    placeholders_for,
    resolve_output_language,
)
from backend.src.utils.transformation import apply_policy

_LOCALES_DIR = Path(__file__).resolve().parents[3] / "frontend" / "locales"


def _catalog(language: OutputLanguage) -> dict:
    return json.loads((_LOCALES_DIR / f"{language.value}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("language", list(OutputLanguage))
def test_every_language_has_a_label_for_every_entity_type(language):
    labels = PLACEHOLDERS[language]
    assert set(labels.type_mask) == set(EntityType)
    for entity_type, label in labels.type_mask.items():
        assert label.startswith("[") and label.endswith("]"), entity_type
    assert labels.redacted.startswith("[") and labels.redacted.endswith("]")
    assert labels.consistent_tag(1) == f"[{labels.person_tag}_1]"


@pytest.mark.parametrize("language", list(OutputLanguage))
def test_frontend_catalog_mirrors_the_backend_labels(language):
    placeholders = _catalog(language)["placeholders"]
    labels = PLACEHOLDERS[language]

    assert placeholders["type_mask"] == {
        entity_type.value: label for entity_type, label in labels.type_mask.items()
    }
    assert placeholders["redacted"] == labels.redacted
    assert placeholders["person_tag"] == labels.person_tag


@pytest.mark.parametrize("language", list(OutputLanguage))
def test_export_filename_matches_the_catalog(language):
    """The UI names its own downloads from the catalog and the backend names
    the ones it serves directly — one document, one file name."""
    assert EXPORT_FILENAMES[language] == _catalog(language)["result"]["export"]["filename"]


def test_resolve_output_language_falls_back_instead_of_failing():
    # A cosmetic setting must never take a document down.
    assert resolve_output_language(None) is DEFAULT_OUTPUT_LANGUAGE
    assert resolve_output_language("klingon") is DEFAULT_OUTPUT_LANGUAGE
    assert resolve_output_language("fr") is OutputLanguage.FR
    assert resolve_output_language(OutputLanguage.ES) is OutputLanguage.ES


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (OutputLanguage.DE, ("[PERSON_1]", "[GEBURTSDATUM]", "[GESCHWÄRZT]")),
        (OutputLanguage.EN, ("[PERSON_1]", "[DATE_OF_BIRTH]", "[REDACTED]")),
        (OutputLanguage.FR, ("[PERSONNE_1]", "[DATE_DE_NAISSANCE]", "[CAVIARDE]")),
        (OutputLanguage.ES, ("[PERSONA_1]", "[FECHA_DE_NACIMIENTO]", "[OCULTADO]")),
    ],
)
def test_apply_policy_writes_the_placeholders_of_the_output_language(language, expected):
    from backend.src.schemas.entities import EntitySpan

    text = "Max Mustermann, geb. 01.02.1980, Beruf: Bäcker"
    spans = [
        EntitySpan(
            start=0,
            end=14,
            text="Max Mustermann",
            entity_type=EntityType.PERSON_NAME,
            confidence=1.0,
            detector="test",
        ),
        EntitySpan(
            start=21,
            end=31,
            text="01.02.1980",
            entity_type=EntityType.DATE_OF_BIRTH,
            confidence=1.0,
            detector="test",
        ),
        EntitySpan(
            start=40,
            end=46,
            text="Bäcker",
            entity_type=EntityType.PROFESSION,
            confidence=1.0,
            detector="test",
        ),
    ]
    policy = {
        EntityType.PERSON_NAME: TransformationType.CONSISTENT_TAG,
        EntityType.DATE_OF_BIRTH: TransformationType.TYPE_MASK,
        EntityType.PROFESSION: TransformationType.REMOVE,
    }

    anonymized, applied, _ = apply_policy(text, spans, policy=policy, output_language=language)

    person_tag, birth_label, redacted = expected
    assert person_tag in anonymized
    assert birth_label in anonymized
    assert redacted in anonymized
    # The source itself is untouched, as always.
    assert "Max Mustermann" not in anonymized
    assert {entity.text for entity in applied} == {"Max Mustermann", "01.02.1980", "Bäcker"}


def test_placeholders_for_defaults_to_german():
    assert placeholders_for(None).redacted == "[GESCHWÄRZT]"
