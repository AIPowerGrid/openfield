"""Original procedural motion fixtures, not photographic showcase footage."""

import argparse
import math
import struct
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT, FPS, FRAMES = 768, 448, 24, 124
CASES = ("car", "bounce", "pendulum")


def center(case: str, t: float) -> tuple[float, float]:
    t = min(t, 5.0)
    if case == "car":
        return WIDTH * (0.18 + 0.64 * t / 5), HEIGHT * 0.68
    if case == "bounce":
        return WIDTH * (0.25 + 0.5 * t / 5), HEIGHT * (
            0.72 - 0.38 * abs(math.sin(math.pi * t))
        )
    if case == "pendulum":
        angle = 0.65 * math.sin(2 * math.pi * t / 2.5)
        return WIDTH * 0.5 + 190 * math.sin(angle), 70 + 190 * math.cos(angle)
    raise ValueError(f"Unknown fixture: {case}")


def frame(case: str, index: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#d7d9dd")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 330, WIDTH, HEIGHT), fill="#a5a7ad")
    for x in range(0, WIDTH, 96):
        draw.line((x, 330, x - 40, HEIGHT), fill="#989ba2", width=2)
    t = index / FPS
    x, y = center(case, t)
    if case == "car":
        draw.ellipse((x - 75, 326, x + 77, 343), fill="#898b91")
        draw.rounded_rectangle((x - 72, y - 20, x + 72, y + 20), 12, "#174fc5")
        draw.polygon(
            ((x - 45, y - 20), (x - 28, y - 55), (x + 30, y - 55), (x + 51, y - 20)),
            fill="#2467dc",
        )
        draw.polygon(
            ((x - 28, y - 24), (x - 17, y - 47), (x + 24, y - 47), (x + 38, y - 24)),
            fill="#9fd6e6",
        )
        for wheel_x in (x - 43, x + 43):
            draw.ellipse((wheel_x - 16, y + 5, wheel_x + 16, y + 37), fill="#282a31")
            draw.ellipse((wheel_x - 8, y + 13, wheel_x + 8, y + 29), fill="#abb6c5")
            draw.line(
                (
                    wheel_x,
                    y + 21,
                    wheel_x + 7 * math.cos(t * 8),
                    y + 21 + 7 * math.sin(t * 8),
                ),
                fill="#30333a",
                width=3,
            )
    else:
        if case == "pendulum":
            draw.line((WIDTH / 2, 70, x, y), fill="#343944", width=5)
            draw.rounded_rectangle(
                (WIDTH / 2 - 60, 52, WIDTH / 2 + 60, 70), 4, "#505661"
            )
        draw.ellipse((x - 28, y - 28, x + 28, y + 28), fill="#df443d")
        draw.ellipse((x - 15, y - 19, x - 4, y - 8), fill="#ffb0a0")
    return image


def make_fixture(case: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    audio = destination / "source.wav"
    sample_rate = 48000
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
        samples = bytearray()
        for index in range(round(FRAMES / FPS * sample_rate)):
            t = index / sample_rate
            phase = (t - 0.5) % 1.0
            envelope = math.sin(math.pi * phase / 0.06) if phase < 0.06 else 0
            samples.extend(
                struct.pack(
                    "<h", round(2400 * envelope * math.sin(t * 2 * math.pi * 660))
                )
            )
        wav.writeframes(samples)
    video = destination / "source.mp4"
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{WIDTH}x{HEIGHT}",
            "-framerate",
            str(FPS),
            "-i",
            "pipe:0",
            "-i",
            str(audio),
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
            str(video),
        ],
        stdin=subprocess.PIPE,
    )
    try:
        assert process.stdin is not None
        for index in range(FRAMES):
            process.stdin.write(frame(case, index).tobytes())
        process.stdin.close()
    except BaseException:
        process.kill()
        process.wait()
        raise
    if process.wait() != 0:
        raise RuntimeError("FFmpeg failed to encode the original fixture.")
    frame(case, 0).save(destination / "first-frame.png")
    return video


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    for case in CASES:
        print(make_fixture(case, args.directory / case).resolve())


if __name__ == "__main__":
    main()
