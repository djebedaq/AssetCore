"""Real Studio B browser acceptance against a disposable loopback installation."""
from pathlib import Path

from run_catalog_durable_review_qa import main
from run_document_studio_qa import prepare as prepare_director


def prepare(factory, qa, password):
    import json

    from app.models import AssetCategory, Machine
    from PIL import Image, ImageDraw
    prepare_director(factory, qa, password)
    image = Image.new('RGB', (480, 160), '#183153')
    ImageDraw.Draw(image).text((30, 60), 'SYNTHETIC QA ONLY', fill='white')
    image.save(qa / 'synthetic-brand.png')
    with factory() as db:
        category = AssetCategory(code='QA_STUDIO_MACHINE', name_bg='SYNTHETIC QA',
            name_en='SYNTHETIC QA', name_ru='SYNTHETIC QA', capabilities=['HAS_PARTS_CATALOG'])
        db.add(category)
        db.flush()
        machine = Machine(inventory_number='QA-STUDIO-ONLY', name='SYNTHETIC QA ONLY',
            category=category.code, category_id=category.id, brand='SYNTHETIC QA', model='SYNTHETIC QA')
        db.add(machine)
        db.commit()
        machine_id = machine.id
    (qa / 'synthetic-catalog.json').write_text(json.dumps({
        'machine_id': machine_id,
    }), encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main(scenario='studio01b', prepare=prepare,
        browser_script=Path(__file__).with_name('document_studio_editor.mjs')))
