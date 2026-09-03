"""Read-only official-document registry domain."""

from .registry import (
    build_official_document_registry,
    count_official_document_registry_items,
    query_official_document_registry_items,
)

__all__ = [
    "build_official_document_registry",
    "count_official_document_registry_items",
    "query_official_document_registry_items",
]
