import json
import shutil
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from comfy_sdk.workflows import WorkflowFactory
from pydantic import ValidationError
from test_app import complete_look, look_request, take, upload, upload_look

from aipg_cinema import cli, generation, reshoot, speech
from aipg_cinema.contracts import TakeRequest
from aipg_cinema.reshoot import video_format
from aipg_cinema.sequence import inspect


@pytest.mark.parametrize("framing", ["portrait", "square", "landscape"])
@pytest.mark.parametrize("opening", [False, True])
@pytest.mark.parametrize("source_video", [False, True])
def test_speech_graph_preserves_tested_sampler_and_fixed_audio(
    framing, opening, source_video
):
    graph = speech.graph(
        "An original character speaking",
        77,
        frame_format=framing,
        opening=opening,
        source_video=source_video,
    )
    assert WorkflowFactory().from_json(graph).json == graph
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph
    assert graph["sampler"]["inputs"]["sampler_name"] == "euler_ancestral_cfg_pp"
    assert graph["sigmas"]["inputs"]["sigmas"].count(",") == 8
    assert graph["guider"]["inputs"]["cfg"] == 1
    assert graph["audio-mask"]["inputs"]["value"] == 0
    assert graph["fixed-audio"]["inputs"]["samples"] == ["encode-audio", 0]
    assert graph["av"]["inputs"]["audio_latent"] == ["fixed-audio", 0]
    assert graph["video"]["inputs"]["audio"] == ["source-audio", 0]
    assert sum(n["class_type"] == "SamplerCustomAdvanced" for n in graph.values()) == 1
    assert not any(n["class_type"] == "LTXVLatentUpsampler" for n in graph.values())
    spec = video_format(framing)
    assert (
        graph["empty"]["inputs"]["width"],
        graph["empty"]["inputs"]["height"],
        graph["empty"]["inputs"]["length"],
    ) == (spec.width, spec.height, 121)
    if opening:
        assert graph["look-preprocess"]["inputs"]["img_compression"] == 35
        assert graph["look-anchor"]["inputs"]["strength"] == (
            0.75 if source_video else 1
        )
    if source_video:
        assert graph["source-window"]["inputs"]["length"] == 121
        assert graph["guide"]["inputs"]["strength"] == 0.85
        assert graph["edges"]["inputs"]["low_threshold"] == 0.35
        assert graph["edges"]["inputs"]["high_threshold"] == 0.75
    else:
        assert "source" not in graph


def test_profiles_are_explicit_and_old_saved_takes_keep_two_pass():
    audio = {
        "request_id": "a" * 32,
        "mode": "audio",
        "audio_id": "b" * 32,
        "prompt": "A performer",
    }
    assert TakeRequest.model_validate(audio).render_profile == "two-pass"
    assert "refine" in generation.graph("A performer", mode="audio")
    graph = generation.graph(
        "A performer", mode="audio", render_profile="single-pass-audio"
    )
    assert "refine" not in graph and "fixed-audio" in graph
    for changes in (
        {"mode": "text", "audio_id": None},
        {"closing_id": "c" * 32},
        {"render_profile": "mystery"},
    ):
        with pytest.raises(ValidationError):
            TakeRequest.model_validate(
                {**audio, "render_profile": "single-pass-audio", **changes}
            )
    for options in (
        {"mode": "text", "render_profile": "single-pass-audio"},
        {"mode": "audio", "render_profile": "single-pass-audio", "closing": True},
        {"render_profile": "mystery"},
    ):
        with pytest.raises(ValueError):
            generation.graph("A performer", **options)


@pytest.mark.parametrize("framing", ["portrait", "square", "landscape"])
@pytest.mark.parametrize("source_video", [False, True])
def test_optional_ending_anchor_uses_final_frame_and_preserves_audio(
    framing, source_video
):
    graph = speech.graph(
        "A performer",
        frame_format=framing,
        opening=True,
        closing=True,
        source_video=source_video,
    )
    assert WorkflowFactory().from_json(graph).json == graph
    guide = graph["closing-guide"]["inputs"]
    assert (guide["frame_idx"], guide["strength"]) == (120, 0.7)
    assert guide["image"] == ["closing-preprocess", 0]
    assert graph["closing-preprocess"]["inputs"]["img_compression"] == 35
    assert guide["latent"] == (["guide", 2] if source_video else ["look-anchor", 0])
    for key in ("guider", "crop"):
        assert graph[key]["inputs"]["positive"] == ["closing-guide", 0]
        assert graph[key]["inputs"]["negative"] == ["closing-guide", 1]
    assert graph["av"]["inputs"] == {
        "video_latent": ["closing-guide", 2],
        "audio_latent": ["fixed-audio", 0],
    }
    assert sum(n["class_type"] == "SamplerCustomAdvanced" for n in graph.values()) == 1
    assert "closing-guide" not in speech.graph("A performer", opening=True)
    with pytest.raises(ValueError, match="opening"):
        speech.graph("A performer", closing=True)
    if not source_video:
        assert (
            generation.graph(
                "A performer",
                mode="audio",
                frame_format=framing,
                opening=True,
                closing=True,
                render_profile="single-pass-audio",
            )
            == graph
        )


@pytest.mark.parametrize("profile", ["single-pass-audio", "two-pass"])
def test_reusing_uploaded_opening_snapshots_both_ends_and_freezes_request(
    local, monkeypatch, profile
):
    client, root, processes = local
    monkeypatch.setattr(generation, "audio_info", lambda path: {})
    image = upload_look(client)
    body = {
        **take(upload(client)),
        "look_id": image,
        "closing_id": image,
        "render_profile": profile,
    }
    assert client.post("/api/jobs", json=body).status_code == 200
    folder = root / "jobs" / body["request_id"]
    assert (folder / "look.png").read_bytes() == (folder / "closing.png").read_bytes()
    args = processes[-1].args
    assert args[args.index("--closing-frame") + 1] == str(folder / "closing.png")
    settings = client.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert settings["closing_reuses_opening"] is True
    assert (settings["closing_strength"], settings["closing_frame_index"]) == (0.7, 120)
    assert client.post("/api/jobs", json=body).status_code == 200
    assert (
        client.post("/api/jobs", json={**body, "closing_id": None}).status_code == 409
    )
    assert len(processes) == 1


def test_generated_opening_can_be_reused_without_bypassing_source_scope(moss):
    client, root, processes = moss
    source = upload(client)
    opening = look_request(source)
    assert client.post("/api/look-jobs", json=opening).status_code == 200
    complete_look(root, processes, opening)
    body = {
        **take(source),
        "look_id": opening["request_id"],
        "closing_id": opening["request_id"],
    }
    project = client.post(
        "/api/projects", json={"title": "Ending reuse", "frame_format": "landscape"}
    ).json()
    project["shots"][0]["draft"].update(
        mode="video",
        source_id=source,
        look_id=opening["request_id"],
        closing_id=opening["request_id"],
        frame_format="landscape",
    )
    saved = client.put(f"/api/projects/{project['id']}", json=project)
    assert saved.status_code == 200
    assert saved.json()["shots"][0]["draft"]["closing_id"] == opening["request_id"]
    other = upload(client)
    assert (
        client.post("/api/jobs", json={**body, "source_id": other}).status_code == 400
    )
    assert client.post("/api/jobs", json=body).status_code == 200
    settings = client.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert settings["closing_reuses_opening"] is True
    assert settings["closing_look"]["source_frame_index"] == 0
    assert settings["closing_frame_index"] == 120
    assert len(processes) == 2  # One existing look job, one take, no extra still.


def test_video_speech_profile_dispatch_settings_and_idempotency(local, monkeypatch):
    client, _root, processes = local
    source = upload(client)
    checked = []
    monkeypatch.setattr(
        generation, "audio_info", lambda path: checked.append(path) or {}
    )
    body = {
        **take(source),
        "render_profile": "single-pass-audio",
        "frame_format": "square",
    }
    assert client.post("/api/jobs", json=body).status_code == 200
    assert client.post("/api/jobs", json=body).status_code == 200
    assert len(processes) == 1
    arguments = processes[0].args
    assert arguments[arguments.index("--render-profile") + 1] == "single-pass-audio"
    assert checked and all(
        p.name == "source.mp4" and "windows" in str(p) for p in checked
    )
    settings = client.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert settings["audio_conditioned"] and not settings["spatial_refinement"]
    assert settings["export_resize"] == "lanczos-2x"
    assert (settings["native_width"], settings["native_height"]) == (640, 640)
    assert (settings["width"], settings["height"]) == (1280, 1280)
    assert (
        client.post(
            "/api/jobs", json={**body, "render_profile": "two-pass"}
        ).status_code
        == 409
    )
    assert len(processes) == 1


def test_silent_video_cannot_consume_speech_render_limit(local, monkeypatch):
    client, root, processes = local
    source = upload(client)

    def reject(path):
        raise ValueError("No source audio")

    monkeypatch.setattr(generation, "audio_info", reject)
    body = {**take(source), "render_profile": "single-pass-audio"}
    assert client.post("/api/jobs", json=body).status_code == 400
    assert not processes and not list((root / "jobs").iterdir())
    assert (
        client.post(
            "/api/jobs", json={**body, "render_profile": "two-pass"}
        ).status_code
        == 200
    )
    assert len(processes) == 1


@pytest.mark.parametrize("mode", ["audio", "video"])
@pytest.mark.parametrize("ending", [False, True])
def test_speech_cli_binds_audio_and_recovery_uses_frozen_profile(
    tmp_path, monkeypatch, mode, ending
):
    calls = []

    class Output:
        name, content_type = "video/fixture.mp4", "video/mp4"

        def to_file(self, path):
            path.write_bytes(b"synthetic video")

    class Job:
        id, status = "saved-speech-job", "succeeded"

        def wait(self, timeout):
            pass

        def get_outputs(self, node):
            assert node == "save"
            return [Output()]

    class Client:
        workflows = WorkflowFactory()
        assets = SimpleNamespace(from_file=lambda path: path)
        jobs = SimpleNamespace(get=lambda job_id: calls.append(job_id) or Job())

        def submit(self, workflow, **kwargs):
            assert workflow.json["source-audio"]["inputs"]["audio"].name == "source.wav"
            assert ("source" in workflow.json) == (mode == "video")
            assert ("closing-guide" in workflow.json) == ending
            if ending:
                assert workflow.json["closing"]["inputs"]["image"].name == "closing.png"
            calls.append("submit")
            return Job()

    @contextmanager
    def sdk(*args, **kwargs):
        yield Client()

    monkeypatch.setattr(cli, "sdk_client", sdk)

    def audio(source, folder, source_start=0):
        target = folder / "source.wav"
        target.write_bytes(b"synthetic fixed audio")
        return target

    monkeypatch.setattr(generation, "prepare_audio", audio)
    monkeypatch.setattr(
        reshoot,
        "prepare_look",
        lambda source, folder, closing=False, **kwargs: (
            folder / ("closing.png" if closing else "look.png")
        ),
    )
    monkeypatch.setattr(
        reshoot,
        "prepare_source",
        lambda source, folder, **kwargs: folder / "source.mp4",
    )

    def finish(folder, generated, **kwargs):
        assert kwargs == {"frame_format": "portrait"}
        target = folder / "reshoot.mp4"
        target.write_bytes(b"offline finished clip")
        return target

    monkeypatch.setattr(generation, "finish", finish)
    folder = tmp_path / mode
    command = (
        ["generate", "--mode", "audio", "--audio", str(tmp_path / "audio.wav")]
        if mode == "audio"
        else ["reshoot", str(tmp_path / "source.mp4"), "--model", "ltx25"]
    )
    command += [
        "--prompt",
        "A performer",
        "--format",
        "portrait",
        "--render-profile",
        "single-pass-audio",
        "--run-dir",
        str(folder),
        "--execute",
    ]
    if ending:
        command += [
            "--look-frame",
            str(tmp_path / "opening.png"),
            "--closing-frame",
            str(tmp_path / "opening.png"),
        ]
    assert cli.main(command) == 0
    state = json.loads((folder / "job.json").read_text())
    assert state["render_profile"] == "single-pass-audio"
    assert state["frame_format"] == "portrait"
    assert state["closing_frame"] == ("closing.png" if ending else None)
    assert state["closing_strength"] == (0.7 if ending else None)
    assert cli.main(command) == 1
    assert cli.main(["resume", str(folder)]) == 0
    assert calls == ["submit", "saved-speech-job"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_native_speech_export_resizes_offline_and_has_exact_sound_clocks(tmp_path):
    native = tmp_path / "native.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=640x640:r=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:sample_rate=48000",
            "-frames:v",
            "121",
            "-t",
            str(121 / 24),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-movie_timescale",
            "48000",
            "-video_track_timescale",
            "24000",
            str(native),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(native),
            "-map",
            "0:a:0",
            "-af",
            "apad=whole_len=242000,atrim=end_sample=242000",
            "-c:a",
            "pcm_s16le",
            str(tmp_path / "source.wav"),
        ],
        check=True,
    )
    output = generation.finish(tmp_path, native, frame_format="square")
    result = inspect(output, 1280, 1280, 120, audio_required=True)
    assert result["seconds"] == 5
    assert not (tmp_path / "reshoot.partial.mp4").exists()
    with pytest.raises(ValueError, match="incompatible dimensions"):
        generation.finish(tmp_path, native, frame_format="portrait")
