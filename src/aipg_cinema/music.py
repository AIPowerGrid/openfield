# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""One instrumental bed for a whole short from open-weights ACE-Step on the Grid.

Finished shorts use one music track with shot sound muted: per-shot generated
sound changed at every cut and the owner rejected it. One bounded request, no
retries; the caller stores the WAV like any uploaded soundtrack.
"""

import math
import os

import httpx

MODEL = "ace-step-v1.5-xl-turbo"
TIMEOUT = 300.0
MAX_BYTES = 40 * 1024 * 1024
STYLES = {
    "premium": (
        (
            "elegant minimal instrumental for a premium product ad, soft piano, warm "
            "strings, subtle pulse, no vocals"
        ),
        90,
        "D Major",
    ),
    "playful": (
        "upbeat playful pop instrumental, bouncy bass, claps, bright synths, no vocals",
        118,
        "C Major",
    ),
    "bold": (
        (
            "dark confident electronic instrumental for a streetwear ad, punchy kick, "
            "deep sub bass, crisp hi-hats, warm synth stabs, no vocals"
        ),
        120,
        "F minor",
    ),
    "calm": (
        (
            "warm calm morning instrumental, acoustic guitar, soft piano, brushed drums, "
            "gentle uplifting groove, no vocals"
        ),
        92,
        "G Major",
    ),
}


class MusicError(Exception):
    """A user-facing reason no track was made; nothing was retried."""


def request_body(
    tone: str, frames: int, seed: int = 42, prompt: str | None = None
) -> dict:
    default, bpm, key = STYLES[tone]
    prompt = prompt or default
    # Cover the short plus a little tail for the fade; ACE-Step takes 10-300 s.
    seconds = min(60, max(10, math.ceil(frames / 24) + 2))
    return {
        "model": MODEL,
        "prompt": prompt,
        "seconds": seconds,
        "bpm": bpm,
        "key_scale": key,
        "time_signature": "4/4",
        "seed": seed,
    }


def generate(
    body: dict,
    idempotency_key: str,
    *,
    key: str | None = None,
    base_url: str | None = None,
    client: httpx.Client | None = None,
) -> tuple[bytes, dict]:
    key = key if key is not None else os.environ.get("GRID_API_KEY", "")
    if not key.strip():
        raise MusicError(
            "Music needs GRID_API_KEY on the server. Upload a track instead."
        )
    base = (
        base_url or os.environ.get("GRID_BASE_URL") or "https://api.aipowergrid.io"
    ).rstrip("/")
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        try:
            response = client.post(
                f"{base}/v1/audio/generations",
                headers={"apikey": key, "Idempotency-Key": idempotency_key},
                json=body,
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
            url = result["data"][0]["url"]
            if not url.startswith("https://"):
                raise ValueError("Unexpected media URL.")
            audio = client.get(url, timeout=120.0)
            audio.raise_for_status()
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            raise MusicError(
                "Music generation failed. Nothing was retried; upload a track instead."
            ) from error
        if not 0 < len(audio.content) <= MAX_BYTES:
            raise MusicError("The generated track was empty or too large.")
        grid = result.get("grid") or {}
        return audio.content, {
            "model": grid.get("model", body["model"]),
            "job_id": grid.get("job_id"),
            "seconds": body["seconds"],
            "prompt": body["prompt"],
        }
    finally:
        if own:
            client.close()
