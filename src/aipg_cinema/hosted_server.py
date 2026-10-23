"""Loopback-only managed staging launcher; never enables unbilled inference."""

import argparse
import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from filelock import FileLock, Timeout

from .core_accounts import CoreAccounts, secret
from .hosted import _private_directory, create_hosted_app
from .sessions import AccountSessions
from .store_activity import store_activity


@dataclass(frozen=True)
class StagingConfig:
    directory: Path
    key_file: Path
    origin: str
    google_client_id: str
    release: str
    port: int = 8800

    def __post_init__(self):
        parsed = urlsplit(self.origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.netloc != parsed.hostname
            or self.origin != f"https://{parsed.hostname}"
            or len(parsed.hostname) > 253
            or not all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in parsed.hostname.split(".")
            )
        ):
            raise ValueError("Use one canonical HTTPS staging origin without a port.")
        if (
            not isinstance(self.google_client_id, str)
            or not 1 <= len(self.google_client_id) <= 255
            or not self.google_client_id.isascii()
            or any(ord(c) < 33 or ord(c) == 127 for c in self.google_client_id)
        ):
            raise ValueError("Configure a public Google OAuth client ID.")
        if not re.fullmatch(r"[0-9a-f]{64}", self.release):
            raise ValueError(
                "Identify the installed wheel by its SHA-256 release hash."
            )
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ValueError("Choose an unprivileged loopback port.")
        if not self.directory.is_absolute() or not self.key_file.is_absolute():
            raise ValueError("Configure absolute private state and key-file paths.")


def service_key(path: Path) -> str:
    """Read a regular owner-only credential without following a final symlink."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
            or not 1 <= info.st_size <= 32768
        ):
            raise ValueError("Use a regular, private owner-only service-key file.")
        with os.fdopen(fd, "r", encoding="ascii", closefd=False) as stream:
            value = stream.read(32769)
        if len(value) > 32768:
            raise ValueError("Use a bounded service-key file.")
        return secret(value.rstrip("\r\n"))
    finally:
        os.close(fd)


@contextmanager
def staging_app(config: StagingConfig):
    """Lease managed writers before initializing credentials or durable state."""
    if os.name != "posix":
        raise ValueError("Managed staging requires a POSIX host.")
    directory = _private_directory(config.directory)
    with store_activity(directory), _managed_app(config, directory) as app:
        yield app


@contextmanager
def _managed_app(config: StagingConfig, directory: Path):
    lease = FileLock(directory / ".staging-server.lock", mode=0o600)
    try:
        lease.acquire(timeout=0)
    except Timeout:
        raise ValueError("This staging store already has a managed writer.") from None
    try:
        core = CoreAccounts(service_key(config.key_file))
        try:
            accounts = AccountSessions(directory / "auth", core, origin=config.origin)
            app = create_hosted_app(
                accounts,
                directory / "workspaces",
                origin=config.origin,
                google_client_id=config.google_client_id,
            )
            yield app
        finally:
            core.close()
    finally:
        lease.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--service-key-file", type=Path, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--google-client-id", required=True)
    parser.add_argument("--release-sha256", required=True)
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check/init private storage without serving.",
    )
    args = parser.parse_args(argv)
    try:
        config = StagingConfig(
            args.state_dir,
            args.service_key_file,
            args.origin,
            args.google_client_id,
            args.release_sha256,
            args.port,
        )
        with staging_app(config) as app:
            print(
                json.dumps(
                    {
                        "status": "checked" if args.check else "starting",
                        "mode": "staging",
                        "release_sha256": config.release,
                        "rendering": False,
                    }
                ),
                flush=True,
            )
            if not args.check:
                uvicorn.run(
                    app,
                    host="127.0.0.1",
                    port=config.port,
                    workers=1,
                    proxy_headers=False,
                    server_header=False,
                    access_log=False,
                    limit_concurrency=64,
                    timeout_keep_alive=5,
                    timeout_graceful_shutdown=30,
                )
    except (ValueError, OSError, UnicodeError):
        parser.exit(
            1,
            "Staging startup rejected. Check the canonical origin, wheel hash, "
            "private credential/state permissions, existing writer and resource policy. "
            "No public rendering was enabled.\n",
        )


if __name__ == "__main__":
    main()
