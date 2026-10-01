"""Synthetic QA PDFs generated at runtime; no manufacturer records or manuals."""

import io

import fitz
from PIL import Image


def manual(*, groups=1, repeated=False, missing=False, landscape=False, rotated=False,
           both=False, language="en", multipage=False, wrapped=False) -> bytes:
    pdf = fitz.open()
    headers = {"en": ["Item", "Part No.", "Description", "Qty"],
               "de": ["Pos.", "Teile-Nr.", "Benennung", "Menge"]}[language]
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
            for x, text in zip([50, 150, 270, 530], headers, strict=True):
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
