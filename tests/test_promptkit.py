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


def test_backend_graph_attaches_the_picture_and_saves_text():
    assert promptkit.writer(["x", "qwen3vl_4b_bf16.safetensors"]) == (
        "qwen3vl_4b_bf16.safetensors"
    )
    assert promptkit.writer(["qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"]) is None
    with_picture = promptkit.graph("spooky", "transform", promptkit.WRITERS[0], True)
    assert with_picture["ask"]["inputs"]["image"] == ["small", 0]
    assert with_picture["picture"]["inputs"]["image"] == "picture.png"
    assert with_picture["save"]["class_type"] == "SaveText"
    assert with_picture["ask"]["inputs"]["prompt"].startswith(
        promptkit.PICTURE["transform"]
    )
    assert "spooky" in with_picture["ask"]["inputs"]["prompt"]
    without = promptkit.graph("a fox", "scene", promptkit.WRITERS[0], False)
    assert "image" not in without["ask"]["inputs"] and "picture" not in without
    assert without["writer"]["inputs"]["type"] == "stable_diffusion"


def test_backend_writer_runs_after_ollama_and_before_the_template(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENFIELD_LLM_URL", "http://127.0.0.1:9")
    seen = {}

    def fake_backend(idea, mode, picture, backend, upstream="", key=""):
        seen.update(idea=idea, picture=picture, backend=backend, key=key)
        return (
            "Cold teal shadows and sickly green light with grainy film texture.",
            "Qwen3-VL on your GPU",
        )

    monkeypatch.setattr(promptkit, "ask_backend", fake_backend)
    frame = tmp_path / "frame.png"
    result = promptkit.suggest(
        "spooky", "transform", picture=frame, backend="self-hosted", key="k"
    )
    assert result["source"] == "Qwen3-VL on your GPU"
    assert result["look"].startswith("Restyle this frame: Cold teal shadows")
    assert seen == {
        "idea": "spooky",
        "picture": frame,
        "backend": "self-hosted",
        "key": "k",
    }
    # Without a backend the template answers; the writer is never asked.
    seen.clear()
    assert promptkit.suggest("spooky", "transform")["source"] == "template"
    assert seen == {}


def test_backend_failure_falls_back_to_the_template(monkeypatch):
    monkeypatch.setenv("OPENFIELD_LLM_URL", "http://127.0.0.1:9")

    def broken(*args, **kwargs):
        raise RuntimeError("no listing")

    monkeypatch.setattr(promptkit, "listed", broken, raising=False)
    from aipg_cinema import swap

    monkeypatch.setattr(swap, "listed", broken)
    assert promptkit.ask_backend("spooky", "transform", None, "cloud") is None
    result = promptkit.suggest("spooky", "transform", backend="cloud")
    assert result["source"] == "template"


def test_prompt_helper_route_passes_the_source_frame(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aipg_cinema import app

    monkeypatch.setenv("OPENFIELD_LLM_URL", "http://127.0.0.1:9")
    seen = {}

    def fake_suggest(idea, mode, **context):
        seen.update(context)
        return {"look": "x", "motion": "y", "source": "template"}

    monkeypatch.setattr(app.promptkit, "suggest", fake_suggest)
    client = TestClient(app.create_app(tmp_path / "web"), base_url="http://localhost")
    reply = client.post("/api/prompt-helper", json={"idea": "golden hour"})
    assert reply.status_code == 200
    assert seen["picture"] is None and seen["backend"] == "cloud"
    # An unknown source or look is a 404, not a render.
    missing = client.post(
        "/api/prompt-helper", json={"idea": "golden hour", "source_id": "a" * 32}
    )
    assert missing.status_code == 404
    assert (
        client.post(
            "/api/prompt-helper", json={"idea": "golden hour", "look_id": "zz"}
        ).status_code
        == 422
    )
