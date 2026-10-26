import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url), modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright'
const { chromium } = require(modulePath), expect = require(modulePath + '/test').expect.configure({ timeout: 60000 })
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
const adminContext = await browser.newContext({ viewport: { width: 1440, height: 1000 }, hasTouch: true })
const directorContext = await browser.newContext({ viewport: { width: 1440, height: 1000 }, hasTouch: true })
const admin = await adminContext.newPage(), director = await directorContext.newPage()
const base = process.env.PUBLIC_BASE_URL, out = process.env.QA_OUTPUT, screenshots = [], checks = [], errors = []
for (const page of [admin, director]) { page.on('pageerror', e => errors.push(e.name)); page.on('dialog', dialog => void dialog.accept()) }
const b = (page, name) => page.getByRole('button', { name, exact: true })
const words = {
  bg: ['Настройки', 'Document Studio — Фирмени документи', 'Библиотека с шаблони', 'Предложения за промени', 'Добави коментар'],
  en: ['Settings', 'Document Studio — Company documents', 'Template library', 'Template change proposals', 'Add comment'],
  ru: ['Настройки', 'Document Studio — Документы компании', 'Библиотека шаблонов', 'Предложения об изменениях', 'Добавить комментарий'],
}
async function api(page, context, path, data, method = 'POST', expected = 200) {
  const csrf = (await context.cookies()).find(c => c.name === 'assetcore_csrf')?.value
  const response = await page.request.fetch(base + '/api' + path, { method: data === undefined ? 'GET' : method,
    ...(data === undefined ? {} : { data }), headers: { 'X-CSRF-Token': csrf || '' } })
  if (response.status() !== expected) throw new Error(`QA ${method} ${path}: ${response.status()}`)
  return response.json()
}
const ownerApi = (...args) => api(admin, adminContext, ...args)
const directorApi = (...args) => api(director, directorContext, ...args)
async function login(page, email) {
  await page.goto(base); await page.locator('input[type=email]').fill(email)
  await page.locator('input[type=password]').fill(process.env.QA_PASSWORD); await b(page, 'Вход').click()
  await expect(page.locator('.sidebar-navigation')).toBeVisible()
}
async function studio(page, locale = 'bg', section = 'center') {
  const w = words[locale]
  // Wait for session bootstrap before deciding whether the mobile menu is
  // needed. Checking visibility while the loading screen is mounted races.
  await page.locator('.mobile-toggle').waitFor({ state: 'attached' })
  if (await page.locator('.mobile-toggle').isVisible() && !await page.locator('.sidebar').evaluate(el => el.classList.contains('open'))) await page.locator('.mobile-toggle').click()
  await page.locator('.sidebar-navigation').getByRole('button', { name: w[0], exact: true }).click()
  await page.locator('.studio-settings-tabs').getByRole('button', { name: /Document Studio/ }).click()
  await expect(page.locator('.document-studio')).toBeVisible()
  await page.locator('.studio-navigation').getByRole('button', { name: section === 'center' ? new RegExp(w[3]) : w[2] }).click()
}
async function shot(page, name, width = 1440) {
  await page.setViewportSize({ width, height: 1000 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await page.evaluate(() => scrollTo(0, 0))
  const file = `${name}-${width}.png`; await page.screenshot({ path: `${out}/${file}`, fullPage: true }); screenshots.push(file)
}
async function selectProposal(page, title) {
  await page.locator('.studio-proposal-card').filter({ hasText: title }).click()
  await expect(page.locator('.studio-proposal-detail h3')).toContainText(title)
}
async function propose(title, attach = false) {
  const version = director.locator('.studio-version').last()
  await version.getByRole('button', { name: 'Предложи промяна', exact: true }).click()
  const dialog = director.getByRole('dialog', { name: 'Предложи промяна' })
  await expect(dialog).toContainText('Версия 1')
  if (attach) await shot(director, '02-director-proposal-dialog')
  await dialog.getByLabel('Заглавие на предложението').fill(title)
  await dialog.getByLabel('Подробно описание').fill('SYNTHETIC QA ONLY: Преместете номера под заглавието. Запазете защитените подписи, динамичните позиции и фирмените данни.')
  if (attach) {
    await shot(director, '03-director-filled-proposal')
    await dialog.getByLabel('Пояснителни изображения').setInputFiles(`${out}/synthetic-brand.png`)
    await expect(dialog.locator('img')).toBeVisible()
    await shot(director, '04-director-image-proposal')
    // Keyboard focus stays inside the real dialog.
    await director.keyboard.press('Tab'); await expect.poll(() => dialog.evaluate(el => el.contains(document.activeElement))).toBe(true)
  }
  await dialog.getByRole('button', { name: 'Изпрати предложение', exact: true }).click()
  await expect(director.locator('.document-studio > [role=status]')).toContainText('е записано успешно')
  await expect(director.locator('.studio-proposal-detail h3')).toContainText(title)
  await expect(director.locator('.studio-proposal-card').filter({ hasText: title })).toBeVisible()
  return (await directorApi('/studio/proposals')).items.find(p => p.title === title).id
}
try {
  await login(admin, process.env.QA_EMAIL)
  const template = await ownerApi('/studio/templates', { code: 'QA_STUDIO_C', document_type: 'PART_REQUEST',
    name_bg: 'SYNTHETIC QA Studio C', name_en: 'SYNTHETIC QA Studio C', name_ru: 'SYNTHETIC QA Studio C' }, 'POST', 201)
  const profile = await ownerApi('/studio/company')
  profile.identity.legal_name = 'SYNTHETIC QA COMPANY'
  await ownerApi('/studio/company', { expected_revision: profile.revision, identity: profile.identity }, 'PUT')
  const initialVersions = []
  for (let number = 1; number <= 2; number++) {
    const draft = await ownerApi(`/studio/templates/${template.id}/drafts`, { title: `SYNTHETIC QA source ${number}`, language: 'bg', design: 'professional' }, 'POST', 201)
    const preview = await ownerApi(`/studio/drafts/${draft.id}/preview`, { expected_revision: draft.revision, rows: 5 })
    initialVersions.push(await ownerApi(`/studio/drafts/${draft.id}/publish`, { expected_revision: draft.revision, receipt: preview.receipt, change_note: 'SYNTHETIC QA initial version' }, 'POST', 201))
  }
  await b(admin, 'Изход').click()
  await expect(admin.locator('input[type=email]')).toBeVisible()
  await login(admin, 'studio-admin@qa.invalid')
  const administrativeActor = await ownerApi('/auth/me')
  if (administrativeActor.role !== 'administrator' || administrativeActor.is_system_owner) throw new Error('QA review requires a non-owner administrator')
  await login(director, 'studio-director@qa.invalid'); await studio(director, 'bg', 'library')
  await director.locator('.studio-template-list button').filter({ hasText: 'SYNTHETIC QA Studio C' }).click()
  await expect(director.getByRole('button', { name: 'Нов шаблон', exact: true })).toHaveCount(0)
  await shot(director, '01-director-template-version')
  for (const [variant, title] of [['machine', 'Заявка към машина'], ['free', 'Свободна заявка']]) {
    await director.locator('.studio-version').last().getByRole('button', { name: `Провери и виж PDF · ${title}`, exact: true }).click()
    await expect(director.getByRole('dialog').locator('img').first()).toBeVisible()
    await shot(director, `01b-director-exact-version-${variant}-pdf`)
    await director.getByRole('dialog').getByRole('button', { name: 'Затвори', exact: true }).click()
  }
  const acceptedTitle = 'SYNTHETIC QA — компактна фирмена шапка'
  const acceptedId = await propose(acceptedTitle, true)
  await shot(director, '05-director-submitted')
  await director.getByLabel('Текст на коментара').fill('<script>window.proposalXss = true</script> SYNTHETIC QA comment')
  await b(director, 'Добави коментар').click()
  await expect(director.locator('.studio-proposal-timeline')).toContainText('<script>')
  if (await director.evaluate(() => window.proposalXss)) throw new Error('Proposal XSS executed')
  await b(director, 'Отвори засегнатия шаблон').click()
  const rejectedTitle = 'SYNTHETIC QA — предложение за отхвърляне'
  const rejectedId = await propose(rejectedTitle)
  await studio(admin)
  await expect(admin.locator('.studio-proposal-card')).toHaveCount(2)
  await admin.locator('.studio-proposal-filters summary').click()
  await admin.getByLabel('Търси предложение, шаблон или автор').fill('КОМПАКТНА')
  await expect(admin.locator('.studio-proposal-card')).toHaveCount(1)
  await admin.getByLabel('Търси предложение, шаблон или автор').fill('')
  await expect(admin.locator('.studio-proposal-card')).toHaveCount(2)
  await shot(admin, '06-admin-pending-proposals')
  await selectProposal(admin, acceptedTitle)
  await expect(admin.locator('.studio-proposal-detail')).toContainText('Има по-нова публикувана версия')
  await shot(admin, '07-admin-target-version-history')
  await admin.locator('.studio-evidence').click()
  await expect(admin.locator('.studio-evidence-full')).toBeVisible()
  await shot(admin, '07b-authorized-attachment')
  await admin.getByRole('dialog').getByRole('button', { name: 'Затвори', exact: true }).click()
  await admin.setViewportSize({ width: 390, height: 1000 })
  await admin.getByLabel('Текст на коментара').fill('SYNTHETIC QA admin: промените ще се проверят чрез реалния PDF.')
  await b(admin, 'Добави коментар').tap()
  await expect(admin.locator('.studio-proposal-timeline')).toContainText('SYNTHETIC QA admin')
  await shot(admin, '10-admin-comment', 390)
  await admin.getByLabel('Мотив за решението').fill('SYNTHETIC QA: прието за отделна редакция и проверка, без активиране.')
  await b(admin, 'Приеми').tap()
  await expect(admin.locator('.studio-proposal-detail .panel-title')).toContainText('Прието')
  await shot(admin, '08-admin-accepted', 390)
  if ((await ownerApi('/studio/templates')).find(t => t.id === template.id).versions.length !== 2) throw new Error('Acceptance published a template')
  await admin.getByLabel('Име на черновата', { exact: true }).fill('SYNTHETIC QA proposal exact-version draft')
  await b(admin, 'Създай чернова по предложението').tap()
  const editor = admin.locator('.visual-editor')
  await expect(editor).toBeVisible(); await shot(admin, '11-proposal-editor-draft', 1440)
  const linked = await ownerApi(`/studio/proposals/${acceptedId}`)
  const draftId = linked.drafts[0].draft_id, exact = await ownerApi(`/studio/drafts/${draftId}`)
  if (exact.base_version_id !== initialVersions[0].id) throw new Error('Exact target version was silently replaced')
  await editor.getByLabel('Автозапис', { exact: true }).uncheck()
  await editor.locator('.editor-density summary').click()
  await editor.getByLabel('Компактност на черновата', { exact: true }).selectOption('compact')
  await b(editor, 'Приложи към черновата').click()
  await b(editor, 'Запази промените').click()
  await expect(editor.getByRole('status')).toContainText('Потвърдено от сървъра')
  await shot(admin, '14-compact-draft')
  const response = admin.waitForResponse(r => r.url().endsWith(`/studio/drafts/${draftId}/preview`) && r.request().method() === 'POST')
  await b(editor, 'Провери и виж PDF').click()
  const actual = await (await response).json()
  if (!actual.report?.pages?.length) throw new Error('No actual PDF pages')
  await expect(editor.locator('.editor-pdf img')).toBeVisible()
  await shot(admin, '13-actual-pdf-empty-logo')
  for (const format of ['docx', 'pdf']) await writeFile(`${out}/compact-missing-logo.${format}`, Buffer.from(actual[format], 'base64'))
  for (const [i, p] of actual.report.pages.entries()) await writeFile(`${out}/compact-missing-logo-page-${i + 1}.png`, Buffer.from(p.png, 'base64'))
  await editor.getByLabel('Описание на промяната', { exact: true }).fill('SYNTHETIC QA proposal publication after actual PDF review')
  await b(editor, 'Публикувай нова версия').click()
  await expect(editor.getByRole('status')).toContainText('Публикувана неизменяема версия')
  await b(editor, 'Затвори').click()
  await admin.locator('.studio-navigation').getByRole('button', { name: /Предложения за промени/ }).click()
  await selectProposal(admin, acceptedTitle)
  await expect(admin.locator('.studio-proposal-timeline')).toContainText('Публикувана свързана версия')
  await shot(admin, '12-proposal-published-version-link')
  await selectProposal(admin, rejectedTitle)
  await admin.setViewportSize({ width: 390, height: 1000 })
  await expect(b(admin, 'Отхвърли')).toBeDisabled()
  await admin.getByLabel('Мотив за решението').fill('SYNTHETIC QA: предложената промяна не е необходима. Текущото оформление се запазва.')
  await b(admin, 'Отхвърли').tap()
  await expect(admin.locator('.studio-proposal-detail .panel-title')).toContainText('Отхвърлено')
  await shot(admin, '09-admin-rejected-with-reason', 390)
  const final = await ownerApi(`/studio/proposals/${acceptedId}`)
  if (final.status !== 'ACCEPTED' || final.events.at(-1).kind !== 'PUBLISHED') throw new Error('Proposal publication trace missing')
  const versions = (await ownerApi('/studio/templates')).find(t => t.id === template.id).versions
  if (versions.some(v => v.active)) throw new Error('QA template activated without explicit action')
  for (const original of initialVersions) if (versions.find(v => v.id === original.id).source_sha256 !== original.source_sha256) throw new Error('Original version bytes changed')
  checks.push('Director submitted exact-version proposal and safe image through UI; own comment escaped; authorized image enlarged')
  checks.push('Administrator accepted and rejected with reasons using touch at 390px; decisions did not publish or activate')
  checks.push('Exact old version cloned by explicit action; compact draft saved via CAS and previewed using real DOCX/PDF')
  checks.push('Separate UI publication appended linked version event; original source hashes and inactive selections retained')
  for (const [role, page, context] of [['admin', admin, adminContext], ['director', director, directorContext]]) for (const locale of ['bg', 'en', 'ru']) {
    await api(page, context, '/users/me/preferences', { preferred_language: locale }, 'PATCH')
    await page.reload(); await studio(page, locale); await selectProposal(page, acceptedTitle)
    await expect(page.locator('.studio-proposal-timeline')).toContainText(locale === 'bg' ? 'Публикувана свързана версия' : locale === 'en' ? 'Linked version published' : 'Опубликована связанная версия')
    for (const width of [390, 768, 1440]) await shot(page, `15-${role}-${locale}-proposal-status`, width)
    const inaccessible = await page.locator('.studio-proposal-detail').evaluate(root => [...root.querySelectorAll('input:not([type=hidden]),textarea,select')].filter(el => !el.labels?.length && !el.getAttribute('aria-label')).length)
    if (inaccessible) throw new Error('Unlabelled proposal control')
  }
  checks.push('BG/EN/RU admin/director status and publication history at 390, 768 and 1440; labelled controls and no document-level horizontal overflow')
  if (errors.length) throw new Error('Browser runtime errors')
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ passed: true, stage: 'COMMERCIAL-DOCS-01C', checks, screenshots, errors,
    accepted_proposal_id: acceptedId, rejected_proposal_id: rejectedId, exact_target_version_id: initialVersions[0].id,
    linked_draft_id: draftId, linked_published_version_id: final.events.at(-1).version_id, actual_pdf_pages: actual.report.page_count,
    no_activation: true, original_source_hashes_unchanged: true, administrative_actor_is_owner: false }, null, 2))
  console.log(JSON.stringify({ passed: true, checks: checks.length, screenshots: screenshots.length }))
} catch (error) {
  for (const [name, page] of [['admin', admin], ['director', director]]) await page.screenshot({ path: `${out}/failure-${name}.png`, fullPage: true }).catch(() => {})
  await writeFile(`${out}/failure-ui.txt`, await director.locator('body').innerText())
  await writeFile(`${out}/failure-studio-buttons.json`, JSON.stringify(await director.locator('.studio-settings-tabs button').evaluateAll(nodes => nodes.map(el => ({ text: el.textContent, hidden: !!el.closest('[inert],[aria-hidden=true]'), display: getComputedStyle(el).display }))), null, 2))
  await writeFile(`${out}/browser-proof.json`, JSON.stringify({ passed: false, checks, screenshots, errors, failure: error.message }, null, 2))
  throw error
} finally { await browser.close() }
