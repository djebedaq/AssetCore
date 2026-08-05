from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from sqlalchemy import select

from app.models import DocumentTemplate, DocumentTemplateVersion, GeneratedDocument, Repair, RepairParticipant


def _advance_to_completed(client, headers, repair_id: int):
    payloads = [
        {"status": "DIAGNOSIS", "inspection_complete": True, "diagnosis": "Диагностика на помпа"},
        {"status": "REPAIRING", "work_performed": "Подменени уплътнения и извършено сглобяване", "result": "Машината е възстановена"},
        {"status": "TESTING", "test_passed": True, "test_method": "Функционален тест", "test_details": "Тестът е успешен", "functional_test_result": "Работи нормално", "condition_after": "Добро"},
        {"status": "COMPLETED", "test_passed": True, "work_performed": "Подменени уплътнения и извършено сглобяване", "result": "Машината е възстановена", "test_details": "Тестът е успешен", "condition_after": "Добро"},
    ]
    response = None
    for payload in payloads:
        response = client.patch(f"/api/repair-cases/{repair_id}", headers=headers, json=payload)
        assert response.status_code == 200, response.text
    return response


def test_internal_repair_protocol_is_bg_contains_participants_and_is_idempotent(client, auth_headers, machine_ids, session_factory):
    created = client.post(
        "/api/repair-cases", headers=auth_headers,
        json={"machine_id": machine_ids["4"], "reported_problem": "Теч от помпата", "condition_before": "Неизправно"},
    )
    assert created.status_code == 201, created.text
    repair_id = created.json()["id"]
    participant = client.post(
        f"/api/repair-cases/{repair_id}/participants", headers=auth_headers,
        json={"full_name": "Иван Петров Иванов", "job_title": "Механик", "contribution": "Съдействие при сглобяването"},
    )
    assert participant.status_code == 201, participant.text

    completed = _advance_to_completed(client, auth_headers, repair_id)
    assert completed.json()["status"] == "COMPLETED"
    assert completed.json().get("document_generation_warning") is None

    # UI language requests are intentionally ignored for internal repair protocols.
    generated = client.post(f"/api/repair-cases/{repair_id}/documents?language=en", headers=auth_headers)
    assert generated.status_code == 201, generated.text
    assert generated.json()["language"] == "bg"
    assert generated.json()["requested_language"] == "en"

    with session_factory() as db:
        docs = list(db.scalars(select(GeneratedDocument).where(GeneratedDocument.repair_id == repair_id)))
        assert len(docs) == 2
        assert {item.language for item in docs} == {"bg"}
        docx = next(item for item in docs if item.format == "docx")
        snapshot = docx.snapshot
        assert snapshot["participants"][0]["full_name"] == "Иван Петров Иванов"
        assert snapshot["responsible_user"]["job_title"]
        document = Document(io.BytesIO(docx.content))
        text = "\n".join(p.text for p in document.paragraphs)
        for table in document.tables:
            text += "\n" + "\n".join(cell.text for row in table.rows for cell in row.cells)
        assert "Иван Петров Иванов" in text
        assert "ВЪТРЕШЕН ПРОТОКОЛ ЗА ИЗВЪРШЕН РЕМОНТ" in text

    repeated = client.patch(f"/api/repair-cases/{repair_id}", headers=auth_headers, json={"status": "COMPLETED"})
    assert repeated.status_code == 200, repeated.text
    with session_factory() as db:
        assert len(list(db.scalars(select(GeneratedDocument).where(GeneratedDocument.repair_id == repair_id)))) == 2


def test_missing_bg_template_does_not_rollback_completed_repair(client, auth_headers, machine_ids, session_factory):
    created = client.post(
        "/api/repair-cases", headers=auth_headers,
        json={"machine_id": machine_ids["5"], "reported_problem": "Повреден клапан"},
    )
    assert created.status_code == 201
    repair_id = created.json()["id"]
    for payload in [
        {"status": "DIAGNOSIS", "inspection_complete": True, "diagnosis": "Клапанът е блокирал"},
        {"status": "REPAIRING", "work_performed": "Клапанът е сменен", "result": "Ремонтът е извършен"},
        {"status": "TESTING", "test_passed": True, "test_details": "Успешен тест"},
    ]:
        response = client.patch(f"/api/repair-cases/{repair_id}", headers=auth_headers, json=payload)
        assert response.status_code == 200, response.text
    with session_factory() as db:
        template = db.scalar(select(DocumentTemplate).where(DocumentTemplate.document_type == "REPAIR_PROTOCOL"))
        versions = list(db.scalars(select(DocumentTemplateVersion).where(DocumentTemplateVersion.template_id == template.id, DocumentTemplateVersion.language == "bg")))
        for version in versions:
            version.is_published = False
        db.commit()
    completed = client.patch(
        f"/api/repair-cases/{repair_id}", headers=auth_headers,
        json={"status": "COMPLETED", "test_passed": True, "work_performed": "Клапанът е сменен", "result": "Ремонтът е извършен", "test_details": "Успешен тест"},
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["status"] == "COMPLETED"
    assert body["document_generation_warning"]["code"] == "document_template_unavailable"
    with session_factory() as db:
        repair = db.get(Repair, repair_id)
        assert repair.status == "COMPLETED"
        assert repair.machine.status == "READY"
        assert not list(db.scalars(select(GeneratedDocument).where(GeneratedDocument.repair_id == repair_id)))


def test_repair_participant_cannot_change_after_completion(client, auth_headers, machine_ids):
    created = client.post("/api/repair-cases", headers=auth_headers, json={"machine_id": machine_ids["7"], "reported_problem": "Тест"})
    repair_id = created.json()["id"]
    added = client.post(f"/api/repair-cases/{repair_id}/participants", headers=auth_headers, json={"full_name": "Петър Иванов Петров"})
    assert added.status_code == 201
    _advance_to_completed(client, auth_headers, repair_id)
    blocked = client.delete(f"/api/repair-cases/{repair_id}/participants/{added.json()['id']}", headers=auth_headers)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "completed_repair_is_locked"


def test_repair_frontend_contract_is_internal_and_bulgarian():
    source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "IndustrialPlatform.tsx").read_text()
    translations = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "i18n.tsx").read_text()
    assert "/documents?language=${locale}" not in source
    assert "repairCase.generateProtocolBg" in source
    assert "repairCase.participants" in source
    assert "Нов вътрешен ремонт" in translations
    assert "Регистрация → Преглед" in translations
