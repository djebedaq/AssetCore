"""Bounded passive image and DOCX ingestion. Never fetch linked resources."""

import base64
import binascii
import hashlib
import io
import re
import warnings
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from PIL import Image

from .schemas import ImageUpload


def normalize_image(payload: ImageUpload) -> tuple[bytes, int, int]:
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
        if len(content) > 2_000_000:
            raise ValueError("studio_image_size")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                expected = "PNG" if payload.media_type == "image/png" else "JPEG"
                if (image.format != expected or getattr(image, "n_frames", 1) != 1
                        or not 1 <= image.width <= 4096 or not 1 <= image.height <= 4096
                        or image.width * image.height > 8_000_000):
                    raise ValueError("studio_image_invalid")
                if PurePosixPath(payload.filename.lower()).suffix not in (
                    (".png",) if expected == "PNG" else (".jpg", ".jpeg")
                ):
                    raise ValueError("studio_image_invalid")
                image.load()
                output = io.BytesIO()
                # Decode/re-encode strips EXIF, scripts, trailing payloads and
                # embedded metadata. Only this passive PNG is retained/served.
                clean = Image.new("RGBA", image.size)
                clean.paste(image.convert("RGBA"))
                clean.save(output, format="PNG")
                if len(output.getvalue()) > 4_000_000:
                    raise ValueError("studio_image_size")
                return output.getvalue(), image.width, image.height
    except ValueError:
        raise
    except (binascii.Error, OSError, Image.DecompressionBombWarning,
            Image.DecompressionBombError):
        raise ValueError("studio_image_invalid") from None


def validate_docx(content: bytes) -> str:
    if not content or len(content) > 12_000_000:
        raise ValueError("studio_docx_unsafe")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (len(entries) > 1000 or len({e.filename for e in entries}) != len(entries)
                    or sum(e.file_size for e in entries) > 40_000_000):
                raise ValueError("studio_docx_unsafe")
            if "word/document.xml" not in archive.namelist():
                raise ValueError("studio_docx_unsafe")
            for entry in entries:
                name = entry.filename.lower()
                if (entry.flag_bits & 1 or name.startswith(("/", "\\"))
                        or ".." in PurePosixPath(name).parts or "\\" in name
                        or name.endswith((".bin", ".exe", ".js", ".html", ".svg", ".vbs"))
                        or any(p in name for p in ("vbaproject", "activex", "embeddings/"))):
                    raise ValueError("studio_docx_unsafe")
                if name.endswith((".xml", ".rels")):
                    data = archive.read(entry)
                    markup = data.replace(b"\x00", b"").upper()
                    if b"<!DOCTYPE" in markup or b"<!ENTITY" in markup:
                        raise ValueError("studio_docx_unsafe")
                    root = ElementTree.fromstring(data)
                    for node in root.iter():
                        local = node.tag.rsplit("}", 1)[-1]
                        kind = (node.attrib.get("Type", "") + " " + node.attrib.get("ContentType", "")).lower()
                        relation = node.attrib.get("Type", "").rsplit("/", 1)[-1].lower()
                        if (any(marker in kind for marker in ("macro", "vba", "activex", "oleobject", "webextension"))
                                or relation in {"attachedtemplate", "control", "package"}
                                or any(key.rsplit("}", 1)[-1].lower() in {"src", "href"}
                                       and re.match(r"\s*(https?|file|ftp|data|javascript):", value, re.I)
                                       for key, value in node.attrib.items())):
                            raise ValueError("studio_docx_unsafe")
                        if (node.attrib.get("TargetMode", "").lower() == "external"
                                or local in {"altChunk", "object", "fldSimple"}
                                or (local == "instrText" and not re.fullmatch(
                                    r"\s*(PAGE|NUMPAGES|SECTIONPAGES)(\s+\\\*\s+(MERGEFORMAT|ARABIC))?\s*",
                                    node.text or "", re.IGNORECASE))):
                            raise ValueError("studio_docx_unsafe")
        from docx import Document
        Document(io.BytesIO(content))
    except Exception:
        raise ValueError("studio_docx_unsafe") from None
    return hashlib.sha256(content).hexdigest()
