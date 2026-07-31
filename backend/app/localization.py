from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SUPPORTED_LANGUAGES = ("bg", "en", "ru")
DEFAULT_LANGUAGE = "bg"

LEGACY_MACHINE_STATUS_CODES = {
    "Готова": "READY",
    "Издадена": "ISSUED",
    "В употреба": "IN_USE",
    "Върната": "RETURNED",
    "За преглед": "INSPECTION",
    "Преглед": "INSPECTION",
    "Почистване": "CLEANING",
    "В ремонт": "REPAIR",
    "Ремонт": "REPAIR",
    "Чака одобрение": "WAITING_APPROVAL",
    "Изчаква одобрение": "WAITING_APPROVAL",
    "Чака части": "WAITING_PARTS",
    "Изчаква части": "WAITING_PARTS",
    "Тестване": "TESTING",
}

LEGACY_REPAIR_STATUS_CODES = {
    "Приета": "ACCEPTED",
    "Диагностика": "DIAGNOSIS",
    "Чака одобрение": "WAITING_APPROVAL",
    "Чака части": "WAITING_PARTS",
    "В ремонт": "REPAIRING",
    "Тестване": "TESTING",
    "Завършена": "COMPLETED",
}

LEGACY_PART_REQUEST_STATUS_CODES = {
    "Чернова": "DRAFT",
    "Изпратена": "SUBMITTED",
    "Подадена": "SUBMITTED",
    "Чака одобрение": "WAITING_APPROVAL",
    "Изчакване на одобрение": "WAITING_APPROVAL",
    "Одобрена": "APPROVED",
    "Отхвърлена": "REJECTED",
    "Поръчана": "ORDERED",
    "Частично доставена": "PARTIALLY_DELIVERED",
    "Доставена": "DELIVERED",
    "Отказана": "CANCELLED",
}

LEGACY_PART_REQUEST_PRIORITY_CODES = {
    "Нисък": "LOW",
    "Нормален": "NORMAL",
    "Спешен": "URGENT",
}


def normalize_language(value: str | None) -> str:
    if not value:
        return DEFAULT_LANGUAGE
    candidate = value.strip().lower().replace("_", "-").split("-", 1)[0]
    return candidate if candidate in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


MESSAGES: dict[str, dict[str, str]] = {
    "auth.invalid_or_expired": {
        "bg": "Невалидна или изтекла сесия",
        "en": "Invalid or expired session",
        "ru": "Недействительная или истекшая сессия",
    },
    "auth.required": {
        "bg": "Необходим е вход в системата",
        "en": "Authentication is required",
        "ru": "Необходимо войти в систему",
    },
    "auth.invalid_session": {
        "bg": "Невалидна сесия",
        "en": "Invalid session",
        "ru": "Недействительная сессия",
    },
    "auth.user_not_found": {
        "bg": "Потребителят не е намерен",
        "en": "The user was not found",
        "ru": "Пользователь не найден",
    },
    "auth.invalid_credentials": {
        "bg": "Грешен имейл или парола",
        "en": "Incorrect email or password",
        "ru": "Неверный адрес электронной почты или пароль",
    },
    "permission.transfer": {
        "bg": "Нямате право да извършвате издаване или връщане.",
        "en": "You are not allowed to issue or return assets.",
        "ru": "У вас нет права выдавать или возвращать оборудование.",
    },
    "permission.denied": {
        "bg": "Нямате право да извършите тази операция.",
        "en": "You are not allowed to perform this operation.",
        "ru": "У вас нет права выполнять эту операцию.",
    },
    "validation.invalid": {
        "bg": "Невалидни данни в заявката.",
        "en": "The request contains invalid data.",
        "ru": "Запрос содержит недопустимые данные.",
    },
    "validation.language": {
        "bg": "Поддържаните езици са български, английски и руски.",
        "en": "The supported languages are Bulgarian, English, and Russian.",
        "ru": "Поддерживаются болгарский, английский и русский языки.",
    },
    "issue.active": {
        "bg": "Машина №{number} не може да бъде издадена, защото има активно предаване и все още не е върната.",
        "en": "Asset No. {number} cannot be issued because it has an active transfer and has not been returned.",
        "ru": "Оборудование №{number} нельзя выдать: передача активна, а оборудование ещё не возвращено.",
    },
    "issue.current_status": {
        "bg": "Текущ статус: {status}.",
        "en": "Current status: {status}.",
        "ru": "Текущий статус: {status}.",
    },
    "issue.protocol": {
        "bg": "Протокол: {protocol}.",
        "en": "Protocol: {protocol}.",
        "ru": "Протокол: {protocol}.",
    },
    "issue.date": {
        "bg": "Дата на издаване: {date}.",
        "en": "Issue date: {date}.",
        "ru": "Дата выдачи: {date}.",
    },
    "issue.recipient": {
        "bg": "Получател или място: {recipient}.",
        "en": "Recipient or location: {recipient}.",
        "ru": "Получатель или место: {recipient}.",
    },
    "issue.not_ready": {
        "bg": "Машина №{number} не може да бъде издадена при статус „{status}“. Необходимо е първо да бъде отбелязана като „{ready}“.",
        "en": "Asset No. {number} cannot be issued with status “{status}”. It must first be marked “{ready}”.",
        "ru": "Оборудование №{number} нельзя выдать со статусом «{status}». Сначала установите статус «{ready}».",
    },
    "issue.machines_not_found": {
        "bg": "Една или повече избрани машини не са намерени.",
        "en": "One or more selected assets were not found.",
        "ru": "Одна или несколько выбранных единиц оборудования не найдены.",
    },
    "issue.concurrent": {
        "bg": "Издаването е отказано поради едновременна конфликтна операция.",
        "en": "The issue was rejected because of a concurrent conflicting operation.",
        "ru": "Выдача отклонена из-за одновременной конфликтующей операции.",
    },
    "issue.success": {
        "bg": "Груповото издаване е завършено успешно.",
        "en": "The bulk issue was completed successfully.",
        "ru": "Групповая выдача успешно завершена.",
    },
    "locations.not_found": {
        "bg": "Едно или повече избрани местоположения не са намерени.",
        "en": "One or more selected locations were not found.",
        "ru": "Одно или несколько выбранных местоположений не найдены.",
    },
    "return.machines_not_found": {
        "bg": "Една или повече машини за връщане не са намерени.",
        "en": "One or more assets to return were not found.",
        "ru": "Одна или несколько возвращаемых единиц оборудования не найдены.",
    },
    "return.transfers_not_found": {
        "bg": "Едно или повече предавания не са намерени.",
        "en": "One or more transfers were not found.",
        "ru": "Одна или несколько передач не найдены.",
    },
    "return.wrong_transfer": {
        "bg": "Избраното предаване не принадлежи на тази машина.",
        "en": "The selected transfer does not belong to this asset.",
        "ru": "Выбранная передача не относится к этому оборудованию.",
    },
    "return.already_returned": {
        "bg": "Машина №{number} вече е върната по протокол {protocol}.",
        "en": "Asset No. {number} has already been returned under protocol {protocol}.",
        "ru": "Оборудование №{number} уже возвращено по протоколу {protocol}.",
    },
    "return.success": {
        "bg": "Връщането е записано успешно.",
        "en": "The return was recorded successfully.",
        "ru": "Возврат успешно зарегистрирован.",
    },
    "batch.not_found": {
        "bg": "Партидата не е намерена.",
        "en": "The batch was not found.",
        "ru": "Партия не найдена.",
    },
    "document.protocol_not_found": {
        "bg": "Генерираният протокол не е намерен.",
        "en": "The generated protocol was not found.",
        "ru": "Созданный протокол не найден.",
    },
}


STATUS_LABELS: dict[str, dict[str, str]] = {
    "READY": {"bg": "Готова", "en": "Ready", "ru": "Готово"},
    "ISSUED": {"bg": "Издадена", "en": "Issued", "ru": "Выдано"},
    "IN_USE": {"bg": "В употреба", "en": "In use", "ru": "В эксплуатации"},
    "RETURNED": {"bg": "Върната", "en": "Returned", "ru": "Возвращено"},
    "INSPECTION": {"bg": "За преглед", "en": "Inspection", "ru": "Осмотр"},
    "CLEANING": {"bg": "Почистване", "en": "Cleaning", "ru": "Очистка"},
    "REPAIR": {"bg": "В ремонт", "en": "Repair", "ru": "В ремонте"},
    "WAITING_APPROVAL": {"bg": "Чака одобрение", "en": "Waiting approval", "ru": "Ожидает согласования"},
    "WAITING_PARTS": {"bg": "Чака части", "en": "Waiting parts", "ru": "Ожидает запчасти"},
    "TESTING": {"bg": "Тестване", "en": "Testing", "ru": "Испытание"},
    "ACTIVE": {"bg": "Издадена партида", "en": "Issued batch", "ru": "Выданная партия"},
    "PARTIALLY_RETURNED": {"bg": "Частично върната партида", "en": "Partially returned batch", "ru": "Частично возвращённая партия"},
    "ACCEPTED": {"bg": "Приета", "en": "Accepted", "ru": "Принято"},
    "DIAGNOSIS": {"bg": "Диагностика", "en": "Diagnosis", "ru": "Диагностика"},
    "REPAIRING": {"bg": "В ремонт", "en": "Repairing", "ru": "Ремонт"},
    "COMPLETED": {"bg": "Завършена", "en": "Completed", "ru": "Завершено"},
    "DRAFT": {"bg": "Чернова", "en": "Draft", "ru": "Черновик"},
    "SUBMITTED": {"bg": "Подадена", "en": "Submitted", "ru": "Подано"},
    "APPROVED": {"bg": "Одобрена", "en": "Approved", "ru": "Одобрено"},
    "REJECTED": {"bg": "Отхвърлена", "en": "Rejected", "ru": "Отклонено"},
    "ORDERED": {"bg": "Поръчана", "en": "Ordered", "ru": "Заказано"},
    "PARTIALLY_DELIVERED": {"bg": "Частично доставена", "en": "Partially delivered", "ru": "Частично поставлено"},
    "DELIVERED": {"bg": "Доставена", "en": "Delivered", "ru": "Поставлено"},
    "CANCELLED": {"bg": "Отказана", "en": "Cancelled", "ru": "Отменено"},
    "LOW": {"bg": "Нисък", "en": "Low", "ru": "Низкий"},
    "NORMAL": {"bg": "Нормален", "en": "Normal", "ru": "Обычный"},
    "URGENT": {"bg": "Спешен", "en": "Urgent", "ru": "Срочный"},
}


def translate(key: str, language: str | None = None, **values: Any) -> str:
    translations: Mapping[str, str] | None = MESSAGES.get(key)
    if translations is None:
        return key
    selected = normalize_language(language)
    template = translations.get(selected) or translations[DEFAULT_LANGUAGE]
    return template.format(**values)


def status_label(code: str, language: str | None = None) -> str:
    translations = STATUS_LABELS.get(code)
    if translations is None:
        return code
    selected = normalize_language(language)
    return translations.get(selected) or translations[DEFAULT_LANGUAGE]
