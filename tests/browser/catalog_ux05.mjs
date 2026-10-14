// Real browser, generated PDF and disposable DB; no auth state in artifacts.
import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url), modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath)
const expect = require(modulePath + '/test').expect.configure({ timeout: 60000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT
page.setDefaultTimeout(60000)
const checks = [], screenshots = [], cases = [], errors = []
page.on('pageerror', error => errors.push(error.message))
page.on('dialog', dialog => void dialog.accept())
const button = name => page.getByRole('button', { name, exact: true })
async function request(path, data) {
  const csrf = (await context.cookies()).find(cookie => cookie.name === 'assetcore_csrf')?.value
  const response = data === undefined ? await page.request.get(base + '/api' + path)
    : await page.request.post(base + '/api' + path, { data, headers: { 'X-CSRF-Token': csrf || '' } })
  if (!response.ok()) {
    const failure = await response.json()
    throw new Error(`QA API ${response.status()}: ${failure.detail?.code || 'request failed'}`)
  }
  return response.json()
}
const api = (path, data) => request('/admin/catalog-builder' + path, data)
async function shot(name, width) {
  await page.setViewportSize({ width, height: 1000 })
  await page.evaluate(() => window.scrollTo(0, 0))
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await page.screenshot({ path: `${out}/${name}-${width}.png`, fullPage: true })
  screenshots.push(`${name}-${width}.png`)
}
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await page.locator('.sidebar-navigation').getByRole('button', { name: 'Каталожен конструктор', exact: true }).click()
  for (const coverage of [59, 45, 0]) {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await button('Нов каталог').click()
    const dialog = page.getByRole('dialog')
    const name = `Synthetic QA UX05 ${coverage} of 59`
    await dialog.getByLabel('Име на каталога', { exact: true }).fill(name)
    await dialog.getByRole('combobox').selectOption({ label: 'QA UX04' })
    await dialog.getByLabel('Производител', { exact: true }).fill('QA')
    await dialog.getByLabel('Модел / справка', { exact: true }).fill('QA')
    await dialog.getByRole('button', { name: 'Продължи', exact: true }).click()
    await page.locator('.reference-sidebar').getByLabel('Възел', { exact: true }).fill('Synthetic QA assembly')
    await button('Добави възел').click()
    await page.locator('.reference-link').first().click()
    await button('+ Добави схема').click()
    await page.getByLabel('Качи PDF', { exact: true }).setInputFiles(`${out}/synthetic.pdf`)
    await expect(page.locator('.pdf-page-picker article')).toHaveCount(7)
    for (let number = 1; number <= 7; number++) {
      await page.locator('.pdf-page-picker article').nth(number - 1).getByRole('checkbox').nth(number <= 3 ? 0 : 1).check()
    }
    await button('Добави избраните страници (7)').click()
    await expect(page.locator('.source-selection')).toHaveCount(0)
    const catalog = (await api('/catalogs')).find(row => row.name_bg === name)
    const revision = (await api(`/catalogs/${catalog.id}/revisions`))[0]
    const assembly = (await api(`/revisions/${revision.id}/assemblies`))[0]
    const logical = (await api(`/assemblies/${assembly.id}/reference-pages`))[0]
    await page.locator('.catalog-navigation').getByRole('button', { name: /Части и маркери/ }).click()
    await button('Разпознай частите').click()
    await expect(page.locator('.unified-parts tbody tr')).toHaveCount(59)
    await page.locator('.part-comparison .reader-image img').evaluate(image => image.decode())
    await button('Избери валидните видими редове').click()
    await button('Потвърди избраните части').click()
    await expect.poll(async () => (await api(`/reference-pages/${logical.id}/parts`)).length).toBe(59)
    // One optional attestation; the remaining three are never attested.
    await page.locator('.source-review-row').first().getByRole('button', { name: 'Покажи оригинала', exact: true }).click()
    await page.locator('.source-attestation img').evaluate(image => image.decode())
    await button('Проверих спрямо оригинала').click()
    await expect(page.locator('.source-attestation')).toHaveCount(0)
    const schemes = logical.sources.filter(source => source.role === 'EXPLODED_SCHEME')
    for (let position = 1; position <= coverage; position++) {
      const scheme = schemes[Math.floor((position - 1) / 20)]
      const marker = await api(`/visual-pages/${scheme.id}/hotspots`, { position: String(position),
        x: .09 + (position - 1) % 5 * .16, y: .16 + Math.floor((position - 1) % 20 / 5) * .15, width: .04, height: .04 })
      await api(`/hotspots/${marker.id}/verify`, { expected_version: marker.version })
    }
    await page.locator('.catalog-navigation').getByRole('button', { name: /Публикуване/ }).click()
    const result = await api(`/revisions/${revision.id}/publication-readiness`)
    expect(result.ready).toBe(true); expect(result.errors).toEqual([])
    expect(result.summary.reviewed_source_count).toBe(1)
    expect(result.warnings.filter(w => w.code === 'catalog_publication_source_review_required')).toHaveLength(3)
    expect(result.warnings.filter(w => w.code === 'catalog_publication_hotspot_coverage').reduce((sum, w) => sum + w.missing_positions, 0)).toBe(59 - coverage)
    await expect(button('Публикувай каталог')).toBeEnabled()
    for (const width of coverage === 45 ? [1440, 768, 390] : [1440]) await shot(`publication-${coverage}-59`, width)
    await button('Публикувай каталог').click()
    await expect.poll(async () => (await api(`/catalogs/${catalog.id}/revisions`))[0].status).toBe('PUBLISHED')
    const state = await api(`/revisions/${revision.id}/publication-readiness`)
    expect(state.summary.reviewed_source_count).toBe(1)
    const machine = (await request('/machines')).find(row => row.inventory_number === 'QA_UX04_1')
    await api(`/catalogs/${catalog.id}/assets/${machine.id}`, {})
    const parts = await request(`/catalog/v2/search?machine_id=${machine.id}&q=QA-UX05-059`)
    const part = parts.find(p => p.source_version === `CATALOG_BUILDER_R${revision.id}`)
    expect(part.verification_status).toBe('CONFIRMED_BUILDER_PUBLICATION')
    await request('/part-requests/multi', { machine_id: machine.id,
      lines: [{ part_id: part.id, description: 'Synthetic QA request without required marker', quantity: 1 }] })
    cases.push({ parts: 59, markers: coverage, source_attestations: '1/4', ready: result.ready,
      warnings: result.warnings, published: true, missing_part_searchable_and_requestable: coverage < 59 })
    checks.push(`${coverage}/59 markers: one bulk parts acceptance, 1/4 optional attestations, warnings allow UI publication and runtime request`)
    await button('Затвори').click()
  }
  expect(errors).toEqual([])
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ passed: true, synthetic_only: true, checks, screenshots, cases }, null, 2))
  console.log(`UX05 browser: ${checks.length} acceptance cases passed; ${screenshots.length} screenshots`)
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true })
  throw error
} finally { await context.close(); await browser.close() }
