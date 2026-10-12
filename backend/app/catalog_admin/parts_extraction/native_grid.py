"""Reconstruct open vector grids from recurring segment endpoints.

Some PDF writers draw each horizontal cell edge without vertical strokes. A
closed-rectangle table detector then finds only the document's title block.
Repeated local endpoints supply column boundaries; text supplies role evidence.
"""

from bisect import bisect_left, bisect_right
from collections import Counter
from statistics import median

from . import panels
from .schema import header_candidates
from .tables import word_lines

MAX_SEGMENTS = 12000
MAX_CELLS = 24000


def clusters(values, tolerance=.8):
    result = []
    for value in sorted(values):
        if not result or value - result[-1][0] > tolerance:
            result.append([value])
        else:
            result[-1].append(value)
    return [median(group) for group in result]


def text(words):
    return "\n".join(" ".join(word["text"] for word in line) for line in word_lines(words))


def extract(page, words, covered=()):
    segments = []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            edges = [(item[1], item[2])] if item[0] == "l" else []
            if item[0] == "re":
                rect = item[1]
                edges = [((rect.x0, rect.y0), (rect.x1, rect.y0)), ((rect.x0, rect.y1), (rect.x1, rect.y1))]
            for first, last in edges:
                if abs(first[1] - last[1]) <= .2 and abs(last[0] - first[0]) >= 4:
                    segments.append((min(first[0], last[0]), max(first[0], last[0]), (first[1] + last[1]) / 2))
                    if len(segments) > MAX_SEGMENTS:
                        return [], [], ["VECTOR_GRID_LIMIT"]
    if not segments:
        return [], [], []
    xs = clusters([value for left, right, _ in segments for value in (left, right)])
    ys = clusters([y for _, _, y in segments])
    def nearest(value, candidates):
        index = bisect_left(candidates, value)
        return min({max(0, index - 1), min(len(candidates) - 1, index)}, key=lambda i: abs(value - candidates[i]))
    bands = {}
    for left, right, y in segments:
        band = bands.setdefault(nearest(y, ys), set())
        band.update((nearest(left, xs), nearest(right, xs)))
    signatures = Counter(tuple(sorted(points)) for points in bands.values() if len(points) >= 4)
    rows, tables = [], []
    used = 0
    for signature, support in signatures.most_common(80):
        if support < 3:
            continue
        edges = [xs[i] for i in signature]
        levels = sorted(ys[i] for i, points in bands.items() if set(signature) <= points)
        bbox = [edges[0], levels[0], edges[-1], levels[-1]]
        if any(left <= bbox[0] + 1 and top <= bbox[1] + 1 and right >= bbox[2] - 1 and bottom >= bbox[3] - 1
                for left, top, right, bottom in covered):
            continue
        used += (len(edges) - 1) * (len(levels) - 1)
        if used > MAX_CELLS:
            return rows, tables, ["VECTOR_GRID_LIMIT"]
        assigned = [[[] for _ in edges[:-1]] for _ in levels[:-1]]
        for word in words:
            box = word["bbox"]
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            col, row = bisect_right(edges, cx) - 1, bisect_right(levels, cy) - 1
            if 0 <= col < len(edges) - 1 and 0 <= row < len(levels) - 1:
                assigned[row][col].append(word)
        cells = [[text(cell) for cell in row] for row in assigned]
        if not cells:
            continue
        # A physical grid alone cannot distinguish a BOM from metadata.
        hints = [header_candidates(value) for value in cells[0]]
        if not all(any(role in hint for hint in hints) for role in ("position", "part_number", "description", "quantity")):
            continue
        # A blank gutter has no horizontal cell edge. It is not an extra column
        # to be guessed into either neighbouring panel. Never discard populated
        # cells, even if their borders are damaged.
        gaps = {i for i, (left, right) in enumerate(zip(edges, edges[1:]))
            if not any(row[i].strip() for row in cells) and not any(
                a < (left + right) / 2 < b for a, b, y in segments if levels[0] - .8 <= y <= levels[-1] + .8)}
        cuts = [0, *sorted(gaps), len(edges) - 1]
        islands = [(start + int(start in gaps), end) for start, end in zip(cuts, cuts[1:])]
        extracted, proposed = [], []
        for start, end in islands:
            if end - start < 3:
                continue
            boxes = [[edges[start], top, edges[end], bottom] for top, bottom in zip(levels[1:-1], levels[2:])]
            parts, regions = panels.parse(cells[0][start:end], [row[start:end] for row in cells[1:]], boxes,
                [edges[start], bbox[1], edges[end], bbox[3]], edges[start:end + 1])
            extracted.extend(parts)
            proposed.extend(regions)
        for table in proposed:
            local = table["geometry"]["boundaries"]
            table.update({"page_width": page.cropbox.width, "vector_grid": True,
                "cell_geometry": [[[left, box[1], right, box[3]] for left, right in zip(local, local[1:])]
                    for box in table["row_boxes"]]})
            table["geometry"]["normalized_boundaries"] = [edge / page.cropbox.width for edge in local]
        rows.extend(extracted)
        tables.extend(proposed)
    return rows, tables, []
