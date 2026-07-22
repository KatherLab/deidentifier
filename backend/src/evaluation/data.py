"""Ground-truth loading for the evaluation harness.

Two input formats:

1. JSONL — one document per line:
   {"document_id": "...", "text": "...",
    "entities": [{"start": 0, "end": 3, "entity_type": "PERSON_NAME",
                  "text": "optional, validated when present"}]}

2. INCEpTION UIMA-CAS JSON (the LLMAIx annotation export format): the document
   text lives in the `uima.cas.Sofa` feature structure (`sofaString`) and each
   entity is a `custom.Span` with `begin`/`end`/`label`. Parsed with plain
   json — no cassis dependency. Directories and .zip archives of CAS files are
   supported (macOS `__MACOSX`/`._*` junk is skipped).

Labels are mapped onto the canonical EntityType taxonomy via a configurable
label map; unknown labels map to OTHER_PII with a warning.
"""

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..schemas.entities import EntityType


@dataclass(frozen=True)
class GroundTruthEntity:
    start: int
    end: int
    label: str  # raw label from the annotation source
    entity_type: EntityType


@dataclass
class GroundTruthDocument:
    document_id: str
    text: str
    entities: list[GroundTruthEntity]
    warnings: list[str] = field(default_factory=list)


# LLMAIx annotation labels plus identity mappings for our own taxonomy.
DEFAULT_LABEL_MAP: dict[str, EntityType] = {
    "patientname": EntityType.PERSON_NAME,
    "firstname": EntityType.PERSON_NAME,
    "lastname": EntityType.PERSON_NAME,
    "name": EntityType.PERSON_NAME,
    "patientgender": EntityType.OTHER_PII,
    "sex": EntityType.OTHER_PII,
    "patientid": EntityType.ID_NUMBER,
    "age": EntityType.AGE,
    "dateofbirth": EntityType.DATE_OF_BIRTH,
    **{t.value.lower(): t for t in EntityType},
}


def map_label(raw: str, label_map: dict[str, EntityType], warnings: list[str]) -> EntityType:
    mapped = label_map.get(raw.strip().lower())
    if mapped is None:
        warnings.append(f"Unknown annotation label '{raw}' mapped to OTHER_PII.")
        return EntityType.OTHER_PII
    return mapped


def load_dataset(
    path: Path, label_map: dict[str, EntityType] | None = None
) -> list[GroundTruthDocument]:
    label_map = label_map or DEFAULT_LABEL_MAP
    if path.is_dir():
        documents: list[GroundTruthDocument] = []
        for child in sorted(path.iterdir()):
            if _is_junk(child.name):
                continue
            if child.suffix.lower() in {".json", ".jsonl"}:
                documents.extend(load_dataset(child, label_map))
        return documents
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return _load_jsonl(path.read_text(encoding="utf-8"), label_map)
    if suffix == ".zip":
        return _load_zip(path, label_map)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [_parse_json_document(payload, path.stem, label_map)]
    raise ValueError(
        f"Unsupported ground-truth input: {path.name} (use .jsonl, .json, .zip or a directory)"
    )


def _is_junk(name: str) -> bool:
    return name.startswith("._") or name.startswith(".") or "__MACOSX" in name


def _load_jsonl(content: str, label_map: dict[str, EntityType]) -> list[GroundTruthDocument]:
    documents = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        documents.append(_parse_json_document(payload, f"line-{line_number}", label_map))
    return documents


def _load_zip(path: Path, label_map: dict[str, EntityType]) -> list[GroundTruthDocument]:
    documents = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            base = name.rsplit("/", 1)[-1]
            if _is_junk(name) or _is_junk(base) or not base.lower().endswith(".json"):
                continue
            payload = json.loads(io.TextIOWrapper(archive.open(name), encoding="utf-8").read())
            documents.append(_parse_json_document(payload, Path(base).stem, label_map))
    return documents


def _parse_json_document(
    payload: dict, fallback_id: str, label_map: dict[str, EntityType]
) -> GroundTruthDocument:
    if "%FEATURE_STRUCTURES" in payload:
        return _parse_cas(payload, fallback_id, label_map)
    return _parse_simple(payload, fallback_id, label_map)


def _parse_simple(
    payload: dict, fallback_id: str, label_map: dict[str, EntityType]
) -> GroundTruthDocument:
    text = payload.get("text")
    if not isinstance(text, str) or not text:
        raise ValueError(f"Document '{fallback_id}': missing 'text'")
    warnings: list[str] = []
    entities: list[GroundTruthEntity] = []
    for raw in payload.get("entities", []):
        start, end = int(raw["start"]), int(raw["end"])
        if not (0 <= start < end <= len(text)):
            raise ValueError(f"Document '{fallback_id}': invalid span {start}:{end}")
        expected = raw.get("text")
        if expected is not None and text[start:end] != expected:
            raise ValueError(
                f"Document '{fallback_id}': span {start}:{end} does not match its 'text' field"
            )
        label = str(raw.get("entity_type") or raw.get("label") or "")
        entities.append(
            GroundTruthEntity(
                start=start,
                end=end,
                label=label,
                entity_type=map_label(label, label_map, warnings),
            )
        )
    return GroundTruthDocument(
        document_id=str(payload.get("document_id") or fallback_id),
        text=text,
        entities=entities,
        warnings=warnings,
    )


def _parse_cas(
    payload: dict, fallback_id: str, label_map: dict[str, EntityType]
) -> GroundTruthDocument:
    structures = payload.get("%FEATURE_STRUCTURES", [])
    text: str | None = None
    for fs in structures:
        if fs.get("%TYPE") == "uima.cas.Sofa" and isinstance(fs.get("sofaString"), str):
            text = fs["sofaString"]
            break
    if text is None:
        raise ValueError(f"CAS document '{fallback_id}': no Sofa string found")

    warnings: list[str] = []
    entities: list[GroundTruthEntity] = []
    for fs in structures:
        if fs.get("%TYPE") != "custom.Span":
            continue
        label = fs.get("label")
        if label is None:
            continue
        start, end = int(fs.get("begin", 0)), int(fs.get("end", 0))
        if not (0 <= start < end <= len(text)):
            warnings.append(f"Skipped invalid CAS span {start}:{end} ('{label}').")
            continue
        entities.append(
            GroundTruthEntity(
                start=start,
                end=end,
                label=str(label),
                entity_type=map_label(str(label), label_map, warnings),
            )
        )
    return GroundTruthDocument(
        document_id=fallback_id, text=text, entities=entities, warnings=warnings
    )


def load_label_map(path: Path) -> dict[str, EntityType]:
    """Load a custom label map ({"annotation label": "ENTITY_TYPE"}) and merge
    it over the defaults."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    custom = {str(key).strip().lower(): EntityType(str(value)) for key, value in payload.items()}
    return {**DEFAULT_LABEL_MAP, **custom}
