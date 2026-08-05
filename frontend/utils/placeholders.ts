/**
 * The replacement placeholders a run writes into the document, per output
 * language — the frontend mirror of `PLACEHOLDERS` in
 * `backend/src/utils/policy.py`.
 *
 * The backend is what actually produces them; these are read by the policy
 * editor to show what a given setting will look like ("z. B. [ADRESSE]"). They
 * live in the message catalogs under `placeholders.*` so both halves can be
 * compared automatically — `backend/tests/unit/test_placeholders.py` fails if
 * they ever drift apart.
 *
 * Always ask for the placeholders of the OUTPUT language, which may differ
 * from the interface language.
 */
import { i18n } from '@/i18n'
import type { EntityType, OutputLanguage } from '@/types/anonymizer'

function inLocale(key: string, locale: OutputLanguage): string {
  return i18n.global.t(key, {}, { locale })
}

/** TYPE_MASK replacement of an entity type, e.g. "[ADRESSE]". */
export function typeMaskPlaceholder(type: EntityType, locale: OutputLanguage): string {
  return inLocale(`placeholders.type_mask.${type}`, locale)
}

/** REMOVE replacement, e.g. "[GESCHWÄRZT]". */
export function redactedPlaceholder(locale: OutputLanguage): string {
  return inLocale('placeholders.redacted', locale)
}

/** CONSISTENT_TAG example for the first person, e.g. "[PERSON_1]". */
export function consistentTagExample(locale: OutputLanguage): string {
  return `[${inLocale('placeholders.person_tag', locale)}_1]`
}
