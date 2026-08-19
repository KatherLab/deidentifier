import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSessionStore, type SessionDocument } from '@/stores/session'
import { applyLocale } from '@/composables/useLocale'
import { i18n, t } from '@/i18n'
import { anonymizeApi } from '@/services/anonymizeApi'
import { useToastStore } from '@/stores/toast'
import type { AnonymizeResponse, AnonymizedEntity } from '@/types/anonymizer'

// The streaming pipeline is not under test here: every spec below drives the
// store with results it sets itself, so a submit must never race a real (or
// failing) stream against those assignments.
vi.mock('@/services/anonymizeStream', () => ({
  anonymizeFileStream: vi.fn(() => new Promise(() => {})),
  anonymizeTextStream: vi.fn(() => new Promise(() => {})),
}))

describe('output language', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    await applyLocale('de', false)
  })

  it('follows the interface language until pinned', async () => {
    const session = useSessionStore()
    expect(session.outputLanguage).toBe('de')

    await applyLocale('en', false)
    expect(session.outputLanguage).toBe('en')
  })

  it('stays put once pinned, whatever the interface does', async () => {
    const session = useSessionStore()
    session.setOutputLanguage('fr')

    await applyLocale('en', false)
    expect(session.outputLanguage).toBe('fr')

    // Releasing the pin hands control back to the interface language.
    session.setOutputLanguage(null)
    expect(session.outputLanguage).toBe('en')
  })

  it('counts as a customized advanced setting only when it deviates', async () => {
    const session = useSessionStore()
    expect(session.advancedCustomized).toBe(false)

    // Pinning the language the UI already uses changes nothing about the run.
    session.setOutputLanguage('de')
    expect(session.advancedCustomized).toBe(false)

    session.setOutputLanguage('es')
    expect(session.advancedCustomized).toBe(true)
  })

  it('is cleared by the advanced-settings reset', () => {
    const session = useSessionStore()
    session.setOutputLanguage('es')

    session.resetAdvancedSettings()

    expect(session.outputLanguageOverride).toBeNull()
    expect(session.outputLanguage).toBe('de')
  })

  it('is captured per document at submit', () => {
    const session = useSessionStore()
    session.setOutputLanguage('fr')
    session.submitText('Ein Befund.')

    // The snapshot travels with the document: later UI/settings changes must
    // not rewrite the placeholders of a document that is already running.
    expect(session.documents.map((doc) => doc.outputLanguage)).toEqual(['fr'])
    session.setOutputLanguage('es')
    expect(session.documents[0]!.outputLanguage).toBe('fr')

    session.reset()
  })
})

describe('result lifetime', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-06T10:00:00Z'))
    i18n.global.locale.value = 'de' // the toast text is locale-dependent
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  /**
   * A batch whose documents already carry results, as after a finished run.
   * One `submitText`/`submitFiles` call per batch — a second submit would
   * replace the first batch rather than add to it.
   */
  function batchWithResults(
    session: ReturnType<typeof useSessionStore>,
    ids: string[],
  ): SessionDocument[] {
    session.submitFiles(ids.map((id) => new File(['Ein Befund.'], `${id}.txt`)))
    session.documents.forEach((doc, index) => {
      doc.result = {
        request_id: ids[index]!,
        lifetime: { expires_in_seconds: 30, can_extend: true },
      } as AnonymizeResponse
      doc.expiresAt = Date.now() + 30_000
      doc.canExtend = true
    })
    return session.documents
  }

  it('extends every document of the batch, not just the active one', async () => {
    const session = useSessionStore()
    batchWithResults(session, ['req-1', 'req-2'])
    const extend = vi.spyOn(anonymizeApi, 'extendResult').mockResolvedValue({
      data: { expires_in_seconds: 900, can_extend: true },
    } as never)

    await session.extendResults()

    expect(extend.mock.calls.map((call) => call[0]).sort()).toEqual(['req-1', 'req-2'])
    for (const doc of session.documents) {
      expect(doc.expiresAt).toBe(Date.now() + 900_000)
      expect(doc.canExtend).toBe(true)
      expect(doc.extending).toBe(false)
    }
    session.reset()
  })

  it('reports the ceiling instead of pretending the click worked', async () => {
    const session = useSessionStore()
    batchWithResults(session, ['req-1'])
    vi.spyOn(anonymizeApi, 'extendResult').mockResolvedValue({
      data: { expires_in_seconds: 120, can_extend: false },
    } as never)

    await session.extendResults()

    expect(session.documents[0]!.canExtend).toBe(false)
    expect(session.documents[0]!.expiresAt).toBe(Date.now() + 120_000)
    session.reset()
  })

  it('marks a document expired when the backend has already forgotten it', async () => {
    const session = useSessionStore()
    batchWithResults(session, ['req-1'])
    vi.spyOn(anonymizeApi, 'extendResult').mockRejectedValue(new Error('410'))

    await session.extendResults()

    expect(session.documents[0]!.expiresAt).toBe(Date.now())
    expect(session.documents[0]!.canExtend).toBe(false)
    session.reset()
  })

  it('does nothing when no document has a result yet', async () => {
    const session = useSessionStore()
    const extend = vi.spyOn(anonymizeApi, 'extendResult')

    await session.extendResults()

    expect(extend).not.toHaveBeenCalled()
  })
})

describe('batch-wide result lifetime', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-06T10:00:00Z'))
    i18n.global.locale.value = 'de' // the toast text is locale-dependent
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  function batch(session: ReturnType<typeof useSessionStore>, ids: string[]): SessionDocument[] {
    session.submitFiles(ids.map((id) => new File(['Ein Befund.'], `${id}.txt`)))
    session.documents.forEach((doc, index) => {
      doc.result = { request_id: ids[index]! } as AnonymizeResponse
      doc.expiresAt = Date.now() + 900_000
      doc.canExtend = true
    })
    return session.documents
  }

  it('reports nothing to count down before the first result', () => {
    const session = useSessionStore()

    expect(session.resultsExpireAt).toBeNull()
    expect(session.resultsCanExtend).toBe(false)
  })

  it('counts down to the FIRST document that expires', () => {
    const session = useSessionStore()
    const docs = batch(session, ['req-1', 'req-2'])
    docs[1]!.expiresAt = Date.now() + 120_000 // this one dies first

    expect(session.resultsExpireAt).toBe(Date.now() + 120_000)
    session.reset()
  })

  it('offers extending while any document still has headroom', () => {
    const session = useSessionStore()
    const docs = batch(session, ['req-1', 'req-2'])
    docs[0]!.canExtend = false

    expect(session.resultsCanExtend).toBe(true)

    docs[1]!.canExtend = false
    expect(session.resultsCanExtend).toBe(false)
    session.reset()
  })

  it('confirms a successful extension, so stepping away is safe', async () => {
    const session = useSessionStore()
    batch(session, ['req-1'])
    vi.spyOn(anonymizeApi, 'extendResult').mockResolvedValue({
      data: { expires_in_seconds: 900, can_extend: true },
    } as never)
    const toast = useToastStore()

    await session.extendResults()

    expect(toast.toasts.at(-1)).toMatchObject({ type: 'success' })
    expect(toast.toasts.at(-1)!.message).toContain('15 Min.')
    session.reset()
  })

  it('says so when the ceiling was reached instead of claiming success', async () => {
    const session = useSessionStore()
    batch(session, ['req-1'])
    vi.spyOn(anonymizeApi, 'extendResult').mockResolvedValue({
      data: { expires_in_seconds: 300, can_extend: false },
    } as never)
    const toast = useToastStore()

    await session.extendResults()

    expect(toast.toasts.at(-1)).toMatchObject({ type: 'info' })
    session.reset()
  })

  it('reports an extension that came too late', async () => {
    const session = useSessionStore()
    batch(session, ['req-1'])
    vi.spyOn(anonymizeApi, 'extendResult').mockRejectedValue(new Error('410'))
    const toast = useToastStore()

    await session.extendResults()

    expect(toast.toasts.at(-1)).toMatchObject({ type: 'error' })
    session.reset()
  })
})

// ---------------------------------------------------------------------------
// Multi-selection in the source review.
//
// The selection is stored as override KEYS (`start:end`), never as indices —
// a re-run reorders the entity array but never moves an offset. Every spec
// below leans on that: the selection has to survive the re-runs its own
// actions trigger.
// ---------------------------------------------------------------------------

const SOURCE = 'Frau Müller, Dr. Schmidt und Frau MÜLLER am 03.04.2024 in Klinik A.'

function entity(
  start: number,
  end: number,
  text: string,
  extra: Partial<AnonymizedEntity> = {},
): AnonymizedEntity {
  return {
    start,
    end,
    text,
    entity_type: 'PERSON_NAME',
    confidence: 0.9,
    detector: 'llm',
    transformation: 'CONSISTENT_TAG',
    replacement: '[PERSON_1]',
    status: 'TAGGED',
    metadata: {},
    ...extra,
  }
}

function response(entities: AnonymizedEntity[], requestId = 'req-1'): AnonymizeResponse {
  return {
    request_id: requestId,
    source_text: SOURCE,
    source_type: 'txt',
    entities,
    lifetime: { expires_in_seconds: 900, can_extend: true },
  } as AnonymizeResponse
}

/** A single-document batch already carrying a result with these entities. */
function documentWith(
  session: ReturnType<typeof useSessionStore>,
  entities: AnonymizedEntity[],
): SessionDocument {
  session.submitFiles([new File([SOURCE], 'befund.txt')])
  const doc = session.documents[0]!
  doc.result = response(entities)
  return doc
}

describe('entity selection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  const THREE = [entity(5, 11, 'Müller'), entity(17, 24, 'Schmidt'), entity(34, 40, 'MÜLLER')]

  it('selects exactly one entity on a plain click', () => {
    const session = useSessionStore()
    documentWith(session, THREE)

    session.selectEntity(1)

    expect(session.selectedEntityIndices).toEqual([1])
    expect(session.selectedEntity?.text).toBe('Schmidt')
    session.reset()
  })

  it('adds and removes single entities without disturbing the rest', () => {
    const session = useSessionStore()
    documentWith(session, THREE)

    session.selectEntity(0)
    session.toggleEntitySelection(2)
    expect(session.selectedEntityIndices).toEqual([0, 2])
    // Two selected: the single-entity detail panel steps aside for the bar.
    expect(session.selectedEntity).toBeNull()

    session.toggleEntitySelection(0)
    expect(session.selectedEntityIndices).toEqual([2])
    session.reset()
  })

  it('selects a whole range between the anchor and the click', () => {
    const session = useSessionStore()
    documentWith(session, THREE)

    session.selectEntity(0)
    session.selectEntityRange(2)

    expect(session.selectedEntityIndices).toEqual([0, 1, 2])
    session.reset()
  })

  it('ranges backwards just as well, and keeps the clicked end in focus', () => {
    const session = useSessionStore()
    documentWith(session, THREE)

    session.selectEntity(2)
    session.selectEntityRange(0)

    expect(session.selectedEntityIndices).toEqual([0, 1, 2])
    // The source view scrolls to where the reviewer clicked, not to the anchor.
    expect(session.selectedEntityIndex).toBe(0)
    session.reset()
  })

  it('treats a shift-click without an anchor as a plain click', () => {
    const session = useSessionStore()
    documentWith(session, THREE)

    session.selectEntityRange(1)

    expect(session.selectedEntityIndices).toEqual([1])
    session.reset()
  })

  it('selects every occurrence of a text, ignoring case and whitespace', () => {
    const session = useSessionStore()
    documentWith(session, [
      entity(5, 11, 'Müller'),
      entity(17, 24, 'Schmidt'),
      entity(34, 40, 'MÜLLER'),
      entity(50, 56, ' müller '),
    ])

    session.selectEntity(0)
    session.selectMatchingEntities(session.selectedEntity!)

    expect(session.selectedEntityIndices).toEqual([0, 2, 3])
    expect(session.countMatchingEntities({ text: 'müller' })).toBe(3)
    // The entity the reviewer came from stays the focus — no jumping away.
    expect(session.selectedEntityIndex).toBe(0)
    session.reset()
  })
})

describe('bulk actions on a selection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    i18n.global.locale.value = 'de'
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  /** Mock the cheap cached re-run; returns the spy for call assertions. */
  function mockRerun(entities: AnonymizedEntity[]) {
    return vi
      .spyOn(anonymizeApi, 'rerunWithOverrides')
      .mockResolvedValue({ data: response(entities, 'req-2') } as never)
  }

  it('redacts every preserved find in ONE re-run, leaving the others as they are', async () => {
    const session = useSessionStore()
    const entities = [
      // Preserved by policy — this is what "Schwärzen" is for.
      entity(43, 53, '03.04.2024', {
        entity_type: 'OTHER_DATE',
        transformation: 'PRESERVE',
        replacement: null,
        status: 'PRESERVED',
      }),
      // Already redacted with a consistent tag: forcing TYPE_MASK here would
      // silently flatten [PERSON_1] into [NAME].
      entity(5, 11, 'Müller'),
    ]
    const doc = documentWith(session, entities)
    const rerun = mockRerun(entities)

    session.selectEntity(0)
    session.toggleEntitySelection(1)
    const changed = await session.applySelectionAction('redact')

    expect(changed).toBe(1)
    expect(rerun).toHaveBeenCalledTimes(1)
    expect(rerun.mock.calls[0]![1]).toEqual([
      { start: 43, end: 53, text: '03.04.2024', transformation: 'TYPE_MASK' },
    ])
    expect(doc.overrides.has('5:11')).toBe(false)
    session.reset()
  })

  it('preserves several detected finds in one round trip', async () => {
    const session = useSessionStore()
    const entities = [entity(5, 11, 'Müller'), entity(17, 24, 'Schmidt')]
    documentWith(session, entities)
    const rerun = mockRerun(entities)

    session.selectEntity(0)
    session.toggleEntitySelection(1)
    const changed = await session.applySelectionAction('preserve')

    expect(changed).toBe(2)
    expect(rerun).toHaveBeenCalledTimes(1)
    expect(rerun.mock.calls[0]![1]).toEqual([
      { start: 5, end: 11, text: 'Müller', transformation: 'PRESERVE' },
      { start: 17, end: 24, text: 'Schmidt', transformation: 'PRESERVE' },
    ])
    session.reset()
  })

  it('releases a manual redaction by dropping its override, not by preserving it', async () => {
    const session = useSessionStore()
    const manual = entity(57, 65, 'Klinik A', {
      detector: 'user_manual',
      transformation: 'REMOVE',
      replacement: '[GESCHWÄRZT]',
      status: 'REDACTED',
      metadata: { user_manual: true },
    })
    const entities = [entity(5, 11, 'Müller'), manual]
    const doc = documentWith(session, entities)
    doc.overrides.set('57:65', {
      start: 57,
      end: 65,
      text: 'Klinik A',
      transformation: 'REMOVE',
    })
    const rerun = mockRerun([entity(5, 11, 'Müller')])

    session.selectEntity(1)
    const changed = await session.applySelectionAction('preserve')

    expect(changed).toBe(1)
    // A manual span has no detection behind it: the override is gone, and no
    // PRESERVE override took its place.
    expect(rerun.mock.calls[0]![1]).toEqual([])
    expect(doc.overrides.size).toBe(0)
    session.reset()
  })

  it('resets only the selected overrides and keeps the others', async () => {
    const session = useSessionStore()
    const entities = [entity(5, 11, 'Müller'), entity(17, 24, 'Schmidt')]
    const doc = documentWith(session, entities)
    doc.overrides.set('5:11', {
      start: 5,
      end: 11,
      text: 'Müller',
      transformation: 'PRESERVE',
    })
    doc.overrides.set('17:24', {
      start: 17,
      end: 24,
      text: 'Schmidt',
      transformation: 'PRESERVE',
    })
    mockRerun(entities)

    session.selectEntity(0)
    const changed = await session.applySelectionAction('reset')

    expect(changed).toBe(1)
    expect([...doc.overrides.keys()]).toEqual(['17:24'])
    session.reset()
  })

  it('sets one type on the whole selection and drops the transformation overrides', async () => {
    const session = useSessionStore()
    const entities = [entity(5, 11, 'Müller'), entity(17, 24, 'Schmidt')]
    const doc = documentWith(session, entities)
    doc.overrides.set('5:11', {
      start: 5,
      end: 11,
      text: 'Müller',
      transformation: 'PRESERVE',
    })
    const rerun = mockRerun(entities)

    session.selectEntity(0)
    session.toggleEntitySelection(1)
    const changed = await session.applySelectionType('ORGANIZATION')

    expect(changed).toBe(2)
    expect(rerun.mock.calls[0]![1]).toEqual([
      { start: 5, end: 11, text: 'Müller', entity_type: 'ORGANIZATION' },
      { start: 17, end: 24, text: 'Schmidt', entity_type: 'ORGANIZATION' },
    ])
    session.reset()
  })

  it('keeps the selection across the re-run it caused', async () => {
    const session = useSessionStore()
    const entities = [entity(5, 11, 'Müller'), entity(17, 24, 'Schmidt')]
    documentWith(session, entities)
    // The re-run returns the same finds, preserved — so "no, redact them
    // again" is one more click on the same selection.
    mockRerun(
      entities.map((each) => ({
        ...each,
        transformation: 'PRESERVE' as const,
        replacement: null,
        status: 'PRESERVED' as const,
      })),
    )

    session.selectEntity(0)
    session.toggleEntitySelection(1)
    await session.applySelectionAction('preserve')

    expect(session.selectedEntityIndices).toEqual([0, 1])
    session.reset()
  })

  it('sheds selected entities the re-run made disappear', async () => {
    const session = useSessionStore()
    const manual = entity(57, 65, 'Klinik A', {
      detector: 'user_manual',
      metadata: { user_manual: true },
    })
    const doc = documentWith(session, [entity(5, 11, 'Müller'), manual])
    doc.overrides.set('57:65', { start: 57, end: 65, text: 'Klinik A', transformation: 'REMOVE' })
    mockRerun([entity(5, 11, 'Müller')]) // the manual span is gone

    session.selectEntity(0)
    session.toggleEntitySelection(1)
    await session.applySelectionAction('preserve')

    expect(session.selectedEntityIndices).toEqual([0])
    session.reset()
  })

  it('rolls the whole batch back when the re-run fails', async () => {
    const session = useSessionStore()
    const entities = [entity(5, 11, 'Müller'), entity(17, 24, 'Schmidt')]
    const doc = documentWith(session, entities)
    vi.spyOn(anonymizeApi, 'rerunWithOverrides').mockRejectedValue(new Error('boom'))

    session.selectEntity(0)
    session.toggleEntitySelection(1)

    await expect(session.applySelectionAction('preserve')).rejects.toThrow()
    // Nothing half-applied: the map is back where it started.
    expect(doc.overrides.size).toBe(0)
    expect(doc.rerunning).toBe(false)
    session.reset()
  })

  it('does not re-run at all when the action would change nothing', async () => {
    const session = useSessionStore()
    const entities = [entity(5, 11, 'Müller'), entity(17, 24, 'Schmidt')]
    documentWith(session, entities)
    const rerun = mockRerun(entities)

    session.selectEntity(0)
    session.toggleEntitySelection(1)
    // Both are already redacted — "Schwärzen" has nothing left to do.
    const changed = await session.applySelectionAction('redact')

    expect(changed).toBe(0)
    expect(rerun).not.toHaveBeenCalled()
    session.reset()
  })
})

describe('redacted pages for the area editor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    i18n.global.locale.value = 'de'
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  /** A document whose redacted-PDF preview has already been generated. */
  function documentWithPreview(
    session: ReturnType<typeof useSessionStore>,
    blob: Blob,
  ): SessionDocument {
    const doc = documentWith(session, [])
    doc.pdfPreviewBlob = blob
    return doc
  }

  function pages(image: string) {
    return {
      data: {
        pages: [{ page: 1, width: 595, height: 842, image, image_boxes: [] }],
        truncated: false,
      },
    } as never
  }

  it('renders the preview the store already holds, once per preview', async () => {
    const session = useSessionStore()
    const blob = new Blob(['%PDF-redacted'], { type: 'application/pdf' })
    documentWithPreview(session, blob)
    const render = vi
      .spyOn(anonymizeApi, 'renderPdfPages')
      .mockResolvedValue(pages('data:image/png;base64,redacted'))

    await session.loadRedactedPdfPages()
    await session.loadRedactedPdfPages()

    // No entity search, no second render: the blackouts come from the bytes
    // the export already produced.
    expect(render).toHaveBeenCalledTimes(1)
    expect(render.mock.calls[0]![0]!.type).toBe('application/pdf')
    expect(session.pdfRedactedPages?.[0]?.image).toBe('data:image/png;base64,redacted')
    session.reset()
  })

  it('re-renders when a new preview supersedes the old one', async () => {
    const session = useSessionStore()
    const doc = documentWithPreview(session, new Blob(['%PDF-1'], { type: 'application/pdf' }))
    const render = vi
      .spyOn(anonymizeApi, 'renderPdfPages')
      .mockResolvedValue(pages('data:image/png;base64,first'))
    await session.loadRedactedPdfPages()

    // What a drawn area or an override does: a brand-new preview blob.
    doc.pdfPreviewBlob = new Blob(['%PDF-2'], { type: 'application/pdf' })
    render.mockResolvedValue(pages('data:image/png;base64,second'))
    await session.loadRedactedPdfPages()

    expect(render).toHaveBeenCalledTimes(2)
    expect(session.pdfRedactedPages?.[0]?.image).toBe('data:image/png;base64,second')
    session.reset()
  })

  it('does not upload a preview larger than the server accepts', async () => {
    const session = useSessionStore()
    session.status = { limits: { max_upload_mb: 20, max_text_chars: 100_000 } } as never
    // Size is all the store reads before deciding — no 21 MB blob needed.
    documentWithPreview(session, { size: 21 * 1024 * 1024, type: 'application/pdf' } as Blob)
    const render = vi.spyOn(anonymizeApi, 'renderPdfPages')

    await session.loadRedactedPdfPages()

    expect(render).not.toHaveBeenCalled()
    expect(session.pdfRedactedPages).toBeNull()
    expect(session.pdfRedactedPagesError).toBe(t('areas.redacted_too_large'))
    session.reset()
  })

  it('stays quiet when there is no redacted preview to render', async () => {
    const session = useSessionStore()
    documentWith(session, [])
    const render = vi.spyOn(anonymizeApi, 'renderPdfPages')

    await session.loadRedactedPdfPages()

    expect(render).not.toHaveBeenCalled()
    expect(session.pdfRedactedPagesError).toBeNull()
    session.reset()
  })
})
