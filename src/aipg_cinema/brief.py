# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Saved product brief. Kept dependency-free so project files can embed it."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID = r"^[0-9a-f]{32}$"


def supported(text: str) -> bool:
    from .finishing import coverage

    ranges = coverage()["ranges"]
    return all(
        character.isspace() or any(a <= ord(character) <= b for a, b in ranges)
        for character in text
    )


class ProductBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    audience: str = Field(default="", max_length=200)
    tone: Literal["premium", "playful", "bold", "calm"] = "premium"
    setting: str = Field(default="", max_length=200)
    benefits: list[str] = Field(default_factory=list, max_length=3)
    tagline: str = Field(default="", max_length=80)
    cta: str = Field(default="", max_length=40)
    # Apparel only: show the product worn by a fictional AI-generated model.
    worn: bool = False
    # The opening line: 3 seconds of reading, so at most ten words.
    hook: str = Field(default="", max_length=60)
    # Locally rendered captions on the opening shot only (the packshot closes)
    # or one per scene shot.
    captions: Literal["open-close", "every-shot"] = "open-close"
    # Calm: two long gentle shots and the packshot. Punchy: one shot per
    # benefit with shorter cuts.
    pacing: Literal["calm", "punchy"] = "calm"

    @field_validator("hook")
    @classmethod
    def short_hook(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value.split()) > 10:
            raise ValueError("Keep the hook to ten words or fewer.")
        if not supported(value):
            raise ValueError("Use letters and punctuation the bundled font supports.")
        return value

    @field_validator("name", "audience", "setting", "tagline", "cta")
    @classmethod
    def printable(cls, value: str) -> str:
        value = " ".join(value.split())
        if not supported(value):
            raise ValueError("Use letters and punctuation the bundled font supports.")
        return value

    @field_validator("benefits")
    @classmethod
    def benefit_lines(cls, values: list[str]) -> list[str]:
        cleaned = [" ".join(value.split()) for value in values]
        if any(
            not value or len(value) > 80 or not supported(value) for value in cleaned
        ):
            raise ValueError("Each benefit needs 1-80 supported characters.")
        return cleaned

    @model_validator(mode="after")
    def has_a_name(self):
        # Length limits run before whitespace is collapsed.
        if not self.name:
            raise ValueError("Name the product.")
        return self


class ProductSetup(BaseModel):
    """The brief, its uploaded photos and which shot is the local packshot."""

    model_config = ConfigDict(extra="forbid")
    brief: ProductBrief
    photo_ids: list[str] = Field(min_length=1, max_length=3)
    packshot_shot_id: str | None = Field(default=None, pattern=ID)

    @field_validator("photo_ids")
    @classmethod
    def photo_identities(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values) or any(
            not re.fullmatch(ID, value) for value in values
        ):
            raise ValueError("Choose 1-3 distinct uploaded product photos.")
        return values


class ProductLookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=ID)
    revision: int = Field(ge=0, strict=True)
    photo_index: int = Field(default=0, ge=0, le=2, strict=True)
    seed: int = Field(default=42, ge=0, le=2**63 - 1)
    refine: bool = False
    # A product look from this project whose person/scene this shot continues.
    continuity_look_id: str | None = Field(default=None, pattern=ID)


class PackshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=ID)
    revision: int = Field(ge=0, strict=True)
    photo_index: int = Field(default=0, ge=0, le=2, strict=True)
    accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class BriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=60)


class MusicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=ID)
    revision: int = Field(ge=0, strict=True)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
