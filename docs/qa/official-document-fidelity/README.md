# Проверка на вярността на официалните документи

Финалният release gate е описан в [release-readiness.md](release-readiness.md); до успешни пет CI jobs за окончателния PR head становището е **NOT READY**. Няма merge, deployment или Production activation.

Началният [архитектурен одит](architecture-audit.md) е записан преди имплементацията. [Източниците](source-of-truth.md), [рисковете](risk-register.md), [матрицата](document-comparison-matrix.md) и [вторият технически self-review](self-review.md) разграничават source, programmatic layout, approval snapshot, official archive и signatures.

Матрицата има 45 действителни legacy/Studio двойки: пет разновидности, BG/EN/RU и 1/5/30 реда. Запазени са 90 DOCX, 90 PDF, 150 page PNG и 75 side-by-side PNG. Всички 75 page pairs имат еднакъв текст и растер. [comparison-results.json](comparison-results.json) е агрегатът, а [visual-review.json](visual-review.json) описва прегледаните 51 различни raster hashes. При transfer броят checklist позиции идва от snapshot; 1/5/30 не означава измисляне на нови контролни позиции.

[Browser доказателствата](browser/README.md) включват 14 native checks и 52 screenshots, както и успешния стар schema-2 сценарий. [Preservation](preservation.json) съдържа реалните 757 baseline paths и hashes, без промени в защитените материали. [Security](security/README.md) запазва реалния dependency audit.

Генериране: `PYTHONPATH=backend:tests DATABASE_URL=sqlite:///:memory: python tests/generate_official_fidelity_evidence.py` на изолиран Linux host с действителния приложен converter. Проверка: `PYTHONPATH=backend python tests/verify_official_fidelity_evidence.py`. Частните предоставени DOCX и техните рендери не са включени.
