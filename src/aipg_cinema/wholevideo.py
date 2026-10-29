# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Restyle a whole clip: consecutive takes that share their boundary looks.

A clip of up to two minutes is cut into back-to-back windows of 10 seconds
(the last one 5 or 10). With anchors only every 15 seconds the style faded
mid-take on a fast push-in; every 10 seconds held it (2026-10-23). One look is made from every boundary frame with
the same style prompt and seed (and the user's style picture, if any). Using
the first look as the style picture instead made Klein copy its composition
onto later frames, so takes fought their anchors (2026-10-23). Each
take opens on its boundary look and ends on the next one, so both sides of
every seam are pinned to the same picture. The finished takes, each carrying
its own stretch of the original sound, are joined end to end.

The orchestrator only talks to the running studio's loopback API, so every
studio limit, estimate and receipt still applies. Request ids are saved
before each request, so a restart finds the same jobs: nothing is submitted
twice and nothing failed is retried.
"""

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from filelock import FileLock
from filelock import Timeout as LockTimeout

TERMINAL = ("succeeded", "failed", "cancelled", "needs_review", "needs_recovery")
MIN_SECONDS = 20
MAX_SECONDS = 120
WINDOW = 10


def plan(duration: float) -> list[tuple[int, int]]:
    """Back-to-back (start, seconds) windows; a tail under 5 s is left out."""
    usable = min(int(duration + 1e-6), MAX_SECONDS) // 5 * 5
    if usable < MIN_SECONDS:
        raise ValueError(
            f"Whole-clip restyle needs at least {MIN_SECONDS} seconds of video and "
            f"uses the first {MAX_SECONDS} at most; this clip has {duration:.1f} s. "
            "Trim or pick a longer clip."
        )
    windows, start = [], 0
    while start < usable:
        seconds = min(WINDOW, usable - start)
        windows.append((start, seconds))
        start += seconds
    return windows


def check_capacity(windows: list[tuple[int, int]], config: dict) -> None:
    """Refuse before anything is submitted if the session's limits are too low.

    Every window is one take; every window boundary (one more than the
    windows) is one look. The studio counts its limits per directory, so the
    suggested flags include what this session has already used.
    """
    takes, looks = len(windows), len(windows) + 1
    renders_used = int(config.get("renders_used", 0))
    looks_used = int(config.get("looks_used", 0))
    takes_left = int(config["max_renders"]) - renders_used
    looks_left = int(config["max_looks"]) - looks_used
    if takes_left < takes or looks_left < looks:
        raise ValueError(
            f"This clip needs {takes} takes and {looks} looks but the session "
            f"allows {max(takes_left, 0)} more takes and {max(looks_left, 0)} "
            f"more looks. Restart with --max-renders {renders_used + takes} "
            f"--max-looks {looks_used + looks}."
        )


class Studio:
    def __init__(self, url: str):
        host = httpx.URL(url).host
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("The studio must be a loopback address.")
        self.url = url.rstrip("/")

    def call(self, method: str, path: str, **kwargs):
        response = httpx.request(method, self.url + path, timeout=120, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text[:300]
            raise RuntimeError(str(detail))
        return response

    def wait(self, path: str) -> dict:
        while True:
            item = self.call("GET", path).json()
            if not item.get("active") and item.get("status") in TERMINAL:
                return item
            time.sleep(4)


class Run:
    def __init__(self, folder: Path, studio: Studio):
        self.folder, self.studio = folder, studio
        self.request = json.loads((folder / "request.json").read_text())
        state = folder / "state.json"
        self.state = json.loads(state.read_text()) if state.is_file() else {}

    def save(self, **changes):
        self.state.update(changes)
        temporary = self.folder / "state.json.tmp"
        temporary.write_text(json.dumps(self.state, indent=1))
        temporary.replace(self.folder / "state.json")

    def request_id(self, key: str) -> str:
        ids = self.state.setdefault("request_ids", {})
        if key not in ids:
            ids[key] = uuid.uuid4().hex
            self.save()
        return ids[key]

    def look(self, key: str, start: int, seconds: int, frame: int, style=None) -> str:
        body = {
            "request_id": self.request_id(key),
            "source_id": self.request["source_id"],
            "prompt": self.request["look"],
            "seed": self.request["seed"],
            "denoise": None,
            "frame_index": frame,
            "frame_format": self.request["frame_format"],
            "source_start": start,
            **({"seconds": seconds} if seconds != 5 else {}),
            **({"style_image_id": style} if style else {}),
        }
        item = self.studio.call("POST", "/api/look-jobs", json=body).json()
        item = self.studio.wait(f"/api/look-jobs/{item['id']}")
        if item.get("status") != "succeeded":
            raise RuntimeError(
                f"Look {key} ended {item.get('status')}: {item.get('error')}"
            )
        return item["id"]

    def upload(self, key: str, look_id: str) -> str:
        """Re-upload a look so it can end the previous window too."""
        uploads = self.state.setdefault("uploads", {})
        if key not in uploads:
            image = self.studio.call("GET", f"/api/looks/{look_id}").content
            uploads[key] = self.studio.call(
                "POST",
                f"/api/looks?frame_format={self.request['frame_format']}",
                files={"file": (f"{key}.png", image, "image/png")},
            ).json()["look_id"]
            self.save()
        return uploads[key]

    def take(self, index: int, start: int, seconds: int, opening: str, ending: str):
        body = {
            "request_id": self.request_id(f"take-{index}"),
            "mode": "video",
            "source_id": self.request["source_id"],
            "look_id": opening,
            "closing_id": ending,
            "prompt": self.request["motion"] or self.request["look"],
            "art_direction": self.request["look"],
            "motion_prompt": self.request["motion"],
            "seed": self.request["seed"],
            "frame_format": self.request["frame_format"],
            "source_start": start,
            **({"seconds": seconds} if seconds != 5 else {}),
        }
        item = self.studio.call("POST", "/api/jobs", json=body).json()
        item = self.studio.wait(f"/api/jobs/{item['id']}")
        if item.get("status") != "succeeded":
            raise RuntimeError(
                f"Take {index + 1} ended {item.get('status')}: {item.get('error')}"
            )
        target = self.folder / f"take-{index + 1:02d}.mp4"
        if not target.is_file():
            partial = target.with_suffix(".partial")
            partial.write_bytes(
                self.studio.call("GET", f"/api/jobs/{item['id']}/output").content
            )
            partial.replace(target)
        return item["id"], target

    def execute(self):
        info = self.studio.call(
            "GET", f"/api/sources/{self.request['source_id']}/info"
        ).json()
        windows = plan(float(info["duration"]))
        if not self.state.get("request_ids"):
            # A fresh run: nothing submitted yet, so the limits can still be
            # raised instead of failing half-way through the clip.
            config = self.studio.call("GET", "/api/config").json()
            check_capacity(windows, config)
        self.save(
            status="running", windows=windows, step="Planning", takes_done=0, error=None
        )
        boundaries = []
        style = self.request.get("style_image_id")
        for k, (start, seconds) in enumerate(windows):
            self.save(step=f"Look {k + 1} of {len(windows) + 1}")
            boundaries.append(self.look(f"look-{k}", start, seconds, 0, style))
        start, seconds = windows[-1]
        self.save(step=f"Look {len(windows) + 1} of {len(windows) + 1}")
        boundaries.append(self.look("look-end", start, seconds, seconds * 24, style))
        self.save(looks=boundaries)
        takes = []
        for index, (start, seconds) in enumerate(windows):
            self.save(step=f"Take {index + 1} of {len(windows)}")
            last = index == len(windows) - 1
            ending = (
                boundaries[-1]
                if last
                else self.upload(f"end-{index}", boundaries[index + 1])
            )
            take_id, path = self.take(index, start, seconds, boundaries[index], ending)
            takes.append(path)
            self.save(
                takes_done=index + 1,
                take_ids=[*self.state.get("take_ids", []), take_id],
            )
        self.save(step="Joining")
        join(takes, self.folder / "whole.mp4")
        self.save(status="succeeded", step="Done", seconds=sum(s for _, s in windows))


def join(takes: list[Path], destination: Path) -> None:
    """Join takes back to back; picture and sound are re-encoded together."""
    inputs = []
    for path in takes:
        inputs += ["-i", str(path)]
    streams = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(len(takes)))
    partial = destination.with_suffix(".partial.mp4")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-y",
            *inputs,
            "-filter_complex",
            f"{streams}concat=n={len(takes)}:v=1:a=1[v][a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-metadata",
            "title=Openfield - AI-restyled video",
            "-movflags",
            "+faststart",
            str(partial),
        ],
        check=True,
        timeout=1800,
    )
    partial.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--studio", required=True)
    args = parser.parse_args()
    # One orchestrator per restyle folder: the studio reads this lock to
    # report the run as active, and a second start (for example after the
    # server restarted) exits here without touching the first run's state.
    try:
        lock = FileLock(args.folder / ".observer.lock", timeout=0)
        lock.acquire()
    except LockTimeout:
        print("Another whole-clip restyle already drives this folder.", file=sys.stderr)
        raise SystemExit(2) from None
    with lock:
        run = Run(args.folder, Studio(args.studio))
        try:
            run.execute()
        except Exception as error:  # recorded for the editor, then re-raised
            run.save(status="failed", error=str(error))
            raise


if __name__ == "__main__":
    main()
