"""Studio C proposal lifecycle against a newly created isolated installation."""
from pathlib import Path

from run_catalog_durable_review_qa import main
from run_document_studio_editor_qa import prepare

if __name__ == '__main__':
    raise SystemExit(main(scenario='studio01c', prepare=prepare,
        browser_script=Path(__file__).with_name('document_studio_proposals.mjs')))
