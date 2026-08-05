import { beforeAll, describe, expect, it } from 'vitest'
import { loadLocaleMessages } from '@/composables/useLocale'
import {
  DEFAULT_POLICY,
  POLICY_OPTIONS,
  policyDeviations,
  policyOptionLabel,
  transformationHint,
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
  beforeAll(async () => {
    await Promise.all([
      loadLocaleMessages('en'),
      loadLocaleMessages('fr'),
      loadLocaleMessages('es'),
    ])
  })

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
      expect(POLICY_OPTIONS[type], type).toContain(DEFAULT_POLICY[type])
    }
  })

  // A missing catalog entry would render the raw key, so both must translate.
  it('labels and explains every offered transformation', () => {
    for (const [type, options] of Object.entries(POLICY_OPTIONS)) {
      for (const option of options) {
        expect(policyOptionLabel(option, 'de'), option).not.toContain('policy.')
        expect(transformationHint(option, type as EntityType, 'de'), option).not.toContain(
          'policy.',
        )
      }
    }
  })

  // The hint has to show what THIS row will actually write into the document,
  // in the language chosen for the output — not in the interface language.
  // The editor preloads the chosen language's catalog (setOutputLanguage);
  // without it, vue-i18n would fall back to the German placeholders.
  it('illustrates each transformation with the placeholder of the output language', () => {
    expect(transformationHint('TYPE_MASK', 'ADDRESS', 'de')).toContain('[ADRESSE]')
    expect(transformationHint('TYPE_MASK', 'ADDRESS', 'en')).toContain('[ADDRESS]')
    expect(transformationHint('CONSISTENT_TAG', 'PERSON_NAME', 'fr')).toContain('[PERSONNE_1]')
    expect(transformationHint('REMOVE', 'PHONE', 'es')).toContain('[OCULTADO]')
    expect(policyOptionLabel('REMOVE', 'de')).toContain('[GESCHWÄRZT]')
  })
})
