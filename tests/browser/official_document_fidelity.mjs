import { createRequire } from 'node:module'
import { readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
const require = createRequire(import.meta.url), modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath), expect = require(modulePath + '/test').expect.configure({ timeout: 90000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } }), page = await context.newPage()
const base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT, checks = [], screenshots = [], errors = []
page.on('pageerror', e => errors.push(e.name)); page.on('dialog', d => void d.accept())
const button = (name, root = page) => root.getByRole('button', { name, exact: true })
async function api(path, data, method = 'POST', expected = 200) {
  const csrf = (await context.cookies()).find(c => c.name === 'assetcore_csrf')?.value
  const response = await page.request.fetch(base + '/api' + path, { method: data === undefined ? 'GET' : method, ...(data === undefined ? {} : { data }), headers: { 'X-CSRF-Token': csrf || '' } })
  if (response.status() !== expected) throw new Error(`QA API ${path}: ${response.status()}`)
  return response.json()
}
async function shot(name) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true }); screenshots.push(`${name}.png`)
}
const languages = [
  { code: 'bg', settings: 'Настройки', title: 'Document Studio — Фирмени документи', library: 'Библиотека с шаблони', source: 'Изтегли изходен DOCX', copy: 'Създай редактируемо Studio копие', preview: 'Провери и виж PDF', back: 'Към редактора', close: 'Затвори', variant: 'Вариант на заявката', save: 'Запази промените', text: 'Текст', publish: 'Публикувай нова версия', note: 'Описание на промяната', published: 'Публикувана неизменяема версия' },
  { code: 'en', settings: 'Settings', title: 'Document Studio — Company documents', library: 'Template library', source: 'Download source DOCX', copy: 'Create editable Studio copy', preview: 'Validate and preview PDF', back: 'Back to editor', close: 'Close', variant: 'Request variant', save: 'Save changes', text: 'Text' },
  { code: 'ru', settings: 'Настройки', title: 'Document Studio — Документы компании', library: 'Библиотека шаблонов', source: 'Скачать исходный DOCX', copy: 'Создать редактируемую копию Studio', preview: 'Проверить и открыть PDF', back: 'Вернуться в редактор', close: 'Закрыть', variant: 'Вариант заявки', save: 'Сохранить изменения', text: 'Текст' },
]
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click(); await expect(page.locator('.sidebar-navigation')).toBeVisible()
  for (const language of languages) {
    await api('/users/me/preferences', { preferred_language: language.code }, 'PATCH')
    await page.reload(); await expect(page.locator('.sidebar-navigation')).toBeVisible()
    await page.locator('.sidebar-navigation').getByRole('button', { name: language.settings, exact: true }).click()
    await page.locator('.studio-settings-tabs').getByRole('button', { name: language.title, exact: true }).click()
    await button(language.library).click()
    const templates = await api('/studio/templates')
    for (const type of ['TRANSFER_ISSUE', 'TRANSFER_RETURN', 'REPAIR_PROTOCOL', 'PART_REQUEST']) {
      const template = templates.find(t => t.document_type === type)
      await page.locator('.studio-template-list button').filter({ hasText: template.code }).click()
      const version = template.versions.find(v => v.language === language.code && v.status === 'PUBLISHED' && !v.studio)
      const row = page.locator(`[data-version-id="${version.id}"]`)
      const download = page.waitForEvent('download')
      await button(language.source, row).click()
      const file = await download
      const hash = createHash('sha256').update(await readFile(await file.path())).digest('hex')
      if (hash !== version.source_sha256) throw new Error('Source download hash mismatch')
      await button(language.copy, row).click()
      const editor = page.locator('.visual-editor')
      await expect(editor).toBeVisible()
      for (const width of [390, 768, 1440]) {
        await page.setViewportSize({ width, height: 1000 })
        await shot(`native-${type.toLowerCase()}-${language.code}-${width}`)
      }
      if (type === 'PART_REQUEST') {
        const title = editor.locator('.editor-paper-stack [data-block-id]').filter({ hasText: 'TECHNICAL SPECIFICATION' }).first()
        await title.click()
        const input = editor.locator('.editor-inspector').getByLabel(language.text, { exact: true })
        await input.fill('TECHNICAL SPECIFICATION — SYNTHETIC QA')
        if (await button(language.save, editor).isEnabled()) await button(language.save, editor).click()
      }
      for (const variant of type === 'PART_REQUEST' ? ['MACHINE', 'FREE_FORM'] : ['MACHINE']) {
        if (type === 'PART_REQUEST') await editor.getByLabel(language.variant, { exact: true }).selectOption(variant)
        await button(language.preview, editor).click()
        await expect(editor.locator('.editor-pdf img')).toBeVisible()
        await shot(`actual-${type.toLowerCase()}-${variant.toLowerCase()}-${language.code}`)
        for (const format of ['PDF', 'DOCX']) {
          const pending = page.waitForEvent('download')
          await button(format, editor).click()
          await (await pending).saveAs(`${out}/${type.toLowerCase()}-${variant.toLowerCase()}-${language.code}.${format.toLowerCase()}`)
        }
        await button(language.back, editor).click()
      }
      if (language.code === 'bg' && type === 'PART_REQUEST') {
        await editor.getByLabel(language.note, { exact: true }).fill('SYNTHETIC QA publication of both canonical request variants')
        await button(language.publish, editor).click()
        await expect(editor.getByRole('status')).toContainText(language.published, { timeout: 240000 })
        const config = await api('/studio/configuration/PART_REQUEST/bg')
        if (config.selection_kind !== 'LEGACY' || config.activation_revision !== 0) throw new Error('Publication changed active selection')
        checks.push('Publishing validates six native request cases and leaves the active legacy selection unchanged')
      }
      await button(language.close, editor).click()
      if (language.code === 'bg' && type === 'PART_REQUEST') {
        await page.getByLabel('Основание за смяна на официалния шаблон', { exact: true }).fill('SYNTHETIC QA native activation')
        await button('Активирай за нови официални документи').click()
        await expect(button('Възстанови одобрения legacy шаблон')).toBeVisible()
        const active = await api('/studio/configuration/PART_REQUEST/bg')
        if (active.selection_kind !== 'STUDIO' || !active.valid || active.activation_revision !== 1) throw new Error('Native activation diagnostics mismatch')
        await page.getByLabel('Основание за смяна на официалния шаблон', { exact: true }).fill('SYNTHETIC QA native legacy restore')
        await button('Възстанови одобрения legacy шаблон').click()
        await expect(button('Възстанови одобрения legacy шаблон')).toHaveCount(0)
        const restored = await api('/studio/configuration/PART_REQUEST/bg')
        if (restored.selection_kind !== 'LEGACY' || !restored.valid || restored.activation_revision !== 2) throw new Error('Native legacy restore diagnostics mismatch')
        await shot('native-legacy-restore-bg')
        checks.push('Explicit native Studio activation and legacy restore in a disposable QA installation, with read-only diagnostics')
      }
      checks.push(`${type}/${language.code}: hash-verified source, native copy, responsive controls, actual PDF and DOCX downloads`)
    }
  }
  if (errors.length) throw new Error('Browser page errors')
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ checks, screenshots, page_errors: errors }, null, 2))
  console.log(`Native fidelity browser checks: ${checks.length}; screenshots: ${screenshots.length}`)
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true })
  throw error
} finally {
  await browser.close()
}
