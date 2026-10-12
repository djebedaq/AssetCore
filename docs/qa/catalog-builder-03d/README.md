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
