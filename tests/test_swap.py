import json
from types import SimpleNamespace

import pytest

from aipg_cinema import swap

CLOUD = {
    "diffusion_models": ["minimax_h3_ref2va_pruned_int8_convrot.safetensors"],
    "text_encoders": ["qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"],
    "vae": [
        "minimax_h3_video_vae_int8_convrot.safetensors",
        "minimax_h3_audio_vae_fp32.safetensors",
    ],
    "loras": [swap.TURBO_LORA],
}
LOCAL = {
    "diffusion_models": ["minimax_h3_ref2va_pruned_bf16.safetensors"],
    "text_encoders": ["qwen3vl_32b_minimax_h3_int8_convrot.safetensors"],
    "vae": ["minimax_h3_video_vae_fp16.safetensors", swap.AUDIO_VAE],
    "loras": [swap.SWAP_LORA, swap.TURBO_LORA],
}


def refs(workflow):
    for key, item in workflow.items():
        for value in item["inputs"].values():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
            ):
                yield key, value[0]


@pytest.mark.parametrize("shape", ["portrait", "landscape", "square"])
def test_graph_keeps_the_clip_as_motion_and_voice_reference(shape):
    models = swap.recipe(LOCAL, "self-hosted")
    workflow = swap.graph(models, shape, seed=7, note="Keep the hat.")
    assert all(target in workflow for _, target in refs(workflow))
    assert workflow["source"]["class_type"] == "LoadVideo"
    assert workflow["character"]["class_type"] == "LoadImage"
    ref = workflow["ref"]["inputs"]
    assert ref["ref_images.ref_image_0"] == ["character", 0]
    assert ref["ref_videos.ref_video_0"] == ["parts", 0]
    # The clip's own soundtrack is the audio reference: that is what keeps the voice.
    assert ref["ref_video_audios.ref_video_audio_0"] == ["parts", 1]
    assert (ref["width"], ref["height"]) == swap.SIZES[shape]
    assert all(side % 32 == 0 for side in swap.SIZES[shape])
    assert ref["length"] == 124 and (124 - 5) % 17 == 0
    assert ref["prompt"].endswith("Keep the hat.")
    # Both LoRAs sit on the sampled model: swap first, Comfy's turbo on top.
    assert workflow["swap"]["inputs"]["lora_name"] == swap.SWAP_LORA
    assert workflow["turbo"]["inputs"]["model"] == ["swap", 0]
    assert workflow["turbo"]["inputs"]["lora_name"] == swap.TURBO_LORA
    assert workflow["schedule"]["inputs"]["model"] == ["turbo", 0]
    assert workflow["guider"]["inputs"]["model"] == ["turbo", 0]
    assert workflow["schedule"]["inputs"]["steps"] == 4
    assert workflow["sampler"]["inputs"]["sampler_name"] == "res_multistep"
    assert workflow["noise"]["inputs"]["noise_seed"] == 7
    # Picture and sound are saved apart; the CLI muxes them.
    assert "audio" not in workflow["video"]["inputs"]
    assert workflow["save"]["class_type"] == "SaveVideo"
    assert workflow["save-audio"]["inputs"]["audio"] == ["decode-audio", 0]
    assert workflow["model"]["inputs"]["unet_name"] == LOCAL["diffusion_models"][0]
    json.dumps(workflow)


def test_recipe_prefers_cloud_builds_and_names_what_is_missing():
    with pytest.raises(swap.Unavailable) as missing:
        swap.recipe(CLOUD, "cloud")
    assert missing.value.missing == [swap.SWAP_LORA]
    assert "Model Library" in str(missing.value)
    assert swap.SWAP_LORA_URL in str(missing.value)
    assert "Nothing was submitted" in str(missing.value)
    imported = {**CLOUD, "loras": [swap.TURBO_LORA, swap.SWAP_LORA]}
    models = swap.recipe(imported, "cloud")
    assert models.unet == "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
    assert models.clip == "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
    assert models.vae == "minimax_h3_video_vae_int8_convrot.safetensors"
    with pytest.raises(swap.Unavailable) as empty:
        swap.recipe({}, "self-hosted")
    assert set(empty.value.missing) == {
        "minimax_h3_ref2va_pruned_bf16.safetensors",
        "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
        "minimax_h3_video_vae_fp16.safetensors",
        swap.AUDIO_VAE,
        swap.SWAP_LORA,
        swap.TURBO_LORA,
    }
    assert "ComfyUI worker" in str(empty.value)


def test_prompt_bounds_the_note():
    assert swap.prompt("  two   words ").endswith("two words")
    assert "<Video 1>" in swap.prompt() and "<Picture 1>" in swap.prompt()
    with pytest.raises(ValueError):
        swap.prompt("x" * 301)
    with pytest.raises(ValueError):
        swap.graph(swap.recipe(LOCAL, "self-hosted"), "wide")


def test_listing_reads_both_backends_and_ignores_odd_replies(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs.get("headers", {})))
        data = (
            [{"name": "a.safetensors", "pathIndex": 0}, {"bad": 1}, "x"]
            if "loras" in url
            else {"error": "not a list"}
        )
        return SimpleNamespace(
            status_code=200, json=lambda: data, raise_for_status=lambda: None
        )

    monkeypatch.setattr(swap.httpx, "get", get)
    listing = swap.available("cloud", key="secret")
    assert listing["loras"] == ["a.safetensors"] and listing["vae"] == []
    assert calls[0][0].startswith("https://cloud.comfy.org/api/experiment/models/")
    assert calls[0][1] == {"X-API-Key": "secret"}
    calls.clear()
    swap.available("self-hosted", "http://127.0.0.1:18189", "secret")
    assert calls[0][0] == "http://127.0.0.1:18189/experiment/models/diffusion_models"
    # Cloud credentials never reach a local worker.
    assert calls[0][1] == {}


def test_background_mode_keeps_the_person_and_needs_no_swap_lora():
    listing = {**LOCAL, "loras": [swap.TURBO_LORA]}
    models = swap.recipe(listing, "self-hosted", "background")
    with pytest.raises(swap.Unavailable):
        swap.recipe(listing, "self-hosted", "person")
    workflow = swap.graph(models, "portrait", 5, "at night", "background")
    assert "swap" not in workflow
    assert workflow["turbo"]["inputs"]["model"] == ["model", 0]
    text = workflow["ref"]["inputs"]["prompt"]
    assert text.startswith("Keep the person in <Video 1> exactly as they are")
    assert "becomes the scene in <Picture 1>" in text and text.endswith("at night")
    assert workflow["ref"]["inputs"]["ref_video_audios.ref_video_audio_0"] == [
        "parts",
        1,
    ]
    with pytest.raises(ValueError):
        swap.prompt("", "scenery")
    with pytest.raises(ValueError):
        swap.recipe(LOCAL, "cloud", "scenery")
