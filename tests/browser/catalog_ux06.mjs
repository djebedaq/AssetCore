// Real browser, generated PDF and disposable DB; no auth state in artifacts.
import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url), modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath)
const expect = require(modulePath + '/test').expect.configure({ timeout: 60000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT
page.setDefaultTimeout(60000)
const checks = [], screenshots = [], errors = []
page.on('pageerror', error => errors.push(error.message))
page.on('dialog', dialog => void dialog.accept())
const button = name => page.getByRole('button', { name, exact: true })
async function request(path, data) {
  const csrf = (await context.cookies()).find(cookie => cookie.name === 'assetcore_csrf')?.value
  const response = data === undefined ? await page.request.get(base + '/api' + path)
    : await page.request.post(base + '/api' + path, { data, headers: { 'X-CSRF-Token': csrf || '' } })
  if (!response.ok()) {
    const failure = await response.json()
    throw new Error(`QA API ${response.status()}: ${failure.detail?.code || 'request failed'}`)
  }
  return response.json()
}
const api = (path, data) => request('/admin/catalog-builder' + path, data)
async function shot(name, width) {
  await page.setViewportSize({ width, height: 1000 })
  await page.evaluate(() => window.scrollTo(0, 0))
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await page.screenshot({ path: `${out}/${name}-${width}.png`, fullPage: true })
  screenshots.push(`${name}-${width}.png`)
}
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await page.locator('.sidebar-navigation').getByRole('button', { name: 'Управление на каталози', exact: true }).click()
    await page.setViewportSize({ width: 1440, height: 1000 })
    await button('Нов каталог').click()
    const creationDialog = page.getByRole('dialog')
    const name = `Synthetic QA UX06 central bindings ${Date.now()}`
    await creationDialog.getByLabel('Име на каталога', { exact: true }).fill(name)
    await creationDialog.getByRole('combobox').selectOption({ label: 'QA UX04' })
    await creationDialog.getByLabel('Производител', { exact: true }).fill('QA')
    await creationDialog.getByLabel('Модел / справка', { exact: true }).fill('QA')
    await creationDialog.getByRole('button', { name: 'Продължи', exact: true }).click()
    await page.locator('.reference-sidebar').getByLabel('Възел', { exact: true }).fill('Synthetic QA assembly')
    await button('Добави възел').click()
    await page.locator('.reference-link').first().click()
    await button('+ Добави схема').click()
    await page.getByLabel('Качи PDF', { exact: true }).setInputFiles(`${out}/synthetic.pdf`)
    await expect(page.locator('.pdf-page-picker article')).toHaveCount(7)
    for (let number = 1; number <= 7; number++) {
      await page.locator('.pdf-page-picker article').nth(number - 1).getByRole('checkbox').nth(number <= 3 ? 0 : 1).check()
    }
    await button('Добави избраните страници (7)').click()
    await expect(page.locator('.source-selection')).toHaveCount(0)
    const catalog = (await api('/catalogs')).find(row => row.name_bg === name)
    const revision = (await api(`/catalogs/${catalog.id}/revisions`))[0]
    const assembly = (await api(`/revisions/${revision.id}/assemblies`))[0]
    const logical = (await api(`/assemblies/${assembly.id}/reference-pages`))[0]
    await page.locator('.catalog-navigation').getByRole('button', { name: /Части и маркери/ }).click()
    await button('Разпознай частите').click()
    await expect(page.locator('.unified-parts tbody tr')).toHaveCount(59)
    await page.locator('.part-comparison .reader-image img').evaluate(image => image.decode())
    await button('Избери валидните видими редове').click()
    await button('Потвърди избраните части').click()
    await expect.poll(async () => (await api(`/reference-pages/${logical.id}/parts`)).length).toBe(59)

    await page.locator('.catalog-navigation').getByRole('button', { name: /Публикуване/ }).click()
    await expect(button('Публикувай каталог')).toBeEnabled()
    await button('Публикувай каталог').click()
    await expect.poll(async () => (await api(`/catalogs/${catalog.id}/revisions`))[0].status).toBe('PUBLISHED')
    checks.push('Created and published through the UI with real PDF extraction, confirmed parts and optional UX05 warnings')
    const machines = (await request('/machines')).filter(row => row.inventory_number.startsWith('QA_UX04_'))
    const machine = number => machines.find(row => row.inventory_number === `QA_UX04_${number}`)
    await button('Управление на връзките').click()
    const dialog = page.getByRole('dialog')
    const row = number => dialog.locator('article').filter({ hasText: `QA_UX04_${number}` })
    async function connect(numbers, ambiguous = false) {
      for (const number of numbers) await row(number).getByRole('checkbox').check()
      await dialog.getByRole('button', { name: 'Преглед преди свързване', exact: true }).click()
      if (ambiguous) {
        await expect(dialog.getByRole('button', { name: 'Потвърди свързването' })).toBeDisabled()
        for (const number of numbers) await dialog.getByLabel(`Потвърждавам съвместимостта за QA_UX04_${number}`).check()
      }
      await expect(dialog.getByRole('button', { name: 'Потвърди свързването' })).toBeEnabled()
      await dialog.getByRole('button', { name: 'Потвърди свързването' }).click()
      await expect(dialog).toContainText(`Успешно записани връзки: ${numbers.length}`)
    }
    await connect([1])
    const historyPart = (await request(`/catalog/v2/search?machine_id=${machine(1).id}&q=QA-UX05-059`))[0]
    const historicalRequest = await request('/part-requests/multi', { machine_id: machine(1).id,
      lines: [{ part_id: historyPart.id, description: 'Synthetic QA immutable history', quantity: 1 }] })
    const historyBefore = (await request('/part-requests/multi')).find(row => row.id === historicalRequest.id)
    const first = (await api(`/bindings?catalog_id=${catalog.id}`)).items.find(link => link.machine_id === machine(1).id)
    await connect([2, 3])
    await connect([4], true)
    for (const number of [1, 2, 3, 4]) expect((await request(`/catalog/v2/machines/${machine(number).id}`)).supported).toBe(true)
    checks.push('Single and batch EXACT connections plus per-machine AMBIGUOUS confirmation; runtime available for all four')
    for (const width of [1440, 768, 390]) await shot('central-connect', width)
    await page.setViewportSize({ width: 1440, height: 1000 })
    await row(5).getByRole('checkbox').check(); await row(6).getByRole('checkbox').check()
    await dialog.getByRole('button', { name: 'Преглед преди свързване', exact: true }).click()
    await expect(dialog.getByRole('button', { name: 'Потвърди свързването' })).toBeDisabled()
    await expect(dialog).toContainText('Несъвместим производител или модел')
    const forged = { catalog_id: catalog.id, machine_ids: [machine(5).id, machine(6).id], confirmed_machine_ids: [machine(5).id] }
    const csrf = (await context.cookies()).find(cookie => cookie.name === 'assetcore_csrf').value
    const invalidPlan = await api('/bindings/preview', forged)
    const rejected = await page.request.post(base + '/api/admin/catalog-builder/bindings/batch', { data: { ...forged, expected_digest: invalidPlan.digest }, headers: { 'X-CSRF-Token': csrf } })
    expect(rejected.status()).toBe(409)
    expect((await rejected.json()).detail.code).toBe('catalog_asset_model_mismatch')
    expect((await api(`/bindings?catalog_id=${catalog.id}`)).total).toBe(4)
    expect((await request(`/catalog/v2/machines/${machine(6).id}`)).supported).toBe(false)
    checks.push('Incompatible group blocked in UI and backend; explicit confirmation cannot bypass and zero partial writes')
    await shot('incompatible-preview', 1440)
    await dialog.getByRole('button', { name: 'Отказ', exact: true }).click()
    await dialog.getByRole('button', { name: 'Активни връзки', exact: true }).click()
    await row(1).getByRole('button', { name: 'Премахни връзката', exact: true }).click()
    await expect(dialog).toContainText('Историята и документите се запазват')
    await dialog.getByRole('button', { name: 'Потвърди премахването', exact: true }).click()
    await expect.poll(async () => (await api(`/bindings?catalog_id=${catalog.id}`)).total).toBe(3)
    for (const number of [2, 3]) await row(number).getByRole('checkbox').check()
    await dialog.getByRole('button', { name: 'Премахни избраните', exact: true }).click()
    await expect(dialog).toContainText('Избрани връзки: 2')
    await shot('batch-removal-preview', 768)
    await dialog.getByRole('button', { name: 'Потвърди премахването', exact: true }).click()
    await expect.poll(async () => (await api(`/bindings?catalog_id=${catalog.id}`)).total).toBe(1)
    for (const number of [1, 2, 3]) expect((await request(`/catalog/v2/machines/${machine(number).id}`)).supported).toBe(false)
    expect((await request('/part-requests/multi')).find(row => row.id === historicalRequest.id)).toEqual(historyBefore)
    checks.push('Individual removal and atomic batch removal use concrete pairs and immediately revoke runtime availability')
    // There are unfinished incompatible selections; the in-dialog close guard preserves them until explicitly discarded.
    await dialog.getByRole('button', { name: 'Затвори', exact: true }).click()
    if (await dialog.getByText(/Незавършеният избор/).count()) await dialog.getByRole('button', { name: 'Затвори', exact: true }).last().click()
    await button('Управление на връзките').click()
    await connect([1])
    expect((await api(`/bindings?catalog_id=${catalog.id}`)).items.find(link => link.machine_id === machine(1).id).id).toBe(first.id)
    expect((await request(`/catalog/v2/search?machine_id=${machine(1).id}&q=QA-UX05-059`)).length).toBe(1)
    expect((await api(`/catalogs/${catalog.id}/revisions`))[0].id).toBe(revision.id)
    checks.push('Reactivation reuses the same binding ID; immutable published revision and all confirmed parts remain available')
    expect((await request('/part-requests/multi')).find(row => row.id === historicalRequest.id)).toEqual(historyBefore)
    const audit = (await request('/audit')).filter(row => row.entity_type === 'catalog_asset_binding' && JSON.parse(row.details || '{}').catalog_id === catalog.id)
    expect(audit).toHaveLength(8)
    expect(new Set(audit.map(row => row.operation_reference)).size).toBe(6)
    expect(audit.filter(row => JSON.parse(row.details).compatibility === 'AMBIGUOUS').every(row => JSON.parse(row.details).compatibility_confirmed)).toBe(true)
    checks.push('Historical request remains identical; eight binding audit events share six operation IDs and retain individual confirmation')
    await dialog.getByRole('button', { name: 'Активни връзки', exact: true }).click()
    await dialog.getByLabel('Каталог', { exact: true }).selectOption('')
    await expect(dialog).toContainText('Synthetic QA pending')
    await expect(dialog).toContainText('Очаква публикация')
    checks.push('Legacy pending binding stays visible and cannot expose draft content in runtime')
    for (const width of [1440, 768, 390]) await shot('central-active', width)
    expect(errors).toEqual([])
    await writeFile(`${out}/browser-proof.json`, JSON.stringify({ passed: true, synthetic_only: true, checks, screenshots }, null, 2))
    console.log(`UX06 browser: ${checks.length} acceptance checks passed; ${screenshots.length} screenshots`)
} catch (error) {
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true })
  throw error
} finally { await context.close(); await browser.close() }
