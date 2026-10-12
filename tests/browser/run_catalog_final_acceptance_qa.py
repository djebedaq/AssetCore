"""03D browser acceptance, each invocation in a new disposable local database."""

import argparse
import hashlib
from pathlib import Path

from run_catalog_durable_review_qa import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("synthetic", "multipage", "d13"))
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--expected", type=Path)
    args = parser.parse_args()
    if args.scenario == "d13":
        if not args.pdf or not args.expected:
            parser.error("D13 requires local --pdf and post-extraction --expected control")
        if hashlib.sha256(args.pdf.read_bytes()).hexdigest() != "e9540c2af79802d000f186381c403dfbca6ae6b58ecb6cb13b9ecec862558e42":
            raise SystemExit("QA original SHA-256 mismatch")
    names = {"synthetic": ("durable", "catalog_simplified_synthetic.mjs"),
        "multipage": ("final-multipage", "catalog_final_multipage.mjs"),
        "d13": ("adaptive", "catalog_simplified_ux.mjs")}
    scenario, script = names[args.scenario]
    raise SystemExit(main(scenario=scenario, pdf_path=args.pdf.resolve() if args.pdf else None,
        expected_path=args.expected.resolve() if args.expected else None,
        browser_script=Path(__file__).with_name(script)))
