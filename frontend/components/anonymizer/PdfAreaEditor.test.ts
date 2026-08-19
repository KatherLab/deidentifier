import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import PdfAreaEditor from '@/components/anonymizer/PdfAreaEditor.vue'
import { i18n } from '@/i18n'
import { anonymizeApi } from '@/services/anonymizeApi'
import { useSessionStore } from '@/stores/session'
import type { AnonymizeResponse } from '@/types/anonymizer'

// The editor is mounted against a finished result the spec sets itself; a real
// stream must never race those assignments.
vi.mock('@/services/anonymizeStream', () => ({
  anonymizeFileStream: vi.fn(() => new Promise(() => {})),
  anonymizeTextStream: vi.fn(() => new Promise(() => {})),
}))

const ORIGINAL_IMAGE = 'data:image/png;base64,original'
const REDACTED_IMAGE = 'data:image/png;base64,redacted'

function pageResponse(image: string, imageBoxes = 0) {
  return {
    data: {
      pages: [
        {
          page: 1,
          width: 595,
          height: 842,
          image,
          image_boxes: Array.from({ length: imageBoxes }, () => ({
            x0: 0,
            y0: 0,
            x1: 100,
            y1: 100,
          })),
        },
      ],
      truncated: false,
    },
  } as never
}

/**
 * A finished single-document batch with a redacted-PDF preview, as after a
 * PDF run. `sourceType` decides which drawing surface the editor must pick.
 */
function documentWithPreview(sourceType: 'pdf' | 'pdf-ocr') {
  const session = useSessionStore()
  session.submitFiles([new File(['%PDF-original'], 'befund.pdf', { type: 'application/pdf' })])
  const doc = session.documents[0]!
  doc.result = {
    request_id: 'req-1',
    source_type: sourceType,
    entities: [],
  } as unknown as AnonymizeResponse
  doc.pdfPreviewBlob = new Blob(['%PDF-redacted'], { type: 'application/pdf' })
  return session
}

/** Renders originals or the redacted preview depending on what is uploaded. */
function mockRenderer() {
  return vi.spyOn(anonymizeApi, 'renderPdfPages').mockImplementation((file: File) => {
    const redacted = file.name === 'redacted.pdf'
    return Promise.resolve(
      pageResponse(redacted ? REDACTED_IMAGE : ORIGINAL_IMAGE, redacted ? 0 : 2),
    )
  })
}

function mountEditor() {
  return mount(PdfAreaEditor, { global: { plugins: [i18n] } })
}

describe('area editor drawing surface', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    i18n.global.locale.value = 'de'
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('opens a native PDF on the redacted pages, and switches to the originals', async () => {
    const session = documentWithPreview('pdf')
    const render = mockRenderer()

    const wrapper = mountEditor()
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()

    // The redactions are what the reviewer is adding to, so they are the
    // default background — no click needed to see them.
    expect(render.mock.calls.map((call) => call[0]!.name).sort()).toEqual([
      'befund.pdf',
      'redacted.pdf',
    ])
    expect(wrapper.get('img').attributes('src')).toBe(REDACTED_IMAGE)
    expect(wrapper.get('img').attributes('alt')).toBe('Seite 1 (geschwärzt)')

    // The originals stay one click away — that is what covering a signature
    // or a letterhead needs.
    await wrapper.get('button[aria-pressed]').trigger('click')
    await flushPromises()

    expect(wrapper.get('img').attributes('src')).toBe(ORIGINAL_IMAGE)
    expect(wrapper.get('img').attributes('alt')).toBe('Seite 1')
    session.reset()
  })

  it('draws on the reconstruction for a scanned PDF, never on the scan', async () => {
    const session = documentWithPreview('pdf-ocr')
    const render = mockRenderer()

    const wrapper = mountEditor()
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()

    // The scan is a different page geometry than the reconstruction the areas
    // are applied to, so it is never rendered — let alone drawn on.
    expect(render.mock.calls.map((call) => call[0]!.name)).toEqual(['redacted.pdf'])
    expect(wrapper.get('img').attributes('src')).toBe(REDACTED_IMAGE)
    expect(wrapper.get('img').attributes('alt')).toBe('Seite 1 (rekonstruiert, geschwärzt)')

    // Nothing to switch and nothing to suggest: no toggle, and no image boxes
    // (which for a scan would be one whole-page box per page).
    expect(wrapper.find('button[aria-pressed]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Alle Bilder schwärzen')
    session.reset()
  })

  it('refuses to fall back to the scan when the reconstruction is missing', async () => {
    const session = documentWithPreview('pdf-ocr')
    const doc = session.documents[0]!
    doc.pdfPreviewBlob = null
    doc.pdfPreviewError = 'Der geschwärzte PDF-Export ist fehlgeschlagen.'
    const render = mockRenderer()

    const wrapper = mountEditor()
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()

    expect(render).not.toHaveBeenCalled()
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('Der geschwärzte PDF-Export ist fehlgeschlagen.')
    session.reset()
  })
})
