# Реален Chromium — COMMERCIAL DOCS 01C

34 screenshots от реален интерфейс и реални HTTP действия, без mockups. Изолирана QA инсталация със синтетични потребители/предложения. Решенията и публикацията са изпълнени от администратор без owner статус; собственикът се използва само за подготовка на началните QA версии. Всички контролирани изображения са пояснителни приложения; не фирмен allowlist.

Проверени са submit с точно избрана стара версия, PNG attachment, коментари и XSS escaping, мобилно приемане/отказ, exact draft, CAS save, compactness, actual PDF, отделна публикация и проследяване от директора. Бутонът за търсене/филтри е реално разгънат и кирилското търсене е изпълнено.

## Screenshots

| Сценарий / език / ширина | Изображение |
|---|---|
| 01-director-template-version-1440 | [PNG](01-director-template-version-1440.png) |
| 01b-director-exact-version-pdf-1440 | [PNG](01b-director-exact-version-pdf-1440.png) |
| 02-director-proposal-dialog-1440 | [PNG](02-director-proposal-dialog-1440.png) |
| 03-director-filled-proposal-1440 | [PNG](03-director-filled-proposal-1440.png) |
| 04-director-image-proposal-1440 | [PNG](04-director-image-proposal-1440.png) |
| 05-director-submitted-1440 | [PNG](05-director-submitted-1440.png) |
| 06-admin-pending-proposals-1440 | [PNG](06-admin-pending-proposals-1440.png) |
| 07-admin-target-version-history-1440 | [PNG](07-admin-target-version-history-1440.png) |
| 07b-authorized-attachment-1440 | [PNG](07b-authorized-attachment-1440.png) |
| 10-admin-comment-390 | [PNG](10-admin-comment-390.png) |
| 08-admin-accepted-390 | [PNG](08-admin-accepted-390.png) |
| 11-proposal-editor-draft-1440 | [PNG](11-proposal-editor-draft-1440.png) |
| 14-compact-draft-1440 | [PNG](14-compact-draft-1440.png) |
| 13-actual-pdf-empty-logo-1440 | [PNG](13-actual-pdf-empty-logo-1440.png) |
| 12-proposal-published-version-link-1440 | [PNG](12-proposal-published-version-link-1440.png) |
| 09-admin-rejected-with-reason-390 | [PNG](09-admin-rejected-with-reason-390.png) |
| 15-admin-bg-proposal-status-390 | [PNG](15-admin-bg-proposal-status-390.png) |
| 15-admin-bg-proposal-status-768 | [PNG](15-admin-bg-proposal-status-768.png) |
| 15-admin-bg-proposal-status-1440 | [PNG](15-admin-bg-proposal-status-1440.png) |
| 15-admin-en-proposal-status-390 | [PNG](15-admin-en-proposal-status-390.png) |
| 15-admin-en-proposal-status-768 | [PNG](15-admin-en-proposal-status-768.png) |
| 15-admin-en-proposal-status-1440 | [PNG](15-admin-en-proposal-status-1440.png) |
| 15-admin-ru-proposal-status-390 | [PNG](15-admin-ru-proposal-status-390.png) |
| 15-admin-ru-proposal-status-768 | [PNG](15-admin-ru-proposal-status-768.png) |
| 15-admin-ru-proposal-status-1440 | [PNG](15-admin-ru-proposal-status-1440.png) |
| 15-director-bg-proposal-status-390 | [PNG](15-director-bg-proposal-status-390.png) |
| 15-director-bg-proposal-status-768 | [PNG](15-director-bg-proposal-status-768.png) |
| 15-director-bg-proposal-status-1440 | [PNG](15-director-bg-proposal-status-1440.png) |
| 15-director-en-proposal-status-390 | [PNG](15-director-en-proposal-status-390.png) |
| 15-director-en-proposal-status-768 | [PNG](15-director-en-proposal-status-768.png) |
| 15-director-en-proposal-status-1440 | [PNG](15-director-en-proposal-status-1440.png) |
| 15-director-ru-proposal-status-390 | [PNG](15-director-ru-proposal-status-390.png) |
| 15-director-ru-proposal-status-768 | [PNG](15-director-ru-proposal-status-768.png) |
| 15-director-ru-proposal-status-1440 | [PNG](15-director-ru-proposal-status-1440.png) |

## Действителен DOCX-derived PDF

[Редактируем DOCX](compact-missing-logo.docx) · [PDF](compact-missing-logo.pdf) · [PNG от PDF страница 1](compact-missing-logo-page-1.png). Празната лява logo клетка не съдържа printable placeholder. Това не е screenshot на canvas.

[Машинно проверим отчет](browser-proof.json). Всички нови контроли са с етикети, dialog focus остава в диалога, основната страница няма хоризонтално разширяване при 390/768/1440 px. Това е ограничена проверка за достъпност; не се твърди пълна WCAG сертификация.
