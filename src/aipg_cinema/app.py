"""Local Openfield studio application. Credentials stay in the server process."""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
import zlib
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Literal

import httpx
import uvicorn
from comfy_sdk import ComfyError
from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from filelock import FileLock
from filelock import Timeout as LockTimeout
from PIL import Image
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as ParsedUploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import autobrief, comfybundle, estimates, music, promptkit
from . import presets as camera_presets
from . import styles as transform_styles
from . import templates as short_templates
from . import tools as video_tools
from .assets import asset_folder, asset_records
from .brief import BriefRequest, MusicRequest, PackshotRequest, ProductLookRequest
from .cli import _CLIENT_CONFIG_LOCK, local_url, observer_active, sdk_client
from .contracts import (
    LookRequest,
    PersonReplacement,
    PromptIdea,
    SavedStyle,
    SourceWindow,
    TakeRequest,
    ToolRequest,
    WholeRestyle,
)
from .finishing import caption_image, prepare_layer, validate_finish
from .generation import AUDIO_FORMATS, audio_info, prepare_audio
from .portable import MAX_ARCHIVE, export_project, import_project, imported_project
from .product import CONTINUITY, load_photo, plan_project, render_packshot
from .project import (
    AudioLayer,
    CaptionPreview,
    Conflict,
    GenerateShot,
    NewProject,
    Project,
    ProjectStore,
    atomic_json,
)
from .reshoot import prepare_look, prepare_source, probe, video_format
from .resources import (
    RequestLimitsMiddleware,
    ResourceError,
    WorkAdmissionMiddleware,
    WorkLimiter,
)
from .transfer_limits import MAX_MANIFEST_BYTES


def browser_values(value):
    if isinstance(value, dict):
        return {
            key: str(item)
            if key == "seed" and isinstance(item, int) and abs(item) > 2**53 - 1
            else browser_values(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [browser_values(item) for item in value]
    return value


class StudioJSONResponse(JSONResponse):
    def render(self, content):
        return super().render(browser_values(content))


def index_response(state: dict) -> HTMLResponse:
    document = Path(__file__).with_name("app.html").read_text()
    marker = "/* STUDIO_SESSION */"
    if document.count(marker) != 1:
        raise ValueError("Studio page is missing its session bootstrap marker.")
    data = (
        json.dumps(state, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace("&", "\\u0026")
    )
    return HTMLResponse(
        document.replace(marker, "globalThis.studioSession = " + data + ";"),
        headers={"Cache-Control": "no-store"},
    )


def create_app(
    directory: Path,
    backend: str = "cloud",
    max_renders: int = 6,
    demo_dir: Path | None = None,
    max_looks: int = 12,
    look_engine: str = "moss",
    *,
    account_host: str | None = None,
    inference_enabled: bool = True,
    work_limiter: WorkLimiter | None = None,
    tool_backend: str | None = None,
) -> FastAPI:
    if account_host and inference_enabled:
        raise ValueError("Hosted inference needs the reviewed Core billing executor.")
    if look_engine not in ("moss", "klein", "klein-cloud"):
        raise ValueError("Choose moss, klein or klein-cloud look execution.")
    # Klein runs on Comfy Cloud or on the owned image worker; both use
    # reference conditioning instead of MOSS's denoise control.
    klein = look_engine in ("klein", "klein-cloud")
    # Tools run on the video backend unless sent to Cloud explicitly.
    tool_backend = tool_backend or backend
    if tool_backend not in ("cloud", "self-hosted"):
        raise ValueError("Choose cloud or self-hosted tool execution.")
    directory = directory.resolve()
    sources, jobs, looks = (
        directory / "sources",
        directory / "jobs",
        directory / "looks",
    )
    sources.mkdir(parents=True, exist_ok=True)
    jobs.mkdir(exist_ok=True)
    looks.mkdir(exist_ok=True)
    audios = directory / "audio"
    audios.mkdir(exist_ok=True)
    projects = ProjectStore(directory / "projects")
    exports = directory / "exports"
    exports.mkdir(exist_ok=True)
    products = directory / "products"
    products.mkdir(exist_ok=True)
    caption_previews = directory / "caption-previews"
    caption_previews.mkdir(exist_ok=True)
    processes: dict[Path, subprocess.Popen] = {}
    lock = threading.RLock()
    preview_lock = threading.Lock()
    cloud_readiness: dict[bool, tuple[float, bool]] = {}
    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        default_response_class=StudioJSONResponse,
    )

    def can_evict():
        with lock:
            # Keep startup handles until children exit, before their durable
            # observer/work locks necessarily exist. Never terminate them here.
            return all(process.poll() is not None for process in processes.values())

    app.state.can_evict = can_evict
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[account_host] if account_host else ["127.0.0.1", "localhost"],
    )
    app.mount("/icons", StaticFiles(directory=Path(__file__).with_name("icons")))
    app.mount("/fonts", StaticFiles(directory=Path(__file__).with_name("fonts")))
    app.mount(
        "/showcase",
        StaticFiles(directory=Path(__file__).with_name("showcase"), check_dir=False),
    )
    app.mount(
        "/preset-previews",
        StaticFiles(directory=camera_presets.PREVIEWS, check_dir=False),
    )
    app.mount(
        "/style-previews",
        StaticFiles(directory=transform_styles.PREVIEWS, check_dir=False),
    )

    @contextmanager
    def work_capacity():
        try:
            with (
                work_limiter.acquire(directory.name) if work_limiter else nullcontext()
            ):
                yield
        except ResourceError as error:
            raise HTTPException(
                error.status, str(error), headers={"Retry-After": "5"}
            ) from error

    async def single_upload(request: Request, handler, *args):
        async with request.form(max_files=1, max_fields=0, max_part_size=65536) as form:
            file = form.get("file")
            if not isinstance(file, ParsedUploadFile) or len(form) != 1:
                raise HTTPException(422, "Choose exactly one file to upload.")
            return await run_in_threadpool(handler, file, *args)

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method != "GET" and (
            request.headers.get("sec-fetch-site") == "cross-site"
            or (origin and origin.rstrip("/") != str(request.base_url).rstrip("/"))
        ):
            return JSONResponse({"detail": "Use the local app tab."}, status_code=403)
        if (
            not inference_enabled
            and request.method == "POST"
            and (
                re.fullmatch(
                    r"/api/(?:jobs|look-jobs)(?:/[0-9a-f]{32}/resume)?",
                    request.url.path,
                )
                or re.fullmatch(
                    r"/api/projects/[0-9a-f]{32}/shots/[0-9a-f]{32}/generate",
                    request.url.path,
                )
            )
        ):
            return JSONResponse(
                {"detail": "Rendering is not enabled in this staging workspace."},
                status_code=503,
            )
        if request.url.path == "/api/sources":
            try:
                if int(request.headers.get("content-length", "0")) > 101 * 1024 * 1024:
                    return JSONResponse(
                        {"detail": "Choose a video smaller than 100 MB."},
                        status_code=413,
                    )
            except ValueError:
                return JSONResponse({"detail": "Invalid upload size."}, status_code=400)
        if request.url.path in ("/api/looks", "/api/products"):
            try:
                if int(request.headers.get("content-length", "0")) > 13 * 1024 * 1024:
                    return JSONResponse(
                        {"detail": "Choose a look frame smaller than 12 MB."},
                        status_code=413,
                    )
            except ValueError:
                return JSONResponse({"detail": "Invalid upload size."}, status_code=400)
        if request.url.path == "/api/audio":
            try:
                if int(request.headers.get("content-length", "0")) > 51 * 1024 * 1024:
                    return JSONResponse(
                        {"detail": "Choose audio smaller than 50 MB."}, status_code=413
                    )
            except ValueError:
                return JSONResponse({"detail": "Invalid upload size."}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def source_path(source_id: str) -> Path:
        try:
            if uuid.UUID(hex=source_id).hex != source_id:
                raise ValueError
        except ValueError as error:
            raise HTTPException(404, "Source not found.") from error
        path = asset_folder(sources, source_id) / "source.mp4"
        if not path.is_file():
            raise HTTPException(404, "Source not found.")
        return path

    def job_path(job_id: str) -> Path:
        try:
            if uuid.UUID(hex=job_id).hex != job_id:
                raise ValueError
        except ValueError as error:
            raise HTTPException(404, "Take not found.") from error
        path = asset_folder(jobs, job_id)
        if not (path / "request.json").is_file():
            raise HTTPException(404, "Take not found.")
        return path

    def look_path(look_id: str) -> Path:
        try:
            if uuid.UUID(hex=look_id).hex != look_id:
                raise ValueError
        except ValueError as error:
            raise HTTPException(404, "Look frame not found.") from error
        folder = asset_folder(looks, look_id)
        path = folder / "look.png"
        if not path.is_file():
            path = folder / "render" / "look.png"
        if not path.is_file():
            raise HTTPException(404, "Look frame not found.")
        return path

    def start(
        folder: Path, arguments: list[str], module: str = "aipg_cinema.cli"
    ) -> None:
        if not inference_enabled and module != "aipg_cinema.sequence":
            raise HTTPException(
                503, "Rendering is not enabled in this staging workspace."
            )
        # Client setup briefly rewrites COMFY_BASE_URL for the image worker.
        # Snapshot under the same lock so a render never inherits that value.
        with _CLIENT_CONFIG_LOCK:
            environment = dict(os.environ)
        with (folder / "render.log").open("ab") as log:
            processes[folder] = subprocess.Popen(
                [sys.executable, "-m", module, *arguments],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=environment,
            )

    def reference_path(
        look_id: str, source_id: str | None, frame_index: int, window: SourceWindow
    ) -> Path:
        path = look_path(look_id)
        request_file = asset_folder(looks, look_id) / "request.json"
        if request_file.is_file():
            request = LookRequest.model_validate_json(request_file.read_text())
            if request.frame_format != window.frame_format or (
                source_id is not None
                and (
                    request.source_id != source_id
                    or request.frame_index != frame_index
                    or request.source_start != window.source_start
                )
            ):
                raise HTTPException(
                    400, "Choose a look made for this source range, framing and frame."
                )
        upload_file = asset_folder(looks, look_id) / "upload.json"
        if (
            upload_file.is_file()
            and json.loads(upload_file.read_text()).get("frame_format", "landscape")
            != window.frame_format
        ):
            raise HTTPException(400, "Upload a reference for this framing.")
        return path

    def window_url(source_id: str, window: SourceWindow) -> str:
        return (
            f"/api/sources/{source_id}?frame_format={window.frame_format}"
            f"&source_start={window.source_start}"
            + (f"&seconds={window.seconds}" if window.seconds != 5 else "")
        )

    def window_path(source_id: str, window: SourceWindow) -> Path:
        original = source_path(source_id)
        legacy = original.parent / "preview" / "source.mp4"
        if (
            window.frame_format == "landscape"
            and window.source_start == 0
            and window.seconds == 5
            and legacy.is_file()
        ):
            return legacy
        # Five-second windows keep the cache keys they had before lengths existed.
        key = hashlib.sha256(
            window.model_dump_json(
                exclude={"seconds"} if window.seconds == 5 else None
            ).encode()
        ).hexdigest()[:24]
        windows = original.parent / "windows"
        target = windows / key
        with (
            work_capacity() if not (target / "source.mp4").is_file() else nullcontext(),
            preview_lock,
        ):
            if (target / "source.mp4").is_file():
                return target / "source.mp4"
            windows.mkdir(exist_ok=True)
            if len(list(windows.glob("*/source.mp4"))) >= 64:
                raise HTTPException(
                    429,
                    "This source has reached its preview limit. Upload it again for more ranges.",
                )
            temporary = Path(tempfile.mkdtemp(prefix=".preparing-", dir=windows))
            try:
                prepare_source(original, temporary, **window.model_dump())
                temporary.rename(target)
            except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
                raise HTTPException(
                    400,
                    str(error)
                    if isinstance(error, ValueError)
                    else "This range could not be read.",
                ) from error
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        return target / "source.mp4"

    def audio_path(audio_id: str) -> Path:
        try:
            if uuid.UUID(hex=audio_id).hex != audio_id:
                raise ValueError
        except ValueError as error:
            raise HTTPException(404, "Audio not found.") from error
        folder = asset_folder(audios, audio_id)
        metadata = folder / "audio.json"
        if not metadata.is_file():
            raise HTTPException(404, "Audio not found.")
        suffix = json.loads(metadata.read_text())["suffix"]
        if (
            suffix not in AUDIO_FORMATS
            or not (folder / ("original" + suffix)).is_file()
        ):
            raise HTTPException(404, "Audio not found.")
        return folder / ("original" + suffix)

    def audio_window(audio_id: str, source_start: float) -> Path:
        original = audio_path(audio_id)
        key = hashlib.sha256(str(source_start).encode()).hexdigest()[:24]
        windows = original.parent / "windows"
        target = windows / key
        with (
            work_capacity() if not (target / "source.wav").is_file() else nullcontext(),
            preview_lock,
        ):
            if (target / "source.wav").is_file():
                return target / "source.wav"
            windows.mkdir(exist_ok=True)
            if len(list(windows.glob("*/source.wav"))) >= 64:
                raise HTTPException(
                    429, "Audio preview limit reached; upload again for more ranges."
                )
            temporary = Path(tempfile.mkdtemp(prefix=".preparing-", dir=windows))
            try:
                prepare_audio(original, temporary, source_start)
                temporary.rename(target)
            except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
                raise HTTPException(
                    400, "This audio section could not be prepared."
                ) from error
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        return target / "source.wav"

    def local_backend_available(endpoint: str, upstream: str, scope: str) -> bool:
        try:
            endpoint, upstream = local_url(endpoint), local_url(upstream)
            with sdk_client("self-hosted", endpoint, credential_scope=scope):
                pass
            token_name = (
                "COMFY_LOOK_LOCAL_TOKEN" if scope == "look" else "COMFY_LOCAL_TOKEN"
            )
            token = os.environ.get(token_name)
            response = httpx.get(
                endpoint + "/api/v2/health",
                timeout=2,
                headers={"Authorization": f"Bearer {token}"} if token else {},
            )
            if response.status_code != 200:
                return False
            # The official proxy's health route intentionally does not probe ComfyUI.
            response = httpx.get(upstream + "/system_stats", timeout=2)
            data = response.json()
            return (
                response.status_code == 200
                and isinstance(data, dict)
                and isinstance(data.get("devices"), list)
            )
        except (ComfyError, httpx.HTTPError, OSError, ValueError, TimeoutError):
            return False

    def cloud_available(*, force: bool = False, look: bool = False) -> bool:
        checked_at, ready = cloud_readiness.get(look, (0.0, False))
        if not force and checked_at and time.monotonic() - checked_at < 15:
            return ready
        ready = False
        try:
            with sdk_client(
                "cloud",
                "https://cloud.comfy.org" if look else None,
                credential_scope="cloud-look" if look else "primary",
                timeout=5,
            ):
                pass
            key = os.environ.get("COMFY_API_KEY", "")
            if key.strip():
                response = httpx.get(
                    "https://cloud.comfy.org/api/user",
                    headers={"X-API-Key": key},
                    timeout=5,
                )
                data = response.json() if response.status_code == 200 else {}
                ready = isinstance(data, dict) and data.get("status") == "active"
        except (
            ComfyError,
            httpx.HTTPError,
            OSError,
            ValueError,
            TimeoutError,
        ):
            pass
        cloud_readiness[look] = (time.monotonic(), ready)
        return ready

    def backend_available(*, force: bool = False) -> bool:
        if backend == "cloud":
            return cloud_available(force=force)
        return local_backend_available(
            os.environ.get("COMFY_BASE_URL", ""),
            os.environ.get("COMFY_UPSTREAM_URL", ""),
            "primary",
        )

    def look_available(*, force: bool = False) -> bool:
        if look_engine == "klein-cloud":
            return cloud_available(force=force, look=True)
        return local_backend_available(
            os.environ.get("COMFY_LOOK_BASE_URL", ""),
            os.environ.get("COMFY_LOOK_UPSTREAM_URL", ""),
            "look",
        )

    def closing_available() -> bool:
        if backend == "cloud":
            return True
        try:
            upstream = local_url(os.environ.get("COMFY_UPSTREAM_URL", ""))
            for node, required in (
                (
                    "LTXVAddGuide",
                    {
                        "positive",
                        "negative",
                        "vae",
                        "latent",
                        "image",
                        "frame_idx",
                        "strength",
                    },
                ),
                ("LTXVCropGuides", {"positive", "negative", "latent"}),
            ):
                response = httpx.get(upstream + "/object_info/" + node, timeout=2)
                if response.status_code != 200 or not required.issubset(
                    response.json()[node]["input"]["required"]
                ):
                    return False
            return True
        except (
            httpx.HTTPError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            TimeoutError,
        ):
            return False

    def moss_models_available() -> bool:
        try:
            upstream = local_url(os.environ.get("COMFY_LOOK_UPSTREAM_URL", ""))
            required = {
                "UNETLoader": ("unet_name", "moss_image_sft_bf16.safetensors"),
                "CLIPLoader": ("clip_name", "qwen3.5_9b_int8_convrot.safetensors"),
                "VAELoader": ("vae_name", "flux2-vae.safetensors"),
            }
            for node, (field, filename) in required.items():
                response = httpx.get(upstream + "/object_info/" + node, timeout=2)
                response.raise_for_status()
                names = response.json()[node]["input"]["required"][field][0]
                if not isinstance(names, list) or filename not in names:
                    return False
            response = httpx.get(
                upstream + "/object_info/SkipLayerGuidanceDiTSimple", timeout=2
            )
            response.raise_for_status()
            fields = response.json()["SkipLayerGuidanceDiTSimple"]["input"]["required"]
            return all(
                field in fields
                for field in (
                    "model",
                    "single_layers",
                    "double_layers",
                    "start_percent",
                    "end_percent",
                )
            )
        except (
            httpx.HTTPError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            TimeoutError,
        ):
            return False

    def render_state(folder: Path, result: Path, scope: str = "primary") -> dict:
        process = processes.get(folder)
        active = (process is not None and process.poll() is None) or observer_active(
            folder / "render"
        )
        state_file = folder / "render" / "job.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        status, error = "preparing", None
        if result.exists():
            status = "succeeded"
        elif state.get("failure") == "numeric":
            from .cli import NUMERIC_FAILURE

            status, error = "failed", NUMERIC_FAILURE
        elif state.get("job_id"):
            try:
                with sdk_client(
                    state.get("backend", backend),
                    state.get("base_url"),
                    credential_scope="cloud-look"
                    if scope == "look" and state.get("backend") == "cloud"
                    else scope,
                    timeout=5.0,
                ) as client:
                    status = client.jobs.get(state["job_id"]).status
                if status == "succeeded":
                    status = "exporting" if active else "needs_recovery"
                elif not active and status not in ("failed", "cancelled"):
                    status = "needs_recovery"
            except (ComfyError, httpx.HTTPError, OSError, ValueError, TimeoutError):
                status = "connection_lost" if active else "needs_recovery"
                error = (
                    "Connection interrupted. The saved render has not been replaced."
                )
        elif not active:
            status = "needs_review"
            error = "Render stopped before a job ID was saved. Check render.log before starting another take."
        return {
            "status": status,
            "error": error,
            "active": active,
            "elapsed_seconds": state.get("elapsed_seconds"),
            "actual": estimates.actual_label(state) if result.exists() else None,
        }

    def render_metadata(folder: Path) -> dict:
        for name in ("job.json", "provenance.json"):
            path = folder / "render" / name
            if path.is_file():
                return json.loads(path.read_text())
        return {}

    def describe(job_id: str) -> dict:
        folder = job_path(job_id)
        data = json.loads((folder / "request.json").read_text())
        result = folder / "render" / "reshoot.mp4"
        return {
            **data,
            **render_state(folder, result),
            "id": job_id,
            "source_url": window_url(
                data["source_id"], SourceWindow.model_validate(data)
            )
            if data.get("source_id")
            else None,
            "source_image_url": f"/api/looks/{data['look_id']}"
            if not data.get("source_id") and data.get("look_id")
            else None,
            "source_audio_url": f"/api/audio/{data['audio_id']}?source_start={data.get('source_start', 0)}"
            if data.get("audio_id")
            else None,
            "look_url": f"/api/looks/{data['look_id']}"
            if data.get("look_id")
            else None,
            "generated_look": bool(
                data.get("look_id")
                and (asset_folder(looks, data["look_id"]) / "request.json").is_file()
            ),
            "look_has_source": bool(
                data.get("look_id")
                and (
                    asset_folder(looks, data["look_id"]) / "render" / "source.png"
                ).is_file()
            ),
            "closing_url": f"/api/looks/{data['closing_id']}"
            if data.get("closing_id")
            else None,
            "generated_closing": bool(
                data.get("closing_id")
                and (asset_folder(looks, data["closing_id"]) / "request.json").is_file()
            ),
            "closing_has_source": bool(
                data.get("closing_id")
                and (
                    asset_folder(looks, data["closing_id"]) / "render" / "source.png"
                ).is_file()
            ),
            "output_url": f"/api/jobs/{job_id}/output" if result.exists() else None,
        }

    def look_job_path(job_id: str) -> Path:
        try:
            if uuid.UUID(hex=job_id).hex != job_id:
                raise ValueError
        except ValueError as error:
            raise HTTPException(404, "Look job not found.") from error
        folder = asset_folder(looks, job_id)
        if not (folder / "request.json").is_file():
            raise HTTPException(404, "Look job not found.")
        return folder

    def describe_look(job_id: str) -> dict:
        folder = look_job_path(job_id)
        data = json.loads((folder / "request.json").read_text())
        result = folder / "render" / "look.png"
        return {
            **data,
            "model": "FLUX.2 Klein 4B FP8"
            if data.get("engine") == "klein-cloud"
            else "FLUX.2 Klein 4B"
            if data.get("engine") == "klein"
            else "MOSS Image SFT BF16",
            "frame_index": data.get("frame_index", 0),
            **render_state(folder, result, "look"),
            "id": job_id,
            "look_id": job_id if result.exists() else None,
            "output_url": f"/api/looks/{job_id}" if result.exists() else None,
        }

    def product_path(product_id: str) -> Path:
        try:
            if uuid.UUID(hex=product_id).hex != product_id:
                raise ValueError
        except ValueError as error:
            raise HTTPException(404, "Product photo not found.") from error
        path = products / product_id / "product.png"
        if not path.is_file():
            raise HTTPException(404, "Product photo not found.")
        return path

    def local_take(folder: Path) -> bool:
        """Packshots are composed locally: no Comfy job and no render credit."""
        return (folder / "render" / "packshot.json").is_file()

    def product_look_folder(job_id: str) -> Path:
        try:
            if uuid.UUID(hex=job_id).hex != job_id:
                raise ValueError
        except ValueError as error:
            raise HTTPException(404, "Product look not found.") from error
        folder = looks / job_id
        if not (folder / "product-look.json").is_file():
            raise HTTPException(404, "Product look not found.")
        return folder

    def describe_product_look(job_id: str) -> dict:
        folder = product_look_folder(job_id)
        data = json.loads((folder / "product-look.json").read_text())
        result = folder / "render" / "look.png"
        return {
            **data,
            **render_state(folder, result, "look"),
            "id": job_id,
            "look_id": job_id if result.exists() else None,
            "output_url": f"/api/looks/{job_id}" if result.exists() else None,
        }

    def klein_models_available(refine: bool) -> bool:
        if look_engine == "klein-cloud":
            return True
        try:
            upstream = local_url(os.environ.get("COMFY_LOOK_UPSTREAM_URL", ""))
            required = {
                "UNETLoader": ("unet_name", "flux-2-klein-4b.safetensors"),
                "CLIPLoader": ("clip_name", "qwen_3_4b.safetensors"),
                "VAELoader": ("vae_name", "flux2-vae.safetensors"),
            }
            for node, (field, filename) in required.items():
                response = httpx.get(upstream + "/object_info/" + node, timeout=2)
                response.raise_for_status()
                names = response.json()[node]["input"]["required"][field][0]
                if not isinstance(names, list) or filename not in names:
                    return False
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
            return False
        return not refine or moss_models_available()

    def project_data(project_id: str) -> Project:
        try:
            return projects.load(project_id)
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(404, "Project not found.") from error

    def validate_project_assets(project: Project) -> None:
        for photo_id in project.product.photo_ids if project.product else []:
            product_path(photo_id)
        for layer in (project.music, project.voiceover):
            if layer:
                audio_path(layer.audio_id)
        for shot in project.shots:
            draft = shot.draft
            if shot.audition:
                for image in (
                    shot.audition.reference_id,
                    shot.audition.left_id,
                    shot.audition.right_id,
                ):
                    if image:
                        look_path(image)
            if draft.source_id:
                source_path(draft.source_id)
            if draft.audio_id:
                audio_path(draft.audio_id)
            for look_id, frame in (
                (draft.look_id, 0),
                (draft.closing_id, 0 if draft.closing_id == draft.look_id else 120),
            ):
                if look_id:
                    reference_path(look_id, draft.source_id, frame, draft)
            if shot.selected_take_id:
                folder = job_path(shot.selected_take_id)
                try:
                    take = TakeRequest.model_validate_json(
                        (folder / "request.json").read_text()
                    )
                except ValueError as error:
                    raise HTTPException(
                        409,
                        "This selected take's saved settings need review. Choose another completed take.",
                    ) from error
                except OSError as error:
                    raise HTTPException(
                        503,
                        "This take could not be read. Keep your edits and try again.",
                    ) from error
                if take.request_id != shot.selected_take_id:
                    raise HTTPException(
                        409, "This take differs from its saved identity."
                    )
                if not (folder / "render" / "reshoot.mp4").is_file():
                    raise HTTPException(409, "Select a completed take for the short.")
                if take.frame_format != project.frame_format:
                    raise HTTPException(
                        409, "This take uses different framing from the project."
                    )

    @app.get("/api/projects")
    def list_projects():
        return [project.model_dump() for project in projects.list()]

    user_templates = directory / "templates"
    user_templates.mkdir(exist_ok=True)

    def template_or_404(template_id: str):
        try:
            return short_templates.by_template_id(user_templates, template_id)
        except ValueError as error:
            raise HTTPException(404, "Template not found.") from error

    def creation_plan(body: NewProject):
        """Validate a product short's photos and template, and return its planner."""
        template = template_or_404(body.template_id) if body.template_id else None
        if template and not body.product:
            raise HTTPException(400, "Templates start product shorts. Add a photo.")
        if not body.product:
            return None
        for photo_id in body.product.photo_ids:
            product_path(photo_id)
        setup = body.product
        if template:
            # The template decides pacing, tone and captions; the user's
            # product, setting, hook and copy stay theirs.
            brief = setup.brief.model_copy(
                update=short_templates.brief_overrides(template)
            )
            setup = setup.model_copy(update={"brief": brief})

        def planner(project):
            planned = plan_project(project, setup)
            return short_templates.apply(planned, template) if template else planned

        return planner

    @app.post("/api/projects")
    def new_project(body: NewProject):
        with lock:
            return projects.create(body, plan=creation_plan(body)).model_dump()

    @app.get("/api/templates")
    def list_templates():
        return [
            {
                **template.model_dump(),
                "preview_url": f"/api/templates/{template.id}/preview"
                if short_templates.preview_path(user_templates, template).is_file()
                else None,
            }
            for template in short_templates.listing(user_templates)
        ]

    @app.get("/api/templates/{template_id}/preview")
    def template_preview(template_id: str):
        path = short_templates.preview_path(
            user_templates, template_or_404(template_id)
        )
        if not path.is_file():
            raise HTTPException(404, "No preview for this template.")
        return FileResponse(path, media_type="video/mp4")

    @app.post("/api/projects/{project_id}/template")
    def save_template(project_id: str):
        """Save the plan (never media, references or keys) as a template."""
        project = project_data(project_id)
        done = [
            path.parent / "short.mp4"
            for path in sorted(
                exports.glob("*/request.json"), key=lambda p: p.stat().st_mtime
            )
            if json.loads(path.read_text()).get("project_id") == project_id
            and (path.parent / "short.mp4").is_file()
        ]
        with lock:
            template = short_templates.save_from(
                project, user_templates, done[-1] if done else None
            )
        return template.model_dump()

    def creation_receipt(request_id: str):
        if not re.fullmatch(r"[0-9a-f]{32}", request_id):
            raise HTTPException(404, "New short request not found.")
        try:
            body, project = projects.creation(request_id)
        except FileNotFoundError as error:
            raise HTTPException(404, "New short request not found.") from error
        except (OSError, ValueError) as error:
            raise HTTPException(
                503, "New short could not be confirmed. Check this request again."
            ) from error
        return {
            "id": request_id,
            "request": body.model_dump(exclude_none=True),
            "project": project.model_dump(),
        }

    @app.post("/api/project-creations/{request_id}")
    def create_project_once(request_id: str, body: NewProject):
        if not re.fullmatch(r"[0-9a-f]{32}", request_id):
            raise HTTPException(404, "New short request not found.")
        try:
            planner = creation_plan(body)
            with lock:
                projects.create(body, request_id=request_id, plan=planner)
        except Conflict as error:
            raise HTTPException(409, str(error)) from error
        except (LockTimeout, OSError, ValueError) as error:
            raise HTTPException(
                503, "New short could not be confirmed. Check this request again."
            ) from error
        return creation_receipt(request_id)

    @app.get("/api/project-creations/{request_id}")
    def get_project_creation(request_id: str):
        return creation_receipt(request_id)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str):
        return project_data(project_id).model_dump()

    def package_folder(request_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", request_id):
            raise HTTPException(404, "Project package not found.")
        folder = directory / "packages" / request_id
        if not (folder / "request.json").is_file():
            raise HTTPException(404, "Project package not found.")
        return folder

    def package_state(request_id: str) -> dict:
        folder = package_folder(request_id)
        ready = (folder / "project.aipg.zip").is_file()
        intent = json.loads((folder / "request.json").read_text())
        return {
            "project_id": intent["project_id"],
            "revision": intent["revision"],
            "id": request_id,
            "status": "complete" if ready else "needs_recovery",
            "download_url": f"/api/project-packages/{request_id}/download"
            if ready
            else None,
        }

    def build_project_package(project_id: str, body: GenerateShot):
        root = directory / "packages"
        root.mkdir(mode=0o700, exist_ok=True)
        with lock, FileLock(root / ".package.lock", timeout=5):
            folder = root / body.request_id
            identity = {"project_id": project_id, "revision": body.revision}
            if (folder / "request.json").is_file():
                intent = json.loads((folder / "request.json").read_text())
                if {key: intent[key] for key in identity} != identity:
                    raise HTTPException(
                        409, "This ID belongs to another project package."
                    )
                if (folder / "project.aipg.zip").is_file():
                    return package_state(body.request_id)
                project = Project.model_validate(intent["project"])
            else:
                project = project_data(project_id)
                if project.revision != body.revision:
                    raise HTTPException(
                        412, "Save and reopen the current project before packaging it."
                    )
                if len(list(root.glob("*/request.json"))) >= 16:
                    raise HTTPException(
                        429, "This workspace has reached its saved-package limit."
                    )
                intent = {**identity, "project": project.model_dump()}
                if (
                    len(json.dumps(intent, indent=2, allow_nan=False)) + 1
                    > MAX_MANIFEST_BYTES
                ):
                    raise HTTPException(
                        400, "Project metadata exceeds its package limit."
                    )
                folder.mkdir(mode=0o700, exist_ok=True)
                atomic_json(
                    folder / "request.json",
                    intent,
                )
            try:
                export_project(directory, project, folder / "project.aipg.zip")
            except (
                ValueError,
                KeyError,
                TypeError,
                subprocess.SubprocessError,
                Image.DecompressionBombError,
            ) as error:
                raise HTTPException(
                    400,
                    "This project could not be packaged. Check its completed takes and source assets.",
                ) from error
            except OSError as error:
                raise HTTPException(
                    503,
                    "The package outcome is unconfirmed. Check this saved transfer before preparing another.",
                ) from error
            return package_state(body.request_id)

    @app.post("/api/projects/{project_id}/packages")
    async def new_project_package(project_id: str, body: GenerateShot):
        try:
            return await run_in_threadpool(build_project_package, project_id, body)
        except LockTimeout as error:
            raise HTTPException(
                409,
                "Another project package is being prepared. Check this transfer again.",
            ) from error

    @app.get("/api/project-packages/{request_id}")
    def get_project_package(request_id: str):
        return package_state(request_id)

    @app.get("/api/project-packages/{request_id}/download")
    def get_project_package_bytes(request_id: str):
        folder = package_folder(request_id)
        if not (folder / "project.aipg.zip").is_file():
            raise HTTPException(409, "Check the saved package before downloading.")
        project = Project.model_validate(
            json.loads((folder / "request.json").read_text())["project"]
        )
        name = (
            re.sub(r"[^A-Za-z0-9._-]+", "-", project.title).strip(".-")[:60]
            or "project"
        )
        return FileResponse(
            folder / "project.aipg.zip",
            media_type="application/zip",
            filename=name + ".aipg.zip",
        )

    @app.get("/api/project-imports/{request_id}")
    def project_import_state(request_id: str):
        try:
            project = imported_project(directory, request_id)
        except (ValueError, KeyError, OSError) as error:
            raise HTTPException(
                400, "The saved project import could not be read."
            ) from error
        if project is None:
            raise HTTPException(
                404, "Import not confirmed. Reuse the same import ID and package."
            )
        return {"project": project.model_dump(), "status": "complete"}

    @app.post("/api/project-imports/{request_id}")
    async def upload_project_package(request_id: str, request: Request):
        if not re.fullmatch(r"[0-9a-f]{32}", request_id):
            raise HTTPException(400, "Invalid project import ID.")
        if request.headers.get("content-type", "").split(";")[0] != "application/zip":
            raise HTTPException(415, "Choose an AIPG project ZIP package.")
        try:
            if int(request.headers.get("content-length", "0")) > MAX_ARCHIVE:
                raise HTTPException(
                    413, "Choose a project package smaller than 514 MB."
                )
        except ValueError as error:
            raise HTTPException(400, "Invalid package size.") from error
        transfers = directory / ".project-transfers"
        transfers.mkdir(mode=0o700, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix="upload-", dir=transfers))
        try:
            archive = temporary / "project.zip"
            with archive.open("xb") as output:
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_ARCHIVE:
                        raise HTTPException(
                            413, "Choose a project package smaller than 514 MB."
                        )
                    output.write(chunk)
            project = await run_in_threadpool(
                import_project, directory, archive, request_id
            )
            return {"project": project.model_dump(), "status": "complete"}
        except LockTimeout as error:
            raise HTTPException(
                409, "Another project import is in progress. Check this import again."
            ) from error
        except (
            ValueError,
            KeyError,
            TypeError,
            EOFError,
            subprocess.SubprocessError,
            zipfile.BadZipFile,
            zlib.error,
            Image.DecompressionBombError,
        ) as error:
            raise HTTPException(
                400,
                "This project package is invalid, incomplete or outside the supported limits.",
            ) from error
        except OSError as error:
            raise HTTPException(
                503,
                "The import outcome is unconfirmed. Check this saved transfer before importing again.",
            ) from error
        finally:
            shutil.rmtree(temporary)

    @app.put("/api/projects/{project_id}")
    def save_project(project_id: str, body: Project):
        if body.id != project_id:
            raise HTTPException(409, "The project ID does not match this URL.")
        with lock:
            project_data(project_id)
            validate_project_assets(body)
            try:
                return projects.save(body).model_dump()
            except Conflict as error:
                raise HTTPException(409, str(error)) from error

    @app.post("/api/projects/{project_id}/shots/{shot_id}/generate")
    def generate_project_shot(project_id: str, shot_id: str, body: GenerateShot):
        with lock:
            existing = asset_folder(jobs, body.request_id) / "request.json"
            if existing.is_file():
                request = TakeRequest.model_validate_json(existing.read_text())
                if (request.project_id, request.shot_id, request.project_revision) != (
                    project_id,
                    shot_id,
                    body.revision,
                ):
                    raise HTTPException(
                        409, "This ID belongs to a different saved shot."
                    )
                return describe(body.request_id)
            project = project_data(project_id)
            if body.revision != project.revision:
                raise HTTPException(
                    409, "The project changed. Reopen it before rendering."
                )
            if project.product and project.product.packshot_shot_id == shot_id:
                raise HTTPException(
                    400, "The packshot uses the real product photo. Build it instead."
                )
            try:
                request = project.request(shot_id, body.request_id)
            except (ValueError, ValidationError) as error:
                raise HTTPException(
                    422,
                    "Complete this shot's scene and required inputs before rendering.",
                ) from error
            return generate(request)

    @app.post("/api/products")
    def upload_product(file: UploadFile):
        product_id = uuid.uuid4().hex
        folder = products / product_id
        folder.mkdir()
        source = folder / "upload"
        try:
            size = 0
            with source.open("wb") as target:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 12 * 1024 * 1024:
                        raise HTTPException(
                            413, "Choose a product photo smaller than 12 MB."
                        )
                    target.write(chunk)
            # Keep the full photo and any transparency; packshots use it as is.
            load_photo(source).save(folder / "product.png")
            source.unlink()
        except ValueError as error:
            shutil.rmtree(folder)
            raise HTTPException(400, str(error)) from error
        except OSError as error:
            shutil.rmtree(folder)
            raise HTTPException(400, "This product photo could not be read.") from error
        except HTTPException:
            shutil.rmtree(folder)
            raise
        return {"product_id": product_id, "url": f"/api/products/{product_id}"}

    @app.post("/api/products/{product_id}/brief")
    def draft_brief(product_id: str, body: BriefRequest):
        """One bounded Grid call that only fills the editable form."""
        photo = product_path(product_id)
        try:
            return autobrief.suggest(photo, body.name)
        except autobrief.AutoBriefError as error:
            raise HTTPException(503, str(error)) from error

    @app.post("/api/projects/{project_id}/music")
    def generate_music(project_id: str, body: MusicRequest):
        """One ACE-Step track under the whole short; shot sound is muted."""
        with lock:
            project = project_data(project_id)
            if body.revision != project.revision:
                raise HTTPException(409, "The project changed. Reopen it first.")
            if not project.shots:
                raise HTTPException(400, "Add shots before generating music.")
            folder = audios / body.request_id
            if folder.exists():
                raise HTTPException(409, "This music request already ran.")
            tone = project.product.brief.tone if project.product else "calm"
            request = music.request_body(
                tone, project.frames, body.seed, project.music_prompt
            )
        try:
            track, meta = music.generate(request, body.request_id)
        except music.MusicError as error:
            raise HTTPException(503, str(error)) from error
        with lock:
            folder.mkdir()
            original = folder / "original.wav"
            original.write_bytes(track)
            try:
                info = audio_info(original, min_duration=0.1)
                sound = next(s for s in info["streams"] if s["codec_type"] == "audio")
                duration = float(sound.get("duration") or info["format"]["duration"])
            except (
                ValueError,
                KeyError,
                StopIteration,
                subprocess.SubprocessError,
            ) as error:
                shutil.rmtree(folder)
                raise HTTPException(
                    502, "The generated track could not be read."
                ) from error
            (folder / "audio.json").write_text(
                json.dumps(
                    {
                        "audio_id": body.request_id,
                        "suffix": ".wav",
                        "name": "Generated music",
                        "duration": duration,
                        "generated": meta,
                    }
                )
            )
            project = project_data(project_id)
            if body.revision != project.revision:
                raise HTTPException(
                    409, "The project changed while music was made; the track is kept."
                )
            frames = min(project.frames, math.floor(duration * 24))
            project.music = AudioLayer(
                audio_id=body.request_id,
                duration_frames=frames,
                volume=0.85,
                fade_out=min(30, frames),
            )
            for shot in project.shots:
                shot.volume = 0
            return {"project": projects.save(project).model_dump(), "music": meta}

    @app.get("/api/products/{product_id}")
    def product_photo(product_id: str):
        return FileResponse(product_path(product_id), media_type="image/png")

    @app.post("/api/projects/{project_id}/shots/{shot_id}/product-look")
    def generate_product_look(project_id: str, shot_id: str, body: ProductLookRequest):
        with lock:
            folder = looks / body.request_id
            identity = {
                "project_id": project_id,
                "shot_id": shot_id,
                "revision": body.revision,
                "photo_index": body.photo_index,
                "seed": body.seed,
                "refine": body.refine,
                "continuity_look_id": body.continuity_look_id,
            }
            if folder.exists():
                saved = folder / "product-look.json"
                if (
                    not saved.is_file()
                    or {key: json.loads(saved.read_text()).get(key) for key in identity}
                    != identity
                ):
                    raise HTTPException(409, "This ID belongs to a different look.")
                return describe_product_look(body.request_id)
            project = project_data(project_id)
            if body.revision != project.revision:
                raise HTTPException(409, "The project changed. Reopen it first.")
            if not project.product:
                raise HTTPException(400, "This is not a product short.")
            shot = (
                project.shot(shot_id)
                if any(item.id == shot_id for item in project.shots)
                else None
            )
            if shot is None:
                raise HTTPException(404, "Shot not found.")
            if shot.id == project.product.packshot_shot_id:
                raise HTTPException(
                    400, "The packshot uses the real photo. Build it instead."
                )
            prompt = (shot.draft.art_direction or "").strip()
            if not prompt:
                raise HTTPException(400, "Describe this shot's scene first.")
            if body.photo_index >= len(project.product.photo_ids):
                raise HTTPException(400, "Choose one of this project's photos.")
            photo = product_path(project.product.photo_ids[body.photo_index])
            continuity = None
            if body.continuity_look_id:
                previous = describe_product_look(body.continuity_look_id)
                if previous["project_id"] != project_id or not previous["output_url"]:
                    raise HTTPException(
                        400, "Continue from a finished look in this project."
                    )
                continuity = look_path(body.continuity_look_id)
                prompt += CONTINUITY
            cloud = look_engine == "klein-cloud"
            if body.refine and cloud:
                raise HTTPException(
                    422, "MOSS refinement needs the owned image runtime."
                )
            used = list(looks.glob("*/request.json")) + list(
                looks.glob("*/product-look.json")
            )
            if len(used) >= max_looks:
                raise HTTPException(429, "This session's look limit has been reached.")
            for path in used:
                old = (
                    describe_product_look(path.parent.name)
                    if path.name == "product-look.json"
                    else describe_look(path.parent.name)
                )
                if old["active"] or old["status"] not in (
                    "succeeded",
                    "failed",
                    "cancelled",
                ):
                    raise HTTPException(
                        409, "Finish or recover the current look first."
                    )
            if not look_available(force=True) or not klein_models_available(
                body.refine
            ):
                raise HTTPException(
                    503,
                    "The image runtime or Klein models are unavailable. "
                    "No look was created or submitted.",
                )
            folder.mkdir()
            (folder / "upload.json").write_text(
                json.dumps({"frame_format": project.frame_format})
            )
            (folder / "product-look.json").write_text(
                json.dumps(
                    {
                        **identity,
                        "prompt": prompt,
                        "frame_format": project.frame_format,
                        "model": "FLUX.2 Klein 4B"
                        + (" + MOSS Image refine 0.4" if body.refine else ""),
                        "backend": "cloud" if cloud else "self-hosted",
                    }
                )
                + "\n"
            )
            start(
                folder,
                [
                    "look",
                    str(photo),
                    "--prompt",
                    prompt,
                    "--seed",
                    str(body.seed),
                    "--format",
                    project.frame_format,
                    "--backend",
                    "cloud" if cloud else "self-hosted",
                    "--run-dir",
                    str(folder / "render"),
                    "--execute",
                ]
                + (["--refine"] if body.refine else [])
                + (["--continuity", str(continuity)] if continuity else []),
                module="aipg_cinema.product",
            )
            return describe_product_look(body.request_id)

    @app.get("/api/product-looks/{job_id}")
    def product_look_status(job_id: str):
        return describe_product_look(job_id)

    @app.post("/api/product-looks/{job_id}/resume")
    def resume_product_look(job_id: str):
        with lock:
            folder = product_look_folder(job_id)
            state_path = folder / "render" / "job.json"
            if not state_path.exists() or not json.loads(state_path.read_text()).get(
                "job_id"
            ):
                raise HTTPException(
                    409, "No saved look job ID; manual review is required."
                )
            old = describe_product_look(job_id)
            if not old["active"] and not old["output_url"]:
                start(folder, ["resume", str(folder / "render")])
            return describe_product_look(job_id)

    @app.post("/api/projects/{project_id}/shots/{shot_id}/packshot")
    def build_packshot(project_id: str, shot_id: str, body: PackshotRequest):
        with lock:
            project = project_data(project_id)
            if body.revision != project.revision:
                raise HTTPException(409, "The project changed. Reopen it first.")
            if not project.product or project.product.packshot_shot_id != shot_id:
                raise HTTPException(400, "This shot is not the product packshot.")
            folder = jobs / body.request_id
            if folder.exists():
                raise HTTPException(409, "This ID belongs to an existing take.")
            brief = project.product.brief
            if body.photo_index >= len(project.product.photo_ids):
                raise HTTPException(400, "Choose one of this project's photos.")
            photo = product_path(project.product.photo_ids[body.photo_index])
            folder.mkdir()
            try:
                render_packshot(
                    photo,
                    folder / "render",
                    name=brief.name,
                    tagline=brief.tagline,
                    cta=brief.cta,
                    frame_format=project.frame_format,
                    accent=body.accent,
                    tone=brief.tone,
                )
                look = looks / body.request_id
                look.mkdir()
                prepare_look(
                    folder / "render" / "packshot.png",
                    look,
                    frame_format=project.frame_format,
                )
                (look / "upload.json").write_text(
                    json.dumps({"frame_format": project.frame_format})
                )
                shot = project.shot(shot_id)
                shot.draft = shot.draft.model_copy(
                    update={"mode": "image", "look_id": body.request_id}
                )
                request = project.request(shot_id, body.request_id)
                (folder / "request.json").write_text(request.model_dump_json())
                shot.selected_take_id = body.request_id
                project = projects.save(project)
            except (
                ValueError,
                ValidationError,
                OSError,
                subprocess.SubprocessError,
            ) as error:
                shutil.rmtree(folder, ignore_errors=True)
                shutil.rmtree(looks / body.request_id, ignore_errors=True)
                raise HTTPException(
                    400,
                    str(error)
                    if isinstance(error, ValueError)
                    and not isinstance(error, ValidationError)
                    else "The packshot could not be built. No take was saved.",
                ) from error
            return {"project": project.model_dump(), "take": describe(body.request_id)}

    def export_folder(export_id: str) -> Path:
        try:
            if uuid.UUID(hex=export_id).hex != export_id:
                raise ValueError
        except ValueError as error:
            raise HTTPException(404, "Export not found.") from error
        folder = exports / export_id
        if not (folder / "request.json").is_file():
            raise HTTPException(404, "Export not found.")
        return folder

    def describe_export(export_id: str) -> dict:
        folder = export_folder(export_id)
        request = json.loads((folder / "request.json").read_text())
        process = processes.get(folder)
        active = (process is not None and process.poll() is None) or observer_active(
            folder
        )
        state_file = folder / "state.json"
        state = json.loads(state_file.read_text()) if state_file.is_file() else {}
        ready = (folder / "short.mp4").is_file()
        project = Project.model_validate_json((folder / "project.json").read_text())
        clean_preview = (folder / "picture.mp4").is_file() or not project.captions
        return {
            **request,
            "id": export_id,
            "active": active,
            "status": "succeeded"
            if ready
            else "queued"
            if active and state.get("status") != "running"
            else "running"
            if active
            else "failed"
            if state.get("status") == "failed"
            else "needs_recovery",
            "error": state.get("error"),
            "output_url": f"/api/exports/{export_id}/output" if ready else None,
            "manifest_url": f"/api/exports/{export_id}/manifest" if ready else None,
            "preview_url": f"/api/exports/{export_id}/preview"
            if ready and clean_preview
            else None,
            "captions_url": f"/api/exports/{export_id}/captions"
            if ready and project.captions and (folder / "captions.srt").is_file()
            else None,
        }

    def start_export(folder: Path):
        atomic_json(folder / "state.json", {"status": "queued"})
        start(
            folder,
            [
                "--project",
                str(folder / "project.json"),
                "--jobs",
                str(jobs),
                "--directory",
                str(folder),
                "--audio-root",
                str(audios),
                *(["--resource-root", str(work_limiter.root)] if work_limiter else []),
            ],
            module="aipg_cinema.sequence",
        )

    @app.post("/api/projects/{project_id}/exports")
    def new_export(project_id: str, body: GenerateShot):
        with lock:
            folder = exports / body.request_id
            identity = {"project_id": project_id, "revision": body.revision}
            if (folder / "request.json").is_file():
                if json.loads((folder / "request.json").read_text()) != identity:
                    raise HTTPException(409, "This ID belongs to a different export.")
                return describe_export(body.request_id)
            project = project_data(project_id)
            if project.revision != body.revision:
                raise HTTPException(
                    409, "Save and reopen the current project before exporting."
                )
            if not project.shots or any(
                not shot.selected_take_id for shot in project.shots
            ):
                raise HTTPException(400, "Choose a completed take for every shot.")
            validate_project_assets(project)
            try:
                validate_finish(project)
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            if any(
                process.poll() is None
                for path, process in processes.items()
                if path.parent == exports
            ) or any(
                observer_active(path) for path in exports.iterdir() if path.is_dir()
            ):
                raise HTTPException(409, "Finish the current local export first.")
            folder.mkdir()
            (folder / "project.json").write_text(project.model_dump_json())
            (folder / "request.json").write_text(json.dumps(identity))
            start_export(folder)
            return describe_export(body.request_id)

    @app.get("/api/projects/{project_id}/exports")
    def list_exports(project_id: str):
        project_data(project_id)
        return [
            describe_export(path.parent.name)
            for path in sorted(
                exports.glob("*/request.json"), key=lambda path: path.stat().st_mtime
            )
            if json.loads(path.read_text())["project_id"] == project_id
        ]

    @app.get("/api/exports/{export_id}")
    def export_state(export_id: str):
        return describe_export(export_id)

    @app.post("/api/exports/{export_id}/resume")
    def resume_export(export_id: str):
        with lock:
            folder = export_folder(export_id)
            state = describe_export(export_id)
            if not state["active"] and not state["output_url"]:
                start_export(folder)
            return describe_export(export_id)

    @app.get("/api/exports/{export_id}/{kind}")
    def download_export(export_id: str, kind: str):
        folder = export_folder(export_id)
        if not (folder / "short.mp4").is_file() or kind not in (
            "output",
            "manifest",
            "project",
            "preview",
            "captions",
        ):
            raise HTTPException(404)
        name = {
            "output": "short.mp4",
            "manifest": "manifest.json",
            "project": "project.json",
            "preview": "picture.mp4",
            "captions": "captions.srt",
        }[kind]
        if kind == "preview" and not (folder / name).is_file():
            project = Project.model_validate_json((folder / "project.json").read_text())
            if project.captions:
                raise HTTPException(404)
            name = "short.mp4"
        if not (folder / name).is_file():
            raise HTTPException(404)
        if kind == "preview":
            return FileResponse(folder / name, media_type="video/mp4")
        return FileResponse(folder / name, filename=f"aipg-{export_id[:8]}-{name}")

    @app.post("/api/caption-previews")
    def make_caption_preview(body: CaptionPreview):
        try:
            image, layout = caption_image(
                body.text, body.frame_format, body.style, body.position
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        key = hashlib.sha256(
            (body.model_dump_json() + layout["font_sha256"]).encode()
        ).hexdigest()
        target = caption_previews / (key + ".png")
        with preview_lock:
            if not target.exists():
                for stale in sorted(
                    caption_previews.glob("*.png"), key=lambda p: p.stat().st_mtime
                )[:-255]:
                    stale.unlink(missing_ok=True)
                temporary = target.with_suffix(".partial")
                image.save(temporary, format="PNG")
                temporary.replace(target)
        return {"url": f"/api/caption-previews/{key}", "layout": layout}

    @app.get("/api/caption-previews/{key}")
    def get_caption_preview(key: str):
        path = caption_previews / (key + ".png")
        if not re.fullmatch(r"[a-f0-9]{64}", key) or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/png")

    @app.get("/")
    def index():
        return index_response({"mode": "local"})

    @app.get("/session.js")
    def local_session():
        return Response(
            'window.studioSession = {mode:"local"};',
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/account.js")
    def account_script():
        return FileResponse(
            Path(__file__).with_name("account.js"), media_type="text/javascript"
        )

    @app.get("/board.js")
    def board_script():
        return FileResponse(
            Path(__file__).with_name("board.js"), media_type="text/javascript"
        )

    @app.get("/product.js")
    def product_script():
        return FileResponse(
            Path(__file__).with_name("product.js"), media_type="text/javascript"
        )

    @app.get("/tools.js")
    def tools_script():
        return FileResponse(
            Path(__file__).with_name("tools.js"), media_type="text/javascript"
        )

    @app.get("/styles.js")
    def styles_script():
        return FileResponse(
            Path(__file__).with_name("styles.js"), media_type="text/javascript"
        )

    @app.get("/presetbrowser.js")
    def preset_browser_script():
        return FileResponse(
            Path(__file__).with_name("presetbrowser.js"), media_type="text/javascript"
        )

    @app.get("/home.js")
    def home_script():
        return FileResponse(
            Path(__file__).with_name("home.js"), media_type="text/javascript"
        )

    @app.get("/autopilot.js")
    def autopilot_script():
        return FileResponse(
            Path(__file__).with_name("autopilot.js"), media_type="text/javascript"
        )

    @app.get("/finishing.js")
    def finishing_script():
        return FileResponse(
            Path(__file__).with_name("finishing.js"), media_type="text/javascript"
        )

    @app.get("/auditions.js")
    def auditions_script():
        return FileResponse(
            Path(__file__).with_name("auditions.js"), media_type="text/javascript"
        )

    @app.get("/packaging.js")
    def packaging_script():
        return FileResponse(
            Path(__file__).with_name("packaging.js"), media_type="text/javascript"
        )

    @app.get("/takecompare.js")
    def take_comparison_script():
        return FileResponse(
            Path(__file__).with_name("takecompare.js"), media_type="text/javascript"
        )

    @app.get("/api/config")
    def config():
        return {
            "backend": backend,
            "max_renders": max_renders,
            "renders_used": len(
                [p for p in jobs.glob("*/request.json") if not local_take(p.parent)]
            ),
            "demo": bool(demo_dir and (demo_dir / "reshoot.mp4").is_file()),
            "connected": inference_enabled and backend_available(),
            "look_connected": inference_enabled and look_available(),
            "inference_enabled": inference_enabled,
            "look_engine": look_engine,
            "look_model": "FLUX.2 Klein 4B FP8"
            if look_engine == "klein-cloud"
            else "FLUX.2 Klein 4B"
            if klein
            else "MOSS Image SFT BF16",
            "look_presets": {
                "warm": "A photorealistic cinematic photograph with golden amber key light, copper-toned highlights and deep plum shadows. Rich natural textures, low-angle warm illumination, realistic materials and fine detail. The source subject, object positions, silhouettes and camera framing remain unchanged. Only existing objects are present. No added objects, lamps, light fixtures, text, logos or people.",
                "blue": "A photorealistic cinematic photograph in deep blue-hour ambient light, cyan highlights and dark teal shadows. Low-key twilight exposure, rich natural textures, realistic materials and fine detail. The source subject, object positions, silhouettes and camera framing remain unchanged. Only existing objects are present. No added objects, lamps, light fixtures, text, logos or people.",
            }
            if klein
            else None,
            "max_looks": max_looks,
            "looks_used": len(list(looks.glob("*/request.json")))
            + len(list(looks.glob("*/product-look.json"))),
            "product_refine": look_engine != "klein-cloud",
            "autobrief": bool(os.environ.get("GRID_API_KEY", "").strip()),
            "estimates": estimates.table(backend, look_engine == "klein-cloud"),
            "presets": [
                {
                    "id": preset.id,
                    "kind": preset.kind,
                    "name": preset.name,
                    "version": preset.version,
                    "motion": preset.motion,
                    "trim_end": preset.trim_end,
                    "preview_url": f"/preset-previews/{preset.id}.mp4",
                }
                for preset in camera_presets.available()
            ],
            "camera_moves": [
                {"id": move.id, "name": move.name, "motion": move.motion}
                for move in camera_presets.SCENE_MOVES
            ],
            "styles": [
                {
                    "id": style.id,
                    "name": style.name,
                    "version": style.version,
                    "blurb": style.blurb,
                    "look": style.look,
                    "motion": style.motion,
                    "source": style.source,
                    "preview_url": f"/style-previews/{style.id}.mp4",
                    "poster_url": f"/style-previews/{style.id}.jpg",
                    "example_url": f"/style-previews/examples/{style.example}.mp4",
                }
                for style in transform_styles.available()
            ],
            "closing_supported": inference_enabled and closing_available(),
            "tool_backend": tool_backend,
            # Cached readiness only (None until a run checks); config makes
            # no extra worker requests.
            "tools": {
                tool: True
                if tool in ("reframe", "captions")
                else tool_readiness.get(tool, (0.0, None))[1]
                for tool in (
                    "fps-boost",
                    "remove-background",
                    "upscale",
                    "depth-map",
                    "reframe",
                    "extend",
                    "captions",
                )
            },
            "modes": ["video", "text", "image", "audio"],
            "formats": {
                name: {
                    "width": video_format(name).output_size[0],
                    "height": video_format(name).output_size[1],
                }
                for name in ("landscape", "portrait", "square")
            },
        }

    @app.get("/api/demo/{kind}")
    def demo(kind: str):
        if not demo_dir or kind not in ("source", "output"):
            raise HTTPException(404)
        path = demo_dir / ("source.mp4" if kind == "source" else "reshoot.mp4")
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="video/mp4")

    @app.post("/api/demo/source")
    def use_demo():
        if not demo_dir or not (demo_dir / "source.mp4").is_file():
            raise HTTPException(404)
        source_id = uuid.uuid4().hex
        path = sources / source_id
        path.mkdir()
        shutil.copyfile(demo_dir / "source.mp4", path / "source.mp4")
        return {"source_id": source_id, "name": "Example clip"}

    @app.post("/api/sources")
    async def upload_source_file(request: Request):
        return await single_upload(request, upload)

    def upload(file: UploadFile):
        source_id = uuid.uuid4().hex
        folder = sources / source_id
        folder.mkdir()
        path = folder / "source.mp4"
        try:
            size = 0
            with path.open("wb") as target:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        raise HTTPException(413, "Choose a video smaller than 100 MB.")
                    target.write(chunk)
            info = probe(path)
            if not any(s["codec_type"] == "video" for s in info["streams"]):
                raise HTTPException(400, "The upload has no video stream.")
            if float(info["format"]["duration"]) < 5:
                raise HTTPException(400, "Choose a clip at least five seconds long.")
            preview = folder / "preview"
            preview.mkdir()
            prepare_source(path, preview)
            (folder / "source.json").write_text(
                json.dumps(
                    {
                        "name": Path(file.filename or "Video").name,
                        "duration": float(info["format"]["duration"]),
                        "has_audio": any(
                            s["codec_type"] == "audio" for s in info["streams"]
                        ),
                    }
                )
            )
        except (subprocess.SubprocessError, OSError, KeyError, ValueError) as error:
            shutil.rmtree(folder)
            raise HTTPException(400, "This video could not be read.") from error
        except HTTPException:
            shutil.rmtree(folder)
            raise
        return {"source_id": source_id, "name": Path(file.filename or "Video").name}

    @app.get("/api/sources/{source_id}")
    def source(
        source_id: str,
        frame_format: Literal["landscape", "portrait", "square"] = "landscape",
        source_start: float = Query(default=0, ge=0, le=86400, allow_inf_nan=False),
        seconds: int = 5,
    ):
        if seconds not in (5, 10, 15):
            raise HTTPException(422, "Choose a 5, 10 or 15 second window.")
        return FileResponse(
            window_path(
                source_id,
                SourceWindow(
                    frame_format=frame_format,
                    source_start=source_start,
                    seconds=seconds,
                ),
            ),
            media_type="video/mp4",
        )

    @app.get("/api/sources/{source_id}/frame")
    def preview_source_frame(
        source_id: str,
        frame_index: int = 0,
        frame_format: Literal["landscape", "portrait", "square"] = "landscape",
        source_start: float = Query(default=0, ge=0, le=86400, allow_inf_nan=False),
        seconds: int = 5,
    ):
        from .look import source_frame

        if seconds not in (5, 10, 15) or frame_index not in (0, seconds * 24):
            raise HTTPException(422, "Choose the opening or the take's last frame.")
        prepared = window_path(
            source_id,
            SourceWindow(
                frame_format=frame_format, source_start=source_start, seconds=seconds
            ),
        )
        target = prepared.parent / f"frame-{frame_index}.png"
        with work_capacity() if not target.is_file() else nullcontext(), preview_lock:
            if not target.is_file():
                with tempfile.TemporaryDirectory(dir=prepared.parent) as directory:
                    try:
                        source_frame(prepared, Path(directory), frame_index).replace(
                            target
                        )
                    except subprocess.CalledProcessError as error:
                        raise HTTPException(
                            400, "This source frame could not be read."
                        ) from error
        return FileResponse(target, media_type="image/png")

    @app.get("/api/sources/{source_id}/info")
    def source_info(source_id: str):
        original = source_path(source_id)
        metadata = original.parent / "source.json"
        data = (
            json.loads(metadata.read_text())
            if metadata.is_file()
            else {
                "name": "Source clip",
                "duration": float(probe(original)["format"]["duration"]),
            }
        )
        if "has_audio" not in data:
            data["has_audio"] = any(
                s["codec_type"] == "audio" for s in probe(original)["streams"]
            )
        return {"source_id": source_id, **data}

    @app.post("/api/looks")
    async def upload_look_file(
        request: Request,
        frame_format: Literal["landscape", "portrait", "square"] = "landscape",
    ):
        return await single_upload(request, upload_look, frame_format)

    def upload_look(
        file: UploadFile,
        frame_format: Literal["landscape", "portrait", "square"] = "landscape",
    ):
        look_id = uuid.uuid4().hex
        folder = looks / look_id
        folder.mkdir()
        source = folder / "upload"
        try:
            size = 0
            with source.open("wb") as target:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 12 * 1024 * 1024:
                        raise HTTPException(
                            413, "Choose a look frame smaller than 12 MB."
                        )
                    target.write(chunk)
            prepare_look(source, folder, frame_format=frame_format)
            (folder / "upload.json").write_text(
                json.dumps({"frame_format": frame_format})
            )
            source.unlink()
        except ValueError as error:
            shutil.rmtree(folder)
            raise HTTPException(400, str(error)) from error
        except OSError as error:
            shutil.rmtree(folder)
            raise HTTPException(400, "This look frame could not be read.") from error
        except HTTPException:
            shutil.rmtree(folder)
            raise
        return {"look_id": look_id, "url": f"/api/looks/{look_id}"}

    @app.get("/api/looks/{look_id}")
    def look(look_id: str):
        return FileResponse(look_path(look_id), media_type="image/png")

    @app.post("/api/prompt-helper")
    def prompt_helper(body: PromptIdea):
        try:
            return promptkit.suggest(body.idea, body.mode)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    # Saved styles: looks the user liked, kept as named tiles in their style
    # library. Each keeps its wording, optional style picture and a poster.
    my_styles = directory / "my-styles"
    my_styles_lock = threading.Lock()

    def read_my_styles() -> list[dict]:
        try:
            return json.loads((my_styles / "styles.json").read_text())
        except (OSError, ValueError):
            return []

    def write_my_styles(items: list[dict]) -> None:
        my_styles.mkdir(exist_ok=True)
        temporary = my_styles / "styles.json.tmp"
        temporary.write_text(json.dumps(items, indent=1))
        temporary.replace(my_styles / "styles.json")

    def my_style_path(style_id: str) -> Path:
        if not re.fullmatch(r"my-[0-9a-f]{12}", style_id):
            raise HTTPException(404, "Saved style not found.")
        path = my_styles / f"{style_id}.png"
        if not path.is_file():
            raise HTTPException(404, "Saved style not found.")
        return path

    @app.get("/api/my-styles")
    def list_my_styles():
        return read_my_styles()

    @app.post("/api/my-styles")
    def save_my_style(body: SavedStyle):
        poster = look_path(body.poster_id)
        if body.style_image_id:
            look_path(body.style_image_id)
        with my_styles_lock:
            items = read_my_styles()
            if len(items) >= 48:
                raise HTTPException(409, "Your library holds 48 styles; remove one.")
            style_id = f"my-{uuid.uuid4().hex[:12]}"
            my_styles.mkdir(exist_ok=True)
            with Image.open(poster) as image:
                thumb = image.convert("RGB")
                thumb.thumbnail((768, 768))
                thumb.save(my_styles / f"{style_id}.png")
            item = {
                "id": style_id,
                "name": body.name,
                "look": body.look,
                "motion": body.motion,
                "style_image_id": body.style_image_id,
                "poster_url": f"/api/my-styles/{style_id}/poster",
                "saved_at": time.time(),
            }
            write_my_styles([item, *items])
        return item

    @app.get("/api/my-styles/{style_id}/poster")
    def my_style_poster(style_id: str):
        return FileResponse(my_style_path(style_id), media_type="image/png")

    @app.delete("/api/my-styles/{style_id}")
    def delete_my_style(style_id: str):
        path = my_style_path(style_id)
        with my_styles_lock:
            write_my_styles([s for s in read_my_styles() if s["id"] != style_id])
            path.unlink(missing_ok=True)
        return {"deleted": style_id}

    @app.post("/api/audio")
    async def upload_audio_file(
        request: Request,
        purpose: Literal["conditioning", "soundtrack"] = "conditioning",
    ):
        return await single_upload(request, upload_audio, purpose)

    def upload_audio(
        file: UploadFile,
        purpose: Literal["conditioning", "soundtrack"] = "conditioning",
    ):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in AUDIO_FORMATS:
            raise HTTPException(
                400, "Choose WAV, MP3, M4A, FLAC, Ogg, AAC or WebM audio."
            )
        audio_id = uuid.uuid4().hex
        folder = audios / audio_id
        folder.mkdir()
        original = folder / ("original" + suffix)
        try:
            size = 0
            with original.open("wb") as output:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 50 * 1024 * 1024:
                        raise HTTPException(413, "Choose audio smaller than 50 MB.")
                    output.write(chunk)
            info = (
                audio_info(original)
                if purpose == "conditioning"
                else audio_info(original, min_duration=0.1)
            )
            sound = next(s for s in info["streams"] if s["codec_type"] == "audio")
            data = {
                "audio_id": audio_id,
                "suffix": suffix,
                "name": Path(file.filename or "Audio").name,
                "duration": float(sound.get("duration") or info["format"]["duration"]),
            }
            (folder / "audio.json").write_text(json.dumps(data))
        except HTTPException:
            shutil.rmtree(folder)
            raise
        except (
            ValueError,
            KeyError,
            TypeError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            shutil.rmtree(folder)
            raise HTTPException(
                400,
                "This audio file could not be read or is outside the supported limits.",
            ) from error
        return {
            "audio_id": audio_id,
            "name": data["name"],
            "duration": data["duration"],
        }

    @app.get("/api/audio/{audio_id}/info")
    def describe_audio(audio_id: str):
        original = audio_path(audio_id)
        data = json.loads((original.parent / "audio.json").read_text())
        return {key: data[key] for key in ("audio_id", "name", "duration")}

    @app.get("/api/audio/{audio_id}")
    def audio_preview(
        audio_id: str,
        source_start: float = Query(default=0, ge=0, le=1800, allow_inf_nan=False),
    ):
        return FileResponse(
            audio_window(audio_id, source_start), media_type="audio/wav"
        )

    @app.get("/api/audio/{audio_id}/soundtrack")
    def soundtrack_preview(
        audio_id: str,
        source_start: float = Query(default=0, ge=0, le=1800, allow_inf_nan=False),
        frames: int = Query(default=120, ge=1, le=720),
    ):
        original = audio_path(audio_id)
        windows = original.parent / "soundtrack-previews"
        key = hashlib.sha256(f"{source_start}:{frames}".encode()).hexdigest()[:24]
        target = windows / key
        with (
            (
                work_capacity()
                if not (target / "preview.wav").is_file()
                else nullcontext()
            ),
            preview_lock,
        ):
            if not (target / "preview.wav").is_file():
                windows.mkdir(exist_ok=True)
                if len(list(windows.glob("*/preview.wav"))) >= 16:
                    raise HTTPException(
                        429, "Soundtrack preview limit reached for this upload."
                    )
                temporary = Path(tempfile.mkdtemp(prefix=".preparing-", dir=windows))
                try:
                    prepare_layer(
                        audios,
                        AudioLayer(
                            audio_id=audio_id,
                            source_start=source_start,
                            duration_frames=frames,
                        ),
                        temporary,
                        "preview",
                    )
                    # Keep only the bounded listening copy, not a duplicate input.
                    for extra in temporary.iterdir():
                        if extra.name != "preview.wav":
                            extra.unlink()
                    temporary.rename(target)
                except (
                    ValueError,
                    KeyError,
                    OSError,
                    subprocess.SubprocessError,
                ) as error:
                    raise HTTPException(
                        400, "This soundtrack section could not be prepared."
                    ) from error
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
        return FileResponse(target / "preview.wav", media_type="audio/wav")

    @app.get("/api/look-jobs")
    def list_look_jobs():
        return [
            describe_look(p.parent.name)
            for p in sorted(asset_records(looks), key=lambda p: p.stat().st_mtime)
        ]

    @app.post("/api/look-jobs")
    def generate_look(body: LookRequest):
        if not body.prompt.strip():
            raise HTTPException(400, "Add a look direction.")
        with lock:
            folder = asset_folder(looks, body.request_id)
            if folder.exists():
                if not (folder / "request.json").is_file():
                    raise HTTPException(409, "This ID belongs to an uploaded image.")
                old = json.loads((folder / "request.json").read_text())
                if LookRequest.model_validate(old).model_dump() != body.model_dump():
                    raise HTTPException(
                        409, "This request ID belongs to a different look."
                    )
                return describe_look(body.request_id)
            if body.project_id:
                project = project_data(body.project_id)
                if project.revision != body.project_revision:
                    raise HTTPException(
                        409,
                        "Save or reopen the current project before generating a look.",
                    )
                try:
                    expected = project.look_request(
                        body.shot_id, body.request_id, look_engine
                    )
                except (KeyError, ValueError) as error:
                    raise HTTPException(409, str(error)) from error
                if expected != body:
                    raise HTTPException(
                        409, "The look does not match its saved shot audition."
                    )
            source_file = None
            if body.look_input == "video":
                source_file = source_path(body.source_id)
                window_path(
                    body.source_id, SourceWindow.model_validate(body.model_dump())
                )
            elif body.look_input == "image":
                source_file = look_path(body.image_id)
            existing = list(looks.glob("*/request.json"))
            if len(existing) >= max_looks:
                raise HTTPException(429, "This session's look limit has been reached.")
            for path in existing:
                old = describe_look(path.parent.name)
                if old["active"] or old["status"] not in (
                    "succeeded",
                    "failed",
                    "cancelled",
                ):
                    raise HTTPException(
                        409, "Finish or recover the current look first."
                    )
            if (look_engine == "moss") != (body.denoise is not None):
                raise HTTPException(
                    422,
                    "Choose a MOSS denoise value."
                    if look_engine == "moss"
                    else "Klein uses reference conditioning, not a denoise control.",
                )
            if look_engine == "moss" and (
                (body.look_input == "text" and body.denoise != 1.0)
                or (body.look_input != "text" and body.denoise == 1.0)
            ):
                raise HTTPException(
                    422,
                    "Text looks use full noise; image/video looks use a supported denoise value.",
                )
            if (body.style_image_id or body.reference_ids) and not klein:
                raise HTTPException(422, "Reference images need the Klein look engine.")
            reference_files = [
                look_path(item)
                for item in [
                    *([body.style_image_id] if body.style_image_id else []),
                    *body.reference_ids,
                ]
            ]
            if (
                not look_available(force=True)
                or (look_engine == "moss" and not moss_models_available())
                or (look_engine == "klein" and not klein_models_available(False))
            ):
                raise HTTPException(
                    503,
                    "Comfy Cloud is unavailable. No look was created or submitted."
                    if look_engine == "klein-cloud"
                    else "Klein worker or models unavailable. No look was created or submitted."
                    if look_engine == "klein"
                    else "MOSS worker or models unavailable. No look was created or submitted.",
                )
            folder.mkdir()
            (folder / "request.json").write_text(
                json.dumps({**body.model_dump(), "engine": look_engine}) + "\n"
            )
            start(
                folder,
                [
                    "look",
                    *([str(source_file)] if source_file else []),
                    "--look-input",
                    body.look_input,
                    "--prompt",
                    body.prompt,
                    "--seed",
                    str(body.seed),
                    "--engine",
                    look_engine,
                    "--frame-index",
                    str(body.frame_index),
                    "--seconds",
                    str(body.seconds),
                    "--format",
                    body.frame_format,
                    "--source-start",
                    str(body.source_start),
                    "--run-dir",
                    str(folder / "render"),
                    "--execute",
                ]
                + (["--denoise", str(body.denoise)] if body.denoise is not None else [])
                + [
                    argument
                    for reference in reference_files
                    for argument in ("--style-image", str(reference))
                ],
            )
            return describe_look(body.request_id)

    @app.get("/api/look-jobs/{job_id}")
    def look_status(job_id: str):
        return describe_look(job_id)

    @app.get("/api/look-jobs/{job_id}/{kind}")
    def download_look(job_id: str, kind: str):
        folder = look_job_path(job_id)
        request = LookRequest.model_validate_json((folder / "request.json").read_text())
        if kind == "settings":
            state = render_metadata(folder)
            return JSONResponse(
                {
                    "version": 1,
                    "model": describe_look(job_id)["model"],
                    "prompt": request.prompt,
                    "seed": request.seed,
                    "denoise": request.denoise,
                    "look_input": request.look_input,
                    "frame_format": request.frame_format,
                    "frame_index": request.frame_index,
                    "source_start": request.source_start,
                    "negative_skip_layers": state.get("negative_skip_layers", []),
                    "source": "source.png"
                    if (folder / "render" / "source.png").is_file()
                    else None,
                    "workflow": "workflow.json",
                },
                headers={
                    "Content-Disposition": 'attachment; filename="look-settings.json"'
                },
            )
        paths = {
            "workflow": folder / "render" / "workflow.json",
            "source": folder / "render" / "source.png",
        }
        path = paths.get(kind)
        if not path or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, filename=path.name)

    @app.post("/api/look-jobs/{job_id}/resume")
    def resume_look(job_id: str):
        with lock:
            folder = look_job_path(job_id)
            state_path = folder / "render" / "job.json"
            if not state_path.exists() or not json.loads(state_path.read_text()).get(
                "job_id"
            ):
                raise HTTPException(
                    409, "No saved look job ID; manual review is required."
                )
            old = describe_look(job_id)
            if not old["active"] and not old["output_url"]:
                start(folder, ["resume", str(folder / "render")])
            return describe_look(job_id)

    @app.get("/api/jobs")
    def list_jobs():
        return [
            describe(p.parent.name)
            for p in sorted(asset_records(jobs), key=lambda p: p.stat().st_mtime)
        ]

    @app.post("/api/jobs")
    def generate(body: TakeRequest):
        if not body.prompt.strip():
            raise HTTPException(400, "Add an art direction.")
        source_file = source_path(body.source_id) if body.source_id else None
        if body.source_id:
            normalized = window_path(
                body.source_id, SourceWindow.model_validate(body.model_dump())
            )
            if body.render_profile == "single-pass-audio":
                try:
                    from .generation import audio_info

                    audio_info(normalized)
                except (ValueError, subprocess.CalledProcessError) as error:
                    raise HTTPException(
                        400,
                        "Single-pass speech needs a video with an audio track covering the selected range.",
                    ) from error
        sound_file = audio_path(body.audio_id) if body.audio_id else None
        if body.audio_id:
            audio_window(body.audio_id, body.source_start)
        if body.closing_id and not body.look_id:
            raise HTTPException(400, "Choose an opening look before a closing look.")
        look_file = (
            reference_path(body.look_id, body.source_id, 0, body)
            if body.look_id
            else None
        )
        closing_file = (
            reference_path(
                body.closing_id,
                body.source_id,
                0 if body.closing_id == body.look_id else body.seconds * 24,
                body,
            )
            if body.closing_id
            else None
        )
        with lock:
            folder = asset_folder(jobs, body.request_id)
            if folder.exists():
                old = json.loads((folder / "request.json").read_text())
                if TakeRequest.model_validate(old).model_dump() != body.model_dump():
                    raise HTTPException(
                        409, "This request ID belongs to a different take."
                    )
                return describe(body.request_id)
            if body.project_id:
                project = project_data(body.project_id)
                try:
                    expected = project.request(body.shot_id, body.request_id)
                except ValueError as error:
                    raise HTTPException(
                        409, "The saved shot is not renderable."
                    ) from error
                if body != expected:
                    raise HTTPException(
                        409,
                        "Render the current saved shot, not a stale or modified snapshot.",
                    )
            existing = [
                path
                for path in jobs.glob("*/request.json")
                if not local_take(path.parent)
            ]
            if len(existing) >= max_renders:
                raise HTTPException(
                    429, "This session's render limit has been reached."
                )
            for path in existing:
                old = describe(path.parent.name)
                if old["active"] or old["status"] not in (
                    "succeeded",
                    "failed",
                    "cancelled",
                ):
                    raise HTTPException(
                        409, "Finish or recover the current take first."
                    )
            if not backend_available(force=True):
                raise HTTPException(
                    503,
                    "Comfy Cloud is unavailable. Check COMFY_API_KEY, network access and account status. No take was submitted."
                    if backend == "cloud"
                    else "Worker connection unavailable. No take was created or submitted.",
                )
            if closing_file and not closing_available():
                raise HTTPException(
                    503,
                    "Closing-look execution is unavailable on this backend. No take was submitted.",
                )
            folder.mkdir()
            (folder / "request.json").write_text(body.model_dump_json())
            if look_file:
                shutil.copyfile(look_file, folder / "look.png")
            if closing_file:
                shutil.copyfile(closing_file, folder / "closing.png")
            start(
                folder,
                [
                    *(
                        ["reshoot", str(source_file), "--model", "ltx25"]
                        if source_file
                        else ["generate", "--mode", body.mode]
                    ),
                    "--prompt",
                    body.prompt,
                    "--seed",
                    str(body.seed),
                    "--format",
                    body.frame_format,
                    "--render-profile",
                    body.render_profile,
                    "--source-start",
                    str(body.source_start),
                    *(["--seconds", str(body.seconds)] if body.seconds != 5 else []),
                    *(
                        ["--motion-strength", str(body.motion_strength)]
                        if body.motion_strength != 1.0
                        else []
                    ),
                    "--run-dir",
                    str(folder / "render"),
                    "--backend",
                    backend,
                    "--execute",
                ]
                + (["--audio", str(sound_file)] if sound_file else [])
                + (["--look-frame", str(folder / "look.png")] if look_file else [])
                + (
                    ["--closing-frame", str(folder / "closing.png")]
                    if closing_file
                    else []
                ),
            )
            return describe(body.request_id)

    @app.get("/api/jobs/{job_id}")
    def status(job_id: str):
        return describe(job_id)

    @app.post("/api/jobs/{job_id}/resume")
    def resume(job_id: str):
        with lock:
            folder = job_path(job_id)
            state_path = folder / "render" / "job.json"
            if not state_path.exists() or not json.loads(state_path.read_text()).get(
                "job_id"
            ):
                raise HTTPException(409, "No saved job ID; manual review is required.")
            old = describe(job_id)
            if not old["active"] and not old["output_url"]:
                start(folder, ["resume", str(folder / "render")])
            return describe(job_id)

    @app.get("/api/jobs/{job_id}/{kind}")
    def download(job_id: str, kind: str):
        folder = job_path(job_id)
        take = json.loads((folder / "request.json").read_text())
        references = {
            "look": asset_folder(looks, take["look_id"])
            if take.get("look_id")
            else looks / "absent",
            "closing": asset_folder(looks, take["closing_id"])
            if take.get("closing_id")
            else looks / "absent",
        }

        def metadata(role: str):
            reference = references[role]
            request_path = reference / "request.json"
            if request_path.is_file():
                request = json.loads(request_path.read_text())
                state = render_metadata(reference)
                return {
                    "model": state.get("model", "MOSS Image SFT BF16"),
                    "prompt": request["prompt"],
                    "seed": request["seed"],
                    "denoise": request["denoise"],
                    "negative_skip_layers": state.get("negative_skip_layers", []),
                    "source_frame_index": state.get(
                        "source_frame_index", request.get("frame_index", 0)
                    ),
                    "source": ("source.png" if role == "look" else "closing-source.png")
                    if (reference / "render" / "source.png").is_file()
                    else None,
                    "workflow": f"{role}-workflow.json",
                }
            return None

        if kind == "settings":
            return JSONResponse(
                {
                    "version": 1,
                    "model": "ltx25",
                    "ai_generated": True,
                    "prompt": take["prompt"],
                    "art_direction": take.get("art_direction"),
                    "motion_prompt": take.get("motion_prompt"),
                    "project_id": take.get("project_id"),
                    "shot_id": take.get("shot_id"),
                    "project_revision": take.get("project_revision"),
                    "shared_direction": take.get("shared_direction"),
                    "seed": take["seed"],
                    "mode": take.get("mode", "video"),
                    "source": "source.mp4"
                    if take.get("source_id")
                    else "source.wav"
                    if take.get("audio_id")
                    else None,
                    "audio_conditioned": bool(take.get("audio_id"))
                    or take.get("render_profile") == "single-pass-audio",
                    "render_profile": take.get("render_profile", "two-pass"),
                    "spatial_refinement": take.get("render_profile", "two-pass")
                    == "two-pass",
                    "export_resize": "lanczos-2x"
                    if take.get("render_profile") == "single-pass-audio"
                    else None,
                    "native_width": video_format(
                        take.get("frame_format", "landscape")
                    ).width
                    * (1 if take.get("render_profile") == "single-pass-audio" else 2),
                    "native_height": video_format(
                        take.get("frame_format", "landscape")
                    ).height
                    * (1 if take.get("render_profile") == "single-pass-audio" else 2),
                    "conditioning_audio": "source.wav"
                    if take.get("audio_id")
                    or take.get("render_profile") == "single-pass-audio"
                    else None,
                    "look_frame": "look.png" if take.get("look_id") else None,
                    "closing_frame": "closing.png" if take.get("closing_id") else None,
                    "closing_frame_index": take.get("seconds", 5) * 24
                    if take.get("closing_id")
                    else None,
                    "closing_strength": 0.7 if take.get("closing_id") else None,
                    "closing_reuses_opening": bool(take.get("look_id"))
                    and take.get("closing_id") == take.get("look_id"),
                    "motion_strength": take.get("motion_strength", 1.0)
                    if take.get("mode", "video") == "video"
                    else None,
                    "opening_look": metadata("look"),
                    "closing_look": metadata("closing"),
                    "fps": 24,
                    "seconds": take.get("seconds", 5),
                    "model_frames": take.get("seconds", 5) * 24 + 1,
                    "export_frames": take.get("seconds", 5) * 24,
                    "frame_format": take.get("frame_format", "landscape"),
                    "source_start": take.get("source_start", 0),
                    "width": video_format(
                        take.get("frame_format", "landscape")
                    ).output_size[0],
                    "height": video_format(
                        take.get("frame_format", "landscape")
                    ).output_size[1],
                },
                headers={
                    "Content-Disposition": 'attachment; filename="openreshoot-take.json"'
                },
            )
        if kind in ("compare-split", "compare-wipe"):
            render = folder / "render"
            result, original = render / "reshoot.mp4", render / "source.mp4"
            if take.get("mode", "video") != "video" or not (
                result.is_file() and original.is_file()
            ):
                raise HTTPException(404, "Before/after needs a finished video take.")
            target = render / f"{kind}.mp4"
            if not target.is_file():
                partial = render / f"{kind}.partial.mp4"
                with work_capacity(), preview_lock:
                    try:
                        video_tools.compare(original, result, partial, kind[8:])
                    except (ValueError, OSError, subprocess.SubprocessError) as error:
                        partial.unlink(missing_ok=True)
                        raise HTTPException(
                            400, "This before/after could not be made."
                        ) from error
                    partial.replace(target)
            return FileResponse(
                target, filename=f"openfield-{job_id[:8]}-before-after-{kind[8:]}.mp4"
            )
        if kind == "comfyui":
            render = folder / "render"
            if not (render / "workflow.json").is_file():
                raise HTTPException(404)
            name = f"openfield-{job_id[:8]}"
            return Response(
                comfybundle.bundle(render, name),
                media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="{name}-comfyui.zip"'
                },
            )
        paths = {
            "output": folder / "render" / "reshoot.mp4",
            "workflow": folder / "render" / "workflow.json",
            "source": folder
            / "render"
            / ("source.wav" if take.get("audio_id") else "source.mp4"),
            "conditioning-audio": folder / "render" / "source.wav",
            "look": folder / "render" / "look.png",
            "closing": folder / "render" / "closing.png",
        }
        for role, reference in references.items():
            if (reference / "request.json").is_file():
                paths.update(
                    {
                        f"{role}-workflow": reference / "render" / "workflow.json",
                        f"{role}-source": reference / "render" / "source.png",
                    }
                )
        path = paths.get(kind)
        if not path or not path.is_file():
            raise HTTPException(404)
        return FileResponse(
            path,
            filename=f"{kind}.json"
            if kind in ("look-workflow", "closing-workflow")
            else "closing-source.png"
            if kind == "closing-source"
            else path.name
            if kind in ("source", "look", "closing", "look-source")
            else f"openreshoot-{job_id[:8]}-{path.name}",
        )

    # Whole-clip restyle: an orchestrator process drives this studio's own
    # loopback API, one look and one take at a time (see wholevideo.py).
    restyles = directory / "restyles"
    restyles.mkdir(exist_ok=True)

    def restyle_folder(restyle_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", restyle_id):
            raise HTTPException(404, "Restyle not found.")
        folder = restyles / restyle_id
        if not (folder / "request.json").is_file():
            raise HTTPException(404, "Restyle not found.")
        return folder

    def describe_restyle(restyle_id: str) -> dict:
        folder = restyle_folder(restyle_id)
        try:
            state = json.loads((folder / "state.json").read_text())
        except (OSError, ValueError):
            state = {"status": "starting"}
        process = processes.get(folder)
        active = process is not None and process.poll() is None
        if not active and state.get("status") in ("starting", "running"):
            state = {**state, "status": "needs_recovery"}
        done = (folder / "whole.mp4").is_file()
        return {
            **json.loads((folder / "request.json").read_text()),
            "id": restyle_id,
            "active": active,
            "status": state.get("status"),
            "step": state.get("step"),
            "error": state.get("error"),
            "windows": state.get("windows"),
            "takes_done": state.get("takes_done", 0),
            "output_url": f"/api/restyles/{restyle_id}/output" if done else None,
        }

    @app.post("/api/restyles")
    def start_restyle(body: WholeRestyle, request: Request):
        if not klein:
            raise HTTPException(409, "Whole-clip restyle needs a Klein look engine.")
        source_path(body.source_id)
        if body.style_image_id:
            look_path(body.style_image_id)
        folder = restyles / body.request_id
        if folder.is_dir():
            return describe_restyle(body.request_id)
        if any(p.poll() is None for f, p in processes.items() if f.parent == restyles):
            raise HTTPException(409, "Finish the current whole-clip restyle first.")
        folder.mkdir()
        (folder / "request.json").write_text(body.model_dump_json(indent=1))
        studio_url = f"http://127.0.0.1:{request.url.port or 80}"
        start(folder, [str(folder), "--studio", studio_url], "aipg_cinema.wholevideo")
        return describe_restyle(body.request_id)

    @app.post("/api/restyles/{restyle_id}/resume")
    def resume_restyle(restyle_id: str, request: Request):
        folder = restyle_folder(restyle_id)
        current = describe_restyle(restyle_id)
        if current["active"] or current["status"] == "succeeded":
            return current
        studio_url = f"http://127.0.0.1:{request.url.port or 80}"
        start(folder, [str(folder), "--studio", studio_url], "aipg_cinema.wholevideo")
        return describe_restyle(restyle_id)

    @app.get("/api/restyles/{restyle_id}")
    def get_restyle(restyle_id: str):
        return describe_restyle(restyle_id)

    @app.get("/api/restyles/{restyle_id}/output")
    def restyle_output(restyle_id: str):
        path = restyle_folder(restyle_id) / "whole.mp4"
        if not path.is_file():
            raise HTTPException(404, "The whole-clip restyle is not finished.")
        return FileResponse(
            path, media_type="video/mp4", filename=f"openfield-{restyle_id[:8]}.mp4"
        )

    # Replace the person (beta): replace.py rebuilds the talking person from a
    # photo through this studio's loopback API, one image or take at a time.
    replacements = directory / "replacements"
    replacements.mkdir(exist_ok=True)

    def replacement_folder(replacement_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", replacement_id):
            raise HTTPException(404, "Replacement not found.")
        folder = replacements / replacement_id
        if not (folder / "request.json").is_file():
            raise HTTPException(404, "Replacement not found.")
        return folder

    def describe_replacement(replacement_id: str) -> dict:
        folder = replacement_folder(replacement_id)
        try:
            state = json.loads((folder / "state.json").read_text())
        except (OSError, ValueError):
            state = {"status": "starting"}
        process = processes.get(folder)
        active = process is not None and process.poll() is None
        if not active and state.get("status") in ("starting", "running"):
            state = {**state, "status": "needs_recovery"}
        base = f"/api/replacements/{replacement_id}"
        return {
            **json.loads((folder / "request.json").read_text()),
            "id": replacement_id,
            "active": active,
            "status": state.get("status"),
            "step": state.get("step"),
            "error": state.get("error"),
            "output_url": f"{base}/output"
            if (folder / "replaced.mp4").is_file()
            else None,
            "compare_url": f"{base}/compare"
            if (folder / "compare.mp4").is_file()
            else None,
        }

    def launch_replacement(folder: Path, request: Request) -> None:
        studio_url = f"http://127.0.0.1:{request.url.port or 80}"
        start(folder, [str(folder), "--studio", studio_url], "aipg_cinema.replace")

    @app.post("/api/replacements")
    def start_replacement(body: PersonReplacement, request: Request):
        if not klein:
            raise HTTPException(409, "Replacing a person needs a Klein look engine.")
        source_path(body.source_id)
        look_path(body.photo_id)
        folder = replacements / body.request_id
        if folder.is_dir():
            return describe_replacement(body.request_id)
        if any(
            p.poll() is None for f, p in processes.items() if f.parent == replacements
        ):
            raise HTTPException(409, "Finish the current replacement first.")
        folder.mkdir()
        (folder / "request.json").write_text(body.model_dump_json(indent=1))
        launch_replacement(folder, request)
        return describe_replacement(body.request_id)

    @app.post("/api/replacements/{replacement_id}/resume")
    def resume_replacement(replacement_id: str, request: Request):
        current = describe_replacement(replacement_id)
        if not current["active"] and current["status"] != "succeeded":
            launch_replacement(replacement_folder(replacement_id), request)
        return describe_replacement(replacement_id)

    @app.get("/api/replacements/{replacement_id}")
    def get_replacement(replacement_id: str):
        return describe_replacement(replacement_id)

    @app.get("/api/replacements/{replacement_id}/{kind}")
    def replacement_file(replacement_id: str, kind: Literal["output", "compare"]):
        name = "replaced.mp4" if kind == "output" else "compare.mp4"
        path = replacement_folder(replacement_id) / name
        if not path.is_file():
            raise HTTPException(404, "The replacement is not finished.")
        return FileResponse(
            path,
            media_type="video/mp4",
            filename=f"openfield-{replacement_id[:8]}-{name}",
        )

    tool_runs = directory / "tools"
    tool_runs.mkdir(exist_ok=True)
    tool_readiness: dict[str, tuple[float, bool]] = {}
    max_tool_runs = 24

    def tool_ready(tool: str) -> bool:
        """Reframe is local; model tools need their file on the tool backend."""
        if tool in ("reframe", "captions"):
            return True
        if tool == "extend":
            return inference_enabled and backend_available(force=True)
        if not inference_enabled:
            return False
        checked_at, ready = tool_readiness.get(tool, (0.0, False))
        if checked_at and time.monotonic() - checked_at < 60:
            return ready
        ready = False
        try:
            if tool_backend == "cloud":
                # Names the Cloud URL explicitly; COMFY_BASE_URL may be local.
                ready = cloud_available(look=True)
            else:
                loader, field = video_tools.LOADERS[tool]
                upstream = local_url(os.environ.get("COMFY_UPSTREAM_URL", ""))
                response = httpx.get(f"{upstream}/object_info/{loader}", timeout=3)
                response.raise_for_status()
                inputs = response.json()[loader]["input"]
                options = {**inputs.get("required", {}), **inputs.get("optional", {})}[
                    field
                ]
                names = options[1].get("options") if len(options) > 1 else None
                names = names or (options[0] if isinstance(options[0], list) else [])
                ready = video_tools.MODELS[tool][1] in names
        except (
            httpx.HTTPError,
            AttributeError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ):
            ready = False
        tool_readiness[tool] = (time.monotonic(), ready)
        return ready

    def tool_folder(tool_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", tool_id):
            raise HTTPException(404, "Tool run not found.")
        folder = tool_runs / tool_id
        if not (folder / "request.json").is_file():
            raise HTTPException(404, "Tool run not found.")
        return folder

    def tool_result(folder: Path) -> Path:
        tool = json.loads((folder / "request.json").read_text())["tool"]
        name = {
            "reframe": "tool.mp4",
            "captions": "tool.mp4",
            "extend": "extended.mp4",
        }.get(tool, "clip-01.mp4")
        return folder / "render" / name

    def describe_tool(tool_id: str) -> dict:
        folder = tool_folder(tool_id)
        request = json.loads((folder / "request.json").read_text())
        result = tool_result(folder)
        ready = result.is_file()
        return {
            **request,
            **render_state(folder, result),
            "id": tool_id,
            "output_url": f"/api/tools/{tool_id}/output" if ready else None,
            "comfyui_url": f"/api/tools/{tool_id}/comfyui"
            if ready and (folder / "render" / "workflow.json").is_file()
            else None,
            "srt_url": f"/api/tools/{tool_id}/srt"
            if (folder / "render" / "captions.srt").is_file()
            else None,
        }

    @app.get("/api/tools")
    def list_tools():
        return [
            describe_tool(path.parent.name)
            for path in sorted(
                tool_runs.glob("*/request.json"), key=lambda p: p.stat().st_mtime
            )
        ]

    @app.post("/api/tools")
    def run_tool(body: ToolRequest):
        with lock:
            folder = tool_runs / body.request_id
            if (folder / "request.json").is_file():
                if (
                    json.loads((folder / "request.json").read_text())
                    != body.model_dump()
                ):
                    raise HTTPException(409, "This ID belongs to a different tool run.")
                return describe_tool(body.request_id)
            if body.take_id:
                take = job_path(body.take_id) / "render" / "reshoot.mp4"
                if not take.is_file():
                    raise HTTPException(400, "Choose a finished take.")
                clip = take
            else:
                clip = source_path(body.source_id)
            runs = list(tool_runs.glob("*/request.json"))
            if len(runs) >= max_tool_runs:
                raise HTTPException(429, "This session's tool limit has been reached.")
            if any(describe_tool(p.parent.name)["active"] for p in runs):
                raise HTTPException(409, "Finish the current tool run first.")
            if body.tool == "extend" and not tool_ready(body.tool):
                raise HTTPException(
                    503, "The video worker is unavailable. Nothing was submitted."
                )
            if not tool_ready(body.tool):
                folder_name, model = video_tools.MODELS[body.tool]
                raise HTTPException(
                    503,
                    "Comfy Cloud is unavailable. Nothing was submitted."
                    if tool_backend == "cloud"
                    else f"Add {model} ({folder_name}) to your ComfyUI worker, "
                    "or start Openfield with --tool-backend cloud. "
                    "Nothing was submitted.",
                )
            folder.mkdir()
            (folder / "request.json").write_text(body.model_dump_json())
            if body.tool == "extend":
                take = json.loads((job_path(body.take_id) / "request.json").read_text())
                direction = (take.get("motion_prompt") or take["prompt"]).strip()
                start(
                    folder,
                    [
                        "extend",
                        str(clip),
                        "--prompt",
                        f"Continue the same scene seamlessly: {direction}"[:4000],
                        "--seed",
                        str(take.get("seed", 42)),
                        "--format",
                        take.get("frame_format", "landscape"),
                        "--backend",
                        backend,
                        "--run-dir",
                        str(folder / "render"),
                        "--execute",
                    ],
                )
                return describe_tool(body.request_id)
            start(
                folder,
                [
                    "tool",
                    body.tool,
                    str(clip),
                    "--background",
                    body.background,
                    "--target",
                    body.target,
                    "--fit",
                    body.fit,
                    "--backend",
                    tool_backend,
                    "--run-dir",
                    str(folder / "render"),
                    "--execute",
                ],
            )
            return describe_tool(body.request_id)

    @app.get("/api/tools/{tool_id}")
    def tool_status(tool_id: str):
        return describe_tool(tool_id)

    @app.get("/api/tools/{tool_id}/{kind}")
    def tool_download(tool_id: str, kind: Literal["output", "comfyui", "srt"]):
        folder = tool_folder(tool_id)
        tool = json.loads((folder / "request.json").read_text())["tool"]
        if kind == "srt":
            subtitles = folder / "render" / "captions.srt"
            if not subtitles.is_file():
                raise HTTPException(404)
            return FileResponse(
                subtitles,
                media_type="application/x-subrip",
                filename=f"openfield-{tool_id[:8]}.srt",
            )
        if kind == "comfyui":
            if not (folder / "render" / "workflow.json").is_file():
                raise HTTPException(404)
            name = f"openfield-{tool}-{tool_id[:8]}"
            return Response(
                comfybundle.bundle(folder / "render", name),
                media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="{name}-comfyui.zip"'
                },
            )
        result = tool_result(folder)
        if not result.is_file():
            raise HTTPException(404)
        return FileResponse(result, filename=f"openfield-{tool}-{tool_id[:8]}.mp4")

    app.add_middleware(RequestLimitsMiddleware)
    if work_limiter is not None:
        app.add_middleware(
            WorkAdmissionMiddleware, limiter=work_limiter, workspace_id=directory.name
        )
    return app


def quickstart_problems() -> list[str]:
    """Everything a first Cloud run needs, checked before the studio starts."""
    problems = []
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            problems.append(
                f"{tool} is not installed (macOS: brew install ffmpeg; "
                "Ubuntu: sudo apt install ffmpeg; Windows: winget install ffmpeg)."
            )
    key = os.environ.get("COMFY_API_KEY", "").strip()
    if not key:
        problems.append(
            "COMFY_API_KEY is not set. Create a key at https://platform.comfy.org "
            "and run: COMFY_API_KEY=your-key uv run openfield --cloud"
        )
        return problems
    try:
        response = httpx.get(
            "https://cloud.comfy.org/api/user", headers={"X-API-Key": key}, timeout=15
        )
    except httpx.HTTPError as error:
        problems.append(
            f"Comfy Cloud could not be reached ({error.__class__.__name__})."
        )
        return problems
    if response.status_code in (401, 403):
        problems.append(
            "Comfy Cloud rejected COMFY_API_KEY; check you copied the whole key."
        )
    elif response.status_code != 200:
        problems.append(
            f"Comfy Cloud answered {response.status_code}; try again shortly."
        )
    elif response.json().get("status") != "active":
        problems.append(
            "This Comfy Cloud account has no active subscription; Cloud API runs need one."
        )
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8793)
    parser.add_argument("--directory", type=Path, default=Path("runs/web"))
    parser.add_argument("--backend", choices=("cloud", "self-hosted"), default="cloud")
    parser.add_argument("--max-renders", type=int, default=6)
    parser.add_argument("--max-looks", type=int, default=12)
    parser.add_argument(
        "--look-engine", choices=("moss", "klein", "klein-cloud"), default="moss"
    )
    parser.add_argument("--demo-dir", type=Path)
    parser.add_argument(
        "--tool-backend",
        choices=("cloud", "self-hosted"),
        help="Where FPS boost, background removal and upscale run (default: --backend)",
    )
    parser.add_argument(
        "--cloud",
        action="store_true",
        help="Quickstart: video, looks and tools all on Comfy Cloud, with checks",
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.cloud:
        args.backend, args.look_engine, args.tool_backend = (
            "cloud",
            "klein-cloud",
            "cloud",
        )
        problems = quickstart_problems()
        if problems:
            parser.exit(
                1,
                "Openfield can't start yet:\n"
                + "".join(f"  - {p}\n" for p in problems),
            )
    if args.max_renders < 1:
        parser.error("--max-renders must be positive")
    if args.max_looks < 1:
        parser.error("--max-looks must be positive")
    try:
        with sdk_client(args.backend):
            pass
    except (ComfyError, ValueError) as error:
        parser.error(str(error))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Openfield is starting at {url}", flush=True)
    if args.cloud and not args.no_browser:
        threading.Timer(2.0, webbrowser.open, (url,)).start()
    uvicorn.run(
        create_app(
            args.directory,
            args.backend,
            args.max_renders,
            args.demo_dir,
            args.max_looks,
            args.look_engine,
            tool_backend=args.tool_backend,
        ),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
