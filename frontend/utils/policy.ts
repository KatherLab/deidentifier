/**
 * Frontend mirror of the backend's DEFAULT_POLICY (backend/src/utils/policy.py)
 * plus the transformation choices the policy editor offers per entity type.
 *
 * The session store holds the editable policy (memory only — never persisted).
 * Requests only carry the DEVIATIONS from these defaults as the request-level
 * `policy` field; omitted types keep their backend default.
 */
import type { EntityType, PolicyMap, TransformationType } from '@/types/anonymizer'

/** Must mirror backend DEFAULT_POLICY exactly (recall-first defaults). */
export const DEFAULT_POLICY: Record<EntityType, TransformationType> = {
  PERSON_NAME: 'CONSISTENT_TAG',
  DATE_OF_BIRTH: 'TYPE_MASK',
  OTHER_DATE: 'PRESERVE',
  AGE: 'TYPE_MASK',
  ADDRESS: 'TYPE_MASK',
  PHONE: 'TYPE_MASK',
  EMAIL: 'TYPE_MASK',
  URL: 'TYPE_MASK',
  ID_NUMBER: 'TYPE_MASK',
  ORGANIZATION: 'TYPE_MASK',
  PROFESSION: 'TYPE_MASK',
  OTHER_PII: 'TYPE_MASK',
}

export interface PolicyOption {
  value: TransformationType
  label: string
}

/** Dates can be generalized to the year instead of fully masked. */
const DATE_OPTIONS: PolicyOption[] = [
  { value: 'TYPE_MASK', label: 'Schwärzen' },
  { value: 'GENERALIZE', label: 'Nur Jahr' },
  { value: 'PRESERVE', label: 'Beibehalten' },
]

/** Generic PII: mask with the type label, remove entirely, or preserve. */
const GENERIC_OPTIONS: PolicyOption[] = [
  { value: 'TYPE_MASK', label: 'Schwärzen' },
  { value: 'REMOVE', label: 'Entfernen [GESCHWÄRZT]' },
  { value: 'PRESERVE', label: 'Beibehalten' },
]

/**
 * Explanation of each transformation with a concrete example, shown in the
 * policy editor under the select for the CURRENTLY chosen value.
 */
export const TRANSFORMATION_HINTS: Record<TransformationType, string> = {
  TYPE_MASK: 'Wird durch einen Platzhalter ersetzt, z. B. [ADRESSE]',
  CONSISTENT_TAG: 'Gleiche Person erhält im ganzen Dokument dieselbe Nummer, z. B. [PERSON_1]',
  GENERALIZE: 'Nur das Jahr bleibt sichtbar, z. B. 01.02.1980 → 1980',
  PRESERVE: 'Bleibt unverändert sichtbar (reduziert den Schutz)',
  REMOVE: 'Wird durch [GESCHWÄRZT] ersetzt',
}

/** Allowed transformations per entity type (policy editor dropdowns). */
export const POLICY_OPTIONS: Record<EntityType, PolicyOption[]> = {
  PERSON_NAME: [
    { value: 'CONSISTENT_TAG', label: 'Konsistente Tags' },
    { value: 'TYPE_MASK', label: 'Schwärzen' },
    { value: 'PRESERVE', label: 'Beibehalten' },
  ],
  DATE_OF_BIRTH: DATE_OPTIONS,
  OTHER_DATE: DATE_OPTIONS,
  AGE: GENERIC_OPTIONS,
  ADDRESS: GENERIC_OPTIONS,
  PHONE: GENERIC_OPTIONS,
  EMAIL: GENERIC_OPTIONS,
  URL: GENERIC_OPTIONS,
  ID_NUMBER: GENERIC_OPTIONS,
  ORGANIZATION: GENERIC_OPTIONS,
  PROFESSION: GENERIC_OPTIONS,
  OTHER_PII: GENERIC_OPTIONS,
}

/** The entries of `policy` that deviate from the defaults, or null if none. */
export function policyDeviations(policy: Record<EntityType, TransformationType>): PolicyMap | null {
  const deviations: PolicyMap = {}
  for (const type of Object.keys(DEFAULT_POLICY) as EntityType[]) {
    if (policy[type] !== DEFAULT_POLICY[type]) deviations[type] = policy[type]
  }
  return Object.keys(deviations).length > 0 ? deviations : null
}
