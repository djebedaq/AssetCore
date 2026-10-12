# 03E QA evidence

These files contain aggregate counts, fingerprints, geometry classifications and resource measurements only. No OEM PDF/pages/cell text, raw extraction report, screenshot with OEM parts, secrets or database is committed.

- `corpus-linux-comparison.json`: independent post-extraction comparison for every physical page.
- `corpus-summary.json`: eight cases, 03C comparison inherited from unchanged PR104 diagnostics, controls/source hashes verified unchanged.
- `geometry-audit.json`: native text availability, local panel/band/column counts, why each page failed previously.
- `d13-linux-exact.json`: three Linux runs; controls absent from extractor runtime.
- `performance.json`: limits, runtime/module fingerprints and sampled native process-tree resources.
- `browser-d13.json`: real Edge/D13 scenario; original screenshots remain private.

The final GitHub Actions run and exact full-suite counts are recorded on the PR for its final HEAD. Extraction PASS never sets VERIFIED or bypasses publication readiness. Original Fussen blank/nonnumeric fields remain review requirements.
