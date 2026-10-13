# 03D FINAL — current combined-code evidence

Main includes merged #105 (`0c6101d`); #104 integrates it through `6b84483` and
retains all four remaining reliability fixes. Product code is frozen at `cb4e4a3`;
subsequent changes are QA/documentation. `implementation.json` and extraction
reports bind normalized module hashes to the current implementation.

The parent directory's original corpus/CI/browser files are **historical**. The
current assessment is [../release-readiness.json](../release-readiness.json).
Every PASS uses these new results or the current PR's CI. The final HEAD's checks
must all pass: [PR #104 checks](https://github.com/djebedaq/AssetCore/pull/104/checks).
Draft status remains mandatory regardless of the limited-scope GO recommendation.

| Evidence | Property proved |
|---|---|
| corpus-summary.json / corpus-comparison.json | Eight real cases, 24 pages, all five fields/multiplicity/SHA/page, 611 exact, original blanks retained |
| d13-linux-exact.json | Three new Linux repetitions, each 20+10 exact with provenance |
| d13-concurrency-exact.json | Two real concurrent OCR workers, exact 20 each; tree metrics and cgroup counters |
| live-capacity-exact.json | Independent controllers: two admitted/third busy; SIGKILL with active Tesseract, no orphans, same-slot native recovery |
| browser-synthetic.json | Eleven Edge checks: publication, immutable reopen, two tabs, failed inspection/late Blob lifecycle |
| browser-multipage.json | 1/4/7 lists, middle disconnect, refresh, single retry, distinct durable candidates |
| browser-d13.json | Seven Edge checks, exact 30, human-edit persistence/re-extraction; no D13 publication |
| postgres.json / ci.json | Current migrated PG/SQLite/constraints, encrypted ledger restore, full tests and final-HEAD checks |
| security.json / fault-injection.json / concurrency.json | Explicit tested boundaries and NOT RUN exclusions |
| performance.json | Bounded QA metrics, sampled RSS versus cgroup charge; no production P95/soak claim |
| screenshot-manifest.json | Four fresh real Edge screenshots, synthetic only |

Raw OEM reports/images, original PDFs, temporary databases and QA keys stay private
and ignored. No control data is available to extraction. Controls are loaded only
by the separate post-extraction comparison commands.

## Reproduce in development / disposable QA only

Use `.github/workflows/check.yml` for full pytest/PG/restore, dependency/SBOM/release
and exact-image document/runtime checks. Local equivalents:

```text
python -m ruff check backend/app backend/alembic backend/scripts scripts tests
python backend/scripts/validate_migration_history.py --require-all-protected
python backend/scripts/validate_authorization_inventory.py
python -m pytest -q -m "not postgres" --durations=10
node frontend/node_modules/vitest/vitest.mjs run --root frontend --maxWorkers=1
```

Within `frontend`: `pnpm typecheck`, `pnpm lint`, `pnpm build`. Browser launcher
requires the installed local Playwright module/Edge channel; Windows D13 OCR uses
the existing local CLI/model paths. It creates a new SQLite DB, random QA credentials
and loopback server, isolated from production.

```text
python tests/browser/run_catalog_final_acceptance_qa.py synthetic
python tests/browser/run_catalog_final_acceptance_qa.py multipage
python tests/browser/run_catalog_final_acceptance_qa.py d13 --pdf <local-original.pdf> --expected <local-expected.json>
```

Linux extraction uses a non-root, read-only production-oriented QA image,
`--rm --init --network none --cpus 2 --memory 1g --memory-swap 1g --pids-limit 64`,
`--cap-drop ALL --security-opt no-new-privileges:true`, private `/tmp` tmpfs 192 MiB.
Mount current app/QA scripts read-only, original PDF read-only and private output
writable. Hide `/app/backend/resources/catalog` with an empty read-only tmpfs.
This run used the existing 03E runtime image with the entire current backend app
mounted read-only; CI separately built/tested the exact new commit image. Local
interrupted rebuild is recorded in `ci.json`, not reported as PASS.

```text
python scripts/catalog_oem_layout_qa.py extract --output <private-corpus.json>
python scripts/catalog_adaptive_pdf_qa.py extract <original.pdf> --pages 13,15 --runs 3 --output <private-d13.json>
python scripts/catalog_adaptive_pdf_qa.py concurrency <original.pdf> --page 13 --output <private-concurrent.json>
python scripts/catalog_capacity_qa.py <original.pdf> --output <private-live-capacity.json>
# Only after extraction finishes, in a separate host process:
python scripts/catalog_oem_layout_qa.py compare --report <private-corpus.json> --output <aggregate-corpus.json>
python scripts/catalog_adaptive_pdf_qa.py compare <private-d13.json> <expected.json> --output <aggregate-d13.json>
python scripts/catalog_adaptive_pdf_qa.py compare <private-concurrent.json> <expected.json> --output <aggregate-concurrent.json>
python scripts/catalog_adaptive_pdf_qa.py compare <private-live-capacity.json> <expected.json> --output <aggregate-live.json>
```

Live capacity gates only admission for deterministic contention; admitted controllers
run the real extractor and never consume expected records. Controlled SIGKILL targets
only the worker whose parent is the tool's own QA controller. Run exclusively in the
disposable bounded container; `--init` reaps descendants and `--rm` removes the runtime
even on a failed assertion.

No deployment, production operations, business approvals or merge were performed.
Hammelmann/P200E/X25 exact/unknown OEMs, long soak, external certification and unresolved
D13 48/38 publication remain outside the accepted automatic scope.
