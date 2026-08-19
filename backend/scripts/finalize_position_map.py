from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.catalog.sources import CATALOG_ROOT, dataset_sources, load_source_dataset  # noqa: E402

PROVENANCE = (
    "MANUAL_VISUAL_VERIFICATION: геометричен кандидат от векторния етикет е "
    "съпоставен визуално с контролираната оригинална PDF страница; OCR не е "
    "използван като самостоятелно доказателство."
)


def _position_sort(value: str) -> tuple[int, str]:
    return (int(value), value) if value.isdigit() else (10**9, value)


def _in_zone(candidate: dict[str, Any], zone: dict[str, Any]) -> bool:
    if zone["source_id"] not in {"*", candidate["source_id"]}:
        return False
    if zone.get("page") is not None and zone["page"] != candidate["page"]:
        return False
    if zone.get("positions") and candidate["position"] not in zone["positions"]:
        return False
    for name in ("x", "y"):
        value = float(candidate[name])
        if zone.get(f"{name}_min") is not None and value < zone[f"{name}_min"]:
            return False
        if zone.get(f"{name}_max") is not None and value > zone[f"{name}_max"]:
            return False
    return True


def _same_occurrence(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if (left["source_id"], left["page"], left["position"]) != (
        right["source_id"],
        right["page"],
        right["position"],
    ):
        return False
    left_center = (left["x"] + left["width"] / 2, left["y"] + left["height"] / 2)
    right_center = (
        right["x"] + right["width"] / 2,
        right["y"] + right["height"] / 2,
    )
    return math.dist(left_center, right_center) <= 0.012


def _load_ocr_candidates(paths: list[Path]) -> tuple[list[dict[str, Any]], int]:
    candidates: list[dict[str, Any]] = []
    pdf_false_candidates: set[tuple[Any, ...]] = set()
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        for source in report.get("sources") or []:
            for item in source.get("candidates") or []:
                if not item.get("accepted"):
                    pdf_false_candidates.add(
                        (
                            item["source_id"],
                            item["page"],
                            item["position"],
                            *[round(float(value), 3) for value in item["text_bbox"]],
                        )
                    )
            for item in source.get("ocr_candidates") or []:
                candidate = dict(item)
                candidate["position"] = str(candidate["position"])
                candidates.append(candidate)
    return candidates, len(pdf_false_candidates)


def finalize(
    *, audit_paths: list[Path], review_path: Path, write: bool
) -> dict[str, Any]:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    raw_candidates, pdf_false_count = _load_ocr_candidates(audit_paths)
    zones = list(review.get("exclusion_zones") or [])
    excluded: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []

    rotation_policy = review.get("rotation_policy") or {}
    primary_positions: dict[str, set[str]] = defaultdict(set)
    for candidate in raw_candidates:
        policy = rotation_policy.get(candidate["source_id"])
        if policy and candidate.get("ocr_rotation") == policy["primary"]:
            primary_positions[candidate["source_id"]].add(candidate["position"])

    for candidate in raw_candidates:
        policy = rotation_policy.get(candidate["source_id"])
        if policy:
            rotation = candidate.get("ocr_rotation")
            if rotation == policy["fallback"] and candidate["position"] in primary_positions[candidate["source_id"]]:
                continue
            if rotation not in {policy["primary"], policy["fallback"]}:
                continue
        matching_zone = next((zone for zone in zones if _in_zone(candidate, zone)), None)
        if matching_zone:
            excluded.append({**candidate, "reason": matching_zone["reason"]})
            continue
        duplicate = next((item for item in accepted if _same_occurrence(item, candidate)), None)
        if duplicate:
            if float(candidate.get("ocr_confidence") or 0) > float(duplicate.get("ocr_confidence") or 0):
                accepted.remove(duplicate)
                accepted.append(candidate)
            continue
        accepted.append(candidate)

    for item in review.get("manual_occurrences") or []:
        candidate = {
            **item,
            "position": str(item["position"]),
            "ocr_confidence": 1.0,
            "verification_method": "MANUAL_VISUAL_VERIFICATION",
        }
        duplicate = next((value for value in accepted if _same_occurrence(value, candidate)), None)
        if duplicate:
            accepted.remove(duplicate)
        accepted.append(candidate)

    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in accepted:
        by_source[candidate["source_id"]].append(candidate)

    not_drawn = {
        (item["source_id"], str(item["position"]))
        for item in review.get("positions_not_drawn") or []
    }
    report_sources: list[dict[str, Any]] = []
    total_occurrences = 0
    total_positions = 0
    unresolved_total = 0

    for source in dataset_sources():
        if not source.get("records_file") or not source.get("diagram_pages"):
            continue
        payload = load_source_dataset(source)
        source_candidates = sorted(
            by_source[source["source_id"]],
            key=lambda item: (
                item["page"],
                _position_sort(item["position"]),
                item["y"],
                item["x"],
            ),
        )
        previous_keys = defaultdict(list)
        for hotspot in payload.get("hotspots") or []:
            previous_keys[(hotspot["page"], str(hotspot["position"]))].append(
                hotspot["hotspot_key"]
            )
        position_occurrences: dict[tuple[int, str], int] = defaultdict(int)
        hotspots: list[dict[str, Any]] = []
        for candidate in source_candidates:
            identity = (candidate["page"], candidate["position"])
            position_occurrences[identity] += 1
            occurrence = position_occurrences[identity]
            preserved = previous_keys[identity]
            key = (
                preserved[occurrence - 1]
                if occurrence <= len(preserved)
                else f"{source['source_id']}:p{candidate['page']}:pos{candidate['position']}:occ{occurrence:02d}"
            )
            hotspots.append(
                {
                    "page": candidate["page"],
                    "position": candidate["position"],
                    "x": round(float(candidate["x"]), 6),
                    "y": round(float(candidate["y"]), 6),
                    "width": round(float(candidate["width"]), 6),
                    "height": round(float(candidate["height"]), 6),
                    "hotspot_key": key,
                    "source_id": source["source_id"],
                    "family": source["family"],
                    "assembly": source["assembly"],
                    "is_verified": True,
                    "provenance": f"{PROVENANCE} {candidate.get('reason', '')}".strip(),
                    "confidence": 1.0,
                }
            )
        bom_positions = {str(record["position"]) for record in payload.get("records") or []}
        mapped_positions = {item["position"] for item in hotspots}
        unresolved = sorted(
            (
                position
                for position in bom_positions - mapped_positions
                if (source["source_id"], position) not in not_drawn
            ),
            key=_position_sort,
        )
        expected_not_drawn = sorted(
            (
                position
                for position in bom_positions - mapped_positions
                if (source["source_id"], position) in not_drawn
            ),
            key=_position_sort,
        )
        if unresolved:
            raise RuntimeError(
                f"{source['source_id']}: unresolved drawn BOM positions: {unresolved}"
            )
        if write:
            dataset_path = CATALOG_ROOT / str(source["records_file"])
            payload["hotspots"] = hotspots
            dataset_path.write_text(
                f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n",
                encoding="utf-8",
            )
        source_summary = {
            "source_id": source["source_id"],
            "diagram_pages": source["diagram_pages"],
            "bom_position_count": len(bom_positions),
            "mapped_position_count": len(mapped_positions),
            "hotspot_occurrence_count": len(hotspots),
            "duplicate_callout_count": len(hotspots) - len(mapped_positions),
            "positions_not_drawn": expected_not_drawn,
            "unresolved_position_count": len(unresolved),
        }
        report_sources.append(source_summary)
        total_occurrences += len(hotspots)
        total_positions += len(mapped_positions)
        unresolved_total += len(unresolved)

    return {
        "review_version": review["review_version"],
        "reviewed_diagram_page_count": sum(
            len(item["pages"]) for item in review["reviewed_pages"]
        ),
        "sources": report_sources,
        "totals": {
            "mapped_position_count": total_positions,
            "hotspot_occurrence_count": total_occurrences,
            "duplicate_callout_count": total_occurrences - total_positions,
            "unresolved_position_count": unresolved_total,
            "positions_not_drawn_count": len(not_drawn),
            "false_numeric_candidate_count": pdf_false_count + len(excluded),
            "pdf_text_geometry_verified_count": 0,
            "manual_visual_verification_count": total_occurrences,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Finalize visually reviewed position geometry into catalog datasets."
    )
    parser.add_argument("--audit", action="append", type=Path, required=True)
    parser.add_argument(
        "--review",
        type=Path,
        default=CATALOG_ROOT / "position_mapping_review.json",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    report = finalize(
        audit_paths=arguments.audit,
        review_path=arguments.review,
        write=arguments.write,
    )
    output = f"{json.dumps(report, ensure_ascii=False, indent=2)}\n"
    if arguments.report:
        arguments.report.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
