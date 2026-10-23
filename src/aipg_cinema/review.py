"""Build a local, synchronized review of completed motion experiments."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote


def build(directory: Path) -> Path:
    destination = directory / "review.html"
    data = []
    labels = {"car": "Toy Car", "bounce": "Bouncing Ball", "pendulum": "Pendulum"}
    for case, label in labels.items():
        source = directory / "motion-fixtures" / case / "source.mp4"
        if not source.is_file():
            continue
        item = {"id": case, "label": label, "videos": []}
        for model, title, path in (
            ("source", "Original", source),
            (
                "ltx",
                "LTX 2.3 · Control",
                directory / f"reshoot-{case}-ltx" / "reshoot.mp4",
            ),
            ("h3", "H3 · Reference", directory / f"reshoot-{case}-h3" / "reshoot.mp4"),
        ):
            state_path = path.parent / "job.json"
            state = json.loads(state_path.read_text()) if state_path.exists() else {}
            item["videos"].append(
                {
                    "model": model,
                    "title": title,
                    "url": quote(
                        Path(os.path.relpath(path, destination.parent)).as_posix()
                    )
                    if path.is_file()
                    else None,
                    "elapsed": state.get("elapsed_seconds"),
                    "gpuSeconds": state.get("provider_gpu_seconds"),
                    "estimatedCredits": state.get("estimated_credits"),
                    "status": "Original"
                    if model == "source"
                    else state.get("status", "Not rendered"),
                }
            )
        data.append(item)
    template = Path(__file__).with_name("review.html").read_text()
    destination.write_text(
        template.replace("__CASES__", json.dumps(data).replace("<", "\\u003c"))
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(build(args.directory).resolve())


if __name__ == "__main__":
    main()
