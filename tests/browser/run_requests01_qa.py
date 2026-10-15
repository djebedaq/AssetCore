"""Run requests acceptance with a new loopback-only SQLite QA database."""

from pathlib import Path

from run_catalog_durable_review_qa import main

if __name__ == "__main__":
    raise SystemExit(main(scenario="requests01", browser_script=Path(__file__).with_name("requests01.mjs")))
