# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Camera flight from a photo with MiniMax H3: a frozen-time orbit or an FPV run.

Two moves on H3's first-and-last-frame model (FL2VA):

- orbit: the photo is pinned as both the first and the last frame, so the
  camera circles the frozen scene and lands back where it started. Uses
  pablodawson's 360 Orbit LoRA (MiniMax H3 Community License).
- fpv: the photo is the first frame only and the camera flies through the
  scene; Jojocodex's Camera Motion LoRA (Apache-2.0), strength 0.9, with its
  "camera motion" trigger first in the prompt.

Comfy's FL2V turbo LoRA (hosted by Comfy Cloud) cuts the run to eight steps.
The 2026-10-26 owned-GPU renders the owner kept (showroom car orbit, skyline
FPV) used 20 steps at 768x1344; the turbo recipe was compared on 2026-10-28.
Comfy Cloud hosts the base models and the turbo LoRA but neither move LoRA;
a Creator plan can import them into the account's model library.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from .swap import AUDIO_VAE, FPS, FRAMES, SIZES, Unavailable, help_text

MOVES = {
    "orbit": {
        "name": "Bullet-time orbit",
        "lora": "h3-360-orbit-flf2v-v1.safetensors",
        "url": "https://huggingface.co/pablodawson/MiniMax-H3-360-Orbit-LoRA",
        "strength": 1.0,
        "pin_last": True,
    },
    "fpv": {
        "name": "FPV fly-through",
        "lora": "h3-camera-motion-v1-3000.safetensors",
        "url": "https://huggingface.co/Jojocodex/minimax-h3-Camera-Motion-lora",
        "strength": 0.9,
        "pin_last": False,
    },
    # Speak from text: no move LoRA, the line goes in the prompt and H3 makes
    # the voice and the lips. The owner dropped the 2026-10-26 talking stills
    # from the reel for mouth timing, so this stays beta.
    "speak": {
        "name": "Make them speak",
        "lora": None,
        "url": "",
        "strength": 0.0,
        "pin_last": False,
    },
}
TURBO_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
TURBO_LORA_URL = "https://huggingface.co/Comfy-Org/MiniMax-H3"
PREFERRED = {
    "diffusion_models": (
        "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "minimax_h3_fl2va_pruned_bf16.safetensors",
        "minimax_h3_fl2va_bf16.safetensors",
    ),
    "text_encoders": (
        "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
    ),
    "vae": (
        "minimax_h3_video_vae_int8_convrot.safetensors",
        "minimax_h3_video_vae_fp16.safetensors",
    ),
}
STEPS = 8
MAX_NOTE = 300


@dataclass(frozen=True)
class Recipe:
    unet: str
    clip: str
    vae: str


def recipe(listing: dict[str, list[str]], backend: str, move: str) -> Recipe:
    if move not in MOVES:
        raise ValueError("Choose the orbit, the FPV flight or the line.")
    chosen, missing = {}, []
    for folder, names in PREFERRED.items():
        present = [name for name in names if name in listing.get(folder, [])]
        if present:
            chosen[folder] = present[0]
        else:
            missing.append(names[-1])
    if AUDIO_VAE not in listing.get("vae", []):
        missing.append(AUDIO_VAE)
    for lora in (MOVES[move]["lora"], TURBO_LORA):
        if lora and lora not in listing.get("loras", []):
            missing.append(str(lora))
    if missing:
        raise Unavailable(missing, backend)
    return Recipe(chosen["diffusion_models"], chosen["text_encoders"], chosen["vae"])


def prompt(move: str, note: str = "") -> str:
    note = " ".join(note.split())
    if len(note) > MAX_NOTE:
        raise ValueError("Keep the note under 300 characters.")
    if move == "orbit":
        subject = note or "the scene"
        return (
            f"A frozen-time 360 degree camera orbit around {subject}. One frozen "
            "instant: people and objects keep their exact position, pose and shape, "
            "faces, hands, clothing and liquids do not move. Only the camera moves, "
            "circling the whole scene in one continuous shot and returning to the "
            "exact starting view. No cuts, no zoom, nothing added."
        )
    if move == "fpv":
        where = note or "through the scene"
        return (
            f"camera motion. Fast FPV drone flight {where}, swooping low then "
            "rising, aerial drone shot with dynamic camera motion, one continuous shot."
        )
    if move == "speak":
        line = note.replace('"', "'").strip()
        if len(line) < 2:
            raise ValueError("Type the line they should say.")
        return (
            "The person in the picture holds the camera at arm's length, looks "
            f'straight into it and says: "{line}". Handheld selfie video, the '
            "camera moves a little, a natural voice, lips in sync with the words, "
            "one continuous shot."
        )
    raise ValueError("Choose the orbit, the FPV flight or the line.")


def node(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def graph(
    models: Recipe, move: str, shape: str, seed: int = 42, note: str = ""
) -> dict:
    if shape not in SIZES:
        raise ValueError("Choose portrait, landscape or square framing.")
    settings = MOVES[move]
    width, height = SIZES[shape]
    frames = {"first_frame": ["photo", 0]}
    if settings["pin_last"]:
        frames["last_frame"] = ["photo", 0]
    return {
        "photo": node("LoadImage", image="photo.png"),
        "model": node("UNETLoader", unet_name=models.unet, weight_dtype="default"),
        **(
            {
                "move": node(
                    "LoraLoaderModelOnly",
                    model=["model", 0],
                    lora_name=settings["lora"],
                    strength_model=settings["strength"],
                )
            }
            if settings["lora"]
            else {}
        ),
        "turbo": node(
            "LoraLoaderModelOnly",
            model=["move", 0] if settings["lora"] else ["model", 0],
            lora_name=TURBO_LORA,
            strength_model=1.0,
        ),
        "clip": node(
            "CLIPLoader", clip_name=models.clip, type="minimax", device="default"
        ),
        "vae": node("VAELoader", vae_name=models.vae),
        "audio-vae": node("VAELoader", vae_name=AUDIO_VAE),
        "i2v": node(
            "MiniMaxH3ImageToVideo",
            clip=["clip", 0],
            vae=["vae", 0],
            prompt=prompt(move, note),
            width=width,
            height=height,
            length=FRAMES,
            **frames,
        ),
        "noise": node("RandomNoise", noise_seed=seed),
        "sampler": node("KSamplerSelect", sampler_name="res_multistep"),
        "schedule": node(
            "BasicScheduler",
            model=["turbo", 0],
            scheduler="simple",
            steps=STEPS,
            denoise=1,
        ),
        "guider": node("BasicGuider", model=["turbo", 0], conditioning=["i2v", 0]),
        "sample": node(
            "SamplerCustomAdvanced",
            noise=["noise", 0],
            guider=["guider", 0],
            sampler=["sampler", 0],
            sigmas=["schedule", 0],
            latent_image=["i2v", 1],
        ),
        "decode": node("VAEDecode", samples=["sample", 0], vae=["vae", 0]),
        "decode-audio": node(
            "VAEDecodeAudio", samples=["sample", 0], vae=["audio-vae", 0]
        ),
        "video": node("CreateVideo", images=["decode", 0], fps=FPS),
        "save": node(
            "SaveVideo",
            video=["video", 0],
            filename_prefix="openfield/flight",
            format="mp4",
            codec="h264",
        ),
        "save-audio": node(
            "SaveAudio", audio=["decode-audio", 0], filename_prefix="openfield/flight"
        ),
    }


def prepare_photo(source: Path, destination: Path, shape: str) -> Path:
    """The photo centre-cropped to the flight's frame shape, so H3 sees no bars."""
    width, height = SIZES[shape]
    with Image.open(source) as image:
        fitted = ImageOps.fit(
            ImageOps.exif_transpose(image).convert("RGB"), (width, height)
        )
        partial = destination.with_suffix(".partial.png")
        fitted.save(partial)
    partial.replace(destination)
    return destination


def finish(run_dir: Path, video: Path, audio: Path | None) -> Path:
    destination = run_dir / "flight.mp4"
    partial = destination.with_suffix(".partial.mp4")
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(video), *(["-i", str(audio)] if audio else []),
            "-map", "0:v:0", *(["-map", "1:a:0"] if audio else []),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", str(partial),
        ],
        check=True,
        timeout=300,
    )  # fmt: skip
    partial.replace(destination)
    return destination


__all__ = [
    "MOVES",
    "Recipe",
    "Unavailable",
    "finish",
    "graph",
    "help_text",
    "prepare_photo",
    "prompt",
    "recipe",
]
