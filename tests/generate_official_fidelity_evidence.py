"""Compare actual legacy and controlled native output with identical QA inputs.

Run only on an isolated converter host. No database is opened. Private user
references are never read, copied or embedded in this evidence generator.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import fitz
from app.document_studio.diagnostics import legacy_preview, request_sample
from app.document_studio.renderer import pdf_required, render, synthetic_values
from app.documents.common import TEXT
from docx import Document
from docx.oxml.ns import qn
from PIL import Image, ImageChops
from test_official_document_fidelity import manifest, template

CASES = {"transfer-issue": ("TRANSFER_ISSUE", "MACHINE"),
         "transfer-return": ("TRANSFER_RETURN", "MACHINE"),
         "repair-protocol": ("REPAIR_PROTOCOL", "MACHINE"),
         "kk-machine": ("PART_REQUEST", "MACHINE"), "kk-free": ("PART_REQUEST", "FREE_FORM")}


def native_text(raw):
    doc = Document(io.BytesIO(raw))
    parts = [doc.element, doc.sections[0].header._element, doc.sections[0].footer._element]
    return [n.text or "" for part in parts for n in part.iter(qn("w:t"))]


def generate(root, languages, counts, cases):
    reports = []
    for case in cases:
        typ, variant = CASES[case]
        for language in languages:
            m = manifest(typ, language)
            v = template(typ, language)
            for count in counts:
                target = root / case / f"{language}-{count}"
                target.mkdir(parents=True, exist_ok=True)
                legacy_docx, legacy_pdf, _ = legacy_preview(v, count, variant, raster=False)
                if typ == "PART_REQUEST":
                    _, values, tables = request_sample(language, count, variant)
                else:
                    values, tables = synthetic_values(language, count)
                    values["CONDITION_LABEL"] = TEXT[language]["overall_condition"]
                studio_docx = render(m, values, tables)
                studio_pdf = pdf_required(studio_docx)
                for name, raw in (("legacy.docx", legacy_docx), ("legacy.pdf", legacy_pdf),
                                  ("studio.docx", studio_docx), ("studio.pdf", studio_pdf)):
                    (target / name).write_bytes(raw)
                with fitz.open(stream=legacy_pdf, filetype="pdf") as before, fitz.open(stream=studio_pdf, filetype="pdf") as after:
                    page_reports = []
                    for i in range(max(len(before), len(after))):
                        images = []
                        for name, pdf in (("legacy", before), ("studio", after)):
                            if i < len(pdf):
                                pix = pdf[i].get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
                                raw = pix.tobytes("png")
                                (target / f"{name}-page-{i + 1}.png").write_bytes(raw)
                                images.append(Image.open(io.BytesIO(raw)).convert("RGB"))
                            else:
                                images.append(Image.new("RGB", images[0].size if images else (744, 1053), "white"))
                        width, height = max(im.width for im in images), max(im.height for im in images)
                        canvas = Image.new("RGB", (width * 2, height), "white")
                        for j, image in enumerate(images):
                            canvas.paste(image, (j * width, 0))
                        canvas.save(target / f"comparison-page-{i + 1}.png")
                        if images[0].size == images[1].size:
                            delta = ImageChops.difference(*images).convert("L")
                            hist = delta.histogram()
                            changed = 1 - hist[0] / (width * height)
                        else:
                            changed = 1
                        page_reports.append({"page": i + 1, "changed_pixel_fraction": changed})
                    report = {"case": case, "language": language, "rows": count,
                        "legacy_pages": len(before), "studio_pages": len(after),
                        "pdf_text_equal": "\n".join(p.get_text() for p in before) == "\n".join(p.get_text() for p in after),
                        "native_text_equal": native_text(legacy_docx) == native_text(studio_docx),
                        "pages": page_reports}
                (target / "comparison.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                reports.append(report)
                print(json.dumps(report), flush=True)
    (root / "comparison-results.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("docs/qa/official-document-fidelity"))
    parser.add_argument("--languages", nargs="+", default=["bg", "en", "ru"])
    parser.add_argument("--counts", nargs="+", type=int, default=[1, 5, 30])
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    args = parser.parse_args()
    generate(args.root, args.languages, args.counts, args.cases)
