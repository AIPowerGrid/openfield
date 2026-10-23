# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Named, versioned Transform styles for video-to-video restyles.

A style fills the opening look's art direction (FLUX.2 Klein restyles the first
frame) and the take's motion text (LTX-2.5 with Union Control follows the
source's edges, motion and timing). Both stay editable. Only styles whose
example passed owner review are offered; each bundles a split before/after
preview rendered natively on a credited source clip.

The examples' prompts also named the scene (for example "a busy city
crosswalk"); a style applied in the app uses only the generic wording below.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

PREVIEWS = Path(__file__).with_name("styles")

KEEP_LOOK = "Keep the same subjects, poses, setting and composition."
KEEP_MOTION = (
    "Follow the source motion, subjects and camera exactly in one continuous shot."
)


class TransformStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,30}$")
    name: str
    version: int = Field(ge=1)
    blurb: str
    # Art direction for the opening look and the take's motion text.
    look: str
    motion: str
    # Example source: Commons title, licence and author shown with the preview,
    # and the bundled clip (examples/<example>.mp4) that "Recreate" loads.
    source: str
    example: str = Field(pattern=r"^[a-z][a-z0-9-]{1,30}$")
    qualified: bool = False
    note: str = ""

    @property
    def preview(self) -> Path:
        return PREVIEWS / f"{self.id}.mp4"

    @property
    def poster(self) -> Path:
        return PREVIEWS / f"{self.id}.jpg"

    @property
    def example_clip(self) -> Path:
        return PREVIEWS / "examples" / f"{self.example}.mp4"


MARKET = "A Trip Down Market Street, 1906 · Miles Brothers · public domain"
CROSSWALK = "Diagonal crosswalk, Yonge–Dundas, Toronto · CC0"
BEACH = "Aerial view of sand beach · Nature video, HD - 4K · CC BY 3.0"
SHANGHAI = "Shanghai Bund, Lujiazui skyline timelapse · CC0"
HORSES = "Horses running in a pasture · Field of Dreams · CC BY 3.0"

STYLES = [
    TransformStyle(
        id="neon-future",
        name="Neon future",
        version=1,
        blurb="Night city with neon signs and wet reflective streets.",
        look=(
            "Turn this into a futuristic neon cyberpunk version of the same scene at "
            "night: holographic signs and neon light, glowing vehicles, wet reflective "
            f"ground. {KEEP_LOOK}"
        ),
        motion=(
            "A neon cyberpunk scene at night, holographic signs and neon light, wet "
            f"reflective ground. {KEEP_MOTION}"
        ),
        source=MARKET,
        example="market1906",
        qualified=True,
        note="Owner review 2026-10-22: hero example (1906 street to neon).",
    ),
    TransformStyle(
        id="full-colour",
        name="Full colour",
        version=1,
        blurb="Old black-and-white film as modern colour footage.",
        look=(
            "Restore this old film as modern full-color cinematic footage: warm "
            "natural sunlight, rich period colors, crisp detail, no film damage. "
            f"{KEEP_LOOK}"
        ),
        motion=(
            "Modern full-color cinematic footage, warm natural sunlight, rich period "
            f"colors, crisp detail. {KEEP_MOTION}"
        ),
        source=MARKET,
        example="market1906",
        qualified=True,
        note="Owner review 2026-10-22: approved for the reel; a horse appears in the first second.",
    ),
    TransformStyle(
        id="anime",
        name="Hand-drawn anime",
        version=1,
        blurb="Cel shading, clean line art and a painted sky.",
        look=(
            "Turn this into a hand-drawn anime film scene with cel shading, clean ink "
            f"line art, vivid saturated colors and a soft painted sky. {KEEP_LOOK}"
        ),
        motion=(
            "A hand-drawn anime film scene, cel shading, clean ink line art, vivid "
            f"colors, painted sky. {KEEP_MOTION}"
        ),
        source=CROSSWALK,
        example="crosswalk",
        qualified=True,
        note="Native 2026-10-22: cel look holds for 10 s; walkers follow the source. Owner approved 2026-10-22.",
    ),
    TransformStyle(
        id="animated-3d",
        name="3D animated film",
        version=1,
        blurb="Rounded, toy-like characters in warm bright light.",
        look=(
            "Turn this into a scene from a modern 3D animated feature film: soft "
            "rounded stylized characters and objects, smooth toy-like materials, warm "
            f"bright lighting. {KEEP_LOOK}"
        ),
        motion=(
            "A scene from a 3D animated feature film, stylized rounded characters, "
            f"smooth toy-like materials, warm bright light. {KEEP_MOTION}"
        ),
        source=CROSSWALK,
        example="crosswalk",
        qualified=True,
        note="Native 2026-10-22: rounded animated-film look holds for 10 s; walkers follow the source. Owner approved 2026-10-22.",
    ),
    TransformStyle(
        id="golden-hour",
        name="Golden hour 35mm",
        version=1,
        blurb="Low warm sun, long shadows and gentle film grain.",
        look=(
            "Make this golden hour: low warm sun from the side, long soft shadows, "
            f"glowing amber light, shot on 35mm film with gentle grain. {KEEP_LOOK}"
        ),
        motion=(
            "Golden hour light, low warm sun, long soft shadows, amber glow, 35mm "
            f"film grain. {KEEP_MOTION}"
        ),
        source=CROSSWALK,
        example="crosswalk",
        qualified=True,
        note="Native 2026-10-22: warm low sun holds for 10 s; walkers follow the source. Owner approved 2026-10-22.",
    ),
    TransformStyle(
        id="bioluminescent",
        name="Bioluminescent night",
        version=1,
        blurb="Water and nature glowing electric blue in the dark.",
        look=(
            "Make this a night scene: water and plants glow electric blue with "
            f"bioluminescence, dark surroundings, faint starlight. {KEEP_LOOK}"
        ),
        motion=(
            "A night scene glowing electric blue with bioluminescence under faint "
            f"starlight. {KEEP_MOTION}"
        ),
        source=BEACH,
        example="beach",
        qualified=True,
        note="Owner review 2026-10-22: approved for the reel.",
    ),
    TransformStyle(
        id="ink-wash",
        name="Ink wash painting",
        version=1,
        blurb="Black ink and soft grey washes on rice paper.",
        look=(
            "Turn this into a traditional Chinese ink-wash painting on rice paper: "
            f"black ink lines, soft grey washes, a small red seal stamp. {KEEP_LOOK}"
        ),
        motion=(
            "A Chinese ink-wash painting on rice paper, black ink lines and soft grey "
            f"washes. {KEEP_MOTION}"
        ),
        source=SHANGHAI,
        example="shanghai",
        qualified=True,
        note="Owner review 2026-10-22: approved (calm).",
    ),
    TransformStyle(
        id="watercolor",
        name="Watercolor",
        version=1,
        blurb="Loose bleeding washes with paper showing through.",
        look=(
            "Turn this into a loose watercolor painting on textured paper: soft "
            f"bleeding washes, delicate brushwork, white paper showing through. {KEEP_LOOK}"
        ),
        motion=(
            "A loose watercolor painting, soft bleeding washes, white paper texture. "
            f"{KEEP_MOTION}"
        ),
        source=HORSES,
        example="horses",
        qualified=True,
        note="Native 2026-10-22: washes and paper texture hold for 10 s; horses follow the source. Owner approved 2026-10-22.",
    ),
    TransformStyle(
        id="van-gogh",
        name="Van Gogh oil",
        version=1,
        blurb="Swirling impasto brushstrokes in bold blues and yellows.",
        look=(
            "Turn this into a thick impasto oil painting in the style of Van Gogh: "
            "swirling brushstrokes, bold blues and yellows, textured paint. "
            f"{KEEP_LOOK}"
        ),
        motion=(
            "A thick impasto Van Gogh oil painting, swirling brushstrokes, bold blues "
            f"and yellows. {KEEP_MOTION}"
        ),
        source=MARKET,
        example="market1906",
        qualified=True,
        note="Native 2026-10-22: holds for 10 s on the 1906 street; on aerial drone and beach clips it fades to photo after ~4 s. Owner approved 2026-10-22.",
    ),
]


def by_id(style_id: str) -> TransformStyle:
    for style in STYLES:
        if style.id == style_id:
            return style
    raise ValueError("Unknown Transform style.")


def available() -> list[TransformStyle]:
    """Styles offered in the app: owner-approved with a bundled preview."""
    return [
        s
        for s in STYLES
        if s.qualified and s.preview.is_file() and s.example_clip.is_file()
    ]
