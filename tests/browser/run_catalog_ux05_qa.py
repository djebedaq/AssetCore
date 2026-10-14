from pathlib import Path

from run_catalog_durable_review_qa import main

if __name__ == "__main__":
    raise SystemExit(main(scenario="ux05", browser_script=Path(__file__).with_name("catalog_ux05.mjs")))
