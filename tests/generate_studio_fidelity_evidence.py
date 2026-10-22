"""Reproducible synthetic reference/Studio comparison through the real renderer.

Run on the isolated Linux converter host. No ORM session or business database is
opened. Approved reference bytes are read only, never rewritten.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path

import fitz
from app.document_studio import renderer
from app.document_studio.schemas import CompanyIdentity
from app.document_studio.starter_layouts import professional_layout
from app.documents.transfer_documents import CHECKLIST_CODES, studio_checklist_rows
from app.models import DocumentTemplate, DocumentTemplateVersion
from app.template_engine import render_docx
from PIL import Image, ImageDraw, ImageFont

CASES = {'TRANSFER_ISSUE': 'transfer-issue', 'TRANSFER_RETURN': 'transfer-return',
         'REPAIR_PROTOCOL': 'repair-protocol', 'PART_REQUEST': 'parts-request'}


def inputs(language, count, size):
    values, tables = renderer.synthetic_values(language, count)
    # Clearly synthetic identifiers: no source inventory, serial, person or part
    # number is copied into the generated QA business inputs.
    text = {'bg': 'Синтетично техническо описание за проверка на оформлението.',
        'en': 'Synthetic technical description for document layout verification.',
        'ru': 'Синтетическое техническое описание для проверки макета.'}[language] + ' '
    for code in values:
        values[code] = text * size
    values.update(DOCUMENT_NUMBER='SYNTHETIC-QA-001', CREATION_DATE='19.10.2026', MACHINE_NUMBER='SYNTHETIC-INVENTORY',
        MACHINE_NAME='SYNTHETIC QA EQUIPMENT', EQUIPMENT_TYPE='SYNTHETIC QA CATEGORY', MODEL='QA MODEL', BRAND='QA MANUFACTURER',
        MODEL_DISPLAY='QA MANUFACTURER / QA MODEL', MANUFACTURER='QA MANUFACTURER', BATCH_REFERENCE='SYNTHETIC-BATCH', SERIAL_NUMBER='SYNTHETIC-SERIAL', PRESSURE_BAR='500',
        LEFT_SIGNER_NAME='СИНТЕТИЧНО ИМЕ ЗА ПРОВЕРКА ' * size,
        RIGHT_SIGNER_NAME='СИНТЕТИЧНО ИМЕ НА ПРИЕМАЩ ' * size,
        LEFT_SIGNER_JOB_TITLE='Синтетична длъжност за проверка ' * size,
        RIGHT_SIGNER_JOB_TITLE='Синтетична длъжност на приемащ ' * size,
        LEFT_SIGNATURE='[[ASSETCORE_LEFT_SIGNATURE]]', RIGHT_SIGNATURE='[[ASSETCORE_RIGHT_SIGNATURE]]',
        PREPARER_NAME='SYNTHETIC QA PREPARER', PREPARER_JOB_TITLE='SYNTHETIC QA ROLE', SIGNATURE_STATUS='SYNTHETIC QA — UNSIGNED',
        DIAGNOSIS_DURATION='30 min', REPAIR_DURATION='1 h', TESTING_DURATION='15 min', TOTAL_WORK_DURATION='1 h 45 min',
        PARTICIPANT_TOTAL_DURATION='45 min', REPAIR_START='19.10.2026 08:00', REPAIR_END='19.10.2026 12:00',
        ACCEPTANCE_DATE='19.10.2026', COMPLETION_DATE='19.10.2026', APPROVAL_DATE='19.10.2026',
        REPAIR_REFERENCE='SYNTHETIC-REPAIR', CATALOG_REFERENCES='SYNTHETIC QA catalog reference')
    values.update(OWNERSHIP='SYNTHETIC QA', SOURCE_RETURN_REFERENCE='SYNTHETIC-QA-RETURN',
        LEFT_SIGNER_ORGANIZATION='SYNTHETIC QA UNIT', RIGHT_SIGNER_ORGANIZATION='SYNTHETIC QA UNIT',
        HANDED_OVER_NAME=values['LEFT_SIGNER_NAME'], ACCEPTED_BY_NAME=values['RIGHT_SIGNER_NAME'],
        APPROVED_BY_NAME=values['RIGHT_SIGNER_NAME'], APPROVED_BY_JOB_TITLE=values['RIGHT_SIGNER_JOB_TITLE'],
        REQUESTER_NAME=values['LEFT_SIGNER_NAME'], APPROVER_NAME=values['RIGHT_SIGNER_NAME'], DEPARTMENT='SYNTHETIC QA UNIT')
    technical = {
        'REPORTED_PROBLEM': ('Колебание на налягането при пробно натоварване.', 'Pressure fluctuation under a test load.', 'Колебания давления при испытательной нагрузке.'),
        'SYMPTOMS': ('Периодични пулсации на изпитвателния стенд.', 'Intermittent pulsation on the test bench.', 'Периодические пульсации на испытательном стенде.'),
        'CONDITION_BEFORE': ('Следи от теч около пробния уплътняващ възел.', 'Leak traces around the test seal assembly.', 'Следы утечки вокруг испытательного уплотнения.'),
        'REQUIRED_WORK': ('Проверка на уплътненията и почистване на пробния корпус.', 'Inspect seals and clean the test housing.', 'Проверить уплотнения и очистить испытательный корпус.'),
        'REMOVED_PARTS': ('Свален пробен комплект уплътнения за оглед.', 'Test seal set removed for inspection.', 'Испытательный комплект уплотнений снят для осмотра.'),
        'DIAGNOSTIC_CLEANING': ('Измит пробен корпус преди диагностиката.', 'Test housing washed before diagnosis.', 'Испытательный корпус промыт перед диагностикой.'),
        'DIAGNOSIS': ('Установено износване на синтетичния пробен комплект.', 'Wear recorded on the synthetic test set.', 'Зафиксирован износ синтетического испытательного комплекта.'),
        'REQUIRED_PARTS': ('Синтетичен QA комплект за изпитвателния възел.', 'Synthetic QA set for the test assembly.', 'Синтетический QA комплект для испытательного узла.'),
        'WORK_PERFORMED': ('Подменен QA комплект и сглобен пробен възел.', 'QA set replaced and test assembly rebuilt.', 'QA комплект заменён, испытательный узел собран.'),
        'TEST_DETAILS': ('Проба на стенд; записаното време за тест е 15 min.', 'Bench trial; recorded testing labor is 15 min.', 'Стендовое испытание; записанный труд на тест — 15 min.'),
        'CONDITION_AFTER': ('Стабилна работа на синтетичния изпитвателен стенд.', 'Stable operation on the synthetic test bench.', 'Устойчивая работа синтетического испытательного стенда.'),
        'FINAL_RESULT': ('Приключена синтетична QA проверка; няма реална машина.', 'Synthetic QA verification complete; no real machine.', 'Синтетическая QA проверка завершена; реального оборудования нет.'),
    }
    for code, labels in technical.items():
        values[code] = ('SYNTHETIC QA: ' + labels[('bg', 'en', 'ru').index(language)] + ' ') * size
    from types import SimpleNamespace
    issue = [{'code': code, 'condition': 'GOOD' if i % 2 else 'SATISFACTORY', 'length_m': 30 if code == 'cable' else None,
        'note': text * size if i == 4 else ''} for i, code in enumerate(CHECKLIST_CODES)]
    returned = [{**row, 'condition': 'FAULTY' if i == 2 else 'GOOD', 'note': text * size if i == 2 else ''} for i, row in enumerate(issue)]
    transfer = SimpleNamespace(issue_checklist=issue, return_checklist=returned)
    tables['EQUIPMENT_CHECKLIST'] = studio_checklist_rows(transfer, 'issue', language)
    tables['RETURN_CHECKLIST'] = studio_checklist_rows(transfer, 'return', language)
    for source in ('REQUEST_LINES', 'PARTS_USED'):
        tables[source] = [{'position': str(i), 'part_number': f'SYNTHETIC-QA-PART-{i:03}', 'description': text * size * (3 if i == count else 1),
            'quantity': str(i), 'unit': 'pcs', 'note': ''} for i in range(1, count + 1)]
    tables['REPAIR_EVENTS'] = [{'date': '19.10.2026', 'event_type': 'SYNTHETIC QA', 'description': text * size} for _ in range(count)]
    tables['REPAIR_PARTICIPANTS'] = [{'name': values['LEFT_SIGNER_NAME'], 'job_title': values['LEFT_SIGNER_JOB_TITLE'],
        'contribution': text, 'duration': '45 min'}]
    tables['REPAIR_ATTACHMENTS'] = []
    for i, row in enumerate(tables['REQUEST_LINES']):
        row['assembly'] = 'SYNTHETIC QA ASSEMBLY A' if i < count // 2 else 'SYNTHETIC QA ASSEMBLY B'
    return values, tables


def image(text, size):
    image = Image.new('RGB', size, 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((1, 1, size[0]-2, size[1]-2), fill='#17314f', width=3)
    large = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 64)
    small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
    draw.text((size[0] / 2, size[1] / 2 - 15), 'QA', font=large, fill='white', anchor='mm')
    draw.text((size[0] / 2, size[1] / 2 + 35), 'SYNTHETIC', font=small, fill='white', anchor='mm')
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def pages(pdf, directory, prefix):
    images = []
    for stale in directory.glob(prefix + "-page-*.png"):
        stale.unlink()
    with fitz.open(stream=pdf, filetype='pdf') as document:
        for i, page in enumerate(document, 1):
            target = directory / f'{prefix}-page-{i}.png'
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(target)
            images.append(target)
    return images


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    references = Path('backend/resources/templates')
    reports = []
    for workflow, folder in CASES.items():
        destination = output / folder
        destination.mkdir(parents=True, exist_ok=True)
        reference = references / f"{workflow.lower()}-bg-v{'6' if workflow == 'REPAIR_PROTOCOL' else '3'}.docx"
        reference_hash = hashlib.sha256(reference.read_bytes()).hexdigest()
        for language, count, size, label in [('bg', 1, 1, 'short'), ('bg', 5, 2, 'medium'), ('bg', 30, 5, 'long'), ('en', 5, 1, 'medium'), ('ru', 5, 1, 'medium')]:
            values, tables = inputs(language, count, size)
            if workflow == 'TRANSFER_RETURN':
                tables['EQUIPMENT_CHECKLIST'] = tables['RETURN_CHECKLIST']
            identity = CompanyIdentity(legal_name='SYNTHETIC QA ONLY', address='Synthetic QA address',
                primary_logo_id=1, secondary_logo_id=2).model_dump()
            images = {str(i): {'content': base64.b64encode(raw).decode(), 'sha256': renderer.digest(raw)}
                for i, raw in [(1, image('QA LOGO', (240, 200))), (2, image('QA IMAGE', (200, 240)))]}
            manifest = {'renderer': 1, 'document_type': workflow, 'language': language,
                'layout': professional_layout(workflow, language, identity, {1: (240, 200), 2: (200, 240)}).model_dump(), 'company': {'revision': 1, 'identity': identity}, 'images': images}
            if workflow == 'PART_REQUEST' and label != 'short':
                next(b for b in manifest['layout']['blocks'] if b['type'] == 'dynamic_table')['group_by'] = 'assembly'
            docx = renderer.render(manifest, values, tables)
            pdf = renderer.pdf_required(docx)
            stem = f'{language}-{label}'
            (destination / f'{stem}.docx').write_bytes(docx)
            (destination / f'{stem}.pdf').write_bytes(pdf)
            actual_pages = pages(pdf, destination, stem)
            # Reference template is filled with the same synthetic data, using
            # the existing legacy engine, without changing the controlled file.
            reference_pages = []
            if language == 'bg':
                for stale in destination.glob(f'comparison-{stem}-page-*.png'):
                    stale.unlink()
                old_values = {**values, "LEFT_SIGNATURE": "________________", "RIGHT_SIGNATURE": "________________", "CONDITION_LABEL": {"bg": "Общо състояние", "en": "Overall condition", "ru": "Общее состояние"}[language]}
                for i, row in enumerate(tables['EQUIPMENT_CHECKLIST'], 1):
                    old_values[f'CHECK_{i}'] = ' · '.join(v for k in ('condition', 'measurement', 'note') if (v := row[k]))
                legacy_tables = {}
                for source, keys in renderer.TABLE_KEYS.items():
                    legacy_tables[source] = [list(keys)] + [[r.get(key, '') for key in keys] for r in tables[source]]
                template = DocumentTemplate(document_type=workflow, code='SYNTHETIC_REFERENCE')
                version = DocumentTemplateVersion(template=template, language='bg', source_content=reference.read_bytes(),
                    source_sha256=reference_hash, source_filename=reference.name, layout_contract={"reference_only": False}, required_fields=[])
                from docx import Document
                controlled = Document(io.BytesIO(reference.read_bytes()))
                for table in controlled.tables:
                    for row in table.rows:
                        if row.cells[0].text.strip() == '{{TABLE:REQUEST_LINES}}':
                            legacy_tables['REQUEST_LINES'][0] = [c.text for c in table.rows[0].cells]
                baseline = render_docx(version, old_values, legacy_tables)
                baseline_pdf = renderer.pdf_required(baseline)
                (destination / f'reference-{stem}.docx').write_bytes(baseline)
                (destination / f'reference-{stem}.pdf').write_bytes(baseline_pdf)
                reference_pages = pages(baseline_pdf, destination, f'reference-{stem}')
                for i in range(max(len(actual_pages), len(reference_pages))):
                    pairs = [Image.open(paths[i]).convert('RGB') if i < len(paths) else Image.new('RGB', (893, 1263), '#eef1f4') for paths in (reference_pages, actual_pages)]
                    combined = Image.new('RGB', (sum(p.width for p in pairs), max(p.height for p in pairs) + 30), 'white')
                    draw = ImageDraw.Draw(combined)
                    draw.text((10, 8), 'APPROVED REFERENCE + SYNTHETIC DATA', fill='black')
                    draw.text((pairs[0].width + 10, 8), 'STUDIO + SAME SYNTHETIC DATA', fill='black')
                    combined.paste(pairs[0], (0, 30))
                    combined.paste(pairs[1], (pairs[0].width, 30))
                    combined.save(destination / f'comparison-{stem}-page-{i + 1}.png')
            reports.append({'workflow': workflow, 'language': language, 'size': label, 'dynamic_rows': 10 if workflow.startswith('TRANSFER_') else count,
                'reference_sha256': reference_hash, 'docx_sha256': renderer.digest(docx), 'pdf_sha256': renderer.digest(pdf),
                'pages': len(actual_pages), 'reference_pages': len(reference_pages), 'reference_unchanged': reference_hash == renderer.digest(reference.read_bytes())})
        if not (destination / 'assessment.md').exists():
            (destination / 'assessment.md').write_text('Оценката се попълва след преглед на всички действителни PDF страници и сравнителни изображения.\n', encoding='utf-8')
    (output / 'render-report.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'cases': len(reports), 'pages': sum(r['pages'] for r in reports)}))


if __name__ == '__main__':
    main()
