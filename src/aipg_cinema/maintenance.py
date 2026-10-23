"""Offline maintenance for managed stores; not a public project-import API."""

import argparse
import json
import os
import re
import sqlite3
import stat
from contextlib import ExitStack, closing, contextmanager
from dataclasses import asdict
from pathlib import Path

from .core_accounts import account_uuid
from .project import atomic_json
from .resources import WorkLimits
from .sessions import AccountSessions
from .store_activity import StoreBusy, file_lease, private_root, store_activity
from .transfer_limits import EXPORT_PEAK_BYTES, IMPORT_PEAK_BYTES, MAX_MANIFEST_BYTES

SCHEMA = {
    "login_flows": {
        "key",
        "csrf_hash",
        "subject",
        "expires",
        "stage",
        "address",
        "message",
        "challenge_expires",
    },
    "sessions": {
        "key",
        "csrf",
        "subject",
        "account",
        "aliases",
        "token",
        "token_expires",
        "expires",
        "last_seen",
    },
    "workspaces": {"id"},
    "account_workspaces": {"account", "workspace"},
}


def _policy(root: Path, previous: Path):
    path = root / ".workspaces-resources/policy.json"
    private_root(path.parent)
    AccountSessions._private_file(path, directory=False)
    if path.stat().st_size > 8192:
        raise ValueError("Unsupported resource policy.")
    data = json.loads(path.read_text())
    try:
        limits = WorkLimits(**data["limits"])
        if data != {
            "workspaces": str(previous / "workspaces"),
            "limits": asdict(limits),
            "transfer_peak_bytes": {
                "import": IMPORT_PEAK_BYTES,
                "package": EXPORT_PEAK_BYTES,
            },
        }:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("Unsupported or mismatched resource policy.") from None
    return data, limits


def _tree(root: Path, maximum: int):
    pending, count = [root], 0
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                count += 1
                if count > maximum:
                    raise ValueError(
                        "Store inspection exceeds the bounded entry limit."
                    )
                info = entry.stat(follow_symlinks=False)
                if info.st_uid != os.getuid() or info.st_mode & 0o022:
                    raise ValueError("Store data has unsafe ownership or permissions.")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif not entry.is_file(follow_symlinks=False) or info.st_nlink != 1:
                    raise ValueError(
                        "Store data must not contain links or special files."
                    )


def _database(root: Path, *, readonly: bool):
    path = root / "auth/sessions.sqlite3"
    private_root(path.parent)
    AccountSessions._private_file(path, directory=False)
    return sqlite3.connect(
        path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True, timeout=10
    )


def _validate(root: Path, previous: Path):
    policy, limits = _policy(root, previous)
    private_root(root / "workspaces")
    _tree(root / "workspaces", limits.scan_entries)
    _tree(root / "auth", limits.scan_entries)
    with closing(_database(root, readonly=True)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        if (
            db.execute("PRAGMA user_version").fetchone()[0] != 2
            or db.execute("PRAGMA quick_check").fetchall() != [("ok",)]
            or db.execute("PRAGMA foreign_key_check").fetchall()
            or db.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('trigger', 'view')"
            ).fetchone()
            or {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            != {"sessions", "login_flows", "workspaces", "account_workspaces"}
        ):
            raise ValueError("Unsupported or damaged account store.")
        if any(
            {row[1] for row in db.execute(f"PRAGMA table_info({name})")} != columns
            for name, columns in SCHEMA.items()
        ):
            raise ValueError("Unsupported account database schema.")
        workspaces = set()
        for number, (identity,) in enumerate(db.execute("SELECT id FROM workspaces")):
            if (
                number >= limits.scan_entries
                or not isinstance(identity, str)
                or not re.fullmatch(r"[0-9a-f]{32}", identity)
            ):
                raise ValueError("Unsupported workspace ownership records.")
            workspaces.add(identity)
        for number, (account, workspace) in enumerate(
            db.execute("SELECT account, workspace FROM account_workspaces")
        ):
            if number >= limits.scan_entries or workspace not in workspaces:
                raise ValueError("Unsupported workspace ownership records.")
            account_uuid(account)
        if any(path.name not in workspaces for path in (root / "workspaces").iterdir()):
            raise ValueError("Store contains an unregistered workspace.")
    return policy


def _pending_export(export: Path) -> bool:
    path = export / "state.json"
    if path.is_symlink():
        raise ValueError("Unsupported export metadata.")
    if not path.exists():
        return True
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size > MAX_MANIFEST_BYTES
    ):
        raise ValueError("Unsupported export metadata.")
    data = json.loads(path.read_text())
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("status"), str)
        or data.get("status")
        not in {
            "queued",
            "running",
            "succeeded",
            "failed",
        }
    ):
        raise ValueError("Unsupported export state.")
    return data["status"] not in {"succeeded", "failed"}


@contextmanager
def maintenance(root: Path):
    """Fence managed servers, current children and known legacy export observers."""
    root = private_root(root)
    with ExitStack() as stack:
        descriptors = [stack.enter_context(store_activity(root, shared=False))]
        descriptors.append(
            stack.enter_context(file_lease(root / ".staging-server.lock"))
        )
        workspaces = private_root(root / "workspaces")
        inspected = 0
        for workspace in workspaces.iterdir():
            inspected += 1
            if inspected > 1000000:
                raise ValueError("Store inspection exceeds the bounded entry limit.")
            if (
                not re.fullmatch(r"[0-9a-f]{32}", workspace.name)
                or workspace.is_symlink()
                or not workspace.is_dir()
            ):
                raise ValueError("Unsupported workspace directory.")
            exports = workspace / "exports"
            if exports.exists():
                if exports.is_symlink() or not exports.is_dir():
                    raise ValueError("Unsupported export directory.")
                for export in exports.iterdir():
                    inspected += 1
                    if inspected > 1000000:
                        raise ValueError(
                            "Store inspection exceeds the bounded entry limit."
                        )
                    if export.is_symlink() or not export.is_dir():
                        raise ValueError("Unsupported export directory.")
                    with ExitStack() as probe:
                        fd = probe.enter_context(
                            file_lease(export / ".observer.lock", private=False)
                        )
                        if _pending_export(export):
                            stack.enter_context(probe.pop_all())
                            descriptors.append(fd)
        yield descriptors


def prepare_restore(root: Path, previous: Path):
    """Prepare only a relocated, verified offline copy; never restore in place."""
    root = private_root(root)
    if (
        root != root.resolve()
        or not previous.is_absolute()
        or previous != previous.resolve()
        or root == previous
        or root.is_relative_to(previous)
        or previous.is_relative_to(root)
    ):
        raise ValueError("Restore to a separate canonical directory, never in place.")
    with maintenance(root):
        policy = _validate(root, previous)
        with closing(_database(root, readonly=False)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM login_flows")
            db.commit()
        # This is the last change: until credentials are cleared, the relocated
        # policy still fails the launcher's workspace-path consistency check.
        atomic_json(
            root / ".workspaces-resources/policy.json",
            {**policy, "workspaces": str(root / "workspaces")},
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    hold = modes.add_parser(
        "hold", help="Run one foreground command under exclusive maintenance."
    )
    hold.add_argument("--state-dir", type=Path, required=True)
    hold.add_argument("command", nargs=argparse.REMAINDER)
    restore = modes.add_parser(
        "prepare-restore", help="Prepare an already verified relocated restore."
    )
    restore.add_argument("--state-dir", type=Path, required=True)
    restore.add_argument("--previous-state-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "prepare-restore":
            prepare_restore(args.state_dir, args.previous_state_dir)
            print(json.dumps({"status": "prepared", "fresh_sign_in_required": True}))
            return
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            parser.error("Supply one foreground command after --.")
        with maintenance(args.state_dir) as descriptors:
            _validate(args.state_dir, args.state_dir)
            os.chdir(args.state_dir)
            for fd in descriptors:
                os.set_inheritable(fd, True)
            # No supervisor can die and release the backup fence early: the
            # foreground executable inherits the same OS-held descriptors.
            os.execvpe(command[0], command, os.environ)
    except StoreBusy:
        parser.exit(
            75, "Store is busy. No maintenance command ran. Stop writers and retry.\n"
        )
    except (ValueError, OSError, sqlite3.Error):
        parser.exit(
            1,
            "Store maintenance rejected. Check the offline layout, permissions, ownership records and resource policy. No service was started.\n",
        )


if __name__ == "__main__":
    main()
