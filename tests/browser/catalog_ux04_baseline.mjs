import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url), modulePath = process.env.PLAYWRIGHT_MODULE
const { chromium } = require(modulePath)
const expect = require(modulePath + '/test').expect.configure({ timeout: 60000 })
const browser = await chromium.launch({ headless: true, channel: 'msedge' })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT
page.setDefaultTimeout(60000)
let assignments = 0
page.on('request', request => { if (/\/reference-pages\/\d+\/sources$/.test(new URL(request.url()).pathname) && request.method() === 'POST') assignments++ })
const button = name => page.getByRole('button', { name, exact: true })
async function jump(number) {
  await page.locator('.reader-toolbar input').fill(String(number))
  await page.locator('.reader-toolbar input').press('Enter')
  await page.locator('.reader-image img').evaluate(image => image.decode())
}
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await page.locator('.sidebar-navigation').getByRole('button', { name: 'Каталожен конструктор', exact: true }).click()
  await button('Нов каталог').click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Име на каталога', { exact: true }).fill('Synthetic QA UX04 baseline')
  await dialog.getByRole('combobox').selectOption({ label: 'QA UX04' })
  await dialog.getByRole('button', { name: 'Продължи', exact: true }).click()
  await page.locator('.reference-sidebar').getByLabel('Референция', { exact: true }).fill('QA baseline user assembly')
  await button('Добави референция').click()
  await expect(page.locator('.reference-sidebar').getByLabel('Референция', { exact: true })).toHaveValue('')
  await page.locator('.catalog-navigation').getByRole('button', { name: /PDF страници/ }).click()
  await button('+ Добави схема').click()
  await page.getByLabel('Качи PDF', { exact: true }).setInputFiles(`${out}/synthetic.pdf`)
  await page.locator('.reader-image img').evaluate(image => image.decode())
  await button('Добави тази страница като схема').click()
  await jump(4); await button('Добави тази страница като схема').click()
  await button('+ Добави списък с части').click()
  for (const number of [2, 3, 5]) { await jump(number); await button('Добави тази страница като списък с части').click() }
  expect(assignments).toBe(5)
  expect(await page.locator('.catalog-navigation button').count()).toBe(6)
  await writeFile(`${out}/baseline-proof.json`, JSON.stringify({ passed: true,
    baseline_sha: 'ad5063bfd67e9a47d8fda52418ad502910f2c247', physical_pages: 5,
    assignment_requests: assignments, assignment_button_clicks: 5, primary_areas: 6,
    scope: 'ACTUAL_BROWSER_ON_ARCHIVED_ORIGIN_MAIN_WITH_NEW_DISPOSABLE_QA_DATABASE' }, null, 2))
  console.log('UX04 baseline browser: five individual assignment requests and six primary areas confirmed')
} catch (error) { await page.screenshot({ path: `${out}/baseline-failure.png`, fullPage: true }); throw error }
finally { await context.close(); await browser.close() }
