"""Source heading hierarchy: distinguish a peripheral running header from a title."""

import re


def select_heading(candidates: list[dict], width: float, height: float, role_words) -> tuple[str | None, dict]:
    valid = []
    for candidate in candidates:
        text = role_words.sub("", candidate["text"]).strip(" -—:·")
        if len(text) >= 3 and not re.fullmatch(r"[\d\W]+", text):
            valid.append({**candidate, "source_name": text})
    if not valid:
        return None, {}
    valid.sort(key=lambda item: (item.get("method") == "OCR", -item["size"], item["bbox"][1]))
    first = valid[0]
    center = (first["bbox"][0] + first["bbox"][2]) / (2 * width)
    if first["bbox"][1] < height * .08 and not .25 <= center <= .75:
        children = [item for item in valid[1:]
            if .25 <= (item["bbox"][0] + item["bbox"][2]) / (2 * width) <= .75
            and first["bbox"][3] <= item["bbox"][1] < height * .2
            and item["size"] >= first["size"] * .75]
        if children:
            child = min(children, key=lambda item: item["bbox"][1])
            return child["source_name"], {"method": "NESTED_TITLE", "selected": child,
                                          "running_header": first, "inferred": True}
    return first["source_name"], {"method": "TYPOGRAPHY", "selected": first, "inferred": False}
