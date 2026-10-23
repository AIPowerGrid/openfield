import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from aipg_cinema import app


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        self.inside = tag == "script"

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is optional for JS tests")
@pytest.mark.parametrize("cloud_look", [False, True])
def test_actual_inline_playback_handlers(cloud_look):
    parser = Scripts()
    parser.feed(Path(app.__file__).with_name("app.html").read_text())
    assert len(parser.parts) == 1
    subprocess.run(
        ["node", str(Path(__file__).with_name("playback.cjs"))]
        + (["--cloud-look"] if cloud_look else []),
        input=parser.parts[0],
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


def test_source_preview_loading_failure_retry_and_readiness_never_change_draft():
    parser = Scripts()
    parser.feed(Path(app.__file__).with_name("app.html").read_text())
    subprocess.run(
        ["node", str(Path(__file__).with_name("playback.cjs")), "--source-preview"],
        input=parser.parts[0],
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is optional for JS tests")
def test_actual_shot_board_handlers():
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        ["node", str(Path(__file__).with_name("board.cjs"))],
        input=parser.parts[0] + "\n" + (folder / "board.js").read_text(),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is optional for JS tests")
def test_actual_finishing_handlers_save_reload_mute_and_never_render():
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        ["node", str(Path(__file__).with_name("board.cjs")), "--finishing"],
        input=parser.parts[0]
        + "\n"
        + (folder / "board.js").read_text()
        + "\n"
        + (folder / "finishing.js").read_text(),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


def test_actual_audition_handlers_preserve_base_and_recover_same_request():
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        ["node", str(Path(__file__).with_name("board.cjs")), "--auditions"],
        input=parser.parts[0]
        + "\n"
        + "\n".join(
            (folder / name).read_text()
            for name in ("board.js", "finishing.js", "auditions.js")
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


def test_speech_profile_handlers_save_restore_and_submit_explicit_choice():
    parser = Scripts()
    parser.feed(Path(app.__file__).with_name("app.html").read_text())
    subprocess.run(
        ["node", str(Path(__file__).with_name("playback.cjs")), "--speech"],
        input=parser.parts[0],
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


def test_ending_anchor_survives_shot_switch_reload_and_never_renders_on_toggle():
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        ["node", str(Path(__file__).with_name("board.cjs")), "--ending-anchor"],
        input=parser.parts[0] + "\n" + (folder / "board.js").read_text(),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


@pytest.mark.parametrize("project", [False, True])
def test_accepted_take_is_remembered_before_post_acceptance_refresh(project):
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("board.cjs" if project else "playback.cjs")),
            "--submission-reload",
        ],
        input=parser.parts[0]
        + ("\n" + (folder / "board.js").read_text() if project else ""),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


def test_project_transfer_handlers_recover_ids_without_inference_or_duplicate_imports():
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        ["node", str(Path(__file__).with_name("board.cjs")), "--packaging"],
        input=parser.parts[0]
        + "\n"
        + (folder / "board.js").read_text()
        + "\n"
        + (folder / "packaging.js").read_text(),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


def test_seed_controls_preserve_full_width_values_and_never_round_requests():
    parser = Scripts()
    parser.feed(Path(app.__file__).with_name("app.html").read_text())
    subprocess.run(
        ["node", str(Path(__file__).with_name("playback.cjs")), "--seed-width"],
        input=parser.parts[0],
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


def test_video_take_comparison_is_read_only_until_explicit_seed_or_winner_action():
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        ["node", str(Path(__file__).with_name("board.cjs")), "--takecompare"],
        input=parser.parts[0]
        + "\n"
        + (folder / "board.js").read_text()
        + "\n"
        + (folder / "takecompare.js").read_text(),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


def test_connection_recovery_preserves_errors_and_reads_pending_jobs_without_reposting():
    parser = Scripts()
    parser.feed(Path(app.__file__).with_name("app.html").read_text())
    subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("playback.cjs")),
            "--connection-recovery",
        ],
        input=parser.parts[0],
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


@pytest.mark.parametrize("image", [False, True])
def test_missing_submission_requires_explicit_retry_with_unchanged_context(image):
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("board.cjs")),
            "--missing-look" if image else "--missing-submission",
        ],
        input=parser.parts[0] + "\n" + (folder / "board.js").read_text(),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


def test_reference_review_and_help_do_not_mutate_render_settings_or_dispatch_work():
    parser = Scripts()
    parser.feed(Path(app.__file__).with_name("app.html").read_text())
    subprocess.run(
        ["node", str(Path(__file__).with_name("playback.cjs")), "--reference-controls"],
        input=parser.parts[0],
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


@pytest.mark.parametrize("initial", [False, True])
@pytest.mark.parametrize("reviewing_frame", [False, True])
def test_completing_a_viewed_take_preserves_newer_project_settings(
    initial, reviewing_frame
):
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        ["node", str(Path(__file__).with_name("board.cjs")), "--draft-completion"]
        + (["--initial-completion"] if initial else [])
        + (["--keep-frame"] if reviewing_frame else []),
        input=parser.parts[0] + "\n" + (folder / "board.js").read_text(),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


@pytest.mark.parametrize("mode", ["text", "image", "audio", "video"])
@pytest.mark.parametrize("frame_format", ["landscape", "square", "portrait"])
def test_take_review_binds_picture_metadata_and_downloads_without_replacing_draft(
    mode, frame_format
):
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("board.cjs")),
            "--take-review",
            mode,
            frame_format,
        ],
        input=parser.parts[0] + "\n" + (folder / "board.js").read_text(),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


@pytest.mark.parametrize(
    "scenario",
    [
        "lost-reply",
        "missing",
        "reload",
        "double-submit",
        "double-check",
        "mismatched",
        "list-failed",
        "list-missing",
        "storage-failed",
        "validation-failed",
        "later-edit",
        "initial-loading",
    ],
)
def test_project_creation_recovers_frozen_request_without_duplicates(scenario):
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("board.cjs")),
            "--creation-recovery",
            scenario,
        ],
        input=parser.parts[0] + "\n" + (folder / "board.js").read_text(),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


@pytest.mark.parametrize(
    "scenario",
    [
        "unchanged",
        "manual",
        "roundtrip",
        "shot",
        "prompt",
        "motion",
        "restore",
        "lost-reply",
        "legacy",
        "malformed",
    ],
)
def test_completed_look_preserves_newer_selection_and_other_shots(scenario):
    parser = Scripts()
    folder = Path(app.__file__).parent
    parser.feed((folder / "app.html").read_text())
    subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("board.cjs")),
            "--look-adoption",
            scenario,
        ],
        input=parser.parts[0] + "\n" + (folder / "board.js").read_text(),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is optional for JS tests")
def test_make_whole_short_plans_only_missing_steps():
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("openfield.cjs"))],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "openfield ok" in result.stdout
