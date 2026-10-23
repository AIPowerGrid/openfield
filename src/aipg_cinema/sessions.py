"""Server-only Core login and durable sessions; not a public HTTP boundary.

The hosted adapter must supply same-origin/CSRF checks, Secure HttpOnly cookies,
rate limits and account-scoped asset routing before exposing these operations.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path

from .core_accounts import (
    CoreAccountError,
    CoreAccounts,
    Ownership,
    TokenGrant,
    account_uuid,
)

LOGIN_SECONDS = 600
SESSION_SECONDS = 8 * 3600
IDLE_SECONDS = 1800
REFRESH_MARGIN = 30
MAX_PENDING_LOGINS = 4096


class SessionError(Exception):
    def __init__(self):
        super().__init__("Sign in again to continue.")


class WorkspaceConflict(Exception):
    def __init__(self):
        super().__init__(
            "Your linked accounts have separate workspaces. Contact support to merge them without losing projects."
        )


class LoginCapacity(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = max(1, min(LOGIN_SECONDS, retry_after))
        super().__init__("Sign-in is busy. Try again shortly.")


def _digest(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise SessionError()
    return hashlib.sha256(value.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class LoginFlow:
    handle: str = field(repr=False)
    csrf: str = field(repr=False)
    seconds: int = field(default=LOGIN_SECONDS, repr=False, compare=False)

    def cookie(self) -> str:
        return f"v1.{self.handle}.{self.csrf}"

    @classmethod
    def from_cookie(cls, value: str):
        if not isinstance(value, str) or not re.fullmatch(
            r"v1\.[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]{43}", value
        ):
            return None
        _, handle, csrf = value.split(".")
        return cls(handle, csrf)


@dataclass(frozen=True)
class Session:
    handle: str = field(repr=False)
    csrf: str = field(repr=False)
    grant: TokenGrant = field(repr=False)
    ownership: Ownership
    workspace_id: str
    expires_at: float
    token_expires_at: float

    def browser_state(self) -> dict:
        """Explicit projection; never serialize the server session or its grant."""
        return {
            "authenticated": True,
            "account_id": self.ownership.account_id,
            "workspace_id": self.workspace_id,
            "csrf": self.csrf,
            "expires_at": self.expires_at,
        }


class AccountSessions:
    def __init__(
        self,
        directory: Path,
        core: CoreAccounts,
        *,
        origin: str,
        clock: Callable[[], float] = time.time,
    ):
        self._core = core
        self._origin = origin
        self._clock = clock
        directory = directory.absolute()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._private_file(directory, directory=True)
        self._path = directory / "sessions.sqlite3"
        flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(self._path, flags, 0o600)
        try:
            self._private_stat(os.fstat(fd), directory=False)
        finally:
            os.close(fd)
        with self._database() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1, 2):
                raise ValueError("Unsupported account session database version.")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS login_flows (
                    key TEXT PRIMARY KEY, csrf_hash TEXT NOT NULL,
                    subject TEXT NOT NULL UNIQUE, expires REAL NOT NULL,
                    stage TEXT NOT NULL, address TEXT, message TEXT,
                    challenge_expires REAL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    key TEXT PRIMARY KEY, csrf TEXT NOT NULL,
                    subject TEXT NOT NULL, account TEXT NOT NULL,
                    aliases TEXT NOT NULL, token TEXT NOT NULL,
                    token_expires REAL NOT NULL, expires REAL NOT NULL,
                    last_seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS account_workspaces (
                    account TEXT PRIMARY KEY,
                    workspace TEXT NOT NULL REFERENCES workspaces(id)
                );
                PRAGMA user_version=2;
            """)

    @property
    def origin(self) -> str:
        return self._origin

    @staticmethod
    def _private_stat(info, *, directory):
        correct_type = (
            stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        )
        if (
            not correct_type
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or (not directory and info.st_nlink != 1)
        ):
            raise ValueError(
                "Account sessions need a private, owner-only directory and database."
            )

    @classmethod
    def _private_file(cls, path, *, directory):
        cls._private_stat(path.lstat(), directory=directory)

    @contextmanager
    def _database(self):
        self._private_file(self._path.parent, directory=True)
        self._private_file(self._path, directory=False)
        db = sqlite3.connect(self._path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def begin(self, existing: LoginFlow | None = None) -> LoginFlow:
        flow, retry_after = None, LOGIN_SECONDS
        with self._database() as db:
            now = self._clock()
            if existing is not None:
                try:
                    row = self._flow(db, existing, "fresh")
                except SessionError:
                    try:
                        handle, csrf = _digest(existing.handle), _digest(existing.csrf)
                    except SessionError:
                        pass
                    else:
                        db.execute(
                            "DELETE FROM login_flows WHERE key = ? AND csrf_hash = ?",
                            (handle, csrf),
                        )
                else:
                    return LoginFlow(
                        existing.handle,
                        existing.csrf,
                        min(LOGIN_SECONDS, max(1, ceil(row["expires"] - now))),
                    )
            db.execute("DELETE FROM login_flows WHERE expires <= ?", (now,))
            db.execute(
                "DELETE FROM sessions WHERE expires <= ? OR last_seen <= ?",
                (now, now - IDLE_SECONDS),
            )
            count, oldest = db.execute(
                "SELECT count(*), min(expires) FROM login_flows"
            ).fetchone()
            if count < MAX_PENDING_LOGINS:
                flow = LoginFlow(secrets.token_urlsafe(32), secrets.token_urlsafe(32))
                db.execute(
                    "INSERT INTO login_flows (key, csrf_hash, subject, expires, stage) VALUES (?, ?, ?, ?, 'fresh')",
                    (
                        _digest(flow.handle),
                        _digest(flow.csrf),
                        "studio:" + secrets.token_hex(16),
                        now + LOGIN_SECONDS,
                    ),
                )
            else:
                retry_after = ceil(oldest - now)
        if flow is None:
            raise LoginCapacity(retry_after)
        return flow

    def _flow(self, db, flow: LoginFlow, stage: str):
        row = db.execute(
            "SELECT * FROM login_flows WHERE key = ?", (_digest(flow.handle),)
        ).fetchone()
        if (
            row is None
            or row["expires"] <= self._clock()
            or row["stage"] != stage
            or not hmac.compare_digest(row["csrf_hash"], _digest(flow.csrf))
        ):
            raise SessionError()
        return row

    def _consume(self, flow: LoginFlow, stage: str):
        with self._database() as db:
            row = self._flow(db, flow, stage)
            if stage == "challenge" and row["challenge_expires"] <= self._clock():
                raise SessionError()
            db.execute("DELETE FROM login_flows WHERE key = ?", (_digest(flow.handle),))
            return dict(row)

    def google(self, flow: LoginFlow, id_token: str) -> Session:
        # A proof consumes its flow before network I/O; replay never rebinds it.
        row = self._consume(flow, "fresh")
        requested_at = self._clock()
        grant = self._core.google(id_token, row["subject"])
        return self._create(grant, row, requested_at)

    def wallet_challenge(self, flow: LoginFlow, address: str) -> dict:
        with self._database() as db:
            row = self._flow(db, flow, "fresh")
            app_subject = row["subject"]
            db.execute(
                "UPDATE login_flows SET stage = 'challenging' WHERE key = ?",
                (_digest(flow.handle),),
            )
        try:
            requested_at = self._clock()
            challenge = self._core.wallet_challenge(address, app_subject, self._origin)
            with self._database() as db:
                row = self._flow(db, flow, "challenging")
                db.execute(
                    "UPDATE login_flows SET stage = 'challenge', address = ?, message = ?, challenge_expires = ? WHERE key = ?",
                    (
                        address,
                        challenge["message"],
                        min(row["expires"], requested_at + challenge["expires_in"]),
                        _digest(flow.handle),
                    ),
                )
            return challenge
        except Exception:
            with self._database() as db:
                db.execute(
                    "DELETE FROM login_flows WHERE key = ?", (_digest(flow.handle),)
                )
            raise

    def wallet(self, flow: LoginFlow, signature: str) -> Session:
        row = self._consume(flow, "challenge")
        requested_at = self._clock()
        grant = self._core.wallet(
            row["address"], row["message"], signature, row["subject"]
        )
        return self._create(grant, row, requested_at)

    def _create(self, grant: TokenGrant, flow: dict, requested_at: float) -> Session:
        ownership = self._core.ownership(grant)
        handle, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = self._clock()
        token_expires = requested_at + grant.expires_in
        if now >= flow["expires"] or now >= token_expires:
            raise SessionError()
        with self._database() as db:
            workspace_id = self._workspace(db, ownership)
            db.execute(
                "INSERT INTO sessions (key, csrf, subject, account, aliases, token, token_expires, expires, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _digest(handle),
                    csrf,
                    flow["subject"],
                    grant.account_id,
                    json.dumps(ownership.aliases),
                    grant.access_token,
                    token_expires,
                    now + SESSION_SECONDS,
                    now,
                ),
            )
        return Session(
            handle,
            csrf,
            grant,
            ownership,
            workspace_id,
            now + SESSION_SECONDS,
            token_expires,
        )

    @staticmethod
    def _workspace(db, ownership: Ownership) -> str:
        identities = tuple(account_uuid(value) for value in ownership.all_accounts)
        if not 1 <= len(identities) <= 128 or len(set(identities)) != len(identities):
            raise CoreAccountError(502)
        placeholders = ",".join("?" for _ in identities)
        existing = {
            row[0]
            for row in db.execute(
                f"SELECT workspace FROM account_workspaces WHERE account IN ({placeholders})",
                identities,
            )
        }
        if len(existing) > 1:
            raise WorkspaceConflict()
        workspace_id = next(iter(existing)) if existing else secrets.token_hex(16)
        db.execute("INSERT OR IGNORE INTO workspaces (id) VALUES (?)", (workspace_id,))
        for account in identities:
            db.execute(
                "INSERT OR IGNORE INTO account_workspaces (account, workspace) VALUES (?, ?)",
                (account, workspace_id),
            )
        return workspace_id

    def _session(self, db, handle: str, csrf: str | None = None, *, live=True):
        row = db.execute(
            "SELECT * FROM sessions WHERE key = ?", (_digest(handle),)
        ).fetchone()
        now = self._clock()
        if row is None or (
            live and (row["expires"] <= now or row["last_seen"] + IDLE_SECONDS <= now)
        ):
            raise SessionError()
        if csrf is not None and not hmac.compare_digest(
            _digest(csrf), _digest(row["csrf"])
        ):
            raise SessionError()
        return row

    def resolve(self, handle: str, *, csrf: str | None = None) -> Session:
        """Resolve a server session. Mutating HTTP routes must pass the CSRF token."""
        with self._database() as db:
            row = self._session(db, handle, csrf)
            db.execute(
                "UPDATE sessions SET last_seen = ? WHERE key = ?",
                (self._clock(), _digest(handle)),
            )
            current = dict(row)
        if current["token_expires"] <= self._clock() + REFRESH_MARGIN:
            requested_at = self._clock()
            grant = self._core.refresh(current["subject"])
            ownership = self._core.ownership(grant)
            if current["account"] not in ownership.all_accounts:
                raise CoreAccountError(502)
            token_expires = requested_at + grant.expires_in
            if token_expires <= self._clock():
                raise CoreAccountError(503)
            with self._database() as db:
                row = self._session(db, handle, csrf)
                # A concurrent refresh may win; logout must never be resurrected.
                if (
                    row["token_expires"] == current["token_expires"]
                    and row["token"] == current["token"]
                ):
                    db.execute(
                        "UPDATE sessions SET account = ?, aliases = ?, token = ?, token_expires = ? WHERE key = ?",
                        (
                            grant.account_id,
                            json.dumps(ownership.aliases),
                            grant.access_token,
                            token_expires,
                            _digest(handle),
                        ),
                    )
                current = dict(self._session(db, handle, csrf))
        if current["token_expires"] <= self._clock():
            raise SessionError()
        ownership = Ownership(current["account"], tuple(json.loads(current["aliases"])))
        with self._database() as db:
            self._session(db, handle, csrf)
            workspace_id = self._workspace(db, ownership)
        return Session(
            handle,
            current["csrf"],
            TokenGrant(
                current["account"],
                current["token"],
                max(0, int(current["token_expires"] - self._clock())),
            ),
            ownership,
            workspace_id,
            current["expires"],
            current["token_expires"],
        )

    def logout(self, handle: str, csrf: str) -> None:
        with self._database() as db:
            self._session(db, handle, csrf, live=False)
            db.execute("DELETE FROM sessions WHERE key = ?", (_digest(handle),))
