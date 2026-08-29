"""Existing public reference-data response shapes."""

from __future__ import annotations

from ..models import CategoryFieldDefinition, Department, Location


def _category_field_dict(item: CategoryFieldDefinition) -> dict:
    return {
        "id": item.id,
        "category_id": item.category_id,
        "code": item.code,
        "label_bg": item.label_bg,
        "label_en": item.label_en,
        "label_ru": item.label_ru,
        "field_type": item.field_type,
        "is_required": item.is_required,
        "options": item.options,
        "unit": item.unit,
        "validation_rules": item.validation_rules,
        "sort_order": item.sort_order,
        "is_active": item.is_active,
    }


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
