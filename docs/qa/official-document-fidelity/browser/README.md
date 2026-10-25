# Chromium evidence

`tests/browser/run_official_document_fidelity_qa.py` създава нова loopback QA инсталация и disposable SQLite база, изпълнява действителния frontend build срещу Linux backend с LibreOffice и стартира headless Chromium. Credentials са еднократни environment стойности и не се записват в доказателствата.

Матрица: четири бизнес типа, BG/EN/RU, 390/768/1440 px; hash-проверен source download, native editable copy, текстова редакция, actual DOCX/PDF previews за двата KK режима, публикация без автоматична активация, след това изрични QA activation и legacy restore. `browser-proof.json` и screenshots се добавят само след успешен реален run. Старият административен екран и останалите workflow/browser permissions се проверяват и от съществуващите CI browser сценарии.
