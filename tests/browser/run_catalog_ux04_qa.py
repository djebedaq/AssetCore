"""UX04 browser acceptance; always creates a new isolated local QA database."""

from pathlib import Path

from run_catalog_durable_review_qa import main

if __name__ == "__main__":
    raise SystemExit(main(scenario="ux04", browser_script=Path(__file__).with_name("catalog_ux04.mjs")))
