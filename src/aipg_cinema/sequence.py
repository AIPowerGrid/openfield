# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Offline exports from explicit selected takes, adapted from AIPG Director editing."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from contextlib import ExitStack, nullcontext
from fractions import Fraction
from pathlib import Path

from filelock import FileLock

from .assets import asset_folder
from .contracts import TakeRequest
from .finishing import (
    audio_graph,
    caption_image,
    prepare_layer,
    subtitles,
    validate_finish,
)
from .project import Project, atomic_json
from .reshoot import video_format
from .resources import ResourceError, WorkLimiter
from .store_activity import StoreBusy, store_activity

MAX_BYTES = 512 * 1024 * 1024


def media_input(path: Path) -> list[str]:
    return [
        "-protocol_whitelist",
        "file",
        "-max_streams",
        "2",
        "-f",
        "mov",
        "-enable_drefs",
        "0",
        "-use_absolute_path",
        "0",
        "-i",
        str(path),
    ]


def run(arguments: list[str], timeout: int = 180) -> None:
    subprocess.run(
        arguments,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        env={"PATH": os.environ.get("PATH", os.defpath)},
    )


def inspect(
    path: Path, width: int, height: int, frames: int, *, audio_required: bool = False
) -> dict:
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("A selected take is missing or exceeds the export size bound.")
    with tempfile.TemporaryFile() as output:
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-max_alloc",
                "67108864",
                *media_input(path),
                "-count_frames",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,avg_frame_rate,nb_read_frames,sample_rate,channels,duration_ts,time_base,start_pts",
                "-of",
                "json",
            ],
            check=True,
            timeout=180,
            stdout=output,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.environ.get("PATH", os.defpath)},
        )
        output.seek(0)
        data = output.read(16385)
    if len(data) > 16384:
        raise ValueError("Export media metadata exceeds its bound.")
    streams = json.loads(data)["streams"]
    video = [stream for stream in streams if stream["codec_type"] == "video"]
    sound = [stream for stream in streams if stream["codec_type"] == "audio"]
    if len(video) != 1 or len(sound) > 1 or (audio_required and len(sound) != 1):
        raise ValueError("A take must have one video and at most one audio track.")
    picture = video[0]
    if (
        picture["codec_name"],
        picture["width"],
        picture["height"],
        Fraction(picture["avg_frame_rate"]),
        int(picture["nb_read_frames"]),
    ) != ("h264", width, height, Fraction(24), frames):
        raise ValueError(
            "A selected take has incompatible dimensions, frame rate or frame count."
        )
    for stream in streams:
        if abs(
            Fraction(stream["time_base"]) * int(stream["duration_ts"])
            - Fraction(frames, 24)
        ) > Fraction(1, 48000) or abs(
            Fraction(stream["time_base"]) * int(stream["start_pts"])
        ) > Fraction(1, 48000):
            raise ValueError("The audio/video clock differs from the exact edit.")
    if sound and (
        sound[0]["codec_name"],
        int(sound[0]["sample_rate"]),
        sound[0]["channels"],
    ) != ("aac", 48000, 2):
        raise ValueError("A selected take must use stereo 48-kHz AAC.")
    run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-err_detect",
            "explode",
            *media_input(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-f",
            "null",
            "-",
        ]
    )
    return {
        "width": width,
        "height": height,
        "fps": 24,
        "frames": frames,
        "audio": bool(sound),
        "seconds": frames / 24,
    }


def encode(
    inputs: list[str], graph: str, output: Path, *, copy_audio: bool = False
) -> None:
    run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-filter_complex_threads",
            "1",
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "[v]",
            "-map",
            "0:a:0" if copy_audio else "[a]",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy" if copy_audio else "aac",
            *([] if copy_audio else ["-b:a", "192k"]),
            "-movie_timescale",
            "48000",
            "-movflags",
            "+faststart",
            "-metadata",
            "title=AIPG - AI-generated short",
            "-metadata",
            "description=AI-generated video assembled from explicitly selected takes.",
            "-fs",
            str(MAX_BYTES),
            str(output),
        ],
        timeout=600,
    )


def assemble(
    project: Project, jobs: Path, destination: Path, audios: Path | None = None
) -> Path:
    if not project.shots or any(not shot.selected_take_id for shot in project.shots):
        raise ValueError("Choose one completed take for every shot before exporting.")
    project = Project.model_validate(project.model_dump())
    validate_finish(project)
    jobs = jobs.resolve()
    width, height = video_format(project.frame_format).output_size
    destination.mkdir(parents=True, exist_ok=True)
    result = destination / "short.mp4"
    partial = destination / "short.partial.mp4"
    if result.exists():
        raise ValueError(
            "This export already exists. Keep it and choose a new export ID."
        )
    inputs, parts, joined, commitments = [], [], [], []
    try:
        with tempfile.TemporaryDirectory(
            prefix=".assembling-", dir=destination
        ) as temporary:
            for index, shot in enumerate(project.shots):
                folder = asset_folder(jobs, shot.selected_take_id)
                request = TakeRequest.model_validate_json(
                    (folder / "request.json").read_text()
                )
                original = folder / "render" / "reshoot.mp4"
                if (
                    request.request_id != shot.selected_take_id
                    or request.frame_format != project.frame_format
                    or not original.resolve().is_relative_to(folder.resolve())
                ):
                    raise ValueError(
                        "A selected take differs from its saved identity or framing."
                    )
                if (
                    not original.is_file()
                    or not 0 < original.stat().st_size <= MAX_BYTES
                ):
                    raise ValueError("A selected take is missing or too large.")
                frozen = Path(temporary) / f"shot-{index}.mp4"
                # Inspect the frozen bytes, never a different pre-copy version.
                with original.open("rb") as source, frozen.open("xb") as target:
                    size = 0
                    while chunk := source.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError(
                                "A selected take grew beyond its size bound."
                            )
                        target.write(chunk)
                info = inspect(frozen, width, height, 120)
                with frozen.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                inputs += media_input(frozen)
                count = shot.trim_end - shot.trim_start
                samples = count * 2000
                parts.append(
                    f"[{index}:v]trim=start_frame={shot.trim_start}:end_frame={shot.trim_end},setpts=N/(24*TB),setsar=1,format=yuv420p[v{index}]"
                )
                if info["audio"]:
                    sound = f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=start_sample={shot.trim_start * 2000}:end_sample={shot.trim_end * 2000},asetpts=N/(48000*TB),volume={shot.volume},"
                else:
                    sound = "anullsrc=r=48000:cl=stereo,"
                parts.append(
                    sound
                    + f"apad=whole_len={samples},atrim=end_sample={samples},asetpts=N/(48000*TB)[a{index}]"
                )
                joined += [f"[v{index}]", f"[a{index}]"]
                commitments.append(
                    {
                        "shot_id": shot.id,
                        "take_id": shot.selected_take_id,
                        "sha256": digest,
                        "settings": request.model_dump(),
                    }
                )
            parts.append(
                "".join(joined) + f"concat=n={len(project.shots)}:v=1:a=1[v][base]"
            )
            sound_commitments, sound_labels = [], ["[base]"]
            for role in ("music", "voiceover"):
                layer = getattr(project, role)
                if layer:
                    if audios is None:
                        raise ValueError(
                            "This export needs its local soundtrack assets."
                        )
                    normalized, commitment = prepare_layer(
                        audios, layer, Path(temporary), role
                    )
                    index = len(project.shots) + len(sound_commitments)
                    inputs += [
                        "-protocol_whitelist",
                        "file",
                        "-f",
                        "wav",
                        "-i",
                        str(normalized),
                    ]
                    parts.append(audio_graph(layer, index, role, project.frames))
                    sound_labels.append(f"[{role}]")
                    sound_commitments.append(commitment)
            if len(sound_labels) > 1:
                parts.append(
                    "".join(sound_labels)
                    + f"amix=inputs={len(sound_labels)}:normalize=0:duration=first,alimiter=limit=0.95:level=false:latency=true[a]"
                )
            else:
                parts.append("[base]anull[a]")
            picture = Path(temporary) / "picture.mp4"
            encode(inputs, ";".join(parts), picture)
            output = inspect(
                picture, width, height, project.frames, audio_required=True
            )
            caption_commitments = []
            if project.captions:
                caption_inputs = media_input(picture)
                caption_filters = ["[0:v]setpts=PTS-STARTPTS[c0]"]
                for index, caption in enumerate(
                    sorted(project.captions, key=lambda cue: cue.start_frame), 1
                ):
                    image, layout = caption_image(
                        caption.text,
                        project.frame_format,
                        project.caption_style,
                        project.caption_position,
                    )
                    path = Path(temporary) / f"caption-{index}.png"
                    image.save(path)
                    caption_inputs += [
                        "-protocol_whitelist",
                        "file",
                        "-f",
                        "image2",
                        "-pattern_type",
                        "none",
                        "-i",
                        str(path),
                    ]
                    caption_filters.append(
                        f"[c{index - 1}][{index}:v]overlay=0:0:eof_action=repeat:enable='between(n,{caption.start_frame},{caption.end_frame - 1})'[c{index}]"
                    )
                    caption_commitments.append(
                        {**caption.model_dump(), "layout": layout}
                    )
                caption_filters.append(f"[c{len(project.captions)}]null[v]")
                encode(
                    caption_inputs, ";".join(caption_filters), partial, copy_audio=True
                )
                output = inspect(
                    partial, width, height, project.frames, audio_required=True
                )
            else:
                picture.replace(partial)
            atomic_json(
                destination / "manifest.json",
                {
                    "version": 1,
                    "ai_generated": True,
                    "project": project.model_dump(),
                    "takes": commitments,
                    "audio_layers": sound_commitments,
                    "captions": caption_commitments,
                },
            )
            (destination / "captions.srt").write_text(
                subtitles(project), encoding="utf-8"
            )
            atomic_json(destination / "quality.json", output)
            if project.captions:
                picture.replace(destination / "picture.mp4")
            partial.replace(result)
        return result
    finally:
        partial.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path)
    parser.add_argument("--resource-root", type=Path)
    args = parser.parse_args()
    with ExitStack() as stack:
        if args.resource_root:
            try:
                stack.enter_context(store_activity(args.resource_root.parent))
            except StoreBusy:
                print("Store maintenance is active. Check this saved export afterward.")
                return 75
        args.directory.mkdir(parents=True, exist_ok=True)
        stack.enter_context(FileLock(args.directory / ".observer.lock", timeout=0))
        try:
            admission = (
                WorkLimiter.reopen(args.resource_root).acquire(
                    args.jobs.resolve().parent.name, export=True
                )
                if args.resource_root
                else nullcontext()
            )
            with admission:
                atomic_json(args.directory / "state.json", {"status": "running"})
                project = Project.model_validate_json(args.project.read_text())
                assemble(project, args.jobs, args.directory, args.audio_root)
                atomic_json(args.directory / "state.json", {"status": "succeeded"})
        except ResourceError as error:
            atomic_json(
                args.directory / "state.json", {"status": "failed", "error": str(error)}
            )
            return 1
        except (
            ValueError,
            KeyError,
            TypeError,
            ZeroDivisionError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            atomic_json(
                args.directory / "state.json",
                {
                    "status": "failed",
                    "error": str(error)
                    if isinstance(error, ValueError)
                    else "Local export failed validation. Your selected takes are unchanged.",
                },
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
