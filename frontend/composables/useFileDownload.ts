/**
 * Composable for triggering browser file downloads from blob data
 * (copied from llmaixweb).
 *
 * Usage:
 *   const { downloadBlob } = useFileDownload()
 *   downloadBlob(text, 'anonymisiert.txt', 'text/plain;charset=utf-8')
 */
import type { AxiosResponse } from 'axios'

interface UseFileDownload {
  /**
   * Trigger a download from raw blob data.
   * @param data - The file data
   * @param filename - Suggested download filename
   * @param mimeType - Optional MIME type override
   */
  downloadBlob: (data: Blob | ArrayBuffer | string, filename: string, mimeType?: string) => void
  /**
   * Fetch a blob from an API call and trigger a download.
   * @param requestFn - Returns a promise resolving to an axios response with blob data
   * @param filename - Suggested download filename
   */
  downloadFromApi: (
    requestFn: () => Promise<AxiosResponse<Blob>>,
    filename: string,
  ) => Promise<void>
}

export function useFileDownload(): UseFileDownload {
  function downloadBlob(
    data: Blob | ArrayBuffer | string,
    filename: string,
    mimeType?: string,
  ): void {
    const blob = mimeType ? new Blob([data], { type: mimeType }) : new Blob([data])
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  }

  async function downloadFromApi(
    requestFn: () => Promise<AxiosResponse<Blob>>,
    filename: string,
  ): Promise<void> {
    const response = await requestFn()
    downloadBlob(response.data, filename)
  }

  return { downloadBlob, downloadFromApi }
}
