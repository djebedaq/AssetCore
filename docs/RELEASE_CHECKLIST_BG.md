# Release checklist

- [ ] `scripts/verify_release.ps1` завършва с exit code 0.
- [ ] Alembic upgrade до head и downgrade/upgrade са проверени върху копие.
- [ ] PostgreSQL integration и SQLite suite са успешни.
- [ ] Docker image е построен и `/api/health` е проверен.
- [ ] Document QA няма unresolved placeholders и има DOCX/PDF hashes.
- [ ] DOCX/PDF са визуално сравнени със снимковите образци чрез LibreOffice.
- [ ] BG/EN/RU ключовете и одобрените шаблони са пълни.
- [ ] Няма tracked DB, dump, secret, private key или generated export.
- [ ] Verified 19-machine HPWJ регистърът и source register са без промяна.
- [ ] SBOM и third-party licences са прегледани.
- [ ] Backup е създаден и restore е тестван в изолирана база.
- [ ] Собственик, licence payload, installation ID, срокове и лимити са проверени.
- [ ] Draft legal documents са прегледани от квалифициран юрист.
