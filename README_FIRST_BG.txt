AssetCore v12.4 — поправка на втория подпис при приемане

Проблем:
При потвърждаване на втория подпис за приемане PostgreSQL отказва заключващата заявка,
защото return batch финализаторът комбинира FOR UPDATE с joinedload(machine), което
създава LEFT OUTER JOIN към machines.

Поправка:
Машината се зарежда с selectinload в отделна заявка. FOR UPDATE остава само върху
transfer_protocols; при реалното финализиране машината се заключва отделно.

Копирай папките backend и tests в корена на repository-то и замени файловете.

Очаквани променени файлове:
- backend/app/transfer_service.py
- tests/test_bulk_transfers.py

Commit message:
Fix second signature PostgreSQL return finalization
