import { createRequire } from 'node:module'
import { readFile, writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url), modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath), expect = require(modulePath + '/test').expect.configure({ timeout: 45000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, hasTouch: true }), page = await context.newPage()
const base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT, checks = [], screenshots = [], errors = []
page.on('pageerror', e => errors.push(e.name)); page.on('dialog', d => void d.accept())
const button = (name, root = page) => root.getByRole('button', { name, exact: true })
const editor = page.locator('.visual-editor'), canvas = editor.locator('.editor-paper-stack'), inspector = editor.locator('.editor-inspector'), palette = editor.locator('.editor-palette')
async function api(path, data, method = 'POST', expected = 200) {
  const csrf = (await context.cookies()).find(c => c.name === 'assetcore_csrf')?.value
  const r = await page.request.fetch(base + '/api' + path, { method: data === undefined ? 'GET' : method, ...(data === undefined ? {} : { data }), headers: { 'X-CSRF-Token': csrf || '' } })
  if (r.status() !== expected) throw new Error(`QA API ${path}: ${r.status()}`)
  return r.json()
}
async function openStudio(settings = 'Настройки', title = 'Document Studio — Фирмени документи', library = 'Библиотека с шаблони') {
  await page.locator('.sidebar-navigation').getByRole('button', { name: settings, exact: true }).click()
  await page.locator('.studio-settings-tabs').getByRole('button', { name: title, exact: true }).click()
  await button(library).click()
}
async function shot(name) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  if (await canvas.isVisible()) await expect.poll(() => canvas.evaluate(stack =>
    [...stack.querySelectorAll('.editor-body')].every(body => [...body.children].every(slice => {
      if (getComputedStyle(slice).overflow === 'hidden') return true // Deliberately sliced oversized flow.
      const content = slice.querySelector(':scope > div > [data-block-id]')
      const end = content?.getBoundingClientRect().bottom || slice.getBoundingClientRect().bottom
      const next = slice.nextElementSibling
      return end <= (next || body).getBoundingClientRect()[next ? 'top' : 'bottom'] + 2
    })))).toBe(true)
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true }); screenshots.push(`${name}.png`)
}
async function save() {
  const b = button('Запази промените', editor)
  if (await b.isEnabled()) await b.click()
  await expect(button('Провери и виж PDF', editor)).toBeEnabled()
}
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await expect(page.locator('.sidebar-navigation')).toBeVisible()
  const raw = (await readFile(`${out}/synthetic-brand.png`)).toString('base64')
  const images = []
  for (const purpose of ['PRIMARY', 'SECONDARY']) images.push(await api('/studio/images', { filename: 'synthetic.png', media_type: 'image/png', purpose, content_base64: raw }, 'POST', 201))
  const profile = await api('/studio/company')
  await api('/studio/company', { expected_revision: profile.revision, identity: { ...profile.identity, legal_name: 'SYNTHETIC QA ONLY', primary_logo_id: images[0].id, secondary_logo_id: images[1].id } }, 'PUT')
  const types = ['TRANSFER_ISSUE', 'TRANSFER_RETURN', 'REPAIR_PROTOCOL', 'PART_REQUEST'], templates = []
  for (const [i, type] of types.entries()) templates.push(await api('/studio/templates', { code: `QA_FIDELITY_${i}`, document_type: type, name_bg: `Synthetic fidelity ${i}`, name_en: `Synthetic fidelity ${i}`, name_ru: `Synthetic fidelity ${i}` }, 'POST', 201))
  await page.reload(); await openStudio()
  for (const [i, template] of templates.entries()) {
    await page.locator('.studio-template-list').getByRole('button', { name: new RegExp(`Synthetic fidelity ${i}`) }).click()
    await page.getByLabel('Име на черновата', { exact: true }).fill(`SYNTHETIC professional ${i}`)
    await expect(page.getByLabel('Начално оформление', { exact: true })).toHaveValue('professional')
    await button('Създай').click(); await expect(editor).toBeVisible()
    await editor.getByLabel('Автозапис', { exact: true }).uncheck()
    await expect(canvas.locator('.editor-header table').first().locator('col')).toHaveCount(3)
    await expect(canvas.locator('.editor-header').first().locator('img')).toHaveCount(2)
    if (i === 0) {
      await canvas.locator('.editor-header td > .editor-cell-select').nth(1).click()
      await expect(inspector.getByLabel('Име на групата', { exact: true })).toBeVisible()
      await button('Текст', palette).click()
      await inspector.getByLabel('Текст', { exact: true }).fill('SYNTHETIC QA HEADER DESCRIPTION')
      await button('Добавяй към страницата', palette).click()
      await button('Редове и клетки', palette).click()
      await inspector.getByLabel('Име на групата', { exact: true }).fill('SYNTHETIC QA GROUP')
      await button('Ред 1, колона 1', inspector).click()
      await button('Избор на поле', palette).click()
      await palette.getByLabel('Търси поле', { exact: true }).fill('Инвентарен номер')
      await palette.getByRole('button', { name: /Инвентарен номер/ }).click()
      const group = canvas.locator('.editor-body .editor-grid').last().locator('..')
      await group.locator('td > .editor-cell-select').first().click()
      await button('Добави ред', inspector).click()
      await button('Добави колона', inspector).click()
      await button('Обедини със следващата клетка', inspector).click()
      await expect(group.locator('td[colspan="2"]')).toHaveCount(1)
      await button('Раздели обединената клетка', inspector).click()
      await button('Ред 2, колона 2', inspector).click()
      await button('Редове и клетки', palette).click()
      await inspector.getByLabel('Име на групата', { exact: true }).fill('SYNTHETIC NESTED GROUP')
      await button('Добавяй към страницата', palette).click()
      // Move an existing protected signature through the visible destination
      // selector; no direct layout JSON edits or alternate signing mechanism.
      await canvas.locator('.editor-signature').first().click()
      await inspector.getByLabel('Премести блока в клетка', { exact: true }).selectOption({ label: 'SYNTHETIC QA GROUP · Ред 1, колона 3' })
      await expect(button('Изтрий блока', inspector)).toBeDisabled()
      await save(); await shot('nested-header-identification-signature-bg-1440')
      const d = (await api(`/studio/templates/${template.id}/drafts`))[0]
      const walk = blocks => blocks.flatMap(b => [b, ...(b.grid_rows || []).flatMap(r => r.cells.flatMap(c => walk(c.blocks)))])
      const blocks = walk(d.layout.blocks)
      if (blocks.filter(b => b.slot === 'LEFT_SIGNATURE').length !== 1 || !blocks.some(b => b.label === 'SYNTHETIC NESTED GROUP')) throw new Error('Nested layout or protected signature did not persist')
      checks.push('Visible UI edits three-column header, dynamic cells, nested groups, rows/columns, merges and protected signature relocation')
    }
    if (i === 3) {
      await canvas.locator('.editor-block').filter({ has: page.locator('table thead') }).first().click()
      const grouping = inspector.getByLabel('Групирай по записания възел, без да пренареждаш позициите', { exact: true })
      await grouping.check(); await save()
      const d = (await api(`/studio/templates/${template.id}/drafts`))[0]
      if (!d.layout.blocks.some(b => b.type === 'dynamic_table' && b.group_by === 'assembly')) throw new Error('Canonical assembly grouping did not persist')
    }
    await save(); await button('Провери и виж PDF', editor).click()
    await expect(editor.getByRole('img', { name: 'Реален PDF преглед' })).toBeVisible({ timeout: 90000 })
    await shot(`actual-${types[i].toLowerCase()}-pdf-bg`)
    for (const kind of ['DOCX', 'PDF']) { const event = page.waitForEvent('download'); await button(kind, editor).click(); await (await event).saveAs(`${out}/${types[i].toLowerCase()}.${kind.toLowerCase()}`) }
    await button('Към редактора', editor).click()
    await shot(`professional-${types[i].toLowerCase()}-editor-bg`)
    if (i === 3) {
      await editor.getByLabel('Описание на промяната', { exact: true }).fill('Synthetic professional source with explicit operational restore')
      await button('Публикувай нова версия', editor).click()
      await expect(editor.getByRole('status')).toContainText('Публикувана неизменяема версия', { timeout: 180000 })
    }
    await button('Затвори', editor).click()
    if (i === 3) {
      await page.getByLabel('Основание за смяна на официалния шаблон', { exact: true }).fill('Synthetic explicit Studio activation')
      await button('Активирай за нови официални документи').click()
      await expect(button('Възстанови одобрения legacy шаблон')).toBeVisible()
      await page.getByLabel('Основание за смяна на официалния шаблон', { exact: true }).fill('Synthetic confirmed legacy restoration')
      await button('Възстанови одобрения legacy шаблон').click()
      await expect(button('Възстанови одобрения legacy шаблон')).toHaveCount(0)
      await page.getByText('История на избора на шаблон', { exact: false }).click()
      await expect(page.getByText('Synthetic confirmed legacy restoration', { exact: false })).toBeVisible()
      await shot('legacy-restore-history-bg')
      const history = await api('/studio/selections/PART_REQUEST/bg')
      if (history[0].selection_kind !== 'LEGACY' || history[1].selection_kind !== 'STUDIO') throw new Error('Restore history missing')
      checks.push('Publication, explicit Studio activation, confirmed legacy restoration and append-only history through the UI')
    }
  }
  checks.push('Four professional workflow starters produce downloadable editable DOCX and real DOCX-derived PDFs')
  for (const l of [
    { code: 'bg', settings: 'Настройки', title: 'Document Studio — Фирмени документи', library: 'Библиотека с шаблони', open: 'Отвори', canvas: 'Лист', blocks: 'Блокове', inspector: 'Свойства', grid: 'Редове и клетки', name: 'Име на групата', text: 'Текст' },
    { code: 'en', settings: 'Settings', title: 'Document Studio — Company documents', library: 'Template library', open: 'Open', canvas: 'Canvas', blocks: 'Blocks', inspector: 'Inspector', grid: 'Rows and cells', name: 'Group name', text: 'Text' },
    { code: 'ru', settings: 'Настройки', title: 'Document Studio — Документы компании', library: 'Библиотека шаблонов', open: 'Открыть', canvas: 'Лист', blocks: 'Блоки', inspector: 'Свойства', grid: 'Строки и ячейки', name: 'Имя группы', text: 'Текст' },
  ]) {
    await api('/users/me/preferences', { preferred_language: l.code }, 'PATCH')
    await page.reload(); await openStudio(l.settings, l.title, l.library)
    await page.locator('.studio-template-list').getByRole('button', { name: /Synthetic fidelity 1/ }).click()
    await button(l.open).click()
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({ width, height: 1000 })
      if (width === 390) await editor.locator('.editor-mobile-tabs').getByRole('button', { name: l.canvas, exact: true }).tap()
      await shot(`professional-${l.code}-${width}`)
    }
    await editor.locator('.editor-mobile-tabs').getByRole('button', { name: l.blocks, exact: true }).tap()
    await button(l.grid, palette).tap()
    await inspector.getByLabel(l.name, { exact: true }).fill(`SYNTHETIC TOUCH ${l.code}`)
    await button(l.open === 'Open' ? 'Row 1, column 1' : l.code === 'ru' ? 'Строка 1, столбец 1' : 'Ред 1, колона 1', inspector).tap()
    await editor.locator('.editor-mobile-tabs').getByRole('button', { name: l.blocks, exact: true }).tap()
    await button(l.text, palette).tap()
    await inspector.getByLabel(l.text, { exact: true }).fill('SYNTHETIC TOUCH CELL CONTENT')
    await shot(`touch-cell-${l.code}-390`)
    await expect.poll(async () => {
      const d = (await api(`/studio/templates/${templates[1].id}/drafts`))[0]
      const grid = d.layout.blocks.find(b => b.label === `SYNTHETIC TOUCH ${l.code}`)
      return !!grid?.grid_rows.some(r => r.cells.some(c => c.blocks.some(b => b.text === 'SYNTHETIC TOUCH CELL CONTENT')))
    }).toBe(true)
    await page.setViewportSize({ width: 1440, height: 1000 })
  }
  checks.push('BG/EN/RU professional editor at 1440/768/390; touch adds and edits nested cell content and autosaves without page overflow')
  if (errors.length) throw new Error('Browser runtime errors')
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ passed: true, platform: process.platform, browser: await browser.version(), checks, screenshots, errors }, null, 2))
  console.log(JSON.stringify({ passed: true, checks: checks.length, screenshots: screenshots.length }))
} catch (e) {
  console.error(e.message)
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true }).catch(() => {})
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ passed: false, checks, screenshots, errors, failure: e.message }, null, 2))
  process.exitCode = 1
} finally { await browser.close() }
