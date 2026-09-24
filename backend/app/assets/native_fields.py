"""Category capability checks for platform-native asset fields."""

from __future__ import annotations

from ..models import AssetCategory


class NativeFieldCapabilityError(ValueError):
    code = "pressure_not_applicable"


def validate_native_asset_fields(
    category: AssetCategory, *, pressure_bar: int | None,
) -> None:
    """Reject native values that the resolved category does not support."""
    if pressure_bar is not None and "HAS_PRESSURE" not in (category.capabilities or []):
        raise NativeFieldCapabilityError(
            "Налягането не е приложимо за избраната категория. "
            "Изчистете налягането изрично или изберете категория, която го поддържа."
        )
