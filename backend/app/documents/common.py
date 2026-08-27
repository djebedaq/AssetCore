"""Document vocabulary, media types and controlled-reference locations."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..localization import translate
from ..models import (
    LanguageCode,
)

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


PDF_MEDIA_TYPE = "application/pdf"


class ConfirmedTemplateUnavailableError(RuntimeError):
    def __init__(self, document_type: str, language: str):
        self.document_type = document_type
        self.language = _language(language)
        self.message = translate("document.template_unavailable", self.language)
        super().__init__(self.message)


RESOURCES = Path(__file__).resolve().parents[2] / "resources"


ASSETS = RESOURCES / "assets"


def _reference_by_sha256(folder: Path, expected_sha256: str) -> Path:
    """Resolve a controlled reference by content, never by a locale-sensitive name."""
    for candidate in sorted(folder.glob("*.docx")):
        if hashlib.sha256(candidate.read_bytes()).hexdigest() == expected_sha256:
            return candidate
    raise FileNotFoundError(
        f"Controlled DOCX reference {expected_sha256} is missing from {folder.name}."
    )


REPAIR_REFERENCE = _reference_by_sha256(
    RESOURCES / "reference_protocols",
    "39337dfc445d61b4d5144259ca35624c2049d266378e326780176de3104784c1",
)


PARTS_REFERENCE = _reference_by_sha256(
    RESOURCES / "reference_protocols",
    "3ba8e43102ae044b02b6aa7a4cd3b06ff00bce444a56fc8da6ba737c42bbc7a7",
)


TEXT = {
    "bg": {
        "protocol": "ПРОТОКОЛ",
        "issue_title": "ПРОТОКОЛ ПРЕДАВАНЕ НА МИЕЩА ТЕХНИКА",
        "return_title": "ПРОТОКОЛ ПРИЕМАНЕ НА МИЕЩА ТЕХНИКА СЛЕД ИЗПОЛЗВАНЕ",
        "date": "ДАТА",
        "equipment": "ОБОРУДВАНЕ",
        "model": "МОДЕЛ",
        "inventory": "ЗАВОДСКИ НОМЕР",
        "serial": "СЕРИЕН НОМЕР",
        "number": "№",
        "element": "Елемент",
        "condition": "Състояние",
        "overall_condition": "Общо състояние",
        "usage_issue": "Оборудването ще се използва за",
        "usage_return": "Оборудването е било използвано за",
        "remarks": "Забележки",
        "handed": "Предал оборудването от страна на ДИРП",
        "accepted": "Приел оборудването",
        "returned": "Върнал оборудването",
        "name": "Три имена / фирма / цех",
        "signature": "Подпис",
        "batch": "Партида",
        "repair_protocol": "ПРОТОКОЛ ПРЕДИ / СЛЕД РЕМОНТ",
        "machine": "Машина",
        "reported_problem": "Регистриран проблем",
        "symptoms": "Наблюдавани симптоми",
        "required_work": "Необходима работа",
        "removed_parts": "Демонтирани части",
        "cleaning": "Почистване при диагностиката",
        "duration": "Време",
        "condition_before": "Състояние преди ремонта",
        "diagnosis": "Преглед и диагноза",
        "work": "Извършени ремонтни дейности",
        "events": "Хронология на ремонта",
        "parts_used": "Използвани части",
        "test": "Почистване и тестване",
        "test_method": "Метод",
        "test_pressure": "Достигнато налягане",
        "leaks": "Установени течове",
        "electrical_test": "Електрически тест",
        "functional_test": "Функционален тест",
        "yes": "Да",
        "no": "Не",
        "condition_after": "Състояние и резултат след ремонта",
        "responsible": "Извършил ремонта",
        "approver": "Одобрил",
        "part_request_title": "ТЕХНИЧЕСКА СПЕЦИФИКАЦИЯ\nЗА ДОСТАВКА НА РЕЗЕРВНИ ЧАСТИ",
        "position": "Поз.",
        "part_number": "PART №",
        "description": "ОПИСАНИЕ",
        "quantity": "КОЛИЧЕСТВО",
        "source": "Източник",
        "request_number": "ЗАЯВКА №",
        "requester": "Заявител",
        "decision": "Решение",
    },
    "en": {
        "protocol": "PROTOCOL",
        "issue_title": "HIGH-PRESSURE WASHING EQUIPMENT ISSUE PROTOCOL",
        "return_title": "HIGH-PRESSURE WASHING EQUIPMENT RETURN PROTOCOL",
        "date": "DATE",
        "equipment": "EQUIPMENT",
        "model": "MODEL",
        "inventory": "FACTORY / INVENTORY NUMBER",
        "serial": "SERIAL NUMBER",
        "number": "No.",
        "element": "Component",
        "condition": "Condition",
        "overall_condition": "Overall condition",
        "usage_issue": "The equipment will be used for",
        "usage_return": "The equipment was used for",
        "remarks": "Remarks",
        "handed": "Handed over by DIRP",
        "accepted": "Accepted by",
        "returned": "Returned by",
        "name": "Full name / company / department",
        "signature": "Signature",
        "batch": "Batch",
        "repair_protocol": "BEFORE / AFTER REPAIR PROTOCOL",
        "machine": "Machine",
        "reported_problem": "Reported problem",
        "symptoms": "Observed symptoms",
        "required_work": "Required work",
        "removed_parts": "Removed parts",
        "cleaning": "Cleaning during diagnosis",
        "duration": "Time",
        "condition_before": "Condition before repair",
        "diagnosis": "Inspection and diagnosis",
        "work": "Repair actions performed",
        "events": "Repair timeline",
        "parts_used": "Parts used",
        "test": "Cleaning and testing",
        "test_method": "Method",
        "test_pressure": "Pressure reached",
        "leaks": "Leaks detected",
        "electrical_test": "Electrical test",
        "functional_test": "Functional test",
        "yes": "Yes",
        "no": "No",
        "condition_after": "Condition and result after repair",
        "responsible": "Repair performed by",
        "approver": "Approved by",
        "part_request_title": "TECHNICAL SPECIFICATION\nFOR SPARE PARTS SUPPLY",
        "position": "Pos.",
        "part_number": "PART No.",
        "description": "DESCRIPTION",
        "quantity": "QUANTITY",
        "source": "Source",
        "request_number": "REQUEST No.",
        "requester": "Requested by",
        "decision": "Decision",
    },
    "ru": {
        "protocol": "ПРОТОКОЛ",
        "issue_title": "ПРОТОКОЛ ВЫДАЧИ МОЕЧНОЙ ТЕХНИКИ",
        "return_title": "ПРОТОКОЛ ПРИЕМА МОЕЧНОЙ ТЕХНИКИ ПОСЛЕ ИСПОЛЬЗОВАНИЯ",
        "date": "ДАТА",
        "equipment": "ОБОРУДОВАНИЕ",
        "model": "МОДЕЛЬ",
        "inventory": "ЗАВОДСКОЙ / ИНВЕНТАРНЫЙ НОМЕР",
        "serial": "СЕРИЙНЫЙ НОМЕР",
        "number": "№",
        "element": "Элемент",
        "condition": "Состояние",
        "overall_condition": "Общее состояние",
        "usage_issue": "Оборудование будет использовано для",
        "usage_return": "Оборудование использовалось для",
        "remarks": "Примечания",
        "handed": "Передал оборудование со стороны ДИРП",
        "accepted": "Принял оборудование",
        "returned": "Вернул оборудование",
        "name": "ФИО / компания / подразделение",
        "signature": "Подпись",
        "batch": "Партия",
        "repair_protocol": "ПРОТОКОЛ ДО / ПОСЛЕ РЕМОНТА",
        "machine": "Машина",
        "reported_problem": "Заявленная неисправность",
        "symptoms": "Наблюдаемые симптомы",
        "required_work": "Необходимые работы",
        "removed_parts": "Демонтированные детали",
        "cleaning": "Очистка при диагностике",
        "duration": "Время",
        "condition_before": "Состояние до ремонта",
        "diagnosis": "Осмотр и диагностика",
        "work": "Выполненные ремонтные работы",
        "events": "Хронология ремонта",
        "parts_used": "Использованные детали",
        "test": "Очистка и испытание",
        "test_method": "Метод",
        "test_pressure": "Достигнутое давление",
        "leaks": "Обнаружены утечки",
        "electrical_test": "Электрическое испытание",
        "functional_test": "Функциональное испытание",
        "yes": "Да",
        "no": "Нет",
        "condition_after": "Состояние и результат после ремонта",
        "responsible": "Ремонт выполнил",
        "approver": "Утвердил",
        "part_request_title": "ТЕХНИЧЕСКАЯ СПЕЦИФИКАЦИЯ\nНА ПОСТАВКУ ЗАПАСНЫХ ЧАСТЕЙ",
        "position": "Поз.",
        "part_number": "PART №",
        "description": "ОПИСАНИЕ",
        "quantity": "КОЛИЧЕСТВО",
        "source": "Источник",
        "request_number": "ЗАЯВКА №",
        "requester": "Заявитель",
        "decision": "Решение",
    },
}


def safe_filename(value: str) -> str:
    """Return a stable ASCII filename stem without path components."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return cleaned.strip(".-") or "assetcore-document"


def _language(value: str | None) -> str:
    return value if value in TEXT else LanguageCode.BG.value
