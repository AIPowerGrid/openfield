import json

import pytest

from aipg_cinema import estimates, templates
from aipg_cinema.brief import ProductBrief, ProductSetup
from aipg_cinema.product import plan_project
from aipg_cinema.project import Project


def planned(**brief):
    setup = ProductSetup(brief=ProductBrief(name="Mug", **brief), photo_ids=["b" * 32])
    return plan_project(Project(id="a" * 32), setup)


def test_builtin_templates_are_plans_with_previews(tmp_path):
    found = {t.id: t for t in templates.listing(tmp_path)}
    assert set(found) == {"aipg-tee", "aipg-mug", "aipg-bottle"}
    for template in found.values():
        assert template.builtin
        assert templates.preview_path(tmp_path, template).stat().st_size < 150_000
        text = template.model_dump_json()
        assert "photo" not in text and "look_id" not in text and "key" not in text


def test_applying_a_template_copies_moves_trims_and_finishing(tmp_path):
    template = templates.by_template_id(tmp_path, "aipg-bottle")
    project = templates.apply(planned(**templates.brief_overrides(template)), template)
    assert [s.camera for s in project.shots] == ["push-in@1", "pull-back@1", None]
    assert [s.trim_end for s in project.shots] == [84, 96, 48]
    assert project.caption_style == "studio" and project.caption_position == "upper"
    tee = templates.by_template_id(tmp_path, "aipg-tee")
    worn = templates.apply(
        planned(benefits=["Soft", "Strong"], **templates.brief_overrides(tee)), tee
    )
    assert worn.music_prompt == tee.music_prompt
    assert [s.trim_end for s in worn.shots] == [72, 48, 72, 48, 48]
    assert all(c.end_frame <= worn.frames for c in worn.captions)


def test_saved_templates_hold_only_the_plan(tmp_path):
    project = planned(hook="Wake up right.")
    saved = templates.save_from(project, tmp_path, None)
    data = json.loads((tmp_path / saved.id / "template.json").read_text())
    assert data["shots"][0]["camera"] == "push-in@1" and not data["builtin"]
    # The hook and other copy belong to the user's brief, not the template.
    assert "Wake up" not in json.dumps(data)
    assert {"brief", "photo_ids", "captions_text"}.isdisjoint(data)
    assert templates.by_template_id(tmp_path, saved.id).id == saved.id
    with pytest.raises(ValueError):
        templates.by_template_id(tmp_path, "../etc")


def test_estimates_are_labelled_approximate():
    table = estimates.table("cloud", look_cloud=False)
    assert table["take3"]["credits"] == 3 * table["take"]["credits"]
    assert all("(est.)" in entry["label"] for entry in table.values())
    owned = estimates.table("self-hosted", look_cloud=False)
    assert "on your GPU" in owned["take"]["label"]
    assert estimates.actual_label({"actual_cost_cents": 7.0}).endswith("(measured)")
    assert estimates.actual_label({"elapsed_seconds": 88.2}) == "88 s (measured)"
    assert estimates.actual_label({}) is None
    # A lagging balance must never read as a free job.
    assert (
        estimates.actual_label({"actual_cost_cents": 0, "elapsed_seconds": 70})
        == "70 s (measured)"
    )


def test_cloud_estimates_carry_an_approximate_wait():
    table = estimates.table("cloud", look_cloud=True)
    assert table["take"]["wait"] == "about 3 min"
    assert table["take10"]["wait"] == "about 5 min"
    assert table["take3"]["wait"] == "about 9 min"
    assert table["look"]["wait"] == "about 30 s"
    assert table["look3"]["wait"] == "about 90 s"
    assert table["take"]["label"] == f"~{table['take']['credits']} Cloud credits (est.)"
    owned = estimates.table("self-hosted", look_cloud=False)
    assert "wait" not in owned["take"] and "wait" not in owned["look"]
    assert "wait" not in table["brief"]
