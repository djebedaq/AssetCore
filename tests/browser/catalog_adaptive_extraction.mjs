// Real OEM input stays on this computer. Independent control is read only AFTER
// the normal UI extraction; no control values are sent to the server/extractor.
import { createRequire } from 'node:module'
import { readFile, writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url)
const modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath)
const expect = require(modulePath + '/test').expect.configure({ timeout: 60000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT
page.setDefaultTimeout(60000)
const errors = [], extracted = [], checks = []
page.on('pageerror', error => errors.push(error.message))
page.on('dialog', dialog => { void dialog.accept() })
let referenceId
page.on('response', async response => {
  const match = response.url().match(/\/reference-pages\/(\d+)\/extract$/)
  if (match && response.status() === 200) { referenceId = Number(match[1]); extracted.push(await response.json()) }
})
const button = name => page.getByRole('button', { name, exact: true })
const api = async path => {
  const response = await page.request.get(base + '/api/admin/catalog-builder' + path)
  expect(response.status()).toBe(200)
  return response.json()
}
const reopen = async () => {
  await page.locator('.sidebar-navigation').getByRole('button', { name: 'Каталожен конструктор', exact: true }).click()
  await page.locator('.builder-list-item').filter({ hasText: 'QA — D13 adaptive extraction' }).getByRole('button', { name: 'Продължи черновата', exact: true }).click()
  await page.locator('.page-workflow nav').getByRole('button', { name: 'Части', exact: true }).click()
}
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await page.locator('.sidebar-navigation').waitFor()
  await button('Каталожен конструктор').click()
  await button('Нов каталог').click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Име на каталога', { exact: true }).fill('QA — D13 adaptive extraction')
  await dialog.getByRole('combobox').selectOption({ label: 'Водоструйни машини с високо налягане' })
  await dialog.getByRole('button', { name: 'Продължи', exact: true }).click()
  await page.getByLabel('Референция', { exact: true }).fill('TCD13A.01 Chassis Assembly-2')
  await button('Добави референция').click()
  await expect(page.getByLabel('Референция', { exact: true })).toHaveValue('')
  await button('Добави страница').click()
  const jump = async number => {
    await page.locator('.reader-toolbar input').fill(String(number))
    await page.locator('.reader-toolbar input').press('Enter')
    const image = page.getByRole('img', { name: `PDF страница ${number}`, exact: true })
    await expect(image).toBeVisible(); await image.evaluate(image => image.decode())
  }
  await button('+ Добави схема').click()
  await page.getByLabel('Качи PDF', { exact: true }).setInputFiles(process.env.QA_PDF)
  await jump(12); await button('Добави тази страница като схема').click()
  await expect(page.getByText('Страница 12 е добавена: Схема', { exact: true })).toBeVisible()
  await page.locator('.source-selection').getByRole('button', { name: 'Затвори', exact: true }).click()
  await button('+ Добави списък с части').click()
  for (const number of [13, 15]) {
    await jump(number); await button('Добави тази страница като списък с части').click()
    await expect(page.getByText(`Страница ${number} е добавена: Списъци с резервни части`, { exact: true })).toBeVisible()
  }
  await page.locator('.source-selection').getByRole('button', { name: 'Затвори', exact: true }).click()
  await page.locator('.page-workflow nav').getByRole('button', { name: 'Части', exact: true }).click()
  await page.locator('.guided-parts').getByRole('button', { name: 'Извлечи резервните части', exact: true }).click()
  await expect(page.locator('.guided-parts tbody tr')).toHaveCount(30, { timeout: 120000 })
  await expect.poll(() => extracted.length).toBe(2)
  // Independent comparator starts only now.
  const expected = JSON.parse(await readFile(process.env.QA_EXPECTED, 'utf8'))
  const fields = row => [row.position, row.part_number, row.description, Number(row.quantity)]
  for (const preview of extracted) {
    const wanted = expected.parts.filter(row => row.pdf_page === preview.source.page_number)
    expect(preview.source.sha256).toBe(expected.pdf_sha256)
    expect(preview.rows.map(row => fields(row.payload))).toEqual(wanted.map(fields))
    expect(preview.rows.every(row => row.provenance.sha256 === expected.pdf_sha256 && row.provenance.physical_page === preview.source.page_number)).toBe(true)
  }
  checks.push('Single UI action: page 13 exact 20/20, page 15 exact 10/10; all four fields and SHA/page provenance')
  const number = page.getByRole('textbox', { name: 'Номер на част 1', exact: true }).first()
  const original = await number.inputValue()
  await number.fill('QA-HUMAN-DRAFT')
  await expect(button('Потвърди избраните части')).toBeEnabled()
  await page.reload(); await reopen()
  await expect(page.getByRole('textbox', { name: 'Номер на част 1', exact: true }).first()).toHaveValue('QA-HUMAN-DRAFT')
  await page.getByRole('textbox', { name: 'Номер на част 1', exact: true }).first().fill(original)
  await expect(button('Потвърди избраните части')).toBeEnabled()
  checks.push('Human draft correction survives refresh; restored to inspected original before confirmation')
  for (const row of expected.parts) await page.getByRole('checkbox', { name: `Позиция ${row.position}`, exact: true }).check()
  await button('Потвърди избраните части').click()
  await expect(button('Потвърди избраните части')).toBeDisabled()
  await expect.poll(async () => (await api(`/reference-pages/${referenceId}/parts`)).length).toBe(30)
  const catalog = (await api('/catalogs')).find(item => item.name_bg === 'QA — D13 adaptive extraction')
  const revision = (await api(`/catalogs/${catalog.id}/revisions`)).find(item => item.status === 'DRAFT')
  let readiness = await api(`/revisions/${revision.id}/publication-readiness`)
  expect(readiness.ready).toBe(false)
  expect(readiness.errors.filter(e => e.code === 'catalog_publication_source_review_required')).toHaveLength(2)
  checks.push('Thirty confirmed parts remain blocked until both original sources receive explicit human review')
  await page.locator('.guided-parts > .actions').getByRole('button', { name: 'Затвори', exact: true }).click()
  await page.locator('.guided-parts').getByRole('button', { name: 'Извлечи резервните части', exact: true }).click()
  await expect.poll(() => extracted.length, { timeout: 120000 }).toBe(4)
  await expect(page.locator('.guided-parts tbody tr')).toHaveCount(30)
  expect(extracted.slice(2).flatMap(p => p.rows.map(r => r.candidate_id))).toEqual(extracted.slice(0, 2).flatMap(p => p.rows.map(r => r.candidate_id)))
  expect(await api(`/reference-pages/${referenceId}/parts`)).toHaveLength(30)
  checks.push('Re-extraction keeps all candidate identities and creates no duplicate parts')
  const panel = page.getByRole('region', { name: 'Проверка на всеки източник', exact: true })
  for (const index of [0, 1]) {
    await panel.getByRole('button', { name: 'Покажи оригинала', exact: true }).nth(index).click()
    await panel.locator('img').evaluate(image => image.decode())
    await panel.getByRole('textbox').fill('QA: Сравнени всички позиции, оригинални номера, описания и количества с точния PDF.')
    await panel.getByRole('button', { name: 'Потвърди проверения източник', exact: true }).click()
    await expect(panel.getByText('Проверен за текущите данни', { exact: false })).toHaveCount(index + 1)
  }
  await page.reload(); await reopen()
  await expect(panel.getByText('Проверен за текущите данни', { exact: false })).toHaveCount(2)
  readiness = await api(`/revisions/${revision.id}/publication-readiness`)
  expect(readiness.ready).toBe(false)
  expect(readiness.errors.filter(e => e.code === 'catalog_publication_source_review_required')).toHaveLength(0)
  checks.push('Source decisions survive refresh; publication still blocked by unverified hotspot work (48/38 untouched)')
  expect(errors).toEqual([])
  await writeFile(out + '/results.json', JSON.stringify({ checks, pageErrors: errors, productionAccess: false }, null, 2))
  console.log(JSON.stringify({ checks, pageErrors: errors }))
} catch (error) {
  await page.screenshot({ path: out + '/failure.png', fullPage: true }).catch(() => {})
  console.error(String(error.stack || error).replaceAll(process.env.QA_PASSWORD, '[redacted]'))
  process.exitCode = 1
} finally { await browser.close() }
