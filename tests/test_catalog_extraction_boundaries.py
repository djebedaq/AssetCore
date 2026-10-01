"""Generated layout and streaming resource boundaries; no business fixtures."""

import asyncio

import fitz
from app.catalog_admin.parts_extraction import extraction
from app.catalog_admin.parts_extraction.process import configuration
from app.catalog_admin.parts_extraction.tables import make_row
from app.catalog_admin.upload_guard import CatalogUploadGuard
from app.settings import settings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def test_two_independent_bom_columns_preserve_row_regions():
    with fitz.open() as pdf:
        page = pdf.new_page(width=900, height=500)
        for left in (30, 450):
            for x, label in [(0, 'Pos'), (55, 'Part No.'), (180, 'Description'), (340, 'Qty')]:
                page.insert_text((left + x, 80), label)
            for index in range(2):
                for x, value in [(0, str(index + 1 + (10 if left > 30 else 0))),
                                 (55, f'QA-{left}-{index}'), (180, 'QA synthetic item'), (340, '1.25')]:
                    page.insert_text((left + x, 110 + index * 30), value)
        result = extraction.extract_page(page, {**configuration(settings), 'ocr_enabled': False})
    assert len(result['rows']) == 4
    assert {row['payload']['position'] for row in result['rows']} == {'1', '2', '11', '12'}
    assert all(row['payload']['quantity'] == '1.25' for row in result['rows'])
    assert all(row['bbox'][2] - row['bbox'][0] < 420 for row in result['rows'])


def test_ruled_native_table_uses_actual_cell_geometry():
    with fitz.open() as pdf:
        page = pdf.new_page()
        xs = [30, 80, 200, 430, 500]
        ys = [70, 100, 130, 160]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for row, values in enumerate([['Pos', 'Part No.', 'Description', 'Qty'],
                                     ['1', 'QA-01', 'Synthetic housing', '2'],
                                     ['13A', 'QA-02', 'Synthetic seal', '1.5']]):
            for col, value in enumerate(values):
                page.insert_text((xs[col] + 4, ys[row] + 18), value)
        result = extraction.extract_page(page, configuration(settings))
    assert len(result['rows']) == 2
    assert all(row['method'] == 'NATIVE_TABLE' for row in result['rows'])
    assert result['rows'][0]['bbox'] == [30., 100., 500., 130.]


def test_chunked_upload_guard_closes_spooled_files_and_returns_configurable_limit(monkeypatch):
    from tempfile import SpooledTemporaryFile

    import starlette.formparsers as parsers

    opened = []
    def spool(*args, **kwargs):
        file = SpooledTemporaryFile(*args, **kwargs)
        opened.append(file)
        return file
    monkeypatch.setattr(parsers, 'SpooledTemporaryFile', spool)
    monkeypatch.setattr(settings, 'catalog_pdf_max_bytes', 1024)
    async def parse(request: Request):
        async with request.form():
            return JSONResponse({'unexpected': True})
    app = CatalogUploadGuard(Starlette(routes=[Route('/api/admin/catalog-builder/revisions/1/pdf', parse, methods=['POST'])]))
    body = b'--qa\r\nContent-Disposition: form-data; name="file"; filename="qa.pdf"\r\nContent-Type: application/pdf\r\n\r\n' + b'X' * (1200 * 1024) + b'\r\n--qa--\r\n'
    chunks = [body[index:index + 65536] for index in range(0, len(body), 65536)]
    sent = []
    async def receive():
        chunk = chunks.pop(0)
        return {'type': 'http.request', 'body': chunk, 'more_body': bool(chunks)}
    async def send(message):
        sent.append(message)
    asyncio.run(app({'type': 'http', 'asgi': {'version': '3.0'}, 'method': 'POST',
        'scheme': 'http', 'path': '/api/admin/catalog-builder/revisions/1/pdf', 'root_path': '',
        'query_string': b'', 'headers': [(b'content-type', b'multipart/form-data; boundary=qa')],
        'server': ('testserver', 80), 'client': ('127.0.0.1', 1), 'http_version': '1.1'}, receive, send))
    assert sent[0]['status'] == 413
    assert b'CATALOG_PDF_MAX_BYTES' in sent[1]['body']
    assert opened and all(file.closed for file in opened)


def test_incomplete_rows_preserve_evidence_instead_of_inventing_required_values():
    raw = {'position': '', 'part_number': 'QA-001', 'description': 'Synthetic item', 'quantity': '2'}
    row = make_row(raw, [20, 50, 400, 70], 'QA-001 Synthetic item 2', method='WORD_LAYOUT')
    assert row['payload']['position'] == '' and 'MISSING_POSITION' in row['warnings']
    raw = {'position': '1', 'part_number': '', 'description': 'Synthetic item', 'quantity': '?'}
    row = make_row(raw, [20, 50, 400, 70], '1 Synthetic item ?', method='WORD_LAYOUT')
    assert row['payload']['part_number'] == '' and row['payload']['quantity'] is None
    assert row['payload']['quantity_raw'] == '?' and row['confidence'] < .9


def test_parser_pool_bounds_parallel_resource_use_without_reading_source(monkeypatch):
    from threading import BoundedSemaphore

    import pytest
    from app.catalog_admin.parts_extraction import process
    from fastapi import HTTPException
    slots = BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(process, 'SLOTS', slots)
    with pytest.raises(HTTPException) as failure:
        process.extract(b'never parsed', 'page', 1, configuration(settings))
    assert failure.value.detail['code'] == 'catalog_extraction_busy'
