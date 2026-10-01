"""Typed review operations. Source evidence can never be edited by a client."""

from typing import Literal

from pydantic import Field

from ..schemas import PartCreate, Payload


class CandidateEdit(Payload):
    name: str | None = Field(default=None, max_length=255)
    group_key: str | None = Field(default=None, min_length=64, max_length=64)
    merge_into_key: str | None = Field(default=None, min_length=64, max_length=64)
    assembly_id: int | None = Field(default=None, gt=0)
    role: Literal["EXPLODED_SCHEME", "SPARE_PARTS_LIST", "BOTH", "OTHER", "AMBIGUOUS"] | None = None
    part: PartCreate | None = None


class CandidateReview(Payload):
    expected_version: int = Field(ge=1)
    action: Literal["EDIT", "ACCEPT", "REJECT", "RESTORE", "VERIFY"]
    edit: CandidateEdit | None = None
    locations: list[int] | None = Field(default=None, min_length=1, max_length=100)


class BulkItem(Payload):
    id: int = Field(gt=0)
    expected_version: int = Field(ge=1)


class BulkReview(Payload):
    action: Literal["ACCEPT", "REJECT", "VERIFY"]
    items: list[BulkItem] = Field(min_length=1, max_length=100)
