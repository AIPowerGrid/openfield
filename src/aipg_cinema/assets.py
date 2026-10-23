"""Resolve workspace assets, including atomically published portable projects."""

import re
from pathlib import Path

KINDS = frozenset({"sources", "jobs", "looks", "audio"})


def asset_directories(root: Path) -> list[Path]:
    if root.name not in KINDS:
        return [root]
    projects = root.parent / "projects"
    if not projects.is_dir():
        return [root]
    return [root] + [
        folder / "assets" / root.name
        for folder in projects.iterdir()
        if re.fullmatch(r"[0-9a-f]{32}", folder.name)
        and not folder.is_symlink()
        and (folder / "project.json").is_file()
        and (folder / "assets" / root.name).is_dir()
    ]


def asset_folder(root: Path, identity: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", identity):
        raise ValueError("Invalid studio asset ID.")
    candidates = [folder / identity for folder in asset_directories(root)]
    found = [path for path in candidates if path.exists()]
    if len(found) > 1:
        raise ValueError("The studio asset ID is ambiguous.")
    path = found[0] if found else root / identity
    if path.is_symlink() or not path.resolve().is_relative_to(root.parent.resolve()):
        raise ValueError("The studio asset is outside its workspace.")
    return path


def asset_records(root: Path, filename: str = "request.json") -> list[Path]:
    records = [
        record
        for folder in asset_directories(root)
        for record in folder.glob("*/" + filename)
        if re.fullmatch(r"[0-9a-f]{32}", record.parent.name)
    ]
    identities = [record.parent.name for record in records]
    if len(identities) != len(set(identities)):
        raise ValueError("The studio asset ID is ambiguous.")
    return records
