import { expect, it, vi } from 'vitest'
import source from '../../public/sw.js?raw'

function worker() {
  type FetchEvent = { request: Request; respondWith: (response: Promise<Response>) => void }
  const listeners = new Map<string, (event: FetchEvent) => void>()
  const stored = new Map<string, Response>()
  const key = (request: Request | string) => typeof request === 'string' ? request : request.url
  const cache = { addAll: vi.fn(), put: vi.fn(async (request: Request, response: Response) => { stored.set(key(request), response) }) }
  const fetch = vi.fn(async () => new Response('page chunk', { headers: { 'Content-Type': 'text/javascript' } }))
  // Run the committed worker against isolated browser APIs, not a copy of its logic.
  const evaluateWorker = new Function('self', 'caches', 'fetch', 'URL', source)
  evaluateWorker(
    { addEventListener: (name: string, callback: (event: FetchEvent) => void) => listeners.set(name, callback), skipWaiting: vi.fn(), clients: { claim: vi.fn() } },
    { open: async () => cache, match: async (request: Request | string) => stored.get(key(request)), keys: async () => [], delete: vi.fn() },
    fetch, URL,
  )
  function request(path: string, method = 'GET') {
    let response: Promise<Response> | undefined
    listeners.get('fetch')!({ request: new Request(`https://assetcore.example.invalid${path}`, { method }), respondWith: (value) => { response = value } })
    return response
  }
  return { request, fetch, cache, stored }
}

it('caches a lazy page chunk after an online visit and serves its exact bytes offline', async () => {
  const qa = worker()
  expect(await (await qa.request('/assets/Catalog-example.js'))!.text()).toBe('page chunk')
  qa.fetch.mockRejectedValueOnce(new Error('offline'))
  const cached = await qa.request('/assets/Catalog-example.js')
  expect(cached!.headers.get('Content-Type')).toBe('text/javascript')
  expect(await cached!.text()).toBe('page chunk')
  expect(qa.cache.put).toHaveBeenCalledTimes(1)
})

it('does not intercept authenticated API requests or mutating operations', () => {
  const qa = worker()
  expect(qa.request('/api/auth/me')).toBeUndefined()
  expect(qa.request('/api/documents/1/download')).toBeUndefined()
  expect(qa.request('/api/auth/login', 'POST')).toBeUndefined()
  expect(qa.request('/form', 'POST')).toBeUndefined()
  expect(qa.fetch).not.toHaveBeenCalled()
  expect(qa.cache.put).not.toHaveBeenCalled()
})

it('retains the cached PWA shell fallback for offline deep links', async () => {
  const qa = worker()
  qa.stored.set('/', new Response('<div id="root"></div>', { headers: { 'Content-Type': 'text/html' } }))
  qa.fetch.mockRejectedValueOnce(new Error('offline'))
  expect(await (await qa.request('/machine/3'))!.text()).toBe('<div id="root"></div>')
})
