import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AxiosResponse } from 'axios'
import { useFileDownload } from '@/composables/useFileDownload'

describe('useFileDownload', () => {
  beforeEach(() => {
    // jsdom implements neither createObjectURL nor revokeObjectURL.
    window.URL.createObjectURL = vi.fn(() => 'blob:fake')
    window.URL.revokeObjectURL = vi.fn()
  })

  it('clicks a download link with the suggested filename', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const { downloadBlob } = useFileDownload()

    downloadBlob('anonymisierter Text', 'anonymisiert.txt', 'text/plain;charset=utf-8')

    expect(click).toHaveBeenCalledOnce()
    const link = click.mock.instances[0] as HTMLAnchorElement
    expect(link.getAttribute('download')).toBe('anonymisiert.txt')
  })

  // The object URL keeps the document content alive in memory until revoked —
  // for a tool whose promise is "nothing is kept", leaking it is a real bug.
  it('revokes the object URL and removes the link again', () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const { downloadBlob } = useFileDownload()

    downloadBlob('inhalt', 'anonymisiert.txt')

    expect(window.URL.revokeObjectURL).toHaveBeenCalledWith('blob:fake')
    expect(document.querySelectorAll('a[download]')).toHaveLength(0)
  })

  it('downloads the blob returned by an API call', async () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const response = { data: new Blob(['%PDF-1.7']) } as AxiosResponse<Blob>
    const requestFn = vi.fn(() => Promise.resolve(response))
    const { downloadFromApi } = useFileDownload()

    await downloadFromApi(requestFn, 'anonymisiert.pdf')

    expect(requestFn).toHaveBeenCalledOnce()
    expect(window.URL.createObjectURL).toHaveBeenCalledOnce()
  })
})
