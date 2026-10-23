import json
import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from aipg_cinema import hosted_server
from aipg_cinema.hosted_server import StagingConfig, service_key, staging_app


@pytest.fixture
def config(tmp_path):
    key = tmp_path / "service-key"
    key.write_text("test-only-service-key\n")
    key.chmod(0o600)
    return StagingConfig(
        tmp_path / "state",
        key,
        "https://studio.example",
        "public-google-client",
        "a" * 64,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"origin": "http://studio.example"},
        {"origin": "https://studio.example/"},
        {"origin": "https://studio.example:443"},
        {"origin": "https://user@studio.example"},
        {"origin": "https://studio..example"},
        {"origin": "https://-studio.example"},
        {"google_client_id": "line\nbreak"},
        {"release": "not-a-release"},
        {"port": 443},
        {"port": True},
        {"directory": hosted_server.Path("relative-state")},
        {"key_file": hosted_server.Path("relative-key")},
    ],
)
def test_invalid_launch_config_cannot_create_storage(config, change):
    with pytest.raises(ValueError):
        replace(config, **change)
    assert not config.directory.exists()


def test_credential_is_regular_private_and_bounded(config, tmp_path):
    assert service_key(config.key_file) == "test-only-service-key"
    config.key_file.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        service_key(config.key_file)
    config.key_file.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(config.key_file)
    with pytest.raises(OSError):
        service_key(link)
    hardlink = tmp_path / "hardlink"
    os.link(config.key_file, hardlink)
    with pytest.raises(ValueError, match="private"):
        service_key(config.key_file)
    hardlink.unlink()
    config.key_file.write_bytes(b"a" * 32769)
    with pytest.raises(ValueError, match="private"):
        service_key(config.key_file)
    config.key_file.write_bytes(b"not ascii \xff")
    with pytest.raises(UnicodeError):
        service_key(config.key_file)
    config.key_file.write_text("internal whitespace")
    with pytest.raises(ValueError):
        service_key(config.key_file)


def test_managed_staging_health_is_not_a_public_launch_claim(config, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Health probes must not call Core or model providers.")

    monkeypatch.setattr(hosted_server.CoreAccounts, "_call", forbidden)
    with staging_app(config) as app, TestClient(app, base_url=config.origin) as client:
        live = client.get("/health/live")
        assert live.status_code == 200
        assert live.json() == {"status": "alive", "mode": "staging", "rendering": False}
        ready = client.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json() == {
            "status": "not_ready",
            "code": "billed_execution_not_enabled",
        }
        assert not live.headers.get("set-cookie")
        assert ready.headers["cache-control"] == "no-store"
        assert client.get("/api/projects").status_code == 401
        assert client.get("/signin").status_code == 200
        assert (
            client.get(
                "/health/live", headers={"host": "untrusted.example"}
            ).status_code
            == 400
        )
        assert not list((config.directory / "workspaces").iterdir())
    assert config.directory.stat().st_mode & 0o777 == 0o700
    assert (config.directory / "auth/sessions.sqlite3").stat().st_mode & 0o777 == 0o600


def test_managed_writer_lease_rejects_overlap_and_releases_on_failure(config):
    with staging_app(config):
        before = (config.directory / "auth/sessions.sqlite3").read_bytes()
        with pytest.raises(ValueError, match="managed writer"), staging_app(config):
            pytest.fail("A second writer must not enter.")
        assert (config.directory / "auth/sessions.sqlite3").read_bytes() == before
    with pytest.raises(RuntimeError, match="test exit"), staging_app(config):
        raise RuntimeError("test exit")
    with staging_app(config):
        pass


def arguments(config):
    return [
        "--state-dir",
        str(config.directory),
        "--service-key-file",
        str(config.key_file),
        "--origin",
        config.origin,
        "--google-client-id",
        config.google_client_id,
        "--release-sha256",
        config.release,
    ]


def test_check_initializes_private_storage_without_serving_or_printing_key(
    config, monkeypatch, capsys
):
    monkeypatch.setattr(
        hosted_server.uvicorn,
        "run",
        lambda *a, **kw: pytest.fail("Check must not bind a listener."),
    )
    hosted_server.main([*arguments(config), "--check"])
    output = capsys.readouterr()
    assert "test-only-service-key" not in output.out + output.err
    assert json.loads(output.out) == {
        "status": "checked",
        "mode": "staging",
        "release_sha256": config.release,
        "rendering": False,
    }
    with staging_app(config):
        pass


def test_server_is_loopback_single_process_and_holds_lease(config, monkeypatch):
    def serve(app, **kwargs):
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["workers"] == 1
        assert kwargs["proxy_headers"] is False
        assert kwargs["access_log"] is False
        assert kwargs["server_header"] is False
        assert kwargs["limit_concurrency"] == 64
        with pytest.raises(ValueError, match="managed writer"), staging_app(config):
            pytest.fail("The lease must cover the server lifetime.")

    monkeypatch.setattr(hosted_server.uvicorn, "run", serve)
    hosted_server.main(arguments(config))


def test_startup_failure_does_not_echo_private_details(config, capsys):
    config.key_file.write_text("private credential with whitespace")
    with pytest.raises(SystemExit) as error:
        hosted_server.main([*arguments(config), "--check"])
    assert error.value.code == 1
    output = capsys.readouterr()
    assert "private credential with whitespace" not in output.out + output.err
    assert str(config.directory) not in output.out + output.err
    assert "Staging startup rejected" in output.err
    assert not (config.directory / "auth").exists()
    config.key_file.write_text("test-only-service-key")
    with staging_app(config):
        pass


def test_credential_pipe_cannot_block_startup(config, tmp_path):
    pipe = tmp_path / "pipe"
    os.mkfifo(pipe, 0o600)
    with pytest.raises(ValueError, match="private"):
        service_key(pipe)


@pytest.mark.parametrize("symlink", [False, True])
def test_existing_unsafe_state_is_not_repaired_or_overwritten(
    config, tmp_path, symlink
):
    if symlink:
        target = tmp_path / "other-data"
        target.mkdir(mode=0o700)
        config.directory.symlink_to(target)
    else:
        config.directory.mkdir(mode=0o755)
        target = config.directory
    sentinel = target / "existing-data"
    sentinel.write_bytes(b"keep this")
    before = target.stat().st_mode
    with pytest.raises(ValueError, match="private"), staging_app(config):
        pytest.fail("An unsafe state root must not be used.")
    assert sentinel.read_bytes() == b"keep this"
    assert target.stat().st_mode == before
    assert not (target / "auth").exists()


def test_launch_has_no_remote_bind_or_rendering_bypass_flags(config):
    for flags in (("--host", "0.0.0.0"), ("--enable-rendering",)):
        with pytest.raises(SystemExit) as error:
            hosted_server.main([*arguments(config), *flags])
        assert error.value.code == 2
    assert not config.directory.exists()
