"""Private single-POST journal for Core-backed video, not a balance ledger."""

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from filelock import FileLock
from pydantic import Field, ValidationError, model_validator

from .core_accounts import TokenGrant, VideoQuote, account_uuid
from .core_video import (
    MAX_BODY,
    CoreVideoClient,
    VideoIntent,
    VideoProtocolError,
    VideoReceipt,
    VideoRejected,
    WireModel,
)


class JournalConflict(Exception):
    def __init__(self):
        super().__init__(
            "This saved video request conflicts with existing work. Recover or review that work first."
        )


class JournalRecord(WireModel):
    version: Literal[1]
    local_id: str = Field(pattern=r"^[0-9a-f]{32}$", min_length=32, max_length=32)
    account_id: str
    request_key: str
    intent_hash: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    body_hash: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    state: Literal["prepared", "attempted", "accepted", "rejected", "cancelled"]
    rejected_status: int | None
    receipt: VideoReceipt | None

    @model_validator(mode="after")
    def valid(self):
        account_uuid(self.account_id)
        key = UUID(self.request_key)
        if str(key) != self.request_key or key.version != 4:
            raise ValueError("Invalid journal request key.")
        if (self.receipt is not None) != (self.state == "accepted") or (
            self.rejected_status is not None
        ) != (self.state == "rejected"):
            raise ValueError("Invalid journal lifecycle.")
        if self.receipt is not None and self.receipt.request_hash != self.intent_hash:
            raise ValueError("Journal receipt changed intent.")
        if self.rejected_status is not None and self.rejected_status not in (
            400,
            401,
            402,
            403,
            409,
            413,
            422,
            429,
        ):
            raise ValueError("Invalid journal rejection.")
        return self

    @property
    def active(self):
        return self.state in ("prepared", "attempted") or (
            self.state == "accepted" and not self.receipt.terminal
        )


class VideoJournal:
    def __init__(self, directory: Path):
        self.directory = directory.absolute()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._private(self.directory, directory=True)
        self.lock = FileLock(self.directory / ".journal.lock", mode=0o600)

    @staticmethod
    def _private(path, *, directory=False):
        info = path.lstat()
        correct = (
            stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        )
        if (
            not correct
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or (not directory and info.st_nlink != 1)
        ):
            raise VideoProtocolError()

    def _folder(self, local_id):
        if not isinstance(local_id, str) or not re.fullmatch(r"[0-9a-f]{32}", local_id):
            raise VideoProtocolError()
        return self.directory / local_id

    @staticmethod
    def _write(path, data):
        descriptor, temporary = tempfile.mkstemp(prefix=".saving-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _save(self, record):
        self._write(
            self._folder(record.local_id) / "record.json",
            record.model_dump_json(by_alias=True).encode(),
        )

    def _read(self, local_id):
        self._private(self.directory, directory=True)
        folder = self._folder(local_id)
        self._private(folder, directory=True)
        for name in ("record.json", "body.json"):
            self._private(folder / name)
        try:
            with (folder / "record.json").open("rb") as source:
                record_data = source.read(65537)
            if len(record_data) > 65536:
                raise VideoProtocolError()
            record = JournalRecord.model_validate_json(record_data)
            if record.local_id != local_id:
                raise VideoProtocolError()
            with (folder / "body.json").open("rb") as source:
                body = source.read(MAX_BODY + 1)
            if (
                len(body) > MAX_BODY
                or hashlib.sha256(body).hexdigest() != record.body_hash
            ):
                raise VideoProtocolError()
            intent = VideoIntent.parse(json.loads(body))
            if intent.request_hash() != record.intent_hash:
                raise VideoProtocolError()
            if record.receipt is not None:
                record.receipt.bind(
                    intent_hash=record.intent_hash,
                    model=intent.model,
                    ceiling=intent.max_cost_micro_usd,
                    seed=intent.seed,
                )
            return record, intent
        except (ValueError, TypeError, ValidationError, RecursionError):
            raise VideoProtocolError() from None

    def load(self, local_id) -> JournalRecord:
        with self.lock:
            return self._read(local_id)[0]

    def prepare(
        self, local_id: str, account_id: str, intent: VideoIntent, quote: VideoQuote
    ) -> JournalRecord:
        account_uuid(account_id)
        folder = self._folder(local_id)
        if (
            quote.account_id != account_id
            or quote.model != intent.model
            or quote.frames != intent.frames
            or type(quote.frames) is not int
            or quote.fps != intent.fps
            or type(quote.fps) is not int
            or type(quote.cost_micro) is not int
            or quote.cost_micro != intent.max_cost_micro_usd
            or quote.balance_sufficient is not True
        ):
            raise VideoProtocolError()
        body = intent.body()
        proposed = JournalRecord(
            version=1,
            local_id=local_id,
            account_id=account_id,
            request_key=str(uuid4()),
            intent_hash=intent.request_hash(),
            body_hash=hashlib.sha256(body).hexdigest(),
            state="prepared",
            rejected_status=None,
            receipt=None,
        )
        with self.lock:
            self._private(self.directory, directory=True)
            if folder.exists():
                existing, _ = self._read(local_id)
                if (
                    existing.account_id != account_id
                    or existing.intent_hash != proposed.intent_hash
                ):
                    raise JournalConflict()
                return existing
            for path in self.directory.iterdir():
                if (
                    re.fullmatch(r"[0-9a-f]{32}", path.name)
                    and self._read(path.name)[0].active
                ):
                    raise JournalConflict()
            temporary = Path(tempfile.mkdtemp(prefix=".preparing-", dir=self.directory))
            try:
                self._write(temporary / "body.json", body)
                self._write(
                    temporary / "record.json",
                    proposed.model_dump_json(by_alias=True).encode(),
                )
                temporary.rename(folder)
                descriptor = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            return proposed

    @staticmethod
    def _owner(record, grant):
        if record.account_id != grant.account_id:
            raise JournalConflict()

    def _accept(self, local_id, receipt):
        with self.lock:
            current, intent = self._read(local_id)
            receipt.bind(
                intent_hash=current.intent_hash,
                model=intent.model,
                ceiling=intent.max_cost_micro_usd,
                seed=intent.seed,
            )
            if current.receipt is not None:
                # An earlier poll may return after a terminal result was saved.
                if current.receipt.terminal and not receipt.terminal:
                    if (
                        receipt.job_id,
                        receipt.request_hash,
                        receipt.model,
                        receipt.reserved_micro,
                        receipt.max_cost_micro,
                    ) != (
                        current.receipt.job_id,
                        current.receipt.request_hash,
                        current.receipt.model,
                        current.receipt.reserved_micro,
                        current.receipt.max_cost_micro,
                    ):
                        raise VideoProtocolError()
                    return current
                receipt.follows(current.receipt)
            accepted = JournalRecord.model_validate(
                {
                    **current.model_dump(by_alias=True),
                    "state": "accepted",
                    "receipt": receipt,
                    "rejected_status": None,
                }
            )
            self._save(accepted)
            return accepted

    def dispatch(
        self, local_id: str, grant: TokenGrant, client: CoreVideoClient
    ) -> JournalRecord:
        with self.lock:
            record, intent = self._read(local_id)
            self._owner(record, grant)
            if record.state == "prepared":
                claimed = JournalRecord.model_validate(
                    {**record.model_dump(by_alias=True), "state": "attempted"}
                )
                self._save(claimed)
            else:
                claimed = None
        if claimed is None:
            return self.recover(local_id, grant, client)
        quote = VideoQuote(
            record.account_id,
            intent.model,
            intent.frames,
            intent.fps,
            intent.max_cost_micro_usd,
            True,
        )
        try:
            receipt = client.submit(grant, intent, quote, record.request_key)
        except VideoRejected as error:
            with self.lock:
                current, _ = self._read(local_id)
                if current.state == "attempted":
                    rejected = JournalRecord.model_validate(
                        {
                            **current.model_dump(by_alias=True),
                            "state": "rejected",
                            "rejected_status": error.status,
                        }
                    )
                    self._save(rejected)
            raise
        return self._accept(local_id, receipt)

    def recover(
        self, local_id: str, grant: TokenGrant, client: CoreVideoClient
    ) -> JournalRecord:
        with self.lock:
            record, intent = self._read(local_id)
            self._owner(record, grant)
        if record.state in ("prepared", "rejected", "cancelled") or (
            record.receipt is not None and record.receipt.terminal
        ):
            return record
        found = client.recover(
            grant,
            intent=intent,
            **(
                {"job_id": record.receipt.job_id, "previous": record.receipt}
                if record.receipt is not None
                else {"key": record.request_key}
            ),
        )
        return record if found is None else self._accept(local_id, found)

    def cancel_prepared(self, local_id: str, grant: TokenGrant) -> JournalRecord:
        with self.lock:
            record, _ = self._read(local_id)
            self._owner(record, grant)
            if record.state != "prepared":
                raise JournalConflict()
            cancelled = JournalRecord.model_validate(
                {**record.model_dump(by_alias=True), "state": "cancelled"}
            )
            self._save(cancelled)
            return cancelled
