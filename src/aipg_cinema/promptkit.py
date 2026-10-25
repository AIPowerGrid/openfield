# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Prompt helper: turn a vibe like "make it spooky" into full directions.

A local model (any Ollama on a loopback address, default phi4-mini) writes
only the creative sentence. Openfield wraps it in the fixed wording each
mode needs, so a small model cannot break the structure. Small models given
the whole job returned the instructions back or invented keys (2026-10-23).
Without a reachable model, a plain template still gives usable directions.
"""

import os
import re

import httpx

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "phi4-mini"
KEEP_FRAME = "Keep the same subjects, poses, setting and composition."
FOLLOW = "Follow the source motion, subjects and camera exactly in one continuous shot."
ASK = {
    "transform": (
        "Describe only a visual style to paint over existing footage: {idea}. "
        "One or two sentences naming the medium, colour palette, lighting and "
        "textures. Never mention places, objects, people, weather or events: the "
        "footage keeps its own content. Reply with the sentences only."
    ),
    "scene": (
        "Write a three-sentence shot description for a five-second video about: "
        "{idea}. Say what we see, the setting and light, and what moves. No "
        "dialogue, no on-screen text, no real people's names. Reply with the "
        "description only."
    ),
}


EXAMPLES = {
    "transform": [
        (
            "golden hour",
            "Low warm amber sunlight with long soft shadows, honey-gold highlights, gently lifted blacks and fine 35mm film grain.",
        ),
        (
            "like a comic book",
            "Bold black ink outlines, flat saturated primary colours, halftone dot shading and crisp hard-edged comic-panel lighting.",
        ),
    ],
    "scene": [
        (
            "a lighthouse in a storm",
            "A white lighthouse stands on a black rocky point as huge waves burst against it at dusk. Rain slants through the beam as it sweeps across the churning sea. Gulls fight the wind above the spray.",
        ),
    ],
}


def endpoint() -> str:
    url = os.environ.get("OPENFIELD_LLM_URL", DEFAULT_URL).rstrip("/")
    if httpx.URL(url).host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("OPENFIELD_LLM_URL must be a loopback address.")
    return url


def tidy(text: str) -> str:
    text = re.sub(r"```(?:json|text)?", "", text)
    text = re.sub(r"^\s*(sure|here(?: is|'s)[^:]*):\s*", "", text, flags=re.IGNORECASE)
    text = " ".join(text.split()).strip(' "')
    # Small models sometimes answer "Medium/Look: ...; Lighting: ..." lists.
    text = re.sub(r"\b[A-Z][\w/ ]{2,20}:\s*", "", text)
    # Keep whole sentences within a sensible length.
    sentences = re.findall(r"[^.!?]+[.!?]", text) or [text]
    kept = ""
    for sentence in sentences:
        if len(kept) + len(sentence) > 420:
            break
        kept += sentence
    return kept.strip()


def ask_model(idea: str, mode: str, timeout: float = 90) -> tuple[str, str] | None:
    """The model's sentence and name, or None when no model answers."""
    model = os.environ.get("OPENFIELD_LLM_MODEL", DEFAULT_MODEL)
    try:
        response = httpx.post(
            endpoint() + "/api/chat",
            json={
                "model": model,
                "stream": False,
                "keep_alive": "5m",
                "options": {"temperature": 0.4, "num_predict": 160},
                "messages": [
                    message
                    for example, reply in EXAMPLES[mode]
                    for message in (
                        {"role": "user", "content": ASK[mode].format(idea=example)},
                        {"role": "assistant", "content": reply},
                    )
                ]
                + [{"role": "user", "content": ASK[mode].format(idea=idea)}],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        text = tidy(response.json()["message"]["content"])
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    return (text, model) if len(text) >= 20 else None


def template(idea: str, mode: str) -> str:
    idea = idea.strip().rstrip(".")
    if mode == "scene":
        return (
            f"{idea[:1].upper()}{idea[1:]}. Cinematic lighting and a clear subject, "
            "with natural movement through one continuous shot."
        )
    idea = re.sub(r"^(make it|turn it into|like|as)\s+", "", idea, flags=re.IGNORECASE)
    return (
        f"Give it a {idea} look, with a colour palette, lighting and textures to match."
    )


def suggest(idea: str, mode: str) -> dict:
    if mode not in ASK:
        raise ValueError("Choose transform or scene.")
    idea = " ".join(idea.split())
    if not 2 <= len(idea) <= 200:
        raise ValueError("Describe the idea in 2 to 200 characters.")
    answer = ask_model(idea, mode)
    sentence, source = answer if answer else (template(idea, mode), "template")
    if mode == "scene":
        return {"prompt": sentence, "motion": "", "source": source}
    look = f"Restyle this frame: {sentence} {KEEP_FRAME}"
    motion = f"{sentence} The look holds for the whole shot. {FOLLOW}"
    return {"look": look, "motion": motion, "source": source}
