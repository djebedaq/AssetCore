# Release checklist

- [x] Alembic upgrade до head и downgrade/upgrade са проверени върху изолирани SQLite бази.
- [x] SQLite backend suite: 132/132 теста изпълнени успешно в контролирани групи.
- [x] Document QA няма unresolved placeholders и съдържа DOCX/PDF hashes.
- [x] DOCX/PDF са визуално и структурно проверени спрямо снимковите образци чрез LibreOffice.
- [x] BG/EN/RU ключовете и одобрените шаблони са проверени.
- [x] Няма tracked DB, dump, secret, private key или generated export в release пакета.
- [x] Провереният 19-machine HPWJ регистър и source register са без промяна.
- [x] Release verifier: 21/21 проверки успешни.
- [x] Frontend TypeScript syntax и изолирана semantic проверка са успешни.
- [ ] Реален `pnpm install`, frontend typecheck, lint, Vitest и production build — изисква зелен GitHub frontend job.
- [ ] PostgreSQL migration и encrypted backup/restore round trip — изисква зелен GitHub postgres job.
- [ ] Docker image build, non-root/LibreOffice smoke, Compose validation и отделни `/api/health` + `/api/ready` проверки — изисква зелен GitHub docker/staging job.
- [ ] Ruff check — изисква зелен GitHub backend job.
- [ ] Реален staging login → issue → batch signatures → return → repair → parts → DOCX/PDF workflow.
- [ ] Backup/restore rehearsal върху staging копие.
- [ ] Собственик, licence payload, installation ID, срокове и лимити са проверени за конкретната инсталация.
- [ ] Draft legal documents са прегледани от квалифициран юрист.
