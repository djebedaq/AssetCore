"""Synthetic PDF generated only inside disposable QA environments."""

import fitz


def workflow_pdf():
    with fitz.open() as pdf:
        for number in range(1, 7):
            page = pdf.new_page(width=850, height=650)
            page.insert_text((30, 40), f"Synthetic QA only - physical PDF page {number}")
            if number in {1, 4}:
                page.draw_rect((50, 80, 800, 600))
                for position in range(1, 20):
                    page.insert_text((80 + (position - 1) % 5 * 140, 150 + (position - 1) // 5 * 100), str(position), fontsize=18)
                continue
            start, count = {2: (1, 7), 3: (8, 6), 5: (14, 6), 6: (1, 2)}[number]
            rows = [["No.", "Part No.", "Description", "Qty"]] + [
                [str(index), f"QA-{number}-{index}", "Synthetic QA component", "2"] for index in range(start, start + count)]
            xs = [30, 110, 280, 600, 830]
            for x in xs:
                page.draw_line((x, 80), (x, 80 + len(rows) * 30))
            for index in range(len(rows) + 1):
                page.draw_line((xs[0], 80 + index * 30), (xs[-1], 80 + index * 30))
            for index, row in enumerate(rows):
                for x, value in zip(xs, row, strict=False):
                    page.insert_text((x + 4, 100 + index * 30), value, fontsize=10)
        return pdf.tobytes()
