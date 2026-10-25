import httpx
import pytest

from aipg_cinema import promptkit


def test_template_fallback_when_no_model(monkeypatch):
    monkeypatch.setenv("OPENFIELD_LLM_URL", "http://127.0.0.1:9")  # nothing listens
    look = promptkit.suggest("make it spooky", "transform")
    assert look["source"] == "template"
    assert look["look"].startswith("Restyle this frame: Give it a spooky look")
    assert look["look"].endswith(promptkit.KEEP_FRAME)
    assert look["motion"].endswith(promptkit.FOLLOW)
    scene = promptkit.suggest("a fox in the snow", "scene")
    assert scene["prompt"].startswith("A fox in the snow.") and scene["motion"] == ""


def test_model_sentence_is_wrapped_and_tidied(monkeypatch):
    def fake_post(url, json, timeout):
        assert url.endswith("/api/chat") and json["messages"][-1]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "```Palette: Cold teal shadows and sickly green light, with grainy film texture.```"
                }
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(promptkit.httpx, "post", fake_post)
    result = promptkit.suggest("spooky", "transform")
    assert result["source"] == promptkit.DEFAULT_MODEL
    assert result["look"] == (
        "Restyle this frame: Cold teal shadows and sickly green light, with grainy "
        "film texture. " + promptkit.KEEP_FRAME
    )


def test_bounds_and_loopback(monkeypatch):
    with pytest.raises(ValueError):
        promptkit.suggest("x", "transform")
    with pytest.raises(ValueError):
        promptkit.suggest("spooky", "poem")
    monkeypatch.setenv("OPENFIELD_LLM_URL", "http://example.com:11434")
    with pytest.raises(ValueError, match="loopback"):
        promptkit.endpoint()


def test_prompt_helper_route(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aipg_cinema import app

    monkeypatch.setenv("OPENFIELD_LLM_URL", "http://127.0.0.1:9")
    client = TestClient(app.create_app(tmp_path / "web"), base_url="http://localhost")
    reply = client.post("/api/prompt-helper", json={"idea": "golden hour"})
    assert reply.status_code == 200 and reply.json()["source"] == "template"
    assert client.post("/api/prompt-helper", json={"idea": "a"}).status_code == 422
