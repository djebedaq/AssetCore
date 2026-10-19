"""Professional nested forms and explicit legacy restore on a disposable DB."""
from pathlib import Path

from run_catalog_durable_review_qa import main
from run_document_studio_editor_qa import prepare

if __name__ == '__main__':
    raise SystemExit(main(scenario='studio01b-final', prepare=prepare,
        browser_script=Path(__file__).with_name('document_studio_fidelity.mjs')))
