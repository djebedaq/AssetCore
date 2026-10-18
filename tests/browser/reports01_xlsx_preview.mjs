import { createRequire } from 'node:module'
import { readFile } from 'node:fs/promises'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_CHANNEL ? { channel: process.env.QA_BROWSER_CHANNEL } : {}) })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  await page.setContent(await readFile(`${process.env.QA_OUTPUT}/xlsx-preview.html`, 'utf8'))
  await page.screenshot({ path: `${process.env.QA_OUTPUT}/15-xlsx-content.png`, fullPage: true })
} finally { await browser.close() }
