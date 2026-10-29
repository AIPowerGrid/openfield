import json
import subprocess

import httpx
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


def test_plan_message_names_both_limits_and_what_to_do():
    with pytest.raises(ValueError) as error:
        wholevideo.plan(12.0)
    assert "at least 20 seconds" in str(error.value)
    assert "120" in str(error.value) and "12.0 s" in str(error.value)
    assert "Trim or pick a longer clip." in str(error.value)
    assert (wholevideo.MIN_SECONDS, wholevideo.MAX_SECONDS, wholevideo.WINDOW) == (
        20,
        120,
        10,
    )


def test_capacity_check_counts_takes_and_boundary_looks():
    windows = wholevideo.plan(62.4)  # six takes, seven looks
    wholevideo.check_capacity(
        windows, {"max_renders": 8, "renders_used": 2, "max_looks": 7, "looks_used": 0}
    )
    windows = wholevideo.plan(65)  # seven takes, eight looks
    with pytest.raises(ValueError) as error:
        wholevideo.check_capacity(
            windows,
            {"max_renders": 12, "renders_used": 6, "max_looks": 20, "looks_used": 8},
        )
    assert str(error.value) == (
        "This clip needs 7 takes and 8 looks but the session allows 6 more takes "
        "and 12 more looks. Restart with --max-renders 13 --max-looks 16."
    )
    with pytest.raises(ValueError, match="allows 0 more takes"):
        wholevideo.check_capacity(
            windows, {"max_renders": 6, "renders_used": 9, "max_looks": 7}
        )


def test_execute_checks_the_limits_before_submitting_anything(tmp_path):
    calls = []

    class Studio:
        def call(self, method, path, **kwargs):
            calls.append((method, path))
            data = {
                "/api/sources/" + "b" * 32 + "/info": {"duration": 65.0},
                "/api/config": {
                    "max_renders": 6,
                    "renders_used": 0,
                    "max_looks": 12,
                    "looks_used": 0,
                },
            }[path]
            return type("R", (), {"json": lambda self: data})()

    (tmp_path / "request.json").write_text(
        json.dumps(
            {
                "source_id": "b" * 32,
                "look": "Watercolor.",
                "motion": "",
                "seed": 1,
                "frame_format": "landscape",
            }
        )
    )
    with pytest.raises(ValueError, match="needs 7 takes and 8 looks"):
        wholevideo.Run(tmp_path, Studio()).execute()
    assert all(method == "GET" for method, _ in calls)
    assert not (tmp_path / "state.json").exists()


def test_a_second_orchestrator_for_the_same_folder_exits_without_touching_state(
    tmp_path, monkeypatch
):
    from filelock import FileLock

    folder = tmp_path / "r"
    folder.mkdir()
    (folder / "request.json").write_text("{}")
    monkeypatch.setattr(
        "sys.argv", ["wholevideo", str(folder), "--studio", "http://127.0.0.1:8793"]
    )
    with (
        FileLock(folder / ".observer.lock", timeout=0),
        pytest.raises(SystemExit) as error,
    ):
        wholevideo.main()
    assert error.value.code == 2
    assert not (folder / "state.json").exists()
    from aipg_cinema import replace

    monkeypatch.setattr(
        "sys.argv", ["replace", str(folder), "--studio", "http://127.0.0.1:8793"]
    )
    with (
        FileLock(folder / ".observer.lock", timeout=0),
        pytest.raises(SystemExit) as error,
    ):
        replace.main()
    assert error.value.code == 2
    assert not (folder / "state.json").exists()


def test_studio_errors_carry_the_detail_without_a_status_suffix(monkeypatch):
    monkeypatch.setattr(
        wholevideo.httpx,
        "request",
        lambda method, url, **kwargs: httpx.Response(
            503, json={"detail": "The look engine is offline."}
        ),
    )
    with pytest.raises(RuntimeError) as error:
        wholevideo.Studio("http://127.0.0.1:8797").call("POST", "/api/jobs")
    assert str(error.value) == "The look engine is offline."
