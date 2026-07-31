import { getStoredLocale } from './locale'

const BASE = '/api'

export type StructuredApiError = {
  code?: string
  message?: string
  conflicts?: Array<Record<string, unknown>>
  [key: string]: unknown
}

export class ApiError extends Error {
  status: number
  code?: string
  data: StructuredApiError

  constructor(status: number, data: StructuredApiError) {
    super(data.message || data.code || 'request_failed')
    this.name = 'ApiError'
    this.status = status
    this.code = data.code
    this.data = data
  }
}

export function getToken() {
  return localStorage.getItem('assetcore_token')
}

export function setToken(token: string) {
  localStorage.setItem('assetcore_token', token)
}

export function logout() {
  localStorage.removeItem('assetcore_token')
  localStorage.removeItem('assetcore_user')
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  const payload = await response.json().catch(() => ({}))
  const detail = payload.detail
  if (typeof detail === 'string') {
    return new ApiError(response.status, { message: detail })
  }
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    return new ApiError(response.status, detail as StructuredApiError)
  }
  if (Array.isArray(detail)) {
    const firstMessage = detail.find(item => typeof item?.msg === 'string')?.msg
    return new ApiError(response.status, {
      code: 'validation_error',
      message: firstMessage || 'validation_error',
      validation: detail,
    })
  }
  return new ApiError(response.status, { code: 'request_failed' })
}

function authenticatedHeaders(options: RequestInit): Headers {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  headers.set('Accept-Language', getStoredLocale())
  return headers
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { ...options, headers: authenticatedHeaders(options) })
  if (response.status === 401) logout()
  if (!response.ok) throw await errorFromResponse(response)
  if (response.status === 204) return undefined as T
  return response.json()
}

function responseFilename(response: Response, fallback: string): string {
  const disposition = response.headers.get('Content-Disposition') || ''
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) return decodeURIComponent(encoded)
  return disposition.match(/filename="?([^";]+)"?/i)?.[1] || fallback
}

export async function downloadApiFile(path: string, fallbackName: string): Promise<void> {
  const response = await fetch(`${BASE}${path}`, { headers: authenticatedHeaders({}) })
  if (response.status === 401) logout()
  if (!response.ok) throw await errorFromResponse(response)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = responseFilename(response, fallbackName)
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
