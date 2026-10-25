# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Openfield as an MCP server: let Claude or any MCP agent drive your studio.

A stdio JSON-RPC server (Model Context Protocol, tools only) that talks to a
running Openfield studio over its local HTTP API, so every studio limit,
estimate and receipt still applies. Start the studio first, then register:

    claude mcp add openfield -- uv run openfield-mcp

Set OPENFIELD_URL when the studio is not on http://127.0.0.1:8797. Every
render tool sends exactly one request; nothing is retried.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

PROTOCOL = "2025-06-18"
TERMINAL = ("succeeded", "failed", "cancelled", "needs_review", "needs_recovery")


def studio() -> str:
    url = os.environ.get("OPENFIELD_URL", "http://127.0.0.1:8797").rstrip("/")
    host = httpx.URL(url).host
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("OPENFIELD_URL must be a loopback studio address.")
    return url


def call(method: str, path: str, **kwargs) -> dict | list:
    response = httpx.request(method, studio() + path, timeout=300, **kwargs)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:300]
        raise RuntimeError(f"Studio refused ({response.status_code}): {detail}")
    return response.json()


def upload(path: str) -> str:
    file = Path(path).expanduser()
    if not file.is_file():
        raise ValueError(f"No such video: {file}")
    with file.open("rb") as handle:
        return call("POST", "/api/sources", files={"file": (file.name, handle)})[
            "source_id"
        ]


def wait(path: str, timeout: float, terminal=TERMINAL) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        item = call("GET", path)
        if not item.get("active") and item.get("status") in terminal:
            return item
        if time.monotonic() > deadline:
            return {**item, "note": "Still running; check again with job_status."}
        time.sleep(5)


def save(url: str | None, save_to: str | None) -> str | None:
    if not url or not save_to:
        return None
    target = Path(save_to).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", studio() + url, timeout=300) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
    return str(target)


def summary(item: dict, kind: str, save_to: str | None = None) -> dict:
    output = item.get("output_url")
    return {
        "kind": kind,
        "id": item.get("id"),
        "status": item.get("status"),
        "error": item.get("error"),
        "output_url": studio() + output if output else None,
        "saved_to": save(output, save_to)
        if item.get("status") == "succeeded"
        else None,
        "note": item.get("note"),
    }


def list_styles(_: dict) -> dict:
    config = call("GET", "/api/config")
    return {
        "styles": [
            {"id": s["id"], "name": s["name"], "blurb": s["blurb"]}
            for s in config.get("styles", [])
        ],
        "look_engine": config.get("look_engine"),
        "connected": config.get("connected"),
    }


def transform_video(args: dict) -> dict:
    """Restyle a local clip: opening look from the style, then one take."""
    config = call("GET", "/api/config")
    style = next(
        (s for s in config.get("styles", []) if s["id"] == args.get("style")), None
    )
    if args.get("style") and not style:
        raise ValueError("Unknown style; call list_styles.")
    direction = style["look"] if style else args.get("direction", "").strip()
    motion = style["motion"] if style else direction
    if not direction:
        raise ValueError("Choose a style or write a direction.")
    seconds = int(args.get("seconds", 5))
    window = {
        "frame_format": args.get("framing", "landscape"),
        "source_start": float(args.get("start", 0)),
        **({"seconds": seconds} if seconds != 5 else {}),
    }
    source = upload(args["video"])
    klein = str(config.get("look_engine", "")).startswith("klein")
    look = call(
        "POST",
        "/api/look-jobs",
        json={
            "request_id": uuid.uuid4().hex,
            "source_id": source,
            "prompt": direction,
            "seed": int(args.get("seed", 42)),
            "denoise": None if klein else 0.65,
            "frame_index": 0,
            **window,
        },
    )
    look = wait(f"/api/look-jobs/{look['id']}", 300)
    if look.get("status") != "succeeded":
        return summary(look, "look")
    take = call(
        "POST",
        "/api/jobs",
        json={
            "request_id": uuid.uuid4().hex,
            "mode": "video",
            "source_id": source,
            "look_id": look["id"],
            "prompt": motion,
            "art_direction": direction,
            "motion_prompt": motion,
            "seed": int(args.get("seed", 42)),
            **window,
        },
    )
    if not args.get("wait", True):
        return summary(take, "take")
    return summary(wait(f"/api/jobs/{take['id']}", 900), "take", args.get("save_to"))


def generate_shot(args: dict) -> dict:
    """A five-second shot from words (text to video)."""
    take = call(
        "POST",
        "/api/jobs",
        json={
            "request_id": uuid.uuid4().hex,
            "mode": "text",
            "prompt": args["prompt"],
            "seed": int(args.get("seed", 42)),
            "frame_format": args.get("framing", "landscape"),
        },
    )
    if not args.get("wait", True):
        return summary(take, "take")
    return summary(wait(f"/api/jobs/{take['id']}", 600), "take", args.get("save_to"))


def run_tool(args: dict) -> dict:
    body = {
        "request_id": uuid.uuid4().hex,
        "tool": args["tool"],
        **(
            {"take_id": args["take_id"]}
            if args.get("take_id")
            else {"source_id": upload(args["video"])}
        ),
        **{k: args[k] for k in ("background", "target", "fit") if k in args},
    }
    run = call("POST", "/api/tools", json=body)
    if not args.get("wait", True):
        return summary(run, "tool")
    return summary(wait(f"/api/tools/{run['id']}", 900), "tool", args.get("save_to"))


def job_status(args: dict) -> dict:
    kind = args.get("kind", "take")
    path = {"take": "/api/jobs/", "tool": "/api/tools/", "look": "/api/look-jobs/"}[
        kind
    ]
    return summary(call("GET", path + args["id"]), kind, args.get("save_to"))


SAVE = {"type": "string", "description": "Optional local path to save the MP4 to."}
WAIT = {"type": "boolean", "description": "Wait for the result (default true)."}
TOOLS = {
    "list_styles": (
        list_styles,
        "List Openfield's Transform styles and whether the studio is connected.",
        {},
        [],
    ),
    "transform_video": (
        transform_video,
        (
            "Restyle a local video clip with a Transform style or your own direction, "
            "keeping its motion, timing and sound. Makes one opening look, then one "
            "5, 10 or 15 second take on the studio's GPU or Comfy Cloud."
        ),
        {
            "video": {"type": "string", "description": "Local path of the clip."},
            "style": {"type": "string", "description": "Style id from list_styles."},
            "direction": {
                "type": "string",
                "description": "Your own art direction instead of a style.",
            },
            "seconds": {"type": "integer", "enum": [5, 10, 15]},
            "framing": {"type": "string", "enum": ["landscape", "portrait", "square"]},
            "start": {"type": "number", "description": "Start time in the clip (s)."},
            "seed": {"type": "integer"},
            "wait": WAIT,
            "save_to": SAVE,
        },
        ["video"],
    ),
    "generate_shot": (
        generate_shot,
        "Make one five-second shot from a written description (LTX-2.5).",
        {
            "prompt": {"type": "string"},
            "framing": {"type": "string", "enum": ["landscape", "portrait", "square"]},
            "seed": {"type": "integer"},
            "wait": WAIT,
            "save_to": SAVE,
        },
        ["prompt"],
    ),
    "run_tool": (
        run_tool,
        (
            "Run FPS boost, remove background, upscale, depth map, reframe or auto "
            "captions on a local clip or a finished take, or extend a finished "
            "take by 5 s."
        ),
        {
            "tool": {
                "type": "string",
                "enum": [
                    "fps-boost",
                    "remove-background",
                    "upscale",
                    "depth-map",
                    "reframe",
                    "extend",
                    "captions",
                ],
            },
            "video": {"type": "string", "description": "Local path of the clip."},
            "take_id": {"type": "string", "description": "Or a finished take's id."},
            "background": {
                "type": "string",
                "enum": ["green", "black", "white", "matte"],
            },
            "target": {"type": "string", "enum": ["portrait", "landscape", "square"]},
            "fit": {"type": "string", "enum": ["blur", "crop"]},
            "wait": WAIT,
            "save_to": SAVE,
        },
        ["tool"],
    ),
    "job_status": (
        job_status,
        "Check a take, look or tool run and optionally save its result.",
        {
            "id": {"type": "string"},
            "kind": {"type": "string", "enum": ["take", "tool", "look"]},
            "save_to": SAVE,
        },
        ["id"],
    ),
}


def handle(message: dict) -> dict | None:
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None  # notifications need no reply
    try:
        if method == "initialize":
            result = {
                "protocolVersion": message.get("params", {}).get(
                    "protocolVersion", PROTOCOL
                ),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "openfield", "version": "0.1.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": description,
                        "inputSchema": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    }
                    for name, (_, description, properties, required) in TOOLS.items()
                ]
            }
        elif method == "tools/call":
            params = message.get("params", {})
            if params.get("name") not in TOOLS:
                raise LookupError(f"Unknown tool {params.get('name')}")
            try:
                output = TOOLS[params["name"]][0](params.get("arguments") or {})
                result = {
                    "content": [{"type": "text", "text": json.dumps(output, indent=1)}]
                }
            except (
                RuntimeError,
                ValueError,
                KeyError,
                OSError,
                httpx.HTTPError,
            ) as error:
                result = {
                    "content": [{"type": "text", "text": f"Error: {error}"}],
                    "isError": True,
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": ident,
                "error": {"code": -32601, "message": f"Unknown method {method}"},
            }
        return {"jsonrpc": "2.0", "id": ident, "result": result}
    except LookupError as error:
        return {
            "jsonrpc": "2.0",
            "id": ident,
            "error": {"code": -32602, "message": str(error)},
        }


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            reply = handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
