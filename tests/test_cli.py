import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from comfy_sdk.workflows import WorkflowFactory
from PIL import Image

from aipg_cinema import cli, reshoot


@pytest.fixture
def workflow(tmp_path):
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps({"9": {"class_type": "SaveVideo", "inputs": {}}}))
    return path


@pytest.fixture
def client(monkeypatch):
    calls = []

    class Video:
        name = "video/demo.mp4"
        content_type = "video/mp4"

        def to_file(self, path):
            path.write_bytes(b"test output, not a generated clip")

    class Job:
        id = "job-test"
        status = "succeeded"

        def wait(self, timeout):
            calls.append("wait")

        def get_outputs(self, node_id):
            assert node_id == "9"
            return [Video()]

    class Client:
        workflows = WorkflowFactory()
        jobs = SimpleNamespace(get=lambda job_id: calls.append("get") or Job())

        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, graph, *, idempotency_key):
            calls.append("submit")
            assert len(idempotency_key) == 36
            return Job()

    monkeypatch.setattr(cli, "Comfy", Client)
    monkeypatch.delenv("COMFY_BASE_URL", raising=False)
    return calls


def test_offline_check_uses_real_sdk_workflow_shape(workflow, capsys):
    graph = cli.load_workflow(workflow, "9")
    assert WorkflowFactory().from_json(graph).json == graph
    assert cli.main(["check", str(workflow), "--output-node", "9"]) == 0
    assert "No job sent" in capsys.readouterr().out


def test_canvas_format_rejected(tmp_path):
    path = tmp_path / "canvas.json"
    path.write_text('{"nodes": []}')
    with pytest.raises(ValueError, match="API-format"):
        cli.load_workflow(path, "9")


def test_missing_output_rejected(workflow):
    with pytest.raises(ValueError, match="Output node"):
        cli.load_workflow(workflow, "missing")


def test_render_requires_explicit_execution(workflow, tmp_path, client):
    assert (
        cli.main(
            [
                "render",
                str(workflow),
                "--output-node",
                "9",
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )
        == 1
    )
    assert client == []


def test_reshoot_requires_explicit_execution_before_reading_or_uploading(
    tmp_path, client
):
    directory = tmp_path / "run"
    assert (
        cli.main(
            [
                "reshoot",
                str(tmp_path / "absent.mp4"),
                "--model",
                "h3",
                "--prompt",
                "A blue toy car",
                "--run-dir",
                str(directory),
            ]
        )
        == 1
    )
    assert client == []
    assert not directory.exists()


def test_invalid_motion_control_stops_before_reading_or_uploading(tmp_path, client):
    directory = tmp_path / "run"
    assert (
        cli.main(
            [
                "reshoot",
                str(tmp_path / "absent.mp4"),
                "--model",
                "ltx25",
                "--prompt",
                "A brass pendulum",
                "--motion-strength",
                "nan",
                "--run-dir",
                str(directory),
                "--execute",
            ]
        )
        == 1
    )
    assert client == []
    assert not directory.exists()


def test_closing_image_requires_opening_before_reading_or_uploading(tmp_path, client):
    directory = tmp_path / "run"
    assert (
        cli.main(
            [
                "reshoot",
                str(tmp_path / "absent.mp4"),
                "--model",
                "ltx25",
                "--prompt",
                "A forest waterfall",
                "--closing-frame",
                str(tmp_path / "end.png"),
                "--run-dir",
                str(directory),
                "--execute",
            ]
        )
        == 1
    )
    assert client == []
    assert not directory.exists()


def test_cli_binds_distinct_closing_asset_and_records_its_settings(
    tmp_path, client, monkeypatch
):
    opening, closing = tmp_path / "start.png", tmp_path / "end.png"
    Image.new("RGB", (96, 56), "red").save(opening)
    Image.new("RGB", (96, 56), "blue").save(closing)
    directory = tmp_path / "run"

    def prepare(source, folder, **options):
        path = folder / "source.mp4"
        path.write_bytes(b"fake video fixture")
        return path

    monkeypatch.setattr(reshoot, "prepare_source", prepare)
    monkeypatch.setattr(
        cli.Comfy,
        "assets",
        SimpleNamespace(from_file=lambda path: "uploaded:" + Path(path).name),
        raising=False,
    )
    captured = []
    monkeypatch.setattr(
        cli,
        "submit_and_collect",
        lambda client, workflow, folder, node, **extra: captured.append(
            (workflow.json, extra)
        ),
    )
    assert (
        cli.main(
            [
                "reshoot",
                str(tmp_path / "source.mp4"),
                "--model",
                "ltx25",
                "--prompt",
                "A forest waterfall",
                "--look-frame",
                str(opening),
                "--closing-frame",
                str(closing),
                "--run-dir",
                str(directory),
                "--execute",
            ]
        )
        == 0
    )
    workflow, state = captured[0]
    assert workflow["look"]["inputs"]["image"] == "uploaded:look.png"
    assert workflow["closing"]["inputs"]["image"] == "uploaded:closing.png"
    assert state["closing_frame"] == "closing.png"
    assert state["closing_frame_index"] == 120
    assert state["closing_strength"] == 0.7
    saved = json.loads((directory / "workflow.json").read_text())
    assert saved["closing"]["inputs"]["image"] == "closing.png"
    assert "uploaded:" not in (directory / "workflow.json").read_text()


def test_render_and_resume_never_resubmit(workflow, tmp_path, client, monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: 1000.0)
    directory = tmp_path / "run"
    command = [
        "render",
        str(workflow),
        "--output-node",
        "9",
        "--run-dir",
        str(directory),
        "--execute",
    ]
    assert cli.main(command) == 0
    state = json.loads((directory / "job.json").read_text())
    assert state["job_id"] == "job-test"
    assert state["cost_usd"] is None
    assert (directory / "clip-01.mp4").is_file()
    assert cli.main(command) == 1
    monkeypatch.setattr(cli.time, "time", lambda: 2000.0)
    assert cli.main(["resume", str(directory)]) == 0
    assert json.loads((directory / "job.json").read_text())["elapsed_seconds"] == 0
    assert client.count("submit") == 1
    assert client.count("get") == 1


def test_ambiguous_submission_requires_manual_lookup(tmp_path, client):
    (tmp_path / "job.json").write_text('{"job_id": null}')
    assert cli.main(["resume", str(tmp_path)]) == 1
    assert client == []


def test_fasth3_cannot_silently_use_unqualified_cloud_catalog(tmp_path, client):
    directory = tmp_path / "run"
    assert (
        cli.main(
            [
                "reshoot",
                str(tmp_path / "absent.mp4"),
                "--model",
                "fasth3",
                "--prompt",
                "A brass pendulum",
                "--run-dir",
                str(directory),
                "--execute",
            ]
        )
        == 1
    )
    assert client == []
    assert not directory.exists()


def test_submit_timeout_persists_state_without_retry(
    workflow, tmp_path, client, monkeypatch
):
    def lose_response(*args, **kwargs):
        client.append("submit")
        raise TimeoutError("response lost")

    monkeypatch.setattr(cli.Comfy, "submit", lose_response)
    directory = tmp_path / "run"
    command = [
        "render",
        str(workflow),
        "--output-node",
        "9",
        "--run-dir",
        str(directory),
        "--execute",
    ]
    assert cli.main(command) == 1
    state = json.loads((directory / "job.json").read_text())
    assert state["job_id"] is None
    assert state["idempotency_key"]
    assert cli.main(command) == 1
    assert cli.main(["resume", str(directory)]) == 1
    assert client == ["submit"]


def test_observation_failure_explains_recovery_without_replacement(
    workflow, tmp_path, client, monkeypatch, capsys
):
    original_collect = cli.collect

    def lost_observation(*args):
        raise OSError("HTTP 503")

    monkeypatch.setattr(cli, "collect", lost_observation)
    directory = tmp_path / "run"
    assert (
        cli.main(
            [
                "render",
                str(workflow),
                "--output-node",
                "9",
                "--run-dir",
                str(directory),
                "--execute",
            ]
        )
        == 1
    )
    assert "Recover without a new render" in capsys.readouterr().err
    monkeypatch.setattr(cli, "collect", original_collect)
    assert cli.main(["resume", str(directory)]) == 0
    assert client.count("submit") == 1


@pytest.mark.parametrize("url", ["http://127.0.0.1:8188", "https://other.invalid"])
def test_existing_infrastructure_cannot_be_targeted(url, monkeypatch):
    monkeypatch.setenv("COMFY_BASE_URL", url)
    with pytest.raises(ValueError, match="platform proof only targets"):
        cli.cloud_only()


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.invalid:8189",
        "https://cloud.comfy.org",
        "http://localhost",
        "http://user:password@127.0.0.1:8189",
        "http://127.0.0.1:8189/path",
        "http://127.0.0.1:8189?key=secret",
        "http://127.0.0.1:99999",
    ],
)
def test_self_hosted_requires_explicit_loopback_proxy(url, monkeypatch, client):
    monkeypatch.setenv("COMFY_BASE_URL", url)
    with pytest.raises(ValueError, match="loopback"), cli.sdk_client("self-hosted"):
        pass
    assert client == []


@pytest.mark.parametrize(
    "backend,scope",
    [("cloud", "primary"), ("self-hosted", "primary"), ("self-hosted", "look")],
)
def test_sdk_allows_bounded_longer_media_transfers(backend, scope, monkeypatch, client):
    captured = []
    monkeypatch.setattr(cli, "Comfy", lambda **kwargs: captured.append(kwargs))
    cli.configured_client(
        backend,
        "http://127.0.0.1:18291"
        if backend == "self-hosted"
        else "https://cloud.comfy.org",
        scope,
    )
    assert captured[0]["timeout"] == 120.0


def test_status_timeout_does_not_change_media_transfer_timeout(monkeypatch, client):
    captured = []
    monkeypatch.setattr(
        cli.Comfy, "__init__", lambda self, **kwargs: captured.append(kwargs)
    )
    with cli.sdk_client("cloud", timeout=5.0):
        pass
    with cli.sdk_client("cloud"):
        pass
    assert [item["timeout"] for item in captured] == [5.0, 120.0]


def test_self_hosted_does_not_forward_cloud_key_and_restores_environment(
    monkeypatch, client
):
    monkeypatch.setenv("COMFY_API_KEY", "cloud-test-key")
    monkeypatch.setenv("COMFY_LOCAL_TOKEN", "local-test-token")
    monkeypatch.setenv("COMFY_BASE_URL", "https://cloud.comfy.org")
    captured = []

    def initialize(self, **kwargs):
        captured.append(
            (
                cli.os.environ.get("COMFY_API_KEY"),
                kwargs["api_key"],
                cli.os.environ["COMFY_BASE_URL"],
            )
        )

    monkeypatch.setattr(cli.Comfy, "__init__", initialize)
    with (
        pytest.raises(RuntimeError),
        cli.sdk_client("self-hosted", "http://127.0.0.1:18291"),
    ):
        assert cli.os.environ["COMFY_BASE_URL"] == "https://cloud.comfy.org"
        raise RuntimeError("test cleanup")
    assert captured == [(None, "local-test-token", "http://127.0.0.1:18291")]
    assert cli.os.environ["COMFY_API_KEY"] == "cloud-test-key"
    assert cli.os.environ["COMFY_BASE_URL"] == "https://cloud.comfy.org"


def test_resume_cannot_compete_with_existing_observer(tmp_path, client):
    from filelock import FileLock

    (tmp_path / "job.json").write_text('{"job_id": "existing-job"}')
    with FileLock(tmp_path / ".observer.lock"):
        assert cli.observer_active(tmp_path)
        assert cli.main(["resume", str(tmp_path)]) == 1
    assert not cli.observer_active(tmp_path)
    assert client == []


def test_self_hosted_render_and_resume_pin_the_same_proxy(
    workflow, tmp_path, monkeypatch, client
):
    monkeypatch.setenv("COMFY_BASE_URL", "http://127.0.0.1:18291")
    directory = tmp_path / "local-run"
    assert (
        cli.main(
            [
                "render",
                str(workflow),
                "--output-node",
                "9",
                "--run-dir",
                str(directory),
                "--backend",
                "self-hosted",
                "--execute",
            ]
        )
        == 0
    )
    state = json.loads((directory / "job.json").read_text())
    assert state["backend"] == "self-hosted"
    assert state["base_url"] == "http://127.0.0.1:18291"
    monkeypatch.setenv("COMFY_BASE_URL", "https://cloud.comfy.org")
    assert cli.main(["resume", str(directory)]) == 0
    assert client.count("submit") == 1
