const BASE = '/api'

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

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${BASE}${path}`, { ...options, headers })
  if (response.status === 401) logout()
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: 'Възникна грешка' }))
    throw new Error(data.detail || 'Възникна грешка')
  }
  return response.json()
}
