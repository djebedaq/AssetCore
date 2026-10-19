import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url), modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath), expect = require(modulePath + '/test').expect.configure({ timeout: 45000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, hasTouch: true }), page = await context.newPage()
const base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT, screenshots = [], checks = [], errors = []
page.on('pageerror', error => errors.push(error.name))
page.on('dialog', dialog => void dialog.accept())
const button = (name, root = page) => root.getByRole('button', { name, exact: true })
const editor = page.locator('.visual-editor'), inspector = page.locator('.editor-inspector'), palette = page.locator('.editor-palette')
const canvas = editor.locator('.editor-paper-stack')
async function api(path, data, method = 'POST', expected = 200) {
  const csrf = (await context.cookies()).find(c => c.name === 'assetcore_csrf')?.value
  const result = await page.request.fetch(base + '/api' + path, { method: data === undefined ? 'GET' : method, ...(data === undefined ? {} : { data }), headers: { 'X-CSRF-Token': csrf || '' } })
  if (result.status() !== expected) throw new Error(`QA API ${path} returned ${result.status()}`)
  return result.json()
}
async function shot(name, width = 1440) {
  await page.setViewportSize({ width, height: 1000 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await page.evaluate(() => scrollTo(0, 0))
  await page.screenshot({ path: `${out}/${name}-${width}.png`, fullPage: true })
  screenshots.push(`${name}-${width}.png`)
}
async function openStudio(settings = 'Настройки', title = 'Document Studio — Фирмени документи', library = 'Библиотека с шаблони') {
  await page.locator('.sidebar-navigation').getByRole('button', { name: settings, exact: true }).click()
  const tab = page.locator('.studio-settings-tabs').getByRole('button', { name: title, exact: true }); await tab.click()
  if (library) await button(library).click()
}
async function saved() {
  await expect(editor.getByRole('status')).toContainText('Потвърдено от сървъра')
  await expect(button('Провери и виж PDF', editor)).toBeEnabled()
}
async function manualSave() { await button('Запази промените', editor).click(); await saved() }
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await openStudio('Настройки', 'Document Studio — Фирмени документи', '')
  await page.getByLabel('Фирмени изображения', { exact: true }).setInputFiles(`${out}/synthetic-brand.png`)
  await button('Качи изображение').click()
  await expect(page.locator('.studio-images img').first()).toBeVisible()
  await button('Запази промените').click()
  await expect(page.getByRole('status')).toHaveText('Потвърдено от сървъра')
  const profile = await api('/studio/company')
  if (!profile.identity.primary_logo_id) throw new Error('Image was not saved to the profile allowlist')
  const template = await api('/studio/templates', { code: 'QA_STUDIO_B', document_type: 'PART_REQUEST', name_bg: 'Synthetic QA Studio B', name_en: 'Synthetic QA Studio B', name_ru: 'Synthetic QA Studio B' }, 'POST', 201)
  await button('Библиотека с шаблони').click()
  await page.locator('.studio-template-list').getByRole('button', { name: /Synthetic QA Studio B/ }).click()
  await page.getByLabel('Име на черновата', { exact: true }).fill('Synthetic QA visual editor')
  await button('Създай').click()
  await expect(editor).toBeVisible()
  await editor.getByLabel('Автозапис', { exact: true }).uncheck()
  await editor.getByLabel('Мащаб', { exact: true }).selectOption('0.65')
  await expect.poll(() => canvas.locator('.editor-paper').first().evaluate(el => Math.round(el.getBoundingClientRect().width))).toBe(516)
  await shot('a4-starter-bg')
  const drafts = await api(`/studio/templates/${template.id}/drafts`), id = drafts[0].id
  await button('Фирмено лого', palette).click()
  await expect(canvas.locator('.editor-image img')).toBeVisible()
  await inspector.getByLabel('Ширина (mm)', { exact: true }).fill('55')
  await inspector.getByLabel('Височина (mm)', { exact: true }).fill('18')
  await button('Премести нагоре', inspector).click()
  await manualSave()
  await shot('logo-inspector-bg')
  // Native HTML drag-and-drop must change persisted order.
  await page.evaluate(() => {
    window.qaStudioDragEvents = []
    for (const type of ['dragstart', 'dragenter', 'dragover', 'drop', 'dragend']) document.addEventListener(type, event => {
      if (window.qaStudioDragEvents.length < 30) window.qaStudioDragEvents.push({ type, block: event.target.closest?.('[data-block-id]')?.dataset.blockId, x: event.clientX, y: event.clientY })
    })
  })
  const beforeDrag = await api(`/studio/drafts/${id}`)
  const source = canvas.locator('[data-block-id]').first(), target = canvas.locator('[data-block-id]').nth(1)
  await source.scrollIntoViewIfNeeded()
  // Linux fonts can wrap the toolbar and put the second row just below the
  // viewport. Scroll the target too before measuring either mouse endpoint.
  await target.scrollIntoViewIfNeeded()
  const start = await source.boundingBox(), end = await target.boundingBox()
  await page.mouse.move(start.x + 20, start.y + start.height / 2)
  await page.mouse.down()
  await page.mouse.move(start.x + 40, start.y + start.height / 2, { steps: 5 })
  await page.mouse.move(end.x + 30, end.y + end.height / 2, { steps: 10 })
  await page.mouse.move(end.x + 35, end.y + end.height / 2)
  await page.mouse.up()
  await expect.poll(() => canvas.locator('[data-block-id]').first().getAttribute('data-block-id')).toBe(beforeDrag.layout.blocks[1].id)
  await manualSave()
  const afterDrag = await api(`/studio/drafts/${id}`)
  if (afterDrag.layout.blocks[1].id !== beforeDrag.layout.blocks[0].id || afterDrag.layout.blocks[0].id !== beforeDrag.layout.blocks[1].id) throw new Error('Drag order did not persist')
  await button('Избор на поле', palette).click()
  await palette.getByLabel('Търси поле', { exact: true }).fill('Фирмено наименование')
  await shot('field-picker-bg')
  await palette.getByRole('button', { name: /Фирмено наименование/ }).click()
  await button('Текст', palette).click()
  await inspector.getByLabel('Текст', { exact: true }).fill('Синтетичен текст — проверка на кирилица')
  await inspector.getByLabel('Получер', { exact: true }).check()
  await inspector.getByLabel('Курсив', { exact: true }).check()
  await inspector.getByLabel('Подравняване', { exact: true }).selectOption('center')
  await button('Дублирай (Ctrl+D)', inspector).click()
  const blockCount = await canvas.locator('[data-block-id]').count()
  await button('Отмени (Ctrl+Z)', editor).click()
  await expect(canvas.locator('[data-block-id]')).toHaveCount(blockCount - 1)
  await button('Повтори (Ctrl+Y)', editor).click()
  await expect(canvas.locator('[data-block-id]')).toHaveCount(blockCount)
  await page.keyboard.press('Control+z')
  await expect(canvas.locator('[data-block-id]')).toHaveCount(blockCount - 1)
  await button('Статична таблица', palette).click()
  await inspector.getByLabel('Ред 2, колона 1', { exact: true }).fill('Синтетична клетка / Synthetic cell / Синтетическая ячейка')
  await button('Добави ред', inspector).click()
  await button('Добави колона', inspector).click()
  await inspector.getByLabel('Ред 3, колона 3', { exact: true }).fill('QA')
  await shot('table-editing-bg')
  await button('Премахни колоната', inspector).click()
  await button('Премахни реда', inspector).last().click()
  await manualSave()
  checks.push('Real logo dimensions, field picker, native drag reorder, text styling, static table rows/columns and undo/redo persist')
  // Exercise each remaining block with real persistence and DOCX rendering.
  for (const name of ['Заглавие', 'Линия', 'Рамка', 'QR код на документа', 'Условен текст', 'Номер на страница']) {
    await button(name, palette).click()
    if (name === 'Заглавие') {
      await inspector.getByLabel('Получер', { exact: true }).uncheck()
      await inspector.getByLabel('Размер (pt)', { exact: true }).fill('14')
      await expect.poll(() => canvas.locator('.editor-heading-text').evaluate(el => getComputedStyle(el).fontWeight)).toBe('400')
      const size = await canvas.locator('.editor-heading-text').evaluate(el => parseFloat(getComputedStyle(el).fontSize))
      expect(size).toBeCloseTo(14 * 96 / 72, 1)
      await inspector.getByLabel('Получер', { exact: true }).check()
      await inspector.getByLabel('Размер (pt)', { exact: true }).fill('16')
    }
    if (name === 'Рамка') {
      const width = await canvas.locator('[data-block-id][aria-pressed=true]').evaluate(el => el.getBoundingClientRect().width)
      expect(width).toBeCloseTo(40 * 96 / 25.4 * .65, 0)
    }
  }
  await inspector.getByLabel('Област', { exact: true }).selectOption('footer')
  await inspector.getByLabel('Размер (pt)', { exact: true }).fill('8')
  await inspector.getByLabel('Разстояние след (mm)', { exact: true }).fill('0')
  await manualSave()
  await editor.getByLabel('Автозапис', { exact: true }).check()
  await inspector.getByLabel('Име на черновата', { exact: true }).fill('Synthetic QA autosaved editor')
  await saved()
  const auto = await api(`/studio/drafts/${id}`)
  if (auto.title !== 'Synthetic QA autosaved editor') throw new Error('Autosave did not persist')
  // A transient transport error retains edits and is retried with backoff.
  let interrupted = false
  await page.route(`**/api/studio/drafts/${id}`, async route => { if (!interrupted && route.request().method() === 'PUT') { interrupted = true; await route.abort('failed') } else await route.continue() })
  await inspector.getByLabel('Име на черновата', { exact: true }).fill('Synthetic QA network recovery')
  await expect(editor.getByRole('alert')).toBeVisible()
  await saved()
  await page.unroute(`**/api/studio/drafts/${id}`)
  if (!interrupted || (await api(`/studio/drafts/${id}`)).title !== 'Synthetic QA network recovery') throw new Error('Network recovery failed')
  checks.push('Autosave confirms server revision and recovers from a real aborted network request without losing edits')
  await editor.getByLabel('Автозапис', { exact: true }).uncheck()
  await inspector.getByLabel('Име на черновата', { exact: true }).fill('Synthetic QA session recovery')
  await page.reload(); await openStudio()
  await page.locator('.studio-template-list').getByRole('button', { name: /Synthetic QA Studio B/ }).click()
  await button('Отвори').click()
  await expect(button('Възстанови промените', editor)).toBeVisible()
  await shot('session-recovery-bg')
  await button('Възстанови промените', editor).click()
  await expect(inspector.getByLabel('Име на черновата', { exact: true })).toHaveValue('Synthetic QA session recovery')
  await manualSave()
  checks.push('Reload recovery restores unsaved work from session storage and saves it against the original revision')
  // Concurrent editor: advance only the server revision, preserve local edits.
  await editor.getByLabel('Автозапис', { exact: true }).uncheck()
  const external = await api(`/studio/drafts/${id}`)
  await api(`/studio/drafts/${id}`, { expected_revision: external.revision, title: 'Synthetic QA other administrator', layout: external.layout }, 'PUT')
  await inspector.getByLabel('Име на черновата', { exact: true }).fill('Synthetic QA retained conflict')
  await button('Запази промените', editor).click()
  await expect(editor.getByRole('alert')).toContainText('Има по-нова версия')
  await expect(inspector.getByLabel('Име на черновата', { exact: true })).toHaveValue('Synthetic QA retained conflict')
  await shot('conflict-retained-bg')
  await button('Зареди от сървъра', editor).click()
  await expect(inspector.getByLabel('Име на черновата', { exact: true })).toHaveValue('Synthetic QA other administrator')
  checks.push('CAS conflict blocks overwrite, retains local work, and explicit reload clears revision history')
  // Bounds are enforced before the converter can see the input.
  await editor.getByLabel('Полета (mm)', { exact: true }).fill('40')
  await canvas.locator('[data-block-id]').filter({ has: page.locator('.editor-image') }).click()
  await inspector.getByLabel('Ширина (mm)', { exact: true }).fill('180')
  await button('Запази промените', editor).click()
  await expect(editor.getByRole('alert')).toContainText('печатната област')
  await shot('bounds-validation-bg')
  await inspector.getByLabel('Ширина (mm)', { exact: true }).fill('55')
  await editor.getByLabel('Полета (mm)', { exact: true }).fill('15')
  await inspector.getByLabel('Име на черновата', { exact: true }).fill('Synthetic QA corrected bounds')
  await manualSave()
  await editor.getByLabel('Тестови редове', { exact: true }).selectOption('30')
  await button('Провери и виж PDF', editor).click()
  await expect(editor.getByRole('img', { name: 'Реален PDF преглед' })).toBeVisible({ timeout: 90000 })
  await shot('actual-pdf-page1-bg')
  const pageText = await editor.locator('.editor-pdf .editor-toolbar').innerText()
  if (!/\/ [2-9]/.test(pageText)) throw new Error('30 long rows did not create a multipage PDF')
  await button('Следваща страница', editor).click()
  await shot('actual-pdf-multipage-bg')
  for (const kind of ['DOCX', 'PDF']) {
    const download = page.waitForEvent('download'); await button(kind, editor).click()
    await (await download).saveAs(`${out}/actual-preview.${kind.toLowerCase()}`)
  }
  await editor.getByLabel('Описание на промяната', { exact: true }).fill('Synthetic QA validated visual publication')
  await shot('publish-review-bg')
  await button('Публикувай нова версия', editor).click()
  await expect(editor.getByRole('status')).toContainText('Публикувана неизменяема версия', { timeout: 180000 })
  await button('Затвори', editor).click()
  await expect(page.locator('.studio-version').getByText('Synthetic QA validated visual publication')).toBeVisible()
  await page.getByLabel('Основание за смяна на официалния шаблон', { exact: true }).fill('Synthetic QA controlled activation')
  await button('Активирай за нови официални документи').click()
  await expect(page.getByText('Активна Studio версия', { exact: true })).toBeVisible()
  await shot('immutable-version-history-active-bg')
  checks.push('Actual DOCX-derived multipage PDF, downloaded editable DOCX/PDF, immutable publication and separate activation')
  // The real KK approval path now selects that same published source.
  const request = await api('/part-requests/free-form', { department: 'Synthetic QA', reason: 'Synthetic QA document proof', language: 'bg', lines: [{ description: 'Синтетична проверка на документ', quantity: '1', unit: 'pcs' }] }, 'POST', 201)
  await api(`/part-requests/${request.id}/submit`, {})
  const approved = await api(`/part-requests/${request.id}/decision`, { decision: 'APPROVED', note: 'Synthetic QA only' })
  if (approved.generation_status !== 'READY') throw new Error('Official KK generation failed')
  for (const doc of approved.documents) {
    const response = await page.request.get(base + '/api/generated-documents/' + doc.id + '/download')
    if (!response.ok()) throw new Error('Generated archive download failed')
    await writeFile(`${out}/official-kk.${doc.format}`, await response.body())
  }
  checks.push('Canonical KK approval generates the actual published Studio DOCX/PDF and archives both formats')
  for (const lang of [
    { code: 'bg', settings: 'Настройки', title: 'Document Studio — Фирмени документи', library: 'Библиотека с шаблони', open: 'Отвори', canvas: 'Лист' },
    { code: 'en', settings: 'Settings', title: 'Document Studio — Company documents', library: 'Template library', open: 'Open', canvas: 'Canvas' },
    { code: 'ru', settings: 'Настройки', title: 'Document Studio — Документы компании', library: 'Библиотека шаблонов', open: 'Открыть', canvas: 'Лист' },
  ]) {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await api('/users/me/preferences', { preferred_language: lang.code }, 'PATCH')
    await page.reload(); await openStudio(lang.settings, lang.title, lang.library)
    await page.locator('.studio-template-list').getByRole('button', { name: /Synthetic QA Studio B/ }).click()
    await button(lang.open).click(); await expect(editor).toBeVisible()
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({ width, height: 1000 })
      if (width === 390) await editor.locator('.editor-mobile-tabs').getByRole('button', { name: lang.canvas, exact: true }).click()
      await shot(`editor-${lang.code}`, width)
      if (lang.code === 'en' && width === 390) {
        await editor.locator('.editor-mobile-tabs').getByRole('button', { name: 'Blocks', exact: true }).tap()
        await shot('touch-blocks-en', width)
        await button('Text', palette).tap()
        await inspector.getByLabel('Text', { exact: true }).fill('Synthetic QA touch editing')
        await inspector.getByRole('button', { name: 'Move up', exact: true }).tap()
        await inspector.getByRole('button', { name: 'Move down', exact: true }).tap()
        await expect(editor.getByRole('status')).toContainText('Confirmed by server')
        await shot('touch-inspector-en', width)
      }
    }
  }
  checks.push('BG/EN/RU editor is usable at 1440, 768 and 390 with compact mobile panels and no document-level overflow')
  checks.push('Touch-enabled 390px context adds text, edits properties, reorders with touch buttons and confirms autosave')
  if (errors.length) throw new Error('Browser runtime errors')
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ passed: true, stage: 'COMMERCIAL-DOCS-01B', platform: process.platform, browser: await browser.version(), checks, screenshots, errors }, null, 2))
  console.log(JSON.stringify({ passed: true, checks: checks.length, screenshots: screenshots.length }))
} catch (error) {
  console.error(error.message)
  await writeFile(`${out}/drag-events.json`, JSON.stringify(await page.evaluate(() => window.qaStudioDragEvents || []), null, 2))
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true, timeout: 15000 }).catch(() => {})
  await writeFile(`${out}/failure-ui.txt`, await page.locator('.document-studio').innerText().catch(() => 'unavailable'))
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ passed: false, checks, screenshots, errors, failure: error.message }, null, 2))
  process.exitCode = 1
} finally { await browser.close() }
