"""Native conversion UI on a newly created disposable loopback installation."""
from pathlib import Path

from run_catalog_durable_review_qa import main
from run_document_studio_qa import prepare

if __name__ == "__main__":
    raise SystemExit(main(scenario="official-fidelity", prepare=prepare,
        browser_script=Path(__file__).with_name("official_document_fidelity.mjs")))
