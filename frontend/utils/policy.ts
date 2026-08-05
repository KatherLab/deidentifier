/**
 * Frontend mirror of the backend's DEFAULT_POLICY (backend/src/utils/policy.py)
 * plus the transformation choices the policy editor offers per entity type.
 *
 * The session store holds the editable policy (memory only — never persisted).
 * Requests only carry the DEVIATIONS from these defaults as the request-level
 * `policy` field; omitted types keep their backend default.
 *
 * Option labels and hints live in the message catalogs (`policy.options.*`,
 * `policy.hints.*`); only the transformation values belong here.
 */
import { t } from '@/i18n'
import {
  consistentTagExample,
  redactedPlaceholder,
  typeMaskPlaceholder,
} from '@/utils/placeholders'
import type { EntityType, OutputLanguage, PolicyMap, TransformationType } from '@/types/anonymizer'

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

/** Catalog key of the dropdown label for each transformation. */
const OPTION_LABEL_KEYS: Record<TransformationType, string> = {
  TYPE_MASK: 'policy.options.mask',
  GENERALIZE: 'policy.options.generalize_year',
  PRESERVE: 'policy.options.preserve',
  REMOVE: 'policy.options.remove',
  CONSISTENT_TAG: 'policy.options.consistent_tag',
}

/**
 * The placeholder a transformation would write for one entity type, in the
 * OUTPUT language of the next run — the example shown in the policy editor.
 * `undefined` for transformations that produce no placeholder.
 */
function placeholderExample(
  transformation: TransformationType,
  type: EntityType,
  outputLanguage: OutputLanguage,
): string | undefined {
  switch (transformation) {
    case 'TYPE_MASK':
      return typeMaskPlaceholder(type, outputLanguage)
    case 'CONSISTENT_TAG':
      return consistentTagExample(outputLanguage)
    case 'REMOVE':
      return redactedPlaceholder(outputLanguage)
    default:
      return undefined
  }
}

/** Dropdown label of a transformation ("Schwärzen", "Entfernen [GESCHWÄRZT]", …). */
export function policyOptionLabel(
  transformation: TransformationType,
  outputLanguage: OutputLanguage,
): string {
  return t(OPTION_LABEL_KEYS[transformation], {
    example: redactedPlaceholder(outputLanguage),
  })
}

/**
 * Explanation of a transformation with a concrete example, shown in the policy
 * editor under the select for the CURRENTLY chosen value. The example is the
 * placeholder this very row would produce, in the run's output language.
 */
export function transformationHint(
  transformation: TransformationType,
  type: EntityType,
  outputLanguage: OutputLanguage,
): string {
  return t(`policy.hints.${transformation}`, {
    example: placeholderExample(transformation, type, outputLanguage) ?? '',
  })
}

/** Dates can be generalized to the year instead of fully masked. */
const DATE_OPTIONS: TransformationType[] = ['TYPE_MASK', 'GENERALIZE', 'PRESERVE']

/** Generic PII: mask with the type label, remove entirely, or preserve. */
const GENERIC_OPTIONS: TransformationType[] = ['TYPE_MASK', 'REMOVE', 'PRESERVE']

/** Allowed transformations per entity type (policy editor dropdowns). */
export const POLICY_OPTIONS: Record<EntityType, TransformationType[]> = {
  PERSON_NAME: ['CONSISTENT_TAG', 'TYPE_MASK', 'PRESERVE'],
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
