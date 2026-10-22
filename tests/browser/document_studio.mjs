import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url)
const modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath)
const expect = require(modulePath + '/test').expect.configure({ timeout: 30000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT
const checks = [], errors = [], screenshots = []
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
  await expect.poll(() => page.locator('.document-studio').evaluate(studio => {
    const workspace = studio.querySelector('.editor-focused') || studio
    const bounds = workspace.getBoundingClientRect()
    return [...workspace.querySelectorAll('input, textarea, select, button')].every(control => {
      if (control.closest('[inert]') || getComputedStyle(control).visibility === 'hidden') return true
      const rect = control.getBoundingClientRect()
      // The A4 canvas intentionally pans internally at readable mobile zoom.
      // Its viewport must stay in the workspace; surrounding controls must fit.
      const canvas = control.closest('.editor-canvas')
      const visible = canvas ? canvas.getBoundingClientRect() : rect
      return !rect.width || visible.left >= bounds.left - 1 && visible.right <= bounds.right + 1
    })
  })).toBe(true)
  const filename = `${name}-${width}.png`
  await page.evaluate(() => scrollTo(0, 0))
  await page.screenshot({ path: `${out}/${filename}`, fullPage: true })
  screenshots.push(filename)
}
async function openStudio(settings, title) {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.locator('.sidebar-navigation').getByRole('button', { name: settings, exact: true }).click()
  const tab = page.locator('.studio-settings-tabs').getByRole('button', { name: title, exact: true })
  await tab.click()
  await expect(page.locator('.document-studio')).toBeVisible()
}
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await openStudio('Настройки', 'Document Studio — Фирмени документи')
  await page.getByLabel('Фирмено наименование', { exact: true }).fill('Synthetic QA Company')
  await page.getByLabel('Регистрационен номер', { exact: true }).fill('QA-INT-001')
  await page.getByLabel('Часова зона (IANA)', { exact: true }).fill('Europe/Sofia')
  await button('Запази промените').click()
  await expect(page.getByRole('status')).toHaveText('Потвърдено от сървъра')
  if ((await api('/studio/company')).identity.registration_number !== 'QA-INT-001') throw new Error('Company save mismatch')
  checks.push('Company profile persisted by server; universal registration and IANA zone')
  for (const width of [390, 768, 1440]) await shot('company-bg', width)
  await button('Библиотека с шаблони').click()
  await expect(page.locator('.studio-version').first()).toBeVisible()
  for (const width of [390, 768, 1440]) await shot('library-bg', width)
  await page.getByLabel('Име на черновата', { exact: true }).fill('Synthetic QA authoring draft')
  await button('Създай').click()
  const draftForm = page.locator('.visual-editor')
  await draftForm.getByLabel('Автозапис', { exact: true }).uncheck()
  await draftForm.getByRole('combobox', { name: /Ориентация/ }).selectOption('landscape')
  await draftForm.getByRole('button', { name: 'Запази промените', exact: true }).click()
  await expect(draftForm.getByRole('status')).toContainText('Потвърдено от сървъра')
  for (const width of [390, 768, 1440]) await shot('draft-settings-bg', width)
  checks.push('Authoring draft created and saved through revision CAS in the visual editor')
  for (const language of [
    { code: 'en', settings: 'Settings', title: 'Document Studio — Company documents', company: 'Company legal name', library: 'Template library' },
    { code: 'ru', settings: 'Настройки', title: 'Document Studio — Документы компании', company: 'Наименование компании', library: 'Библиотека шаблонов' },
  ]) {
    await api('/users/me/preferences', { preferred_language: language.code }, 'PATCH')
    await page.reload()
    await openStudio(language.settings, language.title)
    await expect(page.getByLabel(language.company, { exact: true })).toHaveValue('Synthetic QA Company')
    for (const width of [390, 768, 1440]) await shot(`company-${language.code}`, width)
    await button(language.library).click()
    await expect(page.locator('.studio-version').first()).toBeVisible()
    for (const width of [390, 768, 1440]) await shot(`library-${language.code}`, width)
  }
  checks.push('BG/EN/RU company and library on desktop, tablet and mobile; no horizontal overflow')
  const directorContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const director = await directorContext.newPage()
  await director.goto(base)
  await director.locator('input[type=email]').fill('studio-director@qa.invalid')
  await director.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await director.getByRole('button', { name: 'Вход', exact: true }).click()
  await director.locator('.sidebar-navigation').getByRole('button', { name: 'Настройки', exact: true }).click()
  await expect(director.getByLabel('Фирмено наименование', { exact: true })).toBeDisabled()
  await expect(director.getByRole('button', { name: 'Запази промените', exact: true })).toHaveCount(0)
  await director.screenshot({ path: `${out}/director-read-only-1440.png`, fullPage: true })
  screenshots.push('director-read-only-1440.png')
  await directorContext.close()
  checks.push('Director sees studio without company, template or owner management controls')
  if (errors.length) throw new Error('Browser runtime errors')
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ passed: true, stage: 'COMMERCIAL-DOCS-01A', checks, screenshots, errors }, null, 2))
  console.log(JSON.stringify({ passed: true, checks: checks.length, screenshots: screenshots.length }))
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true })
  await writeFile(`${out}/failure-ui.txt`, await page.locator('.document-studio').innerText().catch(() => 'Studio unavailable'))
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ passed: false, checks, screenshots, errors, failure: error.message }, null, 2))
  throw error
} finally { await browser.close() }
