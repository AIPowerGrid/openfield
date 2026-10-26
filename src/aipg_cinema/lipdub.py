# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Change what they say: new words, same person, matching lips.

This follows Lightricks' published DubIt recipe (LTX-2.3 IC-LoRA DubIt,
two-stage distilled; https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-DubIt)
with core ComfyUI nodes, on the LTX-2.3 models Comfy Cloud hosts. The clip's
frames guide the picture, and its own sound is passed as speaker reference so
the new line keeps the person's voice. Stage one makes picture and sound at
half size; stage two upscales the picture with that sound held as reference.

DubIt was trained on five-second clips. Lines are written in the target
language: the model does not translate, and it handles one speaker. A line of
about the original length works best. Tested 2026-10-25 on Comfy Cloud: the
same clip with an English rewrite and a Spanish line both came back with the
exact words (checked with Whisper), the same face, voice and scene.
"""

import re
import shutil
import subprocess
from pathlib import Path

MAX_SECONDS = 10
PAD_WORDS = 1
LANGUAGES = (
    "English",
    "Spanish",
    "French",
    "German",
    "Italian",
    "Portuguese",
    "Japanese",
    "Korean",
    "Chinese",
    "Hindi",
)
CHECKPOINT = "ltx-2.3-22b-dev.safetensors"
LORA = "ltx-2.3-22b-ic-lora-lipdub-0.9.safetensors"
FIRST_PASS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
SECOND_PASS = "0.909375, 0.725, 0.421875, 0.0"
# Final picture size for each clip shape, both sides multiples of 64 when halved.
SIZES = {"portrait": (1088, 1920), "landscape": (1920, 1088), "square": (1536, 1536)}


def node(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def prompt(line: str, language: str) -> str:
    line = " ".join(line.split()).replace('"', "'")
    if not line:
        raise ValueError("Type what they should say.")
    if language not in LANGUAGES:
        raise ValueError("Choose a listed language.")
    return (
        "The person in the video keeps talking to the camera with the same voice, "
        f'speaking in {language} saying: "{line}"'
    )


def resize(image: list, width: int, height: int) -> dict:
    return node(
        "ResizeImageMaskNode",
        input=image,
        resize_type="scale dimensions",
        **{
            "resize_type.width": width,
            "resize_type.height": height,
            "resize_type.crop": "disabled",
        },
        scale_method="area",
    )


def graph(line: str, language: str, shape: str, seed: int = 42) -> dict:
    width, height = SIZES[shape]
    text = prompt(line, language)
    return {
        "source": node("LoadVideo", file="source.mp4"),
        "parts": node("GetVideoComponents", video=["source", 0]),
        "small": resize(["parts", 0], width // 2, height // 2),
        "large": resize(["parts", 0], width, height),
        "count": node("GetImageSizeAndCount", image=["small", 0]),
        # LTX takes 8k+1 frames.
        "length": node(
            "ComfyMathExpression",
            expression="(int((a - 1) / 8)) * 8 + 1",
            **{"values.a": ["count", 3]},
        ),
        "fps": node("LTXFloatToInt", a=["parts", 2]),
        "checkpoint": node("CheckpointLoaderSimple", ckpt_name=CHECKPOINT),
        "distilled": node(
            "LoraLoaderModelOnly",
            model=["checkpoint", 0],
            lora_name="ltx-2.3-22b-distilled-lora-384-1.1.safetensors",
            strength_model=0.5,
        ),
        "model": node(
            "LTXICLoRALoaderModelOnly",
            model=["distilled", 0],
            lora_name=LORA,
            strength_model=1,
        ),
        "clip": node(
            "LTXAVTextEncoderLoader",
            text_encoder="gemma_3_12B_it.safetensors",
            ckpt_name=CHECKPOINT,
            device="default",
        ),
        "audio-vae": node("LTXVAudioVAELoader", ckpt_name=CHECKPOINT),
        "positive": node("CLIPTextEncode", clip=["clip", 0], text=text),
        "negative": node(
            "CLIPTextEncode",
            clip=["clip", 0],
            text="pc game, console game, video game, cartoon, childish, ugly",
        ),
        "condition": node(
            "LTXVConditioning",
            positive=["positive", 0],
            negative=["negative", 0],
            frame_rate=["parts", 2],
        ),
        "empty": node(
            "EmptyLTXVLatentVideo",
            width=width // 2,
            height=height // 2,
            length=["length", 1],
            batch_size=1,
        ),
        "guide": guide(["condition", 0], ["condition", 1], ["empty", 0], ["small", 0]),
        "voice": node(
            "LTXVAudioVAEEncode", audio=["parts", 1], audio_vae=["audio-vae", 0]
        ),
        "speaker": node(
            "LTXVSetAudioRefTokens",
            positive=["guide", 0],
            negative=["guide", 1],
            audio_latent=["voice", 0],
        ),
        "empty-audio": node(
            "LTXVEmptyLatentAudio",
            audio_vae=["audio-vae", 0],
            frames_number=["length", 1],
            frame_rate=["fps", 0],
            batch_size=1,
        ),
        "first": node(
            "LTXVConcatAVLatent",
            video_latent=["guide", 2],
            audio_latent=["empty-audio", 0],
        ),
        **sampler("first", ["speaker", 0], ["speaker", 1], FIRST_PASS, seed + 1),
        "first-split": node("LTXVSeparateAVLatent", av_latent=["first-sample", 0]),
        "first-crop": node(
            "LTXVCropGuides",
            positive=["guide", 0],
            negative=["guide", 1],
            latent=["first-split", 0],
        ),
        "upscaler": node(
            "LatentUpscaleModelLoader",
            model_name="ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
        ),
        "upscaled": node(
            "LTXVLatentUpsampler",
            samples=["first-crop", 2],
            upscale_model=["upscaler", 0],
            vae=["checkpoint", 2],
        ),
        # The first pass's sound becomes the speaker reference for the second.
        "second-speaker": node(
            "LTXVSetAudioRefTokens",
            positive=["first-crop", 0],
            negative=["first-crop", 1],
            audio_latent=["first-split", 1],
        ),
        "second-guide": guide(
            ["second-speaker", 0],
            ["second-speaker", 1],
            ["upscaled", 0],
            ["large", 0],
        ),
        "second": node(
            "LTXVConcatAVLatent",
            video_latent=["second-guide", 2],
            audio_latent=["second-speaker", 2],
        ),
        **sampler(
            "second", ["second-guide", 0], ["second-guide", 1], SECOND_PASS, seed
        ),
        "second-split": node("LTXVSeparateAVLatent", av_latent=["second-sample", 0]),
        "second-crop": node(
            "LTXVCropGuides",
            positive=["second-guide", 0],
            negative=["second-guide", 1],
            latent=["second-split", 0],
        ),
        "decode": node(
            "LTXVTiledVAEDecode",
            vae=["checkpoint", 2],
            latents=["second-crop", 2],
            horizontal_tiles=2,
            vertical_tiles=2,
            overlap=6,
            last_frame_fix=False,
            working_device="auto",
            working_dtype="auto",
        ),
        "sound": node(
            "LTXVAudioVAEDecode",
            samples=["second-split", 1],
            audio_vae=["audio-vae", 0],
        ),
        "video": node(
            "CreateVideo", images=["decode", 0], audio=["sound", 0], fps=["parts", 2]
        ),
        "save": node(
            "SaveVideo",
            video=["video", 0],
            filename_prefix="aipg-cinema/lipdub",
            format="auto",
            codec="auto",
            **{"format.codec": "auto"},
        ),
    }


def guide(positive: list, negative: list, latent: list, image: list) -> dict:
    return node(
        "LTXAddVideoICLoRAGuide",
        positive=positive,
        negative=negative,
        vae=["checkpoint", 2],
        latent=latent,
        image=image,
        frame_idx=0,
        strength=1,
        latent_downscale_factor=1,
        crop="disabled",
        use_tiled_encode=True,
        tile_size=256,
        tile_overlap=64,
    )


def sampler(name: str, positive: list, negative: list, sigmas: str, seed: int) -> dict:
    return {
        f"{name}-noise": node("RandomNoise", noise_seed=seed),
        f"{name}-select": node("KSamplerSelect", sampler_name="euler"),
        f"{name}-sigmas": node("ManualSigmas", sigmas=sigmas),
        f"{name}-guider": node(
            "CFGGuider", model=["model", 0], positive=positive, negative=negative, cfg=1
        ),
        f"{name}-sample": node(
            "SamplerCustomAdvanced",
            noise=[f"{name}-noise", 0],
            guider=[f"{name}-guider", 0],
            sampler=[f"{name}-select", 0],
            sigmas=[f"{name}-sigmas", 0],
            latent_image=[name, 0],
        ),
    }


def changed_span(
    before: list[dict], after: list[dict]
) -> tuple[int, int, int, int] | None:
    """Word ranges (before i1:i2, after j1:j2) covering every change, or None."""
    from difflib import SequenceMatcher

    def words(spoken: list[dict]) -> list[str]:
        return [re.sub(r"[^\w']", "", w["word"].lower()) for w in spoken]

    changes = [
        op
        for op in SequenceMatcher(
            a=words(before), b=words(after), autojunk=False
        ).get_opcodes()
        if op[0] != "equal"
    ]
    if not changes:
        return None
    return changes[0][1], changes[-1][2], changes[0][3], changes[-1][4]


def boundary(spoken: list[dict], index: int, length: float) -> float:
    """The quiet point just before word `index` (the clip's ends at the edges)."""
    if index <= 0:
        return 0.0
    if index >= len(spoken):
        return length
    return (spoken[index - 1]["end"] + spoken[index]["start"]) / 2


def splice(source: Path, dubbed: Path, destination: Path) -> str:
    """Keep the original clip and cut in only the dubbed stretch that changed.

    Most of the result is then the real footage, lips and sound; a changed
    word's mouth comes from the dub. Returns "spliced", or "whole" when the
    whole line changed (or nothing matched) and the full dub is kept.
    """
    from .captions import transcribe
    from .reshoot import probe

    before, after = transcribe(source), transcribe(dubbed)
    span = changed_span(before, after)
    if span is None or (span[0] == 0 and span[1] == len(before)):
        shutil.copyfile(dubbed, destination)
        return "whole"
    # Fast talkers leave no gap between words, so a cut right at the change
    # clips it; one neighbouring word on each side comes from the dub too.
    i1, i2, j1, j2 = span
    i1, j1 = max(i1 - PAD_WORDS, 0), max(j1 - PAD_WORDS, 0)
    i2, j2 = min(i2 + PAD_WORDS, len(before)), min(j2 + PAD_WORDS, len(after))
    info = probe(source)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    width, height = int(video["width"]), int(video["height"])
    original = float(info["format"]["duration"])
    dub_length = float(probe(dubbed)["format"]["duration"])
    pieces = [
        (0, 0.0, boundary(before, i1, original)),
        (1, boundary(after, j1, dub_length), boundary(after, j2, dub_length)),
        (0, boundary(before, i2, original), original),
    ]
    pieces = [piece for piece in pieces if piece[2] - piece[1] > 0.05]
    chain, labels = [], ""
    for index, (clip, start, end) in enumerate(pieces):
        chain.append(
            f"[{clip}:v]trim={start:.3f}:{end:.3f},setpts=PTS-STARTPTS,"
            f"scale={width}:{height},setsar=1,fps=24[v{index}];"
            f"[{clip}:a]atrim={start:.3f}:{end:.3f},asetpts=PTS-STARTPTS,"
            "aformat=sample_rates=48000:channel_layouts=stereo,"
            f"afade=t=in:d=0.01,areverse,afade=t=in:d=0.01,areverse[a{index}]"
        )
        labels += f"[v{index}][a{index}]"
    partial = destination.with_suffix(".partial.mp4")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(source),
         "-i", str(dubbed), "-filter_complex",
         ";".join(chain) + f";{labels}concat=n={len(pieces)}:v=1:a=1[v][a]",
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "17",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
         str(partial)],
        check=True, timeout=600,
    )  # fmt: skip
    partial.replace(destination)
    return "spliced"
