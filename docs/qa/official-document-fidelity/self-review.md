# Втори технически преглед

Извършен като отделен критичен прочит на final diff, след реалните рендери. Това е self-review на същия изпълнител, а не независимо човешко одобрение.

Проследени са selection → conversion → draft CAS → preview receipt → publication CAS/company lock → explicit activation → canonical issue → frozen source → archive → signing. Проверени са type/language/hash границите, историческият read path, липсващ source, duplicate tokens, signature-marker injection, variant mismatch и промяна на фирмени ресурси.

Намерени и поправени при втория прочит: font reset при текстова редакция; long-row keep-together; неуниверсален HPWJ label map; липсващ CONDITION_LABEL в synthetic preview; липсващи графични KK слотове при signer enrollment; недостъпен variant selector; EN/RU repair table headers; разграничаване на native origin от избраната Studio version в диагностиката. Причини, тестове и ограничения са в risk-register.md.

Проверено е, че новите native source bytes не могат да бъдат подменени с draft update; original images се извличат само през reader-authorized endpoint. Frozen publication manifest включва реалните authorized image bytes. Source ingestion запазва съществуващите ZIP/XML/relationship ограничения.

Не се въвеждат нов signing механизъм, counter, approval registry или migration. Старите schema 1–3 остават четими. Новите exact layouts ползват schema 4 и adapter 1. Generic стари machine-only layouts не се приемат за FREE_FORM.

## Security и concurrency

Approval source се проверява преди number reservation в caller transaction. Архивирането остава savepoint операция: renderer failure не преномерира вече издадено одобрение. Draft/publication CAS, company lock, append-only activation revisions и съществуващите PostgreSQL constraints остават авторитетни. Не се твърди, че SQLite възпроизвежда PostgreSQL row-lock concurrency; това се проверява в отделния postgres CI job.

Password/session/owner/role/licence/QR/repair-history механизми не са преработвани. Production manager scripts са част от preservation проверката и regression suite. Новата диагностична API не връща filesystem paths, тайни или бизнес записи.

Точните изпълнени проверки и евентуални блокери се поддържат в release-readiness.md; неприключил или прекъснат suite не е успешен резултат.


## Втори прочит след пълния CI

Пълният suite установи test-contract drift при два нови authorized routes, очакваните EN/RU repair label промени и browser имената за двата KK preview варианта. Проверени са точните причини; не е променян старият golden или production код, за да се прикрият откази. Новото historical XML сравнение допуска само изрично проверените translated text nodes и запазва останалия byte-level договор.

Отчетните откази са възпроизведени при UTC/Sofia midnight около смяната на часовото време. Production изчислението е правилно; фиксираният test clock и новите DST гранични случаи премахват зависимостта от текущия час, без промяна на threshold или очакваната календарна семантика.
