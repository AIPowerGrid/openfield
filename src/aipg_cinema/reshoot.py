"""Bounded five-second motion-preservation experiment for OpenReshoot."""

import json
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps


@dataclass(frozen=True)
class VideoFormat:
    width: int
    height: int

    @property
    def output_size(self) -> tuple[int, int]:
        return self.width * 2, self.height * 2


FORMATS = {
    "landscape": VideoFormat(768, 448),
    "portrait": VideoFormat(576, 1024),
    "square": VideoFormat(640, 640),
}


def video_format(name: str) -> VideoFormat:
    try:
        return FORMATS[name]
    except KeyError as error:
        raise ValueError("Choose portrait, square or landscape framing.") from error


def node(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


# LTX latents need 8k+1 frames: 5, 10 and 15 s at 24 fps are 121, 241, 361.
SECONDS = (5, 10, 15)


def frames_for(seconds: int) -> int:
    return seconds * 24 + 1


def graph(
    model: str,
    prompt: str,
    seed: int = 42,
    *,
    motion_strength: float = 1.0,
    look_frame: bool = False,
    closing_frame: bool = False,
    frame_format: str = "landscape",
    seconds: int = 5,
) -> dict:
    video_format(frame_format)
    if seconds not in SECONDS:
        raise ValueError("Choose a 5, 10 or 15 second reshoot.")
    if seconds != 5 and model != "ltx25":
        raise ValueError("Longer reshoots require ltx25.")
    if frame_format != "landscape" and model != "ltx25":
        raise ValueError("Portrait and square execution require ltx25.")
    if not prompt.strip():
        raise ValueError("Describe the reshoot before rendering.")
    if not math.isfinite(motion_strength) or not 0 <= motion_strength <= 1:
        raise ValueError("Motion strength must be between zero and one.")
    if model != "ltx25" and motion_strength != 1.0:
        raise ValueError("Motion strength requires ltx25.")
    if model not in ("ltx25", "fasth3") and look_frame:
        raise ValueError("Look frames require ltx25 or fasth3.")
    if closing_frame and (model != "ltx25" or not look_frame):
        raise ValueError("Closing frames require ltx25 and an opening look frame.")
    common = {
        "source": node("LoadVideo", file="source.mp4"),
        "frames": node("GetVideoComponents", video=["source", 0]),
        "video": node("CreateVideo", images=["decode", 0], fps=24, bit_depth=8),
        "save": node(
            "SaveVideo",
            video=["video", 0],
            filename_prefix="openreshoot/experiment",
            format="auto",
            **{"format.codec": "auto"},
            codec="auto",
        ),
    }
    if model in ("h3", "fasth3"):
        workflow = common | {
            "model": node(
                "UNETLoader",
                unet_name="minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                weight_dtype="default",
            ),
            "clip": node(
                "CLIPLoader",
                clip_name="qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                type="minimax",
                device="default",
            ),
            "vae": node(
                "VAELoader", vae_name="minimax_h3_video_vae_int8_convrot.safetensors"
            ),
            "audio-vae": node(
                "VAELoader", vae_name="minimax_h3_audio_vae_fp32.safetensors"
            ),
            "reference": node(
                "MiniMaxH3ReferenceToVideo",
                clip=["clip", 0],
                vae=["vae", 0],
                audio_vae=["audio-vae", 0],
                prompt=prompt
                + " Use <Video 1> as the exact motion, camera and timing reference. Keep its action in one continuous shot.",
                width=768,
                height=448,
                length=124,
                ref_image_size="match",
                **{"ref_videos.ref_video_0": ["frames", 0]},
            ),
            "noise": node("RandomNoise", noise_seed=seed),
            "sampler": node("KSamplerSelect", sampler_name="res_multistep"),
            "schedule": node(
                "BasicScheduler",
                model=["model", 0],
                scheduler="beta",
                steps=20,
                denoise=1,
            ),
            "guider": node(
                "BasicGuider", model=["model", 0], conditioning=["reference", 0]
            ),
            "sample": node(
                "SamplerCustomAdvanced",
                noise=["noise", 0],
                guider=["guider", 0],
                sampler=["sampler", 0],
                sigmas=["schedule", 0],
                latent_image=["reference", 1],
            ),
            "decode": node("VAEDecode", samples=["sample", 0], vae=["vae", 0]),
        }
        if model == "fasth3":
            workflow["model"]["inputs"]["unet_name"] = (
                "fasth3_omniref_qad_nvfp4_comfy.safetensors"
            )
            workflow["vae"]["inputs"]["vae_name"] = (
                "minimax_h3_video_vae_fp16.safetensors"
            )
            workflow["reference"]["inputs"].update(width=1536, height=896)
            workflow["shift"] = node(
                "MiniMaxH3SigmaShift",
                model=["model", 0],
                shift_video=12.0,
                shift_audio=3.0,
            )
            workflow["schedule"]["inputs"].update(
                model=["shift", 0], scheduler="simple", steps=8
            )
            workflow["guider"]["inputs"]["model"] = ["shift", 0]
            if look_frame:
                workflow["look"] = node("LoadImage", image="look.png")
                workflow["reference"]["inputs"].update(
                    {
                        "ref_images.ref_image_0": ["look", 0],
                        "prompt": prompt
                        + " Use <Picture 1> as the target appearance, materials, setting and lighting."
                        + " Use <Video 1> only for motion, camera framing and timing."
                        + " Apply the look from <Picture 1> throughout the entire shot,"
                        + " while following the action from <Video 1>. One continuous shot.",
                    }
                )
        return workflow
    if model == "ltx25":
        return common | ltx25_graph(
            prompt,
            seed,
            motion_strength,
            look_frame,
            closing_frame,
            frame_format,
            seconds,
        )
    if model != "ltx":
        raise ValueError("Choose h3, fasth3, ltx or ltx25.")
    checkpoint = "ltx-2.3-22b-distilled-fp8.safetensors"
    return common | {
        "checkpoint": node("CheckpointLoaderSimple", ckpt_name=checkpoint),
        "clip": node(
            "LTXAVTextEncoderLoader",
            text_encoder="gemma_3_12B_it_fp4_mixed.safetensors",
            ckpt_name=checkpoint,
            device="default",
        ),
        "audio-vae": node("LTXVAudioVAELoader", ckpt_name=checkpoint),
        "model": node(
            "LoraLoaderModelOnly",
            model=["checkpoint", 0],
            lora_name="ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors",
            strength_model=1,
        ),
        "parameters": node("GetICLoRAParameters", iclora_model=["model", 0]),
        "positive": node("CLIPTextEncode", clip=["clip", 0], text=prompt),
        "negative": node(
            "CLIPTextEncode",
            clip=["clip", 0],
            text="flicker, cuts, disappearing objects, distorted geometry, text, logos, people",
        ),
        "condition": node(
            "LTXVConditioning",
            positive=["positive", 0],
            negative=["negative", 0],
            frame_rate=24,
        ),
        "edges": node(
            "Canny", image=["frames", 0], low_threshold=0.1, high_threshold=0.2
        ),
        "empty": node(
            "EmptyLTXVLatentVideo", width=768, height=448, length=121, batch_size=1
        ),
        "guide": node(
            "LTXVAddGuide",
            positive=["condition", 0],
            negative=["condition", 1],
            vae=["checkpoint", 2],
            latent=["empty", 0],
            image=["edges", 0],
            frame_idx=0,
            strength=1,
            iclora_parameters=["parameters", 0],
        ),
        "empty-audio": node(
            "LTXVEmptyLatentAudio",
            audio_vae=["audio-vae", 0],
            frames_number=121,
            frame_rate=24,
            batch_size=1,
        ),
        "av": node(
            "LTXVConcatAVLatent",
            video_latent=["guide", 2],
            audio_latent=["empty-audio", 0],
        ),
        "sample": node(
            "KSampler",
            model=["model", 0],
            seed=seed,
            steps=8,
            cfg=1,
            sampler_name="euler_ancestral",
            scheduler="linear_quadratic",
            positive=["guide", 0],
            negative=["guide", 1],
            latent_image=["av", 0],
            denoise=1,
        ),
        "separate": node("LTXVSeparateAVLatent", av_latent=["sample", 0]),
        "crop": node(
            "LTXVCropGuides",
            positive=["guide", 0],
            negative=["guide", 1],
            latent=["separate", 0],
        ),
        "decode": node(
            "VAEDecodeTiled",
            samples=["crop", 2],
            vae=["checkpoint", 2],
            tile_size=512,
            overlap=64,
            temporal_size=64,
            temporal_overlap=16,
        ),
    }


def ltx25_graph(
    prompt: str,
    seed: int,
    motion_strength: float,
    look_frame: bool,
    closing_frame: bool = False,
    frame_format: str = "landscape",
    seconds: int = 5,
) -> dict:
    """Two-stage 2.5 Union Control with an optional composition-matched anchor."""
    spec = video_format(frame_format)
    frames = frames_for(seconds)
    workflow = {
        "backbone": node(
            "UNETLoader",
            unet_name="ltx-2.5-22b-distilled-transformer-bf16.safetensors",
            weight_dtype="default",
        ),
        "clip": node(
            "CLIPLoader",
            clip_name="gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
            type="ltxv",
            device="default",
        ),
        "vae": node("VAELoader", vae_name="ltx-2.5-video-vae-bf16.safetensors"),
        "audio-vae": node("VAELoader", vae_name="ltx-2.5-audio-vae-bf16.safetensors"),
        "model": node(
            "LTXICLoRALoaderModelOnly",
            model=["backbone", 0],
            lora_name="ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors",
            strength_model=1,
        ),
        "positive": node("CLIPTextEncode", clip=["clip", 0], text=prompt),
        "negative": node("CLIPTextEncode", clip=["clip", 0], text=""),
        "condition": node(
            "LTXVConditioning",
            positive=["positive", 0],
            negative=["negative", 0],
            frame_rate=24,
        ),
        "source-window": node(
            "ImageFromBatch", image=["frames", 0], batch_index=0, length=frames
        ),
        "edges": node(
            "Canny", image=["source-window", 0], low_threshold=0.1, high_threshold=0.2
        ),
        "empty": node(
            "EmptyLTXVLatentVideo",
            width=spec.width,
            height=spec.height,
            length=frames,
            batch_size=1,
        ),
        "guide": node(
            "LTXAddVideoICLoRAGuide",
            positive=["condition", 0],
            negative=["condition", 1],
            vae=["vae", 0],
            latent=["empty", 0],
            image=["edges", 0],
            frame_idx=0,
            strength=motion_strength,
            latent_downscale_factor=["model", 1],
            crop="disabled",
            use_tiled_encode=False,
            tile_size=256,
            tile_overlap=64,
        ),
        "empty-audio": node(
            "LTXVEmptyLatentAudio",
            audio_vae=["audio-vae", 0],
            frames_number=frames,
            frame_rate=24,
            batch_size=1,
        ),
        "av": node(
            "LTXVConcatAVLatent",
            video_latent=["guide", 2],
            audio_latent=["empty-audio", 0],
        ),
        "noise": node("RandomNoise", noise_seed=seed),
        "sampler": node("KSamplerSelect", sampler_name="euler_ancestral"),
        "sigmas": node(
            "ManualSigmas",
            sigmas="1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0",
        ),
        "guider": node(
            "CFGGuider",
            model=["model", 0],
            positive=["guide", 0],
            negative=["guide", 1],
            cfg=1,
        ),
        "sample": node(
            "SamplerCustomAdvanced",
            noise=["noise", 0],
            guider=["guider", 0],
            sampler=["sampler", 0],
            sigmas=["sigmas", 0],
            latent_image=["av", 0],
        ),
        "separate": node("LTXVSeparateAVLatent", av_latent=["sample", 0]),
        "crop": node(
            "LTXVCropGuides",
            positive=["guide", 0],
            negative=["guide", 1],
            latent=["separate", 0],
        ),
        "upscale-model": node(
            "LatentUpscaleModelLoader",
            model_name="ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
        ),
        "upscale": node(
            "LTXVLatentUpsampler",
            samples=["crop", 2],
            upscale_model=["upscale-model", 0],
            vae=["vae", 0],
        ),
        "refine-av": node(
            "LTXVConcatAVLatent",
            video_latent=["upscale", 0],
            audio_latent=["separate", 1],
        ),
        "refine-sigmas": node("ManualSigmas", sigmas="0.909375, 0.725, 0.421875, 0.0"),
        "refine-guider": node(
            "CFGGuider",
            model=["model", 0],
            positive=["crop", 0],
            negative=["crop", 1],
            cfg=1,
        ),
        "refine": node(
            "SamplerCustomAdvanced",
            noise=["noise", 0],
            guider=["refine-guider", 0],
            sampler=["sampler", 0],
            sigmas=["refine-sigmas", 0],
            latent_image=["refine-av", 0],
        ),
        "refine-separate": node("LTXVSeparateAVLatent", av_latent=["refine", 0]),
        "decode": node(
            "VAEDecodeTiled",
            samples=["refine-separate", 0],
            vae=["vae", 0],
            tile_size=512,
            overlap=64,
            temporal_size=128,
            temporal_overlap=32,
        ),
    }
    if look_frame:
        workflow.update(
            {
                "look": node("LoadImage", image="look.png"),
                "look-anchor": node(
                    "LTXVImgToVideoInplace",
                    vae=["vae", 0],
                    image=["look", 0],
                    latent=["empty", 0],
                    strength=1.0,
                    bypass=False,
                ),
                "refine-look-anchor": node(
                    "LTXVImgToVideoInplace",
                    vae=["vae", 0],
                    image=["look", 0],
                    latent=["upscale", 0],
                    strength=1.0,
                    bypass=False,
                ),
            }
        )
        workflow["guide"]["inputs"]["latent"] = ["look-anchor", 0]
        workflow["refine-av"]["inputs"]["video_latent"] = ["refine-look-anchor", 0]
    if closing_frame:
        workflow.update(
            {
                "closing": node("LoadImage", image="closing.png"),
                "closing-guide": node(
                    "LTXVAddGuide",
                    positive=["guide", 0],
                    negative=["guide", 1],
                    vae=["vae", 0],
                    latent=["guide", 2],
                    image=["closing", 0],
                    frame_idx=frames - 1,
                    strength=0.7,
                ),
                "refine-closing-guide": node(
                    "LTXVAddGuide",
                    positive=["crop", 0],
                    negative=["crop", 1],
                    vae=["vae", 0],
                    latent=["refine-look-anchor", 0],
                    image=["closing", 0],
                    frame_idx=frames - 1,
                    strength=0.7,
                ),
                "refine-crop": node(
                    "LTXVCropGuides",
                    positive=["refine-closing-guide", 0],
                    negative=["refine-closing-guide", 1],
                    latent=["refine-separate", 0],
                ),
            }
        )
        workflow["av"]["inputs"]["video_latent"] = ["closing-guide", 2]
        for target in ("guider", "crop"):
            workflow[target]["inputs"].update(
                positive=["closing-guide", 0], negative=["closing-guide", 1]
            )
        workflow["refine-av"]["inputs"]["video_latent"] = ["refine-closing-guide", 2]
        workflow["refine-guider"]["inputs"].update(
            positive=["refine-closing-guide", 0],
            negative=["refine-closing-guide", 1],
        )
        workflow["decode"]["inputs"]["samples"] = ["refine-crop", 2]
    return workflow


# A look frame is scaled to the take; anything smaller than this is a thumbnail.
MIN_LOOK_SIDE = 256


def prepare_look(
    source: Path,
    run_dir: Path,
    *,
    closing: bool = False,
    frame_format: str = "landscape",
) -> Path:
    width, height = video_format(frame_format).output_size
    if source.stat().st_size > 12 * 1024 * 1024:
        raise ValueError("Choose a look frame smaller than 12 MB.")
    try:
        image = Image.open(source)
    except Image.DecompressionBombError as error:
        raise ValueError("Choose a look frame no larger than 16 megapixels.") from error
    with image:
        if image.format not in ("PNG", "JPEG", "WEBP"):
            raise ValueError("Choose a PNG, JPEG or WebP look frame.")
        if image.width * image.height > 16_000_000:
            raise ValueError("Choose a look frame no larger than 16 megapixels.")
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Choose a still image, not an animation.")
        if min(image.width, image.height) < MIN_LOOK_SIDE:
            raise ValueError(
                f"Choose a photo at least {MIN_LOOK_SIDE} pixels wide and tall."
            )
        normalized = ImageOps.contain(
            ImageOps.exif_transpose(image).convert("RGB"), (width, height)
        )
        canvas = Image.new("RGB", (width, height))
        canvas.paste(
            normalized,
            ((width - normalized.width) // 2, (height - normalized.height) // 2),
        )
        destination = run_dir / ("closing.png" if closing else "look.png")
        partial = destination.with_suffix(".partial.png")
        canvas.save(partial)
        partial.replace(destination)
    return destination


def video_input(path: Path) -> list[str]:
    path = path.resolve(strict=True)
    with path.open("rb") as source:
        header = source.read(12)
    # Select only a standalone container; FFmpeg still validates its contents.
    if header[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip"):
        fmt = "mov"
    elif header.startswith(b"\x1aE\xdf\xa3"):
        fmt = "matroska"
    elif header.startswith(b"OggS"):
        fmt = "ogg"
    else:
        raise ValueError(
            "Choose an MP4, MOV, WebM, MKV or Ogg video file, not a playlist."
        )
    args = ["-protocol_whitelist", "file", "-max_streams", "16", "-f", fmt]
    if fmt == "mov":
        args += ["-enable_drefs", "0", "-use_absolute_path", "0"]
    return [*args, "-i", str(path)]


def probe(path: Path) -> dict:
    with tempfile.TemporaryFile() as output:
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-max_alloc",
                "67108864",
                *video_input(path),
                "-show_streams",
                "-show_format",
                "-of",
                "json",
            ],
            stdout=output,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=True,
            env={"PATH": os.environ.get("PATH", os.defpath)},
        )
        output.seek(0)
        data = output.read(65537)
    if len(data) > 65536:
        raise ValueError("Video metadata exceeds the inspection limit.")
    return json.loads(data)


def prepare_source(
    source: Path,
    run_dir: Path,
    *,
    frame_format: str = "landscape",
    source_start: float = 0,
    seconds: int = 5,
) -> Path:
    spec = video_format(frame_format)
    if not math.isfinite(source_start) or source_start < 0:
        raise ValueError("Choose a non-negative source start time.")
    if seconds not in SECONDS:
        raise ValueError("Choose a 5, 10 or 15 second reshoot.")
    words = {5: "five", 10: "ten", 15: "fifteen"}[seconds]
    info = probe(source)
    if float(info["format"]["duration"]) < seconds:
        raise ValueError(
            f"This reshoot needs at least {words} seconds of source video."
        )
    if not any(stream["codec_type"] == "video" for stream in info["streams"]):
        raise ValueError("The source has no video stream.")
    if source_start + seconds > float(info["format"]["duration"]) + 0.001:
        raise ValueError(
            f"Choose a start time leaving {words} seconds of source video."
        )
    destination = run_dir / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-max_alloc",
            "67108864",
            *video_input(source),
            "-ss",
            str(source_start),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            (
                f"fps=24,scale={spec.width}:{spec.height}:force_original_aspect_ratio=decrease,"
                f"pad={spec.width}:{spec.height}:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1,tpad=stop_mode=clone:stop_duration=0.2"
            ),
            "-t",
            str((frames_for(seconds) + 3) / 24),
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        check=True,
        timeout=120,
        stderr=subprocess.DEVNULL,
        env={"PATH": os.environ.get("PATH", os.defpath)},
    )
    return destination


def finish(run_dir: Path, generated: Path, seconds: int = 5) -> Path:
    source = run_dir / "source.mp4"
    destination = run_dir / "reshoot.mp4"
    temporary = run_dir / "reshoot.partial.mp4"
    # Keep the source soundtrack, but trim decoded samples rather than AAC packets.
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-nostdin",
            "-max_alloc",
            "67108864",
            *video_input(generated),
            *video_input(source),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0?",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-vf",
            f"trim=end_frame={seconds * 24},setpts=PTS-STARTPTS",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-af",
            (
                f"aresample=48000,apad=whole_len={seconds * 48000},"
                f"atrim=end_sample={seconds * 48000},asetpts=PTS-STARTPTS"
            ),
            "-t",
            str(seconds),
            "-metadata",
            "title=OpenReshoot - AI-generated video",
            "-metadata",
            "description=AI-generated video by OpenReshoot. Source audio retained when present.",
            "-movflags",
            "+faststart",
            "-movie_timescale",
            "48000",
            "-video_track_timescale",
            "24000",
            str(temporary),
        ],
        check=True,
        timeout=120,
        stderr=subprocess.DEVNULL,
        env={"PATH": os.environ.get("PATH", os.defpath)},
    )
    temporary.replace(destination)
    return destination
