# Регистър на дефектите и остатъчните рискове

| Приоритет | Причина / възпроизводим проблем | Корекция | Доказателство |
|---|---|---|---|
| High | Legacy base_version_id води до generic starter, различен от официалния документ | Контролиран native adapter; неизвестен source отказва | native contract tests, 45 реални сравнителни случая |
| High | Свободна KK може да получи машинно оформление | Два typed варианта в един manifest; backend избира от каноничния snapshot | variants tests, shared KK sequence / official archive test |
| High | Approval поглъща template грешка, archive после избира текущия source | Проверка и freeze преди counter; липсващи доказателства отказват | approval rollback test; historical immutable bytes test |
| High | Snapshot lines и live lines се свързват по различен ред | Един и същ стабилен ID ред | source review и request regression suite |
| High | Графичен signer може да се добави към KK без реална защитена позиция | Проверка за точно един marker преди създаване на signer/session | native KK signer rejection; transfer slot tests |
| Medium | Unapproved preview заобикаля избрания Studio source | Същият build_docx, actual variant и watermark | request preview regression suite |
| Medium | Неясен source download/actual layout и active badge | Read-only диагностика, отделен source download и actual PDF preview | diagnostics no-mutation/permissions test, Chromium |
| Medium | Диагностиката показваше KK programmatic номера и при native transfer | Ограничение до PART_REQUEST; отделен native_origin | native transfer diagnostics regression |
| Medium | Две legacy registry версии с еднакъв най-висок номер | Явен отказ вместо произволен избор | selection review / existing template tests |
| Medium | Изричен избор пренебрегва effective dates | Проверка и при explicit selection | template selection regression suite |
| Medium | Пълният HPWJ print vocabulary се използва и за други категории | Map само при точно съвпадащ пълен HPWJ snapshot; другите labels/length се запазват | custom category 2×3 language tests |
| Medium | Repair EN/RU таблици имаха BG headers | Общ преведен договор за бъдещо генериране; стари архиви не се изменят | триезични native/legacy PDF comparisons |
| Medium | Редакция на native paragraph занулява run formatting | Промяна само на текста и изрично изменените style properties | font/paragraph-preservation test |
| Medium | Дълъг KK ред може да бъде задържан на една страница | Същият native flow threshold като legacy | long-row test за двата варианта |
| Medium | Variant selector извън основната лента и без изрично accessible name | Преместен в toolbar с aria-label | повторен Chromium сценарий |
| High (CI gate) | pypdf 6.21.1 има нови advisory резултати | Pin 6.21.2; без игнориране на advisory | security/python-audit.json |

## Граници

Native adapter е контролиран, не универсален Word importer. Добавяне/изтриване/пренареждане на защитената структура, нови таблици или слотове се отказва; редактират се съществуващият текст, форматиране, размери, изображения и поддържани свойства. Canvas е работен изглед; действителният DOCX-derived PDF е проверката за pagination.

Реалният програмeн KK няма графични signature cells. Бизнес одобрението се запазва. Нов native KK graphic signer се отказва с конкретна локализирана грешка; не се добавя измислено поле или annex. Ако се изисква нова графична подписна позиция, е нужен отделно одобрен формат.

Repair v6 няма отделна REPAIR_EVENTS таблица. Adapter запазва поддържаните в v6 полета и таблици, без да представя event history като измислена нова секция. Наследеното пренасяне на repair tables и неповтарящите се headers остават по оригинала; repeat_header вече може да се редактира преди публикуване.

Нито един тест тук не удостоверява всички реални Production данни. При липсващ стар approval source вече архивираният файл остава достъпен; липсващ файл не се регенерира с нов source.
