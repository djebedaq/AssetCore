"""Neutral editable designs; never imported or activated as official templates."""
from .schemas import Layout
from .starter_labels import LABELS

TITLES = {
    "TRANSFER_ISSUE": ("Протокол за предаване на оборудване", "Equipment handover protocol", "Протокол передачи оборудования"),
    "TRANSFER_RETURN": ("Протокол за връщане на оборудване", "Equipment return protocol", "Протокол возврата оборудования"),
    "REPAIR_PROTOCOL": ("Протокол за приемане и ремонт", "Acceptance and repair protocol", "Протокол приёмки и ремонта"),
    "PART_REQUEST": ("Техническа спецификация за резервни части", "Spare parts technical specification", "Техническая спецификация запасных частей"),
}
COLUMNS = {
    "position": ("№", "Pos.", "№"), "component": ("Елемент", "Component", "Элемент"),
    "condition": ("Състояние", "Condition", "Состояние"), "measurement": ("Измерване", "Measurement", "Измерение"),
    "note": ("Бележка", "Note", "Примечание"), "part_number": ("Номер на част", "Part number", "Номер детали"),
    "description": ("Описание", "Description", "Описание"), "quantity": ("Количество", "Quantity", "Количество"),
    "name": ("Три имена", "Full name", "Полное имя"), "job_title": ("Длъжност", "Job title", "Должность"),
    "contribution": ("Участие", "Contribution", "Участие"), "duration": ("Записан труд", "Recorded labor", "Записанный труд"),
    "filename": ("Файл", "File", "Файл"), "stage": ("Етап", "Stage", "Этап"),
    "date": ("Дата", "Date", "Дата"), "event_type": ("Събитие", "Event", "Событие"),
}


def professional_layout(document_type, language, identity=None):
    identity = identity or {}
    lang = ("bg", "en", "ru").index(language)
    seq = 0
    def block(kind, **kwargs):
        nonlocal seq
        seq += 1
        return {"id": f"design_{seq}", "type": kind, "style": {"size_pt": 9, "color": "#000000", "spacing_mm": 1}, **kwargs}
    def text(value, **kwargs):
        return block("text", text=value, **kwargs)
    def field(code, **kwargs):
        return block("field", field=code, **kwargs)
    def cell(children, **kwargs):
        return {"blocks": children, "padding_mm": 1.2, "vertical_align": "center",
                "style": {"border_pt": .5, "color": "#000000"}, **kwargs}
    def grid(widths, rows, **kwargs):
        return block("grid", widths=widths, grid_rows=rows, **kwargs)
    def identity_table(codes):
        return grid([26, 74], [{"cells": [cell([text(LABELS[code][lang], style={"size_pt": 9, "bold": True, "color": "#000000", "spacing_mm": 0})]),
            cell([field(code)])], "min_height_mm": 6, "keep_together": True} for code in codes])
    def section(code):
        return grid([100], [{"cells": [cell([text(LABELS[code][lang], style={"size_pt": 9, "bold": True, "color": "#000000", "spacing_mm": 0}), field(code)])], "keep_together": True}])
    def paired_identity(codes):
        rows = []
        for offset in range(0, len(codes), 2):
            cells = []
            for code in codes[offset:offset + 2]:
                cells += [cell([text(LABELS[code][lang], style={"size_pt": 8.5, "bold": True, "color": "#000000", "spacing_mm": 0})]), cell([field(code)])]
            rows.append({"cells": cells, "keep_together": True, "min_height_mm": 6})
        return grid([26, 24, 26, 24], rows)
    def dynamic(source, columns):
        return block("dynamic_table", source=source, keep_rows_together=True, style={"size_pt": 8.5, "border_pt": .5, "color": "#000000", "spacing_mm": 2},
            columns=[{"key": key, "label": COLUMNS[key][lang], "width_percent": width} for key, width in columns])
    def heading(value):
        return block("heading", text=value, style={"size_pt": 11, "bold": True, "color": "#000000", "spacing_mm": 2})
    def logo(image_id, width):
        return block("logo", image_id=image_id, width_mm=width, height_mm=20,
                     style={"align": "center", "spacing_mm": 0})
    left = [logo(identity["primary_logo_id"], 22)] if identity.get("primary_logo_id") else [text(("Фирмено лого", "Company logo", "Логотип компании")[lang])]
    right = [logo(identity["secondary_logo_id"], 24)] if identity.get("secondary_logo_id") else [field("COMPANY_REGISTRATION"), field("COMPANY_CONTACTS")]
    header = grid([17, 63, 20], [{"cells": [cell(left), cell([field("COMPANY_NAME", style={"size_pt": 16, "bold": True, "align": "center", "color": "#000000", "spacing_mm": 1}),
        field("COMPANY_ADDRESS", style={"size_pt": 8, "align": "center", "color": "#000000", "spacing_mm": 0})]), cell(right)], "min_height_mm": 27}], region="header")
    blocks = [header, heading(TITLES[document_type][lang])]
    if document_type.startswith("TRANSFER_"):
        blocks += [identity_table(["DOCUMENT_NUMBER", "CREATION_DATE", "EQUIPMENT_TYPE", "MODEL_DISPLAY", "MACHINE_NUMBER", "SERIAL_NUMBER"]),
            dynamic("EQUIPMENT_CHECKLIST", [("position", 6), ("component", 35), ("condition", 59)])]
        blocks += [section(code) for code in ("CONDITION_TEXT", "USAGE_TEXT", "REMARKS")]
    elif document_type == "REPAIR_PROTOCOL":
        blocks += [identity_table(["DOCUMENT_NUMBER", "ACCEPTANCE_DATE", "REPAIR_REFERENCE", "SOURCE_RETURN_REFERENCE", "MACHINE_NAME", "MACHINE_NUMBER", "MODEL_DISPLAY", "SERIAL_NUMBER", "OWNERSHIP"])]
        blocks += [section(code) for code in ("REPORTED_PROBLEM", "SYMPTOMS", "CONDITION_BEFORE", "REQUIRED_WORK", "REMOVED_PARTS", "DIAGNOSTIC_CLEANING", "DIAGNOSIS", "REQUIRED_PARTS", "DIAGNOSIS_DURATION")]
        blocks += [heading(LABELS["REPAIRER_NAMES"][lang]), dynamic("REPAIR_PARTICIPANTS", [("name", 28), ("job_title", 25), ("contribution", 27), ("duration", 20)]),
            identity_table(["HANDED_OVER_NAME", "ACCEPTED_BY_NAME"]), block("page_break"), heading(("Извършен ремонт и приключване", "Repair work and completion", "Ремонтные работы и завершение")[lang])]
        blocks += [section("WORK_PERFORMED"), paired_identity(["REPAIR_DURATION", "TESTING_DURATION"])]
        blocks += [heading(("Вложени части", "Parts used", "Использованные детали")[lang]), dynamic("PARTS_USED", [("position", 7), ("part_number", 23), ("description", 50), ("quantity", 20)])]
        blocks += [paired_identity(["REPAIR_START", "REPAIR_END", "TOTAL_WORK_DURATION", "PARTICIPANT_TOTAL_DURATION"])]
        blocks += [section(code) for code in ("TEST_RESULT", "TEST_DETAILS", "CONDITION_AFTER", "FINAL_RESULT")]
        blocks += [dynamic("REPAIR_EVENTS", [("date", 23), ("event_type", 22), ("description", 55)]), dynamic("REPAIR_ATTACHMENTS", [("filename", 35), ("stage", 20), ("description", 45)]),
            identity_table(["APPROVED_BY_NAME", "APPROVED_BY_JOB_TITLE", "COMPLETION_DATE", "CREATION_DATE"])]
    else:
        blocks += [identity_table(["DOCUMENT_NUMBER", "CREATION_DATE", "MACHINE_NAME", "EQUIPMENT_TYPE", "MANUFACTURER", "MODEL", "SERIAL_NUMBER", "MACHINE_NUMBER", "PRESSURE_BAR", "BATCH_REFERENCE", "CATALOG_REFERENCES"]),
            dynamic("REQUEST_LINES", [("position", 7), ("part_number", 23), ("description", 50), ("quantity", 20)])]
        blocks += [section(code) for code in ("REMARKS", "DECISION")]
        blocks += [identity_table(["REQUESTER_NAME", "DEPARTMENT", "APPROVER_NAME", "APPROVAL_DATE"])]
    sign_rows = []
    for side in (["LEFT"] if document_type == "REPAIR_PROTOCOL" else ["LEFT", "RIGHT"]):
        roles = {
            "REPAIR_PROTOCOL": [("Отговорен за ремонта", "Responsible for repair", "Ответственный за ремонт")],
            "PART_REQUEST": [("Заявител", "Requester", "Заявитель"), ("Одобрил заявката", "Request approved by", "Утвердивший заявку")],
            "TRANSFER_ISSUE": [("Предал оборудването", "Handed over by", "Передал оборудование"), ("Приел оборудването", "Received by", "Принял оборудование")],
            "TRANSFER_RETURN": [("Върнал оборудването", "Returned by", "Вернул оборудование"), ("Приел при връщане", "Return accepted by", "Принял при возврате")],
        }
        role = roles[document_type][side == "RIGHT"][lang]
        sign_rows.append({"cells": [cell([text(role)]), cell([field(f"{side}_SIGNER_NAME"), field(f"{side}_SIGNER_JOB_TITLE"), field(f"{side}_SIGNER_ORGANIZATION")]),
            cell([block("signature", slot=f"{side}_SIGNATURE", show_identity=False, label=("Подпис", "Signature", "Подпись")[lang], style={"size_pt": 8, "color": "#000000", "spacing_mm": 0})])],
            "min_height_mm": 19, "keep_together": True})
    metadata = grid([65, 35], [{"cells": [cell([text(LABELS["PREPARER_NAME"][lang], style={"size_pt": 8, "bold": True, "spacing_mm": 0, "color": "#000000"}),
        field("PREPARER_NAME"), field("PREPARER_JOB_TITLE")]), cell([field("SIGNATURE_STATUS")] + ([field("BATCH_REFERENCE")] if document_type.startswith("TRANSFER_") else []))], "keep_together": True}])
    blocks += [grid([23, 55, 22], sign_rows, keep_together=True), metadata,
        block("page_number", region="footer", style={"size_pt": 8, "align": "right", "color": "#000000", "spacing_mm": 0})]
    return Layout.model_validate({"schema_version": 3, "page": {"margin_mm": 11, "header_mm": 30, "footer_mm": 5}, "blocks": blocks})
