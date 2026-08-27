"""Existing public reference-data response shapes."""

from __future__ import annotations

from ..models import Department, Location


def _location_dict(item: Location) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "is_active": item.is_active,
    }


def _department_dict(item: Department) -> dict:
    return {
        "id": item.id,
        "code": item.code,
        "name_bg": item.name_bg,
        "name_en": item.name_en,
        "name_ru": item.name_ru,
        "description": item.description,
        "is_active": item.is_active,
        "created_at": item.created_at,
    }
