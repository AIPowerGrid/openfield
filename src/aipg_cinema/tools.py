# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Single-purpose video tools built on ComfyUI nodes, plus local reframe.

FPS boost (RIFE v4.26), background removal (BiRefNet) and upscale
(RealESRGAN x2) are plain core-node graphs: the same graph runs on Comfy Cloud
or on an owned ComfyUI that has the model files below. Depth map uses the
widely installed comfyui_controlnet_aux node. Reframe is a local
ffmpeg step and never contacts a GPU. Inputs are normalized to 24 fps and at
most fifteen seconds before anything is sent.
"""

import json
import subprocess
from pathlib import Path

from .reshoot import probe

MAX_SECONDS = 15
# Model files the graphs load, by ComfyUI models folder.
MODELS = {
    "fps-boost": ("frame_interpolation", "rife_v4.26.safetensors"),
    "remove-background": ("background_removal", "birefnet.safetensors"),
    "upscale": ("upscale_models", "RealESRGAN_x2plus.pth"),
    # Depth Anything V2 Small (Apache-2.0; the larger checkpoints are
    # non-commercial) through comfyui_controlnet_aux, not a core node.
    "depth-map": ("custom_nodes/comfyui_controlnet_aux", "depth_anything_v2_vits.pth"),
    "lipdub": ("loras", "ltx-2.3-22b-ic-lora-lipdub-0.9.safetensors"),
}
# Loader node and input for each model, used to check a worker has it.
LOADERS = {
    "fps-boost": ("FrameInterpolationModelLoader", "model_name"),
    "remove-background": ("LoadBackgroundRemovalModel", "bg_removal_name"),
    "upscale": ("UpscaleModelLoader", "model_name"),
    "depth-map": ("DepthAnythingV2Preprocessor", "ckpt_name"),
    "lipdub": ("LTXICLoRALoaderModelOnly", "lora_name"),
}
BACKGROUNDS = {"green": 0x00B140, "black": 0x000000, "white": 0xFFFFFF}
# Longest input edge before a tool runs: bounds GPU time and upscale size.
MAX_EDGE = {
    "fps-boost": 1536,
    "remove-background": 1536,
    "upscale": 960,
    "depth-map": 1280,
    "lipdub": 1920,
}
# Lip-dub was trained on five-second clips; ten is the most it is offered.
# 241 frames at 24 fps is LTX's 8k+1 grid for ten seconds.
SECONDS = {"lipdub": 241 / 24}


def node(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def save(images: list, audio: list, fps: float) -> dict:
    return {
        "video": node("CreateVideo", images=images, audio=audio, fps=fps, bit_depth=8),
        "save": node(
            "SaveVideo",
            video=["video", 0],
            filename_prefix="openfield/tool",
            format="auto",
            **{"format.codec": "auto"},
        ),
    }


def graph(tool: str, *, background: str = "green") -> dict:
    """The core-node workflow for a tool; "source" loads the prepared clip."""
    workflow = {
        "source": node("LoadVideo", file="source.mp4"),
        "frames": node("GetVideoComponents", video=["source", 0]),
    }
    if tool == "fps-boost":
        model = MODELS[tool][1]
        workflow |= {
            "interp-model": node("FrameInterpolationModelLoader", model_name=model),
            "interpolate": node(
                "FrameInterpolate",
                interp_model=["interp-model", 0],
                images=["frames", 0],
                multiplier=2,
            ),
            **save(["interpolate", 0], ["frames", 1], 48),
        }
    elif tool == "remove-background":
        if background not in (*BACKGROUNDS, "matte"):
            raise ValueError("Choose a green, black or white background, or matte.")
        model = MODELS[tool][1]
        workflow |= {
            "bg-model": node("LoadBackgroundRemovalModel", bg_removal_name=model),
            "mask": node(
                "RemoveBackground",
                bg_removal_model=["bg-model", 0],
                image=["frames", 0],
            ),
        }
        if background == "matte":
            workflow |= {
                "matte": node("MaskToImage", mask=["mask", 0]),
                **save(["matte", 0], ["frames", 1], 24),
            }
        else:
            workflow |= {
                "size": node("GetImageSize", image=["frames", 0]),
                "plate": node(
                    "EmptyImage",
                    width=["size", 0],
                    height=["size", 1],
                    batch_size=["size", 2],
                    color=BACKGROUNDS[background],
                ),
                "composite": node(
                    "ImageCompositeMasked",
                    destination=["plate", 0],
                    source=["frames", 0],
                    x=0,
                    y=0,
                    resize_source=False,
                    mask=["mask", 0],
                ),
                **save(["composite", 0], ["frames", 1], 24),
            }
    elif tool == "upscale":
        model = MODELS[tool][1]
        workflow |= {
            "upscale-model": node("UpscaleModelLoader", model_name=model),
            "upscaled": node(
                "ImageUpscaleWithModel",
                upscale_model=["upscale-model", 0],
                image=["frames", 0],
            ),
            **save(["upscaled", 0], ["frames", 1], 24),
        }
    elif tool == "depth-map":
        workflow |= {
            "depth": node(
                "DepthAnythingV2Preprocessor",
                image=["frames", 0],
                ckpt_name=MODELS[tool][1],
                resolution=768,
            ),
            # The depth pass comes back at its own size (odd widths break
            # H.264); match the prepared source, which has even dimensions.
            "size": node("GetImageSize", image=["frames", 0]),
            "fit": node(
                "ImageScale",
                image=["depth", 0],
                upscale_method="bilinear",
                width=["size", 0],
                height=["size", 1],
                crop="disabled",
            ),
            **save(["fit", 0], ["frames", 1], 24),
        }
    else:
        raise ValueError("Unknown tool.")
    return workflow


def prepare(source: Path, run_dir: Path, tool: str) -> Path:
    """Normalize to 24 fps, at most 15 s, even dimensions within the tool's edge."""
    info = probe(source)
    if not any(s["codec_type"] == "video" for s in info["streams"]):
        raise ValueError("The source has no video stream.")
    edge = MAX_EDGE.get(tool, 1536)
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    if tool == "lipdub" and not has_audio:
        raise ValueError("This clip has no sound; the new line keeps the voice.")
    destination = run_dir / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-t", str(SECONDS.get(tool, MAX_SECONDS)),
            "-vf",
            (
                f"fps=24,scale='min({edge},iw)':'min({edge},ih)'"
                ":force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2,"
                "setsar=1,format=yuv420p"
            ),
            *(["-c:a", "aac", "-ar", "48000", "-ac", "2"] if has_audio else ["-an"]),
            "-c:v", "libx264", "-crf", "16", "-movflags", "+faststart",
            str(destination),
        ],
        check=True,
        timeout=300,
    )  # fmt: skip
    return destination


REFRAMES = {"portrait": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}


def reframe(source: Path, run_dir: Path, target: str, fit: str = "blur") -> Path:
    """Local reframe: the whole picture over a blurred fill, or a centre crop."""
    if target not in REFRAMES:
        raise ValueError("Choose portrait, landscape or square.")
    if fit not in ("blur", "crop"):
        raise ValueError("Choose a blurred fill or a centre crop.")
    width, height = REFRAMES[target]
    has_audio = any(s["codec_type"] == "audio" for s in probe(source)["streams"])
    picture = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
        if fit == "crop"
        else f"split[a][b];[a]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur=24:3,eq=brightness=-0.08[bg];"
        f"[b]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
    )
    destination = run_dir / "tool.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-t", "60",
            "-filter_complex", f"[0:v]fps=24,{picture},format=yuv420p[v]",
            "-map", "[v]", *(["-map", "0:a:0", "-c:a", "aac"] if has_audio else []),
            "-c:v", "libx264", "-crf", "18", "-movflags", "+faststart",
            str(destination),
        ],
        check=True,
        timeout=600,
    )  # fmt: skip
    (run_dir / "job.json").write_text(
        json.dumps(
            {
                "tool": "reframe",
                "status": "succeeded",
                "target": target,
                "fit": fit,
                "outputs": [destination.name],
                "tool_output": destination.name,
            },
            indent=2,
        )
        + "\n"
    )
    return destination


def last_frame(video: Path, destination: Path) -> Path:
    """The final picture of a take, as the opening frame of its continuation."""
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-sseof", "-0.2", "-i", str(video), "-update", "1", "-q:v", "1",
            str(destination),
        ],
        check=True,
        timeout=120,
    )  # fmt: skip
    if not destination.is_file():
        raise ValueError("The take's last frame could not be read.")
    return destination


def join(first: Path, continuation: Path, destination: Path) -> Path:
    """The take, then its continuation minus the repeated opening frame.

    A side without sound (a silent source clip) gets silence of its length.
    """
    sound = []
    for index, path in enumerate((first, continuation)):
        info = probe(path)
        trim = ",atrim=start=0.0417,asetpts=PTS-STARTPTS" if index else ""
        if any(s["codec_type"] == "audio" for s in info["streams"]):
            sound.append(
                f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo{trim}"
            )
        else:
            length = float(info["format"]["duration"]) - (0.0417 if index else 0)
            sound.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={length:.4f}")
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(first), "-i", str(continuation),
            "-filter_complex",
            (
                "[0:v]fps=24,setsar=1,format=yuv420p[a];"
                "[1:v]fps=24,trim=start_frame=1,setpts=PTS-STARTPTS,setsar=1,"
                f"format=yuv420p[b];{sound[0]}[x];{sound[1]}[y];"
                "[a][x][b][y]concat=n=2:v=1:a=1[v][s]"
            ),
            "-map", "[v]", "-map", "[s]",
            "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(destination),
        ],
        check=True,
        timeout=600,
    )  # fmt: skip
    return destination


FONT = Path(__file__).with_name("fonts") / "NotoSans.ttf"


def compare(source: Path, result: Path, destination: Path, layout: str) -> Path:
    """A shareable before/after: split screen, or the original wiping into the take.

    Both pictures share one timeline and the take's sound; labels and a small
    Openfield mark are drawn locally. Nothing is sent anywhere.
    """
    if layout not in ("split", "wipe"):
        raise ValueError("Choose a split or wipe comparison.")
    info = probe(result)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    width, height = int(video["width"]), int(video["height"])
    length = float(info["format"]["duration"])
    if length < 2.5:
        raise ValueError("A comparison needs a take of at least 2.5 seconds.")
    size = max(18, height // 30)
    pad = size // 2

    def chip(text: str, x: str, colour: str, ink: str, enable: str = "1") -> str:
        return (
            f"drawtext=fontfile={FONT}:text={text}:fontsize={size}:fontcolor={ink}"
            f":box=1:boxcolor={colour}:boxborderw={pad}:x={x}:y={pad * 3}"
            f":enable='{enable}'"
        )

    mark = (
        f"drawtext=fontfile={FONT}:text=Made with Openfield:fontsize={int(size * 0.8)}"
        f":fontcolor=white@0.75:x=w-tw-{pad * 3}:y=h-th-{pad * 3}"
    )
    before = chip("ORIGINAL", f"{pad * 3}", "black@0.6", "white")
    if layout == "split":
        half = width // 2
        picture = (
            f"[0:v]scale={width}:{height},setsar=1,fps=24,trim=duration={length},"
            f"crop={half}:{height}:0:0[l];"
            f"[1:v]setsar=1,fps=24,crop={width - half}:{height}:{half}:0[r];"
            f"[l][r]hstack,drawbox=x={half - 1}:y=0:w=3:h={height}:color=white@0.9:t=fill,"
            f"{before},{chip('OPENFIELD', f'w-tw-{pad * 3}', '0xff9900', '0x1a0f00')},"
            f"{mark},format=yuv420p[v]"
        )
    else:
        # Original for 1.2 s, a 0.8 s wipe, then the take, all on one clock.
        picture = (
            f"[0:v]scale={width}:{height},setsar=1,fps=24,trim=duration=2,"
            "setpts=PTS-STARTPTS[o];"
            "[1:v]setsar=1,fps=24,trim=start=1.2,setpts=PTS-STARTPTS[t];"
            "[o][t]xfade=transition=wiperight:duration=0.8:offset=1.2,"
            f"{chip('ORIGINAL', f'{pad * 3}', 'black@0.6', 'white', 'lt(t,1.6)')},"
            f"{chip('OPENFIELD', f'{pad * 3}', '0xff9900', '0x1a0f00', 'gte(t,1.6)')},"
            f"{mark},format=yuv420p[v]"
        )
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-i", str(result),
            "-filter_complex", picture, "-map", "[v]",
            *(["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"] if has_audio else []),
            "-t", f"{length:.3f}",
            "-c:v", "libx264", "-crf", "18", "-movflags", "+faststart",
            str(destination),
        ],
        check=True,
        timeout=600,
    )  # fmt: skip
    return destination
