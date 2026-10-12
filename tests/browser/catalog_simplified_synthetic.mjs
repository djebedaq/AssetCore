// Real browser / real APIs; only the runtime-generated synthetic PDF is used.
import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
import { finalHotspotAcceptance } from './catalog_final_hotspots.mjs'
const require = createRequire(import.meta.url), modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath)
const expect = require(modulePath + '/test').expect.configure({ timeout: 60000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const context = await browser.newContext({ hasTouch: true, viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT
page.setDefaultTimeout(60000)
const errors = [], checks = [], extracted = []
let acceptDialog = true, referenceId
page.on('pageerror', error => errors.push(error.message))
page.on('dialog', dialog => { void (acceptDialog ? dialog.accept() : dialog.dismiss()) })
page.on('response', async response => {
  const match = response.url().match(/\/reference-pages\/(\d+)\/extract$/)
  if (match && response.status() === 200) { referenceId = Number(match[1]); extracted.push(await response.json()) }
})
const button = name => page.getByRole('button', { name, exact: true })
const task = name => page.locator('.catalog-navigation').getByRole('button', { name }).click()
const api = async path => {
  const response = await page.request.get(base + '/api/admin/catalog-builder' + path)
  expect(response.status()).toBe(200); return response.json()
}
const login = async () => {
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click(); await page.locator('.sidebar-navigation').waitFor()
}
const reopen = async () => {
  await page.locator('.sidebar-navigation').getByRole('button', { name: 'Каталожен конструктор', exact: true }).click()
  await page.locator('.builder-list-item').filter({ hasText: 'Synthetic QA simplified UX' }).getByRole('button', { name: 'Продължи черновата', exact: true }).click()
  await task(/Проверка на части/)
}
try {
  await page.goto(base); await login(); await button('Каталожен конструктор').click()
  expect(await page.getByRole('button', { name: /Advanced|Разширен режим/ }).count()).toBe(0)
  await button('Нов каталог').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeFocused()
  for (let index = 0; index < 12; index++) {
    await page.keyboard.press(index % 2 ? 'Shift+Tab' : 'Tab')
    expect(await dialog.evaluate(node => node.contains(document.activeElement))).toBe(true)
  }
  await dialog.getByLabel('Име на каталога', { exact: true }).fill('Unsaved synthetic QA')
  acceptDialog = false; await page.keyboard.press('Escape'); await expect(dialog).toBeVisible()
  acceptDialog = true; await page.keyboard.press('Escape'); await expect(dialog).toHaveCount(0)
  await expect(button('Нов каталог')).toBeFocused()
  checks.push('No global Advanced mode; dialog keyboard focus trap, Escape cancellation and focus restoration; unsaved values are guarded')
  await button('Нов каталог').click()
  await dialog.getByLabel('Име на каталога', { exact: true }).fill('Synthetic QA simplified UX')
  await dialog.getByRole('combobox').selectOption({ label: 'Водоструйни машини с високо налягане' })
  await dialog.getByRole('button', { name: 'Продължи', exact: true }).click()
  await page.locator('.reference-sidebar').getByLabel('Референция', { exact: true }).fill('Synthetic QA assembly')
  await button('Добави референция').click()
  await expect(page.locator('.reference-sidebar').getByLabel('Референция', { exact: true })).toHaveValue('')
  await task(/PDF страници/)
  const jump = async number => {
    await page.locator('.reader-toolbar input').fill(String(number)); await page.locator('.reader-toolbar input').press('Enter')
    await page.getByRole('img', { name: `PDF страница ${number}`, exact: true }).evaluate(image => image.decode())
  }
  await button('+ Добави схема').click()
  await page.getByLabel('Качи PDF', { exact: true }).setInputFiles(out + '/synthetic.pdf')
  await jump(1); await button('Добави тази страница като схема').click()
  await expect(page.getByText('Страница 1 е добавена: Схема', { exact: true })).toBeVisible()
  await jump(4); await button('Добави тази страница като схема').click()
  await expect(page.getByText('Страница 4 е добавена: Схема', { exact: true })).toBeVisible()
  await page.locator('.source-selection').getByRole('button', { name: 'Затвори', exact: true }).click()
  await button('+ Добави списък с части').click()
  for (const number of [2, 3]) {
    await jump(number); await button('Добави тази страница като списък с части').click()
    await expect(page.getByText(`Страница ${number} е добавена: Списъци с резервни части`, { exact: true })).toBeVisible()
  }
  await page.locator('.source-selection').getByRole('button', { name: 'Затвори', exact: true }).click()
  await page.screenshot({ path: out + '/sources-1440.png', fullPage: true })
  await button('Продължи').click(); await button('Разпознай частите').click()
  await expect.poll(() => extracted.length).toBe(2); await task(/Проверка на части/)
  await expect(page.locator('.guided-parts tbody tr')).toHaveCount(10)
  expect(extracted.flatMap(preview => preview.rows.map(row => row.payload.part_number))).toEqual(Array.from({ length: 10 }, (_, index) => `QA-${index + 1}`))
  await page.locator('.part-original img').evaluate(image => image.decode())
  await expect(page.locator('.part-original .evidence-highlight')).toHaveCount(1)
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await expect.poll(() => page.locator('.unified-parts').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true)
    await page.getByLabel('Номер на част', { exact: true }).focus()
    await expect(page.getByLabel('Номер на част', { exact: true })).toBeFocused()
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: out + `/parts-${width}.png`, fullPage: true })
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  for (const [locale, review, select] of [['en', 'Parts review', 'Select valid visible rows'], ['ru', 'Проверка деталей', 'Выбрать допустимые видимые строки']]) {
    await page.locator('.language-switch').getByRole('combobox').click()
    await page.getByRole('option', { name: locale === 'en' ? 'English' : 'Русский', exact: true }).click()
    await expect(page.locator('.catalog-navigation').getByRole('button', { name: new RegExp(review) })).toBeVisible()
    await expect(button(select)).toBeVisible()
    await expect(page.locator('.guided-parts tbody tr')).toHaveCount(10)
  }
  await page.locator('.language-switch').getByRole('combobox').click()
  await page.getByRole('option', { name: 'Български', exact: true }).click()
  checks.push('Explicit scheme and two list assignments; one recognition action; ten exact separate candidates in one table; 390/768/1440 no page overflow and keyboard editor access')
  checks.push('English and Russian workflow/review controls render; switching back to Bulgarian keeps all ten candidates')
  const other = await context.newPage()
  other.setDefaultTimeout(60000)
  other.on('pageerror', error => errors.push(error.message))
  other.on('dialog', dialog => { void dialog.accept() })
  await other.goto(base)
  await other.locator('.sidebar-navigation').waitFor()
  await other.locator('.language-switch').getByRole('combobox').click()
  await other.getByRole('option', { name: 'Български', exact: true }).click()
  await other.locator('.sidebar-navigation').getByRole('button', { name: 'Каталожен конструктор', exact: true }).click()
  await other.locator('.builder-list-item').filter({ hasText: 'Synthetic QA simplified UX' }).getByRole('button', { name: 'Продължи черновата', exact: true }).click()
  await other.locator('.catalog-navigation').getByRole('button', { name: /Проверка на части/ }).click()
  await expect(other.getByLabel('Номер на част', { exact: true })).toHaveValue('QA-1')
  await page.getByLabel('Номер на част', { exact: true }).fill('QA-FIRST-TAB')
  await expect(button('Потвърди избраните части')).toBeEnabled()
  await other.getByLabel('Номер на част', { exact: true }).fill('QA-SECOND-TAB')
  await expect(other.getByText(/Конфликт с друга промяна/)).toBeVisible()
  await expect(other.getByLabel('Номер на част', { exact: true })).toHaveValue('QA-SECOND-TAB')
  await expect(other.getByRole('button', { name: 'Потвърди избраните части', exact: true })).toBeDisabled()
  await other.getByRole('button', { name: 'Зареди текущия ред', exact: true }).click()
  await expect(other.getByLabel('Номер на част', { exact: true })).toHaveValue('QA-FIRST-TAB')
  await other.getByLabel('Номер на част', { exact: true }).fill('QA-1')
  await expect(other.getByRole('button', { name: 'Потвърди избраните части', exact: true })).toBeEnabled()
  await button('Потвърди избраните части').click()
  await expect(page.getByText(/Страницата е променена/)).toBeVisible()
  expect(await api(`/reference-pages/${referenceId}/parts`)).toHaveLength(0)
  await button('Зареди текущия ред').click()
  await expect(page.getByLabel('Номер на част', { exact: true })).toHaveValue('QA-1')
  await other.close()
  checks.push('Two actual browser tabs: stale autosave preserves unsaved human text; explicit reload sees the saved other-tab correction; stale confirmation creates zero parts; restored exact synthetic original before approval')
  await button('Избери валидните видими редове').click(); await button('Потвърди избраните части').click()
  await expect(button('Потвърди избраните части')).toBeDisabled()
  const catalog = (await api('/catalogs')).find(item => item.name_bg === 'Synthetic QA simplified UX')
  const revision = (await api(`/catalogs/${catalog.id}/revisions`)).find(item => item.status === 'DRAFT')
  const readiness = await api(`/revisions/${revision.id}/publication-readiness`)
  expect(readiness.ready).toBe(false)
  const csrf = (await context.cookies()).find(cookie => cookie.name === 'assetcore_csrf')
  expect(csrf).toBeTruthy()
  const bypass = await page.request.post(base + `/api/admin/catalog-builder/revisions/${revision.id}/publish`, {
    headers: { 'X-CSRF-Token': csrf.value }, data: { expected_publication_digest: readiness.publication_digest, confirmed: true },
  })
  expect(bypass.status()).toBe(409)
  checks.push('Direct authenticated API publication remains blocked before source review and verified hotspots')
  const panel = page.getByRole('region', { name: 'Проверка на всеки източник', exact: true })
  // QA fixture only: remove three confirmed synthetic parts, then use the real
  // extractor/ledger to obtain ACCEPTED_PART_REMOVED conflicts (no mocked API).
  await expect.poll(async () => (await api(`/reference-pages/${referenceId}/parts`)).length).toBe(10)
  for (const part of (await api(`/reference-pages/${referenceId}/parts`)).filter(item => ['1', '2', '6'].includes(item.position))) {
    const removed = await page.request.delete(base + `/api/admin/catalog-builder/parts/${part.id}`, { headers: { 'X-CSRF-Token': csrf.value } })
    expect(removed.status()).toBe(204)
  }
  expect(await api(`/reference-pages/${referenceId}/parts`)).toHaveLength(7)
  await task(/Разпознаване/); await button('Разпознай частите').click()
  await expect.poll(() => extracted.length).toBe(4); await task(/Проверка на части/)
  const showOriginal = index => panel.getByRole('button', { name: 'Покажи оригинала', exact: true }).nth(index).click()
  await showOriginal(0); await panel.locator('img').evaluate(image => image.decode())
  await expect(panel.getByRole('combobox')).toHaveCount(2)
  const remaining = await api(`/reference-pages/${referenceId}/parts`)
  const linkTarget = String(remaining.find(part => part.position === '3').id)
  await panel.getByRole('combobox').nth(0).selectOption(linkTarget)
  await expect(panel.getByRole('combobox').nth(1)).toHaveValue('')
  await panel.getByRole('combobox').nth(1).selectOption(linkTarget)
  await expect(panel.getByRole('combobox').nth(0)).toHaveValue('')
  const pendingReason = 'QA: непотвърдено основание за конкретната оригинална страница.'
  await panel.getByRole('textbox').fill(pendingReason); await panel.getByRole('checkbox').check()
  const firstOriginal = await panel.locator('img').getAttribute('src')
  const cancelled = page.waitForEvent('dialog')
  acceptDialog = false; await showOriginal(1)
  expect((await cancelled).message()).toContain('ще бъдат изчистени')
  await expect(panel.getByRole('textbox')).toHaveValue(pendingReason)
  await expect(panel.getByRole('checkbox')).toBeChecked()
  await expect(panel.getByRole('combobox').nth(1)).toHaveValue(linkTarget)
  await expect(panel.locator('img')).toHaveAttribute('src', firstOriginal)
  acceptDialog = true; await showOriginal(1)
  await panel.locator('img').evaluate(image => image.decode())
  await expect(panel.locator('img')).toHaveAttribute('alt', 'PDF страница 3')
  await expect(panel.getByRole('textbox')).toHaveValue('')
  await expect(panel.getByRole('checkbox')).not.toBeChecked()
  await expect(panel.getByRole('combobox')).toHaveValue('')
  await expect(panel.getByRole('button', { name: 'Свържи с вече поправена част', exact: true })).toBeDisabled()
  expect(await panel.locator('img').getAttribute('src')).not.toBe(firstOriginal)
  await showOriginal(0); await panel.locator('img').evaluate(image => image.decode())
  await expect(panel.getByRole('combobox').nth(0)).toHaveValue('')
  await expect(panel.getByRole('combobox').nth(1)).toHaveValue('')
  await page.screenshot({ path: out + '/source-switch-reset.png', fullPage: true })
  checks.push('Real ledger conflicts: LINK_EXISTING is candidate-specific; cancelled source switch preserves reason/manual/link/original; accepted switch and return clear them and load the exact new physical original')
  // A failed new inspection cannot reuse the prior source's image or receipt.
  await page.route('**/visual-pages/*/review-original', route => route.abort('connectionreset'), { times: 1 })
  await showOriginal(1)
  await expect(panel.locator('p.error[role="alert"]')).toHaveCount(1)
  await expect(panel.locator('img')).toHaveCount(0)
  await expect(panel.getByRole('button', { name: 'Потвърди проверения източник', exact: true })).toBeDisabled()
  await expect(panel.getByRole('textbox')).toHaveValue('')
  await expect(panel.getByRole('checkbox')).not.toBeChecked()
  await page.unroute('**/visual-pages/*/review-original')
  // Delay an authorized real response until after navigation unmounts review.
  await page.evaluate(() => {
    const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL)
    window.qaReviewBlobs = { created: [], revoked: [] }
    URL.createObjectURL = blob => { const url = create(blob); window.qaReviewBlobs.created.push(url); return url }
    URL.revokeObjectURL = url => { window.qaReviewBlobs.revoked.push(url); return revoke(url) }
  })
  let pendingInspection
  const intercepted = new Promise(resolve => { pendingInspection = resolve })
  let finishInspection
  const released = new Promise(resolve => { finishInspection = resolve })
  await page.route('**/visual-pages/*/review-original', async route => {
    const response = await route.fetch()
    pendingInspection()
    await released
    await route.fulfill({ response })
  }, { times: 1 })
  await showOriginal(0); await intercepted
  await task(/Разпознаване/)
  await expect(panel).toHaveCount(0)
  const createdBefore = await page.evaluate(() => window.qaReviewBlobs.created.length)
  finishInspection()
  await expect.poll(() => page.evaluate(before => window.qaReviewBlobs.created.slice(before).some(url => window.qaReviewBlobs.revoked.includes(url)), createdBefore)).toBe(true)
  await page.unroute('**/visual-pages/*/review-original')
  await task(/Проверка на части/)
  await expect(panel.locator('img')).toHaveCount(0)
  await showOriginal(0); await panel.locator('img').evaluate(image => image.decode())
  checks.push('Failed inspection clears the old original and blocks approval; late authorized response after navigation unmount revokes its Blob URL; reopening requires a fresh inspection')
  // Explicit UI recovery of the deliberately removed synthetic rows, keeping
  // their original values and normal candidate versions/audit/publication gate.
  for (const [index, count] of [[0, 2], [1, 1]]) {
    await showOriginal(index)
    await panel.getByRole('textbox').fill('QA: възстановяване на умишлено премахнати синтетични части по точния оригинал.')
    for (let left = count; left > 0; left--) {
      await panel.getByRole('button', { name: 'Потвърди като отделен вариант за преглед', exact: true }).first().click()
      await expect(panel.getByRole('combobox')).toHaveCount(left - 1)
    }
  }
  await button('Избери валидните видими редове').click(); await button('Потвърди избраните части').click()
  await expect(button('Потвърди избраните части')).toBeDisabled()
  await expect.poll(async () => (await api(`/reference-pages/${referenceId}/parts`)).length).toBe(10)
  expect((await api(`/reference-pages/${referenceId}/parts`)).map(part => part.part_number).sort()).toEqual(
    Array.from({ length: 10 }, (_, index) => `QA-${index + 1}`).sort())
  for (const index of [0, 1]) {
    await page.waitForLoadState('networkidle')
    await panel.getByRole('button', { name: 'Покажи оригинала', exact: true }).nth(index).click()
    await panel.locator('img').evaluate(image => image.decode())
    await panel.getByRole('textbox').fill('QA: Сравнени всички десет синтетични реда с точните оригинални страници.')
    await panel.getByRole('button', { name: 'Потвърди проверения източник', exact: true }).click()
    await expect(panel.getByText('Проверен за текущите данни', { exact: false })).toHaveCount(index + 1)
    await expect(panel.locator('.source-attestation')).toHaveCount(0)
  }
  await button('Изход').click(); await login(); await reopen()
  await expect(panel.getByText('Проверен за текущите данни', { exact: false })).toHaveCount(2)
  expect(await api(`/reference-pages/${referenceId}/parts`)).toHaveLength(10)
  checks.push('Confirmed parts and source decisions survive logout and a fresh login')
  await task(/Маркери/)
  await page.locator('.builder-scheme-canvas img').evaluate(image => image.decode())
  await button('Цяла страница').click()
  for (let index = 0; index < 10; index++) {
    await expect(page.getByText(`Щракнете позиция ${index + 1} върху схемата.`, { exact: true })).toBeVisible()
    const width = index < 3 ? 390 : index < 6 ? 768 : 1440
    await page.setViewportSize({ width, height: 1000 }); await button('Цяла страница').click()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const canvas = page.locator('.builder-scheme-canvas')
    await canvas.scrollIntoViewIfNeeded()
    const box = await canvas.boundingBox()
    await page.touchscreen.tap(box.x + box.width * (80 + index % 5 * 140) / 850, box.y + box.height * (145 + Math.floor(index / 5) * 140) / 650)
    await expect.poll(async () => (await api(`/reference-pages/${referenceId}/coverage`)).filter(row => row.state === 'VERIFIED').length).toBe(index + 1)
    await expect(button('Точка')).toBeEnabled()
    // The last saved marker remains selected as a draft overlay; coverage above
    // proves verification independently of the rendered selection class.
    await expect(canvas.locator('.builder-hotspot')).toHaveCount(index + 1)
    await expect.poll(() => canvas.locator('.builder-hotspot').evaluateAll(nodes => nodes.every(node => {
      const rect = node.getBoundingClientRect(), parent = node.parentElement.getBoundingClientRect()
      const css = getComputedStyle(node)
      // A subpixel 0.2% point still has its existing one-pixel border on both sides.
      const borderWidth = parseFloat(css.borderLeftWidth) + parseFloat(css.borderRightWidth)
      const borderHeight = parseFloat(css.borderTopWidth) + parseFloat(css.borderBottomWidth)
      return css.minHeight === '0px' && css.minWidth === '0px'
        && Math.abs(rect.width - Math.max(borderWidth, parent.width * parseFloat(node.style.width) / 100)) < 1
        && Math.abs(rect.height - Math.max(borderHeight, parent.height * parseFloat(node.style.height) / 100)) < 1
    }))).toBe(true)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: out + `/touch-hotspots-${width}.png`, fullPage: true })
  }
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: out + '/hotspots-1440.png', fullPage: true })
  await finalHotspotAcceptance({ page, expect, api, button, referenceId, revisionId: revision.id, base, out })
  checks.push('Second actual synthetic scheme: pointer cancellation, rectangle, mouse move/resize, verify/unverify blocker, stale version rejection, undo/delete, second occurrence, zoom/pan and refresh preserve normalized geometry')
  await task(/Публикуване/)
  await expect(button('Публикувай каталог')).toBeEnabled()
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await expect(button('Публикувай каталог')).toBeEnabled()
  }
  await page.screenshot({ path: out + '/ready-1440.png', fullPage: true })
  const assemblies = await api(`/revisions/${revision.id}/assemblies`)
  const originalGraph = {
    parts: await api(`/reference-pages/${referenceId}/parts`),
    coverage: await api(`/reference-pages/${referenceId}/coverage`),
    pages: await api(`/assemblies/${assemblies[0].id}/reference-pages`),
    hotspots: await Promise.all((await api(`/reference-pages/${referenceId}/exploded-pages`)).map(row => api(`/visual-pages/${row.visual_page_id}/hotspots`))),
  }
  await button('Публикувай каталог').click()
  await expect(page.getByText('Каталогът е публикуван.', { exact: true })).toBeVisible()
  checks.push('Ten actual synthetic callouts placed, saved, verified and advanced with touch at 390/768/1440; overlay dimensions match normalized geometry; responsive reviewed synthetic catalog publishes through UI')
  await page.reload()
  await page.locator('.sidebar-navigation').getByRole('button', { name: 'Каталожен конструктор', exact: true }).click()
  await page.locator('.builder-list-item').filter({ hasText: 'Synthetic QA simplified UX' }).getByRole('button', { name: 'Отвори работното пространство', exact: true }).click()
  await expect(page.getByText('Каталогът е публикуван.', { exact: true })).toBeVisible()
  expect((await api(`/catalogs/${catalog.id}/revisions`)).find(row => row.id === revision.id).status).toBe('PUBLISHED')
  expect(await api(`/reference-pages/${referenceId}/parts`)).toEqual(originalGraph.parts)
  expect(await api(`/reference-pages/${referenceId}/coverage`)).toEqual(originalGraph.coverage)
  expect(await api(`/assemblies/${assemblies[0].id}/reference-pages`)).toEqual(originalGraph.pages)
  expect(await Promise.all((await api(`/reference-pages/${referenceId}/exploded-pages`)).map(row => api(`/visual-pages/${row.visual_page_id}/hotspots`)))).toEqual(originalGraph.hotspots)
  await expect(button('Публикувай каталог')).toHaveCount(0)
  await page.screenshot({ path: out + '/published-reopened-1440.png', fullPage: true })
  checks.push('Published synthetic revision reopens read-only after refresh; exact source assignments, parts and verified hotspot coverage are unchanged')
  expect(errors).toEqual([])
  await writeFile(out + '/results.json', JSON.stringify({ passed: true, checks, pageErrors: errors, syntheticOnly: true, productionAccess: false }, null, 2))
  console.log(JSON.stringify({ checks, pageErrors: errors }))
} catch (error) {
  console.error('Marker layout diagnostics:', JSON.stringify(await page.locator('.builder-hotspot.verified').evaluateAll(nodes => nodes.map(node => ({
    width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height,
    parentWidth: node.parentElement.getBoundingClientRect().width, parentHeight: node.parentElement.getBoundingClientRect().height,
    styleWidth: node.style.width, styleHeight: node.style.height, minHeight: getComputedStyle(node).minHeight,
  }))).catch(() => [])))
  await page.screenshot({ path: out + '/failure.png', fullPage: true }).catch(() => {})
  console.error(String(error.stack || error).replaceAll(process.env.QA_PASSWORD, '[redacted]')); process.exitCode = 1
} finally { await browser.close() }
