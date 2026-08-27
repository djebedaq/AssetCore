"""Restricted asset presentation used by the legacy machine read endpoints."""

from __future__ import annotations

from ..models import Machine


def _limited_machine(item: Machine) -> dict:
    return {
        "id": item.id,
        "inventory_number": item.inventory_number,
        "name": item.name,
        "brand": item.brand,
        "model": item.model,
        "status": item.status,
        "is_active": item.is_active,
        "location": (
            {"id": item.location.id, "name": item.location.name} if item.location else None
        ),
    }
