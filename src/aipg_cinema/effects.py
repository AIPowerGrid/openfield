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
  Org's LTX-2 LoRA template (workflows/ltx-2-effect.json). The template pins
  the photo only in its half-size pass, and its upscale pass then redrew the
  face, so the photo is pinned again before that pass.
- "clip": in-context LoRAs on our LTX-2.5 Transform graph, guided by the
  clip itself instead of its edges.

Rejected 2026-10-25: Instant shave (the beard stayed), Cakeify (only a knife
appeared), and the product-ad LoRA (no visible gain over our product shots).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

WORKFLOW = Path(__file__).resolve().parents[2] / "workflows" / "ltx-2-effect.json"
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

    @property
    def kind(self) -> str:
        return "clip" if self.graph == "clip" else "photo"

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
