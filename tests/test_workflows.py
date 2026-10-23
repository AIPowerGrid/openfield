from pathlib import Path

import pytest
from comfy_sdk.workflows import WorkflowFactory

from aipg_cinema.cli import load_workflow


@pytest.mark.parametrize(
    ("filename", "output_node"),
    [("minimax-h3-native.json", "92"), ("ltx-2.5-native.json", "75")],
)
def test_baseline_links_resolve(filename, output_node):
    path = Path(__file__).parents[1] / "workflows" / filename
    graph = load_workflow(path, output_node)
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph
                assert isinstance(value[1], int)


def test_ltx_baseline_keeps_native_distilled_schedule():
    path = Path(__file__).parents[1] / "workflows" / "ltx-2.5-native.json"
    graph = load_workflow(path, "75")
    assert WorkflowFactory().from_json(graph).json == graph
    latent = graph["356"]["inputs"]
    assert latent["width"] % 32 == latent["height"] % 32 == 0
    assert latent["length"] == 121
    assert (latent["length"] - 1) % 8 == 0
    assert graph["339"]["inputs"]["noise_seed"] == 42
    assert graph["338"]["inputs"]["noise_seed"] == 42
    assert len(graph["404"]["inputs"]["sigmas"].split(",")) == 9
    assert len(graph["395"]["inputs"]["sigmas"].split(",")) == 4


def test_h3_baseline_has_resolved_links_and_no_optional_lora():
    path = Path(__file__).parents[1] / "workflows" / "minimax-h3-native.json"
    graph = load_workflow(path, "92")
    assert WorkflowFactory().from_json(graph).json == graph
    assert graph["140:129"]["inputs"]["noise_seed"] == 42
    assert graph["140:124"]["inputs"]["steps"] == 20
    assert graph["140:133"]["inputs"]["value"] == 5
    assert not any("Lora" in node["class_type"] for node in graph.values())
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph
                assert isinstance(value[1], int)


def test_h3_duration_grid():
    # The upstream expression rounds 5 * 24 up to a 17k+5 frame count.
    frames = 120 + (5 - 120 % 17) % 17
    assert frames == 124
    assert (frames - 5) % 17 == 0
