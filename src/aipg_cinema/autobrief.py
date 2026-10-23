# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Draft a product brief from a photo with an open-weights model on the Grid.

One bounded request, no retries, a hard cost ceiling. The result only fills
the editable form; it never creates a project or starts a render. Fields the
model gets wrong are dropped rather than failing the whole draft.
"""

import base64
import io
import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image
from pydantic import ValidationError

from .brief import ProductBrief

DEFAULT_URL = "https://api.aipowergrid.io"
VISION_PREFERENCE = ("deepseek-v4-flash-nvfp4",)
TEXT_PREFERENCE = ("gpt-oss-120b", "qwen3:8b")
MAX_COST_USD = 0.01
MAX_TOKENS = 1500
TIMEOUT = 90.0
PATTERNS = (
    "problem",
    "contrarian",
    "curiosity",
    "result-first",
    "scenario",
    "pattern-interrupt",
    "listicle",
)
SYSTEM = (
    "You write short vertical video ad briefs. Return ONLY a JSON object with "
    "keys: name (string, at most 60 characters; keep a provided name), tone "
    "(premium, playful, bold or calm), setting (one concrete place the product "
    "lives, at most 120 characters, with simple surfaces and soft props; avoid "
    "complex mechanical objects such as dumbbells, bikes, tools or machines, "
    "which image models draw badly), benefits (up to 3 concrete strings, at most "
    "60 characters each, no invented statistics), hook (the opening line, at "
    "most 10 words), hook_pattern (one of " + ", ".join(PATTERNS) + "), "
    "tagline (at most 60 characters) and cta (at most 30 characters). Do not "
    "quote or describe text or logos printed on the product."
)


class AutoBriefError(Exception):
    """A user-facing reason the draft is unavailable; the form stays manual."""


def _models(client: httpx.Client, base: str, key: str) -> list[dict]:
    response = client.get(f"{base}/v1/models", headers={"apikey": key})
    response.raise_for_status()
    data = response.json()
    return data.get("data", data) if isinstance(data, dict) else data


def _pick(models: list[dict], vision: bool) -> dict | None:
    preference = VISION_PREFERENCE if vision else TEXT_PREFERENCE
    usable = {
        m["id"]: m
        for m in models
        if m.get("pricing")
        and (not vision or "image" in (m.get("input_modalities") or []))
    }
    for model_id in preference:
        if model_id in usable:
            return usable[model_id]
    return next(iter(usable.values()), None)


def _cost(model: dict, prompt_tokens: int, completion_tokens: int) -> float:
    price = model["pricing"]
    return (
        prompt_tokens * price["input_per_mtok_usd"]
        + completion_tokens * price["output_per_mtok_usd"]
    ) / 1_000_000


def _image(photo: Path) -> str:
    image = Image.open(photo).convert("RGB")
    image.thumbnail((768, 768))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def _json(content: str) -> dict:
    match = re.search(r"\{.*\}", content or "", flags=re.DOTALL)
    if not match:
        raise AutoBriefError("The model did not return a brief. Fill it in manually.")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise AutoBriefError(
            "The model returned an unreadable brief. Fill it in manually."
        ) from error
    if not isinstance(data, dict):
        raise AutoBriefError("The model did not return a brief. Fill it in manually.")
    return data


def clean(data: dict, name: str = "") -> tuple[ProductBrief, str, list[str]]:
    """Keep every field that passes the brief rules; report the ones dropped."""
    fields = {
        "name": (name or str(data.get("name") or "")).strip()[:60],
        "tone": data.get("tone"),
        "setting": str(data.get("setting") or "")[:200],
        "benefits": [
            str(item)[:80] for item in (data.get("benefits") or []) if str(item).strip()
        ][:3],
        "hook": str(data.get("hook") or ""),
        "tagline": str(data.get("tagline") or "")[:80],
        "cta": str(data.get("cta") or "")[:40],
    }
    dropped = []
    if fields["tone"] not in ("premium", "playful", "bold", "calm"):
        fields.pop("tone")
        dropped.append("tone")
    for key in ("setting", "benefits", "hook", "tagline", "cta"):
        try:
            ProductBrief(name=fields["name"] or "x", **{key: fields[key]})
        except ValidationError:
            fields.pop(key)
            dropped.append(key)
    if not fields["name"]:
        raise AutoBriefError("Add the product name, then try again.")
    pattern = data.get("hook_pattern") if "hook" in fields else ""
    return (
        ProductBrief(**fields),
        pattern if pattern in PATTERNS else "",
        dropped,
    )


def suggest(
    photo: Path,
    name: str = "",
    *,
    key: str | None = None,
    base_url: str | None = None,
    client: httpx.Client | None = None,
) -> dict:
    key = key if key is not None else os.environ.get("GRID_API_KEY", "")
    if not key.strip():
        raise AutoBriefError(
            "Fill from photo needs GRID_API_KEY on the server. Fill the brief manually."
        )
    base = (base_url or os.environ.get("GRID_BASE_URL") or DEFAULT_URL).rstrip("/")
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        try:
            models = _models(client, base, key)
        except (httpx.HTTPError, ValueError) as error:
            raise AutoBriefError(
                "The Grid is unavailable. Fill the brief manually."
            ) from error
        model = _pick(models, vision=True)
        content = [{"type": "image_url", "image_url": {"url": _image(photo)}}]
        if model is None:
            if not name.strip():
                raise AutoBriefError(
                    "No vision model is online. Add the product name, then try again."
                )
            model, content = _pick(models, vision=False), []
            if model is None:
                raise AutoBriefError(
                    "No suitable Grid model is online. Fill the brief manually."
                )
        # Worst case: a generous prompt estimate plus every allowed output token.
        ceiling = _cost(model, 2000, MAX_TOKENS)
        if ceiling > MAX_COST_USD:
            raise AutoBriefError(
                f"Drafting could cost up to USD {ceiling:.4f}, above the "
                f"USD {MAX_COST_USD} cap. Fill the brief manually."
            )
        text = f"Product name: {name.strip()}" if name.strip() else "Name the product."
        body = {
            "model": model["id"],
            "max_tokens": MAX_TOKENS,
            "temperature": 0.7,
            "reasoning_effort": "low",
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": [{"type": "text", "text": text}, *content]},
            ],
        }
        started = time.monotonic()
        try:
            response = client.post(
                f"{base}/v1/chat/completions",
                headers={"apikey": key, "Idempotency-Key": uuid.uuid4().hex},
                json=body,
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise AutoBriefError(
                "The brief request failed. Nothing was retried; fill it in manually."
            ) from error
        usage = result.get("usage") or {}
        cost = _cost(
            model,
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
        )
        choice = (result.get("choices") or [{}])[0]
        brief, pattern, dropped = clean(
            _json((choice.get("message") or {}).get("content") or ""), name
        )
        return {
            "brief": brief.model_dump(),
            "hook_pattern": pattern,
            "dropped": dropped,
            "model": model["id"],
            "vision": bool(content),
            "cost_usd": round(cost, 6),
            "seconds": round(time.monotonic() - started, 2),
        }
    finally:
        if own:
            client.close()
