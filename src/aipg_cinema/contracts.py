"""Saved draft and execution contracts shared by the editor and shot board."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ID = r"^[0-9a-f]{32}$"


class SourceWindow(BaseModel):
    frame_format: Literal["landscape", "portrait", "square"] = "landscape"
    source_start: float = Field(default=0, ge=0, le=86400, allow_inf_nan=False)
    # Video-to-video takes run 5, 10 or 15 seconds (LTX-2.5, 8k+1 frames).
    seconds: Literal[5, 10, 15] = 5


class TakeDraft(SourceWindow):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["video", "text", "image", "audio"] = "video"
    render_profile: Literal["two-pass", "single-pass-audio"] = "two-pass"
    source_id: str | None = Field(default=None, pattern=ID)
    audio_id: str | None = Field(default=None, pattern=ID)
    prompt: str = Field(default="", max_length=4000)
    art_direction: str | None = Field(default=None, max_length=4000)
    motion_prompt: str | None = Field(default=None, max_length=4000)
    seed: int = Field(default=42, ge=0, le=2**63 - 1)
    look_id: str | None = Field(default=None, pattern=ID)
    closing_id: str | None = Field(default=None, pattern=ID)


class TakeRequest(TakeDraft):
    request_id: str = Field(pattern=ID)
    prompt: str = Field(min_length=1, max_length=4000)
    project_id: str | None = Field(default=None, pattern=ID)
    shot_id: str | None = Field(default=None, pattern=ID)
    project_revision: int | None = Field(default=None, ge=0)
    shared_direction: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def inputs_match_mode(self):
        if self.render_profile == "single-pass-audio" and (
            self.mode not in ("video", "audio")
            or (self.closing_id and not self.look_id)
        ):
            raise ValueError(
                "Single-pass speech requires audio or video input; an ending frame also requires an opening image."
            )
        if (self.mode == "video") != (self.source_id is not None):
            raise ValueError("A source video is required exactly in video mode.")
        if (self.mode == "audio") != (self.audio_id is not None):
            raise ValueError("Source audio is required exactly in audio mode.")
        if self.mode == "image" and not self.look_id:
            raise ValueError("Choose an opening image for image mode.")
        if self.mode not in ("video", "audio") and self.source_start != 0:
            raise ValueError("A source start requires video or audio mode.")
        if self.seconds != 5 and (
            self.mode != "video" or self.render_profile != "two-pass" or self.closing_id
        ):
            raise ValueError(
                "Longer takes are video-to-video two-pass takes without an ending frame."
            )
        context = (
            self.project_id,
            self.shot_id,
            self.project_revision,
            self.shared_direction,
        )
        if any(value is not None for value in context) and not all(
            value is not None for value in context
        ):
            raise ValueError("A project take requires its complete saved shot context.")
        return self


class LookRequest(SourceWindow):
    request_id: str = Field(pattern=ID)
    # An uploaded picture whose look a Klein video look copies.
    style_image_id: str | None = Field(default=None, pattern=ID)
    source_id: str | None = Field(default=None, pattern=ID)
    image_id: str | None = Field(default=None, pattern=ID)
    look_input: Literal["video", "image", "text"] = "video"
    prompt: str = Field(min_length=1, max_length=4000)
    seed: int = Field(default=42, ge=0, le=2**63 - 1)
    denoise: Literal[0.4, 0.65, 0.75, 1.0] | None = 0.65
    frame_index: Literal[0, 120] = 0
    audition: bool = False
    project_id: str | None = Field(default=None, pattern=ID)
    shot_id: str | None = Field(default=None, pattern=ID)
    project_revision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def input_contract(self):
        if (self.look_input == "video") != (self.source_id is not None):
            raise ValueError("Video looks require exactly one source video.")
        if (self.look_input == "image") != (self.image_id is not None):
            raise ValueError("Image looks require exactly one reference image.")
        if self.look_input != "video" and self.source_start != 0:
            raise ValueError("A video source offset requires video input.")
        if self.style_image_id and self.look_input != "video":
            raise ValueError("A style image restyles a video frame.")
        if self.seconds != 5 and (self.look_input != "video" or self.frame_index):
            raise ValueError(
                "Longer takes use a video source and an opening look only."
            )
        context = (self.project_id, self.shot_id, self.project_revision)
        if any(value is not None for value in context) and (
            not all(value is not None for value in context) or not self.audition
        ):
            raise ValueError("A project audition requires its full saved shot context.")
        return self


class ToolRequest(BaseModel):
    """One single-purpose tool run on an uploaded clip or a finished take."""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=ID)
    tool: Literal[
        "fps-boost", "remove-background", "upscale", "depth-map", "reframe", "extend"
    ]
    source_id: str | None = Field(default=None, pattern=ID)
    take_id: str | None = Field(default=None, pattern=ID)
    background: Literal["green", "black", "white", "matte"] = "green"
    target: Literal["portrait", "landscape", "square"] = "portrait"
    fit: Literal["blur", "crop"] = "blur"

    @model_validator(mode="after")
    def one_input(self):
        if (self.source_id is None) == (self.take_id is None):
            raise ValueError("Choose exactly one clip or finished take.")
        if self.tool == "extend" and not self.take_id:
            raise ValueError("Extend continues a finished take.")
        return self
