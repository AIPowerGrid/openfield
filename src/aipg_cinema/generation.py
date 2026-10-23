# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""SDK-ready LTX starting modes, including the Director's fixed-audio graph."""

import json
import math
import os
import subprocess
import tempfile
import wave
from pathlib import Path

from .reshoot import graph as reshoot_graph
from .reshoot import node

AUDIO_FORMATS = {
    ".wav": "wav",
    ".mp3": "mp3",
    ".m4a": "mov",
    ".mp4": "mov",
    ".flac": "flac",
    ".ogg": "ogg",
    ".opus": "ogg",
    ".aac": "aac",
    ".webm": "matroska",
    ".mkv": "matroska",
}


def audio_input(source: Path) -> list[str]:
    fmt = AUDIO_FORMATS.get(source.suffix.lower())
    if fmt is None:
        raise ValueError("Choose WAV, MP3, M4A, FLAC, Ogg, AAC or WebM audio.")
    arguments = ["-protocol_whitelist", "file", "-max_streams", "2", "-f", fmt]
    if fmt == "mov":
        arguments += ["-enable_drefs", "0", "-use_absolute_path", "0"]
    return [*arguments, "-i", str(source)]


def audio_info(source: Path, *, min_duration: float = 5) -> dict:
    if not source.is_file() or not 0 < source.stat().st_size <= 50 * 1024 * 1024:
        raise ValueError("Choose an audio file smaller than 50 MB.")
    with tempfile.TemporaryFile() as output:
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-max_alloc",
                "67108864",
                *audio_input(source),
                "-show_entries",
                "stream=codec_type,duration,sample_rate,channels:format=duration",
                "-of",
                "json",
            ],
            check=True,
            timeout=30,
            stdout=output,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.environ.get("PATH", os.defpath)},
        )
        output.seek(0)
        data = output.read(65537)
    if len(data) > 65536:
        raise ValueError("Audio metadata exceeds the inspection limit.")
    info = json.loads(data)
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if (
        len(audio) != 1
        or not 1 <= int(audio[0]["channels"]) <= 8
        or not 8000 <= int(audio[0]["sample_rate"]) <= 192000
    ):
        raise ValueError("Choose a file with one unambiguous supported audio track.")
    duration = float(
        audio[0].get("duration") or info.get("format", {}).get("duration", 0)
    )
    if not math.isfinite(duration) or not min_duration <= duration <= 1800:
        minimum = "five seconds" if min_duration == 5 else f"{min_duration:g} seconds"
        raise ValueError(f"Choose audio between {minimum} and 30 minutes long.")
    return info


def graph(
    prompt: str,
    seed: int = 42,
    *,
    mode: str = "text",
    frame_format: str = "portrait",
    opening: bool = False,
    closing: bool = False,
    render_profile: str = "two-pass",
) -> dict:
    if mode not in ("text", "image", "audio"):
        raise ValueError("Choose text, image or audio generation.")
    if not prompt.strip() or len(prompt) > 4000:
        raise ValueError("Describe the shot in 1-4000 characters.")
    if type(seed) is not int or not 0 <= seed <= 2**63 - 1:
        raise ValueError("Choose a non-negative whole-number seed below 2^63.")
    if render_profile == "single-pass-audio":
        from .speech import graph as speech_graph

        if mode != "audio":
            raise ValueError("Single-pass speech requires audio input.")
        return speech_graph(
            prompt, seed, frame_format=frame_format, opening=opening, closing=closing
        )
    if render_profile != "two-pass":
        raise ValueError("Choose a supported LTX render profile.")
    if mode == "image" and not opening:
        raise ValueError("Image-to-video requires an opening image.")
    workflow = reshoot_graph(
        "ltx25",
        prompt,
        seed,
        look_frame=opening,
        closing_frame=closing,
        frame_format=frame_format,
    )
    # Keep the established two-pass graph, but remove source-video control.
    for key in ("source", "frames", "source-window", "edges", "guide", "model"):
        workflow.pop(key)
    workflow["negative"]["inputs"]["text"] = (
        "flicker, cuts, distorted geometry, watermark, unwanted text and logos"
    )
    condition = {"positive": ["condition", 0], "negative": ["condition", 1]}
    latent = ["look-anchor", 0] if opening else ["empty", 0]
    if closing:
        workflow["closing-guide"]["inputs"].update(**condition, latent=latent)
    else:
        workflow["av"]["inputs"]["video_latent"] = latent
        for key in ("guider", "crop"):
            workflow[key]["inputs"].update(condition)
    for key in ("guider", "refine-guider"):
        workflow[key]["inputs"]["model"] = ["backbone", 0]
    if mode == "audio":
        # Adapted from AIPG Director ltx.py under the owner's MIT reuse grant.
        # The audio is fixed conditioning, not a voice reference or a new voice.
        workflow.update(
            {
                "source-audio": node("LoadAudio", audio="source.wav"),
                "encode-audio": node(
                    "LTXVAudioVAEEncode",
                    audio=["source-audio", 0],
                    audio_vae=["audio-vae", 0],
                ),
                "audio-mask": node("SolidMask", value=0.0, width=1, height=1),
                "empty-audio": node(
                    "SetLatentNoiseMask",
                    samples=["encode-audio", 0],
                    mask=["audio-mask", 0],
                ),
            }
        )
        workflow["refine-av"]["inputs"]["audio_latent"] = ["empty-audio", 0]
        sound = ["source-audio", 0]
    else:
        workflow["decode-audio"] = node(
            "LTXVAudioVAEDecode",
            samples=["refine-separate", 1],
            audio_vae=["audio-vae", 0],
        )
        sound = ["decode-audio", 0]
    workflow["video"]["inputs"]["audio"] = sound
    return workflow


def prepare_audio(source: Path, directory: Path, source_start: float = 0) -> Path:
    if not math.isfinite(source_start) or source_start < 0:
        raise ValueError("Choose a non-negative audio start time.")
    info = audio_info(source)
    audio = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
    if len(audio) != 1:
        raise ValueError("Choose a file with one unambiguous audio track.")
    duration = float(audio[0].get("duration", info["format"]["duration"]))
    if (
        not math.isfinite(duration)
        or duration > 1800
        or duration + 0.001 < source_start + 5
    ):
        raise ValueError(
            "Choose a five-second audio section within a file of at most 30 minutes."
        )
    destination = directory / "source.wav"
    # Only the extra model frame is silent padding; the exported five seconds
    # must be covered by real source audio, checked above.
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-ss",
            str(source_start),
            *audio_input(source),
            "-map",
            "0:a:0",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            "-af",
            "aresample=48000,atrim=duration=5,apad=whole_len=242000,atrim=end_sample=242000",
            str(destination),
        ],
        check=True,
        timeout=90,
        env={"PATH": os.environ.get("PATH", os.defpath)},
    )
    with wave.open(str(destination)) as audio_file:
        if (
            audio_file.getnchannels(),
            audio_file.getsampwidth(),
            audio_file.getframerate(),
            audio_file.getnframes(),
        ) != (2, 2, 48000, 242000):
            raise ValueError(
                "Audio normalization did not produce the exact model duration."
            )
    return destination


def finish(
    directory: Path, generated: Path, *, frame_format: str | None = None
) -> Path:
    destination = directory / "reshoot.mp4"
    temporary = directory / "reshoot.partial.mp4"
    audio = directory / "source.wav"
    picture_filter = "trim=end_frame=120,setpts=PTS-STARTPTS"
    if frame_format:
        from .reshoot import video_format
        from .sequence import inspect

        spec = video_format(frame_format)
        inspect(generated, spec.width, spec.height, 121, audio_required=True)
        width, height = spec.output_size
        picture_filter += f",scale={width}:{height}:flags=lanczos,setsar=1"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(generated),
            "-i",
            str(audio if audio.is_file() else generated),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            picture_filter,
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-af",
            "aresample=48000,apad=whole_len=240000,atrim=end_sample=240000,asetpts=PTS-STARTPTS",
            "-t",
            "5",
            "-metadata",
            "title=AIPG - AI-generated video",
            "-metadata",
            "description=AI-generated video. Supplied source audio retained when present.",
            "-movflags",
            "+faststart",
            "-movie_timescale",
            "48000",
            "-video_track_timescale",
            "24000",
            str(temporary),
        ],
        check=True,
        timeout=180,
        env={"PATH": os.environ.get("PATH", os.defpath)},
    )
    if frame_format:
        inspect(temporary, width, height, 120, audio_required=True)
    temporary.replace(destination)
    return destination
