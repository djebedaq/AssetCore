from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

UNITS = frozenset({"pcs", "m", "l", "kg", "g", "m2", "m3", "set", "pair"})
INDIVISIBLE = frozenset({"pcs", "set", "pair"})
ALIASES = {"бр.": "pcs", "бр": "pcs", "м": "m", "л": "l", "кг": "kg", "г": "g"}


def decimal_text(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else str(value)


class RequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FreeFormLine(RequestInput):
    description: str = Field(min_length=1, max_length=4000)
    quantity: Decimal = Field(gt=0, lt=1_000_000_000, max_digits=15, decimal_places=6)
    unit: str

    @field_validator("quantity", mode="before")
    @classmethod
    def comma_decimal(cls, value):
        if isinstance(value, bool):
            raise ValueError("invalid_quantity")
        return value.replace(",", ".") if isinstance(value, str) else value

    @field_validator("unit")
    @classmethod
    def known_unit(cls, value):
        value = ALIASES.get(value, value)
        if value not in UNITS:
            raise ValueError("invalid_unit")
        return value

    @model_validator(mode="after")
    def whole_units(self):
        if self.unit in INDIVISIBLE and self.quantity != self.quantity.to_integral_value():
            raise ValueError("indivisible_unit_requires_integer")
        return self


class FreeFormRequest(RequestInput):
    department: str = Field(min_length=1, max_length=255)
    reason: str | None = Field(default=None, max_length=8000)
    language: Literal["bg", "en", "ru"] = "bg"
    lines: list[FreeFormLine] = Field(min_length=1, max_length=500)
    submit_for_approval: bool = False


class DeliveryLine(RequestInput):
    line_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, lt=1_000_000_000, max_digits=15, decimal_places=6)

    _comma = field_validator("quantity", mode="before")(FreeFormLine.comma_decimal.__func__)


class DeliveryCreate(RequestInput):
    idempotency_key: str = Field(min_length=1, max_length=80)
    lines: list[DeliveryLine] = Field(min_length=1, max_length=500)
    supplier: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def unique_lines(self):
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError("duplicate_delivery_line")
        return self


class DeliveryCorrection(RequestInput):
    idempotency_key: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=8000)


class RequestCancel(RequestInput):
    confirmed: StrictBool
    reason: str = Field(min_length=1, max_length=8000)
    replacement_request_id: int | None = Field(default=None, gt=0)

    @field_validator("confirmed")
    @classmethod
    def explicit_confirmation(cls, value):
        if not value:
            raise ValueError("cancellation_confirmation_required")
        return value
