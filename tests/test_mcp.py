import io
import json

import pytest

from aipg_cinema import mcp


def ask(method, params=None, ident=1):
    return mcp.handle(
        {"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}}
    )


def test_initialize_and_list_tools():
    init = ask("initialize", {"protocolVersion": "2025-06-18"})["result"]
    assert init["capabilities"] == {"tools": {}}
    assert init["serverInfo"]["name"] == "openfield"
    tools = {t["name"]: t for t in ask("tools/list")["result"]["tools"]}
    assert set(tools) == {
        "list_styles",
        "transform_video",
        "generate_shot",
        "run_tool",
        "job_status",
    }
    assert tools["transform_video"]["inputSchema"]["required"] == ["video"]


def test_notifications_get_no_reply_and_unknowns_are_errors():
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert ask("bogus")["error"]["code"] == -32601
    assert ask("tools/call", {"name": "rm_rf"})["error"]["code"] == -32602


def test_only_a_loopback_studio_is_used(monkeypatch):
    monkeypatch.setenv("OPENFIELD_URL", "https://example.com")
    reply = ask("tools/call", {"name": "list_styles", "arguments": {}})["result"]
    assert reply["isError"] and "loopback" in reply["content"][0]["text"]


def test_list_styles_reads_the_studio(monkeypatch):
    monkeypatch.delenv("OPENFIELD_URL", raising=False)
    config = {
        "styles": [
            {"id": "anime", "name": "Hand-drawn anime", "blurb": "Cel", "look": "x"}
        ],
        "look_engine": "klein",
        "connected": True,
    }
    seen = []

    class Response:
        status_code = 200

        def json(self):
            return config

    def request(method, url, **kwargs):
        seen.append((method, url))
        return Response()

    monkeypatch.setattr(mcp.httpx, "request", request)
    reply = ask("tools/call", {"name": "list_styles", "arguments": {}})["result"]
    data = json.loads(reply["content"][0]["text"])
    assert data["styles"] == [
        {"id": "anime", "name": "Hand-drawn anime", "blurb": "Cel"}
    ]
    assert seen == [("GET", "http://127.0.0.1:8797/api/config")]


def test_transform_needs_a_style_or_direction(monkeypatch, tmp_path):
    monkeypatch.setattr(
        mcp, "call", lambda *a, **k: {"styles": [], "look_engine": "klein"}
    )
    reply = ask(
        "tools/call", {"name": "transform_video", "arguments": {"video": "x.mp4"}}
    )["result"]
    assert (
        reply["isError"] and "style or write a direction" in reply["content"][0]["text"]
    )


def test_stdio_loop_answers_each_line(monkeypatch):
    lines = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            "not json",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        ]
    )
    out = io.StringIO()
    monkeypatch.setattr(mcp.sys, "stdin", io.StringIO(lines + "\n"))
    monkeypatch.setattr(mcp.sys, "stdout", out)
    mcp.main()
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert replies[0] == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert replies[1]["error"]["code"] == -32700
    assert len(replies) == 2


@pytest.mark.parametrize("url", ["http://localhost:9000", "http://127.0.0.1:8797/"])
def test_loopback_urls_are_accepted(monkeypatch, url):
    monkeypatch.setenv("OPENFIELD_URL", url)
    assert mcp.studio() == url.rstrip("/")
