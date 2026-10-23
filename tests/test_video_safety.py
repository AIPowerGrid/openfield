import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from aipg_cinema import app, reshoot
from aipg_cinema.contracts import TakeRequest


def test_unfinished_take_settings_are_readable_without_provider_calls_or_secrets(
    tmp_path, monkeypatch
):
    request = TakeRequest(
        request_id="a" * 32,
        mode="text",
        prompt="An original paper boat",
        seed=2**63 - 1,
    )
    job = tmp_path / "jobs" / request.request_id
    (job / "render").mkdir(parents=True)
    (job / "request.json").write_text(request.model_dump_json())
    state = {"job_id": "private-provider-id", "token": "synthetic-private-token"}
    (job / "render" / "job.json").write_text(json.dumps(state))

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Reading settings must not call a provider or dispatch work."
        )

    monkeypatch.setattr(app, "sdk_client", forbidden)
    monkeypatch.setattr(app.subprocess, "Popen", forbidden)
    client = TestClient(app.create_app(tmp_path), base_url="http://localhost")
    response = client.get(f"/api/jobs/{request.request_id}/settings")
    assert response.status_code == 200
    assert response.json()["seed"] == 2**63 - 1
    assert response.json()["prompt"] == request.prompt
    assert "private-provider-id" not in response.text
    assert "synthetic-private-token" not in response.text
    assert not (job / "render" / "reshoot.mp4").exists()
    assert (job / "request.json").read_text() == request.model_dump_json()


@pytest.mark.parametrize(
    "content",
    [
        b"#EXTM3U\nhttp://127.0.0.1/private.mp4",
        b"ffconcat version 1.0\nfile '/other-account/private.mp4'",
        b"<MPD>remote manifest</MPD>",
        b"not a movie",
    ],
)
def test_playlists_and_noncontainers_are_rejected_before_any_decoder(
    tmp_path, monkeypatch, content
):
    source = tmp_path / "deceptive.mp4"
    source.write_bytes(content)

    def forbidden(*args, **kwargs):
        raise AssertionError("A playlist must not reach a decoder.")

    monkeypatch.setattr(reshoot.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="playlist"):
        reshoot.probe(source)


@pytest.mark.parametrize(
    "header,fmt",
    [
        (b"\x00\x00\x00\x18ftypisom", "mov"),
        (b"\x00\x00\x00\x18moovxxxx", "mov"),
        (b"\x1aE\xdf\xa3container", "matroska"),
        (b"OggScontainer", "ogg"),
    ],
)
def test_container_selection_forces_file_only_demuxing(tmp_path, header, fmt):
    source = tmp_path / "arbitrary-extension.upload"
    source.write_bytes(header)
    args = reshoot.video_input(source)
    assert args[args.index("-protocol_whitelist") + 1] == "file"
    assert args[args.index("-f") + 1] == fmt
    assert args[-1] == str(source.resolve())
    if fmt == "mov":
        assert args[args.index("-enable_drefs") + 1] == "0"
        assert args[args.index("-use_absolute_path") + 1] == "0"


def test_video_metadata_output_timeout_allocation_and_environment_are_bounded(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypisom")

    def oversized(command, **kwargs):
        assert kwargs["timeout"] == 30
        assert set(kwargs["env"]) == {"PATH"}
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert command[command.index("-max_alloc") + 1] == "67108864"
        kwargs["stdout"].write(b"x" * 65537)

    monkeypatch.setattr(reshoot.subprocess, "run", oversized)
    with pytest.raises(ValueError, match="metadata"):
        reshoot.probe(source)


def test_playlist_upload_cleans_up_and_never_fetches_a_referenced_file(
    tmp_path, monkeypatch
):
    web = TestClient(app.create_app(tmp_path), base_url="http://localhost")

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "No decoder or network fetch is permitted for this upload."
        )

    monkeypatch.setattr(reshoot.subprocess, "run", forbidden)
    response = web.post(
        "/api/sources",
        files={"file": ("video.mp4", b"#EXTM3U\nfile:///another-account/private.mp4")},
    )
    assert response.status_code == 400
    assert not list((tmp_path / "sources").iterdir())


def test_video_inspection_timeout_is_a_clean_upload_error(tmp_path, monkeypatch):
    web = TestClient(app.create_app(tmp_path), base_url="http://localhost")

    def timeout(path):
        raise subprocess.TimeoutExpired("ffprobe", 30)

    monkeypatch.setattr(app, "probe", timeout)
    response = web.post("/api/sources", files={"file": ("video.mp4", b"fixture")})
    assert response.status_code == 400
    assert not list((tmp_path / "sources").iterdir())
