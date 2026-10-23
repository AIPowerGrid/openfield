# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Named, versioned LTX camera moves for image-mode shots.

A preset fills the shot's motion text and trim; the text stays editable. Only
presets that passed native review on two subjects are offered in the app. The
rest stay listed with the reason they were rejected.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PREVIEWS = Path(__file__).with_name("presets")


# Recommended trims keep each move to its gentle opening: the owner found the
# full-length moves too much in a finished short (2026-10-22 review).
class CameraPreset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z-]{1,30}$")
    # Effects transform the scene or the subject's surface; they are opt-in
    # and never act on people.
    kind: Literal["camera", "effect"] = "camera"
    name: str
    version: int = Field(ge=1)
    motion: str
    trim_end: int = Field(ge=24, le=120)
    qualified: bool = False
    note: str = ""

    @property
    def preview(self) -> Path:
        return PREVIEWS / f"{self.id}.mp4"


KEEP = "The subject keeps its exact shape, colors and surface."
RECOGNISABLE = "The product stays recognisable: same shape, size and position."

PRESETS = [
    CameraPreset(
        id="push-in",
        name="Slow push-in",
        version=1,
        motion=f"The camera slowly and steadily pushes straight in toward the subject. {KEEP}",
        trim_end=60,
        qualified=True,
        note="Native 2026-10-22: clear steady push on bottle and lighthouse; shapes and print held.",
    ),
    CameraPreset(
        id="pull-back",
        name="Pull-back reveal",
        version=1,
        motion=(
            "The camera starts close on the subject and slowly pulls back to reveal "
            f"the wider scene around it. {KEEP}"
        ),
        trim_end=60,
        qualified=True,
        note="Native 2026-10-22: strong reveal on the bottle, gentler on the lighthouse; shapes held.",
    ),
    CameraPreset(
        id="orbit",
        name="Orbit",
        version=1,
        motion=(
            "The camera smoothly orbits around the subject in a half circle, keeping "
            f"it centered while the background slides past. {KEEP}"
        ),
        trim_end=36,
        qualified=False,
        note="Rejected 2026-10-22 (owner review): the trimmed 1.5 s move barely reads, and longer runs turn the logo out of view.",
    ),
    CameraPreset(
        id="crash-zoom",
        name="Crash zoom",
        version=1,
        motion=(
            "A sudden, fast crash zoom rushes in toward the subject and then holds "
            f"steady on it. {KEEP}"
        ),
        trim_end=60,
        qualified=False,
        note="Rejected 2026-10-22 (owner review): renders a smooth push-in, indistinguishable from Slow push-in.",
    ),
    CameraPreset(
        id="dolly-zoom",
        name="Dolly zoom",
        version=1,
        motion=(
            "Dolly zoom: the camera moves backward while zooming in, so the subject "
            f"stays the same size while the background stretches away. {KEEP}"
        ),
        trim_end=96,
        qualified=False,
        note="Rejected 2026-10-22: no vertigo effect; renders a plain pull-back or push-in.",
    ),
    CameraPreset(
        id="fpv",
        name="FPV fly-through",
        version=1,
        motion=(
            "Fast FPV drone shot: the camera swoops forward low and fast through the "
            f"scene and sweeps past the subject. {KEEP}"
        ),
        trim_end=72,
        qualified=False,
        note="Rejected 2026-10-22: dramatic on scenes but flies away from a product until it vanishes.",
    ),
    CameraPreset(
        id="hero-rise",
        name="Low-angle hero rise",
        version=1,
        motion=(
            "The camera starts low near the ground and rises upward, tilting to keep "
            f"the subject large and heroic in frame. {KEEP}"
        ),
        trim_end=40,
        qualified=False,
        note="Rejected 2026-10-22 (owner review): the camera rises and the product slides out of the bottom of the frame.",
    ),
    CameraPreset(
        id="handheld",
        name="Handheld drift",
        version=1,
        motion=(
            "Subtle handheld camera: a gentle natural sway and drift around the "
            f"subject, as if filmed by hand. {KEEP}"
        ),
        trim_end=96,
        qualified=False,
        note="Rejected 2026-10-22: reads as a slow push-in; the sway is too subtle to distinguish.",
    ),
]


EFFECTS = [
    CameraPreset(
        id="earth-zoom-out",
        kind="effect",
        name="Earth zoom out",
        version=1,
        motion=(
            "The camera starts on the subject and zooms smoothly straight up and "
            "out, through the clouds into space until the whole Earth is visible."
        ),
        trim_end=120,
        qualified=False,
        note="Rejected 2026-10-22 (owner review): the product drops out of frame, then a cross-fade to a stock Earth; not a zoom out.",
    ),
    CameraPreset(
        id="turning-metal",
        kind="effect",
        name="Turning metal",
        version=1,
        motion=(
            "The subject's surface slowly turns into polished liquid chrome, "
            f"reflecting the scene around it. {RECOGNISABLE}"
        ),
        trim_end=96,
        qualified=False,
        note="Rejected 2026-10-22: convincing chrome on the bottle but it erases the printed logo; nothing happens on scenes.",
    ),
    CameraPreset(
        id="wireframe",
        kind="effect",
        name="Wireframe",
        version=1,
        motion=(
            "The whole scene gradually becomes a glowing holographic wireframe of "
            f"thin cyan lines, then fades back to reality. {RECOGNISABLE}"
        ),
        trim_end=120,
        qualified=True,
        note="Native 2026-10-22: glowing cyan wireframe on bottle and cliff, logo still readable, returns to normal by 5 s.",
    ),
    CameraPreset(
        id="point-cloud",
        kind="effect",
        name="Point cloud",
        version=1,
        motion=(
            "The scene breaks into a shimmering cloud of tiny glowing points that "
            f"drift apart and gather back together. {RECOGNISABLE}"
        ),
        trim_end=96,
        qualified=False,
        note="Rejected 2026-10-22 (owner review): a lens flare and sparkle noise, not a readable point cloud.",
    ),
    CameraPreset(
        id="disintegration",
        kind="effect",
        name="Disintegration",
        version=1,
        motion=(
            "The subject slowly disintegrates into fine glowing dust that blows "
            "away on the wind, starting from its edges."
        ),
        trim_end=72,
        qualified=False,
        note="Rejected 2026-10-22: a golden dust burst, but the product never disintegrates and the lighthouse just fades into haze.",
    ),
    CameraPreset(
        id="garden-bloom",
        kind="effect",
        name="Garden bloom",
        version=1,
        motion=(
            "Green vines and colorful flowers grow and bloom quickly all around "
            f"the subject. {KEEP}"
        ),
        trim_end=96,
        qualified=True,
        note="Native 2026-10-22: vines and red flowers grow around bottle and cliff; product and logo untouched.",
    ),
    CameraPreset(
        id="freezing",
        kind="effect",
        name="Freezing",
        version=1,
        motion=(
            "Frost and ice crystals spread quickly across the scene and over the "
            f"subject, freezing everything. {RECOGNISABLE}"
        ),
        trim_end=96,
        qualified=True,
        note="Native 2026-10-22: frost sweeps across both scenes; the bottle frosts over but stays recognisable.",
    ),
    CameraPreset(
        id="smoke-reveal",
        kind="effect",
        name="Smoke reveal",
        version=1,
        motion=(
            "Thick soft smoke swirls across the frame and slowly clears to reveal "
            f"the subject. {KEEP}"
        ),
        trim_end=120,
        qualified=False,
        note="Rejected 2026-10-22 (owner review): an orange haze washes over and clears; nothing is revealed.",
    ),
]
PRESETS = PRESETS + EFFECTS


def by_id(preset_id: str) -> CameraPreset:
    for preset in PRESETS:
        if preset.id == preset_id:
            return preset
    raise ValueError("Unknown camera preset.")


def available() -> list[CameraPreset]:
    """Presets offered in the app: natively qualified with a bundled preview."""
    return [p for p in PRESETS if p.qualified and p.preview.is_file()]
