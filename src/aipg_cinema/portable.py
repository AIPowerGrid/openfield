"""Bounded, data-only project packages; importing never executes a workflow."""

import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from filelock import FileLock
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from .assets import asset_folder, asset_records
from .contracts import ID, LookRequest, TakeRequest
from .generation import AUDIO_FORMATS, audio_info
from .generation import graph as generation_graph
from .look import graph as moss_graph
from .look import klein_graph
from .project import Project, atomic_json
from .reshoot import graph as video_graph
from .reshoot import probe, video_format
from .sequence import inspect
from .speech import graph as speech_graph
from .transfer_limits import MAX_ARCHIVE_BYTES as MAX_ARCHIVE
from .transfer_limits import MAX_MANIFEST_BYTES as MAX_MANIFEST
from .transfer_limits import MAX_MEDIA_BYTES as MAX_BYTES
from .transfer_limits import MAX_REBUILT_METADATA_BYTES as MAX_REBUILT_METADATA

MAX_FILES = 512
AssetID = Annotated[str, Field(pattern=ID)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImageRecord(Record):
    frame_format: Literal["landscape", "portrait", "square"]
    request: LookRequest | None = None
    engine: Literal["moss", "klein", "klein-cloud"] = "moss"
    negative_skip_layers: list[Annotated[int, Field(ge=0, le=255, strict=True)]] = (
        Field(default_factory=list, max_length=32)
    )


class AudioRecord(Record):
    suffix: str = Field(max_length=8)
    name: str = Field(default="Imported audio", max_length=255)


class Commitment(Record):
    size: int = Field(gt=0, le=MAX_BYTES, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Package(Record):
    format: Literal["aipg.studio-project"] = "aipg.studio-project"
    version: Literal[1] = 1
    project: Project
    takes: dict[AssetID, TakeRequest] = Field(default_factory=dict, max_length=32)
    images: dict[AssetID, ImageRecord] = Field(default_factory=dict, max_length=64)
    sources: dict[AssetID, str] = Field(default_factory=dict, max_length=32)
    audio: dict[AssetID, AudioRecord] = Field(default_factory=dict, max_length=32)
    files: dict[str, Commitment] = Field(default_factory=dict, max_length=MAX_FILES)


def read_json(path: Path):
    if path.stat().st_size > MAX_MANIFEST:
        raise ValueError("Project metadata exceeds the package limit.")
    return json.loads(path.read_text(), object_pairs_hook=_unique)


def _unique(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate project metadata key.")
        result[key] = value
    return result


def _hash(path: Path) -> Commitment:
    with path.open("rb") as stream:
        return Commitment(
            size=path.stat().st_size,
            sha256=hashlib.file_digest(stream, "sha256").hexdigest(),
        )


@lru_cache(maxsize=1)
def _workflow_fields() -> dict[str, set[str]]:
    examples = [
        video_graph("ltx25", "A paper boat", look_frame=True, closing_frame=True),
        speech_graph("A paper boat", opening=True, closing=True, source_video=True),
        moss_graph("A paper boat"),
        moss_graph("A paper boat", from_image=False),
        klein_graph("A paper boat"),
        klein_graph("A paper boat", from_image=False),
    ] + [
        generation_graph("A paper boat", mode=mode, opening=True, closing=True)
        for mode in ("text", "image", "audio")
    ]
    fields = {}
    for workflow in examples:
        for node in workflow.values():
            fields.setdefault(node["class_type"], set()).update(node["inputs"])
    return fields


def validate_workflow(path: Path, available: set[str]) -> None:
    workflow = read_json(path)
    if not isinstance(workflow, dict) or not 0 < len(workflow) <= 128:
        raise ValueError("Unsupported saved workflow.")
    fields = _workflow_fields()
    for name, node in workflow.items():
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name)
            or not isinstance(node, dict)
            or set(node) != {"class_type", "inputs"}
        ):
            raise ValueError("Unsupported saved workflow node.")
        kind, inputs = node["class_type"], node["inputs"]
        if (
            not isinstance(kind, str)
            or kind not in fields
            or not isinstance(inputs, dict)
            or not set(inputs) <= fields[kind]
        ):
            raise ValueError(
                "The saved workflow contains unsupported or private fields."
            )
        for key, value in inputs.items():
            if isinstance(value, list):
                if (
                    len(value) != 2
                    or not isinstance(value[0], str)
                    or value[0] not in workflow
                    or type(value[1]) is not int
                    or not 0 <= value[1] <= 16
                ):
                    raise ValueError("Unsupported saved workflow link.")
            elif isinstance(value, str):
                if len(value) > 16000 or (
                    key != "text"
                    and (
                        "://" in value
                        or value.startswith(("/", "\\", "~"))
                        or ".." in value.split("/")
                    )
                ):
                    raise ValueError("Saved workflow paths must be portable and local.")
            elif type(value) in (int, bool):
                if abs(value) > 2**64:
                    raise ValueError("Unsupported saved workflow integer.")
            elif not isinstance(value, float) or not math.isfinite(value):
                raise ValueError("Unsupported saved workflow value.")
        slot = {"LoadImage": "image", "LoadVideo": "file", "LoadAudio": "audio"}.get(
            kind
        )
        if slot and (
            not isinstance(inputs.get(slot), str) or inputs[slot] not in available
        ):
            raise ValueError("The saved workflow is missing a required local input.")
        roles = {
            "LoadImage": {"source.png", "look.png", "closing.png"},
            "LoadVideo": {"source.mp4"},
            "LoadAudio": {"source.wav"},
        }
        if slot and inputs[slot] not in roles[kind]:
            raise ValueError("A saved workflow input has the wrong media role.")


def _negative_layers(path: Path) -> list[int]:
    result = set()
    for node in read_json(path).values():
        if node["class_type"] == "SkipLayerGuidanceDiTSimple":
            layers = node["inputs"].get("single_layers", "")
            if not isinstance(layers, str):
                raise ValueError("Unsupported saved layer guidance.")
            for value in layers.split(","):
                if value.strip():
                    if not value.strip().isdigit() or not 0 <= int(value) <= 255:
                        raise ValueError("Unsupported saved layer guidance.")
                    result.add(int(value))
    return sorted(result)


def _closure(package: Package) -> dict[str, set[str]]:
    needed = {kind: set() for kind in ("sources", "jobs", "looks", "audio")}

    def take_refs(draft):
        for kind, value in (
            ("sources", draft.source_id),
            ("audio", draft.audio_id),
            ("looks", draft.look_id),
            ("looks", draft.closing_id),
        ):
            if value:
                needed[kind].add(value)

    for shot in package.project.shots:
        take_refs(shot.draft)
        if shot.selected_take_id:
            needed["jobs"].add(shot.selected_take_id)
        if shot.audition:
            needed["looks"].update(
                value
                for value in (
                    shot.audition.reference_id,
                    shot.audition.left_id,
                    shot.audition.right_id,
                )
                if value
            )
    for layer in (package.project.music, package.project.voiceover):
        if layer:
            needed["audio"].add(layer.audio_id)
    for identity, take in package.takes.items():
        if (
            take.request_id != identity
            or take.frame_format != package.project.frame_format
        ):
            raise ValueError("A portable take differs from its identity or framing.")
        if identity not in needed["jobs"] and not (
            take.project_id == package.project.id
            and any(shot.id == take.shot_id for shot in package.project.shots)
        ):
            raise ValueError("The package contains an unrelated take.")
        take_refs(take)
        needed["jobs"].add(identity)
    if not needed["jobs"] <= package.takes.keys():
        raise ValueError("A selected take is missing from the package.")
    pending = list(needed["looks"])
    seen = set()
    while pending:
        identity = pending.pop()
        if identity in seen:
            continue
        seen.add(identity)
        image = package.images.get(identity)
        if image is None:
            raise ValueError("A referenced image is missing from the package.")
        request = image.request
        if request:
            if (
                request.request_id != identity
                or request.frame_format != image.frame_format
            ):
                raise ValueError("A portable look differs from its saved settings.")
            if request.source_id:
                needed["sources"].add(request.source_id)
            if request.image_id:
                needed["looks"].add(request.image_id)
                pending.append(request.image_id)
    if (
        needed["sources"] != package.sources.keys()
        or needed["looks"] != package.images.keys()
        or needed["audio"] != package.audio.keys()
    ):
        raise ValueError("The package has missing or unrelated source assets.")
    return needed


def _allowed_files(package: Package) -> tuple[set[str], set[str]]:
    required, allowed = set(), set()
    for identity in package.sources:
        required.add(f"sources/{identity}/source.mp4")
    for identity, audio in package.audio.items():
        if audio.suffix not in AUDIO_FORMATS or Path(audio.name).name != audio.name:
            raise ValueError("Unsupported portable audio metadata.")
        required.add(f"audio/{identity}/original{audio.suffix}")
    for identity, image in package.images.items():
        required.add(f"looks/{identity}/look.png")
        if image.request:
            required.add(f"looks/{identity}/workflow.json")
            allowed.add(f"looks/{identity}/source.png")
    for identity, take in package.takes.items():
        required.update(
            {f"jobs/{identity}/reshoot.mp4", f"jobs/{identity}/workflow.json"}
        )
        if take.mode == "video":
            required.add(f"jobs/{identity}/source.mp4")
        if take.mode == "audio" or take.render_profile == "single-pass-audio":
            required.add(f"jobs/{identity}/source.wav")
        for key, filename in (
            (take.look_id, "look.png"),
            (take.closing_id, "closing.png"),
        ):
            if key:
                required.add(f"jobs/{identity}/{filename}")
    return required, required | allowed


def validate_package(package: Package, root: Path) -> None:
    _closure(package)
    if any(
        len(name) > 255 or Path(name).name != name for name in package.sources.values()
    ):
        raise ValueError("Unsupported portable source name.")
    required, allowed = _allowed_files(package)
    if (
        not required <= package.files.keys()
        or not package.files.keys() <= allowed
        or sum(item.size for item in package.files.values()) > MAX_BYTES
    ):
        raise ValueError("The project package has missing, extra or oversized media.")
    for name, commitment in package.files.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or _hash(path) != commitment:
            raise ValueError("A project asset is missing or its checksum differs.")
        if path.suffix == ".json":
            validate_workflow(path, {p.name for p in path.parent.iterdir()})
        elif path.suffix == ".png":
            if path.stat().st_size > 12 * 1024 * 1024:
                raise ValueError("A portable image exceeds 12 MB.")
            with Image.open(path) as image:
                if (
                    image.format != "PNG"
                    or image.width * image.height > 16777216
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise ValueError("Unsupported portable image.")
                image.verify()
        elif name.startswith("jobs/") and path.name == "source.wav":
            audio_info(path)
        elif name.startswith("jobs/") and path.name == "source.mp4":
            probe(path)
    for identity, take in package.takes.items():
        inspect(
            root / "jobs" / identity / "reshoot.mp4",
            *video_format(take.frame_format).output_size,
            120,
        )
    for identity in package.sources:
        path = root / "sources" / identity / "source.mp4"
        if path.stat().st_size > 100 * 1024 * 1024:
            raise ValueError("A portable source exceeds 100 MB.")
        info = probe(path)
        if (
            not any(s["codec_type"] == "video" for s in info["streams"])
            or not math.isfinite(float(info["format"]["duration"]))
            or float(info["format"]["duration"]) < 5
        ):
            raise ValueError(
                "A portable source must contain at least five seconds of video."
            )
    for identity, audio in package.audio.items():
        audio_info(
            root / "audio" / identity / ("original" + audio.suffix), min_duration=0.1
        )
    for identity, image in package.images.items():
        with Image.open(root / "looks" / identity / "look.png") as picture:
            expected = video_format(image.frame_format).output_size
            if picture.size != expected:
                raise ValueError("A reference image differs from its saved framing.")
        if image.request and image.negative_skip_layers != _negative_layers(
            root / "looks" / identity / "workflow.json"
        ):
            raise ValueError("Look guidance differs from its frozen workflow.")
    for draft in [shot.draft for shot in package.project.shots] + list(
        package.takes.values()
    ):
        for identity, frame in (
            (draft.look_id, 0),
            (draft.closing_id, 0 if draft.closing_id == draft.look_id else 120),
        ):
            if not identity:
                continue
            image = package.images[identity]
            if image.frame_format != draft.frame_format or (
                image.request
                and draft.source_id
                and (
                    image.request.source_id != draft.source_id
                    or image.request.source_start != draft.source_start
                    or image.request.frame_index != frame
                )
            ):
                raise ValueError(
                    "A reference belongs to different framing or source range."
                )


class BoundedArchive(io.BufferedWriter):
    def __init__(self, raw, maximum: int):
        super().__init__(raw)
        self.maximum = maximum

    def write(self, value):
        if self.tell() + len(value) > self.maximum:
            raise ValueError("The project package exceeds its archive limit.")
        return super().write(value)


def export_project(workspace: Path, project: Project, destination: Path) -> Path:
    workspace = workspace.resolve()
    package = Package(project=Project.model_validate(project.model_dump()))
    for path in asset_records(workspace / "jobs"):
        take = TakeRequest.model_validate(read_json(path))
        if (
            (
                take.project_id == project.id
                and any(s.id == take.shot_id for s in project.shots)
            )
            or any(s.selected_take_id == take.request_id for s in project.shots)
        ) and (path.parent / "render" / "reshoot.mp4").is_file():
            package.takes[take.request_id] = take
    if len(package.takes) > 32:
        raise ValueError("A portable project supports up to 32 completed takes.")
    # Resolve only assets referenced by this project's drafts, auditions and takes.
    needed = {kind: set() for kind in ("sources", "looks", "audio")}
    drafts = [shot.draft for shot in project.shots] + list(package.takes.values())
    for draft in drafts:
        for kind, value in (
            ("sources", draft.source_id),
            ("audio", draft.audio_id),
            ("looks", draft.look_id),
            ("looks", draft.closing_id),
        ):
            if value:
                needed[kind].add(value)
    for shot in project.shots:
        if shot.audition:
            needed["looks"].update(
                v
                for v in (
                    shot.audition.reference_id,
                    shot.audition.left_id,
                    shot.audition.right_id,
                )
                if v
            )
    for layer in (project.music, project.voiceover):
        if layer:
            needed["audio"].add(layer.audio_id)
    pending = list(needed["looks"])
    while pending:
        identity = pending.pop()
        if identity in package.images:
            continue
        folder = asset_folder(workspace / "looks", identity)
        if (folder / "request.json").is_file():
            data = read_json(folder / "request.json")
            request = LookRequest.model_validate(data)
            package.images[identity] = ImageRecord(
                frame_format=request.frame_format,
                request=request,
                engine=data.get("engine", "moss"),
            )
            if request.source_id:
                needed["sources"].add(request.source_id)
            if request.image_id:
                needed["looks"].add(request.image_id)
                pending.append(request.image_id)
        else:
            data = read_json(folder / "upload.json")
            package.images[identity] = ImageRecord(
                frame_format=data.get("frame_format", "landscape")
            )
    for identity in needed["sources"]:
        folder = asset_folder(workspace / "sources", identity)
        data = (
            read_json(folder / "source.json")
            if (folder / "source.json").is_file()
            else {}
        )
        package.sources[identity] = Path(data.get("name", "Source clip")).name[:255]
    for identity in needed["audio"]:
        data = read_json(asset_folder(workspace / "audio", identity) / "audio.json")
        package.audio[identity] = AudioRecord(
            suffix=data["suffix"], name=Path(data["name"]).name[:255]
        )
    # Copy first, then inspect/hash those frozen bytes rather than live source files.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".packaging-", dir=destination.parent
    ) as staging:
        root = Path(staging)
        required, allowed = _allowed_files(package)
        total = 0
        for name in sorted(allowed):
            kind, identity, filename = name.split("/")
            folder = asset_folder(workspace / kind, identity)
            source = folder / filename
            if kind == "jobs" or (kind == "looks" and not source.is_file()):
                source = folder / "render" / filename
            if not source.is_file() and name not in required:
                continue
            if source.is_symlink() or not source.resolve().is_relative_to(workspace):
                raise ValueError("The project asset is outside its workspace.")
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as incoming, target.open("xb") as output:
                while chunk := incoming.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError("The project package exceeds 512 MB.")
                    output.write(chunk)
            package.files[name] = _hash(target)
        for identity, image in package.images.items():
            if image.request:
                image.negative_skip_layers = _negative_layers(
                    root / "looks" / identity / "workflow.json"
                )
        package = Package.model_validate(package.model_dump())
        validate_package(package, root)
        manifest = package.model_dump_json().encode("utf-8")
        if len(manifest) > MAX_MANIFEST:
            raise ValueError("Project metadata exceeds its bound.")
        archive = root / "project.aipg.zip"
        with (
            BoundedArchive(archive.open("xb", buffering=0), MAX_ARCHIVE) as bounded,
            zipfile.ZipFile(bounded, "w", compression=zipfile.ZIP_STORED) as output,
        ):
            output.writestr("project.json", manifest)
            for name in sorted(package.files):
                output.write(root / name, "media/" + name)
        if archive.stat().st_size > MAX_ARCHIVE:
            raise ValueError("The project package exceeds its archive limit.")
        if destination.exists():
            raise ValueError(
                "Keep the existing project package; choose a new destination."
            )
        archive.replace(destination)
    return destination


class HeaderReader(io.BufferedReader):
    """Bound stdlib ZIP directory parsing before it allocates entry objects."""

    headers_only = True

    def read(self, size=-1):
        requested = size if size >= 0 else os.fstat(self.fileno()).st_size - self.tell()
        if self.headers_only and requested > 512 * 1024:
            raise ValueError("Project archive directory metadata exceeds its bound.")
        return super().read(size)


def unpack(archive: Path, root: Path) -> Package:
    if not 0 < archive.stat().st_size <= MAX_ARCHIVE:
        raise ValueError("Choose a project package no larger than 514 MB.")
    with (
        HeaderReader(archive.open("rb", buffering=0)) as reader,
        zipfile.ZipFile(reader) as source,
    ):
        reader.headers_only = False
        entries = source.infolist()
        names = [entry.filename for entry in entries]
        if (
            len(entries) > MAX_FILES + 1
            or len(set(names)) != len(names)
            or "project.json" not in names
        ):
            raise ValueError("Duplicate or excessive project archive entries.")
        if source.getinfo("project.json").file_size > MAX_MANIFEST:
            raise ValueError("Project metadata exceeds its bound.")
        for entry in entries:
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if (
                entry.is_dir()
                or kind not in (0, stat.S_IFREG)
                or entry.flag_bits & 1
                or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            ):
                raise ValueError(
                    "Project archives may contain only regular unencrypted files."
                )
        package = Package.model_validate(
            json.loads(source.read("project.json"), object_pairs_hook=_unique)
        )
        required, allowed = _allowed_files(package)
        if (
            not required <= package.files.keys()
            or not package.files.keys() <= allowed
            or set(names)
            != {"project.json"} | {"media/" + name for name in package.files}
        ):
            raise ValueError("The archive contains missing or unlisted project files.")
        total = 0
        for name, commitment in package.files.items():
            entry = source.getinfo("media/" + name)
            if entry.file_size != commitment.size:
                raise ValueError("Project asset size differs from its commitment.")
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(entry) as incoming, target.open("xb") as output:
                while chunk := incoming.read(65536):
                    total += len(chunk)
                    if (
                        total > MAX_BYTES
                        or output.tell() + len(chunk) > commitment.size
                    ):
                        raise ValueError("Project media exceeds its size bound.")
                    output.write(chunk)
        validate_package(package, root)
        return package


def _remap(package: Package, identity: str, media: Path, target: Path) -> Project:
    metadata_bytes = 0

    def write_metadata(path, value):
        nonlocal metadata_bytes
        # atomic_json emits ASCII JSON with this formatting and one newline.
        size = len(json.dumps(value, indent=2, allow_nan=False)) + 1
        if metadata_bytes + size > MAX_REBUILT_METADATA:
            raise ValueError("Imported project metadata exceeds its bound.")
        atomic_json(path, value)
        metadata_bytes += size

    project = package.project.model_copy(deep=True)
    project.id, project.revision = identity, 0
    maps = {
        kind: {old: uuid.uuid4().hex for old in values}
        for kind, values in (
            ("sources", package.sources),
            ("jobs", package.takes),
            ("looks", package.images),
            ("audio", package.audio),
        )
    }
    shots = {shot.id: uuid.uuid4().hex for shot in project.shots}

    def draft_refs(draft):
        for field, kind in (
            ("source_id", "sources"),
            ("audio_id", "audio"),
            ("look_id", "looks"),
            ("closing_id", "looks"),
        ):
            value = getattr(draft, field)
            if value:
                setattr(draft, field, maps[kind][value])

    for kind, mapping in maps.items():
        for old, new in mapping.items():
            original = media / kind / old
            folder = target / "assets" / kind / new
            folder.mkdir(parents=True)
            if kind == "jobs":
                render = folder / "render"
                shutil.copytree(original, render)
                take = package.takes[old].model_copy(deep=True)
                take.request_id = new
                draft_refs(take)
                if take.project_id == package.project.id and take.shot_id in shots:
                    take.project_id, take.shot_id, take.project_revision = (
                        identity,
                        shots[take.shot_id],
                        0,
                    )
                elif take.project_id is not None:
                    for field in (
                        "project_id",
                        "shot_id",
                        "project_revision",
                        "shared_direction",
                    ):
                        setattr(take, field, None)
                write_metadata(
                    folder / "request.json",
                    TakeRequest.model_validate(take.model_dump()).model_dump(),
                )
            elif kind == "looks":
                image = package.images[old]
                if image.request:
                    shutil.copytree(original, folder / "render")
                    request = image.request.model_copy(deep=True)
                    request.request_id = new
                    request.source_id = maps["sources"].get(request.source_id)
                    request.image_id = maps["looks"].get(request.image_id)
                    if (
                        request.project_id == package.project.id
                        and request.shot_id in shots
                    ):
                        (
                            request.project_id,
                            request.shot_id,
                            request.project_revision,
                        ) = identity, shots[request.shot_id], 0
                    elif request.project_id is not None:
                        for field in ("project_id", "shot_id", "project_revision"):
                            setattr(request, field, None)
                    write_metadata(
                        folder / "request.json",
                        {
                            **LookRequest.model_validate(
                                request.model_dump()
                            ).model_dump(),
                            "engine": image.engine,
                        },
                    )
                    write_metadata(
                        folder / "render" / "provenance.json",
                        {
                            "model": "FLUX.2 Klein 4B FP8"
                            if image.engine == "klein-cloud"
                            else "FLUX.2 Klein 4B"
                            if image.engine == "klein"
                            else "MOSS Image SFT BF16",
                            "negative_skip_layers": image.negative_skip_layers,
                            "source_frame_index": request.frame_index,
                            "imported": True,
                        },
                    )
                else:
                    shutil.copyfile(original / "look.png", folder / "look.png")
                    write_metadata(
                        folder / "upload.json", {"frame_format": image.frame_format}
                    )
            elif kind == "sources":
                shutil.copyfile(original / "source.mp4", folder / "source.mp4")
                info = probe(folder / "source.mp4")
                write_metadata(
                    folder / "source.json",
                    {
                        "name": package.sources[old],
                        "duration": float(info["format"]["duration"]),
                        "has_audio": any(
                            s["codec_type"] == "audio" for s in info["streams"]
                        ),
                    },
                )
            else:
                audio = package.audio[old]
                shutil.copyfile(
                    original / ("original" + audio.suffix),
                    folder / ("original" + audio.suffix),
                )
                info = audio_info(
                    folder / ("original" + audio.suffix), min_duration=0.1
                )
                sound = next(s for s in info["streams"] if s["codec_type"] == "audio")
                write_metadata(
                    folder / "audio.json",
                    {
                        "audio_id": new,
                        "suffix": audio.suffix,
                        "name": audio.name,
                        "duration": float(
                            sound.get("duration") or info["format"]["duration"]
                        ),
                    },
                )
    for shot in project.shots:
        old_input = [
            shot.draft.mode,
            shot.draft.source_id
            if shot.draft.mode == "video"
            else shot.draft.audio_id
            if shot.draft.mode == "audio"
            else None,
            shot.draft.source_start,
            shot.draft.frame_format,
        ]
        shot.id = shots[shot.id]
        draft_refs(shot.draft)
        shot.selected_take_id = maps["jobs"].get(shot.selected_take_id)
        if shot.audition:
            try:
                key = json.loads(shot.audition.input_key)
                matches = (
                    isinstance(key, list)
                    and len(key) == 4
                    and type(key[2]) in (int, float)
                    and key == old_input
                )
            except (ValueError, TypeError):
                matches = False
            if matches:
                active = (
                    shot.draft.source_id
                    if shot.draft.mode == "video"
                    else shot.draft.audio_id
                    if shot.draft.mode == "audio"
                    else None
                )
                shot.audition.input_key = json.dumps(
                    [
                        shot.draft.mode,
                        active,
                        shot.draft.source_start,
                        shot.draft.frame_format,
                    ],
                    separators=(",", ":"),
                )
            for field in ("reference_id", "left_id", "right_id"):
                setattr(
                    shot.audition,
                    field,
                    maps["looks"].get(getattr(shot.audition, field)),
                )
    for layer in (project.music, project.voiceover):
        if layer:
            layer.audio_id = maps["audio"][layer.audio_id]
    for caption in project.captions:
        caption.id = uuid.uuid4().hex
    project = Project.model_validate(project.model_dump())
    write_metadata(target / "project.json", project.model_dump())
    return project


def imported_project(workspace: Path, request_id: str) -> Project | None:
    if not re.fullmatch(ID, request_id):
        raise ValueError("Invalid project import ID.")
    marker = workspace / ".imports" / (request_id + ".json")
    if not marker.is_file():
        return None
    intent = read_json(marker)
    identity = intent["project_id"]
    if not re.fullmatch(ID, identity):
        raise ValueError("Invalid saved import identity.")
    target = workspace / "projects" / identity
    if not (target / "project.json").is_file():
        return None
    if read_json(target / "import.json")["sha256"] != intent["sha256"]:
        raise ValueError("The saved import commitment differs.")
    return Project.model_validate(read_json(target / "project.json"))


def _sync_directory(path: Path):
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def import_project(workspace: Path, archive: Path, request_id: str) -> Project:
    workspace = workspace.resolve()
    if not re.fullmatch(ID, request_id):
        raise ValueError("Invalid project import ID.")
    imports = workspace / ".imports"
    imports.mkdir(mode=0o700, parents=True, exist_ok=True)
    projects = workspace / "projects"
    projects.mkdir(exist_ok=True)
    with FileLock(imports / ".import.lock", timeout=0):
        if not 0 < archive.stat().st_size <= MAX_ARCHIVE:
            raise ValueError("Choose a project package no larger than 514 MB.")
        with archive.open("rb") as stream:
            archive_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        marker = imports / (request_id + ".json")
        intent = (
            read_json(marker)
            if marker.is_file()
            else {"project_id": uuid.uuid4().hex, "sha256": archive_hash}
        )
        if intent["sha256"] != archive_hash:
            raise ValueError("This import ID belongs to a different project package.")
        previous = imported_project(workspace, request_id)
        if previous:
            return previous
        with tempfile.TemporaryDirectory(prefix=".import-", dir=projects) as staging:
            root = Path(staging)
            media = root / "media"
            media.mkdir()
            package = unpack(archive, media)
            ready = root / "ready"
            ready.mkdir(mode=0o700)
            project = _remap(package, intent["project_id"], media, ready)
            atomic_json(ready / "import.json", {"version": 1, "sha256": archive_hash})
            for path in ready.rglob("*"):
                path.chmod(0o700 if path.is_dir() else 0o600)
                if path.is_file():
                    with path.open("rb") as stream:
                        os.fsync(stream.fileno())
            for path in sorted(
                (p for p in ready.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts),
                reverse=True,
            ):
                _sync_directory(path)
            _sync_directory(ready)
            # One directory rename publishes the project and every referenced asset.
            atomic_json(marker, intent)
            _sync_directory(imports)
            target = projects / project.id
            if target.exists():
                raise ValueError(
                    "Keep the existing project; do not overwrite its directory."
                )
            ready.rename(target)
            _sync_directory(projects)
            return project
