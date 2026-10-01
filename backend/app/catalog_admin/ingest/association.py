"""Conservative section/continuation evidence shared by persisted and QA runs."""


def table_signature(table: dict, width: float) -> tuple:
    schema = table.get("schema", {})
    return (tuple(schema.get("mapping", {}).values()),
            tuple(round(h["center"] / max(1, width), 2) for h in table.get("header_geometry", []))
            or tuple(round(x / max(1, width), 2) for x in table.get("anchors", [])))


def relationship(previous: dict | None, current: dict) -> str | None:
    if not previous or previous["role"] == "OTHER" or current["role"] == "OTHER":
        return None
    if current.get("heading"):
        return "SAME_HEADING" if current["heading"].casefold() == (previous.get("heading") or "").casefold() else None
    old = {table_signature(table, previous["unrotated_width"]) for table in previous.get("tables", [])
           if table.get("schema", {}).get("state") == "RESOLVED"}
    new = {table_signature(table, current["unrotated_width"]) for table in current.get("tables", [])
           if table.get("schema", {}).get("state") == "RESOLVED"}
    if old & new:
        return "TABLE_CONTINUATION"
    labels = {label["text"] for label in previous.get("labels", [])}
    positions = {row["payload"]["position"] for row in current.get("rows", [])}
    if labels and positions and len(labels & positions) >= 2 and len(labels & positions) / len(positions) >= .6:
        return "POSITION_VOCABULARY"
    return None
