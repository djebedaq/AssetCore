import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createApiObjectUrl, downloadApiFile } from './api'
import { I18nProvider } from './i18n'
import { DocumentButtons } from './industrialUi'
import type { Locale } from './locale'

vi.mock('./api', async (importOriginal) => ({
  ...await importOriginal<typeof import('./api')>(),
  createApiObjectUrl: vi.fn(),
  downloadApiFile: vi.fn(),
}))

const createPreviewMock = vi.mocked(createApiObjectUrl)
const downloadMock = vi.mocked(downloadApiFile)

function renderButtons(format = 'pdf', locale: Locale = 'bg') {
  return render(
    <I18nProvider initialLocale={locale}>
      <DocumentButtons path="/generated-documents/44/download" filename={`protocol.${format}`} format={format} />
    </I18nProvider>,
  )
}

describe('DocumentButtons PDF preview recovery', () => {
  beforeEach(() => {
    createPreviewMock.mockReset()
    createPreviewMock.mockResolvedValue({ url: 'blob:n04-preview', mediaType: 'application/pdf' })
    downloadMock.mockReset()
    downloadMock.mockResolvedValue()
    const NativeURL = URL
    class TestURL extends NativeURL {
      static createObjectURL = vi.fn()
      static revokeObjectURL = vi.fn()
    }
    vi.stubGlobal('URL', TestURL)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('keeps the inline object and exposes independent safe open and download actions', async () => {
    renderButtons()

    await userEvent.click(screen.getByRole('button', { name: 'Преглед' }))
    const dialog = await screen.findByRole('dialog', { name: 'protocol.pdf' })
    const object = dialog.querySelector('object.generated-document-preview')
    const recovery = within(dialog).getByRole('note')
    const open = within(recovery).getByRole('link', { name: 'Отвори PDF отделно' })

    expect(createPreviewMock).toHaveBeenCalledWith('/generated-documents/44/download')
    expect(object).toHaveAttribute('data', 'blob:n04-preview')
    expect(object).toHaveAttribute('type', 'application/pdf')
    expect(object?.contains(recovery)).toBe(false)
    expect(object?.nextElementSibling).toBe(recovery)
    expect(open).toHaveAttribute('href', 'blob:n04-preview')
    expect(open).toHaveAttribute('target', '_blank')
    expect(open).toHaveAttribute('rel', 'noopener noreferrer')
    expect(within(recovery).getByRole('button', { name: 'Изтегли' })).toBeVisible()
  })

  it('does not depend on fallback children rendered by the PDF object', async () => {
    renderButtons()
    await userEvent.click(screen.getByRole('button', { name: 'Преглед' }))
    const dialog = await screen.findByRole('dialog', { name: 'protocol.pdf' })
    const object = dialog.querySelector('object.generated-document-preview')
    object?.replaceChildren()

    const recovery = within(dialog).getByRole('note')
    expect(within(recovery).getByText(/PDF прегледът е празен/)).toBeVisible()
    expect(within(recovery).getByRole('link', { name: 'Отвори PDF отделно' })).toBeVisible()
    expect(within(recovery).getByRole('button', { name: 'Изтегли' })).toBeVisible()
  })

  it('preserves the existing error and leaves no broken modal when preview fetching fails', async () => {
    createPreviewMock.mockRejectedValueOnce(new Error('isolated preview failure'))
    renderButtons()

    await userEvent.click(screen.getByRole('button', { name: 'Преглед' }))

    expect(await screen.findByText('Документът не може да бъде отворен за визуален преглед.')).toBeVisible()
    expect(screen.queryByRole('dialog', { name: 'protocol.pdf' })).not.toBeInTheDocument()
  })

  it('keeps non-PDF documents download-only', async () => {
    renderButtons('docx')

    expect(screen.queryByRole('button', { name: 'Преглед' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'DOCX' }))
    expect(downloadMock).toHaveBeenCalledWith('/generated-documents/44/download', 'protocol.docx')
    expect(createPreviewMock).not.toHaveBeenCalled()
  })

  it('revokes active Blob URLs on close and unmount', async () => {
    const view = renderButtons()
    await userEvent.click(screen.getByRole('button', { name: 'Преглед' }))
    await screen.findByRole('dialog', { name: 'protocol.pdf' })
    await userEvent.click(screen.getByRole('button', { name: 'Затвори' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'protocol.pdf' })).not.toBeInTheDocument())
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:n04-preview')

    createPreviewMock.mockResolvedValueOnce({ url: 'blob:n04-unmount', mediaType: 'application/pdf' })
    await userEvent.click(screen.getByRole('button', { name: 'Преглед' }))
    await screen.findByRole('dialog', { name: 'protocol.pdf' })
    view.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:n04-unmount')
  })

  it.each([
    ['bg', 'Отвори PDF отделно'],
    ['en', 'Open PDF separately'],
    ['ru', 'Открыть PDF отдельно'],
  ] as const)('localizes the independent recovery controls in %s', async (locale, openLabel) => {
    renderButtons('pdf', locale)
    await userEvent.click(screen.getByRole('button', { name: locale === 'bg' ? 'Преглед' : locale === 'en' ? 'Preview' : 'Предпросмотр' }))
    const dialog = await screen.findByRole('dialog', { name: 'protocol.pdf' })
    expect(within(dialog).getByRole('link', { name: openLabel })).toBeVisible()
  })
})
