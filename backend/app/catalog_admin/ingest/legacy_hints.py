"""Preserved conservative manual hints, also reusable from cached page text."""

import re


def suggestions(texts) -> dict:
    output, headings = [], []
    for number, raw in texts:
        text = raw[:16000]
        normalized = text.casefold()
        role = None
        if (re.search(r"part\s*(no|number|№)|номер.*част|номер.*детал", normalized)
                and re.search(r"\bqty\b|quantity|количество|количество", normalized)):
            role = "SPARE_PARTS_LIST"
        elif re.search(r"exploded\s+(view|scheme)|разглобена\s+схема|взрыв.?схема", normalized):
            role = "EXPLODED_SCHEME"
        candidates = [line.strip() for line in text.splitlines() if 3 <= len(line.strip()) <= 100
                      and re.search(r"\b(assembly|system)\b|възел|система|узел", line, re.I)]
        heading = candidates[0] if candidates else None
        if heading and heading not in headings and len(headings) < 50:
            headings.append(heading)
        if role or heading:
            output.append({"page_number": number, "suggested_role": role, "suggested_group_name": heading})
    return {"pages": output, "group_names": headings, "requires_confirmation": True}
