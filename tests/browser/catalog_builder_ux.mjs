// Run against an isolated, authenticated Bulgarian QA session. Relationships
// are created through the UI only. The caller supplies the controlled D13 PDF;
// credentials and original manuals are deliberately absent from this fixture.
export async function catalogBuilderUx({ page, expect, pdfPath, screenshotDir, onHelpers }) {
  expect = expect.configure({ timeout: 60000 })
  const previews = []
  page.on('response', async response => {
    if (/\/artifacts\/\d+\/pages\/\d+\/preview$/.test(response.url())) {
      previews.push({ status: response.status(), type: response.headers()['content-type'], url: response.url().split('/api/')[1] })
    }
  })
  page.removeAllListeners('dialog')
  page.on('dialog', dialog => { void dialog.accept().catch(() => {}) })
  const button = name => page.getByRole('button', { name, exact: true })
  const shot = name => page.screenshot({ path: `${screenshotDir}/${name}.png`, fullPage: true })
  const decoded = async number => {
    const img = page.getByRole('img', { name: `PDF страница ${number}`, exact: true })
    await expect(img).toBeVisible()
    await img.evaluate(async image => { await image.decode(); if (image.naturalWidth < 1000) throw Error('Unreadable PDF render') })
  }
  const jump = async number => {
    await page.locator('.reader-toolbar input').fill(String(number))
    await page.locator('.reader-toolbar input').press('Enter')
    await decoded(number)
  }
  const assign = async (role, numbers, upload = false) => {
    await expect(button('Добави страница')).toBeEnabled()
    await button(role === 'scheme' ? '+ Добави схема' : '+ Добави списък с части').click()
    if (upload) await page.getByLabel('Качи PDF', { exact: true }).setInputFiles(pdfPath)
    for (const number of numbers) {
      await jump(number)
      await button(role === 'scheme' ? 'Добави тази страница като схема' : 'Добави тази страница като списък с части').click()
      await expect(page.getByText(`Страница ${number} е добавена: ${role === 'scheme' ? 'Схема' : 'Списъци с резервни части'}`, { exact: true })).toBeVisible()
    }
  }
  const closeSource = () => page.locator('.source-selection').getByRole('button', { name: 'Затвори', exact: true }).click()
  const task = name => page.locator('.page-workflow nav').getByRole('button', { name, exact: true }).click()
  const point = async (position, x, y) => {
    const select = page.locator('.builder-scheme-details select').last()
    await select.selectOption(String(position))
    await button('Точка').click()
    const canvas = page.locator('.builder-scheme-canvas')
    const box = await canvas.boundingBox()
    const count = await page.locator('.builder-hotspot-list button').count()
    await canvas.click({ position: { x: box.width * x, y: box.height * y } })
    await expect(page.locator('.builder-hotspot-list button')).toHaveCount(count + 1)
    await expect(button('Точка')).toBeEnabled()
  }
  const extract = async count => {
    await task('Части')
    await button('Извлечи резервните части').click()
    const confirm = button('Потвърди избраните части')
    await expect(confirm).toBeEnabled({ timeout: 120000 })
    await expect(page.locator('.guided-parts tbody tr')).toHaveCount(count)
    await confirm.click()
    await expect(confirm).toBeDisabled()
    await page.locator('.guided-parts').getByRole('button', { name: 'Затвори', exact: true }).click()
    await task('Маркиране')
    await page.locator('.builder-scheme-canvas img').evaluate(image => image.decode())
    await button('Цяла страница').click()
  }
  const finishPage = async () => {
    await expect(page.locator('.wizard-position-list').getByText('Без зона', { exact: true })).toHaveCount(0)
    await button('Към страницата').click()
    await expect(page.getByText('✓ Страницата е завършена', { exact: true })).toBeVisible()
  }
  const reference = async name => page.locator('.reference-sidebar nav').getByRole('button', { name: new RegExp(name) }).click()
  const scheme = async number => {
    const option = page.locator('.builder-workspace > label select option').filter({ hasText: new RegExp(`\\b${number}\\b`) })
    await page.locator('.builder-workspace > label select').selectOption(await option.getAttribute('value'))
    await page.locator('.builder-scheme-canvas img').evaluate(image => image.decode())
    await button('Цяла страница').click()
  }
  const helpers = { point, finishPage, assign, closeSource, extract, reference, shot, jump, decoded, scheme, previews }
  onHelpers?.(helpers)
  await button('Каталожен конструктор').click()
  await button('Нов каталог').click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Име на каталога', { exact: true }).fill('D13 QA')
  await dialog.getByRole('combobox').selectOption({ label: 'Водоструйни машини с високо налягане' })
  await dialog.getByRole('button', { name: 'Продължи', exact: true }).click()
  for (const name of ['Reference A QA', 'Reference B QA', 'Reference C QA']) {
    await page.getByLabel('Референция', { exact: true }).fill(name)
    await button('Добави референция').click()
    await expect(page.getByLabel('Референция', { exact: true })).toHaveValue('')
  }
  await reference('Reference A QA')
  await button('Добави страница').click()
  await assign('scheme', [22], true)
  for (const number of [1, 43, 86]) { await jump(number); await shot(`pdf-${number}`) }
  await button('Предишна PDF страница').click(); await decoded(85)
  await button('Следваща PDF страница').click(); await decoded(86)
  await button('Увеличи').click(); await button('Намали').click()
  await closeSource()
  await assign('list', [23, 25])
  await button('Добави и като схема').click()
  await expect(page.getByRole('button', { name: 'Премахни страница 25: Схема', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Премахни страница 25: Схема', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Премахни страница 25: Схема', exact: true })).toHaveCount(0)
  await shot('source-summary')
  await closeSource()
  await extract(5)
  await shot('parts-and-mapping')
  for (const [position, x, y] of [[1, .177, .708], [2, .510, .708], [3, .790, .708]]) await point(position, x, y)
  const geometry = await page.locator('.builder-hotspot').first().evaluate(node => ({ width: parseFloat(node.style.width), height: parseFloat(node.style.height), visible: node.getBoundingClientRect().width }))
  expect(geometry.width).toBe(.2); expect(geometry.height).toBe(.2); expect(geometry.visible).toBeLessThan(4)
  await shot('precision-points')
  await finishPage()
  await button('Добави страница').click()
  await assign('scheme', [22, 24]); await closeSource()
  await assign('list', [25]); await closeSource()
  await extract(2)
  await scheme(24)
  await point(1, .325, .200); await point(2, .477, .360)
  await finishPage()
  await reference('Reference B QA'); await button('Добави страница').click()
  await assign('scheme', [22, 24]); await closeSource()
  await assign('list', [23, 25]); await closeSource()
  await extract(5)
  for (const [position, x, y] of [[1, .177, .708], [2, .510, .708], [3, .790, .708]]) await point(position, x, y)
  await finishPage()
  await reference('Reference C QA'); await button('Добави страница').click()
  await assign('scheme', [24]); await closeSource()
  await assign('list', [25]); await closeSource()
  await extract(2)
  await point(1, .325, .200); await point(2, .477, .360)
  await finishPage()
  await shot('completed-references')
  expect(previews.length).toBeGreaterThan(10)
  for (const response of previews) { expect(response.status).toBe(200); expect(response.type).toContain('image/png') }
  return { ...helpers, geometry }
}

export async function catalogBuilderUxCompletion({ page, expect, helpers: h, machineLabel, bindingLabel }) {
  expect = expect.configure({ timeout: 60000 })
  const button = name => page.getByRole('button', { name, exact: true })
  if (await button('Към страницата').isVisible()) await button('Към страницата').click()
  await h.reference('Reference C QA')
  await page.locator('.page-workflow nav').getByRole('button', { name: 'Маркиране', exact: true }).click()
  await page.locator('.builder-scheme-canvas img').evaluate(image => image.decode())
  await button('Цяла страница').click()
  await page.locator('.builder-scheme-details select').last().selectOption('1')
  await button('Правоъгълник').click()
  const box = await page.locator('.builder-scheme-canvas').boundingBox()
  await page.mouse.move(box.x + box.width * .324, box.y + box.height * .199)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * .354, box.y + box.height * .229)
  await page.mouse.up()
  await expect(page.locator('.builder-hotspot-list button')).toHaveCount(3)
  await expect(button('Правоъгълник')).toBeEnabled()
  await page.locator('.builder-hotspot-list button').last().click()
  const handle = await page.locator('.builder-hotspot.draft .builder-hotspot-handle').boundingBox()
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
  await page.mouse.down()
  await page.mouse.move(handle.x + handle.width / 2 - box.width * .029, handle.y + handle.height / 2 - box.height * .029)
  await page.mouse.up()
  await expect(button('Правоъгълник')).toBeEnabled()
  const tiny = page.locator('.builder-hotspot.draft')
  expect(await tiny.evaluate(node => [parseFloat(node.style.width), parseFloat(node.style.height)])).toEqual([.2, .2])
  const target = await tiny.boundingBox()
  await page.mouse.click(target.x - 5, target.y)
  await tiny.focus(); await tiny.press('ArrowRight')
  await button('Запази геометрията').click()
  await expect(button('Правоъгълник')).toBeEnabled()
  await h.shot('precision-rectangle-final')
  await h.finishPage()
  await h.reference('Reference B QA'); await button('Добави страница').click()
  await h.assign('scheme', [10]); await h.closeSource()
  await h.assign('list', [11]); await h.closeSource()
  await h.extract(19)
  // Printed labels visually checked against the supplied controlled drawing.
  // These are UI test coordinates, never trusted/generated product geometry.
  const coordinates = [[1,.59344,.76928],[2,.79372,.67163],[3,.61530,.44487],[7,.59888,.12669],
    [9,.38430,.63758],[10,.55132,.39905],[12,.32187,.32391],[13,.47906,.71905],[15,.45593,.24167],
    [16,.23196,.52919],[17,.20595,.61425],[22,.73654,.36260],[32,.48343,.34060],[40,.76369,.60964],
    [58,.73531,.51318],[61,.76030,.56143],[62,.64646,.82887],[63,.61547,.39892],[65,.71227,.89003]]
  for (const coordinate of coordinates) await h.point(...coordinate)
  await h.shot('dense-chassis-points'); await h.finishPage()
  await button('Публикуване').click()
  await expect(page.getByText('Готова за публикуване', { exact: true })).toBeVisible()
  await h.shot('review-publish'); await button('Публикувай каталог').click()
  await expect(page.getByText('Каталогът е публикуван.', { exact: true })).toBeVisible()
  await page.locator('.builder-row').filter({ hasText: bindingLabel }).getByRole('button', { name: 'Добави актив', exact: true }).click()
  await button('Каталог резервни части').click()
  await page.locator('.catalog-v2-machine select').first().selectOption({ label: machineLabel })
  await expect(page.locator('.catalog-v2-parts tbody tr')).toHaveCount(5)
  await page.locator('.catalog-v2-diagram-viewport img').evaluate(image => image.decode())
  await page.locator('.catalog-v2-diagram-tabs').first().getByRole('button', { name: 'Страница 2', exact: true }).click()
  await expect(page.locator('.catalog-v2-parts tbody tr')).toHaveCount(2)
  await expect(page.locator('.catalog-v2-diagram-tabs').nth(1).getByRole('button')).toHaveCount(2)
  await page.locator('.catalog-v2-diagram-tabs').nth(1).getByRole('button').nth(1).click()
  await page.locator('.catalog-v2-diagram-viewport img').evaluate(image => image.decode())
  await expect(page.locator('.catalog-v2-hotspot')).toHaveCount(2)
  await h.shot('runtime-a2-scheme2')
  await page.locator('.catalog-v2-machine select').nth(1).selectOption({ label: 'Reference B QA · 24' })
  await expect(page.locator('.catalog-v2-parts tbody tr')).toHaveCount(5)
  await page.locator('.catalog-v2-diagram-tabs').first().getByRole('button', { name: 'Страница 2', exact: true }).click()
  await expect(page.locator('.catalog-v2-parts tbody tr')).toHaveCount(19)
  await expect(page.locator('.catalog-v2-hotspot')).toHaveCount(19)
  await h.shot('runtime-dense-chassis')
  return { parts: 33, logicalPages: 5, references: 3, densePositions: 19, rectangleSize: .002 }
}
