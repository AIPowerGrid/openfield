import itertools

import pytest
from comfy_sdk.workflows import WorkflowFactory

from aipg_cinema.fasth3 import graph


@pytest.mark.parametrize(
    "frame_format,appearance,audio_reference",
    list(
        itertools.product(
            ("landscape", "portrait", "square"), (False, True), (False, True)
        )
    ),
)
def test_graph_binds_distinct_reference_roles(
    frame_format, appearance, audio_reference
):
    workflow = graph(
        "A red paper boat floats on neon water.",
        frame_format=frame_format,
        appearance=appearance,
        audio_reference=audio_reference,
    )
    WorkflowFactory().from_json(workflow)
    for node in workflow.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in workflow
    reference = workflow["reference"]["inputs"]
    assert "ref_videos.ref_video_0" not in reference
    assert ("ref_images.ref_image_0" in reference) == appearance
    assert ("ref_audios.ref_audio_0" in reference) == audio_reference
    assert reference["length"] == 124
    assert reference["prompt"] == "A red paper boat floats on neon water."
    assert workflow["video"]["inputs"]["audio"] == ["decode-audio", 0]
    assert workflow["decode-audio"]["inputs"]["samples"] == ["sample", 0]
    assert workflow["schedule"]["inputs"]["steps"] == 8
    assert (
        workflow["model"]["inputs"]["unet_name"]
        == "fasth3_omniref_qad_nvfp4_comfy.safetensors"
    )
    assert workflow["save"]["inputs"]["codec"] == "h264"
    assert "format.codec" not in workflow["save"]["inputs"]
    assert "guide" not in workflow  # Appearance is not silently a first frame.
    expected = {"landscape": (1344, 768), "portrait": (768, 1344), "square": (768, 768)}
    assert (reference["width"], reference["height"]) == expected[frame_format]


@pytest.mark.parametrize("seed", [-1, True, 1.2, 2**53])
def test_seed_must_be_bounded_integer(seed):
    with pytest.raises(ValueError, match="seed"):
        graph("A paper boat", seed)


@pytest.mark.parametrize(
    "prompt",
    ["", " ", "a" * 4001, "Follow <Video 1>.", "Use <Picture 2>.", "Use <Audio 1>."],
)
def test_invalid_or_missing_reference_prompt_is_rejected(prompt):
    with pytest.raises(ValueError):
        graph(prompt)


def test_available_reference_tags_and_invalid_format():
    graph("Use <Picture 1> and <Audio 1>.", appearance=True, audio_reference=True)
    with pytest.raises(ValueError, match="framing"):
        graph("A boat", frame_format="cinema")


@pytest.mark.parametrize("framing", ["portrait", "square", "landscape"])
def test_image_plus_video_uses_distinct_appearance_and_motion_references(framing):
    workflow = graph(
        "Use <Picture 1> for appearance and <Video 1> for motion.",
        frame_format=framing,
        appearance=True,
        video_reference=True,
    )
    assert WorkflowFactory().from_json(workflow).json == workflow
    assert workflow["reference"]["inputs"]["ref_images.ref_image_0"] == [
        "appearance",
        0,
    ]
    assert workflow["reference"]["inputs"]["ref_videos.ref_video_0"] == ["frames", 0]
    assert workflow["source"]["class_type"] == "LoadVideo"
    assert workflow["appearance"]["class_type"] == "LoadImage"
    assert "guide" not in workflow
