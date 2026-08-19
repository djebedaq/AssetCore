from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import fitz

AUTO_MATCHED = "AUTO_MATCHED"
MANUALLY_CONFIRMED = "MANUALLY_CONFIRMED"
ALLOWED_POSITION_PROVENANCE = frozenset({AUTO_MATCHED, MANUALLY_CONFIRMED})
_LEGACY_ADMIN_CORRECTION_MARKER = "Административна проверка:"

_TOKEN_EDGE = re.compile(r"^[\s\[\](){},.:;]+|[\s\[\](){},.:;]+$")
_ANNOTATION_UNITS = {"nm", "n·m", "n-m", "bar", "mm"}


def is_manually_confirmed(provenance: str | None) -> bool:
    """Return whether an exact occurrence has explicit manual evidence.

    The legacy marker is accepted only during importer normalization so a real
    pre-correction QA edit is not lost. Generic legacy page-review provenance
    deliberately does not qualify.
    """

    return provenance == MANUALLY_CONFIRMED or (
        provenance is not None and _LEGACY_ADMIN_CORRECTION_MARKER in provenance
    )


def occurrence_identity(item: dict[str, Any]) -> tuple[Any, ...]:
    """Build the stable exact-occurrence key used by review and validation."""

    return (
        item["source_id"],
        int(item["page"]),
        str(item["position"]),
        *(round(float(item[name]), 6) for name in ("x", "y", "width", "height")),
    )


@dataclass(frozen=True)
class PositionCandidate:
    source_id: str
    page: int
    position: str
    occurrence: int
    x: float
    y: float
    width: float
    height: float
    text_bbox: tuple[float, float, float, float]
    page_size: tuple[float, float]
    accepted: bool
    rejection_reason: str | None
    verification_method: str

    @property
    def candidate_key(self) -> str:
        return (
            f"{self.source_id}:p{self.page}:pos{self.position}:"
            f"occ{self.occurrence}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {"candidate_key": self.candidate_key, **asdict(self)}


def normalize_position_token(value: str) -> str:
    """Normalize PDF punctuation without changing source position identity."""

    return _TOKEN_EDGE.sub("", value.strip())


def _same_line_neighbours(
    words: list[tuple[Any, ...]], index: int
) -> tuple[str | None, str | None]:
    word = words[index]
    block, line = word[5], word[6]
    line_words = [
        (candidate[7], str(candidate[4]))
        for candidate in words
        if candidate[5] == block and candidate[6] == line
    ]
    line_words.sort()
    word_number = word[7]
    previous = next(
        (text for number, text in reversed(line_words) if number < word_number), None
    )
    following = next(
        (text for number, text in line_words if number > word_number), None
    )
    return previous, following


def _numeric_annotation_reason(
    words: list[tuple[Any, ...]], index: int, raw_text: str
) -> str | None:
    previous, following = _same_line_neighbours(words, index)
    neighbours = {
        normalize_position_token(value).casefold()
        for value in (previous, following)
        if value
    }
    if neighbours & _ANNOTATION_UNITS:
        return "MEASUREMENT_VALUE"
    if "/" in raw_text or "/" in neighbours:
        return "PAGE_OR_DRAWING_REFERENCE"
    return None


def extract_position_candidates(
    *,
    pdf_path: Path,
    source_id: str,
    diagram_pages: Iterable[int],
    bom_positions: Iterable[str],
    hit_padding_points: float = 2.5,
) -> list[PositionCandidate]:
    """Extract source-backed PDF text geometry without auto-verifying it.

    Exact BOM membership is required. Known numeric annotations such as torque
    values are retained as rejected QA evidence instead of being silently
    converted into hotspots.
    """

    valid_positions = {
        normalize_position_token(str(position))
        for position in bom_positions
        if normalize_position_token(str(position))
    }
    occurrences: defaultdict[tuple[int, str], int] = defaultdict(int)
    candidates: list[PositionCandidate] = []

    with fitz.open(pdf_path) as document:
        for page_number in diagram_pages:
            page = document[page_number - 1]
            words = list(page.get_text("words"))
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)
            for index, word in enumerate(words):
                raw_text = str(word[4]).strip()
                position = normalize_position_token(raw_text)
                if position not in valid_positions:
                    continue

                occurrences[(page_number, position)] += 1
                reason = _numeric_annotation_reason(words, index, raw_text)
                x0, y0, x1, y1 = (float(value) for value in word[:4])
                padded_x0 = max(0.0, x0 - hit_padding_points)
                padded_y0 = max(0.0, y0 - hit_padding_points)
                padded_x1 = min(page_width, x1 + hit_padding_points)
                padded_y1 = min(page_height, y1 + hit_padding_points)
                candidates.append(
                    PositionCandidate(
                        source_id=source_id,
                        page=page_number,
                        position=position,
                        occurrence=occurrences[(page_number, position)],
                        x=padded_x0 / page_width,
                        y=padded_y0 / page_height,
                        width=(padded_x1 - padded_x0) / page_width,
                        height=(padded_y1 - padded_y0) / page_height,
                        text_bbox=(x0, y0, x1, y1),
                        page_size=(page_width, page_height),
                        accepted=reason is None,
                        rejection_reason=reason,
                        verification_method="PDF_TEXT_GEOMETRY_CANDIDATE",
                    )
                )
    return candidates


def mapping_metrics(
    *, candidates: Iterable[PositionCandidate], bom_positions: Iterable[str]
) -> dict[str, Any]:
    candidate_list = list(candidates)
    bom = {normalize_position_token(str(value)) for value in bom_positions}
    accepted = [candidate for candidate in candidate_list if candidate.accepted]
    accepted_positions = {candidate.position for candidate in accepted}
    rejected = [candidate for candidate in candidate_list if not candidate.accepted]
    return {
        "bom_position_count": len(bom),
        "diagram_position_count": len(accepted_positions),
        "candidate_occurrence_count": len(accepted),
        "duplicate_callout_count": len(accepted) - len(accepted_positions),
        "unresolved_bom_position_count": len(bom - accepted_positions),
        "false_numeric_candidate_count": len(rejected),
        "false_numeric_candidates": [candidate.as_dict() for candidate in rejected],
    }
