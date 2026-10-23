import json
import shutil

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from aipg_cinema.product import (
    PACKSHOT_FRAMES,
    PRODUCT_SHOT_FRAMES,
    SAFE,
    ProductBrief,
    layout,
    main,
    plan,
    render_packshot,
)
from aipg_cinema.project import Project
from aipg_cinema.reshoot import video_format
from aipg_cinema.sequence import assemble


def photo(path, cutout=False):
    image = Image.new(
        "RGBA", (600, 800), (0, 0, 0, 0) if cutout else (235, 230, 220, 255)
    )
    ImageDraw.Draw(image).rounded_rectangle(
        (200, 100, 400, 700), 30, fill=(30, 90, 160, 255)
    )
    image.save(path)
    return path


def test_plan_has_hook_reveal_benefits_and_local_packshot():
    brief = ProductBrief(
        pacing="punchy",
        name="Grid Cold Brew",
        tone="bold",
        benefits=["Twelve hours steeped", "Zero sugar"],
        tagline="Slow-steeped. Fast energy.",
        cta="Shop now",
    )
    result = plan(brief)
    shots = result["shots"]
    assert [item.shot.beat for item in shots] == [
        "hook",
        "reveal",
        "build",
        "build",
        "payoff",
    ]
    assert shots[-1].packshot and shots[-1].image_direction is None
    for item in shots:
        # Named prompts make image models print the name onto the product.
        assert "Grid Cold Brew" not in item.shot.draft.prompt
        assert "Grid Cold Brew" not in (item.image_direction or "")
    for item in shots[:-1]:
        assert "from the reference image" in item.image_direction
        assert "No people" in item.image_direction
        assert item.shot.draft.mode == "image" and item.shot.draft.look_id is None
        assert item.shot.trim_end == PRODUCT_SHOT_FRAMES
    project = Project(
        id="a" * 32,
        shots=[item.shot for item in shots],
        captions=result["captions"],
    )
    assert project.frames == 4 * PRODUCT_SHOT_FRAMES + PACKSHOT_FRAMES
    # Default: one opening line; the packshot carries the close.
    assert [c.text for c in project.captions] == ["Meet Grid Cold Brew"]
    every = plan(brief.model_copy(update={"captions": "every-shot"}))["captions"]
    assert [c.text for c in every] == [
        "Meet Grid Cold Brew",
        "Slow-steeped. Fast energy.",
        "Twelve hours steeped",
        "Zero sugar",
    ]
    # A scene shot cannot render until a product-reference image is chosen.
    with pytest.raises(ValidationError):
        project.request(shots[0].shot.id, "b" * 32)


def test_worn_plan_uses_a_fictional_model_and_keeps_the_print():
    brief = ProductBrief(
        pacing="punchy", name="AIPG Tee", worn=True, benefits=["Heavyweight cotton"]
    )
    shots = plan(brief)["shots"]
    directions = [item.image_direction for item in shots if item.image_direction]
    assert len(directions) == 3 and len(set(directions)) == 3
    assert all("fictional adult model" in text for text in directions)
    assert all("same emblem and wordmark" in text for text in directions)
    assert not any("No people" in text for text in directions)
    assert all("AIPG Tee" not in text for text in directions)
    assert shots[-1].packshot
    product_only = plan(ProductBrief(pacing="punchy", name="AIPG Tee"))["shots"]
    assert all("No people" in item.image_direction for item in product_only[:-1])


def test_plan_without_benefits_uses_a_detail_shot():
    shots = plan(ProductBrief(pacing="punchy", name="Lamp"), "square")["shots"]
    assert [item.shot.beat for item in shots] == ["hook", "reveal", "detail", "payoff"]
    assert all(item.shot.draft.frame_format == "square" for item in shots)


@pytest.mark.parametrize(
    "field",
    [
        {"name": ""},
        {"name": "x" * 61},
        {"name": "Cafe \U0001f600"},
        {"name": "A", "benefits": ["a"] * 4},
    ],
)
def test_brief_rejects_unrenderable_text(field):
    with pytest.raises(ValidationError):
        ProductBrief(**field)


@pytest.mark.parametrize("frame_format", ["portrait", "square", "landscape"])
def test_layout_stays_inside_the_safe_area(tmp_path, frame_format):
    image = Image.open(photo(tmp_path / "p.png")).convert("RGBA")
    result = layout(
        image, frame_format, "Grid Cold Brew", "Slow-steeped. Fast energy.", "Shop now"
    )
    width, height = video_format(frame_format).output_size
    top, bottom = SAFE[frame_format]
    for _, layer, (x, y) in result["text"]:
        assert x >= 0 and x + layer.width <= width
        assert top * height <= y and y + layer.height <= bottom * height + 1


def test_layout_rejects_text_that_cannot_fit(tmp_path):
    image = Image.open(photo(tmp_path / "p.png")).convert("RGBA")
    with pytest.raises(ValueError, match="too long"):
        layout(image, "landscape", "W" * 60, "W" * 80, "W" * 40)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is required")
def test_packshot_is_a_valid_take_for_sequence_export(tmp_path):
    jobs = tmp_path / "jobs"
    take = "c" * 32
    render = jobs / take / "render"
    out = render_packshot(
        photo(tmp_path / "p.png", cutout=True),
        render,
        name="Grid Cold Brew",
        cta="Shop now",
        frame_format="square",
    )
    meta = json.loads((render / "packshot.json").read_text())
    assert meta["ai_generated"] is False and meta["output"]["frames"] == 120
    assert (render / "packshot.png").is_file()
    with pytest.raises(ValueError, match="already exists"):
        render_packshot(tmp_path / "p.png", render, name="Again", frame_format="square")
    shot = plan(ProductBrief(name="Grid Cold Brew"), "square")["shots"][-1].shot
    request = shot.draft.model_dump() | {
        "request_id": take,
        "look_id": "d" * 32,
        "prompt": shot.draft.prompt,
    }
    (jobs / take / "request.json").write_text(json.dumps(request))
    project = Project(
        id="a" * 32,
        frame_format="square",
        shots=[shot.model_copy(update={"selected_take_id": take})],
    )
    short = assemble(project, jobs, tmp_path / "export")
    assert short.is_file() and out.is_file()
    assert (
        json.loads((tmp_path / "export" / "quality.json").read_text())["frames"]
        == PACKSHOT_FRAMES
    )


def test_plan_command_prints_json(tmp_path, capsys):
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({"name": "Lamp", "cta": "Buy"}))
    assert main(["plan", "--brief", str(brief)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["shots"][-1]["packshot"] is True


@pytest.mark.parametrize("refine", [False, True])
def test_look_graph_links_klein_and_optional_moss(refine):
    from aipg_cinema.product import look_graph

    workflow, output = look_graph("A bottle on stone.", 7, refine=refine)
    for node in workflow.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in workflow
    assert workflow["model"]["inputs"]["unet_name"] == "flux-2-klein-4b.safetensors"
    assert workflow["empty"]["inputs"]["width"] == 720
    if refine:
        assert output == "moss-save"
        assert workflow["moss-scale"]["inputs"]["image"] == ["decode", 0]
        assert workflow["moss-sample"]["inputs"]["denoise"] == 0.4
    else:
        assert output == "save" and "moss-sample" not in workflow
    cloud, _ = look_graph("A bottle.", backend="cloud")
    assert cloud["model"]["inputs"]["unet_name"] == "flux-2-klein-4b-fp8.safetensors"
    with pytest.raises(ValueError, match="owned image runtime"):
        look_graph("A bottle.", backend="cloud", refine=True)


def test_benefit_shots_do_not_repeat_the_reveal():
    brief = ProductBrief(
        pacing="punchy",
        name="Lamp",
        benefits=["Warm light", "Folds flat", "Runs all day"],
    )
    shots = plan(brief)["shots"]
    directions = [item.image_direction for item in shots if item.image_direction]
    assert len(set(directions)) == len(directions) == 5
    assert "Low-angle" in directions[2] and "Eye-level" in directions[3]
    assert "warm light" in directions[2]
    # Benefit text is a hint; the product must stay the visible subject.
    assert all("fully visible" in text for text in directions[2:])
    assert not any("Overhead" in text for text in directions)


def test_continuity_chains_a_second_reference():
    from aipg_cinema.product import look_graph

    workflow, _ = look_graph("Same model.", continuity=True)
    assert workflow["continuity-positive"]["inputs"]["conditioning"] == [
        "ref-positive",
        0,
    ]
    assert workflow["guider"]["inputs"]["positive"] == ["continuity-positive", 0]
    assert workflow["guider"]["inputs"]["negative"] == ["continuity-negative", 0]
    for node in workflow.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in workflow


def test_worn_benefit_directions_read_cleanly():
    brief = ProductBrief(
        pacing="punchy", name="Tee", worn=True, benefits=["Soft", "Strong"]
    )
    directions = [item.image_direction for item in plan(brief)["shots"][2:4]]
    assert directions[1].startswith("Mid shot of a fictional adult model wearing")
    assert "no readable lettering" in directions[0]


def test_worn_shots_use_a_steady_camera_regardless_of_tone():
    shots = plan(ProductBrief(pacing="punchy", name="Tee", worn=True, tone="bold"))[
        "shots"
    ]
    for item in shots[:-1]:
        assert "Steady camera" in item.shot.draft.motion_prompt
        assert "fast confident push-in" not in item.shot.draft.motion_prompt.lower()


def test_worn_shorts_caption_below_the_face():
    from aipg_cinema.brief import ProductSetup
    from aipg_cinema.product import plan_project

    empty = Project(id="a" * 32)
    for worn, position in ((False, "upper"), (True, "lower")):
        setup = ProductSetup(
            brief=ProductBrief(name="Tee", worn=worn), photo_ids=["b" * 32]
        )
        assert plan_project(empty, setup).caption_position == position


def test_worn_hook_leaves_the_print_uncaptioned():
    brief = ProductBrief(
        name="Tee", worn=True, tagline="Wear it.", hook="Not just a tee."
    )
    opening = plan(brief)["captions"]
    assert [c.text for c in opening] == ["Not just a tee."]
    assert opening[0].start_frame >= 72
    every = plan(brief.model_copy(update={"captions": "every-shot"}))["captions"]
    assert [c.text for c in every] == ["Wear it."]
    assert every[0].start_frame >= 72


def test_hook_line_is_short_and_opens_the_short():
    result = plan(ProductBrief(name="Lamp", hook="Your desk is lying to you."))
    assert [c.text for c in result["captions"]] == ["Your desk is lying to you."]
    assert result["captions"][0].start_frame < 72
    with pytest.raises(ValidationError, match="ten words"):
        ProductBrief(
            name="Lamp", hook="one two three four five six seven eight nine ten eleven"
        )


@pytest.mark.parametrize("tone", ["premium", "playful", "bold", "calm"])
def test_every_scene_shot_asks_for_sound(tone):
    shots = plan(ProductBrief(name="Tee", tone=tone))["shots"]
    for item in shots[:-1]:
        assert "Sound:" in item.shot.draft.motion_prompt
        assert "Sound:" in item.shot.draft.prompt
        assert "Sound:" not in item.image_direction


def test_drafted_sentence_settings_read_mid_sentence():
    shots = plan(ProductBrief(name="Mug", setting="A sunlit desk with a plant."))[
        "shots"
    ]
    assert "centered on a sunlit desk with a plant," in shots[1].image_direction
    keep = plan(ProductBrief(name="Mug", setting="AIPG booth at a fair"))["shots"]
    assert "centered on AIPG booth" in keep[1].image_direction


def test_calm_default_is_two_gentle_shots_and_a_packshot():
    from aipg_cinema.product import CALM_FRAMES

    brief = ProductBrief(name="Mug", benefits=["A", "B", "C"], hook="Wake up right.")
    result = plan(brief)
    shots = [item.shot for item in result["shots"]]
    assert [s.beat for s in shots] == ["hook", "reveal", "payoff"]
    assert [s.camera for s in shots] == ["push-in@1", "pull-back@1", None]
    assert [s.trim_end for s in shots] == [*CALM_FRAMES, PACKSHOT_FRAMES]
    assert shots[0].draft.motion_prompt.startswith("The camera slowly and steadily")
    caption = result["captions"][0]
    assert caption.text == "Wake up right." and caption.end_frame == CALM_FRAMES[0] - 6
    worn = plan(ProductBrief(name="Tee", worn=True))["shots"]
    assert [i.shot.beat for i in worn] == ["hook", "reveal", "payoff"]
    assert "fictional adult model" in worn[1].image_direction


def test_calm_hook_opens_on_the_whole_product():
    calm = plan(ProductBrief(name="Mug"))["shots"][0].image_direction
    assert calm.startswith("Medium close-up") and "whole product visible" in calm
    punchy = plan(ProductBrief(name="Mug", pacing="punchy"))["shots"][0].image_direction
    assert punchy.startswith("Wide establishing shot") and "whole product" in punchy
