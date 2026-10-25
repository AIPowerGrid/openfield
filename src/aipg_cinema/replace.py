# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Replace the person (beta): someone from a photo takes over a talking clip.

Editing the original frame always left part of the original person behind,
and following the clip's edges made the new face copy the old lip shapes
(2026-10-23). So the person is rebuilt instead:

1. Klein removes the person from the clip's first frame (an empty scene).
2. Klein places the person from the photo into that empty scene.
3. LTX animates them from the clip's own voice (single-pass speech), so the
   lips follow the words. Body motion is new, not copied from the clip.
4. The result keeps the clip's sound; a before/after wipe is made too.

Like the whole-clip restyle, it drives the studio's loopback API with saved
request ids: a restart finds the same jobs and nothing is retried.
"""

import argparse
import subprocess
from pathlib import Path

from .tools import compare
from .wholevideo import Run, Studio

PLATE = (
    "Remove the person completely and show the empty scene behind them: the same "
    "room, furniture, background, lighting, camera angle and framing, with nobody "
    "in it. Photorealistic."
)
PLACE = (
    "Create a new photo of the exact person from the first image, with the same "
    "face, eyes, nose, teeth, eyebrows, hair and skin, placed into the empty scene "
    "from the second image: the same background, lighting and camera angle. They "
    "are fully clothed in everyday clothes that suit the scene, with a solid, "
    "natural adult body in normal proportion to their head, standing or sitting "
    "firmly in the scene. Centred in the frame, head and shoulders clearly visible, "
    "talking to the camera like a vlogger, mouth open mid-sentence. Photorealistic. "
    "{note}"
)
TALK = (
    "The person talks to the camera with natural head movement and expressions, "
    "their lips and jaw precisely following the supplied speech. One continuous "
    "shot. {note}"
)


class Replacement(Run):
    def look_job(self, key: str, body: dict) -> str:
        item = self.studio.call(
            "POST",
            "/api/look-jobs",
            json={
                "request_id": self.request_id(key),
                "seed": self.request["seed"],
                "denoise": None,
                "frame_format": self.request["frame_format"],
                **body,
            },
        ).json()
        item = self.studio.wait(f"/api/look-jobs/{item['id']}")
        if item.get("status") != "succeeded":
            raise RuntimeError(f"The {key} image ended {item.get('status')}.")
        return item["id"]

    def upload_file(self, key: str, path: Path, route: str, field: str) -> str:
        uploads = self.state.setdefault("uploads", {})
        if key not in uploads:
            with path.open("rb") as handle:
                uploads[key] = self.studio.call(
                    "POST", route, files={"file": (path.name, handle)}
                ).json()[field]
            self.save()
        return uploads[key]

    def execute(self):
        note = self.request.get("note", "").strip()
        fmt = self.request["frame_format"]
        self.save(status="running", step="Reading the clip")
        window = self.folder / "window.mp4"
        if not window.is_file():
            window.write_bytes(
                self.studio.call(
                    "GET",
                    f"/api/sources/{self.request['source_id']}?frame_format={fmt}"
                    f"&source_start={self.request['source_start']}",
                ).content
            )
        frame, voice = self.folder / "frame.png", self.folder / "voice.wav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(window),
             "-frames:v", "1", str(frame)],
            check=True, timeout=120,
        )  # fmt: skip
        sound = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(window), "-map",
             "0:a:0", "-af", "apad=whole_dur=6", "-t", "6", "-ar", "48000", "-ac",
             "2", "-c:a", "pcm_s16le", str(voice)],
            check=False, capture_output=True, timeout=120,
        )  # fmt: skip
        if sound.returncode or not voice.is_file():
            raise RuntimeError(
                "This clip has no sound; the new person speaks its voice."
            )
        looks = f"/api/looks?frame_format={fmt}"
        self.save(step="Emptying the scene (1 of 3)")
        scene = self.upload_file("frame", frame, looks, "look_id")
        plate = self.look_job(
            "plate", {"look_input": "image", "image_id": scene, "prompt": PLATE}
        )
        plate_image = self.folder / "plate.png"
        plate_image.write_bytes(self.studio.call("GET", f"/api/looks/{plate}").content)
        self.save(step="Placing the new person (2 of 3)")
        placed = self.look_job(
            "placed",
            {
                "look_input": "image",
                "image_id": self.request["photo_id"],
                "reference_ids": [
                    self.upload_file("plate", plate_image, looks, "look_id")
                ],
                "prompt": PLACE.format(note=note).strip(),
            },
        )
        opening = self.folder / "opening.png"
        opening.write_bytes(self.studio.call("GET", f"/api/looks/{placed}").content)
        self.save(step="Animating from the voice (3 of 3)", opening=placed)
        body = {
            "request_id": self.request_id("take"),
            "mode": "audio",
            "render_profile": "single-pass-audio",
            "audio_id": self.upload_file(
                "voice", voice, "/api/audio?purpose=conditioning", "audio_id"
            ),
            "look_id": self.upload_file("opening", opening, looks, "look_id"),
            "prompt": TALK.format(note=note).strip(),
            "art_direction": TALK.format(note=note).strip(),
            "motion_prompt": "",
            "seed": self.request["seed"],
            "frame_format": fmt,
        }
        item = self.studio.call("POST", "/api/jobs", json=body).json()
        item = self.studio.wait(f"/api/jobs/{item['id']}")
        if item.get("status") != "succeeded":
            raise RuntimeError(
                item.get("error") or f"The take ended {item.get('status')}."
            )
        result = self.folder / "replaced.mp4"
        partial = result.with_suffix(".partial.mp4")
        partial.write_bytes(
            self.studio.call("GET", f"/api/jobs/{item['id']}/output").content
        )
        partial.replace(result)
        self.save(step="Making the before / after", take_id=item["id"])
        compare(window, result, self.folder / "compare.mp4", "wipe")
        self.save(status="succeeded", step="Done")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--studio", required=True)
    args = parser.parse_args()
    run = Replacement(args.folder, Studio(args.studio))
    try:
        run.execute()
    except Exception as error:  # recorded for the editor, then re-raised
        run.save(status="failed", error=str(error))
        raise


if __name__ == "__main__":
    main()
