import argparse
import json
from pathlib import Path

import pytest
from test_app import local, take, upload, upload_look  # noqa: F401

from aipg_cinema import cli, effects
from aipg_cinema.contracts import TakeRequest
from aipg_cinema.generation import graph as photo_graph
from aipg_cinema.reshoot import graph as clip_graph


def refs(workflow):
    for key, item in workflow.items():
        for value in item["inputs"].values():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
            ):
                yield key, value[0]


def test_every_listed_effect_was_rendered_and_has_a_source():
    ids = [effect.id for effect in effects.EFFECTS]
    assert ids == [
        "inflate",
        "crush",
        "squish",
        "atomic-explosion",
        "cakeify",
        "eat",
        "timelapse",
        "outfit-check",
        "animatediff",
        "googly-eyes",
        "cross-eyed",
        "claymation",
        "paper-cutout",
        "cozy-felt",
        "pixar-toon",
        "nineties-cartoon",
        "wild-west",
        "post-apocalyptic",
        "fantasy-anime",
        "fantasy-painterly",
        "fantasy-puppet",
        "cyberpunk",
        "fantasy-realism",
        "star-trek-tng",
        "crt-terminal",
        "fpv-motion",
        "colorize",
    ]
    assert len(set(ids)) == len(ids)
    for effect in effects.EFFECTS:
        assert effect.note and effect.source and effect.lora.endswith(".safetensors")
        assert 0 < effect.strength <= 1
    assert effects.get("cross-eyed").kind == "clip"
    assert effects.get("inflate").kind == "photo"
    assert effects.get("claymation").kind == "idea"
    assert effects.get("colorize").kind == "clip"
    assert (
        effects.get("colorize")
        .prompt("a rabbit on rocks")
        .startswith("Reference shows")
    )
    assert effects.get("claymation").graph == "ltx25"
    assert (
        effects.get("paper-cutout")
        .prompt("a fox in the snow")
        .startswith("Pap3rCut0u7")
    )
    with pytest.raises(ValueError):
        effects.get("melt")


def test_prompt_puts_the_trigger_first_and_keeps_the_scene():
    effect = effects.get("inflate")
    prompt = effect.prompt("  A woman in a kitchen.  ")
    assert prompt.startswith("infl4t3 it -- A woman in a kitchen. ")
    assert prompt.endswith(effect.action)
    assert effects.get("atomic-explosion").prompt("").startswith("Far behind")


def test_ltx2_template_carries_the_lora_and_pins_the_photo_twice():
    effect = effects.get("crush")
    workflow = effects.ltx2_graph(effect, "c5us4 -- test", 9, 704, 1280)
    for node in effects.LTX2_LORA_NODES:
        assert workflow[node]["inputs"]["lora_name"] == "ltx2-crush.safetensors"
        assert workflow[node]["inputs"]["strength_model"] == 0.85
    pins = [
        k for k, v in workflow.items() if v["class_type"] == "LTXVImgToVideoInplace"
    ]
    assert len(pins) == 2 and workflow["83"]["inputs"]["video_latent"] == ["repin", 0]
    assert workflow["3"]["inputs"]["text"] == "c5us4 -- test"
    assert workflow["11"]["inputs"]["noise_seed"] == 9
    assert workflow["89"]["inputs"]["width"] % 64 == 0
    assert workflow["62"]["inputs"]["value"] == 121
    assert workflow["look"]["class_type"] == "LoadImage"
    assert workflow["save"]["class_type"] == "SaveVideo"
    assert all(target in workflow for _, target in refs(workflow))


def test_photo_lora_sits_between_the_backbone_and_everything_else():
    workflow = photo_graph("x", 1, mode="image", frame_format="portrait", opening=True)
    effects.add_lora(workflow, effects.get("googly-eyes"), "backbone")
    users = [key for key, target in refs(workflow) if target == "backbone"]
    assert users == ["effect-lora"]
    assert workflow["effect-lora"]["inputs"]["lora_name"].startswith("ltx-2.3-googly")


def test_clip_effect_swaps_the_union_lora_and_guides_with_the_clip():
    workflow = clip_graph("ltx25", "x", 1, frame_format="portrait")
    effects.guide_with_clip(workflow, effects.get("cross-eyed"))
    assert "edges" not in workflow
    assert "cross-eyed" in workflow["model"]["inputs"]["lora_name"]
    assert workflow["guide"]["inputs"]["image"] == ["source-window", 0]
    assert all(target in workflow for _, target in refs(workflow))


@pytest.mark.parametrize(
    ("change", "ok"),
    [
        ({"mode": "image", "look_id": "b" * 32, "effect": "inflate"}, True),
        ({"mode": "video", "source_id": "c" * 32, "effect": "cross-eyed"}, True),
        ({"mode": "video", "source_id": "c" * 32, "effect": "inflate"}, False),
        ({"mode": "image", "look_id": "b" * 32, "effect": "cross-eyed"}, False),
        (
            {
                "mode": "video",
                "source_id": "c" * 32,
                "look_id": "b" * 32,
                "effect": "cross-eyed",
            },
            False,
        ),
        (
            {
                "mode": "image",
                "look_id": "b" * 32,
                "closing_id": "d" * 32,
                "effect": "inflate",
            },
            False,
        ),
        ({"mode": "image", "look_id": "b" * 32, "effect": "melt"}, False),
        ({"mode": "text", "effect": "claymation"}, True),
        ({"mode": "image", "look_id": "b" * 32, "effect": "claymation"}, False),
        ({"mode": "text", "look_id": "b" * 32, "effect": "claymation"}, False),
    ],
)
def test_takes_only_accept_effects_that_fit(change, ok):
    body = {"request_id": "a" * 32, "prompt": "A woman", **change}
    if ok:
        assert TakeRequest(**body).effect == change["effect"]
    else:
        with pytest.raises(ValueError):
            TakeRequest(**body)


def test_cli_checks_the_effect_against_the_take():
    photo = argparse.Namespace(
        effect="squish",
        mode="image",
        look_frame="look.png",
        closing_frame=None,
        render_profile="two-pass",
    )
    assert cli.effect_for(photo, "photo").id == "squish"
    with pytest.raises(ValueError):
        cli.effect_for(photo, "clip")
    with pytest.raises(ValueError):
        cli.effect_for(argparse.Namespace(**{**vars(photo), "mode": "text"}), "photo")
    clip = argparse.Namespace(
        effect="cross-eyed",
        model="ltx25",
        look_frame=None,
        closing_frame=None,
        render_profile="single-pass-audio",
        seconds=5,
        motion_strength=1.0,
    )
    with pytest.raises(ValueError):
        cli.effect_for(clip, "clip")
    assert cli.effect_for(argparse.Namespace(effect=None), "photo") is None


def test_app_offers_effects_and_sends_them_to_the_cli(local):  # noqa: F811
    client, _, processes = local
    offered = client.get("/api/config").json()["effects"]
    assert {e["id"] for e in offered} == {e.id for e in effects.EFFECTS}
    assert next(e for e in offered if e["id"] == "inflate")["cloud_only"]
    look = upload_look(client)
    photo = {
        "request_id": "b" * 32,
        "mode": "image",
        "look_id": look,
        "prompt": "A woman",
        "effect": "inflate",
    }
    # The self-hosted test studio has no LTX-2 model.
    assert client.post("/api/jobs", json=photo).status_code == 409
    source = upload(client)
    body = {**take(source), "effect": "cross-eyed"}
    assert client.post("/api/jobs", json=body).status_code == 200
    arguments = processes[-1].args
    assert arguments[arguments.index("--effect") + 1] == "cross-eyed"
    page = client.get("/").text
    assert 'id="effect-row"' in page and 'id="effect-chips"' in page


def test_vendored_template_keeps_its_upstream_notice():
    workflow = json.loads(effects.WORKFLOW.read_text())
    assert "repin" in workflow
    readme = (effects.REPO_WORKFLOW.parent / "README.md").read_text()
    assert "ltx-2-effect.json" in readme


def test_effect_template_ships_inside_the_package():
    # Installed wheels have no repo-root workflows/ folder, so the graph is
    # read from the package; the repo copy stays beside its license notice.
    assert effects.WORKFLOW == effects.PACKAGED_WORKFLOW
    assert effects.PACKAGED_WORKFLOW.parent.parent == Path(effects.__file__).parent
    assert effects.PACKAGED_WORKFLOW.read_bytes() == effects.REPO_WORKFLOW.read_bytes()
