import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url)
const modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath)
const expect = require(modulePath + '/test').expect.configure({ timeout: 30000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT
const checks = [], errors = []
page.setDefaultTimeout(30000)
page.on('pageerror', error => errors.push(error.name))
page.on('dialog', dialog => void dialog.accept())
const button = name => page.getByRole('button', { name, exact: true })
async function api(path, data, method = 'POST') {
  const csrf = (await context.cookies()).find(cookie => cookie.name === 'assetcore_csrf')?.value
  const response = await page.request.fetch(base + '/api' + path, { method: data === undefined ? 'GET' : method, ...(data === undefined ? {} : { data }), headers: { 'X-CSRF-Token': csrf || '' } })
  if (!response.ok()) throw new Error(`QA API status ${response.status()}`)
  return response.json()
}
async function shot(name, width) {
  await page.setViewportSize({ width, height: 1000 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await expect.poll(() => page.getByRole('dialog').evaluate(dialog => {
    const bounds = dialog.getBoundingClientRect()
    return dialog.scrollWidth <= dialog.clientWidth + 1 && [...dialog.querySelectorAll('input, textarea, select, button')].every(control => {
      const rect = control.getBoundingClientRect()
      return rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1 &&
        (control.tagName === 'BUTTON' || rect.width >= 80)
    })
  })).toBe(true)
  await page.screenshot({ path: `${out}/${name}-${width}.png`, fullPage: true })
}
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await page.locator('.sidebar-navigation').getByRole('button', { name: 'Каталог резервни части', exact: true }).click()
  await expect(button('Нова свободна заявка')).toBeEnabled()
  await button('Нова свободна заявка').click()
  let dialog = page.getByRole('dialog')
  await dialog.getByLabel('Отдел / звено', { exact: true }).fill('QA requests01')
  await dialog.getByLabel('Наименование на артикул', { exact: true }).fill('QA делим материал с дълго наименование '.repeat(5))
  await dialog.getByLabel('Мерна единица', { exact: true }).selectOption('l')
  await dialog.getByLabel('Количество', { exact: true }).fill('2,5')
  await dialog.getByRole('button', { name: 'Добави ред', exact: true }).click()
  await dialog.getByLabel('Наименование на артикул', { exact: true }).nth(1).fill('QA неделим ред')
  await dialog.getByLabel('Количество', { exact: true }).nth(1).fill('3')
  await dialog.getByRole('button', { name: 'Добави ред', exact: true }).click()
  await dialog.getByRole('button', { name: 'Премахни 3', exact: true }).click()
  for (const width of [390, 768, 1440]) await shot('free-form-bg', width)
  await dialog.getByRole('button', { name: 'Преглед на заявката', exact: true }).click()
  await expect(dialog.locator('iframe')).toHaveAttribute('src', /^blob:/)
  let request = (await api('/workspace/requests?request_kind=FREE_FORM')).items[0]
  if (request.machine_id !== null || request.official_number !== null || request.lines[0].exact_quantity !== '2.5') throw new Error('QA draft invariant')
  const identifier = request.id
  await dialog.getByRole('button', { name: 'Затвори', exact: true }).click()
  await page.locator('.sidebar-navigation').getByRole('button', { name: 'Заявени части', exact: true }).click()
  const card = page.locator('.request-card').filter({ hasText: 'QA requests01' })
  await expect(card).toContainText('Без официален номер')
  await card.getByRole('button', { name: 'Подай за одобрение', exact: true }).click()
  await card.getByRole('button', { name: 'Одобри', exact: true }).click()
  await expect(card).toContainText('KK1000')
  await expect.poll(async () => (await api('/workspace/requests?q=KK1000')).items[0]?.generation_status).toBe('READY')
  request = (await api('/workspace/requests?q=KK1000')).items[0]
  if (request.documents.length !== 2) throw new Error('QA archive invariant')
  await card.getByRole('button', { name: 'Отчети доставка', exact: true }).click()
  dialog = page.getByRole('dialog')
  await dialog.getByLabel('Получено количество', { exact: true }).first().fill('0,75')
  await dialog.getByRole('button', { name: 'Запази', exact: true }).click()
  await expect(card).toContainText('0,75 / 2,5')
  await card.getByRole('button', { name: 'Отмени заявката', exact: true }).click()
  dialog = page.getByRole('dialog')
  await dialog.getByLabel('Причина за отмяна', { exact: true }).fill('QA controlled cancellation')
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: 'Отмени заявката', exact: true }).click()
  request = (await api(`/workspace/requests?record_id=${identifier}`)).items[0]
  await expect.poll(async () => (await api(`/workspace/requests?record_id=${identifier}`)).items[0]?.status).toBe('CANCELLED')
  if (request.official_number !== 'KK1000') throw new Error('QA cancelled number changed')
  checks.push('BG UI: category-independent draft, add/remove rows, decimal comma, real preview, approval and two archived files, fractional delivery and confirmed cancellation')
  for (const language of [
    { code: 'en', catalog: 'Spare-parts catalog', create: 'New free-form request', description: 'Item description', quantity: 'Quantity', unit: 'Unit', close: 'Close' },
    { code: 'ru', catalog: 'Каталог запчастей', create: 'Новая свободная заявка', description: 'Наименование позиции', quantity: 'Количество', unit: 'Единица измерения', close: 'Закрыть' },
  ]) {
    await api('/users/me/preferences', { preferred_language: language.code }, 'PATCH')
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.reload()
    await page.locator('.sidebar-navigation').getByRole('button', { name: language.catalog, exact: true }).click()
    await button(language.create).click()
    dialog = page.getByRole('dialog')
    await expect(dialog.getByLabel(language.description, { exact: true })).toBeVisible()
    await expect(dialog.getByLabel(language.quantity, { exact: true })).toBeVisible()
    await expect(dialog.getByLabel(language.unit, { exact: true })).toBeVisible()
    for (const width of [390, 768, 1440]) await shot(`free-form-${language.code}`, width)
    await dialog.getByRole('button', { name: language.close, exact: true }).click()
    checks.push(`${language.code.toUpperCase()} form renders at 390, 768 and 1440 pixels without horizontal overflow`)
  }
  if (errors.length) throw new Error('QA browser runtime error')
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ checks, errors }, null, 2))
  console.log(`REQUESTS-01 browser checks passed: ${checks.length}`)
} finally {
  await browser.close()
}
