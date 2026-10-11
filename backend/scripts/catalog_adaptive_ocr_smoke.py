"""Real offline runtime smoke: synthetic raster evidence, never OEM fixtures."""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # noqa: E402
from app.catalog_admin.parts_extraction.process import configuration, extract  # noqa: E402
from app.settings import settings  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402


def fixture(*, rotation=0, skew=0, alpha=False, scale=1, ruled=True, partial=False, language="en"):
    image = Image.new("RGBA" if alpha else "RGB", (1600, 650), (255, 255, 255, 0) if alpha else "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("DejaVuSans.ttf", 28)
    xs, ys = [40, 180, 540, 1300, 1560], [70, 140, 240, 340, 480]
    records = [["Pos", "Part No.", "Description", "Qty"],
        ["1", "QA-0001-A.02", "QA synthetic housing", "2"],
        ["13A", "QA-0013", "QA synthetic seal", "" if partial else "12"],
        ["9", "QA-0009", "QA item\nwrapped description", "3"]]
    if language == "de":
        records[0] = ["Pos.", "Teile-Nr.", "Benennung", "Menge"]
        for row, description in zip(records[1:], ["QA synthetisches Gehäuse", "QA Dichtung", "QA Teil\nmehrzeilige Beschreibung"], strict=True):
            row[2] = description
    if ruled:
        for x in xs:
            draw.line((x, ys[0], x, ys[-1]), fill="black", width=2)
        for y in ys:
            draw.line((xs[0], y, xs[-1], y), fill="black", width=2)
    for row, record in enumerate(records):
        for col, value in enumerate(record):
            draw.multiline_text((xs[col] + 12, ys[row] + 24), value, font=font, fill="black", spacing=10)
    if skew:
        image = image.rotate(skew, resample=Image.Resampling.BICUBIC, fillcolor="white")
    if rotation:
        image = image.rotate(rotation, expand=True, fillcolor="white")
    if scale != 1:
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    with fitz.open() as pdf:
        page = pdf.new_page(width=image.width * .4, height=image.height * .4)
        page.insert_image(page.rect, stream=buffer.getvalue())
        return pdf.tobytes()


def main():
    cases = [{}, {"alpha": True}, {"rotation": 90}, {"rotation": 180}, {"rotation": 270},
        {"skew": 1.5}, {"scale": .75}, {"scale": 1.5}, {"ruled": False}, {"partial": True}, {"language": "de"}]
    results = []
    for case in cases:
        result = extract(fixture(**case), "page", 1, configuration(settings))
        assert not result.get("error"), (case, result.get("error"))
        rows = result["rows"]
        assert len(rows) == 3, (case, len(rows), result["warnings"])
        assert [row["payload"]["position"] for row in rows] == ["1", "13A", "9"], (case, "position")
        assert [row["payload"]["part_number"] for row in rows] == ["QA-0001-A.02", "QA-0013", "QA-0009"], (case, "identifier")
        assert [row["payload"]["quantity"] for row in rows] == ["2", None if case.get("partial") else "12", "3"], (case, "quantity")
        german = case.get("language") == "de"
        assert rows[0]["payload"]["description"] == ("QA synthetisches Gehäuse" if german else "QA synthetic housing"), (case, "description")
        assert ("mehrzeilige Beschreibung" if german else "wrapped description") in rows[2]["payload"]["description"], (case, "wrapped")
        if german:
            assert result["tables"][0]["ocr_profile"]["description_language"] == "deu"
        assert all(row["bbox"] and row["provenance"]["physical_page"] == 1 for row in rows)
        if case.get("alpha"):
            assert result["tables"][0]["raster"]["mask"]
        if case.get("partial"):
            assert result["quality"]["state"] == "NEEDS_REVIEW"
        results.append({"case": case, "rows": len(rows), "quality": result["quality"], "metrics": result["metrics"]})
    print(json.dumps({"passed": True, "cases": results}))


if __name__ == "__main__":
    main()
