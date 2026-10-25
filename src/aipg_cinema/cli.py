"""Official Comfy SDK runner; no generation occurs without --execute."""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from ipaddress import ip_address
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

import httpx
from comfy_sdk import Comfy, ComfyError
from filelock import FileLock
from filelock import Timeout as LockTimeout

_CLIENT_CONFIG_LOCK = RLock()


def load_workflow(path: Path, output_node: str) -> dict:
    graph = json.loads(path.read_text())
    if (
        not isinstance(graph, dict)
        or not graph
        or not all(
            isinstance(node, dict)
            and isinstance(node.get("class_type"), str)
            and isinstance(node.get("inputs"), dict)
            for node in graph.values()
        )
    ):
        raise ValueError("Export an API-format workflow, not the canvas-format JSON.")
    if output_node not in graph:
        raise ValueError(f"Output node {output_node} is not in this workflow.")
    return graph


def cloud_only() -> None:
    url = os.environ.get("COMFY_BASE_URL", "").strip() or "https://cloud.comfy.org"
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "cloud.comfy.org"
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("This platform proof only targets https://cloud.comfy.org.")


def local_url(url: str) -> str:
    parsed = urlsplit(url)
    try:
        loopback = (
            parsed.hostname == "localhost"
            or ip_address(parsed.hostname or "").is_loopback
        )
        valid_port = parsed.port is not None
    except ValueError:
        loopback, valid_port = False, False
    if (
        parsed.scheme != "http"
        or not loopback
        or not valid_port
        or parsed.path not in ("", "/")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Self-hosted SDK execution requires an explicit loopback HTTP "
            "URL and port. Use an SSH tunnel for remote workers."
        )
    return url.rstrip("/")


@contextmanager
def sdk_client(
    backend: str,
    base_url: str | None = None,
    *,
    credential_scope: str = "primary",
    timeout: float = 120.0,
):
    with _CLIENT_CONFIG_LOCK:
        client = configured_client(backend, base_url, credential_scope, timeout)
    with client:
        yield client


def configured_client(
    backend: str,
    base_url: str | None,
    credential_scope: str = "primary",
    timeout: float = 120.0,
):
    if credential_scope not in ("primary", "look", "cloud-look"):
        raise ValueError("Unknown credential scope.")
    if credential_scope == "look" and backend != "self-hosted":
        raise ValueError("MOSS looks require a qualified self-hosted runtime.")
    if credential_scope == "cloud-look" and backend != "cloud":
        raise ValueError("Cloud looks require the official Cloud runtime.")
    previous_url = os.environ.get("COMFY_BASE_URL")
    previous_key = os.environ.get("COMFY_API_KEY")
    try:
        if base_url is not None:
            os.environ["COMFY_BASE_URL"] = base_url
        if backend == "cloud":
            cloud_only()
        elif backend == "self-hosted":
            local_url(os.environ.get("COMFY_BASE_URL", ""))
            # Cloud credentials must never be forwarded to a local worker proxy.
            os.environ.pop("COMFY_API_KEY", None)
        else:
            raise ValueError("Choose cloud or self-hosted execution.")
        return Comfy(
            client_info="openreshoot",
            timeout=timeout,
            api_key=os.environ.get(
                "COMFY_LOOK_LOCAL_TOKEN"
                if credential_scope == "look"
                else "COMFY_LOCAL_TOKEN"
            )
            if backend == "self-hosted"
            else None,
        )
    finally:
        for name, old in (
            ("COMFY_BASE_URL", previous_url),
            ("COMFY_API_KEY", previous_key),
        ):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def observer_active(run_dir: Path) -> bool:
    if not run_dir.is_dir():
        return False
    try:
        with FileLock(run_dir / ".observer.lock", timeout=0):
            return False
    except LockTimeout:
        return True


def save_state(run_dir: Path, state: dict) -> None:
    temporary = run_dir / "job.json.tmp"
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(run_dir / "job.json")


# GPU numeric errors (NaN) come back either as a failed save or as a video of
# solid black frames; seen intermittently on Comfy Cloud (2026-10-23), where
# the identical workflow then rendered cleanly.
NUMERIC_FAILURE = (
    "The GPU hit a numeric error and the video came back blank. Nothing was "
    "retried; press Generate again (a new seed can help)."
)


def solid_black(video: Path) -> bool:
    """True when sampled frames are all black: limited-range luma at most 17."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            "select='not(mod(n\\,12))',signalstats,"
            + "metadata=print:key=lavfi.signalstats.YMAX:file=-",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    peaks = [
        float(line.split("=", 1)[1])
        for line in result.stdout.splitlines()
        if "YMAX=" in line
    ]
    return bool(peaks) and max(peaks) <= 17


def collect(job, run_dir: Path, state: dict) -> None:
    print(f"Job: {job.id}", flush=True)
    job.wait(timeout=1800)
    # A self-hosted proxy reports "expired" when one status check to its
    # ComfyUI fails, e.g. over a tunnel while the GPU is busy, although the
    # job then finishes normally. Look again for a while before giving up.
    for _ in range(36):
        if job.status != "expired":
            break
        time.sleep(5)
        job.refresh()
        if job.status not in ("expired", "succeeded", "failed", "canceled"):
            job.wait(timeout=1800)
    state["status"] = job.status
    save_state(run_dir, state)
    if job.status != "succeeded":
        if "NaN" in str(job.error or ""):
            save_state(run_dir, {**state, "failure": "numeric"})
            raise RuntimeError(NUMERIC_FAILURE)
        raise RuntimeError(
            f"Comfy job ended {job.status}; no replacement was submitted."
        )
    outputs = job.get_outputs(state["output_node"])
    is_look = bool(state.get("look_render"))
    media = [
        output
        for output in outputs
        if output.content_type.startswith("image/" if is_look else "video/")
    ]
    if not media or (is_look and len(media) != 1):
        raise ValueError(
            "The selected node must return one look image."
            if is_look
            else "The selected node returned no video. Check its output node ID."
        )
    if (state.get("generation_mode") or state.get("reshoot")) and len(media) != 1:
        raise ValueError(
            "A shot must return exactly one video. Inspect the saved job; no replacement was submitted."
        )
    paths = []
    for index, output in enumerate(media, start=1):
        suffix = Path(output.name).suffix.lower()
        if suffix not in ((".png",) if is_look else (".mp4", ".webm", ".mov", ".mkv")):
            raise ValueError("Unexpected output extension; inspect the saved job.")
        prefix = "image" if is_look else "clip"
        destination = run_dir / f"{prefix}-{index:02d}{suffix}"
        partial = destination.with_suffix(destination.suffix + ".partial")
        output.to_file(partial)
        partial.replace(destination)
        if not is_look and solid_black(destination):
            # Final: recovering would only fetch the same blank video again.
            save_state(run_dir, {**state, "failure": "numeric"})
            raise RuntimeError(NUMERIC_FAILURE)
        paths.append(destination.name)
        print(f"Output: {destination.resolve()}")
    state["outputs"] = paths
    state.setdefault("elapsed_seconds", round(time.time() - state["started_at"], 2))
    if (
        state.get("balance_before_cents") is not None
        and "actual_cost_cents" not in state
    ):
        from .estimates import cloud_balance_cents

        after = cloud_balance_cents()
        # Billing can lag the job; a zero or negative change is unknown, not
        # free, so the label falls back to measured time.
        if after is not None and state["balance_before_cents"] - after > 0.01:
            state["actual_cost_cents"] = round(state["balance_before_cents"] - after, 4)
    if state.get("render_profile") == "single-pass-audio":
        from .generation import finish as finish_generation

        destination = finish_generation(
            run_dir, run_dir / paths[0], frame_format=state["frame_format"]
        )
        state["reshoot_output"] = destination.name
        print(f"Finished speech shot: {destination.resolve()}")
    elif state.get("generation_mode"):
        from .generation import finish as finish_generation

        destination = finish_generation(run_dir, run_dir / paths[0])
        state["reshoot_output"] = destination.name
        print(f"Finished shot: {destination.resolve()}")
    elif state.get("reshoot"):
        from .reshoot import finish

        destination = finish(run_dir, run_dir / paths[0], state.get("seconds", 5))
        state["reshoot_output"] = destination.name
        print(f"Reshoot with original soundtrack: {destination.resolve()}")
    elif state.get("tool"):
        state["tool_output"] = paths[0]
    if is_look:
        from .reshoot import prepare_look

        destination = prepare_look(
            run_dir / paths[0],
            run_dir,
            frame_format=state.get("frame_format", "landscape"),
        )
        state["look_output"] = destination.name
        print(f"Opening look: {destination.resolve()}")
    save_state(run_dir, state)


def submit_and_collect(
    client, workflow, run_dir: Path, output_node: str, **extra
) -> None:
    with FileLock(run_dir / ".observer.lock", timeout=0):
        submit_locked(client, workflow, run_dir, output_node, **extra)


def submit_locked(client, workflow, run_dir: Path, output_node: str, **extra) -> None:
    state = {
        "idempotency_key": str(uuid.uuid4()),
        "job_id": None,
        "output_node": output_node,
        "started_at": time.time(),
        "status": "submitting",
        "cost_usd": None,
        **extra,
    }
    if state.get("backend") == "cloud":
        from .estimates import cloud_balance_cents

        # Spend is measured from the balance; overlapping jobs blur it.
        state["balance_before_cents"] = cloud_balance_cents()
    save_state(run_dir, state)
    job = client.submit(workflow, idempotency_key=state["idempotency_key"])
    state.update(job_id=job.id, status=job.status)
    save_state(run_dir, state)
    collect(job, run_dir, state)


def render(args: argparse.Namespace) -> None:
    graph = load_workflow(args.workflow, args.output_node)
    if not args.execute:
        raise ValueError("No job sent. --execute requires prior spending approval.")
    with sdk_client(args.backend) as client:
        workflow = client.workflows.from_json(graph)
        args.run_dir.mkdir(parents=True, exist_ok=False)
        submit_and_collect(
            client,
            workflow,
            args.run_dir,
            args.output_node,
            backend=args.backend,
            base_url=os.environ.get("COMFY_BASE_URL", "https://cloud.comfy.org"),
        )


# On Comfy Cloud the Gemma text encoder, run on the GPU, sometimes yields
# values that turn the take into NaN: a blank video or a failed save
# (2026-10-23: the same prompts failed at every seed and sampler, and Cloud's
# int8 encoder still failed one). Encoding the same bf16 weights on the CPU
# rendered every one of them, in about the usual take time. Owned GPUs keep
# the default device.
LTX_TEXT_ENCODER = "gemma4-12b-with-proj-ltx-2.5-bf16.safetensors"


def cloud_text_encoder(workflow: dict, backend: str) -> dict:
    if backend == "cloud":
        for node in workflow.values():
            if node["inputs"].get("clip_name") == LTX_TEXT_ENCODER:
                node["inputs"]["device"] = "cpu"
    return workflow


def reshoot(args: argparse.Namespace) -> None:
    from .reshoot import graph, prepare_look, prepare_source

    if not args.execute:
        raise ValueError("No job sent. --execute requires prior spending approval.")
    if args.model == "fasth3" and args.backend != "self-hosted":
        raise ValueError(
            "FastH3 is only qualified on a compatible self-hosted runtime."
        )
    profile = getattr(args, "render_profile", "two-pass")
    if profile == "single-pass-audio":
        from .speech import graph as speech_graph

        if args.model != "ltx25" or args.motion_strength != 1:
            raise ValueError(
                "Single-pass speech requires LTX 2.5 and the fixed guide strength."
            )
        workflow_graph = speech_graph(
            args.prompt,
            args.seed,
            frame_format=args.frame_format,
            opening=args.look_frame is not None,
            closing=args.closing_frame is not None,
            source_video=True,
        )
    else:
        workflow_graph = graph(
            args.model,
            args.prompt,
            args.seed,
            motion_strength=args.motion_strength,
            look_frame=args.look_frame is not None,
            closing_frame=args.closing_frame is not None,
            frame_format=args.frame_format,
            seconds=args.seconds,
        )
    if profile == "single-pass-audio" and args.seconds != 5:
        raise ValueError("Single-pass speech reshoots are five seconds.")
    with sdk_client(args.backend) as client:
        args.run_dir.mkdir(parents=True, exist_ok=False)
        source = prepare_source(
            args.source.resolve(),
            args.run_dir,
            frame_format=args.frame_format,
            source_start=args.source_start,
            seconds=args.seconds,
        )
        look = (
            prepare_look(
                args.look_frame.resolve(), args.run_dir, frame_format=args.frame_format
            )
            if args.look_frame
            else None
        )
        closing = (
            prepare_look(
                args.closing_frame.resolve(),
                args.run_dir,
                closing=True,
                frame_format=args.frame_format,
            )
            if args.closing_frame
            else None
        )
        cloud_text_encoder(workflow_graph, args.backend)
        (args.run_dir / "workflow.json").write_text(
            json.dumps(workflow_graph, indent=2) + "\n"
        )
        workflow = client.workflows.from_json(workflow_graph)
        workflow.set_input("source", "file", client.assets.from_file(source))
        if profile == "single-pass-audio":
            from .generation import prepare_audio

            sound = prepare_audio(source, args.run_dir)
            workflow.set_input("source-audio", "audio", client.assets.from_file(sound))
        if look:
            workflow.set_input("look", "image", client.assets.from_file(look))
        if closing:
            workflow.set_input("closing", "image", client.assets.from_file(closing))
        submit_and_collect(
            client,
            workflow,
            args.run_dir,
            "save",
            reshoot=True,
            model=args.model,
            prompt=args.prompt,
            seed=args.seed,
            frame_format=args.frame_format,
            source_start=args.source_start,
            render_profile=profile,
            motion_strength=args.motion_strength,
            look_frame="look.png" if look else None,
            closing_frame="closing.png" if closing else None,
            closing_frame_index=args.seconds * 24 if closing else None,
            seconds=args.seconds,
            closing_strength=0.7 if closing else None,
            backend=args.backend,
            base_url=os.environ.get("COMFY_BASE_URL", "https://cloud.comfy.org"),
        )


def generate(args: argparse.Namespace) -> None:
    from .generation import graph, prepare_audio
    from .reshoot import prepare_look

    if not args.execute:
        raise ValueError("No job sent. --execute requires prior execution approval.")
    if (args.mode == "audio") != (args.audio is not None):
        raise ValueError("Supply --audio exactly when using audio mode.")
    if args.mode != "audio" and args.source_start != 0:
        raise ValueError("A source offset requires audio mode.")
    workflow_graph = graph(
        args.prompt,
        args.seed,
        mode=args.mode,
        frame_format=args.frame_format,
        opening=args.look_frame is not None,
        closing=args.closing_frame is not None,
        render_profile=getattr(args, "render_profile", "two-pass"),
    )
    with sdk_client(args.backend) as client:
        args.run_dir.mkdir(parents=True, exist_ok=False)
        assets = {}
        if args.audio:
            assets["source-audio"] = (
                "audio",
                prepare_audio(args.audio.resolve(), args.run_dir, args.source_start),
            )
        if args.look_frame:
            assets["look"] = (
                "image",
                prepare_look(
                    args.look_frame.resolve(),
                    args.run_dir,
                    frame_format=args.frame_format,
                ),
            )
        if args.closing_frame:
            assets["closing"] = (
                "image",
                prepare_look(
                    args.closing_frame.resolve(),
                    args.run_dir,
                    closing=True,
                    frame_format=args.frame_format,
                ),
            )
        cloud_text_encoder(workflow_graph, args.backend)
        (args.run_dir / "workflow.json").write_text(
            json.dumps(workflow_graph, indent=2) + "\n"
        )
        workflow = client.workflows.from_json(workflow_graph)
        for key, (field, path) in assets.items():
            workflow.set_input(key, field, client.assets.from_file(path))
        submit_and_collect(
            client,
            workflow,
            args.run_dir,
            "save",
            generation_mode=args.mode,
            model="ltx25",
            prompt=args.prompt,
            seed=args.seed,
            frame_format=args.frame_format,
            source_start=args.source_start,
            render_profile=getattr(args, "render_profile", "two-pass"),
            source_audio="source.wav" if args.audio else None,
            look_frame="look.png" if args.look_frame else None,
            closing_frame="closing.png" if args.closing_frame else None,
            closing_frame_index=120 if args.closing_frame else None,
            closing_strength=0.7 if args.closing_frame else None,
            backend=args.backend,
            base_url=os.environ.get("COMFY_BASE_URL", "https://cloud.comfy.org"),
        )


def make_look(args: argparse.Namespace) -> None:
    from .look import graph, klein_graph, source_frame
    from .reshoot import prepare_look, prepare_source

    if not args.execute:
        raise ValueError("No look sent. --execute requires prior execution approval.")
    cloud = args.engine == "klein-cloud"
    klein = args.engine in ("klein", "klein-cloud")
    if args.style_image and not klein:
        raise ValueError("A style image needs a Klein look engine.")
    if klein and args.denoise is not None:
        raise ValueError("Klein uses reference conditioning, not a denoise control.")
    if (args.look_input == "text") != (args.source is None):
        raise ValueError("Supply a source file exactly for video/image look input.")
    if args.look_input != "video" and args.source_start != 0:
        raise ValueError("A source offset requires video look input.")
    denoise = (
        1.0
        if args.look_input == "text"
        else args.denoise
        if args.denoise is not None
        else 0.65
    )
    if not klein and args.look_input == "text" and args.denoise not in (None, 1.0):
        raise ValueError("Text-to-image starts from full noise, not image denoise.")
    workflow_graph = (
        klein_graph(
            args.prompt,
            args.seed,
            from_image=args.look_input != "text",
            frame_format=args.frame_format,
            **({} if cloud else {"unet_name": "flux-2-klein-4b.safetensors"}),
            style_image=len(args.style_image or []),
        )
        if klein
        else graph(
            args.prompt,
            args.seed,
            denoise,
            frame_format=args.frame_format,
            from_image=args.look_input != "text",
        )
    )
    endpoint = (
        "https://cloud.comfy.org"
        if cloud
        else local_url(os.environ.get("COMFY_LOOK_BASE_URL", ""))
    )
    look_backend = "cloud" if cloud else "self-hosted"
    with sdk_client(
        look_backend, endpoint, credential_scope="cloud-look" if cloud else "look"
    ) as client:
        args.run_dir.mkdir(parents=True, exist_ok=False)
        opening = None
        if args.look_input == "video":
            source = prepare_source(
                args.source.resolve(),
                args.run_dir,
                frame_format=args.frame_format,
                source_start=args.source_start,
                seconds=args.seconds,
            )
            if args.frame_index not in (0, args.seconds * 24):
                raise ValueError("An ending look uses the take's last frame.")
            opening = source_frame(source, args.run_dir, args.frame_index)
        elif args.look_input == "image":
            normalized = prepare_look(
                args.source.resolve(), args.run_dir, frame_format=args.frame_format
            )
            opening = args.run_dir / "source.png"
            normalized.replace(opening)
        (args.run_dir / "workflow.json").write_text(
            json.dumps(workflow_graph, indent=2) + "\n"
        )
        workflow = client.workflows.from_json(workflow_graph)
        if opening:
            workflow.set_input("source", "image", client.assets.from_file(opening))
        for index, reference in enumerate(args.style_image or []):
            from PIL import Image

            # At most a megapixel: a reference sets the look or the object,
            # not the size.
            name = "style" if index == 0 else f"style-{index + 1}"
            with Image.open(reference.resolve()) as picture:
                style = picture.convert("RGB")
                style.thumbnail((1024, 1024))
                style.save(args.run_dir / f"{name}.png")
            workflow.set_input(
                name, "image", client.assets.from_file(args.run_dir / f"{name}.png")
            )
        submit_and_collect(
            client,
            workflow,
            args.run_dir,
            "save",
            look_render=True,
            model="FLUX.2 Klein 4B FP8"
            if cloud
            else "FLUX.2 Klein 4B"
            if klein
            else "MOSS Image SFT BF16",
            prompt=args.prompt,
            seed=args.seed,
            denoise=None if klein else denoise,
            negative_skip_layers=[] if klein else [22],
            source_frame_index=args.frame_index if args.look_input == "video" else None,
            frame_format=args.frame_format,
            source_start=args.source_start,
            look_input=args.look_input,
            backend=look_backend,
            base_url=endpoint,
        )


def run_tool(args: argparse.Namespace) -> None:
    from .tools import graph, prepare, reframe

    if not args.execute:
        raise ValueError("No tool run. --execute requires prior approval.")
    if args.tool == "reframe":
        args.run_dir.mkdir(parents=True, exist_ok=False)
        output = reframe(args.source.resolve(), args.run_dir, args.target, args.fit)
        print(f"Reframed locally: {output.resolve()}")
        return
    if args.tool == "captions":
        from .captions import burn

        args.run_dir.mkdir(parents=True, exist_ok=False)
        output = burn(args.source.resolve(), args.run_dir)
        print(f"Captioned locally: {output.resolve()}")
        return
    workflow_graph = graph(args.tool, background=args.background)
    # A self-hosted studio may send tools to Cloud: name Cloud explicitly so a
    # local COMFY_BASE_URL is never used with the Cloud key.
    base_url = "https://cloud.comfy.org" if args.backend == "cloud" else None
    with sdk_client(args.backend, base_url) as client:
        args.run_dir.mkdir(parents=True, exist_ok=False)
        source = prepare(args.source.resolve(), args.run_dir, args.tool)
        (args.run_dir / "workflow.json").write_text(
            json.dumps(workflow_graph, indent=2) + "\n"
        )
        workflow = client.workflows.from_json(workflow_graph)
        workflow.set_input("source", "file", client.assets.from_file(source))
        submit_and_collect(
            client,
            workflow,
            args.run_dir,
            "save",
            tool=args.tool,
            background=args.background if args.tool == "remove-background" else None,
            backend=args.backend,
            base_url=base_url or os.environ.get("COMFY_BASE_URL", ""),
        )


def extend(args: argparse.Namespace) -> None:
    """Five more seconds: the take's last frame opens an image-mode shot."""
    import tempfile

    from .tools import join, last_frame

    if not args.execute:
        raise ValueError("No job sent. --execute requires prior execution approval.")
    take = args.take.resolve()
    with tempfile.TemporaryDirectory() as folder:
        opening = last_frame(take, Path(folder) / "last.png")
        generate(
            argparse.Namespace(
                mode="image",
                prompt=args.prompt,
                seed=args.seed,
                audio=None,
                look_frame=opening,
                closing_frame=None,
                backend=args.backend,
                run_dir=args.run_dir,
                execute=True,
                frame_format=args.frame_format,
                source_start=0,
                render_profile="two-pass",
            )
        )
    output = join(take, args.run_dir / "reshoot.mp4", args.run_dir / "extended.mp4")
    state = json.loads((args.run_dir / "job.json").read_text())
    save_state(args.run_dir, {**state, "tool": "extend", "tool_output": output.name})
    print(f"Extended take: {output.resolve()}")


def resume(run_dir: Path) -> None:
    state = json.loads((run_dir / "job.json").read_text())
    if not state.get("job_id"):
        raise ValueError(
            "Submission has no recorded job ID. Check the backend manually; do not resubmit."
        )
    with (
        FileLock(run_dir / ".observer.lock", timeout=0),
        sdk_client(
            state.get("backend", "cloud"),
            state.get("base_url"),
            credential_scope=(
                "cloud-look" if state.get("backend") == "cloud" else "look"
            )
            if state.get("look_render")
            else "primary",
        ) as client,
    ):
        collect(client.jobs.get(state["job_id"]), run_dir, state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "render"):
        command = commands.add_parser(name)
        command.add_argument("workflow", type=Path)
        command.add_argument("--output-node", required=True)
        if name == "render":
            command.add_argument("--run-dir", type=Path, required=True)
            command.add_argument("--execute", action="store_true")
            command.add_argument(
                "--backend", choices=("cloud", "self-hosted"), default="cloud"
            )
    recovery = commands.add_parser("resume")
    recovery.add_argument("run_dir", type=Path)
    editing = commands.add_parser(
        "reshoot", help="Motion-preserving reshoot of 5, 10 or 15 seconds"
    )
    editing.add_argument("source", type=Path)
    editing.add_argument("--seconds", type=int, choices=(5, 10, 15), default=5)
    editing.add_argument(
        "--model", choices=("h3", "fasth3", "ltx", "ltx25"), required=True
    )
    editing.add_argument("--backend", choices=("cloud", "self-hosted"), default="cloud")
    editing.add_argument("--prompt", required=True)
    editing.add_argument("--seed", type=int, default=42)
    editing.add_argument(
        "--motion-strength",
        type=float,
        default=1.0,
        help="Experimental source-guide weight, not playback speed (ltx25 only)",
    )
    editing.add_argument(
        "--look-frame",
        type=Path,
        help="Experimental composition-matched look frame (ltx25 or fasth3)",
    )
    editing.add_argument(
        "--closing-frame",
        type=Path,
        help="Experimental closing look at frame 120; requires ltx25 and --look-frame",
    )
    editing.add_argument("--run-dir", type=Path, required=True)
    editing.add_argument("--execute", action="store_true")
    looks = commands.add_parser("look", help="Generate a source-guided look image")
    looks.add_argument("source", type=Path, nargs="?")
    looks.add_argument(
        "--look-input", choices=("video", "image", "text"), default="video"
    )
    looks.add_argument("--prompt", required=True)
    looks.add_argument("--seed", type=int, default=42)
    looks.add_argument(
        "--engine", choices=("moss", "klein", "klein-cloud"), default="moss"
    )
    looks.add_argument("--denoise", type=float, help="MOSS only; default 0.65")
    looks.add_argument(
        "--style-image",
        type=Path,
        action="append",
        help="Klein only: a style picture or an object to add (up to three)",
    )
    looks.add_argument(
        "--frame-index",
        type=int,
        choices=(0, 120, 240, 360),
        default=0,
        help="Opening (0) or the last frame (seconds x 24) of the normalized source",
    )
    looks.add_argument("--seconds", type=int, choices=(5, 10, 15), default=5)
    looks.add_argument("--run-dir", type=Path, required=True)
    looks.add_argument("--execute", action="store_true")
    generation = commands.add_parser(
        "generate", help="LTX text, image or audio-conditioned shot"
    )
    generation.add_argument("--mode", choices=("text", "image", "audio"), required=True)
    generation.add_argument("--prompt", required=True)
    generation.add_argument("--seed", type=int, default=42)
    generation.add_argument("--audio", type=Path)
    generation.add_argument("--look-frame", type=Path)
    generation.add_argument("--closing-frame", type=Path)
    generation.add_argument(
        "--backend", choices=("cloud", "self-hosted"), default="cloud"
    )
    generation.add_argument("--run-dir", type=Path, required=True)
    generation.add_argument("--execute", action="store_true")
    tools = commands.add_parser(
        "tool", help="FPS boost, background removal, upscale or local reframe"
    )
    tools.add_argument(
        "tool",
        choices=(
            "fps-boost",
            "remove-background",
            "upscale",
            "depth-map",
            "reframe",
            "captions",
        ),
    )
    tools.add_argument("source", type=Path)
    tools.add_argument(
        "--background", choices=("green", "black", "white", "matte"), default="green"
    )
    tools.add_argument(
        "--target", choices=("portrait", "landscape", "square"), default="portrait"
    )
    tools.add_argument("--fit", choices=("blur", "crop"), default="blur")
    tools.add_argument("--backend", choices=("cloud", "self-hosted"), default="cloud")
    tools.add_argument("--run-dir", type=Path, required=True)
    tools.add_argument("--execute", action="store_true")
    extension = commands.add_parser(
        "extend", help="Continue a finished take by five seconds from its last frame"
    )
    extension.add_argument("take", type=Path)
    extension.add_argument("--prompt", required=True)
    extension.add_argument("--seed", type=int, default=42)
    extension.add_argument(
        "--backend", choices=("cloud", "self-hosted"), default="cloud"
    )
    extension.add_argument("--run-dir", type=Path, required=True)
    extension.add_argument("--execute", action="store_true")
    extension.add_argument(
        "--format",
        dest="frame_format",
        choices=("landscape", "portrait", "square"),
        default="landscape",
    )
    for command in (editing, looks, generation):
        command.add_argument(
            "--format",
            dest="frame_format",
            choices=("landscape", "portrait", "square"),
            default="landscape",
        )
        command.add_argument("--source-start", type=float, default=0)
    for command in (editing, generation):
        command.add_argument(
            "--render-profile",
            choices=("two-pass", "single-pass-audio"),
            default="two-pass",
        )
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            graph = load_workflow(args.workflow, args.output_node)
            print(f"API-format structure checked: {len(graph)} nodes. No job sent.")
        elif args.command == "render":
            render(args)
        elif args.command == "reshoot":
            reshoot(args)
        elif args.command == "look":
            make_look(args)
        elif args.command == "generate":
            generate(args)
        elif args.command == "tool":
            run_tool(args)
        elif args.command == "extend":
            extend(args)
        else:
            resume(args.run_dir)
    except (
        ComfyError,
        httpx.HTTPError,
        ValueError,
        OSError,
        TimeoutError,
        RuntimeError,
        subprocess.SubprocessError,
        LockTimeout,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        directory = getattr(args, "run_dir", None)
        state_file = directory / "job.json" if directory else None
        if state_file and state_file.is_file():
            state = json.loads(state_file.read_text())
            if state.get("job_id"):
                print(
                    f"The saved Comfy job may still run or be complete. "
                    f"Recover without a new render: aipg-cinema resume {directory}",
                    file=sys.stderr,
                )
            else:
                print(
                    "No job ID recorded. Check the backend before submitting another render.",
                    file=sys.stderr,
                )
        return 1
    except KeyboardInterrupt:
        print(
            "Stopped watching. The Comfy job may still run; use resume.",
            file=sys.stderr,
        )
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
