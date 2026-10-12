# Catalog Builder 03D — QA evidence

Baseline: `1bdb74b1c6d78d99ac4072690b66b5bf7b8d6be0`; PRs 101/102/103 are ancestors.

Initial audit matrix (prior-stage evidence is not a new 03D PASS):

| Requirement | Existing evidence | New confirmation |
|---|---|---|
| Exact D13 fields/provenance | 03B/03C Linux reports, three runs | Three new isolated Linux runs; Edge workflow |
| Synthetic publication / responsive UX | 03C Edge 8 checks | Repeat current code; extend hotspot lifecycle / published reopen |
| N=1/4/7, context, failed middle | Multipage backend/frontend/PG tests | Full CI, browser N-page scenario |
| Durable decisions / corrections / direct API gate | 03A/03B SQLite + PG regressions | Full CI, fault injection, browser concurrency |
| Cross-web-process capacity | Only same-process thread benchmark | **Reproduced FAIL**: three processes enter a two-slot runtime; regression + OS lease fix |
| Process-tree cleanup / budgets | Unix timeout/crash tests + image smoke | Repeat Linux, bounded contention / fault measurements |
| Review source switching / LINK_EXISTING | Final 03C component + Edge scenario | Repeat browser and lifecycle audit |
| Migration / historical integrity / PARTS-DOC | Full CI, source fingerprints | Full CI, exact encrypted ledger backup/restore |
| Security / SBOM / release image | Existing release verifier + CI | Current dependency audits / release verifier / Docker CI |
| Other OEM accuracy | D13 only; local P200E/X25 available | Inventory and sampled extraction; no absent Falch/Hammelmann accuracy claim |

Stress budget established before execution: one disposable Linux container, at most
2 CPUs, 1 GiB RAM, 64 PIDs, 192 MiB private tmpfs; no more than three contending
clients and two admitted parser workers. Short synthetic blocking work is used for
capacity fault injection. D13 measured sequentially and with at most two workers.
No production resources. Original OEM bytes/rows/screenshots remain local and ignored;
only aggregate counts, hashes, measurements and synthetic screenshots may be committed.

## Final evidence

**Recommendation: NO-GO; PR #104 remains draft / NOT READY.** Five reproduced
product defects are fixed. D13 passes three Linux exact 30/30 runs, Edge and
bounded two-worker OCR. Other real OEM extraction fails: eight cases, 24 pages,
611 verified controls, 94 partial candidates (all lack quantity), zero exact
complete rows. Same payload/provenance and accuracy/quality on the 03C baseline.
No review/publication guard was relaxed and no OEM originals/rows were committed.

| Evidence | Scope |
|---|---|
| [release-readiness.json](release-readiness.json) | PASS/FAIL/BLOCKED/NOT RUN with proof |
| [ci.json](ci.json) | Completed CI revisions, local checks, skips, final-head check link |
| [d13-linux-exact.json](d13-linux-exact.json) | Three sequential exact-field comparisons |
| [d13-concurrency-exact.json](d13-concurrency-exact.json) | Two bounded real OCR workers, exact fields, cgroup counters |
| [performance.json](performance.json) | Timings, CPU, sampled RSS versus container memory; no small-sample P95 |
| [browser-synthetic.json](browser-synthetic.json) | 10 real Edge checks, publication and immutable reopen |
| [browser-d13.json](browser-d13.json) | 7 Edge checks, no OEM screenshot or publication claim |
| [browser-multipage.json](browser-multipage.json) | 1/4/7, interrupted middle, refresh, single retry |
| [corpus-summary.json](corpus-summary.json) | Real corpus failure and baseline equality |
| [corpus-comparison.json](corpus-comparison.json) | Per-page ordered fields, consumed occurrence/full-row metrics |
| [corpus-baseline-comparison.json](corpus-baseline-comparison.json) | Same independent comparator on 03C image |
| [postgres.json](postgres.json) | Encrypted restore, human correction, five ledger tables and protected anchors |
| [fault-injection.json](fault-injection.json), [concurrency.json](concurrency.json) | Fault/race scope and explicit not-run load |
| [security.json](security.json) | Audit areas, proof and limitations |
| [implementation.json](implementation.json) | Normalized module fingerprints; no schema/OCR change |
| [screenshot-manifest.json](screenshot-manifest.json) | Four real synthetic-only browser screenshots and hashes |

Full report: [CATALOG_BUILDER_03D_BG.md](../../CATALOG_BUILDER_03D_BG.md).
No production access, merge or deployment. Unsupported OEM acceptance requires
a separate bounded extraction follow-up after independent review.
