import { describe, expect, it } from 'vitest'
import {
  DEFAULT_POLICY,
  POLICY_OPTIONS,
  TRANSFORMATION_HINTS,
  policyDeviations,
} from '@/utils/policy'
import type { EntityType, TransformationType } from '@/types/anonymizer'

describe('policyDeviations', () => {
  it('returns null when the policy matches the defaults', () => {
    expect(policyDeviations({ ...DEFAULT_POLICY })).toBeNull()
  })

  it('returns only the entity types that deviate', () => {
    const policy = { ...DEFAULT_POLICY, OTHER_DATE: 'TYPE_MASK' as TransformationType }

    expect(policyDeviations(policy)).toEqual({ OTHER_DATE: 'TYPE_MASK' })
  })

  it('collects multiple deviations', () => {
    const policy = {
      ...DEFAULT_POLICY,
      DATE_OF_BIRTH: 'GENERALIZE' as TransformationType,
      ORGANIZATION: 'PRESERVE' as TransformationType,
    }

    expect(policyDeviations(policy)).toEqual({
      DATE_OF_BIRTH: 'GENERALIZE',
      ORGANIZATION: 'PRESERVE',
    })
  })
})

describe('policy defaults', () => {
  // The backend applies its own DEFAULT_POLICY to every type the request
  // omits, so a drifted frontend default would silently send no deviation and
  // display a transformation the backend never applied.
  it('mirrors the recall-first backend defaults', () => {
    expect(DEFAULT_POLICY.PERSON_NAME).toBe('CONSISTENT_TAG')
    expect(DEFAULT_POLICY.OTHER_DATE).toBe('PRESERVE')
    expect(DEFAULT_POLICY.DATE_OF_BIRTH).toBe('TYPE_MASK')
  })

  it('offers the current default as a selectable option for every type', () => {
    for (const type of Object.keys(DEFAULT_POLICY) as EntityType[]) {
      const values = POLICY_OPTIONS[type].map((option) => option.value)
      expect(values, type).toContain(DEFAULT_POLICY[type])
    }
  })

  it('has a hint for every offered transformation', () => {
    for (const options of Object.values(POLICY_OPTIONS)) {
      for (const option of options) {
        expect(TRANSFORMATION_HINTS[option.value], option.value).toBeTruthy()
      }
    }
  })
})
