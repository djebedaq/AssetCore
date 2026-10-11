# Catalog Builder 03B — локални QA доказателства

`d13-linux-exact.json` и `d13-windows-exact.json` съдържат отделно последващо сравнение на три извличания на физически страници 13/15. Всеки запис проверява четирите полета, броя, SHA-256, страницата и липсата на останали parser descendants. `implementation_sha256` използва SHA-256 след нормализиране на CRLF до LF и позволява сравнение на Windows checkout с Linux image.

`linux-ocr-smoke.json` съдържа 11 реални CLI OCR сценария с разрешени синтетични таблици. `browser-d13.json` съдържа проверки през нормалния UI, без OEM изображения/редове, credentials или локални пътища. `verification.json` описва командите и резултатите на проверките.

OEM PDF и контролният JSON остават извън Git. Оригиналният документ не се изпраща по мрежа. Expected JSON се чете само от отделния comparator **след** приключване на извличането. Тези отчети доказват извличане, а не VERIFIED източници, пълни hotspots или готова публикация.

## Възпроизвеждане в изолиран Linux Docker runtime

Променливите `QA_PDF` и `QA_EXPECTED` сочат разрешените локални оригинал и независим контрол. `QA_OUTPUT` е предварително създадена абсолютна локална директория само за QA. Изпълнете от development checkout; не използвайте production ресурси.

```sh
docker build --tag assetcore-catalog-03b-proof:dev .
docker run --rm --init --name assetcore-catalog-03b-proof \
  --network none --read-only --memory 1g --cpus 2 --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,noexec,size=192m \
  --mount "type=bind,source=$QA_PDF,target=/qa/input.pdf,readonly" \
  --mount "type=bind,source=$PWD/scripts/catalog_adaptive_pdf_qa.py,target=/app/scripts/catalog_adaptive_pdf_qa.py,readonly" \
  --mount "type=bind,source=$QA_OUTPUT,target=/qa-output" \
  assetcore-catalog-03b-proof:dev python scripts/catalog_adaptive_pdf_qa.py \
  extract /qa/input.pdf --pages 13,15 --runs 3 --output /qa-output/extraction.json
python scripts/catalog_adaptive_pdf_qa.py compare \
  "$QA_OUTPUT/extraction.json" "$QA_EXPECTED" --output "$QA_OUTPUT/comparison.json"
```

За две едновременни извличания заменете последната container команда с `concurrency /qa/input.pdf --page 13 --output /qa-output/concurrency.json`. Сравнете получения отчет със същия отделен comparator. Измерването е за общото process tree на двата worker-а, включително QA controller, при непроменен container лимит.

```sh
docker run --rm --init --network none --read-only --memory 1g --cpus 2 \
  --pids-limit 64 --tmpfs /tmp:rw,nosuid,noexec,size=192m \
  assetcore-catalog-03b-proof:dev python backend/scripts/catalog_adaptive_ocr_smoke.py
python tests/browser/run_catalog_adaptive_extraction_qa.py "$QA_PDF" "$QA_EXPECTED"
```

Browser launcher създава собствен SQLite файл, временни credentials и localhost server и го спира във `finally`. PostgreSQL launcher създава отделен контейнер със случайно име и премахва само него и неговия volume във `finally`. Съществуващи Docker ресурси не се променят.
