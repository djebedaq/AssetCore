"""Real Studio B browser acceptance against a disposable loopback installation."""
from pathlib import Path

from run_catalog_durable_review_qa import main
from run_document_studio_qa import prepare as prepare_director


def prepare(factory, qa, password):
    from PIL import Image, ImageDraw
    prepare_director(factory, qa, password)
    image = Image.new('RGB', (480, 160), '#183153')
    ImageDraw.Draw(image).text((30, 60), 'SYNTHETIC QA ONLY', fill='white')
    image.save(qa / 'synthetic-brand.png')


if __name__ == '__main__':
    raise SystemExit(main(scenario='studio01b', prepare=prepare,
        browser_script=Path(__file__).with_name('document_studio_editor.mjs')))
