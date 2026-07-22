from backend.src.schemas.entities import (
    AppliedEntity,
    EntityType,
    SpanStatus,
    TransformationType,
    ValidationStatus,
)
from backend.src.utils.leakage import validate_output


def applied(
    start: int,
    end: int,
    text: str,
    etype: EntityType,
    status: SpanStatus,
    replacement: str | None,
) -> AppliedEntity:
    transformation = (
        TransformationType.PRESERVE
        if status == SpanStatus.PRESERVED
        else TransformationType.TYPE_MASK
    )
    return AppliedEntity(
        start=start,
        end=end,
        text=text,
        entity_type=etype,
        confidence=0.9,
        detector="test",
        transformation=transformation,
        replacement=replacement,
        status=status,
    )


async def test_residual_identifier_fails():
    # The name was supposedly redacted but still appears in the output.
    entities = [
        applied(9, 23, "Max Mustermann", EntityType.PERSON_NAME, SpanStatus.TAGGED, "[PERSON_1]")
    ]
    result = await validate_output("Patient: Max Mustermann wurde entlassen.", entities)
    assert result.status == ValidationStatus.FAIL
    assert any(w.category == "residual_identifier" for w in result.warnings)


async def test_clean_output_passes():
    entities = [
        applied(9, 23, "Max Mustermann", EntityType.PERSON_NAME, SpanStatus.TAGGED, "[PERSON_1]"),
        applied(38, 48, "10.03.2024", EntityType.OTHER_DATE, SpanStatus.PRESERVED, None),
    ]
    result = await validate_output("Patient: [PERSON_1] wurde entlassen am 10.03.2024.", entities)
    assert result.status == ValidationStatus.PASS
    assert result.warnings == []


async def test_missed_entity_found_by_rule_rerun():
    # No detector caught the phone number; the re-run should flag it.
    result = await validate_output("Rückfragen unter Tel.: 0351 458-0.", [])
    assert result.status == ValidationStatus.REVIEW_REQUIRED
    assert any(w.category == "revalidation_hit" for w in result.warnings)


async def test_labelled_field_with_content_warns():
    result = await validate_output("Name: Mustermann, weitere Angaben folgen.", [])
    assert result.status == ValidationStatus.REVIEW_REQUIRED
    assert any(w.category == "labelled_field" for w in result.warnings)


async def test_labelled_field_with_tag_is_fine():
    result = await validate_output("Patient: [PERSON_1] wurde vorstellig.", [])
    assert result.status == ValidationStatus.PASS


async def test_detector_warnings_prevent_pass():
    # An ungrounded LLM mention means possible unredacted PII: never PASS.
    result = await validate_output(
        "Unauffälliger Text.",
        [],
        detector_warnings=["The LLM reported a PERSON_NAME mention that could not be located."],
    )
    assert result.status == ValidationStatus.REVIEW_REQUIRED
    assert any(w.category == "detector" for w in result.warnings)
