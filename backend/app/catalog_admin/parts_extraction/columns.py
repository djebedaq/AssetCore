"""Bounded geometric column regions, independent of semantic field roles."""

from statistics import median


def header_geometry(text: str, words: list[dict]) -> dict:
    bbox = [min(w["bbox"][0] for w in words), min(w["bbox"][1] for w in words),
            max(w["bbox"][2] for w in words), max(w["bbox"][3] for w in words)]
    return {"text": text, "bbox": bbox, "x0": bbox[0], "x1": bbox[2],
            "center": (bbox[0] + bbox[2]) / 2, "width": bbox[2] - bbox[0]}


def assign_words(words: list[dict], boundaries: list[float]) -> tuple[list[str], list[dict], int]:
    cells = [""] * (len(boundaries) - 1)
    assignments, conflicts = [], 0
    for word in sorted(words, key=lambda w: w["bbox"][0]):
        x0, _, x1, _ = word["bbox"]
        center = (x0 + x1) / 2
        if not boundaries[0] <= center <= boundaries[-1]:
            continue
        overlaps = [max(0., min(x1, right) - max(x0, left)) for left, right in zip(boundaries, boundaries[1:])]
        col = max(range(len(overlaps)), key=overlaps.__getitem__)
        share = overlaps[col] / max(.01, x1 - x0)
        conflict = share < .75
        conflicts += int(conflict)
        cells[col] = (cells[col] + " " + word["text"]).strip()
        assignments.append({"text": word["text"], "bbox": word["bbox"], "column": col,
                            "overlap": round(share, 4), "conflict": conflict})
    return cells, assignments, conflicts


def infer_columns(headers: list[dict], lines: list[list[dict]], left: float, right: float,
                  width: float) -> dict:
    """Header priors plus repeated whitespace gutters. <=32 rows, 16-beam."""
    centers = [header["center"] for header in headers]
    def nearest(word):
        center = (word["bbox"][0] + word["bbox"][2]) / 2
        return min(range(len(centers)), key=lambda i: abs(centers[i] - center))

    # Wrapped descriptions and disconnected annotations cannot define gutters.
    # They are assigned afterwards using geometry learned from populated rows.
    sample = [line for line in lines[:32]
              if len({nearest(w) for w in line}) >= min(3, len(headers))]
    height = median([max(1., w["bbox"][3] - w["bbox"][1]) for line in sample for w in line]) if sample else 10.
    run_columns = {}
    for line in sample:
        runs = []
        for word in line:
            if runs and word["bbox"][0] - runs[-1][-1]["bbox"][2] <= height:
                runs[-1].append(word)
            else:
                runs.append([word])
        for run in runs:
            column = nearest({"bbox": [run[0]["bbox"][0], 0, run[-1]["bbox"][2], 0]})
            run_columns.update((id(word), column) for word in run)
    # Nearest edge-column run bounds exclude disconnected side annotations.
    edge_runs = [[], []]
    for line in sample:
        for edge, center in enumerate((centers[0], centers[-1])):
            eligible = [w for w in line if left <= (w["bbox"][0] + w["bbox"][2]) / 2 <= right]
            if not eligible:
                continue
            seed = min(eligible, key=lambda w: abs((w["bbox"][0] + w["bbox"][2]) / 2 - center))
            spacing = centers[1] - centers[0] if edge == 0 else centers[-1] - centers[-2]
            if abs((seed["bbox"][0] + seed["bbox"][2]) / 2 - center) > max(2 * height, spacing * .4):
                continue
            run = [seed]
            current = seed
            for word in sorted(eligible, key=lambda w: w["bbox"][0], reverse=edge == 0):
                gap = current["bbox"][0] - word["bbox"][2] if edge == 0 else word["bbox"][0] - current["bbox"][2]
                outward = word["bbox"][0] < current["bbox"][0] if edge == 0 else word["bbox"][0] > current["bbox"][0]
                if outward and 0 <= gap <= height:
                    run.append(word)
                    current = word
            edge_runs[edge].extend(run)
    outer_left = max(left, min([headers[0]["x0"]] + [w["bbox"][0] for w in edge_runs[0]]) - height * .4)
    outer_right = min(right, max([headers[-1]["x1"]] + [w["bbox"][2] for w in edge_runs[1]]) + height * .4)
    choices = []
    for index, (first, second) in enumerate(zip(centers, centers[1:])):
        prior = (first + second) / 2
        points = {prior}
        for line in sample:
            for a, b in zip(line, line[1:]):
                if run_columns[id(a)] != index or run_columns[id(b)] != index + 1:
                    continue
                lo, hi = max(first, a["bbox"][2]), min(second, b["bbox"][0])
                if hi - lo >= height:
                    points.add((lo + hi) / 2)
        scored = []
        for point in sorted(points):
            gaps, crossings = [], 0
            for line in sample:
                before = [w["bbox"][2] for w in line if w["bbox"][2] <= point and run_columns[id(w)] == index]
                after = [w["bbox"][0] for w in line if w["bbox"][0] >= point and run_columns[id(w)] == index + 1]
                crossings += int(any(w["bbox"][0] < point < w["bbox"][2] for w in line))
                crossings += int(any(a["bbox"][2] <= point <= b["bbox"][0]
                                     and b["bbox"][0] - a["bbox"][2] < height for a, b in zip(line, line[1:])))
                if before and after:
                    gaps.append(min(after) - max(before))
            support = sum(gap >= height for gap in gaps) / max(1, len(sample))
            score = 3 * support - 4 * crossings / max(1, len(sample))
            score += min(1.5, median(gaps) / max(1, height) * .15) if gaps else 0
            score -= .3 * abs(point - prior) / max(height, second - first)
            scored.append((score, point))
        choices.append(sorted(scored, reverse=True)[:3])
    beam = [(0., [outer_left])]
    for options in choices:
        beam = sorted([(score + quality, bounds + [point]) for score, bounds in beam
                       for quality, point in options if point > bounds[-1]], reverse=True)[:16]
    alternatives = []
    signatures = set()
    for score, bounds in beam:
        bounds = bounds + [outer_right]
        if bounds[-1] <= bounds[-2]:
            continue
        assignments = [assign_words(line, bounds) for line in sample]
        cells = [item[0] for item in assignments]
        signature = tuple(tuple(row) for row in cells)
        if signature in signatures:
            continue
        signatures.add(signature)
        conflicts = sum(item[2] for item in assignments)
        occupied = [sum(bool(cell) for cell in row) for row in cells]
        coherence = sum(count >= min(3, len(headers)) for count in occupied) / max(1, len(occupied))
        alternatives.append({"boundaries": bounds, "score": round(score + 2 * coherence - conflicts, 4),
                             "coherence": coherence, "conflicts": conflicts, "sample_cells": cells[:5]})
    alternatives.sort(key=lambda item: item["score"], reverse=True)
    if not alternatives:
        return {"state": "NEEDS_REVIEW", "boundaries": [], "alternatives": [], "warnings": ["GEOMETRY_AMBIGUOUS"]}
    best = alternatives[0]
    ambiguous = best["conflicts"] > 0 or best["coherence"] < .5 or (len(alternatives) > 1 and best["score"] - alternatives[1]["score"] < .6)
    return {**best, "state": "NEEDS_REVIEW" if ambiguous else "RESOLVED", "alternatives": alternatives[:4],
            "populated_rows": len(sample),
            "normalized_boundaries": [round(x / width, 8) for x in best["boundaries"]],
            "warnings": ["GEOMETRY_AMBIGUOUS"] if ambiguous else []}
