import json

import httpx
import pytest
from PIL import Image

from aipg_cinema import autobrief

VISION = {
    "id": "deepseek-v4-flash-nvfp4",
    "input_modalities": ["text", "image"],
    "pricing": {"input_per_mtok_usd": 0.07, "output_per_mtok_usd": 0.14},
}
TEXT = {
    "id": "gpt-oss-120b",
    "input_modalities": ["text"],
    "pricing": {"input_per_mtok_usd": 0.075, "output_per_mtok_usd": 0.3},
}
DRAFT = {
    "name": "AIPG Bottle",
    "tone": "bold",
    "setting": "A rocky mountain trail at sunrise",
    "benefits": [
        "Keeps drinks cold all day",
        "Matte grip",
        "Fits cup holders",
        "Extra",
    ],
    "hook": "Your water deserves a better summit.",
    "hook_pattern": "curiosity",
    "tagline": "Hydrate the network.",
    "cta": "Shop now",
}


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "p.png"
    Image.new("RGB", (64, 64), (10, 10, 10)).save(path)
    return path


def grid(models, reply=None, status=200, seen=None):
    def handler(request: httpx.Request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": models})
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(
            status,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 800, "completion_tokens": 700},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_vision_draft_is_validated_and_costed(photo):
    seen = []
    result = autobrief.suggest(
        photo, "AIPG Bottle", key="k", client=grid([TEXT, VISION], DRAFT, seen=seen)
    )
    assert result["model"] == "deepseek-v4-flash-nvfp4" and result["vision"]
    assert result["brief"]["benefits"] == DRAFT["benefits"][:3]
    assert result["hook_pattern"] == "curiosity"
    assert result["cost_usd"] == pytest.approx((800 * 0.07 + 700 * 0.14) / 1e6)
    body = seen[0]
    assert body["max_tokens"] == autobrief.MAX_TOKENS
    assert body["messages"][1]["content"][1]["type"] == "image_url"


def test_bad_fields_are_dropped_not_fatal(photo):
    draft = DRAFT | {
        "tone": "loud",
        "hook": "one two three four five six seven eight nine ten eleven",
        "hook_pattern": "curiosity",
    }
    result = autobrief.suggest(photo, "", key="k", client=grid([VISION], draft))
    assert set(result["dropped"]) == {"tone", "hook"}
    assert result["brief"]["tone"] == "premium" and result["brief"]["hook"] == ""
    assert result["hook_pattern"] == ""


def test_without_a_vision_model_the_name_is_required(photo):
    with pytest.raises(autobrief.AutoBriefError, match="product name"):
        autobrief.suggest(photo, "", key="k", client=grid([TEXT], DRAFT))
    seen = []
    result = autobrief.suggest(
        photo, "Lamp", key="k", client=grid([TEXT], DRAFT, seen=seen)
    )
    assert result["model"] == "gpt-oss-120b" and not result["vision"]
    assert len(seen[0]["messages"][1]["content"]) == 1


def test_expensive_models_are_refused_before_any_request(photo):
    pricey = VISION | {"pricing": {"input_per_mtok_usd": 50, "output_per_mtok_usd": 50}}
    seen = []
    with pytest.raises(autobrief.AutoBriefError, match="cap"):
        autobrief.suggest(photo, "", key="k", client=grid([pricey], DRAFT, seen=seen))
    assert not seen


@pytest.mark.parametrize("reply,status", [("not json", 200), (DRAFT, 500)])
def test_failures_degrade_to_the_manual_form(photo, reply, status):
    with pytest.raises(autobrief.AutoBriefError, match="manually"):
        autobrief.suggest(photo, "", key="k", client=grid([VISION], reply, status))


def test_missing_key_is_reported(photo, monkeypatch):
    monkeypatch.delenv("GRID_API_KEY", raising=False)
    with pytest.raises(autobrief.AutoBriefError, match="GRID_API_KEY"):
        autobrief.suggest(photo, "")


def test_system_prompt_steers_away_from_complex_props():
    # The owner's review found malformed dumbbells in a drafted gym setting.
    assert "dumbbells" in autobrief.SYSTEM and "simple surfaces" in autobrief.SYSTEM
