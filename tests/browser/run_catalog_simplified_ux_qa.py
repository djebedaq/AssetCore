"""03C browser acceptance: local OEM original, post-extraction control only."""
import argparse
import hashlib
from pathlib import Path

from run_catalog_durable_review_qa import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("expected", type=Path)
    args = parser.parse_args()
    if hashlib.sha256(args.pdf.read_bytes()).hexdigest() != "e9540c2af79802d000f186381c403dfbca6ae6b58ecb6cb13b9ecec862558e42":
        raise SystemExit("QA original SHA-256 mismatch")
    raise SystemExit(main(scenario="adaptive", pdf_path=args.pdf.resolve(), expected_path=args.expected.resolve(),
        browser_script=Path(__file__).with_name("catalog_simplified_ux.mjs")))
