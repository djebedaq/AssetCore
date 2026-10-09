// Local disposable QA only. Mutations use the normal UI; API reads verify state.
import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
import { catalogMultipageExtraction } from './catalog_multipage_extraction.mjs'
const require = createRequire(import.meta.url)
const modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath)
const { expect: baseExpect } = require(modulePath + '/test')
const expect = baseExpect.configure({ timeout: 60000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT
const errors = [], checks = []
page.on('pageerror', error => errors.push(error.message))
page.on('dialog', dialog => { void dialog.accept() })
page.setDefaultTimeout(60000)
const button = name => page.getByRole('button', { name, exact: true })
const task = name => page.locator('.page-workflow nav').getByRole('button', { name, exact: true }).click()
const apiJson = async path => {
  const response = await page.request.get(base + '/api/admin/catalog-builder' + path)
  expect(response.status()).toBe(200)
  return response.json()
}
const reopen = async () => {
  await page.locator('.sidebar-navigation').getByRole('button', { name: 'Каталожен конструктор', exact: true }).click()
  await page.locator('.builder-list-item').filter({ hasText: 'Synthetic QA multipage' }).getByRole('button', { name: 'Продължи черновата', exact: true }).click()
  await task('Части')
}
let referenceId, revisionId
page.on('response', async response => {
  const match = response.url().match(/\/reference-pages\/(\d+)\/extract$/)
  if (match && response.status() === 200) referenceId = Number(match[1])
})
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await page.locator('.sidebar-navigation').waitFor()
  await button('Каталожен конструктор').click()
  await catalogMultipageExtraction({ page, expect, pdfPath: out + '/synthetic.pdf', screenshotPath: out + '/01-extracted.png',
    beforeConfirm: async () => {
      await page.getByRole('textbox', { name: 'Номер на част 1', exact: true }).first().fill('QA-HUMAN-CORRECTED')
      await expect(page.getByRole('button', { name: 'Потвърди избраните части', exact: true })).toBeEnabled()
      await page.reload(); await reopen()
      await expect(page.getByRole('textbox', { name: 'Номер на част 1', exact: true }).first()).toHaveValue('QA-HUMAN-CORRECTED')
      checks.push('Draft human correction survives refresh before confirmation')
      // Finish the review against the actual synthetic original before approval.
      await page.getByRole('textbox', { name: 'Номер на част 1', exact: true }).first().fill('QA-1')
      await expect(page.getByRole('button', { name: 'Потвърди избраните части', exact: true })).toBeEnabled()
    } })
  const references = await apiJson('/catalogs')
  const catalog = references.find(item => item.name_bg === 'Synthetic QA multipage')
  revisionId = (await apiJson(`/catalogs/${catalog.id}/revisions`)).find(item => item.status === 'DRAFT').id
  const parts = await apiJson(`/reference-pages/${referenceId}/parts`)
  expect(parts).toHaveLength(10)
  expect(parts.map(part => [part.position, part.part_number, part.description, Number(part.quantity)])).toEqual(
    Array.from({ length: 10 }, (_, index) => [String(index + 1), `QA-${index + 1}`, 'QA component', 2]))
  const blocked = await apiJson(`/revisions/${revisionId}/publication-readiness`)
  expect(blocked.ready).toBe(false)
  expect(blocked.errors.filter(error => error.code === 'catalog_publication_source_review_required')).toHaveLength(2)
  checks.push('Both selected sources block publication before explicit human review')
  const panel = page.getByRole('region', { name: 'Проверка на всеки източник', exact: true })
  await expect(panel).toBeVisible()
  for (const index of [0, 1]) {
    await panel.getByRole('button', { name: 'Покажи оригинала', exact: true }).nth(index).click()
    await panel.locator('img').evaluate(image => image.decode())
    await panel.getByRole('textbox').fill('QA: Сравних всички позиции, номера, описания и количества с точния оригинал.')
    await panel.getByRole('button', { name: 'Потвърди проверения източник', exact: true }).click()
    await expect(panel.getByText('Проверен за текущите данни', { exact: false })).toHaveCount(index + 1)
  }
  await page.screenshot({ path: out + '/02-reviewed.png', fullPage: true })
  await page.reload(); await reopen()
  await expect(panel.getByText('Проверен за текущите данни', { exact: false })).toHaveCount(2)
  checks.push('Original inspection and source decisions survive refresh')
  await button('Изход').click()
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await reopen()
  await expect(panel.getByText('Проверен за текущите данни', { exact: false })).toHaveCount(2)
  expect(await apiJson(`/reference-pages/${referenceId}/parts`)).toHaveLength(10)
  checks.push('Saved parts and source decisions survive logout and a fresh login')
  for (const viewport of [{ width: 768, height: 1024 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    const reviewBox = await panel.boundingBox()
    expect(reviewBox.width).toBeLessThanOrEqual(viewport.width)
    await panel.getByRole('button', { name: 'Покажи оригинала', exact: true }).first().click()
    await panel.locator('img').evaluate(image => image.decode())
    expect((await panel.locator('img').boundingBox()).width).toBeLessThanOrEqual(viewport.width)
    await page.screenshot({ path: `${out}/03-review-${viewport.width}.png`, fullPage: true })
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  checks.push('Source review and authorized original remain usable at tablet/mobile widths')
  await task('Маркиране')
  await page.locator('.builder-scheme-canvas img').evaluate(image => image.decode())
  await button('Цяла страница').click()
  for (let index = 0; index < 10; index++) {
    await page.locator('.builder-scheme-details select').last().selectOption(String(index + 1))
    await button('Точка').click()
    const canvas = page.locator('.builder-scheme-canvas'), box = await canvas.boundingBox()
    await canvas.click({ position: { x: box.width * (80 + index % 5 * 140) / 850, y: box.height * (145 + Math.floor(index / 5) * 140) / 650 } })
    await expect(page.locator('.builder-hotspot-list button')).toHaveCount(index + 1)
    await expect(button('Точка')).toBeEnabled()
  }
  await button('Към страницата').click()
  await page.locator('.catalog-navigation').getByRole('button', { name: 'Публикуване', exact: true }).click()
  await expect(button('Публикувай каталог')).toBeEnabled()
  await button('Публикувай каталог').click()
  await expect(page.getByText('Каталогът е публикуван.', { exact: true })).toBeVisible()
  checks.push('Ten visible synthetic callouts verified; reviewed complete catalog publishes through UI')
  expect(errors).toEqual([])
  await writeFile(out + '/results.json', JSON.stringify({ checks, pageErrors: errors, productionAccess: false }, null, 2))
  console.log(JSON.stringify({ checks, pageErrors: errors }))
} catch (error) {
  await page.screenshot({ path: out + '/failure.png', fullPage: true }).catch(() => {})
  console.error(String(error.stack || error).replaceAll(process.env.QA_PASSWORD, '[redacted]'))
  process.exitCode = 1
} finally { await browser.close() }
