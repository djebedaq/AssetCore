"""Synthetic QA PDFs generated at runtime; no manufacturer records or manuals."""

import io

import fitz
from PIL import Image


def manual(*, groups=1, repeated=False, missing=False, landscape=False, rotated=False,
           both=False, language="en", multipage=False, wrapped=False, item_description=False,
           centered_headers=False) -> bytes:
    pdf = fitz.open()
    headers = {"en": ["Item", "Part No.", "Description", "Qty"],
               "de": ["Pos.", "Teile-Nr.", "Benennung", "Menge"]}[language]
    if item_description:
        headers = ["No.", "Part No.", "Item", "Qty"]
    for group in range(groups):
        name = f"QA ASSEMBLY {group + 1}"
        page = pdf.new_page(width=842 if landscape else 595, height=595 if landscape else 842)
        page.insert_text((50, 40), name, fontsize=18)
        page.insert_text((50, 70), "Exploded view", fontsize=12)
        for index, value in enumerate(["1", "13A", "13.1", "A12"]):
            if missing and value == "A12":
                continue
            page.insert_text((100 + 80 * index, 140 + 60 * index), value, fontsize=10)
        page.draw_rect(fitz.Rect(60, 100, 440, 370))
        if repeated:
            page.insert_text((450, 320), "13A", fontsize=10)
        if rotated:
            page.set_rotation(90)
        for continuation in range(2 if multipage else 1):
            if not both or continuation:
                page = pdf.new_page(width=842 if landscape else 595, height=595 if landscape else 842)
                page.insert_text((50, 40), name, fontsize=18)
            y = 430 if both and not continuation else 100
            for x, text in zip([55, 215, 370, 540] if centered_headers else [50, 150, 270, 530], headers, strict=True):
                if centered_headers:
                    x -= fitz.get_text_length(text, fontsize=10) / 2
                page.insert_text((x, y), text, fontsize=10)
            for row, pos in enumerate(["1", "13A", "13.1", "A12"]):
                for x, text in zip([50, 150, 270, 530], [pos, f"QA-{group}-{row}", "QA component", "2.5"], strict=True):
                    page.insert_text((x, y + 25 + row * 40), text, fontsize=10)
                if wrapped:
                    page.insert_text((270, y + 38 + row * 40), "continued description", fontsize=10)
    result = pdf.tobytes()
    pdf.close()
    return result


def scanned(*, mixed=False) -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    image = Image.new("RGB", (400, 400), "white")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    page.insert_image(fitz.Rect(0, 0, 595, 842), stream=stream.getvalue())
    if mixed:
        source = fitz.open(stream=manual(), filetype="pdf")
        pdf.insert_pdf(source)
        source.close()
    result = pdf.tobytes()
    pdf.close()
    return result


def encrypted() -> bytes:
    with fitz.open(stream=manual(), filetype="pdf") as pdf:
        return pdf.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="qa-owner", user_pw="qa-reader")


def cyrillic_manual(language="bg") -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_font(fontname="qa-cyrillic", fontbuffer=fitz.Font("cjk").buffer)
    page.insert_text((50, 40), "QA ВЪЗЕЛ" if language == "bg" else "QA УЗЕЛ", fontname="qa-cyrillic", fontsize=18)
    headings = ["позиция", "номер част" if language == "bg" else "номер детали", "описание", "количество"]
    for x, text in zip([30, 130, 300, 480], headings, strict=True):
        page.insert_text((x, 100), text, fontname="qa-cyrillic", fontsize=10)
    for x, text in zip([30, 130, 300, 480], ["13A", "QA-001", "QA уплътнение" if language == "bg" else "QA уплотнение", "1,5"], strict=True):
        page.insert_text((x, 130), text, fontname="qa-cyrillic", fontsize=10)
    result = pdf.tobytes()
    pdf.close()
    return result


def over_12_mib() -> bytes:
    # An unused uncompressed stream is structurally valid, exact and inexpensive.
    with fitz.open(stream=manual(), filetype="pdf") as pdf:
        xref = pdf.get_new_xref()
        pdf.update_object(xref, "<<>>")
        pdf.update_stream(xref, b"Q" * (13 * 1024 * 1024), compress=False)
        return pdf.tobytes(garbage=0, deflate=False)


def contextual_table(headers=None, rows=None, *, ruled=False, both=False, continuation=False,
                     repeat_header=True, heading=True) -> bytes:
    """Unknown-OEM QA patterns, entirely synthetic, with configurable evidence."""
    headers = headers or ["No.", "Part No.", "Item", "Qty"]
    rows = rows or [["13A", "QA-101", "Seal", "2.5"], ["2", "QA-102", "Bolt M8, DIN (20 mm)", "1200"]]
    with fitz.open() as pdf:
        for index in range(2 if continuation else 1):
            page = pdf.new_page(width=850, height=650)
            if heading and index == 0:
                page.insert_text((30, 35), "QA ROTATING UNIT", fontsize=18)
            if both and index == 0:
                page.insert_text((40, 65), "Exploded view")
                page.draw_rect((30, 90, 300, 210))
                page.insert_text((60, 120), "13A")
                page.insert_text((220, 180), "2")
            top = 250 if both and index == 0 else 100
            xs = [30, 110, 280, 600, 680, 760][:len(headers)] + [830]
            include_header = index == 0 or repeat_header
            records = ([headers] if include_header else []) + rows
            if ruled:
                for x in xs:
                    page.draw_line((x, top - 20), (x, top + len(records) * 30 - 20))
                for row in range(len(records) + 1):
                    page.draw_line((xs[0], top - 20 + row * 30), (xs[-1], top - 20 + row * 30))
            for row, values in enumerate(records):
                for col, value in enumerate(values):
                    page.insert_text((xs[col] + 4, top + row * 30), value, fontsize=10)
        return pdf.tobytes()


def centered_geometry(*, width=720, shifted=0, notes=False, noisy=False, wrapped=False,
                      continuation=False, second_width=None, multiple=False) -> bytes:
    """Geometrically realistic unknown-OEM QA; centered headers over varied cells."""
    with fitz.open() as pdf:
        for number in range(2 if continuation else 1):
            page_width = second_width if number and second_width else width
            page = pdf.new_page(width=page_width, height=650)
            if not number:
                page.insert_text((25, 35), "QA SOURCE UNIT", fontsize=18)
            scale = page_width / 720
            for side in range(2 if multiple else 1):
                local = .48 if multiple else 1
                offset = side * page_width * .5 + shifted * scale
                xs = [50, 190, 390, 600, 660] if notes else [50, 190, 390, 620]
                headers = ["No.", "Part No.", "Item", "Qty"] + (["Remark"] if notes else [])
                font = 8 if multiple else 10
                factor = scale * local
                if not number:
                    for x, header in zip(xs, headers, strict=True):
                        tw = fitz.get_text_length(header, fontsize=font)
                        page.insert_text((offset + x * factor - tw / 2, 100), header, fontsize=font)
                values = [["1", "QA-123456", "Hex Head Bolt", "4"],
                          ["13A", "QA.03-00-0060", "Spring Washer, 10x2.6", "1200"],
                          ["2", "QA-998877665544", "PVC Steel Wire Reinforced Hose", "2.5"]]
                for row, cells in enumerate(values):
                    y = 130 + 40 * row
                    for col, text in enumerate(cells):
                        noise = (-2 if row % 2 else 2) * scale if noisy else 0
                        x = ([45, 125, 290][col] * factor + noise if col < 3 else 630 * factor - fitz.get_text_length(text, fontsize=font))
                        page.insert_text((offset + x, y), text, fontsize=font)
                    if wrapped:
                        page.insert_text((offset + 290 * factor, y + 12), "continued source description", fontsize=font)
                if not multiple:
                    outside = min(offset + 690 * factor, page_width - fitz.get_text_length("Outside", fontsize=font) - 8)
                    page.insert_text((outside, 150), "Outside", fontsize=font)
        return pdf.tobytes()
