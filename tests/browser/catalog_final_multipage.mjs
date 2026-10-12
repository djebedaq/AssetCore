// Current six-step UI; real synthetic PDF/API. Only a client disconnect is injected.
import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url), modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath)
const expect = require(modulePath + '/test').expect.configure({ timeout: 60000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } })
const base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT, cases = [], errors = []
page.setDefaultTimeout(60000)
page.on('pageerror', error => errors.push(error.message))
const button = name => page.getByRole('button', { name, exact: true })
const task = name => page.locator('.catalog-navigation').getByRole('button', { name }).click()
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click(); await page.locator('.sidebar-navigation').waitFor()
  for (const count of [1, 4, 7]) {
    const extracted = []
    let referenceId, requests = 0, disconnected = false
    const observe = async response => {
      const match = response.url().match(/\/reference-pages\/(\d+)\/extract$/)
      if (match && response.status() === 200) { referenceId = Number(match[1]); extracted.push(await response.json()) }
    }
    page.on('response', observe)
    await page.route('**/reference-pages/*/extract', async route => {
      requests++
      if (count === 7 && requests === 4) { disconnected = true; await route.abort('connectionreset') }
      else await route.continue()
    })
    await page.goto(base)
    await page.locator('.sidebar-navigation').getByRole('button', { name: 'Каталожен конструктор', exact: true }).click()
    await button('Нов каталог').click()
    const dialog = page.getByRole('dialog'), title = `Synthetic QA ${count} lists`
    await dialog.getByLabel('Име на каталога', { exact: true }).fill(title)
    await dialog.getByRole('combobox').selectOption({ label: 'Водоструйни машини с високо налягане' })
    await dialog.getByRole('button', { name: 'Продължи', exact: true }).click()
    await page.locator('.reference-sidebar').getByLabel('Референция', { exact: true }).fill('Synthetic N-page assembly')
    await button('Добави референция').click()
    await expect(page.locator('.reference-sidebar').getByLabel('Референция', { exact: true })).toHaveValue('')
    await task(/PDF страници/); await button('+ Добави схема').click()
    await page.getByLabel('Качи PDF', { exact: true }).setInputFiles(out + '/synthetic.pdf')
    const jump = async number => {
      await page.locator('.reader-toolbar input').fill(String(number)); await page.locator('.reader-toolbar input').press('Enter')
      await page.getByRole('img', { name: `PDF страница ${number}`, exact: true }).evaluate(image => image.decode())
    }
    await jump(1); await button('Добави тази страница като схема').click()
    await expect(page.getByText('Страница 1 е добавена: Схема', { exact: true })).toBeVisible()
    await page.locator('.source-selection').getByRole('button', { name: 'Затвори', exact: true }).click()
    await button('+ Добави списък с части').click()
    for (let number = 2; number <= count + 1; number++) {
      await jump(number); await button('Добави тази страница като списък с части').click()
      await expect(page.getByText(`Страница ${number} е добавена: Списъци с резервни части`, { exact: true })).toBeVisible()
    }
    await page.locator('.source-selection').getByRole('button', { name: 'Затвори', exact: true }).click()
    await button('Продължи').click(); await button('Разпознай частите').click()
    await expect(button('Разпознай частите')).toBeEnabled({ timeout: 180000 })
    await expect.poll(() => extracted.length).toBe(count - (disconnected ? 1 : 0))
    await task(/Проверка на части/)
    await expect(page.locator('.guided-parts tbody tr')).toHaveCount(5 * extracted.length)
    if (disconnected) {
      // Refresh must retain successes and make the single unstarted source resumable.
      await page.reload()
      await page.locator('.sidebar-navigation').getByRole('button', { name: 'Каталожен конструктор', exact: true }).click()
      await page.locator('.builder-list-item').filter({ hasText: title }).getByRole('button', { name: 'Продължи черновата', exact: true }).click()
      await task(/Проверка на части/)
      await expect(page.locator('.guided-parts tbody tr')).toHaveCount(30)
      await task(/Разпознаване/)
      const missing = page.getByLabel('Списъци с резервни части', { exact: true }).locator(':scope > div').filter({ hasText: 'PDF страница 5' })
      await missing.getByRole('button', { name: 'Грешка — опитайте отново', exact: true }).click()
      await expect.poll(() => extracted.length).toBe(7)
      expect(extracted.map(item => item.source.page_number)).toEqual([2, 3, 4, 6, 7, 8, 5])
      await task(/Проверка на части/)
    }
    await expect(page.locator('.guided-parts tbody tr')).toHaveCount(count * 5)
    expect(new Set(extracted.flatMap(item => item.rows.map(row => row.candidate_id))).size).toBe(count * 5)
    const cookies = await page.context().cookies(base)
    const csrf = cookies.find(cookie => cookie.name === 'assetcore_csrf')?.value
    const response = await page.request.post(base + `/api/admin/catalog-builder/reference-pages/${referenceId}/review-session`, { headers: { 'X-CSRF-Token': csrf } })
    expect(response.status()).toBe(200)
    const ledger = await response.json()
    expect(ledger.sources).toHaveLength(count)
    expect(ledger.sources.every(source => source.review_state !== 'VERIFIED' && source.attempts.length === 1)).toBe(true)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    cases.push({ selectedLists: count, candidates: count * 5, sources: count, attemptsPerSource: 1, clientDisconnect: disconnected, retriedOnlyMissingPage: disconnected, automaticallyVerified: 0 })
    await page.screenshot({ path: out + `/lists-${count}-1920.png`, fullPage: true })
    await page.unroute('**/reference-pages/*/extract'); page.off('response', observe)
  }
  expect(errors).toEqual([])
  await writeFile(out + '/results.json', JSON.stringify({ passed: true, cases, pageErrors: errors, syntheticOnly: true, productionAccess: false }, null, 2))
  console.log(JSON.stringify({ cases, pageErrors: errors }))
} catch (error) {
  await page.screenshot({ path: out + '/failure.png', fullPage: true }).catch(() => {})
  console.error(String(error.stack || error).replaceAll(process.env.QA_PASSWORD, '[redacted]')); process.exitCode = 1
} finally { await browser.close() }
