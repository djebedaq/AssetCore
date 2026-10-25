"""Localized future repair table labels; archived files are never regenerated."""

HEADERS = {
    "PARTS_USED": [("Поз.", "Номер", "Описание", "Количество"), ("Pos.", "Part No.", "Description", "Quantity"), ("Поз.", "Номер", "Описание", "Количество")],
    "REPAIR_PARTICIPANTS": [("Три имена", "Длъжност", "Участие", "Време"), ("Full name", "Job title", "Contribution", "Time"), ("ФИО", "Должность", "Участие", "Время")],
    "REPAIR_ATTACHMENTS": [("Файл", "Етап", "Описание"), ("File", "Stage", "Description"), ("Файл", "Этап", "Описание")],
}
EMPTY = {
    "REPAIR_PARTICIPANTS": ("Няма допълнителни участници", "No additional participants", "Нет дополнительных участников"),
    "REPAIR_ATTACHMENTS": ("Няма приложения", "No attachments", "Нет приложений"),
}


def headers(source, language):
    return HEADERS[source][("bg", "en", "ru").index(language)]


def empty_label(source, language):
    return EMPTY.get(source, ("", "", ""))[("bg", "en", "ru").index(language)]
