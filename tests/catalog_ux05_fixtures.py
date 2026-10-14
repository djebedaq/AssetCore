"""Generated synthetic QA only; never an industrial catalog or stored DB."""
import fitz


def publication_pdf():
    with fitz.open() as pdf:
        for scheme in range(3):
            page = pdf.new_page(width=850, height=650)
            page.insert_text((40, 40), f"Synthetic QA scheme {scheme + 1}", fontsize=18)
            for index in range(scheme * 20, min(59, (scheme + 1) * 20)):
                page.insert_text((80 + index % 5 * 140, 120 + index % 20 // 5 * 100), str(index + 1), fontsize=14)
        for number, count in enumerate([15, 15, 15, 14]):
            page = pdf.new_page(width=850, height=650)
            page.insert_text((40, 40), "Synthetic QA parts list", fontsize=18)
            xs = [30, 110, 280, 600, 830]
            rows = [["No.", "Part No.", "Description", "Qty"]] + [
                [str(number * 15 + row + 1), f"QA-UX05-{number * 15 + row + 1:03}", "QA component", "2"]
                for row in range(count)]
            for x in xs:
                page.draw_line((x, 80), (x, 80 + len(rows) * 30))
            for row in range(len(rows) + 1):
                page.draw_line((xs[0], 80 + row * 30), (xs[-1], 80 + row * 30))
            for row, values in enumerate(rows):
                for x, value in zip(xs, values, strict=False):
                    page.insert_text((x + 4, 100 + row * 30), value, fontsize=10)
        return pdf.tobytes()
