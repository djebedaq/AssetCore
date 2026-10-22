"""Verify saved real artifacts; no database, conversion or fixture writes."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import fitz
from generate_studio_fidelity_evidence import CASES, inputs
from lxml import etree


def normalized(value):
    return re.sub(r'[\s\u200b\u00ad]+', '', str(value))


def verify(root: Path):
    reports = json.loads((root / 'render-report.json').read_text(encoding='utf-8'))
    assert len(reports) == 20
    checked = []
    for row in reports:
        folder = root / CASES[row['workflow']]
        stem = f"{row['language']}-{row['size']}"
        content = (folder / (stem + '.docx')).read_bytes()
        pdf = (folder / (stem + '.pdf')).read_bytes()
        assert hashlib.sha256(content).hexdigest() == row['docx_sha256'], stem
        assert hashlib.sha256(pdf).hexdigest() == row['pdf_sha256'], stem
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            manifest = json.loads(package.read('assetcore/studio.json'))
            # Word tables, headings and cells retain native editable text.
            document = etree.fromstring(package.read('word/document.xml'))
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            native = normalized(''.join(document.xpath('//w:t/text()', namespaces=ns)))
            assert document.xpath('//w:tbl', namespaces=ns)
        count = {'short': 1, 'medium': 5, 'long': 30}[row['size']]
        size = {'short': 1, 'medium': 2, 'long': 5}[row['size']] if row['language'] == 'bg' else 1
        values, tables = inputs(row['language'], count, size)
        def blocks(items):
            for block in items:
                yield block
                for grid_row in block.get('grid_rows', []):
                    for cell in grid_row['cells']:
                        yield from blocks(cell['blocks'])
        fields = {b['field'] for b in blocks(manifest['layout']['blocks']) if b['type'] == 'field' and not b['field'].startswith('COMPANY_')}
        actual_fields = [field for field in fields if values.get(field) not in (None, '')]
        for field in actual_fields:
            assert normalized(values[field]) in native, (row['workflow'], stem, field)
        with fitz.open(stream=pdf, filetype='pdf') as pages:
            assert len(pages) == row['pages']
            text = normalized('\n'.join(page.get_text() for page in pages))
            for field in ('DOCUMENT_NUMBER', 'MACHINE_NUMBER', 'SERIAL_NUMBER'):
                assert normalized(values[field]) in text, (row['workflow'], stem, field)
            assert '[[ASSETCORE_' not in text
            for i, page in enumerate(pages, 1):
                assert (folder / f'{stem}-page-{i}.png').is_file()
                assert page.get_text().strip()
            if row['workflow'].startswith('TRANSFER_'):
                source = 'RETURN_CHECKLIST' if row['workflow'] == 'TRANSFER_RETURN' else 'EQUIPMENT_CHECKLIST'
                assert len(tables[source]) == 10
                for item in tables[source]:
                    assert normalized(item['component']) in text
            else:
                for item in tables['REQUEST_LINES' if row['workflow'] == 'PART_REQUEST' else 'PARTS_USED']:
                    assert normalized(item['part_number']) in text
        if row['language'] == 'bg':
            with fitz.open(folder / f'reference-{stem}.pdf') as reference:
                assert len(reference) == row['reference_pages']
                for i in range(1, len(reference) + 1):
                    assert (folder / f'reference-{stem}-page-{i}.png').is_file()
            for i in range(1, max(row['pages'], row['reference_pages']) + 1):
                assert (folder / f'comparison-{stem}-page-{i}.png').is_file()
        checked.append({'workflow': row['workflow'], 'case': stem, 'native_business_fields': sorted(actual_fields),
            'pdf_identity_and_dynamic_rows_present': True, 'all_pdf_pages_rasterized': True, 'pages': row['pages']})
    official = json.loads((root / 'official-workflow-proof.json').read_text(encoding='utf-8'))
    assert official['passed'] and len(official['cases']) == 4
    for row in official['cases']:
        folder = root / CASES[row['workflow']]
        for extension in ('docx', 'pdf'):
            assert hashlib.sha256((folder / f'official-synthetic.{extension}').read_bytes()).hexdigest() == row[extension + '_sha256']
        assert row['status'] == ('FINALIZED' if row['workflow'] == 'REPAIR_PROTOCOL' else 'SIGNED')
        assert row['archive_unchanged_after_profile_and_selection_change']
        with fitz.open(folder / 'official-synthetic.pdf') as pdf:
            assert len(pdf) == row['pages']
            for i in range(1, len(pdf) + 1):
                assert (folder / f'official-synthetic-page-{i}.png').is_file()
        if row['workflow'].startswith('TRANSFER_'):
            assert row['recorded_checklist_items'] == 10
        if row['workflow'] != 'REPAIR_PROTOCOL':
            assert row['graphic_signatures_in_original_cells']
            proof = json.loads((folder / 'long-signature-proof.json').read_text(encoding='utf-8'))
            assert proof['passed'] and proof['unsigned_had_no_signature_images'] and len(proof['placements']) == 2
            for extension in ('docx', 'pdf'):
                assert hashlib.sha256((folder / f'long-signed.{extension}').read_bytes()).hexdigest() == proof[extension + '_sha256']
        if row['workflow'] == 'PART_REQUEST':
            assert all(row[key] for key in ('catalog_image_bytes_preserved_through_signing',
                'studio_final_conversion_failure_rolled_back', 'approval_template_bytes_unchanged',
                'signed_kk_archive_unchanged_after_followup_profile_change'))
    restored = json.loads((root / 'legacy-restore/restore-proof.json').read_text(encoding='utf-8'))
    assert restored['passed'] and len(restored['transitions']) == 3
    assert [r['selection'] for r in restored['transitions']] == ['legacy-before', 'studio', 'legacy-restored']
    assert restored['transitions'][0]['template_id'] == restored['transitions'][2]['template_id']
    assert restored['transitions'][1]['template_id'] != restored['transitions'][0]['template_id']
    for row in restored['transitions']:
        assert row['unchanged']
        for extension, digest in row['archives'].items():
            assert hashlib.sha256((root / 'legacy-restore' / (row['selection'] + '.' + extension)).read_bytes()).hexdigest() == digest
    return {'passed': True, 'cases': checked, 'case_count': len(checked), 'pages': sum(r['pages'] for r in checked),
            'official_archives_checked': 4, 'long_signed_archives_checked': 3, 'restore_archives_checked': 3}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report = verify(args.root)
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}))
