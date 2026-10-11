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
const errors = [], extracted = [], checks = [], actions = []
let phase = 'login'
await page.exposeFunction('recordAction', action => { if (phase !== 'login') actions.push({phase, ...action}) })
await page.addInitScript(() => {
  document.addEventListener('click', event => { const e=event.target.closest('button,input[type=checkbox],summary'); if(e) window.recordAction({kind:'click', label:(e.getAttribute('aria-label') || e.textContent || '').trim().slice(0,100)}) }, true)
  document.addEventListener('keydown', event => { if(event.key==='Enter') window.recordAction({kind:'Enter',label:'page/form'}) }, true)
  document.addEventListener('change', event => { if(['select-one','file'].includes(event.target.type)) window.recordAction({kind:event.target.type,label:'selection/upload'}) }, true)
})
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
  await page.locator('.catalog-navigation').getByRole('button', { name: /Проверка на части/ }).click()
}
try {
  await page.goto(base)
  await page.locator('input[type=email]').fill(process.env.QA_EMAIL)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD)
  await button('Вход').click()
  await page.locator('.sidebar-navigation').waitFor()
  phase='catalog-and-pages'; await button('Каталожен конструктор').click()
  await button('Нов каталог').click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Име на каталога', { exact: true }).fill('QA — D13 adaptive extraction')
  await dialog.getByRole('combobox').selectOption({ label: 'Водоструйни машини с високо налягане' })
  await dialog.getByRole('button', { name: 'Продължи', exact: true }).click()
  await page.locator('.reference-sidebar').getByLabel('Референция', { exact: true }).fill('TCD13A.01 Chassis Assembly-2')
  await button('Добави референция').click()
  await expect(page.locator('.reference-sidebar').getByLabel('Референция', { exact: true })).toHaveValue('')
  await page.locator('.catalog-navigation').getByRole('button', { name: /PDF страници/ }).click()
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
  await button('Продължи').click()
  phase='recognize'; await page.locator('.guided-parts').getByRole('button', { name: 'Разпознай частите', exact: true }).click()
  await expect.poll(() => extracted.length, { timeout: 120000 }).toBe(2)
  await page.locator('.catalog-navigation').getByRole('button', { name: /Проверка на части/ }).click()
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
  expect(await page.locator('.guided-parts table').count()).toBe(1)
  expect(await page.locator('.guided-parts tbody tr').evaluateAll(rows => rows.map(row => Number(row.cells[5].querySelector('span').textContent.match(/\d+$/)[0])))).toEqual([...Array(20).fill(13),...Array(10).fill(15)])
  await page.locator('.part-original img').evaluate(image => image.decode())
  await expect(page.locator('.part-original .evidence-highlight')).toHaveCount(1)
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height:1000 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await expect.poll(() => page.locator('.unified-parts').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path:out+`/review-${width}.png`,fullPage:true })
    const field = page.getByLabel('Номер на част', {exact:true})
    await field.focus(); await expect(field).toBeFocused()
  }
  await page.setViewportSize({width:1440,height:1000})
  checks.push('One table retains 20/10 original source occurrences; responsive 390/768/1440 without page overflow; keyboard field focus')
  phase='edit-refresh'; const number = page.getByRole('textbox', { name: 'Номер на част', exact: true }).first()
  const original = await number.inputValue()
  await number.fill('QA-HUMAN-DRAFT')
  await expect(button('Потвърди избраните части')).toBeEnabled()
  await page.reload(); await reopen()
  await expect(page.getByRole('textbox', { name: 'Номер на част', exact: true }).first()).toHaveValue('QA-HUMAN-DRAFT')
  await page.getByRole('textbox', { name: 'Номер на част', exact: true }).first().fill(original)
  await expect(button('Потвърди избраните части')).toBeEnabled()
  checks.push('Human draft correction survives refresh; restored to inspected original before confirmation')
  phase='confirm-parts'; await button('Избери валидните видими редове').click()
  await button('Потвърди избраните части').click()
  await expect(button('Потвърди избраните части')).toBeDisabled()
  await expect.poll(async () => (await api(`/reference-pages/${referenceId}/parts`)).length).toBe(30)
  const catalog = (await api('/catalogs')).find(item => item.name_bg === 'QA — D13 adaptive extraction')
  const revision = (await api(`/catalogs/${catalog.id}/revisions`)).find(item => item.status === 'DRAFT')
  let readiness = await api(`/revisions/${revision.id}/publication-readiness`)
  expect(readiness.ready).toBe(false)
  expect(readiness.errors.filter(e => e.code === 'catalog_publication_source_review_required')).toHaveLength(2)
  checks.push('Thirty confirmed parts remain blocked until both original sources receive explicit human review')
  phase='reextract'; await page.locator('.catalog-navigation').getByRole('button', { name: /Разпознаване/ }).click()
  await page.locator('.guided-parts').getByRole('button', { name: 'Разпознай частите', exact: true }).click()
  await expect.poll(() => extracted.length, { timeout: 120000 }).toBe(4)
  await page.locator('.catalog-navigation').getByRole('button', { name: /Проверка на части/ }).click()
  await expect(page.locator('.guided-parts tbody tr')).toHaveCount(30)
  expect(extracted.slice(2).flatMap(p => p.rows.map(r => r.candidate_id))).toEqual(extracted.slice(0, 2).flatMap(p => p.rows.map(r => r.candidate_id)))
  expect(await api(`/reference-pages/${referenceId}/parts`)).toHaveLength(30)
  checks.push('Re-extraction keeps all candidate identities and creates no duplicate parts')
  phase='review-sources'; const panel = page.getByRole('region', { name: 'Проверка на всеки източник', exact: true })
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
  await page.locator('.catalog-navigation').getByRole('button', {name:/Маркери/}).click()
  await expect(page.locator('.hotspot-simple')).toBeVisible()
  await expect(page.getByText(/Ако позицията липсва/)).toBeVisible()
  await page.screenshot({path:out+'/hotspots-1440.png',fullPage:true})
  await page.locator('.catalog-navigation').getByRole('button', {name:/Публикуване/}).click()
  await expect(page.getByRole('button',{name:'Публикувай каталог',exact:true})).toBeDisabled()
  await page.screenshot({path:out+'/publication-blockers.png',fullPage:true})
  checks.push('Simplified hotspot workspace opens original; unresolved positions stay blocked; final readiness remains server-authoritative')
  expect(errors).toEqual([])
  await writeFile(out + '/results.json', JSON.stringify({ checks, actions, pageErrors: errors, productionAccess: false }, null, 2))
  console.log(JSON.stringify({ checks, pageErrors: errors }))
} catch (error) {
  await page.screenshot({ path: out + '/failure.png', fullPage: true }).catch(() => {})
  console.error(String(error.stack || error).replaceAll(process.env.QA_PASSWORD, '[redacted]'))
  process.exitCode = 1
} finally { await writeFile(out + '/metrics.json', JSON.stringify({ passed: !process.exitCode, checks, actions, pageErrors: errors, productionAccess: false }, null, 2)); await browser.close() }
