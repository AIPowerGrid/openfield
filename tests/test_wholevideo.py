import subprocess

import pytest

from aipg_cinema import wholevideo


def test_plan_covers_the_clip_in_back_to_back_windows():
    assert wholevideo.plan(62.4) == [
        (0, 10),
        (10, 10),
        (20, 10),
        (30, 10),
        (40, 10),
        (50, 10),
    ]
    assert wholevideo.plan(68) == [*wholevideo.plan(62.4), (60, 5)]
    assert wholevideo.plan(41) == [(0, 10), (10, 10), (20, 10), (30, 10)]
    # Two minutes at most; a tail under five seconds is left out.
    assert sum(s for _, s in wholevideo.plan(600)) == 120
    with pytest.raises(ValueError, match="at least 20 seconds"):
        wholevideo.plan(19.9)


def test_studio_must_be_loopback():
    with pytest.raises(ValueError, match="loopback"):
        wholevideo.Studio("http://example.com:8797")


def test_join_keeps_every_take_and_its_sound(tmp_path):
    takes = []
    for index, color in enumerate(("red", "blue")):
        path = tmp_path / f"take-{index}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color={color}:s=128x72:r=24:d=2",
                "-f",
                "lavfi",
                "-i",
                "sine=f=440:d=2",
                "-shortest",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
        )
        takes.append(path)
    wholevideo.join(takes, tmp_path / "whole.mp4")
    duration = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(tmp_path / "whole.mp4"),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert abs(float(duration) - 4) < 0.1


def test_restyle_routes_validate_and_need_klein(tmp_path):
    from fastapi.testclient import TestClient

    from aipg_cinema import app

    moss = TestClient(app.create_app(tmp_path / "a"), base_url="http://localhost")
    body = {"request_id": "a" * 32, "source_id": "b" * 32, "look": "Watercolor."}
    assert moss.post("/api/restyles", json=body).status_code == 409
    klein = TestClient(
        app.create_app(tmp_path / "b", look_engine="klein"), base_url="http://localhost"
    )
    assert klein.post("/api/restyles", json=body).status_code == 404  # no such source
    assert klein.post("/api/restyles", json={**body, "extra": 1}).status_code == 422
    assert klein.get("/api/restyles/" + "c" * 32).status_code == 404
    assert klein.get("/api/restyles/not-an-id").status_code == 404
