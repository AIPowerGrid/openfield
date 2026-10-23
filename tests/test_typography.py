import json
import shutil

import pytest
from PIL import Image

from aipg_cinema import typography
from aipg_cinema.finishing import caption_image, font
from aipg_cinema.product import layout


def test_display_fonts_are_bundled_with_licenses_and_hashes():
    data = typography.manifest()
    assert set(data) == {"michroma", "montserrat", "playfair"}
    for name in ("OFL-Michroma.txt", "OFL-Montserrat.txt", "OFL-PlayfairDisplay.txt"):
        assert "Open Font License" in (typography.FONT_ROOT / name).read_text()


def test_tampered_font_is_rejected(tmp_path, monkeypatch):
    for path in typography.FONT_ROOT.iterdir():
        shutil.copy(path, tmp_path / path.name)
    data = json.loads((tmp_path / "display.json").read_text())
    data["montserrat"]["sha256"] = "0" * 64
    (tmp_path / "display.json").write_text(json.dumps(data))
    monkeypatch.setattr(typography, "FONT_ROOT", tmp_path)
    typography.manifest.cache_clear()
    try:
        with pytest.raises(ValueError, match="integrity"):
            typography.manifest()
    finally:
        typography.manifest.cache_clear()


def test_unsupported_text_falls_back_to_noto_as_a_whole_line():
    assert typography.covers("montserrat", "Shop now")
    assert not typography.covers("michroma", "Καλημέρα")
    fallback = typography.face("michroma", "Καλημέρα", 40)
    assert fallback.path == font(40, 600).path


def test_two_line_wraps_are_balanced():
    typeface = typography.face("montserrat", "x", 80, 800)
    lines = typography.wrap("Small glass. Big mornings.", typeface, 700)
    assert lines == ["Small glass.", "Big mornings."]


def test_studio_captions_stay_in_their_band_without_a_box():
    image, meta = caption_image(
        "Small glass. Big mornings.", "portrait", "studio", "upper"
    )
    left, top, right, bottom = meta["bounds"]
    assert 0 <= left and right <= meta["width"]
    assert 0.12 * meta["height"] <= top and bottom <= 0.36 * meta["height"]
    assert meta["font_sha256"] == typography.manifest()["montserrat"]["sha256"]
    # Corners stay transparent: a soft scrim, not a full-frame tint.
    assert image.getpixel((0, 0))[3] == 0


@pytest.mark.parametrize("tone", ["bold", "playful", "premium", "calm"])
def test_every_tone_fits_a_long_name(tone):
    photo = Image.new("RGBA", (600, 800), (30, 90, 160, 255))
    result = layout(
        photo,
        "portrait",
        "AI Power Grid Tee",
        "Wear the network.",
        "Shop now",
        tone=tone,
    )
    assert [key for key, _, _ in result["text"]] == ["title", "rule", "tagline", "cta"]


def test_three_line_wraps_are_balanced():
    typeface = typography.face("montserrat", "x", 80, 800)
    text = "Stop drinking lukewarm water all day."
    lines = typography.wrap(text, typeface, 900)
    assert len(lines) == 3 and " ".join(lines) == text
    assert lines[-1] != "day."
