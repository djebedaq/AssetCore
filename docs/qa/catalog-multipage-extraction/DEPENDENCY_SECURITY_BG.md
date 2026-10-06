# PR #98: frontend dependency security follow-up

Промяната отстранява блокиращите advisories след преминалия functional review.
Multi-page extraction кодът, frontend assertions, security policy, workflow и
списъкът с audit exceptions не се променят. Production не е отварян или променян;
няма deployment или merge.

## Проверен dependency graph преди промяната

- `assetcore-frontend → vite@6.4.3 → postcss@8.5.25 → source-map-js@1.2.1`.
  Същият Vite е използван от `@vitejs/plugin-react@4.7.0`, Vitest и mocker.
- `assetcore-frontend → vitest@3.2.7 → tinypool@1.1.1`.

Пътищата са проверени с `pnpm --dir frontend why source-map-js tinypool vitest vite`
и чрез importer/package/snapshot записите в lockfile.

## Минимално избраната корекция

| Зависимост | Преди | След | Причина |
|---|---|---|---|
| source-map-js | 1.2.1 | 1.2.2 | Patched версия за GHSA-68fv-2mgg-jv7q; съвместима с PostCSS диапазона `^1.2.1` |
| vitest и седемте @vitest пакета | 3.2.7 | 4.1.11 | Vitest 4 премахва Tinypool; 4.1.11 е първата stable 4.x версия, поправяща и GHSA-82fw-gwwq-j7x9 |
| tinypool | 1.1.1 | премахнат | Няма dependency path към засегнатия пакет; премахва GHSA-5gmw-xhrv-c9v3 и GHSA-85c8-ppgw-ccpr |

За двата Tinypool advisories patched версиите са съответно 2.1.1 и 2.1.2.
Не е наложен неподдържан cross-major override върху Vitest 3. Последната налична
3.x версия е 3.2.7 и запазва уязвимия Tinypool. Поддържаният Vitest 4 runner
премахва тази зависимост изцяло и работи с наличния Vite 6 и CI Node 22.
Vitest 5, Vite, React, React plugin, PostCSS, TypeScript и ESLint не са обновявани.

`frontend/package.json` променя един ред: `vitest` от `^3.2.4` на точен `4.1.11`.
`frontend/pnpm-lock.yaml` сменя само Vitest dependency tree и source-map-js patch.
Всички общи package records запазват metadata/integrity; peer snapshot суфиксите
се преизчисляват от pnpm. Допълнителните toolchain промени са:
`chai 5.3.3 → 6.3.0`, `es-module-lexer 1.7.0 → 2.3.2`,
`std-env 3.10.0 → 4.3.0`, `tinyexec 0.3.2 → 1.3.1`,
`tinyrainbow 2.0.0 → 3.2.0`; добавени са `obug@2.2.1` и
`@standard-schema/spec@1.1.0`. Старите runner-only зависимости, включително
`vite-node`, са премахнати. Няма нови overrides или audit exceptions.

## Проверки и критерий за готовност

Lockfile е синхронизиран и проверен с project pnpm 11.9.0:

- `pnpm dlx pnpm@11.9.0 --dir frontend install --frozen-lockfile` — PASS.
- `.venv/Scripts/python.exe scripts/audit_dependencies.py frontend --output .tmp/pr98-security/frontend-audit.json` — PASS: 342 зависимости, нула blocking/informational advisories и нула accepted exceptions.
- `pnpm dlx pnpm@11.9.0 --dir frontend run typecheck` — PASS.
- `pnpm dlx pnpm@11.9.0 --dir frontend run lint` — PASS.
- `pnpm dlx pnpm@11.9.0 --dir frontend run build` — PASS; съществуващото предупреждение за chunk над 500 kB.

Първият пълен frontend run (`pnpm dlx pnpm@11.9.0 --dir frontend exec vitest run --maxWorkers=2`)
дава 557 passed и един timeout при първото lazy зареждане на passport dialog,
докато се изпълнява build. Самостоятелният диагностичен run
(`pnpm dlx pnpm@11.9.0 --dir frontend exec vitest run src/features/passport/MachineEntryActions.test.tsx --maxWorkers=1 --reporter=verbose`)
дава 25 passed. Няма променени тестове, assertions или timeout настройки.
Повторният пълен run със същата команда завършва с 56 files / 558 passed
за 104.18 s; първият неуспешен опит не се отчита за PASS.

Catalog/PARTS-DOC локалната регресия също минава: 82 passed за 97.26 s:
`.venv/Scripts/python.exe -m pytest -q tests/test_catalog_guided_builder.py tests/test_catalog_multipage_extraction.py tests/test_catalog_selected_extraction.py tests/test_catalog_extraction_schema.py tests/test_catalog_extraction_columns.py tests/test_catalog_extraction_boundaries.py --tb=short`.

Окончателните локални резултати и пълният Build check за точния финален HEAD
се записват в PR #98 след приключване. Готовност се отбелязва единствено след
зелен frontend/backend/PostgreSQL/Docker workflow върху същия HEAD.
CI изпълнява `pnpm test`, typecheck, lint, build, dependency gate, пълния backend
набор, реалните PostgreSQL 16 проверки, Docker backup/restore/rendering gates и
`scripts/verify_release.py`. PR остава отворен и unmerged.

## Източници

- [source-map-js advisory и patched 1.2.2](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)
- [Tinypool worker-options advisory](https://github.com/advisories/GHSA-5gmw-xhrv-c9v3)
- [Tinypool run-options advisory](https://github.com/advisories/GHSA-85c8-ppgw-ccpr)
- [Vitest 4 migration: Tinypool removal и Vite/Node compatibility](https://v4.vitest.dev/guide/migration#pool-rework)
- [Vitest/mocker patched 4.1.11](https://github.com/advisories/GHSA-82fw-gwwq-j7x9)
