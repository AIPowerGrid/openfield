"""Source-guided MOSS opening looks, using the qualified native workflow."""

import math
import subprocess
from pathlib import Path

from .reshoot import node

SIZES = {"landscape": (1344, 768), "portrait": (720, 1280), "square": (1024, 1024)}


def graph(
    prompt: str,
    seed: int = 42,
    denoise: float = 0.65,
    *,
    frame_format: str = "landscape",
    from_image: bool = True,
) -> dict:
    if frame_format not in SIZES:
        raise ValueError("Choose portrait, square or landscape framing.")
    width, height = SIZES[frame_format]
    if not prompt.strip() or len(prompt) > 4000:
        raise ValueError("Describe the opening look in 1-4000 characters.")
    if not 0 <= seed <= 2**63 - 1:
        raise ValueError("Choose a non-negative seed below 2^63.")
    if not math.isfinite(denoise) or not 0 < denoise <= 1:
        raise ValueError("Look denoise must be greater than zero and at most one.")
    workflow = {
        "source": node("LoadImage", image="source.png"),
        "scale": node(
            "ImageScale",
            image=["source", 0],
            upscale_method="lanczos",
            width=width,
            height=height,
            crop="center",
        ),
        "model": node(
            "UNETLoader",
            unet_name="moss_image_sft_bf16.safetensors",
            weight_dtype="default",
        ),
        "clip": node(
            "CLIPLoader",
            clip_name="qwen3.5_9b_int8_convrot.safetensors",
            type="moss_image",
            device="default",
        ),
        "vae": node("VAELoader", vae_name="flux2-vae.safetensors"),
        "negative-skip": node(
            "SkipLayerGuidanceDiTSimple",
            model=["model", 0],
            double_layers="",
            single_layers="22",
            start_percent=0,
            end_percent=1,
        ),
        "positive": node("CLIPTextEncode", clip=["clip", 0], text=prompt),
        "negative": node(
            "CLIPTextEncode",
            clip=["clip", 0],
            text="worst quality, watermark, jpeg artifact, text, logos, people, distorted geometry",
        ),
        "encode": node("VAEEncode", pixels=["scale", 0], vae=["vae", 0]),
        "sample": node(
            "KSampler",
            model=["negative-skip", 0],
            seed=seed,
            steps=50,
            cfg=3,
            sampler_name="euler",
            scheduler="simple",
            denoise=denoise,
            positive=["positive", 0],
            negative=["negative", 0],
            latent_image=["encode", 0],
        ),
        "decode": node("VAEDecode", samples=["sample", 0], vae=["vae", 0]),
        "save": node(
            "SaveImage", images=["decode", 0], filename_prefix="openreshoot/look"
        ),
    }
    if not from_image:
        for key in ("source", "scale", "encode"):
            del workflow[key]
        workflow["empty"] = node(
            "EmptyFlux2LatentImage", width=width, height=height, batch_size=1
        )
        workflow["sample"]["inputs"].update(latent_image=["empty", 0], denoise=1.0)
    return workflow


def klein_graph(
    prompt: str,
    seed: int = 42,
    *,
    from_image: bool = True,
    frame_format: str = "landscape",
    unet_name: str = "flux-2-klein-4b-fp8.safetensors",
    style_image: bool | int = False,
) -> dict:
    """Four-step reference-conditioned editing, not latent-blend img2img.

    Comfy Cloud serves the FP8 file; the owned image worker has the BF16 one.
    """
    if not prompt.strip() or len(prompt) > 4000:
        raise ValueError("Describe the look in 1-4000 characters.")
    if not 0 <= seed <= 2**63 - 1:
        raise ValueError("Choose a non-negative seed below 2^63.")
    if frame_format not in SIZES:
        raise ValueError("Choose portrait, square or landscape framing.")
    workflow = {
        "source": node("LoadImage", image="source.png"),
        "model": node(
            "UNETLoader",
            unet_name=unet_name,
            weight_dtype="default",
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
        "encode": node("VAEEncode", pixels=["source", 0], vae=["vae", 0]),
        "ref-positive": node(
            "ReferenceLatent", conditioning=["positive", 0], latent=["encode", 0]
        ),
        "ref-negative": node(
            "ReferenceLatent", conditioning=["negative", 0], latent=["encode", 0]
        ),
        "size": node("GetImageSize", image=["source", 0]),
        "empty": node(
            "EmptyFlux2LatentImage",
            width=["size", 0],
            height=["size", 1],
            batch_size=1,
        ),
        "schedule": node(
            "Flux2Scheduler", steps=4, width=["size", 0], height=["size", 1]
        ),
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
            "SaveImage", images=["decode", 0], filename_prefix="openreshoot/look"
        ),
    }
    references = int(style_image) if isinstance(style_image, bool) else style_image
    if references:
        if not from_image:
            raise ValueError("Reference images edit a source frame.")
        if references > 3:
            raise ValueError("Use at most three reference images.")
        # Extra reference latents carry a style picture or the objects to add.
        positive, negative = "ref-positive", "ref-negative"
        for index in range(references):
            name = "style" if index == 0 else f"style-{index + 1}"
            workflow |= {
                name: node("LoadImage", image=f"{name}.png"),
                f"{name}-encode": node("VAEEncode", pixels=[name, 0], vae=["vae", 0]),
                f"{name}-positive": node(
                    "ReferenceLatent",
                    conditioning=[positive, 0],
                    latent=[f"{name}-encode", 0],
                ),
                f"{name}-negative": node(
                    "ReferenceLatent",
                    conditioning=[negative, 0],
                    latent=[f"{name}-encode", 0],
                ),
            }
            positive, negative = f"{name}-positive", f"{name}-negative"
        workflow["guider"]["inputs"].update(
            positive=[positive, 0], negative=[negative, 0]
        )
    if not from_image:
        for key in ("source", "encode", "ref-positive", "ref-negative", "size"):
            del workflow[key]
        width, height = SIZES[frame_format]
        workflow["empty"]["inputs"].update(width=width, height=height)
        workflow["schedule"]["inputs"].update(width=width, height=height)
        workflow["guider"]["inputs"].update(
            positive=["positive", 0], negative=["negative", 0]
        )
    return workflow


def source_frame(source: Path, run_dir: Path, frame_index: int = 0) -> Path:
    if frame_index not in (0, 120, 240, 360):
        raise ValueError(
            "Choose the opening frame or the last frame of a 5, 10 or 15 s take."
        )
    destination = run_dir / "source.png"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(source),
            "-vf",
            f"select=eq(n\\,{frame_index})",
            "-frames:v",
            "1",
            str(destination),
        ],
        check=True,
    )
    return destination
