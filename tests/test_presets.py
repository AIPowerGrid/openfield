import shutil
import subprocess
from pathlib import Path

import pytest

from aipg_cinema import presets


def test_presets_are_named_versioned_and_unique():
    ids = [p.id for p in presets.PRESETS]
    assert len(ids) == len(set(ids))
    assert sum(p.kind == "camera" for p in presets.PRESETS) == 8
    for preset in presets.PRESETS:
        assert preset.version >= 1 and 24 <= preset.trim_end <= 120
        if preset.kind == "camera":
            assert "exact shape" in preset.motion


def test_only_qualified_presets_with_previews_are_offered(tmp_path, monkeypatch):
    monkeypatch.setattr(presets, "PREVIEWS", tmp_path)
    for preset in presets.available():
        assert preset.qualified and preset.preview.is_file()
    assert presets.available() == []  # no previews in an empty directory


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        presets.by_id("barrel-roll")


def test_app_offers_only_reviewed_presets_and_serves_previews(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aipg_cinema import app
    from aipg_cinema.project import Shot

    previews = tmp_path / "previews"
    previews.mkdir()
    (previews / "orbit.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    monkeypatch.setattr(presets, "PREVIEWS", previews)
    qualified = [
        p.model_copy(update={"qualified": p.id in ("orbit", "fpv")})
        for p in presets.PRESETS
    ]
    monkeypatch.setattr(presets, "PRESETS", qualified)
    client = TestClient(app.create_app(tmp_path / "web"), base_url="http://localhost")
    offered = client.get("/api/config").json()["presets"]
    # fpv is qualified but has no preview, so it is not offered.
    assert [p["id"] for p in offered] == ["orbit"]
    assert offered[0]["preview_url"] == "/preset-previews/orbit.mp4"
    assert client.get(offered[0]["preview_url"]).status_code == 200
    assert Shot(camera="orbit@1").camera == "orbit@1"
    with pytest.raises(ValueError):
        Shot(camera="Orbit!")


def test_native_review_qualified_two_camera_moves_with_bundled_previews():
    assert [p.id for p in presets.available() if p.kind == "camera"] == [
        "push-in",
        "pull-back",
    ]
    for preset in presets.PRESETS:
        assert preset.note, preset.id
        if not preset.qualified:
            assert preset.note.startswith("Rejected")
            assert not preset.preview.exists()
        else:
            assert preset.preview.stat().st_size < 150_000


def test_recommended_trims_stay_gentle():
    # Camera moves stay gentle; opt-in effects need their full arc.
    for preset in presets.available():
        assert preset.trim_end <= (60 if preset.kind == "camera" else 120), preset.id


def test_effect_review_qualified_three_opt_in_effects():
    effects = [p.id for p in presets.available() if p.kind == "effect"]
    assert effects == ["wireframe", "garden-bloom", "freezing"]
    rejected = [p.id for p in presets.PRESETS if p.kind == "effect" and not p.qualified]
    assert rejected == [
        "earth-zoom-out",
        "turning-metal",
        "point-cloud",
        "disintegration",
        "smoke-reveal",
    ]


def test_shipped_previews_are_not_git_ignored():
    # Presets and templates without a preview are hidden, so ignored loops
    # would silently empty the picker and gallery in a fresh clone.
    root = Path(__file__).resolve().parents[1]
    if shutil.which("git") is None or not (root / ".git").exists():
        pytest.skip("not a git checkout")
    package = root / "src" / "aipg_cinema"
    previews = (
        sorted(package.glob("presets/*.mp4"))
        + sorted(package.glob("templates/*.mp4"))
        + sorted(package.glob("showcase/*.mp4"))
        + sorted(package.glob("styles/*.mp4"))
        + sorted(package.glob("styles/examples/*.mp4"))
    )
    assert previews
    ignored = subprocess.run(
        ["git", "check-ignore", *map(str, previews)],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert ignored.stdout == ""
