from pydantic import BaseModel, ConfigDict, Field


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogCreate(Payload):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Z][A-Z0-9_]*$")
    asset_category_id: int = Field(gt=0)
    name_bg: str = Field(min_length=1, max_length=255)
    name_en: str = Field(min_length=1, max_length=255)
    name_ru: str = Field(min_length=1, max_length=255)
    description: str | None = None
    manufacturer: str | None = Field(default=None, max_length=255)
    model_reference: str | None = Field(default=None, max_length=255)


class CatalogUpdate(Payload):
    code: str | None = None
    asset_category_id: int | None = Field(default=None, gt=0)
    name_bg: str | None = Field(default=None, min_length=1, max_length=255)
    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    name_ru: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    manufacturer: str | None = Field(default=None, max_length=255)
    model_reference: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class RevisionCreate(Payload):
    revision_code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    change_note: str | None = None
    status: str | None = None


class RevisionUpdate(Payload):
    revision_code: str | None = None
    change_note: str | None = None
    status: str | None = None
