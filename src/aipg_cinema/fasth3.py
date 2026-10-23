# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Opt-in native FastH3 comparison, not a studio default or Grid SKU."""

import re

from .reshoot import graph as reference_video_graph


def graph(
    prompt: str,
    seed: int = 42,
    *,
    frame_format: str = "square",
    appearance: bool = False,
    audio_reference: bool = False,
    video_reference: bool = False,
) -> dict:
    """Generate sound and picture; references do not promise exact preservation."""
    sizes = {"landscape": (1344, 768), "portrait": (768, 1344), "square": (768, 768)}
    if frame_format not in sizes:
        raise ValueError("Choose portrait, square or landscape framing.")
    if not prompt.strip() or len(prompt) > 4000:
        raise ValueError("Describe the scene in 1 to 4000 characters.")
    if type(seed) is not int or not 0 <= seed <= 2**53 - 1:
        raise ValueError("Use an integer seed between zero and 2**53 - 1.")
    available = set()
    if appearance:
        available.add(("Picture", "1"))
    if audio_reference:
        available.add(("Audio", "1"))
    if video_reference:
        available.add(("Video", "1"))
    if any(
        label not in available
        for label in re.findall(r"<(Picture|Audio|Video)\s*(\d+)>", prompt)
    ):
        raise ValueError("The prompt names a reference that was not supplied.")
    workflow = reference_video_graph("fasth3", prompt, seed)
    reference = workflow["reference"]["inputs"]
    if not video_reference:
        del workflow["source"], workflow["frames"]
        del reference["ref_videos.ref_video_0"]
    reference.update(
        prompt=prompt,
        width=sizes[frame_format][0],
        height=sizes[frame_format][1],
    )
    if appearance:
        workflow["appearance"] = {
            "class_type": "LoadImage",
            "inputs": {"image": "appearance.png"},
        }
        reference["ref_images.ref_image_0"] = ["appearance", 0]
    if audio_reference:
        workflow["reference-audio"] = {
            "class_type": "LoadAudio",
            "inputs": {"audio": "reference.wav"},
        }
        reference["ref_audios.ref_audio_0"] = ["reference-audio", 0]
    workflow["decode-audio"] = {
        "class_type": "VAEDecodeAudio",
        "inputs": {"samples": ["sample", 0], "vae": ["audio-vae", 0]},
    }
    workflow["video"]["inputs"]["audio"] = ["decode-audio", 0]
    workflow["save"]["inputs"].update(
        filename_prefix="aipg-cinema/fasth3-comparison", codec="h264"
    )
    workflow["save"]["inputs"].pop("format.codec", None)
    return workflow
