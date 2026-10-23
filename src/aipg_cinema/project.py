# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Persistent shot plans. Editing a plan never starts inference or changes a take."""

import json
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .brief import ProductSetup
from .contracts import ID, LookRequest, TakeDraft, TakeRequest


class LookAudition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_key: str = Field(default="", max_length=256)
    direction: str = Field(default="", max_length=4000)
    seed: int = Field(default=42, ge=0, le=2**63 - 1)
    denoise: Literal[0.4, 0.65, 0.75] = 0.65
    reference_id: str | None = Field(default=None, pattern=ID)
    left_id: str | None = Field(default=None, pattern=ID)
    right_id: str | None = Field(default=None, pattern=ID)
    frame_index: Literal[0, 120] = 0


class Shot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=ID)
    title: str = Field(default="Untitled shot", min_length=1, max_length=80)
    beat: Literal["hook", "build", "reveal", "payoff", "detail"] = "detail"
    draft: TakeDraft = Field(default_factory=lambda: TakeDraft(mode="text"))
    direction_override: str | None = Field(default=None, max_length=2000)
    # The camera preset (id@version) whose motion text this shot started from.
    camera: str | None = Field(default=None, pattern=r"^[a-z][a-z-]{1,30}@[0-9]{1,4}$")
    selected_take_id: str | None = Field(default=None, pattern=ID)
    trim_start: int = Field(default=0, ge=0, le=119, strict=True)
    trim_end: int = Field(default=120, ge=1, le=120, strict=True)
    volume: float = Field(default=1.0, ge=0, le=2, allow_inf_nan=False)
    audition: LookAudition | None = None

    @model_validator(mode="after")
    def valid_trim(self):
        if self.trim_start >= self.trim_end:
            raise ValueError("The shot trim must keep at least one frame.")
        return self


class AudioLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_id: str = Field(pattern=ID)
    source_start: float = Field(default=0, ge=0, le=1800, allow_inf_nan=False)
    start_frame: int = Field(default=0, ge=0, le=719, strict=True)
    duration_frames: int = Field(ge=1, le=720, strict=True)
    volume: float = Field(default=1, ge=0, le=2, allow_inf_nan=False)
    loop: bool = False
    fade_in: int = Field(default=0, ge=0, le=240, strict=True)
    fade_out: int = Field(default=0, ge=0, le=240, strict=True)

    @model_validator(mode="after")
    def fades_fit(self):
        if self.fade_in + self.fade_out > self.duration_frames:
            raise ValueError("Audio fades must fit inside the layer.")
        return self


class Caption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=ID)
    text: str = Field(min_length=1, max_length=160)
    start_frame: int = Field(ge=0, le=719, strict=True)
    end_frame: int = Field(ge=1, le=720, strict=True)

    @model_validator(mode="after")
    def valid_cue(self):
        if not self.text.strip() or self.start_frame >= self.end_frame:
            raise ValueError("A caption needs text and a positive duration.")
        if any(
            not character.isprintable() and character not in "\n\t"
            for character in self.text
        ):
            raise ValueError("Caption text contains unsupported control characters.")
        return self


class CaptionPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=160)
    frame_format: Literal["portrait", "square", "landscape"]
    style: Literal["clean", "bold", "studio"] = "clean"
    position: Literal["lower", "center", "upper"] = "lower"


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    id: str = Field(pattern=ID)
    revision: int = Field(default=0, ge=0, strict=True)
    title: str = Field(default="Untitled short", min_length=1, max_length=100)
    frame_format: Literal["portrait", "square", "landscape"] = "portrait"
    art_direction: str = Field(default="", max_length=2000)
    shots: list[Shot] = Field(default_factory=list, max_length=6)
    music: AudioLayer | None = None
    voiceover: AudioLayer | None = None
    captions: list[Caption] = Field(default_factory=list, max_length=30)
    caption_style: Literal["clean", "bold", "studio"] = "clean"
    caption_position: Literal["lower", "center", "upper"] = "lower"
    product: ProductSetup | None = None
    # A saved music style (from a template); None uses the tone's default.
    music_prompt: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def shot_contract(self):
        if len({shot.id for shot in self.shots}) != len(self.shots):
            raise ValueError("Every shot must have a unique ID.")
        if any(shot.draft.frame_format != self.frame_format for shot in self.shots):
            raise ValueError("All shots must use the project's framing.")
        if len({caption.id for caption in self.captions}) != len(self.captions):
            raise ValueError("Every caption must have a unique ID.")
        if (
            self.product
            and self.product.packshot_shot_id
            and self.product.packshot_shot_id not in {shot.id for shot in self.shots}
        ):
            # A removed packshot shot is simply no longer the packshot.
            self.product = self.product.model_copy(update={"packshot_shot_id": None})
        return self

    @property
    def frames(self) -> int:
        return sum(shot.trim_end - shot.trim_start for shot in self.shots)

    def shot(self, shot_id: str) -> Shot:
        for shot in self.shots:
            if shot.id == shot_id:
                return shot
        raise ValueError("Shot not found in this project.")

    def request(self, shot_id: str, request_id: str) -> TakeRequest:
        shot = self.shot(shot_id)
        direction = (
            self.art_direction
            if shot.direction_override is None
            else shot.direction_override
        )
        prompt = "\n\n".join(
            text.strip() for text in (direction, shot.draft.prompt) if text.strip()
        )
        if not shot.draft.prompt.strip():
            raise ValueError("Describe this shot before generating it.")
        return TakeRequest.model_validate(
            {
                **shot.draft.model_dump(),
                "prompt": prompt,
                "request_id": request_id,
                "project_id": self.id,
                "shot_id": shot.id,
                "project_revision": self.revision,
                "shared_direction": direction,
            }
        )

    def look_request(self, shot_id: str, request_id: str, engine: str) -> LookRequest:
        shot = self.shot(shot_id)
        audition = shot.audition
        if audition is None or not audition.direction.strip():
            raise ValueError("Describe the image direction before generating a look.")
        kind = (
            "video"
            if shot.draft.mode == "video"
            else "image"
            if audition.reference_id
            else "text"
        )
        return LookRequest(
            request_id=request_id,
            look_input=kind,
            source_id=shot.draft.source_id if kind == "video" else None,
            image_id=audition.reference_id if kind == "image" else None,
            source_start=shot.draft.source_start if kind == "video" else 0,
            frame_format=self.frame_format,
            frame_index=audition.frame_index,
            prompt=audition.direction,
            seed=audition.seed,
            denoise=None
            if engine in ("klein", "klein-cloud")
            else 1.0
            if kind == "text"
            else audition.denoise,
            audition=True,
            project_id=self.id,
            shot_id=shot.id,
            project_revision=self.revision,
        )


class NewProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="Untitled short", min_length=1, max_length=100)
    frame_format: Literal["portrait", "square", "landscape"] = "portrait"
    structure: Literal["hook-reveal-payoff", "before-after", "blank", "product"] = (
        "hook-reveal-payoff"
    )
    product: ProductSetup | None = None
    template_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,40}$")

    @model_validator(mode="after")
    def product_brief(self):
        if (self.structure == "product") != (self.product is not None):
            raise ValueError("A product short needs exactly one product brief.")
        return self


class GenerateShot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=ID)
    revision: int = Field(ge=0, strict=True)


class Conflict(ValueError):
    pass


def atomic_json(path: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".saving-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _directory_sync(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class ProjectStore:
    def __init__(self, directory: Path):
        self.root = directory
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, project_id: str) -> Path:
        if uuid.UUID(hex=project_id).hex != project_id:
            raise ValueError("Project not found.")
        return self.root / project_id

    def load(self, project_id: str) -> Project:
        return Project.model_validate_json(
            (self.path(project_id) / "project.json").read_text()
        )

    def list(self) -> list[Project]:
        return [
            self.load(path.parent.name)
            for path in sorted(
                (
                    path
                    for path in self.root.glob("*/project.json")
                    if re.fullmatch(ID, path.parent.name)
                ),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        ]

    def creation(self, request_id: str) -> tuple[NewProject, Project]:
        folder = self.path(request_id)
        body = NewProject.model_validate_json((folder / "creation.json").read_text())
        project = self.load(request_id)
        if project.id != request_id:
            raise ValueError(
                "Saved project identity differs from its creation request."
            )
        return body, project

    def create(
        self,
        body: NewProject,
        *,
        request_id: str | None = None,
        plan: Callable[[Project], Project] | None = None,
    ) -> Project:
        project_id = request_id or uuid.uuid4().hex
        folder = self.path(project_id)
        beats = {
            "hook-reveal-payoff": [
                ("The hook", "hook"),
                ("The reveal", "reveal"),
                ("The payoff", "payoff"),
            ],
            "before-after": [
                ("Before", "hook"),
                ("The transformation", "build"),
                ("After", "payoff"),
            ],
            "blank": [],
            # Product shots are planned by the app from the brief and photos.
            "product": [],
        }[body.structure]
        project = Project(
            id=project_id,
            title=body.title,
            frame_format=body.frame_format,
            shots=[
                Shot(
                    title=title,
                    beat=beat,
                    draft=TakeDraft(mode="text", frame_format=body.frame_format),
                )
                for title, beat in beats
            ],
        )
        if plan:
            # Planning is pure, so the planned project is written atomically
            # with its creation request; a replay returns it unchanged.
            project = plan(project)
        with FileLock(self.root / ".creation.lock", timeout=5):
            if folder.exists():
                if request_id and (folder / "creation.json").is_file():
                    original, current = self.creation(request_id)
                    if original == body:
                        return current
                raise Conflict("This creation ID belongs to different project details.")
            temporary = Path(tempfile.mkdtemp(prefix=".creating-", dir=self.root))
            try:
                if request_id:
                    atomic_json(temporary / "creation.json", body.model_dump())
                atomic_json(temporary / "project.json", project.model_dump())
                _directory_sync(temporary)
                temporary.rename(folder)
                _directory_sync(self.root)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            return project

    def save(self, project: Project) -> Project:
        project = Project.model_validate(project.model_dump())
        folder = self.path(project.id)
        if not (folder / "project.json").is_file():
            raise FileNotFoundError("Project not found.")
        with FileLock(folder / ".project.lock", timeout=5):
            previous = self.load(project.id)
            if project.revision != previous.revision:
                raise Conflict(
                    "This project changed in another tab. Reopen it before saving."
                )
            result = project.model_copy(update={"revision": project.revision + 1})
            atomic_json(folder / "project.json", result.model_dump())
        return result
