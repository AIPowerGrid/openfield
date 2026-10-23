"""Primary controls remain reachable without exposing technical settings."""

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from aipg_cinema import app


class Controls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.ids = []
        self.parents = {}
        self.attributes = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        identity = attributes.get("id")
        if identity:
            self.ids.append(identity)
            self.parents[identity] = [name for _, name in self.stack if name]
            self.attributes[identity] = attributes
        if tag not in {"img", "input", "meta", "link", "br", "hr", "source"}:
            self.stack.append((tag, identity))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def test_primary_flow_and_saved_advanced_inputs_have_unique_stable_ids():
    controls = Controls()
    controls.feed(Path(app.__file__).with_name("app.html").read_text())
    assert not [name for name, count in Counter(controls.ids).items() if count > 1]
    for name in ("motion-prompt", "render-profile", "seed", "source-position"):
        assert "motion-settings" in controls.parents[name]
    for name in (
        "input-mode",
        "frame-format",
        "prompt",
        "look-file",
        "reuse-opening-end",
        "generate",
    ):
        assert "motion-settings" not in controls.parents[name]
        assert "shot-details" not in controls.parents[name]
    for name in ("motion-settings", "shot-details", "take-history", "shots-panel"):
        assert "open" not in controls.attributes[name]
    assert controls.attributes["seed"]["value"] == "42"
    assert controls.attributes["back-preview"]["href"] == "#shot-workspace"
    assert "shot-details" in controls.parents["shot-duplicate"]
    assert "take-history" in controls.parents["takes"]


def test_frame_help_is_accessible_without_hiding_reference_controls():
    controls = Controls()
    controls.feed(Path(app.__file__).with_name("app.html").read_text())
    assert "open" not in controls.attributes["reference-help"]
    assert controls.attributes["reference-help-toggle"]["aria-controls"] == (
        "reference-help-content"
    )
    for control, description in (
        ("reference-opening", "opening-description"),
        ("reference-closing", "ending-description"),
        ("reuse-opening-end", "anchor-description"),
    ):
        assert controls.attributes[control]["aria-describedby"] == description
        assert description in controls.ids
        assert "reference-help" not in controls.parents[control]
    assert controls.attributes["preview-look"]["aria-controls"] == "look-canvas"
    assert "checked" not in controls.attributes["reuse-opening-end"]
    assert Path(app.__file__).with_name("icons").joinpath("info.svg").is_file()


def test_openfield_home_and_preset_browser_are_wired():
    html = Path(app.__file__).with_name("app.html").read_text()
    controls = Controls()
    controls.feed(html)
    for name in (
        "home",
        "home-create",
        "preset-browser",
        "make-short",
        "browse-presets",
    ):
        assert name in controls.ids
    assert "<title>Openfield</title>" in html
    order = [
        html.index(f'src="/{name}.js"')
        for name in ("product", "presetbrowser", "styles", "home", "autopilot")
    ]
    assert order == sorted(order)
    # The preset card stays outside Advanced so the move is visible at a glance.
    assert "motion-settings" not in controls.parents["camera-presets"]


def test_product_shots_open_in_a_simple_panel_with_one_signal_colour():
    html = Path(app.__file__).with_name("app.html").read_text()
    controls = Controls()
    controls.feed(html)
    # Pro reveals prompts, frames and seeds; the look, preset and Generate stay.
    for name in ("prompt", "input-mode", "motion-settings", "look-history"):
        assert "pro-only" in controls.attributes[name].get("class", "").split()
    for name in ("product-panel", "camera-presets", "generate"):
        assert "pro-only" not in controls.attributes[name].get("class", "")
    assert "pro-toggle" in controls.ids
    assert "--accent:#ff9900" in html
    assert "linear-gradient(120deg" not in html and "#8f7cff" not in html


def test_home_offers_every_studio_capability():
    script = Path(app.__file__).with_name("home.js").read_text()
    html = Path(app.__file__).with_name("app.html").read_text()
    controls = Controls()
    controls.feed(html)
    for feature in ("product", "reshoot", "animate", "idea", "audio", "story", "looks"):
        assert f"id:'{feature}'" in script
    # Each card opens a real mode and a picker or field that exists.
    for mode in ("video", "image", "text", "audio"):
        assert f"mode:'{mode}'" in script and f'value="{mode}"' in html
    assert "SHOWCASE_ORDER=['reshoot','product'" in script
    for target in ("upload", "upload-look", "upload-audio", "prompt", "auditions-tab"):
        assert target in controls.ids
    assert 'value="single-pass-audio"' in html


def test_page_scripts_share_no_top_level_names():
    # Classic scripts share one global scope; a repeated let/const/function
    # name stops the later script from loading at all.
    import re

    html = Path(app.__file__).with_name("app.html").read_text()
    folder = Path(app.__file__).parent
    sources = {"app.html": html}
    for name in re.findall(r'<script src="/([a-z]+\.js)"', html):
        sources[name] = (folder / name).read_text()
    # The inline script is indented four spaces; page scripts start at column 0.
    names = r"(?:let|const|var|function|async function)\s+([A-Za-z_$][\w$]*)"
    patterns = {
        name: re.compile(("^ {4}" if name == "app.html" else "^") + names, re.MULTILINE)
        for name in sources
    }
    seen = {}
    for name, text in sources.items():
        for match in patterns[name].finditer(text):
            assert match.group(1) not in seen or seen[match.group(1)] == name, (
                match.group(1),
                seen.get(match.group(1)),
                name,
            )
            seen.setdefault(match.group(1), name)
