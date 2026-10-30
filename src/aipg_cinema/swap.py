# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Replace the person with MiniMax H3: one pass, their motion and voice kept.

The clip is H3's video reference, the photo its picture reference and the
clip's own soundtrack its audio reference, so the new person copies the
original performance and speaks in the original voice. Two LoRAs sit on the
Ref2VA model: akatz-ai's Character Swap (without it the model hands the
original person back) and Comfy's own four-step turbo (the official R2V
template's Lightning option), which made the same picture as twenty steps in
a quarter of the time in the 2026-10-27 side-by-side.

Comfy Cloud hosts the base models and the turbo LoRA but not the swap LoRA;
a Creator plan can import it into the account's model library. The exact
file names differ between Cloud (int8 / NVFP4 builds) and a local worker, so
the recipe is chosen from what the backend lists. Tested 2026-10-26/27 on an
owned 96 GB GPU at 768x1344 (portrait); landscape and square use the same
pixel budget and Cloud has not been run.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx

# OPENFIELD_SWAP_LORA lets a worker try another character-swap LoRA file.
SWAP_LORA = os.environ.get("OPENFIELD_SWAP_LORA", "h3_character_swap_v1.5.safetensors")
SWAP_LORA_URL = "https://huggingface.co/akatz-ai/MiniMax-H3-Character-Swap-LoRA"
TURBO_LORA = "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
TURBO_LORA_URL = "https://huggingface.co/Comfy-Org/MiniMax-H3"
# First listed name wins: Cloud's int8/NVFP4 builds, then the bf16/fp16 files.
PREFERRED = {
    "diffusion_models": (
        "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
        "minimax_h3_ref2va_pruned_bf16.safetensors",
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
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
# H3 takes 17k+5 frames; 124 covers the five-second window at 24 fps.
FRAMES = 124
FPS = 24
# The tested portrait bucket, and the same pixel budget for the other shapes.
SIZES = {"portrait": (768, 1344), "landscape": (1344, 768), "square": (1024, 1024)}
STEPS = 4
MAX_NOTE = 300
CLOUD_URL = "https://cloud.comfy.org"
# "person": the photo replaces the person (swap LoRA). "background": the photo
# is the new place and the person stays; no LoRA, so Comfy Cloud runs it as is.
MODES = ("person", "background")


@dataclass(frozen=True)
class Recipe:
    unet: str
    clip: str
    vae: str


class Unavailable(Exception):
    """The backend lacks an H3 swap model; `help` says what to add."""

    def __init__(self, missing: list[str], backend: str):
        self.missing = missing
        self.backend = backend
        super().__init__(help_text(missing, backend))


def help_text(missing: list[str], backend: str) -> str:
    names = ", ".join(missing)
    if backend == "cloud":
        if missing == [SWAP_LORA]:
            return (
                f"Comfy Cloud does not host {SWAP_LORA}. On a Creator plan, import "
                f"it from {SWAP_LORA_URL} into your Model Library (Models > Import), "
                "then try again. Nothing was submitted."
            )
        return f"Comfy Cloud does not list {names}. Nothing was submitted."
    return (
        f"Add {names} to your ComfyUI worker (loras: {SWAP_LORA_URL} and "
        f"{TURBO_LORA_URL}; the MiniMax H3 Ref2VA files from {TURBO_LORA_URL}). "
        "Nothing was submitted."
    )


def listed(backend: str, upstream: str, folder: str, key: str = "") -> list[str]:
    """Model file names the backend lists for one models folder."""
    if backend == "cloud":
        response = httpx.get(
            f"{CLOUD_URL}/api/experiment/models/{folder}",
            headers={"X-API-Key": key} if key else {},
            timeout=10,
        )
    else:
        response = httpx.get(f"{upstream}/experiment/models/{folder}", timeout=5)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        return []
    return [
        item["name"]
        for item in data
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]


FOLDERS = ("diffusion_models", "text_encoders", "vae", "loras")


def available(
    backend: str,
    upstream: str = "",
    key: str = "",
    folders: tuple[str, ...] = FOLDERS,
) -> dict[str, list[str]]:
    return {folder: listed(backend, upstream, folder, key) for folder in folders}


def recipe(listing: dict[str, list[str]], backend: str, mode: str = "person") -> Recipe:
    """The model files to load, or Unavailable naming what the backend lacks."""
    chosen, missing = {}, []
    for folder, names in PREFERRED.items():
        present = [name for name in names if name in listing.get(folder, [])]
        if present:
            chosen[folder] = present[0]
        else:
            missing.append(names[-1])
    if AUDIO_VAE not in listing.get("vae", []):
        missing.append(AUDIO_VAE)
    if mode not in MODES:
        raise ValueError("Choose the person or the background.")
    for lora in (SWAP_LORA, TURBO_LORA) if mode == "person" else (TURBO_LORA,):
        if lora not in listing.get("loras", []):
            missing.append(lora)
    if missing:
        raise Unavailable(missing, backend)
    return Recipe(chosen["diffusion_models"], chosen["text_encoders"], chosen["vae"])


def prompt(note: str = "", mode: str = "person") -> str:
    """The wording from the kept 2026-10-26 swaps, plus the user's note."""
    note = " ".join(note.split())
    if len(note) > MAX_NOTE:
        raise ValueError("Keep the note under 300 characters.")
    if mode not in MODES:
        raise ValueError("Choose the person or the background.")
    if mode == "background":
        # Tested 2026-10-28: kitchen clip onto a skyline look, person, spoon
        # and voice kept, light matched.
        text = (
            "Keep the person in <Video 1> exactly as they are: the same face, "
            "hair, clothes, position, pose, gestures, mouth movement and voice, "
            "with the same camera and framing. Replace only the background: the "
            "place behind them becomes the scene in <Picture 1>, its setting, "
            "depth, lighting and colours filling the whole frame behind the "
            "person, with matching light on them. Do not show the reference "
            "picture as a flat image."
        )
        return f"{text} {note}".strip()
    text = (
        "Replace only the person speaking in the foreground in <Video 1> with the "
        "character in <Picture 1>. Keep the replacement character's identity, "
        "outfit, and art style from <Picture 1>. Preserve the source video's camera, "
        "framing, background, lighting, objects, and all other people. Match the "
        "selected person's position, scale, pose, and movement throughout the clip. "
        "Do not show the reference sheet or its background."
    )
    return f"{text} {note}".strip()


def node(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def graph(
    models: Recipe, shape: str, seed: int = 42, note: str = "", mode: str = "person"
) -> dict:
    if shape not in SIZES:
        raise ValueError("Choose portrait, landscape or square framing.")
    width, height = SIZES[shape]
    text = prompt(note, mode)
    graph = {
        "source": node("LoadVideo", file="source.mp4"),
        "parts": node("GetVideoComponents", video=["source", 0]),
        "character": node("LoadImage", image="photo.png"),
        "model": node("UNETLoader", unet_name=models.unet, weight_dtype="default"),
        "swap": node(
            "LoraLoaderModelOnly",
            model=["model", 0],
            lora_name=SWAP_LORA,
            strength_model=1.0,
        ),
        "turbo": node(
            "LoraLoaderModelOnly",
            model=["swap", 0],
            lora_name=TURBO_LORA,
            strength_model=1.0,
        ),
        "clip": node(
            "CLIPLoader", clip_name=models.clip, type="minimax", device="default"
        ),
        "vae": node("VAELoader", vae_name=models.vae),
        "audio-vae": node("VAELoader", vae_name=AUDIO_VAE),
        "ref": node(
            "MiniMaxH3ReferenceToVideo",
            clip=["clip", 0],
            vae=["vae", 0],
            audio_vae=["audio-vae", 0],
            prompt=text,
            width=width,
            height=height,
            length=FRAMES,
            ref_image_size="match",
            **{
                "ref_images.ref_image_0": ["character", 0],
                "ref_videos.ref_video_0": ["parts", 0],
                # The clip's own sound as the audio reference keeps the voice.
                "ref_video_audios.ref_video_audio_0": ["parts", 1],
            },
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
        "guider": node("BasicGuider", model=["turbo", 0], conditioning=["ref", 0]),
        "sample": node(
            "SamplerCustomAdvanced",
            noise=["noise", 0],
            guider=["guider", 0],
            sampler=["sampler", 0],
            sigmas=["schedule", 0],
            latent_image=["ref", 1],
        ),
        "decode": node("VAEDecode", samples=["sample", 0], vae=["vae", 0]),
        "decode-audio": node(
            "VAEDecodeAudio", samples=["sample", 0], vae=["audio-vae", 0]
        ),
        # Picture and sound are saved apart and muxed locally: a worker pinned
        # to LTX's audio clock rejects H3 sound inside SaveVideo.
        "video": node("CreateVideo", images=["decode", 0], fps=FPS),
        "save": node(
            "SaveVideo",
            video=["video", 0],
            filename_prefix="openfield/swap",
            format="mp4",
            codec="h264",
        ),
        "save-audio": node(
            "SaveAudio", audio=["decode-audio", 0], filename_prefix="openfield/swap"
        ),
    }
    if mode == "background":
        del graph["swap"]
        graph["turbo"]["inputs"]["model"] = ["model", 0]
    return graph


def finish(run_dir: Path, video: Path, audio: Path | None) -> Path:
    """Mux the saved picture and sound into replaced.mp4, then the wipe."""
    from .tools import compare

    destination = run_dir / "replaced.mp4"
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
    compare(run_dir / "source.mp4", destination, run_dir / "compare.mp4", "wipe")
    return destination
