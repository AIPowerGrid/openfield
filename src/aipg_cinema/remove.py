# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Remove anything from a clip: name it, check the mask, paint it out.

Two stages, each one ComfyUI job of core nodes on the video backend:

- find: SAM 3.1 tracks what you named ("the cup") through the five-second
  window; the mask comes back as a preview video with the region lit up, so
  you can see what will go before anything is painted.
- remove: the same tracking, then Wan 2.1 VACE (the 1.3B model, trained at
  480p) regenerates the masked region from a control video with that region
  blacked out, as Comfy's own VACE inpainting template does. The rest of the
  frame is the original picture; the clip's own sound is muxed back locally.

VACE is trained on short clips (81 frames at 16 fps); the window here is 121
frames at 24 fps, which it accepts on the 4k+1 grid. Comfy Cloud and the owned
worker both list the model files (Wan 2.1 VACE 1.3B, UMT5-XXL, the Wan VAE and
SAM 3.1), so nothing has to be imported.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx

from .swap import Unavailable

SAM = "sam3.1_multiplex_fp16.safetensors"
VAE = "wan_2.1_vae.safetensors"
# The dedicated remover (MiniMax-Remover on Wan 2.1 1.3B): no prompt, no fill
# line, the masked region is mid-grey and the mask rides along as a second
# latent. It needs the WanVideoWrapper pack's embeds node, which Comfy Cloud
# has and a core-only worker does not; then the VACE route below is used.
REMOVER = "Wan2_1-MiniMaxRemover_1_3B_fp16.safetensors"
REMOVER_NODE = "WanVideoMiniMaxRemoverEmbeds"
ENGINES = ("remover", "vace")
PREFERRED = {
    "diffusion_models": ("wan2.1_vace_1.3B_fp16.safetensors",),
    "text_encoders": (
        "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "umt5_xxl_fp16.safetensors",
    ),
}
FOLDERS = ("diffusion_models", "text_encoders", "vae", "checkpoints")
# VACE 1.3B's 480p bucket, sides multiples of 16.
SIZES = {"portrait": (480, 848), "landscape": (848, 480), "square": (640, 640)}
FRAMES = 121  # 4k+1 at 24 fps covers the five-second window
FPS = 24
STAGES = ("find", "remove")
GREY = 0x7F7F7F
EXPAND = 40  # pixels at the 480p bucket; the region must cover the object's shadow
MAX_TARGET = 80
MAX_NOTE = 300
NEGATIVE = (
    "bright colors, overexposed, static, blurry details, subtitles, style, "
    "artwork, painting, picture, still, overall gray, worst quality, low quality, "
    "JPEG artifacts, ugly, incomplete, extra fingers, poorly drawn hands, poorly "
    "drawn face, deformed, disfigured, malformed limbs, fused fingers, still "
    "picture, cluttered background, three legs, many people in the background, "
    "walking backwards"
)


@dataclass(frozen=True)
class Recipe:
    unet: str
    clip: str
    engine: str = "vace"


def remover_node_present(backend: str, upstream: str = "") -> bool:
    """Whether the backend has the wrapper's remover node.

    Comfy Cloud had it in its catalogue on 2026-10-28 (its per-node endpoint
    is not served, so that is taken as given); a local worker is asked.
    """
    if backend == "cloud":
        return True
    try:
        response = httpx.get(f"{upstream}/object_info/{REMOVER_NODE}", timeout=5)
        return response.status_code == 200 and REMOVER_NODE in response.json()
    except (httpx.HTTPError, ValueError, OSError):
        return False


def recipe(listing: dict[str, list[str]], backend: str, engine: str = "vace") -> Recipe:
    if engine not in ENGINES:
        raise ValueError("Choose the remover or the VACE engine.")
    if engine == "remover":
        missing = [
            name
            for name, folder in (
                (REMOVER, "diffusion_models"),
                (VAE, "vae"),
                (SAM, "checkpoints"),
            )
            if name not in listing.get(folder, [])
        ]
        if missing:
            raise Unavailable(missing, backend)
        return Recipe(REMOVER, "", "remover")
    chosen, missing = {}, []
    for folder, names in PREFERRED.items():
        present = [name for name in names if name in listing.get(folder, [])]
        if present:
            chosen[folder] = present[0]
        else:
            missing.append(names[-1])
    if VAE not in listing.get("vae", []):
        missing.append(VAE)
    if SAM not in listing.get("checkpoints", []):
        missing.append(SAM)
    if missing:
        raise Unavailable(missing, backend)
    return Recipe(chosen["diffusion_models"], chosen["text_encoders"])


def target_text(target: str) -> str:
    target = " ".join(target.split()).strip(" .")
    if not 2 <= len(target) <= MAX_TARGET:
        raise ValueError("Name what to remove in 2 to 80 characters.")
    return target


def prompt(target: str, note: str = "", fill: str = "") -> str:
    """What the hole should show; naming the object itself paints it back.

    Plain "with the spoon gone" and "with the pot gone" both regenerated the
    object on 2026-10-28, so the positive prompt describes only what is there
    instead and the object goes to the negative prompt.
    """
    note, fill = " ".join(note.split()), " ".join(fill.split()).rstrip(".")
    if len(note) > MAX_NOTE or len(fill) > MAX_NOTE:
        raise ValueError("Keep the note and the fill under 300 characters.")
    target_text(target)
    scene = f"{note.rstrip('.')}. " if note else ""
    instead = fill or "only the plain background that was behind it, empty"
    return (
        f"{scene}In the marked area there is {instead}, nothing held, nothing "
        "placed, the surface continuous with its surroundings and consistent "
        "from frame to frame. Everything else in the picture is unchanged."
    )


def negative(target: str) -> str:
    return f"{target_text(target)}, {NEGATIVE}"


def node(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def graph(
    models: Recipe | None,
    stage: str,
    target: str,
    shape: str,
    seed: int = 42,
    note: str = "",
    expand: int = EXPAND,
    fill: str = "",
) -> dict:
    """The find graph, or the full removal when `stage` is "remove"."""
    if stage not in STAGES:
        raise ValueError("Choose the find or the remove stage.")
    if shape not in SIZES:
        raise ValueError("Choose portrait, landscape or square framing.")
    if not 0 <= expand <= 100:
        raise ValueError("Grow the mask by 0 to 100 pixels.")
    width, height = SIZES[shape]
    text = prompt(target, note, fill)
    nodes = {
        "source": node("LoadVideo", file="source.mp4"),
        "parts": node("GetVideoComponents", video=["source", 0]),
        "sam": node("CheckpointLoaderSimple", ckpt_name=SAM),
        "what": node("CLIPTextEncode", clip=["sam", 1], text=target_text(target)),
        "track": node(
            "SAM3_VideoTrack",
            images=["parts", 0],
            model=["sam", 0],
            conditioning=["what", 0],
            detection_threshold=0.35,
            max_objects=0,
            detect_interval=1,
        ),
        "mask": node("SAM3_TrackToMask", track_data=["track", 0], object_indices=""),
        "grown": node(
            "GrowMask", mask=["mask", 0], expand=expand, tapered_corners=True
        ),
        # The preview lights the region up over the picture.
        "mask-image": node("MaskToImage", mask=["grown", 0]),
        "preview": node(
            "ImageBlend",
            image1=["parts", 0],
            image2=["mask-image", 0],
            blend_factor=0.55,
            blend_mode="screen",
        ),
        "preview-video": node("CreateVideo", images=["preview", 0], fps=FPS),
        "save-mask": node(
            "SaveVideo",
            video=["preview-video", 0],
            filename_prefix="openfield/remove-mask",
            format="mp4",
            codec="h264",
        ),
    }
    if stage == "find":
        return nodes
    if models is None:
        raise ValueError("The remove stage needs the backend's model names.")
    if models.engine == "remover":
        nodes.update(remover_nodes(width, height, seed))
        return nodes
    nodes.update(
        {
            "model": node("UNETLoader", unet_name=models.unet, weight_dtype="default"),
            "shift": node("ModelSamplingSD3", model=["model", 0], shift=8.0),
            "clip": node(
                "CLIPLoader", clip_name=models.clip, type="wan", device="default"
            ),
            "vae": node("VAELoader", vae_name=VAE),
            "positive": node("CLIPTextEncode", clip=["clip", 0], text=text),
            "negative": node("CLIPTextEncode", clip=["clip", 0], text=negative(target)),
            # Control video: the picture with the region blacked out, as the
            # official inpainting template builds it.
            # Mid-grey, not black: a black hole read as a dark object and the
            # spoon came back on the first owned-GPU run (2026-10-28).
            "fill": node(
                "EmptyImage", width=width, height=height, batch_size=FRAMES, color=GREY
            ),
            "control": node(
                "ImageCompositeMasked",
                destination=["parts", 0],
                source=["fill", 0],
                x=0,
                y=0,
                resize_source=True,
                mask=["grown", 0],
            ),
            "vace": node(
                "WanVaceToVideo",
                positive=["positive", 0],
                negative=["negative", 0],
                vae=["vae", 0],
                width=width,
                height=height,
                length=FRAMES,
                batch_size=1,
                strength=1.0,
                control_video=["control", 0],
                control_masks=["grown", 0],
            ),
            "sample": node(
                "KSampler",
                model=["shift", 0],
                seed=seed,
                steps=20,
                cfg=6.0,
                sampler_name="uni_pc",
                scheduler="simple",
                positive=["vace", 0],
                negative=["vace", 1],
                latent_image=["vace", 2],
                denoise=1.0,
            ),
            "trim": node(
                "TrimVideoLatent", samples=["sample", 0], trim_amount=["vace", 3]
            ),
            "decode": node("VAEDecode", samples=["trim", 0], vae=["vae", 0]),
            "video": node("CreateVideo", images=["decode", 0], fps=FPS),
            "save": node(
                "SaveVideo",
                video=["video", 0],
                filename_prefix="openfield/remove",
                format="mp4",
                codec="h264",
            ),
        }
    )
    return nodes


def remover_nodes(width: int, height: int, seed: int) -> dict:
    """MiniMax-Remover through the WanVideoWrapper pack, as its pipeline does:
    the masked region zeroed in [-1, 1] (mid-grey), the mask encoded as a
    second latent, twelve UniPC steps, no text, no guidance."""
    tiles = {
        "enable_vae_tiling": False,
        "tile_x": 272,
        "tile_y": 272,
        "tile_stride_x": 144,
        "tile_stride_y": 128,
    }
    return {
        "fill": node(
            "EmptyImage", width=width, height=height, batch_size=FRAMES, color=GREY
        ),
        "control": node(
            "ImageCompositeMasked",
            destination=["parts", 0],
            source=["fill", 0],
            x=0,
            y=0,
            resize_source=True,
            mask=["grown", 0],
        ),
        "vae": node("WanVideoVAELoader", model_name=VAE, precision="bf16"),
        "latents": node(
            "WanVideoEncode", vae=["vae", 0], image=["control", 0], **tiles
        ),
        "mask-latents": node(
            "WanVideoEncode", vae=["vae", 0], image=["mask-image", 0], **tiles
        ),
        "embeds": node(
            REMOVER_NODE,
            width=width,
            height=height,
            num_frames=FRAMES,
            latents=["latents", 0],
            mask_latents=["mask-latents", 0],
        ),
        "model": node(
            "WanVideoModelLoader",
            model=REMOVER,
            base_precision="bf16",
            quantization="disabled",
            load_device="main_device",
            attention_mode="sdpa",
        ),
        "sample": node(
            "WanVideoSampler",
            model=["model", 0],
            image_embeds=["embeds", 0],
            steps=12,
            cfg=1.0,
            shift=5.0,
            seed=seed,
            force_offload=True,
            scheduler="unipc",
            riflex_freq_index=0,
        ),
        "decode": node(
            "WanVideoDecode", vae=["vae", 0], samples=["sample", 0], **tiles
        ),
        "video": node("CreateVideo", images=["decode", 0], fps=FPS),
        "save": node(
            "SaveVideo",
            video=["video", 0],
            filename_prefix="openfield/remove",
            format="mp4",
            codec="h264",
        ),
    }


def prepare(source: Path, run_dir: Path, shape: str) -> Path:
    """The window at VACE's size, centre-cropped, exactly 121 frames at 24 fps."""
    width, height = SIZES[shape]
    destination = run_dir / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(source),
            "-vf",
            (f"fps={FPS},scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,tpad=stop_mode=clone:stop_duration=1,"
            "format=yuv420p"),
            "-frames:v", str(FRAMES),
            "-c:v", "libx264", "-crf", "16", "-c:a", "aac", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(destination),
        ],
        check=True,
        timeout=300,
    )  # fmt: skip
    return destination


def finish(run_dir: Path, video: Path, stage: str) -> Path:
    """mask.mp4 for the find stage; removed.mp4 with the clip's sound for remove."""
    from .tools import compare

    if stage == "find":
        destination = run_dir / "mask.mp4"
        video.replace(destination)
        return destination
    destination = run_dir / "removed.mp4"
    partial = destination.with_suffix(".partial.mp4")
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(video), "-i", str(run_dir / "source.mp4"),
            "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-movflags", "+faststart", str(partial),
        ],
        check=True,
        timeout=300,
    )  # fmt: skip
    partial.replace(destination)
    compare(run_dir / "source.mp4", destination, run_dir / "compare.mp4", "wipe")
    return destination
