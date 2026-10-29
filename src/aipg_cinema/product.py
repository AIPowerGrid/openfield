# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Product videos: a brief becomes a shot plan, and the closing packshot is
composed locally from the supplied photo. The product's name, text and logo are
never generated; only the scene shots go through image and video models."""

import argparse
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from pydantic import BaseModel

from .brief import ProductBrief, ProductSetup
from .contracts import TakeDraft
from .finishing import _FONT_LOCK, coverage
from .presets import by_id
from .project import Caption, Project, Shot, atomic_json
from .reshoot import video_format
from .sequence import inspect
from .typography import LOCK as TYPE_LOCK
from .typography import face, manifest, stack, text_layer, wrap

# Where a failed ffmpeg encode leaves its stderr, inside the run folder.
PACKSHOT_LOG = "packshot.log"
FRAMES = 120
# Generated product shots are cut to their first three seconds: the opening
# image is the faithful frame and label/shape drift grows over time.
PRODUCT_SHOT_FRAMES = 72
# The packshot resolves the ad in two seconds; its push-in runs to the last
# frame and its type is fully in by frame 25.
PACKSHOT_FRAMES = 48
# Calm pacing: a slow push-in hook and a slow pull-back reveal, held long
# enough that a 9-10 s short has only two cuts.
CALM_MOVES = ("push-in", "pull-back")
CALM_FRAMES = (84, 96)
# Top and bottom fractions kept clear of platform UI (vertical feeds overlay
# usernames, captions and buttons on the lower fifth).
SAFE = {"portrait": (0.12, 0.80), "square": (0.08, 0.90), "landscape": (0.08, 0.92)}
TONES = {
    "premium": (
        (
            "soft directional key light, deep gentle shadows, glossy reflections, "
            "muted neutral palette with warm highlights"
        ),
        "slow, smooth dolly movement",
    ),
    "playful": (
        "bright high-key light, saturated pastel colors, crisp clean shadows",
        "bouncy handheld push with a playful tilt",
    ),
    "bold": (
        (
            "hard rim light, high contrast, deep black background, one saturated "
            "accent color"
        ),
        "fast confident push-in",
    ),
    "calm": (
        "diffused natural window light, airy soft tones, light haze",
        "gentle slow drift",
    ),
}
# LTX generates sound from the prompt; without a sound line native product
# takes came back near-silent (about -80 dB). One line per tone keeps the
# shots' generated audio consistent across cuts.
SOUND = {
    "premium": "Sound: a warm, minimal score with soft piano notes over quiet room "
    "tone. No speech.",
    "playful": "Sound: an upbeat, bouncy pop groove with light percussion. No speech.",
    "bold": "Sound: a confident, punchy electronic beat with deep bass over subtle "
    "ambience. No speech.",
    "calm": "Sound: soft ambient pads with gentle natural room tone. No speech.",
}
# Prompts never name the product: image models write a named product's name
# onto it (a native test embossed invented lettering on an unlabelled bottle).
FIDELITY = (
    "The product's shape, colors and surface stay exactly as in the reference. "
    "No people."
)


# Owner-approved on 2026-10-21 for apparel: a fictional AI-generated model,
# never a real person's likeness. Native tests kept the chest print readable
# in most but not all looks, so every look still needs review.
FIDELITY_WORN = (
    "The garment's shape, colors and print stay exactly as in the reference: the "
    "same emblem and wordmark, same size and position. The model is a fictional "
    "adult. Background signs and lights are soft and out of focus, with no "
    "readable lettering."
)
# Appended when a shot also references the previous shot's approved look, so a
# multi-shot ad keeps one model instead of a new person per shot.
CONTINUITY = (
    " Keep the same person as in the second reference image: identical face, "
    "hair, skin tone and build."
)


def _worn_beats(brief: ProductBrief, light: str, camera: str, where: str) -> list:
    # Tone camera moves are ignored for people: a native bold-tone push-in
    # ended in a blurred close-up and smeared the wordmark as it grew.
    camera = "Steady camera with only a very slow push-in"
    garment = "the garment from the reference image"
    model = f"a fictional adult model wearing {garment}"
    keep = "facing the camera so the print stays fully visible"
    beats = [
        (
            "Hook",
            "hook",
            (
                f"Close-up of the chest print on {garment}, worn by a fictional adult "
                f"model, fabric texture visible, shallow depth of field, {light}."
            ),
            (
                "Slow push-in on the print; the fabric moves gently with breathing. "
                f"{camera}."
            ),
            # The close-up is all print; any caption would cover the logo.
            None,
        ),
        (
            "Reveal",
            "reveal",
            f"Fashion photograph of {model}, waist-up, {keep}, in {where}, {light}.",
            (
                "The model breathes naturally, shifts weight and gives a slight smile; "
                f"slow push-in. {camera}."
            ),
            brief.tagline or None,
        ),
    ]
    angles = (
        "Three-quarter waist-up shot of {model}",
        "Mid shot of {model}, walking toward the camera",
        "Candid mid shot of {model}, turning back to the camera",
    )
    for index, benefit in enumerate(brief.benefits or [""]):
        beats.append(
            (
                "Benefit" if benefit else "Detail",
                "build" if benefit else "detail",
                f"{angles[index].format(model=model)}, {keep}, in a different spot near "
                f"{where}."
                + (
                    f" The setting hints at: {benefit.rstrip('.').lower()}."
                    if benefit
                    else ""
                )
                + f" {light[0].upper()}{light[1:]}.",
                f"Small natural movements, the model stays {keep}. {camera}.",
                benefit or None,
            )
        )
    return beats


class PlannedShot(BaseModel):
    shot: Shot
    image_direction: str | None
    packshot: bool = False


def plan(brief: ProductBrief, frame_format: str = "portrait") -> dict:
    """Hook, reveal, benefit beats and a local packshot (4-6 shots).

    Scene shots start in image mode without a look: each needs a generated
    product-reference image before it can render, so the product is never
    invented from text alone.
    """
    video_format(frame_format)
    light, camera = TONES[brief.tone]
    camera = camera[0].upper() + camera[1:]
    where = brief.setting or "a clean, uncluttered surface"
    # Drafted settings arrive as sentences ("A sunlit desk..."); prompts use
    # them mid-sentence. Keep acronyms such as "AIPG" intact.
    if where[:1].isupper() and not where[1:2].isupper():
        where = where[0].lower() + where[1:]
    where = where.rstrip(".")
    subject = "the product from the reference image"
    fidelity = FIDELITY_WORN if brief.worn else FIDELITY
    beats = (
        []
        if brief.worn
        else [
            (
                "Hook",
                "hook",
                # An extreme close-up hook read as a blurry crop (owner review
                # 2026-10-22). Open wide in the setting; the push-in closes in.
                (
                    f"Wide establishing shot of {subject} standing upright on {where}, "
                    f"the whole product clearly visible in the lower middle of the "
                    f"frame with the scene around it, {light}."
                ),
                (
                    "Slow macro push-in across the product; a sweep of light glides "
                    f"over its surface. {camera}."
                ),
                brief.hook or f"Meet {brief.name}",
            ),
            (
                "Reveal",
                "reveal",
                (
                    f"Hero shot of {subject}, centered on {where}, {light}, space above "
                    "the product."
                ),
                (
                    "Slow orbit around the product as the light rises; the background "
                    f"stays soft. {camera}."
                ),
                brief.tagline or None,
            ),
        ]
    )
    # Each benefit gets its own angle and a nearby, different spot. Reusing the
    # reveal's setting made a native benefit shot nearly repeat the reveal.
    # No top-down angle: a native overhead shot lost a clear glass product.
    angles = (
        "Low-angle three-quarter view",
        "Eye-level side view",
        "Tight three-quarter close-up",
    )
    for index, benefit in enumerate(brief.benefits or [""]):
        beats.append(
            (
                "Benefit" if benefit else "Detail",
                "build" if benefit else "detail",
                (
                    f"{angles[index]} of {subject}, upright and fully visible as "
                    f"the clear focus, in a different spot near {where}. The "
                    f"setting hints at: {benefit.rstrip('.').lower()}. "
                    f"{light[0].upper()}{light[1:]}."
                    if benefit
                    else f"Close-up of the materials and texture of {subject}, {light}."
                ),
                (
                    f"Subtle camera drift; gentle ambient motion in the environment "
                    f"while the product stays still and sharp. {camera}."
                ),
                benefit or None,
            )
        )
    if brief.worn:
        beats = _worn_beats(brief, light, camera, where)
    calm = brief.pacing == "calm"
    if calm:
        # Owner-approved default (2026-10-22 review): two long, gentle shots
        # and the packshot. Benefit shots and stronger moves made too many
        # cuts and too much camera; "punchy" keeps the per-benefit plan.
        beats = beats[:2]
        if not brief.worn:
            # The push-in already moves closer; an extreme close-up start was
            # too tight (owner review 2026-10-22). Open on the whole product.
            title, beat, _, motion, caption = beats[0]
            beats[0] = (
                title,
                beat,
                (
                    f"Medium close-up of {subject}, the whole product visible with "
                    f"space around it, shallow depth of field, {light}."
                ),
                motion,
                caption,
            )
    shots, captions = [], []
    frame = 0
    for title, beat, image, motion, caption in beats:
        # Matches the editor: art direction describes the look image, the
        # motion prompt directs LTX, and image takes send both.
        image = f"{image} {fidelity}"
        preset = by_id(CALM_MOVES[len(shots)]) if calm else None
        if preset:
            motion = preset.motion
        motion = f"{motion} {fidelity} {SOUND[brief.tone]}"
        shot = Shot(
            title=title,
            beat=beat,
            draft=TakeDraft(
                mode="image",
                frame_format=frame_format,
                art_direction=image,
                motion_prompt=motion,
                prompt=f"{image}\n\n{motion}",
            ),
            trim_end=CALM_FRAMES[len(shots)] if calm else PRODUCT_SHOT_FRAMES,
            camera=f"{preset.id}@{preset.version}" if preset else None,
        )
        shots.append(PlannedShot(shot=shot, image_direction=image))
        if brief.captions == "open-close":
            # One opening line; the packshot carries the close. The worn print
            # close-up stays clean, so its opening line moves to the reveal.
            opening = 1 if brief.worn else 0
            caption = (
                (brief.hook or f"Meet {brief.name}")
                if len(shots) - 1 == opening
                else None
            )
        if caption:
            captions.append(
                Caption(
                    text=caption,
                    start_frame=frame + 6,
                    end_frame=frame + shot.trim_end - 6,
                )
            )
        frame += shot.trim_end
    packshot = Shot(
        title="Packshot",
        beat="payoff",
        draft=TakeDraft(
            mode="image",
            frame_format=frame_format,
            prompt="Packshot composed locally from the supplied product photo.",
        ),
        trim_end=PACKSHOT_FRAMES,
    )
    shots.append(PlannedShot(shot=packshot, image_direction=None, packshot=True))
    return {"brief": brief, "shots": shots, "captions": captions}


def plan_project(project: Project, setup: ProductSetup) -> Project:
    """Fill an empty project with the product plan; nothing is generated."""
    result = plan(setup.brief, project.frame_format)
    packshot = next(item.shot for item in result["shots"] if item.packshot)
    return Project.model_validate(
        project.model_dump()
        | {
            "shots": [item.shot.model_dump() for item in result["shots"]],
            "captions": [item.model_dump() for item in result["captions"]],
            # Lower cues would sit over a centered product; upper cues would
            # cover a model's face, so worn shorts caption low.
            "caption_position": "lower" if setup.brief.worn else "upper",
            "caption_style": "studio",
            "product": setup.model_copy(update={"packshot_shot_id": packshot.id}),
        }
    )


LOOK_SIZES = {"landscape": (1344, 768), "portrait": (720, 1280), "square": (1024, 1024)}
KLEIN_MODELS = {
    "cloud": "flux-2-klein-4b-fp8.safetensors",
    "self-hosted": "flux-2-klein-4b.safetensors",
}
# Native tests: MOSS refinement at 0.4 keeps the product; 0.65 changed its
# colors. MOSS alone cannot place a product into a new scene.
MOSS_REFINE = 0.4


def look_graph(
    prompt: str,
    seed: int = 42,
    *,
    frame_format: str = "portrait",
    backend: str = "self-hosted",
    refine: bool = False,
    continuity: bool = False,
) -> tuple[dict, str]:
    """Klein places the reference product in a scene; MOSS optionally refines."""
    from .look import graph as moss_graph
    from .reshoot import node

    if not prompt.strip() or len(prompt) > 4000:
        raise ValueError("Describe the product scene in 1-4000 characters.")
    if type(seed) is not int or not 0 <= seed <= 2**63 - 1:
        raise ValueError("Choose a non-negative whole-number seed below 2^63.")
    if refine and backend != "self-hosted":
        raise ValueError("MOSS refinement needs the owned image runtime.")
    width, height = LOOK_SIZES[frame_format]
    workflow = {
        "product": node("LoadImage", image="product.png"),
        "model": node(
            "UNETLoader", unet_name=KLEIN_MODELS[backend], weight_dtype="default"
        ),
        "clip": node(
            "CLIPLoader",
            clip_name="qwen_3_4b.safetensors",
            type="flux2",
            device="default",
        ),
        "vae": node("VAELoader", vae_name="flux2-vae.safetensors"),
        "positive": node("CLIPTextEncode", clip=["clip", 0], text=prompt),
        "negative": node("ConditioningZeroOut", conditioning=["positive", 0]),
        "encode": node("VAEEncode", pixels=["product", 0], vae=["vae", 0]),
        "ref-positive": node(
            "ReferenceLatent", conditioning=["positive", 0], latent=["encode", 0]
        ),
        "ref-negative": node(
            "ReferenceLatent", conditioning=["negative", 0], latent=["encode", 0]
        ),
        "empty": node(
            "EmptyFlux2LatentImage", width=width, height=height, batch_size=1
        ),
        "schedule": node("Flux2Scheduler", steps=4, width=width, height=height),
        "noise": node("RandomNoise", noise_seed=seed),
        "guider": node(
            "CFGGuider",
            model=["model", 0],
            positive=["ref-positive", 0],
            negative=["ref-negative", 0],
            cfg=1,
        ),
        "sampler": node("KSamplerSelect", sampler_name="euler"),
        "sample": node(
            "SamplerCustomAdvanced",
            noise=["noise", 0],
            guider=["guider", 0],
            sampler=["sampler", 0],
            sigmas=["schedule", 0],
            latent_image=["empty", 0],
        ),
        "decode": node("VAEDecode", samples=["sample", 0], vae=["vae", 0]),
        "save": node(
            "SaveImage", images=["decode", 0], filename_prefix="openreshoot/product"
        ),
    }
    if continuity:
        # Chain a second reference: the previous shot's approved look.
        workflow["continuity"] = node("LoadImage", image="continuity.png")
        workflow["continuity-encode"] = node(
            "VAEEncode", pixels=["continuity", 0], vae=["vae", 0]
        )
        for side in ("positive", "negative"):
            workflow[f"continuity-{side}"] = node(
                "ReferenceLatent",
                conditioning=[f"ref-{side}", 0],
                latent=["continuity-encode", 0],
            )
        workflow["guider"]["inputs"].update(
            positive=["continuity-positive", 0], negative=["continuity-negative", 0]
        )
    if not refine:
        return workflow, "save"
    moss = moss_graph(prompt, seed, MOSS_REFINE, frame_format=frame_format)
    for key in ("source", "save"):
        del moss[key]
    for key, value in moss.items():
        for name, link in value["inputs"].items():
            if isinstance(link, list) and link[0] in moss:
                value["inputs"][name] = ["moss-" + link[0], link[1]]
        workflow["moss-" + key] = value
    # MOSS starts from Klein's decoded image instead of a source frame.
    workflow["moss-scale"]["inputs"]["image"] = ["decode", 0]
    workflow["moss-save"] = node(
        "SaveImage",
        images=["moss-decode", 0],
        filename_prefix="openreshoot/product-refined",
    )
    return workflow, "moss-save"


def make_look(args: argparse.Namespace) -> None:
    from .cli import sdk_client, submit_and_collect

    if not args.execute:
        raise ValueError("No job sent. Pass --execute to submit one image job.")
    photo = load_photo(args.photo)
    workflow_graph, output = look_graph(
        args.prompt,
        args.seed,
        frame_format=args.frame_format,
        backend=args.backend,
        refine=args.refine,
        continuity=args.continuity is not None,
    )
    endpoint = (
        "https://cloud.comfy.org"
        if args.backend == "cloud"
        else os.environ.get("COMFY_LOOK_BASE_URL", "")
    )
    with sdk_client(
        args.backend,
        endpoint,
        credential_scope="cloud-look" if args.backend == "cloud" else "look",
    ) as client:
        args.run_dir.mkdir(parents=True, exist_ok=False)
        reference = args.run_dir / "product.png"
        flat = Image.new("RGB", photo.size, _base_color(photo))
        flat.paste(photo, mask=photo.getchannel("A"))
        flat.save(reference)
        (args.run_dir / "workflow.json").write_text(
            json.dumps(workflow_graph, indent=2)
        )
        workflow = client.workflows.from_json(workflow_graph)
        workflow.set_input("product", "image", client.assets.from_file(reference))
        if args.continuity is not None:
            previous = args.run_dir / "continuity.png"
            Image.open(args.continuity).convert("RGB").save(previous)
            workflow.set_input("continuity", "image", client.assets.from_file(previous))
        submit_and_collect(
            client,
            workflow,
            args.run_dir,
            output,
            look_render=True,
            frame_format=args.frame_format,
            backend=args.backend,
            base_url=endpoint,
            product_look=True,
            refine=args.refine,
        )


def load_photo(path: Path) -> Image.Image:
    if path.stat().st_size > 12 * 1024 * 1024:
        raise ValueError("Choose a product photo smaller than 12 MB.")
    try:
        image = Image.open(path)
    except Image.DecompressionBombError as error:
        raise ValueError(
            "Choose a product photo no larger than 16 megapixels."
        ) from error
    with image:
        if image.format not in ("PNG", "JPEG", "WEBP"):
            raise ValueError("Choose a PNG, JPEG or WebP product photo.")
        if image.width * image.height > 16_000_000:
            raise ValueError("Choose a product photo no larger than 16 megapixels.")
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Choose a still product photo, not an animation.")
        return ImageOps.exif_transpose(image).convert("RGBA")


def _cutout(photo: Image.Image) -> bool:
    return photo.getchannel("A").getextrema()[0] < 250


def _base_color(photo: Image.Image) -> tuple[int, int, int]:
    small = photo.resize((32, 32), Image.Resampling.BOX)
    raw = small.tobytes()
    data = [tuple(raw[i : i + 4]) for i in range(0, len(raw), 4)]
    pixels = [p for p in data if p[3] > 200] or data
    return tuple(sum(p[i] for p in pixels) // len(pixels) for i in range(3))


def _background(photo: Image.Image, size: tuple[int, int], color) -> Image.Image:
    # A studio sweep in the photo's own tone. A blurred copy of the photo was
    # rejected: its subject reappears as a dark blob behind the text.
    width, height = size
    base = color if color is not None else _base_color(photo)
    top = tuple(round(c * 0.62) for c in base)
    bottom = tuple(round(c * 0.22) for c in base)
    ramp = Image.linear_gradient("L").resize((1, height))
    background = Image.composite(
        Image.new("RGB", (1, height), bottom), Image.new("RGB", (1, height), top), ramp
    ).resize(size)
    glow = Image.new("L", size, 0)
    ImageDraw.Draw(glow).ellipse(
        (-width * 0.2, height * 0.05, width * 1.2, height * 0.75), fill=90
    )
    glow = glow.filter(ImageFilter.GaussianBlur(round(width * 0.12)))
    light = Image.new("RGB", size, tuple(min(255, round(c * 1.1) + 20) for c in base))
    return Image.composite(light, background, glow)


# Display type per tone: a wide techno face for bold/playful briefs, an
# elegant serif for premium/calm ones. Montserrat sets supporting lines.
TITLE_TYPE = {
    "bold": ("michroma", None, 0.066, 0.06, True),
    "playful": ("michroma", None, 0.066, 0.06, True),
    "premium": ("playfair", 600, 0.092, 0.01, False),
    "calm": ("playfair", 500, 0.092, 0.01, False),
}


def _title_layer(text: str, tone: str, unit: int, scale: float) -> Image.Image | None:
    name, weight, size, tracking, upper = TITLE_TYPE[tone]
    text = text.upper() if upper else text
    typeface = face(name, text, round(unit * size * scale), weight)
    lines = wrap(text, typeface, round(unit * 0.84), tracking)
    if len(lines) > 2:
        return None
    shadow = max(2, round(unit * 0.012))
    layers = [
        text_layer(line, typeface, (255, 255, 255), tracking=tracking, shadow=shadow)
        for line in lines
    ]
    return stack(layers, round(typeface.size * 0.32))


def _tagline_layer(text: str, unit: int, scale: float) -> Image.Image | None:
    if not text:
        return None
    typeface = face("montserrat", text, round(unit * 0.034 * scale), 500)
    lines = wrap(text, typeface, round(unit * 0.8), 0.04)
    if len(lines) > 2:
        return None
    shadow = max(2, round(unit * 0.008))
    layers = [
        text_layer(line, typeface, (238, 238, 242), tracking=0.04, shadow=shadow)
        for line in lines
    ]
    return stack(layers, round(typeface.size * 0.3))


def _rule_layer(unit: int, accent) -> Image.Image:
    width, thickness = round(unit * 0.1), max(2, round(unit * 0.004))
    layer = Image.new("RGBA", (width, thickness))
    ImageDraw.Draw(layer).rounded_rectangle(
        (0, 0, width - 1, thickness - 1), radius=thickness // 2, fill=(*accent, 255)
    )
    return layer


def _cta_layer(text: str, unit: int, scale: float, accent, ink) -> Image.Image | None:
    if not text:
        return None
    label = text.upper()
    typeface = face("montserrat", label, round(unit * 0.03 * scale), 700)
    glyphs = text_layer(label, typeface, ink, tracking=0.16)
    pad_x, pad_y = round(typeface.size * 1.5), round(typeface.size * 0.55)
    blur = max(3, round(unit * 0.012))
    width, height = glyphs.width + 2 * pad_x, glyphs.height + 2 * pad_y
    layer = Image.new("RGBA", (width + 4 * blur, height + 4 * blur))
    shadow = Image.new("L", layer.size)
    ImageDraw.Draw(shadow).rounded_rectangle(
        (
            2 * blur,
            2 * blur + blur // 2,
            2 * blur + width,
            2 * blur + height + blur // 2,
        ),
        radius=height // 2,
        fill=120,
    )
    dark = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    dark.putalpha(shadow.filter(ImageFilter.GaussianBlur(blur)))
    layer.alpha_composite(dark)
    pill = Image.new("RGBA", layer.size)
    ImageDraw.Draw(pill).rounded_rectangle(
        (2 * blur, 2 * blur, 2 * blur + width, 2 * blur + height),
        radius=height // 2,
        fill=(*accent, 255),
    )
    layer.alpha_composite(pill)
    layer.alpha_composite(glyphs, (2 * blur + pad_x, 2 * blur + pad_y))
    return layer


def _contrast_ink(color) -> tuple[int, int, int]:
    luminance = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
    return (16, 17, 19) if luminance > 150 else (255, 255, 255)


def _fade(layer: Image.Image, amount: float) -> Image.Image:
    if amount >= 1:
        return layer
    faded = layer.copy()
    faded.putalpha(layer.getchannel("A").point(lambda value: round(value * amount)))
    return faded


def _ease(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return 0.5 - math.cos(math.pi * value) / 2


def layout(
    photo: Image.Image,
    frame_format: str,
    name: str,
    tagline: str = "",
    cta: str = "",
    accent: tuple[int, int, int] | None = None,
    tone: str = "premium",
) -> dict:
    width, height = video_format(frame_format).output_size
    top, bottom = SAFE[frame_format]
    unit = min(width, round(height * 0.5625))
    accent = accent or (245, 245, 240)
    with _FONT_LOCK, TYPE_LOCK:
        for scale in (1.0, 0.9, 0.8, 0.7):
            title = _title_layer(name, tone, unit, scale)
            line = _tagline_layer(tagline, unit, scale)
            button = _cta_layer(cta, unit, scale, accent, _contrast_ink(accent))
            if title is None or (tagline and line is None):
                continue
            gap = round(unit * 0.028)
            rule = _rule_layer(unit, accent) if line is not None else None
            texts = [
                layer for layer in (title, rule, line, button) if layer is not None
            ]
            text_height = sum(layer.height for layer in texts) + gap * (len(texts) - 1)
            band = (bottom - top) * height
            box_height = band - text_height - 2 * gap
            if (
                box_height >= band * 0.45
                and max(t.width for t in texts) <= width * 0.86
            ):
                break
        else:
            raise ValueError(
                "The product name, tagline or call to action is too long for a "
                "readable packshot. Shorten it."
            )
    box = (min(width * 0.76, unit * 0.9), box_height)
    product = ImageOps.contain(
        photo, (round(box[0]), round(box[1])), Image.Resampling.LANCZOS
    )
    if not _cutout(photo):
        mask = Image.new("L", product.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, product.width - 1, product.height - 1),
            radius=round(min(product.size) * 0.04),
            fill=255,
        )
        product.putalpha(ImageChops.multiply(product.getchannel("A"), mask))
    block = product.height + 2 * gap + text_height
    y = round(top * height + (band - block) / 2)
    positions = {"product": (width // 2, y + product.height // 2)}
    y += product.height + 2 * gap
    placed = []
    for key, layer in (
        ("title", title),
        ("rule", rule),
        ("tagline", line),
        ("cta", button),
    ):
        if layer is not None:
            placed.append((key, layer, ((width - layer.width) // 2, y)))
            y += layer.height + gap
    if y - gap > bottom * height + 1:
        raise ValueError("The packshot layout left the safe area.")
    return {
        "size": (width, height),
        "product": product,
        "center": positions["product"],
        "text": placed,
    }


def frames(
    photo: Image.Image,
    frame_format: str,
    name: str,
    tagline: str = "",
    cta: str = "",
    accent: tuple[int, int, int] | None = None,
    background: tuple[int, int, int] | None = None,
    tone: str = "premium",
):
    plan = layout(photo, frame_format, name, tagline, cta, accent, tone)
    width, height = plan["size"]
    product = plan["product"]
    base = _background(photo, (width, height), background)
    radius = max(4, round(width * 0.02))
    shadow = Image.new(
        "RGBA", (product.width + 4 * radius, product.height + 4 * radius)
    )
    shadow.putalpha(0)
    silhouette = Image.new("RGBA", product.size, (0, 0, 0, 255))
    silhouette.putalpha(product.getchannel("A").point(lambda value: value * 0.55))
    shadow.alpha_composite(silhouette, (2 * radius, 2 * radius))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius))
    # Text starts staggered so a three-second trim still ends on the full card.
    starts = {"title": 4, "rule": 8, "tagline": 10, "cta": 15}
    for index in range(FRAMES):
        canvas = base.convert("RGBA")
        zoom = 0.97 + 0.05 * _ease(index / (FRAMES - 1))
        size = (
            max(1, round(product.width * zoom)),
            max(1, round(product.height * zoom)),
        )
        moving = product.resize(size, Image.Resampling.LANCZOS)
        cast = shadow.resize(
            (round(shadow.width * zoom), round(shadow.height * zoom)),
            Image.Resampling.BILINEAR,
        )
        cx, cy = plan["center"]
        canvas.alpha_composite(
            cast, (cx - cast.width // 2, cy - cast.height // 2 + round(height * 0.012))
        )
        canvas.alpha_composite(
            moving, (cx - moving.width // 2, cy - moving.height // 2)
        )
        for key, layer, position in plan["text"]:
            amount = _ease((index - starts[key]) / 10)
            if amount > 0:
                offset = round((1 - amount) * height * 0.01)
                canvas.alpha_composite(
                    _fade(layer, amount), (position[0], position[1] + offset)
                )
        yield canvas.convert("RGB")


def _color(value: str | None) -> tuple[int, int, int] | None:
    if value is None:
        return None
    text = value.removeprefix("#")
    if len(text) != 6 or any(c not in "0123456789abcdefABCDEF" for c in text):
        raise ValueError("Colors use #RRGGBB hex notation.")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))


def render_packshot(
    photo_path: Path,
    directory: Path,
    *,
    name: str,
    tagline: str = "",
    cta: str = "",
    frame_format: str = "portrait",
    accent: str | None = None,
    background: str | None = None,
    tone: str = "premium",
) -> Path:
    """Write `reshoot.mp4` (120 frames, 24 fps, silent) plus provenance.

    The output matches a selected take's contract, so the sequence exporter can
    use it as the closing shot without any inference.
    """
    brief = ProductBrief(name=name, tagline=tagline, cta=cta, tone=tone)
    photo = load_photo(photo_path)
    width, height = video_format(frame_format).output_size
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "reshoot.mp4"
    partial = directory / "reshoot.partial.mp4"
    if destination.exists():
        raise ValueError("This packshot already exists. Keep it and use a new take.")
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            "24",
            "-i",
            "-",
            "-frames:v",
            str(FRAMES),
            "-c:v",
            "libx264",
            "-crf",
            "16",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-video_track_timescale",
            "24000",
            "-map_metadata",
            "-1",
            "-metadata",
            "title=AIPG - product packshot",
            "-metadata",
            "description=Composed locally from the supplied product photo; not AI-generated.",
            "-movflags",
            "+faststart",
            str(partial),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": os.environ.get("PATH", os.defpath)},
    )
    try:
        last = None
        for frame in frames(
            photo,
            frame_format,
            brief.name,
            brief.tagline,
            brief.cta,
            _color(accent),
            _color(background),
            brief.tone,
        ):
            process.stdin.write(frame.tobytes())
            last = frame
        process.stdin.close()
        error = process.stderr.read().decode(errors="replace")
        if process.wait(timeout=300) != 0:
            # FFmpeg's stderr is for the log, not the browser.
            log = directory / PACKSHOT_LOG
            log.write_text(f"ffmpeg exited {process.returncode}\n{error}")
            raise ValueError(f"The packshot could not be composed; see {log}.")
        info = inspect(partial, width, height, FRAMES)
        last.save(directory / "packshot.png")
        atomic_json(
            directory / "packshot.json",
            {
                "version": 1,
                "ai_generated": False,
                "photo_sha256": hashlib.sha256(photo_path.read_bytes()).hexdigest(),
                "name": brief.name,
                "tagline": brief.tagline,
                "cta": brief.cta,
                "frame_format": frame_format,
                "accent": accent,
                "background": background,
                "tone": brief.tone,
                "font_sha256": coverage()["sha256"],
                "display_fonts": {
                    key: value["sha256"] for key, value in manifest().items()
                },
                "output": info,
            },
        )
        partial.replace(destination)
        return destination
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        partial.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    shot = commands.add_parser("packshot", help="Compose a packshot from a photo")
    shot.add_argument("photo", type=Path)
    shot.add_argument("--name", required=True)
    shot.add_argument("--tagline", default="")
    shot.add_argument("--cta", default="")
    shot.add_argument("--accent")
    shot.add_argument("--background")
    shot.add_argument(
        "--tone", default="premium", choices=["premium", "playful", "bold", "calm"]
    )
    shot.add_argument(
        "--format",
        dest="frame_format",
        default="portrait",
        choices=["portrait", "square", "landscape"],
    )
    shot.add_argument("--run-dir", type=Path, required=True)
    looks = commands.add_parser("look", help="Generate one product-reference look")
    looks.add_argument("photo", type=Path)
    looks.add_argument("--prompt", required=True)
    looks.add_argument("--seed", type=int, default=42)
    looks.add_argument("--refine", action="store_true")
    looks.add_argument("--continuity", type=Path)
    looks.add_argument("--backend", choices=["cloud", "self-hosted"], required=True)
    looks.add_argument(
        "--format",
        dest="frame_format",
        default="portrait",
        choices=["portrait", "square", "landscape"],
    )
    looks.add_argument("--run-dir", type=Path, required=True)
    looks.add_argument("--execute", action="store_true")
    planning = commands.add_parser("plan", help="Print a product shot plan as JSON")
    planning.add_argument("--brief", type=Path, required=True)
    planning.add_argument(
        "--format",
        dest="frame_format",
        default="portrait",
        choices=["portrait", "square", "landscape"],
    )
    args = parser.parse_args(argv)
    if args.command == "look":
        make_look(args)
    elif args.command == "packshot":
        print(
            render_packshot(
                args.photo,
                args.run_dir,
                name=args.name,
                tagline=args.tagline,
                cta=args.cta,
                frame_format=args.frame_format,
                accent=args.accent,
                background=args.background,
                tone=args.tone,
            )
        )
    else:
        brief = ProductBrief.model_validate_json(args.brief.read_text())
        result = plan(brief, args.frame_format)
        print(
            json.dumps(
                {
                    "brief": brief.model_dump(),
                    "shots": [item.model_dump() for item in result["shots"]],
                    "captions": [item.model_dump() for item in result["captions"]],
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
