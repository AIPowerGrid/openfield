# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""One-click effects from trained LTX LoRAs hosted on Comfy Cloud.

Effects written only as prompts (melt, levitate, inflate...) looked generic
on LTX-2.5 (2026-10-25), so every effect here is a LoRA trained on real clips
of that effect. Each was rendered on Comfy Cloud on the same kitchen portrait
before being listed; the note records what that render showed.

Three graphs carry them:

- "ltx25": our LTX-2.5 photo graph with the LoRA after the model. LTX-2.3
  LoRAs load on 2.5 unchanged.
- "ltx2": the effect LoRAs that exist only for LTX-2 19B run through Comfy
  Org's LTX-2 LoRA template (ltx-2-effect.json, vendored). The template pins
  the photo only in its half-size pass, and its upscale pass then redrew the
  face, so the photo is pinned again before that pass.
- "clip": in-context LoRAs on our LTX-2.5 Transform graph, guided by the
  clip itself instead of its edges.

Rejected 2026-10-25: Instant shave (the beard stayed), the first Cakeify LoRA
(only a knife appeared; the listed v2 cuts and shows the cake), and the
product-ad LoRA (no visible gain over our product shots).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# The vendored template ships inside the package so installed wheels find it;
# the repo-root copy under workflows/ stays beside its upstream notice and
# README, and a test keeps the two identical.
PACKAGED_WORKFLOW = Path(__file__).with_name("workflows") / "ltx-2-effect.json"
REPO_WORKFLOW = Path(__file__).resolve().parents[2] / "workflows" / "ltx-2-effect.json"
WORKFLOW = PACKAGED_WORKFLOW if PACKAGED_WORKFLOW.is_file() else REPO_WORKFLOW
LTX2_LORA_NODES = ("109", "110")


@dataclass(frozen=True)
class Effect:
    id: str
    name: str
    graph: Literal["ltx25", "ltx2", "clip"]
    lora: str
    strength: float
    trigger: str
    action: str
    note: str
    source: str
    # "photo" (Animate a photo), "clip" (Transform) or "idea" (Idea to video,
    # where a style LoRA shapes the whole picture because no frame is pinned).
    kind_name: str = ""

    @property
    def kind(self) -> str:
        return self.kind_name or ("clip" if self.graph == "clip" else "photo")

    def prompt(self, scene: str) -> str:
        scene = " ".join(scene.split()).rstrip(".")
        parts = [self.trigger, f"{scene}." if scene else "", self.action]
        return " ".join(part for part in parts if part)


EFFECTS = [
    Effect(
        id="inflate",
        name="Inflate",
        graph="ltx2",
        lora="ltx2-inflate.safetensors",
        strength=0.85,
        trigger="infl4t3 it --",
        action=(
            "The main subject inflates like a balloon, swelling up big, round and "
            "shiny until it floats up into the air."
        ),
        note="Swells into a balloon and floats off; faint letters can show on it.",
        source="huggingface.co/kabachuha/ltx2-inflate-it",
    ),
    Effect(
        id="crush",
        name="Crush",
        graph="ltx2",
        lora="ltx2-crush.safetensors",
        strength=0.85,
        trigger="c5us4 --",
        action="A hydraulic press slowly comes down on the main subject and crushes it flat.",
        note="A press comes down and flattens her; the face holds until it is covered.",
        source="huggingface.co/kabachuha/ltx2-hydraulic-press",
    ),
    Effect(
        id="squish",
        name="Squish",
        graph="ltx2",
        lora="ltx2-squish.safetensors",
        strength=0.85,
        trigger="squish it --",
        action=(
            "Two giant hands come in from the sides and squish the main subject like "
            "soft dough, squashing and bulging comically, then it springs back."
        ),
        note="Giant hands squish her like clay; she stays the same person.",
        source="Comfy-Org/ltx-2 (template LoRA)",
    ),
    Effect(
        id="atomic-explosion",
        name="Atomic explosion",
        graph="ltx2",
        lora="ltx2-atomic_explosion.safetensors",
        strength=0.85,
        trigger="",
        action=(
            "Far behind the main subject a huge atomic explosion erupts: a blinding "
            "flash and a mushroom cloud of fire, the shockwave shaking the scene."
        ),
        note="A mushroom cloud rises through the kitchen window behind her.",
        source="huggingface.co/Nebsh/LTX2_AtomicExplosion (no license stated)",
    ),
    Effect(
        id="cakeify",
        name="Cakeify",
        graph="ltx2",
        lora="ltx2-cakeify-v2.safetensors",
        strength=0.85,
        trigger="c4k3 cakeify it --",
        action=(
            "A knife comes in and cuts into the main subject, revealing that it is "
            "a cake inside: soft sponge, cream and layers under the realistic surface."
        ),
        note="A knife slices in and the thing is cake; the outside keeps its look.",
        source="huggingface.co/kabachuha/ltx2-cakeify (LTX-2 community license)",
    ),
    Effect(
        id="eat",
        name="Eat it",
        graph="ltx2",
        lora="ltx2-eat-v2.safetensors",
        strength=0.85,
        trigger="",
        action=(
            "A person leans in from the side, picks up the main subject with both "
            "hands and takes a big bite out of it, chewing happily, vivid colors."
        ),
        note="Someone picks the thing up and bites it; it crunches like food.",
        source="huggingface.co/kabachuha/ltx2-eat (LTX-2 community license)",
    ),
    Effect(
        id="timelapse",
        name="Human timelapse",
        graph="ltx2",
        lora="ltx2-timelapse.safetensors",
        strength=0.85,
        trigger="",
        action=(
            "A timelapse: hours pass in seconds while the person holds still, the "
            "sun arcs across the sky, shadows sweep over the ground, clouds race, "
            "and daylight turns to dusk and then night with lights coming on."
        ),
        note="Hours pass in five seconds around a person who holds still.",
        source="huggingface.co/Nebsh/LTX2_Lora_TimelapseHuman (no license stated)",
    ),
    Effect(
        id="outfit-check",
        name="Outfit check",
        graph="ltx2",
        lora="ltx2-outfit_check.safetensors",
        strength=0.85,
        trigger="",
        action=(
            "An outfit check: the person snaps their fingers and their clothes "
            "instantly change into a completely different stylish outfit, then "
            "they pose and turn to show it off."
        ),
        note="She poses and the outfit changes a little; the person and place stay.",
        source="huggingface.co/Nebsh/LTX2_Lora_Outfitcheck (no license stated)",
    ),
    Effect(
        id="animatediff",
        name="AnimateDiff look",
        graph="ltx2",
        lora="ltx2-animatediff.safetensors",
        strength=0.85,
        trigger="",
        action=(
            "The scene comes alive in the dreamy, shimmering AnimateDiff style: soft "
            "flickering details, painterly motion, the subject moving gently."
        ),
        note="The skyline slides from dusk into night with boats crossing the water.",
        source="huggingface.co/Nebsh/LTX2_Animatediff_Lora (no license stated)",
    ),
    Effect(
        id="googly-eyes",
        name="Googly eyes",
        graph="ltx25",
        lora="ltx-2.3-googlyeyes.safetensors",
        strength=1.0,
        trigger="googlyeyes.",
        action=(
            "The person has huge wobbly googly eyes that jiggle as they move and talk."
        ),
        note="Plastic googly eyes stay on her face as she talks; present from frame one.",
        source="huggingface.co/TheBurgstall/ltx-2.3-googlyeyes-lora",
    ),
    Effect(
        id="cross-eyed",
        name="Cross-eyed",
        graph="clip",
        lora="ltx-2.3-22b-ic-lora-cross-eyed-0.9.safetensors",
        strength=1.0,
        trigger="",
        action=(
            "Their eyes are strongly crossed, both pupils turned in toward the nose "
            "the whole time. Everything else is unchanged."
        ),
        note="Her eyes cross while she keeps talking and gesturing; the clip is kept.",
        source="huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-Cross-Eyed",
    ),
]
# Idea-to-video styles: vrgamedevgirl84's LTX-2.3 style LoRAs, hosted by Comfy
# Cloud under these names and loaded on our LTX-2.5 graph. The trigger goes
# first; each was rendered on the owned GPU on 2026-10-28 (see the note).
STYLE_SOURCE = "huggingface.co/vrgamedevgirl84"
EFFECTS += [
    Effect(
        id="claymation",
        name="Claymation",
        graph="ltx25",
        lora="LTX_2.3_Clay_Mation_Style.safetensors",
        strength=1.0,
        trigger="claymation style, stop motion clay, handcrafted clay characters in a clay diorama.",
        action="Everything is sculpted clay with fingerprints and soft edges, animated in stop motion.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX_2.3_Clay_Mation_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="paper-cutout",
        name="Paper cut-out",
        graph="ltx25",
        lora="LTX_2.3_Paper_Cut_Out_Style.safetensors",
        strength=1.0,
        trigger="Pap3rCut0u7, paper cutout style, handcrafted layered paper diorama.",
        action="Every element is cut paper with visible edges and stacked layers.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX_2.3_Paper_Cut_Out_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="cozy-felt",
        name="Cozy felt",
        graph="ltx25",
        lora="LTX2.3_Cozy_Felt_Style.safetensors",
        strength=1.0,
        trigger="F3ltCut0u7, felt cutout style, handcrafted felt diorama with stitched felt textures.",
        action="Characters, objects and backgrounds are all soft plush felt.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX2.3_Cozy_Felt_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="pixar-toon",
        name="Pixar-style toon",
        graph="ltx25",
        lora="LTX_2.3_Pixar_Toon_Style.safetensors",
        strength=1.0,
        trigger="P1x4r, pixar-style animation, stylized CGI characters, high-end animated film style.",
        action="A stylized CGI animated film look across the whole scene.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX_2.3_Pixar_Toon_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="nineties-cartoon",
        name="90s cartoon",
        graph="ltx25",
        lora="LTX_2.3_90s_Animation_Style.safetensors",
        strength=1.0,
        trigger="9o4n1m, manic 90s gross-out cartoon, hand-painted grotesque animation, ugly-funny cartoon style.",
        action="Everything is a hand-painted 1990s TV cartoon with wobbly exaggerated characters.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX_2.3_90s_Animation_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="wild-west",
        name="Wild West",
        graph="ltx25",
        lora="LTX_2.3_Wild_West_Style.safetensors",
        strength=1.0,
        trigger="W1ldW4st, cinematic realistic Wild West video, grounded frontier western footage.",
        action="A weathered frontier western film look: dust, leather, sun-bleached wood.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX_2.3_Wild_West_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="post-apocalyptic",
        name="Post-apocalyptic",
        graph="ltx25",
        lora="LTX_2.3_Post_Apocalyptic_Style.safetensors",
        strength=1.0,
        trigger="P0st4p0c0, cinematic post-apocalyptic photorealistic video, gritty realistic textures.",
        action="A grounded post-apocalyptic survival film look with ruined, overgrown surroundings.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX_2.3_Post_Apocalyptic_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="fantasy-anime",
        name="Fantasy anime",
        graph="ltx25",
        lora="LTX_2.3_Fantasy_Anime_Style.safetensors",
        strength=1.0,
        trigger="f4nt4sy4n1m6, cinematic fantasy anime cel-shaded illustration, hand-drawn fantasy anime style.",
        action="A painted cel-shaded fantasy anime look across the whole scene.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX_2.3_Fantasy_Anime_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="fantasy-painterly",
        name="Fantasy painting",
        graph="ltx25",
        lora="LTX_2.3_Fantasy_Painterly_Style.safetensors",
        strength=1.0,
        trigger="D4rkP41nt3r, fantasy painterly style, cinematic fantasy painting, oil painted fantasy scene.",
        action="Visible oil brushwork and painted light over the whole scene.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX_2.3_Fantasy_Painterly_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="fantasy-puppet",
        name="Fantasy puppet",
        graph="ltx25",
        lora="LTX_2.3_Fantasy_Puppet_Style.safetensors",
        strength=1.0,
        trigger="6u8p3t, fantasy puppet style, handcrafted fantasy puppet characters, labyrinth-style puppets.",
        action="Every character is a handcrafted foam-and-fabric puppet on a practical set.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX_2.3_Fantasy_Puppet_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="cyberpunk",
        name="Cyberpunk",
        graph="ltx25",
        lora="LTX_2.3_Cinematic_Sci-fi-Cyberpunk_Style.safetensors",
        strength=1.0,
        trigger="C6b4rP8nk, cinematic cyberpunk neo-noir aesthetic, neon-lit futuristic cityscape.",
        action="A rain-slick neon neo-noir science-fiction look.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX_2.3_Cinematic_Sci-fi-Cyberpunk_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="fantasy-realism",
        name="Fantasy realism",
        graph="ltx25",
        lora="LTX_2.3_Fantasy_Realism_Style.safetensors",
        strength=1.0,
        trigger="f4nt4sy, cinematic fantasy realism, premium live-action fantasy cinema shot.",
        action="A live-action fantasy film look with rich costume and practical-set detail.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source=f"{STYLE_SOURCE}/LTX_2.3_Fantasy_Realism_Style_LoRa",
        kind_name="idea",
    ),
    Effect(
        id="star-trek-tng",
        name="90s TV sci-fi",
        graph="ltx25",
        lora="StarTrek_TNG_Style_LTX23_v1.safetensors",
        strength=1.0,
        trigger="Classic 1990s science-fiction television production style, authentic studio lighting and set design.",
        action="A 1990s television science-fiction episode look: starship corridors, bridge sets, broadcast grain.",
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source="huggingface.co/bionicman69/StarTrek_TNG_Style_LTX23 (Apache-2.0)",
        kind_name="idea",
    ),
    Effect(
        id="crt-terminal",
        name="CRT terminal",
        graph="ltx25",
        lora="ltx-2.3-crt-animation-terminal-10000.safetensors",
        strength=1.0,
        trigger="crtanim,",
        action=(
            "Shown on a late-80s CRT monitor: scanlines, phosphor glow, chromatic "
            "aberration, barrel curvature, dithering and choppy limited-frame motion."
        ),
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source="huggingface.co/lovis93/crt-animation-terminal-ltx-2.3-lora (Apache-2.0)",
        kind_name="idea",
    ),
    Effect(
        id="fpv-motion",
        name="FPV drone",
        graph="ltx25",
        lora="ltx2.3_fpv_motion.safetensors",
        strength=1.0,
        trigger="",
        action=(
            "Smooth first-person-view drone footage, the camera gliding low and "
            "banking through the scene in one continuous flight."
        ),
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source="huggingface.co/chsengni/ltx2.3-fpv-motion (Apache-2.0)",
        kind_name="idea",
    ),
    # Lightricks IC-LoRAs for a clip (video-to-video on the Transform graph,
    # guided by the clip itself), gated on Hugging Face under the LTX-2
    # Community License; the owner accepted the gates on 2026-10-28. Clean
    # plate, day-to-night and water were tried the same day and did not take
    # on the distilled two-pass Transform path (no guidance scale), so they
    # are not listed; see tests/REAL_FOOTAGE.md.
    Effect(
        id="colorize",
        name="Colorize",
        graph="clip",
        lora="ltx-2.3-22b-ic-lora-colorization-0.9.safetensors",
        strength=1.0,
        trigger=(
            "Reference shows the scene in grayscale. Edited shows the same scene with "
            "natural colors restored. COLORIZE"
        ),
        action=(
            "natural lifelike colors across the whole scene; subject identity, framing "
            "and background geometry are unchanged, only the color information differs."
        ),
        note="Rendered 2026-10-28 on the owned GPU; see tests/REAL_FOOTAGE.md.",
        source="huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-Colorization",
    ),
]
BY_ID = {effect.id: effect for effect in EFFECTS}


def get(effect_id: str) -> Effect:
    try:
        return BY_ID[effect_id]
    except KeyError:
        raise ValueError(f"Unknown effect: {effect_id}.") from None


def add_lora(workflow: dict, effect: Effect, loader: str) -> dict:
    """Insert the effect LoRA after the model loader node `loader`."""
    for item in workflow.values():
        for name, value in item["inputs"].items():
            if value == [loader, 0]:
                item["inputs"][name] = ["effect-lora", 0]
    workflow["effect-lora"] = {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {
            "model": [loader, 0],
            "lora_name": effect.lora,
            "strength_model": effect.strength,
        },
    }
    return workflow


def guide_with_clip(workflow: dict, effect: Effect) -> dict:
    """Swap the Transform graph's Union LoRA and edge guide for an IC-LoRA."""
    workflow["model"]["inputs"]["lora_name"] = effect.lora
    workflow["model"]["inputs"]["strength_model"] = effect.strength
    for item in workflow.values():
        for name, value in item["inputs"].items():
            if value == ["edges", 0]:
                item["inputs"][name] = ["source-window", 0]
    workflow.pop("edges")
    return workflow


def ltx2_graph(effect: Effect, prompt: str, seed: int, width: int, height: int) -> dict:
    """The LTX-2 19B effect template for one photo, five seconds at 24 fps."""
    workflow = json.loads(WORKFLOW.read_text())
    workflow["3"]["inputs"]["text"] = prompt
    workflow["11"]["inputs"]["noise_seed"] = seed
    workflow["89"]["inputs"].update(width=width, height=height)
    workflow["62"]["inputs"]["value"] = 121
    for node in LTX2_LORA_NODES:
        workflow[node]["inputs"].update(
            lora_name=effect.lora, strength_model=effect.strength
        )
    return workflow
