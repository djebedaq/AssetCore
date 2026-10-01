/** Test transport for the actual multipart/XHR upload API, without a network. */
export class UploadTestTransport {
  status = 0
  responseText = ''
  withCredentials = false
  upload: { onprogress?: (event: { lengthComputable: boolean; loaded: number; total: number }) => void } = {}
  onload?: () => void
  onerror?: () => void
  private path = ''
  private headers = new Headers()
  open(_method: string, path: string) { this.path = path }
  setRequestHeader(key: string, value: string) { this.headers.set(key, value) }
  send(body: FormData) {
    this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 })
    void fetch(this.path, { method: 'POST', body, headers: this.headers }).then(async response => {
      this.status = response.status; this.responseText = await response.text()
      this.upload.onprogress?.({ lengthComputable: true, loaded: 2, total: 2 })
      this.onload?.()
    }).catch(() => this.onerror?.())
  }
}
