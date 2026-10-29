import subprocess
from pathlib import Path

import pytest

from aipg_cinema import styles


def test_styles_are_named_versioned_unique_and_generic():
    ids = [s.id for s in styles.STYLES]
    assert len(ids) == len(set(ids))
    for style in styles.STYLES:
        assert style.version >= 1 and style.name and style.blurb
        # Applied wording keeps the source's subjects and motion; it never
        # names an example's scene.
        assert style.look.endswith(styles.KEEP_LOOK)
        assert style.motion.endswith(styles.KEEP_MOTION)
        assert "crosswalk" not in style.look + style.motion
        assert len(style.look) < 4000 and len(style.motion) < 4000
        assert style.source


def test_only_qualified_styles_with_previews_are_offered(tmp_path, monkeypatch):
    monkeypatch.setattr(styles, "PREVIEWS", tmp_path)
    assert styles.available() == []
    (tmp_path / "anime.mp4").write_bytes(b"\x00")
    (tmp_path / "watercolor.mp4").write_bytes(b"\x00")
    assert styles.available() == []  # no bundled example clips yet
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "crosswalk.mp4").write_bytes(b"\x00")
    offered = [s.id for s in styles.available()]
    assert offered == ["anime"]  # watercolor's example clip is missing
    for style in styles.available():
        assert style.qualified and style.preview.is_file()


def test_unknown_style_is_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        styles.by_id("barrel-roll")


def test_bundled_styles_cover_eight_to_ten_reviewed_examples():
    offered = styles.available()
    assert 8 <= len(offered) <= 10
    for style in offered:
        assert style.poster.is_file() and style.example_clip.is_file()
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                str(style.preview),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert probe.stdout.strip() == "768,432"  # 16:9 split cards


def test_app_offers_styles_and_serves_their_previews(tmp_path):
    from fastapi.testclient import TestClient

    from aipg_cinema import app

    client = TestClient(app.create_app(tmp_path / "web"), base_url="http://localhost")
    offered = client.get("/api/config").json()["styles"]
    assert [s["id"] for s in offered] == [s.id for s in styles.available()]
    first = offered[0]
    assert first["look"] == styles.by_id(first["id"]).look
    assert client.get(first["example_url"]).status_code == 200
    assert client.get(first["preview_url"]).status_code == 200
    assert client.get(first["poster_url"]).status_code == 200
    script = client.get("/styles.js")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")


def test_style_picker_replaces_the_look_dropdown():
    from aipg_cinema import app

    html = Path(app.__file__).with_name("app.html").read_text()
    assert 'id="style-current"' in html and 'id="style-browser"' in html
    assert 'id="home-styles-section"' in html
    # The old dropdown stays only as hidden state for restored takes.
    assert '<select id="look" class="pro-only" hidden' in html


def test_saved_styles_round_trip_and_validate(tmp_path):
    from io import BytesIO

    from fastapi.testclient import TestClient
    from PIL import Image

    from aipg_cinema import app

    client = TestClient(app.create_app(tmp_path / "web"), base_url="http://localhost")
    content = BytesIO()
    Image.new("RGB", (480, 280), (20, 90, 200)).save(content, format="PNG")
    look = client.post(
        "/api/looks", files={"file": ("look.png", content.getvalue(), "image/png")}
    ).json()["look_id"]
    assert client.get("/api/my-styles").json() == []
    body = {"name": "  Moody   teal ", "look": "Teal night grade.", "poster_id": look}
    saved = client.post("/api/my-styles", json=body).json()
    assert saved["name"] == "Moody teal"
    assert saved["id"].startswith("my-") and saved["motion"] == ""
    assert client.get(saved["poster_url"]).headers["content-type"] == "image/png"
    assert client.get("/api/my-styles").json() == [saved]
    # A missing poster, a blank name or extra fields are refused.
    assert (
        client.post("/api/my-styles", json={**body, "poster_id": "f" * 32}).status_code
        == 404
    )
    assert (
        client.post("/api/my-styles", json={**body, "name": "   "}).status_code == 422
    )
    assert client.post("/api/my-styles", json={**body, "seed": 1}).status_code == 422
    # Saved styles survive a restart of the studio.
    again = TestClient(app.create_app(tmp_path / "web"), base_url="http://localhost")
    assert again.get("/api/my-styles").json() == [saved]
    assert again.delete(f"/api/my-styles/{saved['id']}").status_code == 200
    assert again.get("/api/my-styles").json() == []
    assert again.get(saved["poster_url"]).status_code == 404
    assert again.delete("/api/my-styles/../../etc").status_code == 404


def test_saved_styles_join_the_library_and_compare():
    script = (Path(styles.__file__).with_name("styles.js")).read_text()
    assert "function allStyles()" in script
    assert "allStyles().filter(s=>compareSet.has(s.id))" in script
    assert "style_image_id:cell.style.style_image_id" in script
    assert "/api/my-styles" in script
