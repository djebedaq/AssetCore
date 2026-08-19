from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageDraw, ImageFont

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.catalog.position_mapping import (  # noqa: E402
    PositionCandidate,
    extract_position_candidates,
    mapping_metrics,
)
from app.catalog.sources import (  # noqa: E402
    dataset_sources,
    load_source_dataset,
    source_path,
)

_NUMERIC_GROUP = re.compile(r"(?<![A-Za-z0-9])[0-9]+(?![A-Za-z0-9])")


def _render_overlay(
    *,
    pdf_path: Path,
    page_number: int,
    candidates: list[PositionCandidate],
    output_path: Path,
    scale: float = 2.0,
) -> None:
    with fitz.open(pdf_path) as document:
        page = document[page_number - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for candidate in candidates:
        x0, y0, x1, y1 = (value * scale for value in candidate.text_bbox)
        color = "#008a3b" if candidate.accepted else "#d1242f"
        draw.rectangle((x0 - 3, y0 - 3, x1 + 3, y1 + 3), outline=color, width=2)
        label = f"{candidate.position}/{candidate.occurrence}"
        draw.text((x0, max(0, y0 - 13)), label, fill=color, font=font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def _ocr_candidates(
    *,
    engine: Any,
    pdf_path: Path,
    source_id: str,
    diagram_pages: list[int],
    bom_positions: set[str],
    render_dir: Path | None,
    scale: float = 3.0,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    accepted: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    numeric_evidence: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for page_number in diagram_pages:
            page = document[page_number - 1]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            page_candidates: list[dict[str, Any]] = []
            rotations = (0, 90, 270) if source_id.startswith("hydwin_") else (0,)
            rows_with_rotation: list[tuple[Any, str, float, int]] = []
            for rotation in rotations:
                rotated = image if rotation == 0 else image.rotate(rotation, expand=True)
                rows, _ = engine(rotated)
                rows_with_rotation.extend(
                    (box, text, confidence, rotation)
                    for box, text, confidence in (rows or [])
                )
            for box, text, confidence, rotation in rows_with_rotation:
                groups = [match.group(0) for match in _NUMERIC_GROUP.finditer(str(text))]
                matching = [group for group in groups if group in bom_positions]
                original_points: list[tuple[float, float]] = []
                for point in box:
                    rotated_x, rotated_y = float(point[0]), float(point[1])
                    if rotation == 90:
                        original_points.append((image.width - rotated_y, rotated_x))
                    elif rotation == 270:
                        original_points.append((rotated_y, image.height - rotated_x))
                    else:
                        original_points.append((rotated_x, rotated_y))
                xs = [point[0] / scale for point in original_points]
                ys = [point[1] / scale for point in original_points]
                x0, x1 = min(xs), max(xs)
                y0, y1 = min(ys), max(ys)
                evidence = {
                    "source_id": source_id,
                    "page": page_number,
                    "ocr_text": str(text),
                    "ocr_confidence": float(confidence),
                    "ocr_rotation": rotation,
                    "matching_bom_positions": matching,
                    "text_bbox": [x0, y0, x1, y1],
                }
                if any(character.isdigit() for character in str(text)):
                    numeric_evidence.append(dict(evidence))
                if (
                    len(groups) == 1
                    and len(matching) == 1
                    and str(text).strip(" .,:;()[]") == matching[0]
                ):
                    position = matching[0]
                    evidence.update(
                        {
                            "position": position,
                            "x": max(0.0, x0 - 2.5) / page.rect.width,
                            "y": max(0.0, y0 - 2.5) / page.rect.height,
                            "width": min(page.rect.width, x1 + 2.5)
                            / page.rect.width
                            - max(0.0, x0 - 2.5) / page.rect.width,
                            "height": min(page.rect.height, y1 + 2.5)
                            / page.rect.height
                            - max(0.0, y0 - 2.5) / page.rect.height,
                            "verification_method": "OCR_CANDIDATE_REQUIRES_VISUAL_REVIEW",
                        }
                    )
                    accepted.append(evidence)
                    page_candidates.append(evidence)
                elif matching:
                    evidence["reason"] = "OCR_GROUP_REQUIRES_MANUAL_SPLIT_OR_REVIEW"
                    ambiguous.append(evidence)

            if render_dir is not None:
                draw = ImageDraw.Draw(image)
                font = ImageFont.load_default()
                for candidate in page_candidates:
                    x0, y0, x1, y1 = (
                        value * scale for value in candidate["text_bbox"]
                    )
                    draw.rectangle((x0, y0, x1, y1), outline="#0067c5", width=3)
                    draw.text(
                        (x0, max(0, y0 - 16)),
                        candidate["position"],
                        fill="#0067c5",
                        font=font,
                    )
                render_dir.mkdir(parents=True, exist_ok=True)
                image.save(render_dir / f"{source_id}-page-{page_number}.png")
    return accepted, ambiguous, numeric_evidence


def build_audit(
    *,
    render_dir: Path | None = None,
    use_ocr: bool = False,
    ocr_render_dir: Path | None = None,
    source_ids: set[str] | None = None,
    ocr_scale: float = 3.0,
) -> dict[str, Any]:
    report: dict[str, Any] = {"sources": [], "totals": {}}
    totals = {
        "diagram_page_count": 0,
        "bom_position_count": 0,
        "diagram_position_count": 0,
        "candidate_occurrence_count": 0,
        "duplicate_callout_count": 0,
        "unresolved_bom_position_count": 0,
        "false_numeric_candidate_count": 0,
    }
    ocr_engine: Any = None
    if use_ocr:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover - optional analyst dependency
            raise RuntimeError(
                "--ocr requires the optional rapidocr-onnxruntime analyst tool"
            ) from exc
        # Diagram pages are A4/A3-like sheets with small vector-outline callouts.
        # Keep the detector close to the rendered page size so single-digit labels
        # are not lost during the detector's default down-scaling.
        ocr_engine = RapidOCR(det_limit_side_len=max(3000, int(ocr_scale * 1000)))

    for source in dataset_sources():
        if source_ids and source["source_id"] not in source_ids:
            continue
        diagram_pages = list(source.get("diagram_pages") or [])
        if not diagram_pages:
            continue
        payload = load_source_dataset(source)
        bom_positions = {
            str(record["position"])
            for record in payload.get("records") or []
            if str(record.get("position") or "").strip()
        }
        candidates = extract_position_candidates(
            pdf_path=source_path(source),
            source_id=source["source_id"],
            diagram_pages=diagram_pages,
            bom_positions=bom_positions,
        )
        metrics = mapping_metrics(candidates=candidates, bom_positions=bom_positions)
        source_report = {
            "source_id": source["source_id"],
            "family": source["family"],
            "assembly": source["assembly"],
            "diagram_pages": diagram_pages,
            **metrics,
            "candidates": [candidate.as_dict() for candidate in candidates],
        }
        if ocr_engine is not None:
            ocr_candidates, ocr_ambiguous, ocr_numeric_evidence = _ocr_candidates(
                engine=ocr_engine,
                pdf_path=source_path(source),
                source_id=source["source_id"],
                diagram_pages=diagram_pages,
                bom_positions=bom_positions,
                render_dir=ocr_render_dir,
                scale=ocr_scale,
            )
            source_report["ocr_candidates"] = ocr_candidates
            source_report["ocr_ambiguous"] = ocr_ambiguous
            source_report["ocr_numeric_evidence"] = ocr_numeric_evidence
        report["sources"].append(source_report)
        totals["diagram_page_count"] += len(diagram_pages)
        for key in totals:
            if key != "diagram_page_count":
                totals[key] += int(metrics[key])

        if render_dir is not None:
            for page_number in diagram_pages:
                _render_overlay(
                    pdf_path=source_path(source),
                    page_number=page_number,
                    candidates=[
                        candidate
                        for candidate in candidates
                        if candidate.page == page_number
                    ],
                    output_path=(
                        render_dir / f"{source['source_id']}-page-{page_number}.png"
                    ),
                )
    report["totals"] = totals
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract BOM-constrained PDF text geometry candidates. The utility never "
            "marks candidates as verified and never edits authoritative source files."
        )
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--render-overlays", type=Path)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--render-ocr-overlays", type=Path)
    parser.add_argument("--ocr-scale", type=float, default=3.0)
    parser.add_argument("--source-id", action="append", dest="source_ids")
    arguments = parser.parse_args()

    report = build_audit(
        render_dir=arguments.render_overlays,
        use_ocr=arguments.ocr,
        ocr_render_dir=arguments.render_ocr_overlays,
        source_ids=set(arguments.source_ids or []),
        ocr_scale=arguments.ocr_scale,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(f"{encoded}\n", encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
