# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Open in ComfyUI: the exact graph a take ran, packaged to run again.

The zip holds the API-format workflow with numeric node IDs (what the ComfyUI
frontend's Open/drag-and-drop expects), every input file the graph loads,
renamed so they cannot collide with other files in ComfyUI's input folder, and
a README listing the model files the loaders name. Nothing is uploaded or run.
"""

import io
import json
import zipfile
from pathlib import Path

# Loader inputs that name a model file under ComfyUI/models.
MODEL_INPUTS = {
    "unet_name": "diffusion_models",
    "ckpt_name": "checkpoints",
    "clip_name": "text_encoders",
    "vae_name": "vae",
    "lora_name": "loras",
    "model_name": "latent_upscale_models",
}


def numbered(workflow: dict) -> dict:
    """Renumber node IDs 1..n and rewrite every [node, output] link."""
    ids = {old: str(index) for index, old in enumerate(workflow, start=1)}
    graph = {}
    for old, node in workflow.items():
        inputs = {}
        for name, value in node["inputs"].items():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
                and value[0] in ids
                and isinstance(value[1], int)
            ):
                value = [ids[value[0]], value[1]]
            inputs[name] = value
        graph[ids[old]] = {
            **node,
            "inputs": inputs,
            "_meta": {"title": node.get("_meta", {}).get("title") or old},
        }
    return graph


def bundle(render_dir: Path, name: str) -> bytes:
    """Zip the take's workflow, its input files and run instructions."""
    workflow = json.loads((render_dir / "workflow.json").read_text())
    graph = numbered(workflow)
    files: dict[str, Path] = {}
    models: list[tuple[str, str]] = []
    for node in graph.values():
        for key, value in node["inputs"].items():
            if not isinstance(value, str):
                continue
            if key in MODEL_INPUTS:
                models.append((MODEL_INPUTS[key], value))
                continue
            local = render_dir / value
            if "/" in value or not local.is_file() or value == "workflow.json":
                continue
            renamed = f"{name}-{value}"
            files[renamed] = local
            node["inputs"][key] = renamed
    readme = [
        f"{name}: an Openfield take as a ComfyUI workflow",
        "",
        "1. Copy everything in input/ into ComfyUI/input/.",
        "2. In ComfyUI choose Workflow > Open (or drag the JSON onto the canvas)",
        f"   and pick {name}-workflow.json.",
        "3. Check the model files below are installed, then press Run.",
        "",
        "The graph uses core ComfyUI nodes. It is the exact graph Openfield ran,",
        "including the seed, so the same models give the same result.",
        "",
        "Model files:",
        *sorted({f"  ComfyUI/models/{folder}/{file}" for folder, file in models}),
        "",
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{name}-workflow.json", json.dumps(graph, indent=1))
        for renamed, path in sorted(files.items()):
            archive.write(path, f"input/{renamed}")
        archive.writestr("README.txt", "\n".join(readme))
    return buffer.getvalue()
