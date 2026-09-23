"""Render part-request visual evidence from the immutable 01A aggregate only."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import fitz
from PIL import Image, ImageDraw

from ..part_requests.visual_snapshots import _integrity_error

RENDER_DPI = 180
MAX_PAGE_PIXELS = 8_000_000
MAX_IMAGE_BYTES = 48_000_000
MAX_VISUAL_BLOCKS = 120
MAX_SOURCE_BYTES = 80_000_000
MAX_SOURCE_TOTAL_BYTES = 160_000_000

LABELS = {
    "bg": {
        "title": "Визуално приложение към заявката",
        "line": "Ред",
        "part": "Част №",
        "position": "Позиция",
        "source": "Източник",
        "page": "стр.",
        "revision": "Ревизия",
        "captured": "Заснето",
        "markers": "Отбелязани области",
        "scheme": "Разглобена схема",
        "list": "Списък резервни части",
        "unclassified": "Исторически визуален източник без определена роля",
        "unavailable": "Редове без запазена визуална препратка",
        "no_visual_reference_at_capture": "При заснемането на този ред не е имало потвърден визуален източник.",
        "legacy_snapshot_unavailable": "За този исторически ред няма неизменима визуална снимка.",
        "no_catalog_binding": "Редът няма потвърдена връзка с каталог и визуален източник.",
    },
    "en": {
        "title": "Visual reference appendix",
        "line": "Line",
        "part": "Part No.",
        "position": "Position",
        "source": "Source",
        "page": "p.",
        "revision": "Revision",
        "captured": "Captured",
        "markers": "Marked regions",
        "scheme": "Exploded scheme",
        "list": "Spare parts list",
        "unclassified": "Historical visual source without a captured role",
        "unavailable": "Lines without retained visual references",
        "no_visual_reference_at_capture": "No verified visual reference was available when this line was captured.",
        "legacy_snapshot_unavailable": "No immutable historical visual snapshot is available for this line.",
        "no_catalog_binding": "This line has no verified catalog binding or visual source.",
    },
    "ru": {
        "title": "Визуальное приложение к заявке",
        "line": "Строка",
        "part": "Деталь №",
        "position": "Позиция",
        "source": "Источник",
        "page": "стр.",
        "revision": "Ревизия",
        "captured": "Сохранено",
        "markers": "Отмеченные области",
        "scheme": "Разборная схема",
        "list": "Список запасных частей",
        "unclassified": "Исторический визуальный источник без сохранённой роли",
        "unavailable": "Строки без сохранённых визуальных ссылок",
        "no_visual_reference_at_capture": "На момент сохранения строки проверенного визуального источника не было.",
        "legacy_snapshot_unavailable": "Для этой исторической строки нет неизменимого визуального снимка.",
        "no_catalog_binding": "У строки нет подтверждённой связи с каталогом и визуальным источником.",
    },
}


@dataclass(frozen=True)
class VisualBlock:
    role: str
    artifact_sha256: str
    page_number: int
    ordinals: tuple[int, ...]
    image: bytes
    width: int
    height: int
    filename: str | None
    revision: str | None
    positions: tuple[str, ...]


@dataclass(frozen=True)
class VisualLine:
    line_id: int
    sequence: int
    part_number: str
    description: str
    position: str
    state: str
    snapshot_id: int | None
    snapshot_sha256: str | None
    captured_at: str | None
    blocks: tuple[VisualBlock, ...]


@dataclass(frozen=True)
class VisualPage:
    role: str
    artifact_sha256: str
    page_number: int
    image: bytes
    width: int
    height: int
    filename: str | None
    revision: str | None
    contributions: tuple[dict, ...]


@dataclass(frozen=True)
class VisualPlan:
    lines: tuple[VisualLine, ...]
    pages: tuple[VisualPage, ...]

    def __getitem__(self, index: int) -> VisualLine:
        return self.lines[index]

    def __len__(self) -> int:
        return len(self.lines)

    def __iter__(self):
        return iter(self.lines)


def _render_page(
    content: bytes, media_type: str, page_number: int, references: list[dict]
) -> tuple[bytes, int, int]:
    if media_type not in {"application/pdf", "image/png", "image/jpeg", "image/tiff"}:
        raise _integrity_error()
    filetype = {
        "application/pdf": "pdf",
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/tiff": "tiff",
    }[media_type]
    try:
        with fitz.open(stream=content, filetype=filetype) as source:
            if page_number < 1 or page_number > source.page_count:
                raise _integrity_error()
            page = source.load_page(page_number - 1)
            rect = page.rect  # Display orientation, including the captured PDF rotation.
            if rect.width <= 0 or rect.height <= 0:
                raise _integrity_error()
            scale = min(RENDER_DPI / 72, math.sqrt(MAX_PAGE_PIXELS / (rect.width * rect.height)))
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False
            )
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        draw = ImageDraw.Draw(image)
        stroke = max(4, round(min(image.size) / 300))
        for reference in references:
            x, y, width, height = (reference[key] for key in ("x", "y", "width", "height"))
            if (
                not all(math.isfinite(value) for value in (x, y, width, height))
                or min(x, y) < 0
                or min(width, height) <= 0
                or x + width > 1.000001
                or y + height > 1.000001
            ):
                raise _integrity_error()
            box = (
                round(x * image.width),
                round(y * image.height),
                round((x + width) * image.width),
                round((y + height) * image.height),
            )
            draw.rectangle(box, outline="white", width=stroke + 4)
            draw.rectangle(box, outline="#c81923", width=stroke)
            badge = str(reference["ordinal"])
            badge_width = max(22, 10 + 7 * len(badge))
            bx = min(max(0, box[0]), image.width - badge_width)
            by = max(0, box[1] - 23)
            draw.rectangle((bx, by, bx + badge_width, by + 20), fill="#c81923")
            draw.text((bx + 5, by + 3), badge, fill="white")
        output = io.BytesIO()
        image.save(output, format="PNG", compress_level=6)
        return output.getvalue(), image.width, image.height
    except Exception as exc:
        raise _integrity_error() from exc
