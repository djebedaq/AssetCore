// Real browser and APIs in a freshly generated QA database. No storage state,
// HAR, credentials or authentication headers are saved in artifacts.
import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url), modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath)
const expect = require(modulePath + '/test').expect.configure({ timeout: 60000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT
page.setDefaultTimeout(60000)
const errors = [], checks = [], screenshots = []
let assignments = 0
page.on('pageerror', error => errors.push(error.message))
page.on('dialog', dialog => void dialog.accept())
page.on('request', request => { if (/\/reference-pages\/\d+\/sources$/.test(new URL(request.url()).pathname) && request.method() === 'POST') assignments++ })
const button = name => page.getByRole('button', { name, exact: true })
const api = async path => { const response = await page.request.get(base + '/api/admin/catalog-builder' + path); expect(response.status()).toBe(200); return response.json() }
async function shot(name, width) {
  await page.setViewportSize({ width, height: 1000 })
  await page.evaluate(() => window.scrollTo(0, 0))
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await page.screenshot({ path: `${out}/${name}-${width}.png`, fullPage: true })
  screenshots.push(`${name}-${width}.png`)
}
async function createCatalog(name) {
  await button('Нов каталог').click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Име на каталога', { exact: true }).fill(name)
  await dialog.getByRole('combobox').selectOption({ label: 'QA UX04' })
  await dialog.getByLabel('Производител', { exact: true }).fill('QA')
  await dialog.getByLabel('Модел / справка', { exact: true }).fill('QA')
  await dialog.getByRole('button', { name: 'Продължи', exact: true }).click()
  await expect(page.locator('.catalog-navigation button')).toHaveCount(3)
}
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await page.locator('.sidebar-navigation').getByRole('button', { name: 'Каталожен конструктор', exact: true }).click()
  await createCatalog('Synthetic QA UX04 draft')
  for (const name of ['QA Chassis', 'QA Boom', 'QA Blasting']) {
    await page.locator('.reference-sidebar').getByLabel('Възел', { exact: true }).fill(name)
    await button('Добави възел').click()
    await expect(page.locator('.reference-sidebar').getByLabel('Възел', { exact: true })).toHaveValue('')
  }
  await expect(page.locator('.reference-link')).toHaveCount(3)
  checks.push('Three explicitly named user assemblies; no inferred assemblies; three primary areas')
  await page.locator('.reference-link').filter({ hasText: 'QA Chassis' }).click()
  await button('+ Добави схема').click()
  await page.getByLabel('Качи PDF', { exact: true }).setInputFiles(`${out}/synthetic.pdf`)
  await expect(page.locator('.pdf-page-picker article')).toHaveCount(6)
  for (const [number, role] of [[1, 0], [4, 0], [2, 1], [3, 1], [5, 1]]) {
    await page.locator('.pdf-page-picker article').nth(number - 1).getByRole('checkbox').nth(role).check()
  }
  await page.locator('.source-selection .reader-image img').evaluate(image => image.decode())
  await expect(page.locator('.pdf-page-picker img')).toHaveCount(6)
  for (const img of await page.locator('.pdf-page-picker img').all()) await img.evaluate(image => image.decode())
  await shot('pdf-selection', 1440)
  await button('Добави избраните страници (5)').click()
  await expect(page.locator('.source-selection')).toHaveCount(0)
  expect(assignments).toBe(1)
  const catalog = (await api('/catalogs'))[0], revision = (await api(`/catalogs/${catalog.id}/revisions`))[0]
  const assembly = (await api(`/revisions/${revision.id}/assemblies`)).find(row => row.name_bg === 'QA Chassis')
  const logical = (await api(`/assemblies/${assembly.id}/reference-pages`))[0]
  expect(logical.scheme_count).toBe(2); expect(logical.spare_list_count).toBe(3)
  expect(logical.sources.map(source => source.page_number)).toEqual([1, 4, 2, 3, 5])
  checks.push('Two physical scheme pages and three nonconsecutive lists assigned together to one logical group')
  await page.locator('.catalog-navigation').getByRole('button', { name: /Части и маркери/ }).click()
  await button('Разпознай частите').click()
  await expect(page.locator('.unified-parts tbody tr')).toHaveCount(19)
  await button('Избери валидните видими редове').click()
  await button('Потвърди избраните части').click()
  await expect.poll(async () => (await api(`/reference-pages/${logical.id}/parts`)).length).toBe(19)
  const quantity = page.locator('.part-comparison').getByLabel('Количество', { exact: true })
  await quantity.fill('3'); await quantity.press('Tab')
  await expect.poll(async () => Number((await api(`/reference-pages/${logical.id}/parts`))[0].quantity)).toBe(3)
  // Restore the actual synthetic source quantity before any source attestation.
  await quantity.fill('2'); await quantity.press('Tab')
  await expect.poll(async () => Number((await api(`/reference-pages/${logical.id}/parts`))[0].quantity)).toBe(2)
  await page.reload()
  await page.locator('.sidebar-navigation').getByRole('button', { name: 'Каталожен конструктор', exact: true }).click()
  await page.locator('.builder-list-item').filter({ hasText: 'Synthetic QA UX04 draft' }).getByRole('button', { name: 'Продължи черновата', exact: true }).click()
  await page.locator('.catalog-navigation').getByRole('button', { name: /Части и маркери/ }).click()
  await expect.poll(async () => Number(await page.locator('.part-comparison').getByLabel('Количество', { exact: true }).inputValue())).toBe(2)
  checks.push('Accepted rows edited directly, autosaved and resumed after reload; original source quantity restored before attestation')
  for (let index = 0; index < 3; index++) {
    await page.locator('.source-review-row').nth(index).getByRole('button', { name: 'Покажи оригинала', exact: true }).click()
    await page.locator('.source-attestation img').evaluate(image => image.decode())
    await button('Проверих спрямо оригинала').click()
    await expect(page.locator('.source-attestation')).toHaveCount(0)
  }
  checks.push('Actual PDF extraction of 19 rows; bulk acceptance; all three originals loaded and explicitly attested without written normal-review reasons')
  await page.locator('.part-comparison .reader-image img').evaluate(image => image.decode())
  for (const width of [1440, 768, 390]) await shot('parts-reviewed', width)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.locator('.catalog-navigation').getByRole('button', { name: /Каталог и PDF/ }).click()
  const source = logical.sources.find(row => row.page_number === 2)
  await page.getByRole('button', { name: 'Премахни страница 2: Списъци с резервни части', exact: true }).click()
  const deletion = page.getByRole('dialog')
  await expect(deletion).toContainText('Части: 7')
  await shot('source-dependency-preview', 1440)
  await deletion.getByRole('button', { name: 'Изтрий', exact: true }).click()
  await expect.poll(async () => (await api(`/reference-pages/${logical.id}/parts`)).length).toBe(12)
  const current = (await api(`/assemblies/${assembly.id}/reference-pages`))[0]
  expect(current.sources.some(row => row.id === source.id)).toBe(false)
  checks.push('One dependency confirmation removed a processed physical list, its seven owned parts and temporary OCR data')
  await page.locator('.catalog-navigation').getByRole('button', { name: /Части и маркери/ }).click()
  await button('Изтрий всички части в тази група').click()
  await expect(page.getByRole('dialog')).toContainText('Части: 12')
  await page.getByRole('dialog').getByRole('button', { name: 'Изтрий', exact: true }).click()
  await expect.poll(async () => (await api(`/reference-pages/${logical.id}/parts`)).length).toBe(0)
  expect((await api(`/assemblies/${assembly.id}/reference-pages`))[0].sources.map(row => row.id)).toEqual(current.sources.map(row => row.id))
  checks.push('All remaining group parts deleted together with one confirmation; the logical group, diagrams and selected PDF sources remain')
  const catalogDeletion = await api(`/draft-deletion/catalog/${catalog.id}`)
  expect(catalogDeletion.counts.catalog_extraction_sources).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Изтрий каталога', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText(`Обработени източници: ${catalogDeletion.counts.catalog_extraction_sources}`)
  await page.getByRole('dialog').getByRole('button', { name: 'Изтрий', exact: true }).click()
  await expect.poll(async () => (await api('/catalogs')).length).toBe(0)
  checks.push('Whole unpublished catalog with remaining OCR/review data deleted; machine inventory remains')
  await createCatalog('Synthetic QA shared catalog A')
  await button('Затвори').click()
  await createCatalog('Synthetic QA shared catalog B')
  await page.goto(base + '/machines?category=QA_UX04_ONLY')
  await expect(page.locator('.machine-registry-table tbody tr')).toHaveCount(2)
  for (let index = 0; index < 2; index++) {
    await page.locator('.machine-registry-table tbody tr').nth(index).getByRole('button', { name: 'Свържи каталог', exact: true }).click()
    const dialog = page.getByRole('dialog')
    for (const name of ['Synthetic QA shared catalog A', 'Synthetic QA shared catalog B']) {
      await dialog.locator('article').filter({ hasText: name }).getByRole('button', { name: 'Свържи каталог', exact: true }).click()
    }
    await expect(dialog.getByRole('button', { name: 'Премахни връзката с каталога', exact: true })).toHaveCount(2)
    await shot(`machine-${index + 1}-whole-catalog-links`, index ? 390 : 1440)
    await dialog.getByRole('button', { name: 'Затвори', exact: true }).click()
    await page.setViewportSize({ width: 1440, height: 1000 })
  }
  const catalogs = await api('/catalogs')
  expect(catalogs.map(row => row.bound_asset_count)).toEqual([2, 2])
  await page.locator('.machine-registry-table tbody tr').first().getByRole('button', { name: 'Свържи каталог', exact: true }).click()
  await page.getByRole('dialog').locator('article').filter({ hasText: 'Synthetic QA shared catalog A' }).getByRole('button', { name: 'Премахни връзката с каталога', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Премахни връзката с каталога', exact: true })).toHaveCount(1)
  checks.push('Both machines link both complete catalogs; unpublished links are labeled prepared; unlink removes only the selected active relationship')
  expect(errors).toEqual([])
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ passed: true, checks, screenshots, actions: {
    physical_pages: 5, before_assignment_requests: 5, after_assignment_requests: assignments,
    before_primary_areas: 6, after_primary_areas: 3, normal_review_written_reasons: 0,
    draft_source_delete_confirmations: 1, whole_catalog_link_selections: 1,
  } }, null, 2))
  console.log(`UX04 browser: ${checks.length} acceptance checks passed; ${screenshots.length} screenshots`)
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true })
  throw error
} finally { await context.close(); await browser.close() }
