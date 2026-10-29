# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Prompt helper: turn a vibe like "make it spooky" into full directions.

A model writes only the creative sentence. Openfield wraps it in the fixed
wording each mode needs, so a small model cannot break the structure. Small
models given the whole job returned the instructions back or invented keys
(2026-10-23). Three writers, tried in order:

1. A local Ollama on a loopback address (default phi4-mini), text only.
2. Qwen3-VL on the video backend, Comfy Cloud or the owned worker, through the
   core TextGenerate node with the clip's first frame or the photo attached,
   so the sentence fits what is actually in the picture. The answer comes
   back as a SaveText file (PreviewAny shows text in the editor only;
   checked 2026-10-28). One job, no retry; a lost reply means a new click.
3. A plain template, so there are always usable directions.
"""

import os
import re
from pathlib import Path

import httpx

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "phi4-mini"
# First listed name the backend has wins; Cloud and the owned worker both
# list the 8B bf16 build.
WRITERS = (
    "qwen3vl_8b_bf16.safetensors",
    "qwen3vl_8b_fp8_scaled.safetensors",
    "qwen3vl_4b_bf16.safetensors",
)
BACKEND_TIMEOUT = 150
PICTURE = {
    "transform": (
        "The picture is the first frame of the footage. Do not describe it: "
        "choose a style that would suit it. "
    ),
    "scene": "The picture is the opening frame: describe what we see in it. ",
}
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


def writer(listing: list[str]) -> str | None:
    return next((name for name in WRITERS if name in listing), None)


def graph(idea: str, mode: str, model: str, picture: bool) -> dict:
    """TextGenerate on the backend; the answer is saved as a text file."""
    ask = (PICTURE[mode] if picture else "") + ASK[mode].format(idea=idea)
    nodes = {
        "writer": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": model,
                "type": "stable_diffusion",
                "device": "default",
            },
        },
        "ask": {
            "class_type": "TextGenerate",
            "inputs": {
                "clip": ["writer", 0],
                "prompt": ask,
                "max_length": 160,
                "sampling_mode": "off",
                "thinking": False,
                "use_default_template": True,
                "mtp": "auto",
            },
        },
        "save": {
            "class_type": "SaveText",
            "inputs": {
                "text": ["ask", 0],
                "filename_prefix": "openfield/helper",
                "format": "txt",
            },
        },
    }
    if picture:
        nodes["picture"] = {
            "class_type": "LoadImage",
            "inputs": {"image": "picture.png"},
        }
        nodes["small"] = {
            "class_type": "ImageScaleToMaxDimension",
            "inputs": {
                "image": ["picture", 0],
                "upscale_method": "area",
                "largest_size": 640,
            },
        }
        nodes["ask"]["inputs"]["image"] = ["small", 0]
    return nodes


def ask_backend(
    idea: str,
    mode: str,
    picture: Path | None,
    backend: str,
    upstream: str = "",
    key: str = "",
) -> tuple[str, str] | None:
    """Qwen3-VL's sentence and a source label, or None when the backend cannot."""
    from .cli import sdk_client
    from .swap import listed

    try:
        model = writer(listed(backend, upstream, "text_encoders", key))
        if not model:
            return None
        base_url = "https://cloud.comfy.org" if backend == "cloud" else None
        with sdk_client(backend, base_url, timeout=BACKEND_TIMEOUT) as client:
            workflow = client.workflows.from_json(
                graph(idea, mode, model, bool(picture))
            )
            if picture:
                workflow.set_input("picture", "image", client.assets.from_file(picture))
            job = client.submit(workflow)
            job.wait(timeout=BACKEND_TIMEOUT)
            if job.status != "succeeded":
                return None
            outputs = job.get_outputs("save")
            if len(outputs) != 1:
                return None
            text = tidy(outputs[0].to_bytes().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - any backend trouble falls back to the template
        return None
    where = "Comfy Cloud" if backend == "cloud" else "your GPU"
    return (text, f"Qwen3-VL on {where}") if len(text) >= 20 else None


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


def suggest(
    idea: str,
    mode: str,
    *,
    picture: Path | None = None,
    backend: str | None = None,
    upstream: str = "",
    key: str = "",
) -> dict:
    if mode not in ASK:
        raise ValueError("Choose transform or scene.")
    idea = " ".join(idea.split())
    if not 2 <= len(idea) <= 200:
        raise ValueError("Describe the idea in 2 to 200 characters.")
    answer = ask_model(idea, mode)
    if not answer and backend:
        answer = ask_backend(idea, mode, picture, backend, upstream, key)
    sentence, source = answer if answer else (template(idea, mode), "template")
    if mode == "scene":
        return {"prompt": sentence, "motion": "", "source": source}
    look = f"Restyle this frame: {sentence} {KEEP_FRAME}"
    motion = f"{sentence} The look holds for the whole shot. {FOLLOW}"
    return {"look": look, "motion": motion, "source": source}
