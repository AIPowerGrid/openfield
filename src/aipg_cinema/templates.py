# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Reusable short plans: pacing, camera presets, captions, tone and music.

A template never carries media, references, briefs or keys. Built-ins come from
owner-approved shorts; users can save their own shorts as templates.
"""

import json
import re
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .presets import by_id
from .project import Project, atomic_json

BUILTINS = Path(__file__).with_name("templates")
ID = r"^[a-z0-9][a-z0-9-]{1,40}$"


class TemplateShot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beat: Literal["hook", "build", "reveal", "payoff", "detail"]
    camera: str | None = Field(default=None, pattern=r"^[a-z][a-z-]{1,30}@[0-9]{1,4}$")
    trim_end: int = Field(ge=1, le=120)


class Template(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=80)
    builtin: bool = False
    tone: Literal["premium", "playful", "bold", "calm"] = "calm"
    pacing: Literal["calm", "punchy"] = "calm"
    worn: bool = False
    captions: Literal["open-close", "every-shot"] = "open-close"
    caption_style: Literal["clean", "bold", "studio"] = "studio"
    caption_position: Literal["lower", "center", "upper"] = "upper"
    music_prompt: str | None = Field(default=None, max_length=400)
    shots: list[TemplateShot] = Field(min_length=1, max_length=6)


def _read(path: Path) -> Template | None:
    try:
        return Template.model_validate_json(path.read_text())
    except (OSError, ValueError):
        return None


def listing(user_root: Path) -> list[Template]:
    found = [_read(p) for p in sorted(BUILTINS.glob("*.json"))]
    found += [_read(p) for p in sorted(user_root.glob("*/template.json"))]
    return [t for t in found if t is not None]


def by_template_id(user_root: Path, template_id: str) -> Template:
    if not re.fullmatch(ID, template_id):
        raise ValueError("Unknown template.")
    for template in listing(user_root):
        if template.id == template_id:
            return template
    raise ValueError("Unknown template.")


def preview_path(user_root: Path, template: Template) -> Path:
    if template.builtin:
        return BUILTINS / f"{template.id}.mp4"
    return user_root / template.id / "preview.mp4"


def brief_overrides(template: Template) -> dict:
    """The brief fields a template decides; the user's product details stay."""
    return {
        "tone": template.tone,
        "pacing": template.pacing,
        "worn": template.worn,
        "captions": template.captions,
    }


def apply(project: Project, template: Template) -> Project:
    """Copy the template's moves, trims and finishing onto a planned project."""
    from .product import FIDELITY, FIDELITY_WORN, SOUND

    data = project.model_dump()
    fidelity = FIDELITY_WORN if template.worn else FIDELITY
    for shot, plan in zip(data["shots"], template.shots, strict=False):
        if shot["beat"] != plan.beat:
            continue
        shot["trim_start"], shot["trim_end"] = 0, plan.trim_end
        if plan.camera and plan.camera != shot.get("camera"):
            preset = by_id(plan.camera.split("@")[0])
            motion = f"{preset.motion} {fidelity} {SOUND[template.tone]}"
            draft = shot["draft"]
            draft["motion_prompt"] = motion
            draft["prompt"] = f"{draft.get('art_direction') or ''}\n\n{motion}".strip()
            shot["camera"] = plan.camera
    data["caption_style"] = template.caption_style
    data["caption_position"] = template.caption_position
    data["music_prompt"] = template.music_prompt
    result = Project.model_validate(data)
    # Keep caption cues inside the (possibly shorter) shots they open.
    frames = result.frames
    for caption in result.captions:
        caption.end_frame = min(caption.end_frame, frames)
        caption.start_frame = min(caption.start_frame, caption.end_frame - 1)
    return result


def save_from(project: Project, user_root: Path, export: Path | None) -> Template:
    """Save a project's plan (never its media) as a user template."""
    brief = project.product.brief if project.product else None
    template = Template(
        id=f"user-{uuid.uuid4().hex[:12]}",
        name=project.title[:80],
        tone=brief.tone if brief else "calm",
        pacing=brief.pacing if brief else "calm",
        worn=brief.worn if brief else False,
        captions=brief.captions if brief else "open-close",
        caption_style=project.caption_style,
        caption_position=project.caption_position,
        music_prompt=project.music_prompt,
        shots=[
            TemplateShot(beat=s.beat, camera=s.camera, trim_end=s.trim_end)
            for s in project.shots
        ],
    )
    folder = user_root / template.id
    folder.mkdir(parents=True)
    atomic_json(folder / "template.json", json.loads(template.model_dump_json()))
    if export is not None and export.is_file():
        # A short silent loop of the user's own export, for the gallery tile.
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-ss",
                "1",
                "-t",
                "3",
                "-i",
                str(export),
                "-an",
                "-vf",
                "fps=20,scale=216:384:flags=lanczos",
                "-c:v",
                "libx264",
                "-crf",
                "30",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(folder / "preview.mp4"),
            ],
            check=False,
            timeout=120,
        )
    return template
